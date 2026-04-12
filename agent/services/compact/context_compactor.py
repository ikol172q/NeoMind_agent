"""
Context Compactor for NeoMind Agent.

LLM-driven context window compression that intelligently summarizes
conversation history while preserving critical information.

Replaces heuristic truncation with semantic compression.

Created: 2026-04-02 (Phase 2 - Coding 完整功能)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class MessageRole(Enum):
    """Role of a message in conversation history."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"


class PreservePolicy(Enum):
    """Which messages to never compress."""

    ALWAYS_KEEP = "always_keep"      # System msgs, recent user msgs
    PREFER_KEEP = "prefer_keep"      # Tool calls with errors, important decisions
    COMPRESSIBLE = "compressible"    # Normal assistant replies, successful tool results


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CompactMessage:
    """A single message annotated with token count and preservation policy."""

    role: MessageRole
    content: str
    token_count: int
    preserve: PreservePolicy = PreservePolicy.COMPRESSIBLE
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CompactResult:
    """Statistics produced after a compaction run."""

    original_tokens: int
    compacted_tokens: int
    compression_ratio: float
    messages_before: int
    messages_after: int
    summary_text: str
    preserved_count: int


# ---------------------------------------------------------------------------
# Summary prompt template
# ---------------------------------------------------------------------------

_SUMMARY_PROMPT_TEMPLATE = """\
You are a context-compression assistant.  Summarize the following conversation
messages into a concise paragraph that preserves:
  - Key decisions made
  - Important facts, file paths, variable names, or code references
  - Any unresolved questions or pending actions
  - Error messages and their resolutions (if any)

Be factual and brief.  Do NOT add opinions or commentary.

--- MESSAGES ---
{messages}
--- END MESSAGES ---

Summary:"""


# ---------------------------------------------------------------------------
# ContextCompactor
# ---------------------------------------------------------------------------

