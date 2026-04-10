"""NeoMind Query Engine — Central Turn Loop

Extracted from core.py to mirror Claude Code's QueryEngine.ts architecture.
Handles the complete message → LLM → tool → response cycle.

Architecture:
    QueryEngine owns:
        - Turn loop (message normalization → API call → tool dispatch → response)
        - Token budget tracking and auto-compaction triggers
        - Message history normalization
        - Streaming response assembly

    QueryEngine does NOT own:
        - Tool implementations (ToolRegistry)
        - Permission checks (PermissionManager)
        - UI rendering (frontends handle via events)
        - System prompt building (DynamicPromptComposer)

Usage:
    engine = QueryEngine(config, tool_registry, prompt_composer)
    async for event in engine.run_turn(user_message):
        handle(event)  # QueryEvent objects
"""

import asyncio
import logging
import time
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Optional, Dict, List, Any, AsyncIterator,
    Callable, Awaitable, Tuple, Union
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Events — frontend-agnostic, like Claude Code's message normalization
# ─────────────────────────────────────────────────────────────────────

class QueryEventType(Enum):
    """All event types the query engine can emit."""
    TURN_START = "turn_start"
    LLM_STREAM_START = "llm_stream_start"
    LLM_STREAM_DELTA = "llm_stream_delta"      # Incremental text chunk
    LLM_STREAM_END = "llm_stream_end"
    LLM_THINKING = "llm_thinking"               # Thinking/reasoning block
    TOOL_START = "tool_start"
    TOOL_PROGRESS = "tool_progress"             # Like Claude Code's BashProgress
    TOOL_RESULT = "tool_result"
    TOOL_ERROR = "tool_error"
    COMPACT_START = "compact_start"             # Context compaction triggered
    COMPACT_END = "compact_end"
    BUDGET_WARNING = "budget_warning"           # Token budget approaching limit
    TURN_END = "turn_end"
    ERROR = "error"


@dataclass
class QueryEvent:
    """Single event emitted during a query turn.

    Modeled after Claude Code's normalized message format.
    Frontends (CLI, Telegram, API) consume these uniformly.
    """
    type: QueryEventType
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def __repr__(self):
        return f"QueryEvent({self.type.value}, keys={list(self.data.keys())})"


# ─────────────────────────────────────────────────────────────────────
# Token Budget — mirrors Claude Code's per-turn budget tracking
# ─────────────────────────────────────────────────────────────────────

class TokenBudget:
    """Track token usage and trigger compaction when needed.

    Mirrors Claude Code's createBudgetTracker() pattern:
    - Tracks input/output tokens per turn and cumulative
    - Auto-triggers compaction at configurable threshold
    - Supports micro-compaction between turns

    Args:
        max_context_tokens: Maximum context window size
        warning_threshold: Fraction of max at which to warn (0.0-1.0)
        compact_threshold: Fraction of max at which to trigger compaction
    """

    def __init__(
        self,
        max_context_tokens: int = 131072,
        warning_threshold: float = 0.61,
        compact_threshold: float = 0.80,
    ):
        self.max_context_tokens = max_context_tokens
        self.warning_threshold = warning_threshold
        self.compact_threshold = compact_threshold

        # Running counters
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.turn_input_tokens: int = 0
        self.turn_output_tokens: int = 0
        self.turn_count: int = 0

        # Cost tracking (per-model pricing from config)
        self.total_cost_usd: float = 0.0
        self.turn_cost_usd: float = 0.0

        # State
        self._warning_emitted = False
        self._compact_triggered = False

    @property
    def estimated_usage(self) -> int:
        """Estimate current context window usage in tokens."""
        return self.total_input_tokens + self.total_output_tokens

    @property
    def usage_ratio(self) -> float:
        """Current usage as fraction of max context."""
        if self.max_context_tokens <= 0:
            return 0.0
        return self.estimated_usage / self.max_context_tokens

    def start_turn(self):
        """Reset per-turn counters at start of new turn."""
        self.turn_input_tokens = 0
        self.turn_output_tokens = 0
        self.turn_cost_usd = 0.0
        self.turn_count += 1
        self._warning_emitted = False

    def record_usage(
        self,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
    ):
        """Record token usage from an API call."""
        self.turn_input_tokens += input_tokens
        self.turn_output_tokens += output_tokens
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.turn_cost_usd += cost_usd
        self.total_cost_usd += cost_usd

    def should_warn(self) -> bool:
        """Check if we should emit a budget warning."""
        if self._warning_emitted:
            return False
        if self.usage_ratio >= self.warning_threshold:
            self._warning_emitted = True
            return True
        return False

    def should_compact(self) -> bool:
        """Check if we should trigger context compaction."""
        return self.usage_ratio >= self.compact_threshold

    def after_compact(self, tokens_freed: int):
        """Update counters after compaction."""
        self.total_input_tokens = max(0, self.total_input_tokens - tokens_freed)
        self._compact_triggered = False

    def get_summary(self) -> Dict[str, Any]:
        """Return a summary dict for display or logging."""
        return {
            "turn": self.turn_count,
            "turn_input": self.turn_input_tokens,
            "turn_output": self.turn_output_tokens,
            "total_input": self.total_input_tokens,
            "total_output": self.total_output_tokens,
            "usage_ratio": round(self.usage_ratio, 3),
            "total_cost_usd": round(self.total_cost_usd, 6),
            "turn_cost_usd": round(self.turn_cost_usd, 6),
        }