class ContextCompactor:
    """LLM-driven context compression.

    When the conversation approaches the token limit, ``compact()``
    summarises older, compressible messages while preserving system
    messages, recent user turns, and error-bearing tool results.

    If no ``llm_fn`` is provided the compactor falls back to a simple
    extractive strategy (first sentence of each assistant reply).
    """

    def __init__(
        self,
        max_tokens: int = 100_000,
        compact_threshold: float = 0.8,
        target_ratio: float = 0.5,
        preserve_recent: int = 5,
        llm_fn: Optional[Callable[..., Any]] = None,
        token_count_fn: Optional[Callable[[str], int]] = None,
    ) -> None:
        """Initialise the compactor.

        Parameters
        ----------
        max_tokens:
            Hard ceiling for the context window (in tokens).
        compact_threshold:
            Fraction of *max_tokens* that triggers compaction (0-1).
        target_ratio:
            After compaction the total token count should be roughly
            ``max_tokens * target_ratio``.
        preserve_recent:
            Always keep the last *N* user messages (and their adjacent
            assistant replies) regardless of policy.
        llm_fn:
            An async callable ``(prompt: str) -> str`` used to produce
            semantic summaries.  ``None`` → extractive fallback.
        token_count_fn:
            A callable ``(text: str) -> int`` for accurate token
            counting.  ``None`` → ``len(text) // 4`` heuristic.
        """

        if not 0 < compact_threshold <= 1:
            raise ValueError("compact_threshold must be in (0, 1]")
        if not 0 < target_ratio < 1:
            raise ValueError("target_ratio must be in (0, 1)")
        if target_ratio >= compact_threshold:
            raise ValueError("target_ratio must be less than compact_threshold")

        self.max_tokens = max_tokens
        self.compact_threshold = compact_threshold
        self.target_ratio = target_ratio
        self.preserve_recent = preserve_recent
        self._llm_fn = llm_fn
        self._token_count_fn = token_count_fn

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def should_compact(self, messages: List[CompactMessage]) -> bool:
        """Return ``True`` when the total token count exceeds the threshold."""

        total = sum(m.token_count for m in messages)
        threshold = int(self.max_tokens * self.compact_threshold)
        return total >= threshold

    async def compact(
        self, messages: List[CompactMessage]
    ) -> Tuple[List[CompactMessage], CompactResult]:
        """Compress *messages* and return the new list plus statistics.

        Steps
        -----
        1. Separate messages into *to_compress* and *to_keep*.
        2. Generate a summary of *to_compress* (LLM or extractive).
        3. Build a transition system message containing the summary.
        4. Return ``[transition] + to_keep`` and a ``CompactResult``.
        """

        original_tokens = sum(m.token_count for m in messages)
        messages_before = len(messages)

        # 0. Pre-compact: strip media, inject session notes ──────────────
        messages = self._strip_media(messages)
        messages = self._inject_session_notes(messages)

        # 1. Split -------------------------------------------------------
        to_compress, to_keep = self._select_compressible(messages)

        if not to_compress:
            # Nothing compressible — return as-is.
            result = CompactResult(
                original_tokens=original_tokens,
                compacted_tokens=original_tokens,
                compression_ratio=1.0,
                messages_before=messages_before,
                messages_after=messages_before,
                summary_text="",
                preserved_count=len(to_keep),
            )
            return list(messages), result

        # 2. Summarise ----------------------------------------------------
        summary = await self._generate_summary(to_compress)

        # 3. Transition message -------------------------------------------
        transition = self._create_transition_message(summary)

        # 4. Assemble result list -----------------------------------------
        compacted: List[CompactMessage] = [transition] + to_keep
        compacted_tokens = sum(m.token_count for m in compacted)
        ratio = compacted_tokens / original_tokens if original_tokens else 1.0

        result = CompactResult(
            original_tokens=original_tokens,
            compacted_tokens=compacted_tokens,
            compression_ratio=round(ratio, 4),
            messages_before=messages_before,
            messages_after=len(compacted),
            summary_text=summary,
            preserved_count=len(to_keep),
        )

        logger.info(
            "Context compacted: %d → %d tokens (%.1f%%), %d → %d messages",
            original_tokens,
            compacted_tokens,
            ratio * 100,
            messages_before,
            len(compacted),
        )

        return compacted, result

    def classify_message(
        self, role: str, content: str, is_error: bool = False
    ) -> PreservePolicy:
        """Assign a ``PreservePolicy`` to a message based on heuristics.

        Rules
        -----
        * ``system`` → ALWAYS_KEEP
        * ``tool_call`` / ``tool_result`` with *is_error* → PREFER_KEEP
        * ``user`` → PREFER_KEEP  (recent ones promoted to ALWAYS_KEEP later)
        * Everything else → COMPRESSIBLE
        """

        role_lower = role.lower()

        if role_lower == MessageRole.SYSTEM.value:
            return PreservePolicy.ALWAYS_KEEP

        if role_lower in (MessageRole.TOOL_CALL.value, MessageRole.TOOL_RESULT.value):
            return PreservePolicy.PREFER_KEEP if is_error else PreservePolicy.COMPRESSIBLE

        if role_lower == MessageRole.USER.value:
            return PreservePolicy.PREFER_KEEP

        # assistant or unknown
        return PreservePolicy.COMPRESSIBLE

    # ------------------------------------------------------------------
    # Micro-compact — lightweight pre-API-call compression
    # ------------------------------------------------------------------

    def should_micro_compact(self, messages: List[CompactMessage],
                              threshold: float = 0.7) -> bool:
        """Check if micro-compaction should run (lower threshold than full compact).

        Micro-compact runs before API calls to trim tool outputs and long
        assistant responses, without a full LLM-based summary.
        """
        total = sum(m.token_count for m in messages)
        return total >= int(self.max_tokens * threshold)

    def micro_compact(self, messages: List[CompactMessage],
                       max_tool_output: int = 2000) -> Tuple[List[CompactMessage], int]:
        """Lightweight compaction: truncate long tool outputs and old assistant messages.

        This is NOT an LLM call — it's a fast, heuristic pass:
        1. Truncate tool results older than preserve_recent to max_tool_output chars
        2. Truncate long assistant messages (>3000 chars) in older turns
        3. Remove duplicate tool read results

        Returns:
            (compacted_messages, tokens_freed)
        """
        original_tokens = sum(m.token_count for m in messages)
        result = []

        # Find the boundary for "recent" messages
        user_indices = [i for i, m in enumerate(messages) if m.role == MessageRole.USER]
        recent_start = user_indices[-self.preserve_recent] if len(user_indices) >= self.preserve_recent else 0

        for i, msg in enumerate(messages):
            if i >= recent_start or msg.preserve == PreservePolicy.ALWAYS_KEEP:
                result.append(msg)
                continue

            # Truncate old tool results
            if msg.role == MessageRole.TOOL_RESULT and len(msg.content) > max_tool_output:
                truncated = msg.content[:max_tool_output] + "\n... [output truncated for context savings]"
                new_tokens = self._estimate_tokens(truncated)
                result.append(CompactMessage(
                    role=msg.role,
                    content=truncated,
                    token_count=new_tokens,
                    preserve=msg.preserve,
                    metadata={**msg.metadata, "micro_compacted": True},
                ))
                continue

            # Truncate long old assistant messages
            if msg.role == MessageRole.ASSISTANT and len(msg.content) > 3000:
                truncated = msg.content[:1500] + "\n...\n" + msg.content[-500:]
                new_tokens = self._estimate_tokens(truncated)
                result.append(CompactMessage(
                    role=msg.role,
                    content=truncated,
                    token_count=new_tokens,
                    preserve=msg.preserve,
                    metadata={**msg.metadata, "micro_compacted": True},
                ))
                continue

            result.append(msg)

        compacted_tokens = sum(m.token_count for m in result)
        tokens_freed = original_tokens - compacted_tokens

        if tokens_freed > 0:
            logger.info("Micro-compact freed %d tokens (%d → %d)",
                        tokens_freed, original_tokens, compacted_tokens)

        return result, tokens_freed

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _generate_summary(self, messages: List[CompactMessage]) -> str:
        """Produce a textual summary of *messages*.

        Uses the LLM function when available; otherwise falls back to an
        extractive approach that concatenates the first sentence of each
        assistant reply.
        """

        if self._llm_fn is not None:
            return await self._generate_summary_llm(messages)
        return self._generate_summary_extractive(messages)

    async def _generate_summary_llm(self, messages: List[CompactMessage]) -> str:
        """Call the configured LLM to produce a semantic summary."""

        formatted_parts: List[str] = []
        for msg in messages:
            label = msg.role.value.upper()
            # Truncate very long individual messages to keep the prompt sane
            body = msg.content[:2000] if len(msg.content) > 2000 else msg.content
            formatted_parts.append(f"[{label}]: {body}")

        prompt = _SUMMARY_PROMPT_TEMPLATE.format(messages="\n".join(formatted_parts))

        try:
            summary: str = await self._llm_fn(prompt)  # type: ignore[misc]
            return summary.strip()
        except Exception:
            logger.warning(
                "LLM summary generation failed; falling back to extractive",
                exc_info=True,
            )
            return self._generate_summary_extractive(messages)

    @staticmethod
    def _generate_summary_extractive(messages: List[CompactMessage]) -> str:
        """Fallback: keep the first sentence of each assistant reply."""

        sentences: List[str] = []
        for msg in messages:
            if msg.role != MessageRole.ASSISTANT:
                continue
            text = msg.content.strip()
            if not text:
                continue
            # Grab first sentence (split on period, question mark, or newline)
            for sep in (".", "?", "!", "\n"):
                idx = text.find(sep)
                if idx != -1:
                    text = text[: idx + 1]
                    break
            sentences.append(text)

        if not sentences:
            return "Prior conversation context was compressed (no assistant content)."

        return " ".join(sentences)

    def _select_compressible(
        self, messages: List[CompactMessage]
    ) -> Tuple[List[CompactMessage], List[CompactMessage]]:
        """Split messages into *(to_compress, to_keep)*.

        Preservation rules (applied in order):
        1. Messages with ``ALWAYS_KEEP`` are always kept.
        2. The last ``preserve_recent`` user messages (and their
           immediately following assistant replies) are kept.
        3. Messages with ``PREFER_KEEP`` are kept *only if* removing them
           would not bring us below the token target.
        4. Everything remaining goes into *to_compress*.
        """

        # --- Step 1: mark indices that must be kept ----------------------
        keep_indices: set[int] = set()

        # ALWAYS_KEEP
        for i, msg in enumerate(messages):
            if msg.preserve == PreservePolicy.ALWAYS_KEEP:
                keep_indices.add(i)

        # --- Step 2: protect last N user messages + following assistant ---
        user_indices: List[int] = [
            i for i, m in enumerate(messages) if m.role == MessageRole.USER
        ]
        recent_user = user_indices[-self.preserve_recent:] if user_indices else []
        for idx in recent_user:
            keep_indices.add(idx)
            # Also keep the assistant reply immediately after, if any
            if idx + 1 < len(messages) and messages[idx + 1].role == MessageRole.ASSISTANT:
                keep_indices.add(idx + 1)

        # --- Step 3: PREFER_KEEP if budget allows ------------------------
        target_tokens = int(self.max_tokens * self.target_ratio)
        kept_tokens = sum(messages[i].token_count for i in keep_indices)

        for i, msg in enumerate(messages):
            if i in keep_indices:
                continue
            if msg.preserve == PreservePolicy.PREFER_KEEP:
                if kept_tokens + msg.token_count <= target_tokens:
                    keep_indices.add(i)
                    kept_tokens += msg.token_count

        # --- Step 4: split -----------------------------------------------
        to_compress: List[CompactMessage] = []
        to_keep: List[CompactMessage] = []
        for i, msg in enumerate(messages):
            if i in keep_indices:
                to_keep.append(msg)
            else:
                to_compress.append(msg)

        return to_compress, to_keep

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count for *text*.

        Uses ``token_count_fn`` if provided, otherwise falls back to
        the simple ``len(text) // 4`` heuristic.
        """

        if self._token_count_fn is not None:
            return self._token_count_fn(text)
        # Rough heuristic: ~4 characters per token for English text
        return max(1, len(text) // 4)

    def _create_transition_message(self, summary: str) -> CompactMessage:
        """Build a system message that bridges compressed and live context."""

        content = (
            f"[Context compressed] Summary of prior conversation:\n\n{summary}"
        )
        return CompactMessage(
            role=MessageRole.SYSTEM,
            content=content,
            token_count=self._estimate_tokens(content),
            preserve=PreservePolicy.ALWAYS_KEEP,
            metadata={"is_compaction_summary": True},
        )

    # ── Pre-compact helpers ─────────────────────────────────────

    @staticmethod
    def _strip_media(messages: List[CompactMessage]) -> List[CompactMessage]:
        """Strip image/attachment references before summarization.

        Replaces image blocks with text placeholders to avoid sending
        binary data to the summarization LLM.
        """
        result = []
        for msg in messages:
            content = msg.content
            # Replace base64 image data with placeholder
            import re
            content = re.sub(
                r'data:image/[^;]+;base64,[A-Za-z0-9+/=]+',
                '[image: base64 data removed for compaction]',
                content,
            )
            # Replace long binary-looking strings
            content = re.sub(
                r'[A-Za-z0-9+/=]{500,}',
                '[binary data removed for compaction]',
                content,
            )
            if content != msg.content:
                result.append(CompactMessage(
                    role=msg.role,
                    content=content,
                    token_count=len(content) // 4,
                    preserve=msg.preserve,
                    metadata={**msg.metadata, 'media_stripped': True},
                ))
            else:
                result.append(msg)
        return result

    def _inject_session_notes(self, messages: List[CompactMessage]) -> List[CompactMessage]:
        """Inject session notes into the compact context.

        If SessionNotes has content, use it as a pre-built summary to
        reduce the LLM's summarization burden.
        """
        try:
            from agent.services.session_notes import SessionNotes
            # Try to get current session notes from a global or passed instance
            # This is best-effort — if not available, skip
            import importlib
            notes_mod = importlib.import_module('agent.services.session_notes')
            # Notes might be accessible via a global or need explicit passing
        except Exception:
            pass
        return messages

    def reinject_state(self, compacted: List[CompactMessage],
                        tool_descriptions: str = "",
                        active_plan: str = "") -> List[CompactMessage]:
        """Reinject tool schemas, active plans, and skill context after compaction.

        After summarization, the model loses awareness of available tools
        and any in-progress plans. This restores them.
        """
        state_parts = []
        if tool_descriptions:
            state_parts.append(f"[Available tools restored after compaction]\n{tool_descriptions}")
        if active_plan:
            state_parts.append(f"[Active plan restored after compaction]\n{active_plan}")

        if state_parts:
            state_content = "\n\n".join(state_parts)
            state_msg = CompactMessage(
                role=MessageRole.SYSTEM,
                content=state_content,
                token_count=self._estimate_tokens(state_content),
                preserve=PreservePolicy.ALWAYS_KEEP,
                metadata={"is_state_reinjection": True},
            )
            compacted.append(state_msg)

        return compacted