# ─────────────────────────────────────────────────────────────────────
# Message Normalizer — canonical format like Claude Code
# ─────────────────────────────────────────────────────────────────────

class MessageNormalizer:
    """Normalize messages to a canonical format for API calls.

    Like Claude Code's normalizeMessagesForAPI(), ensures all messages
    follow a consistent structure regardless of source (user, tool, system).
    """

    @staticmethod
    def normalize(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Normalize a message list for API consumption.

        Rules:
        - System messages stay at the front
        - Adjacent same-role messages get merged
        - Empty messages get filtered
        - Tool results get properly formatted
        """
        if not messages:
            return []

        normalized = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            # Skip empty messages
            if not content and not msg.get("tool_calls"):
                continue

            # Ensure content is string
            if isinstance(content, list):
                content = "\n".join(
                    block.get("text", str(block))
                    for block in content
                    if isinstance(block, dict)
                )

            normalized_msg = {
                "role": role,
                "content": content,
            }

            # Preserve tool_calls if present
            if "tool_calls" in msg:
                normalized_msg["tool_calls"] = msg["tool_calls"]

            # Merge adjacent same-role messages (except system)
            if (
                normalized
                and normalized[-1]["role"] == role
                and role != "system"
                and "tool_calls" not in normalized[-1]
                and "tool_calls" not in normalized_msg
            ):
                normalized[-1]["content"] += "\n\n" + content
            else:
                normalized.append(normalized_msg)

        return normalized

    @staticmethod
    def estimate_tokens(messages: List[Dict[str, Any]]) -> int:
        """Rough token estimation (4 chars ≈ 1 token).

        For accurate counting, integrate tiktoken or the model's tokenizer.
        This is a fast fallback like Claude Code uses for budget checks.
        """
        total_chars = sum(
            len(str(msg.get("content", "")))
            for msg in messages
        )
        # Add overhead for message structure (~4 tokens per message)
        overhead = len(messages) * 4
        return (total_chars // 4) + overhead


# ─────────────────────────────────────────────────────────────────────
# Context Compactor — LLM-powered compaction like Claude Code
# ─────────────────────────────────────────────────────────────────────

class ContextCompactor:
    """LLM-powered context compaction, replacing heuristic truncation.

    Mirrors Claude Code's compact/ service with two levels:
    1. Auto-compact: Full compaction when budget threshold hit
    2. Micro-compact: Incremental compression of old tool outputs

    Args:
        llm_caller: Async function that calls the LLM for summarization
        budget: TokenBudget instance for threshold checks
    """

    # Compact prompt templates
    COMPACT_SYSTEM_PROMPT = (
        "You are a conversation compactor. Summarize the conversation so far, "
        "preserving:\n"
        "1. All key decisions, facts, and user preferences\n"
        "2. Current task state and what has been done vs what remains\n"
        "3. Important file paths, code snippets, and technical details\n"
        "4. Any errors encountered and their resolutions\n\n"
        "Be concise but preserve critical context. Output ONLY the summary."
    )

    MICRO_COMPACT_PROMPT = (
        "Summarize this tool output in 2-3 sentences, preserving key data:\n\n{output}"
    )

    def __init__(
        self,
        llm_caller: Optional[Callable[..., Awaitable[str]]] = None,
        budget: Optional[TokenBudget] = None,
    ):
        self.llm_caller = llm_caller
        self.budget = budget
        self._compact_count = 0

    async def auto_compact(
        self,
        messages: List[Dict[str, Any]],
        keep_recent: int = 5,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Full compaction: summarize old messages, keep recent ones.

        Returns:
            (new_messages, tokens_freed) tuple
        """
        if len(messages) <= keep_recent + 1:  # +1 for system
            return messages, 0

        # Separate system messages and conversation
        system_msgs = [m for m in messages if m["role"] == "system"]
        conv_msgs = [m for m in messages if m["role"] != "system"]

        if len(conv_msgs) <= keep_recent:
            return messages, 0

        # Split: old messages to compact, recent to keep
        old_msgs = conv_msgs[:-keep_recent]
        recent_msgs = conv_msgs[-keep_recent:]

        # Estimate tokens before
        tokens_before = MessageNormalizer.estimate_tokens(old_msgs)

        if self.llm_caller:
            # LLM-powered compaction
            old_text = "\n\n".join(
                f"[{m['role']}]: {m['content'][:500]}"
                for m in old_msgs
            )
            try:
                summary = await self.llm_caller(
                    messages=[
                        {"role": "system", "content": self.COMPACT_SYSTEM_PROMPT},
                        {"role": "user", "content": f"Conversation to summarize:\n\n{old_text}"},
                    ],
                    max_tokens=1000,
                )
                compact_msg = {
                    "role": "system",
                    "content": (
                        f"# Context Summary (compacted from {len(old_msgs)} messages)\n\n"
                        f"{summary}\n\n"
                        f"---\n_[Conversation continues below]_"
                    ),
                }
            except Exception as e:
                logger.warning(f"LLM compaction failed, using heuristic: {e}")
                compact_msg = self._heuristic_compact(old_msgs)
        else:
            compact_msg = self._heuristic_compact(old_msgs)

        tokens_after = MessageNormalizer.estimate_tokens([compact_msg])
        tokens_freed = max(0, tokens_before - tokens_after)

        self._compact_count += 1

        # Rebuild: system + compact summary + recent
        new_messages = system_msgs + [compact_msg] + recent_msgs
        return new_messages, tokens_freed

    async def micro_compact(
        self,
        messages: List[Dict[str, Any]],
        max_tool_output_tokens: int = 500,
    ) -> List[Dict[str, Any]]:
        """Micro-compaction: compress large tool outputs in-place.

        Like Claude Code's microCompact, this targets tool results that
        are larger than needed for context, replacing them with summaries.
        """
        compacted = []
        for msg in messages:
            content = msg.get("content", "")
            # Only compress old assistant messages with tool results
            if (
                msg["role"] == "assistant"
                and len(content) > max_tool_output_tokens * 4  # rough char threshold
                and "<tool_result>" in content
            ):
                # Extract and compress tool results
                compacted_content = self._compress_tool_results(content, max_tool_output_tokens)
                compacted.append({**msg, "content": compacted_content})
            else:
                compacted.append(msg)
        return compacted

    def _heuristic_compact(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Fallback compaction when LLM is unavailable."""
        summary_parts = []
        for msg in messages:
            role = msg["role"]
            content = msg.get("content", "")
            # Keep first 100 chars of each message
            preview = content[:100].replace("\n", " ")
            if len(content) > 100:
                preview += "..."
            summary_parts.append(f"[{role}]: {preview}")

        return {
            "role": "system",
            "content": (
                f"# Context Summary (heuristic, {len(messages)} messages)\n\n"
                + "\n".join(summary_parts[-10:])  # Keep last 10 previews
                + "\n\n---\n_[Conversation continues below]_"
            ),
        }

    @staticmethod
    def _compress_tool_results(content: str, max_tokens: int) -> str:
        """Compress tool results within a message."""
        import re
        pattern = r"<tool_result>(.*?)</tool_result>"

        def replacer(match):
            result = match.group(1)
            if len(result) > max_tokens * 4:
                # Truncate with indicator
                truncated = result[:max_tokens * 4]
                return f"<tool_result>{truncated}\n...[truncated]</tool_result>"
            return match.group(0)

        return re.sub(pattern, replacer, content, flags=re.DOTALL)


# ─────────────────────────────────────────────────────────────────────
# QueryEngine — the main turn loop
# ─────────────────────────────────────────────────────────────────────

class QueryEngine:
    """Central query processing engine — one instance per session.

    Mirrors Claude Code's QueryEngine.ts: orchestrates the turn loop,
    manages token budget, triggers compaction, normalizes messages.

    This replaces the inline turn logic scattered in core.py.

    Args:
        tool_registry: ToolRegistry instance for tool execution
        prompt_composer: DynamicPromptComposer for system prompt building
        llm_caller: Async callable for LLM API calls
        config: AgentConfigManager instance
    """

    def __init__(
        self,
        tool_registry=None,
        prompt_composer=None,
        llm_caller: Optional[Callable[..., Awaitable]] = None,
        config=None,
    ):
        from agent_config import agent_config
        self.config = config or agent_config

        self.tool_registry = tool_registry
        self.prompt_composer = prompt_composer
        self.llm_caller = llm_caller

        # Token budget
        self.budget = TokenBudget(
            max_context_tokens=self.config.get("context.max_context_tokens", 131072),
            warning_threshold=self.config.get("context.warning_threshold", 0.61),
            compact_threshold=self.config.get("context.break_threshold", 0.80),
        )

        # Context compactor
        self.compactor = ContextCompactor(
            llm_caller=llm_caller,
            budget=self.budget,
        )

        # Message normalizer
        self.normalizer = MessageNormalizer()

        # Session state
        self.messages: List[Dict[str, Any]] = []
        self.turn_count: int = 0
        self._active = False

    def add_system_message(self, content: str):
        """Add a system message to the conversation."""
        self.messages.append({"role": "system", "content": content})

    def add_user_message(self, content: str):
        """Add a user message to the conversation."""
        self.messages.append({"role": "user", "content": content})

    def add_assistant_message(self, content: str):
        """Add an assistant message to the conversation."""
        self.messages.append({"role": "assistant", "content": content})

    async def run_turn(self, user_input: str) -> AsyncIterator[QueryEvent]:
        """Execute one complete turn: user message → LLM → tools → response.

        This is the heart of the engine. It:
        1. Normalizes messages
        2. Checks token budget
        3. Calls LLM (streaming)
        4. Dispatches tool calls
        5. Loops back to LLM if tools were called
        6. Yields events throughout

        Yields:
            QueryEvent objects for the frontend to consume
        """
        self._active = True
        self.turn_count += 1
        self.budget.start_turn()

        yield QueryEvent(
            type=QueryEventType.TURN_START,
            data={"turn": self.turn_count, "input_preview": user_input[:100]},
        )

        # Add user message
        self.add_user_message(user_input)

        # Check if compaction needed before LLM call
        if self.budget.should_compact():
            yield QueryEvent(type=QueryEventType.COMPACT_START)
            self.messages, tokens_freed = await self.compactor.auto_compact(
                self.messages,
                keep_recent=self.config.get("compact.keep_recent_turns", 5),
            )
            self.budget.after_compact(tokens_freed)
            yield QueryEvent(
                type=QueryEventType.COMPACT_END,
                data={"tokens_freed": tokens_freed},
            )

        # Tool execution loop (like Claude Code's turn loop)
        max_tool_rounds = 10  # Hard limit
        tool_round = 0

        while tool_round < max_tool_rounds and self._active:
            # Normalize messages for API
            api_messages = self.normalizer.normalize(self.messages)

            # Build system prompt (dynamic composition)
            if self.prompt_composer:
                system_prompt = self.prompt_composer.compose(
                    mode=self.config.mode,
                    tool_registry=self.tool_registry,
                    budget=self.budget,
                )
                # Replace or add system message
                if api_messages and api_messages[0]["role"] == "system":
                    api_messages[0]["content"] = system_prompt
                else:
                    api_messages.insert(0, {"role": "system", "content": system_prompt})

            # Budget warning
            if self.budget.should_warn():
                yield QueryEvent(
                    type=QueryEventType.BUDGET_WARNING,
                    data=self.budget.get_summary(),
                )

            # Call LLM
            yield QueryEvent(type=QueryEventType.LLM_STREAM_START)

            try:
                llm_response = ""
                thinking_content = ""

                if self.llm_caller:
                    # The llm_caller should handle streaming internally
                    # and return the complete response
                    result = await self.llm_caller(
                        messages=api_messages,
                        stream=True,
                    )

                    if isinstance(result, dict):
                        llm_response = result.get("content", "")
                        thinking_content = result.get("thinking", "")
                        usage = result.get("usage", {})
                        self.budget.record_usage(
                            input_tokens=usage.get("prompt_tokens", 0),
                            output_tokens=usage.get("completion_tokens", 0),
                        )
                    elif isinstance(result, str):
                        llm_response = result

                    if thinking_content:
                        yield QueryEvent(
                            type=QueryEventType.LLM_THINKING,
                            data={"content": thinking_content},
                        )

                    yield QueryEvent(
                        type=QueryEventType.LLM_STREAM_DELTA,
                        data={"content": llm_response},
                    )

                yield QueryEvent(type=QueryEventType.LLM_STREAM_END)

            except Exception as e:
                yield QueryEvent(
                    type=QueryEventType.ERROR,
                    data={"error": str(e), "phase": "llm_call"},
                )
                break

            # Add assistant response to history
            self.add_assistant_message(llm_response)

            # Check for tool calls
            if self.tool_registry:
                from agent.coding.tool_parser import ToolCallParser
                parser = ToolCallParser()
                tool_call = parser.parse(llm_response)

                if tool_call:
                    tool_round += 1

                    yield QueryEvent(
                        type=QueryEventType.TOOL_START,
                        data={
                            "tool": tool_call.tool_name,
                            "params": tool_call.params,
                            "round": tool_round,
                        },
                    )

                    # Execute tool
                    try:
                        tool_result = await self._execute_tool(tool_call)

                        yield QueryEvent(
                            type=QueryEventType.TOOL_RESULT,
                            data={
                                "tool": tool_call.tool_name,
                                "result": tool_result.output[:2000],  # Preview
                                "status": tool_result.status,
                                "full_length": len(tool_result.output),
                            },
                        )

                        # Add tool result to history for next LLM call
                        result_msg = (
                            f"<tool_result>\n"
                            f"tool: {tool_call.tool_name}\n"
                            f"status: {tool_result.status}\n"
                            f"output: |\n  {tool_result.output}\n"
                            f"</tool_result>"
                        )
                        self.messages.append({
                            "role": "user",
                            "content": result_msg,
                        })

                        # Micro-compact old tool outputs if needed
                        if self.budget.usage_ratio > 0.5:
                            self.messages = await self.compactor.micro_compact(
                                self.messages
                            )

                    except Exception as e:
                        error_msg = f"Tool execution error: {e}"
                        yield QueryEvent(
                            type=QueryEventType.TOOL_ERROR,
                            data={"tool": tool_call.tool_name, "error": error_msg},
                        )
                        # Feed error back to LLM
                        self.messages.append({
                            "role": "user",
                            "content": (
                                f"<tool_result>\n"
                                f"tool: {tool_call.tool_name}\n"
                                f"status: ERROR\n"
                                f"output: |\n  {error_msg}\n"
                                f"</tool_result>"
                            ),
                        })

                    # Continue loop for next LLM call with tool result
                    continue

            # No tool call — turn is complete
            break

        self._active = False
        yield QueryEvent(
            type=QueryEventType.TURN_END,
            data={
                "turn": self.turn_count,
                "tool_rounds": tool_round,
                "budget": self.budget.get_summary(),
            },
        )

    async def _execute_tool(self, tool_call) -> Any:
        """Execute a tool call through the registry.

        Handles permission checks and delegates to ToolRegistry.
        """
        if not self.tool_registry:
            raise RuntimeError("No tool registry configured")

        # The tool registry handles validation, permission, and execution
        result = await asyncio.to_thread(
            self.tool_registry.execute,
            tool_call.tool_name,
            tool_call.params,
        )
        return result

    async def compact_now(self) -> int:
        """Manually trigger compaction. Returns tokens freed."""
        self.messages, tokens_freed = await self.compactor.auto_compact(
            self.messages,
            keep_recent=self.config.get("compact.keep_recent_turns", 5),
        )
        self.budget.after_compact(tokens_freed)
        return tokens_freed

    def get_state(self) -> Dict[str, Any]:
        """Snapshot of engine state for debugging/display."""
        return {
            "turn_count": self.turn_count,
            "message_count": len(self.messages),
            "budget": self.budget.get_summary(),
            "compact_count": self.compactor._compact_count,
            "active": self._active,
        }
