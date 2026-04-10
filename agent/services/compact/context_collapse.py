"""
Context Collapse — Staged progressive compaction.

Instead of a single full compact, this module progressively reduces
context in stages as usage increases:
  85%: Collapse old tool results into 1-line summaries
  90%: Collapse old assistant messages into bullet summaries
  95%: Trigger full compact

This runs BETWEEN micro-compact and full compact in the compaction pipeline.
"""

import logging
from typing import List, Tuple

from .context_compactor import CompactMessage, MessageRole, PreservePolicy

logger = logging.getLogger(__name__)


class ContextCollapser:
    """Staged progressive context reduction.

    Usage:
        collapser = ContextCollapser(max_tokens=128000, preserve_recent=5)
        messages, freed = collapser.collapse(messages)
    """

    def __init__(self, max_tokens: int = 128000, preserve_recent: int = 5):
        self.max_tokens = max_tokens
        self.preserve_recent = preserve_recent

    def _usage_ratio(self, messages: List[CompactMessage]) -> float:
        total = sum(m.token_count for m in messages)
        return total / self.max_tokens if self.max_tokens > 0 else 0.0

    def should_collapse(self, messages: List[CompactMessage]) -> bool:
        """Check if context is at a level where collapse should run."""
        return self._usage_ratio(messages) >= 0.85

    def collapse(self, messages: List[CompactMessage]) -> Tuple[List[CompactMessage], int]:
        """Run staged collapse based on current usage.

        Returns:
            (collapsed_messages, tokens_freed)
        """
        ratio = self._usage_ratio(messages)
        original_tokens = sum(m.token_count for m in messages)

        if ratio < 0.85:
            return messages, 0

        # Find the boundary for recent messages
        user_indices = [i for i, m in enumerate(messages) if m.role == MessageRole.USER]
        recent_start = user_indices[-self.preserve_recent] if len(user_indices) >= self.preserve_recent else 0

        result = list(messages)

        if ratio >= 0.85:
            # Stage 1: Collapse old tool results into 1-line summaries
            result = self._collapse_old_tool_results(result, recent_start)

        if self._recalc_ratio(result) >= 0.90:
            # Stage 2: Collapse old assistant messages into bullet summaries
            result = self._collapse_old_assistant(result, recent_start)

        final_tokens = sum(m.token_count for m in result)
        freed = original_tokens - final_tokens

        if freed > 0:
            logger.info("Context collapse: freed %d tokens (%.1f%% → %.1f%%)",
                        freed, ratio * 100, self._recalc_ratio(result) * 100)

        return result, freed

    def _recalc_ratio(self, messages: List[CompactMessage]) -> float:
        total = sum(m.token_count for m in messages)
        return total / self.max_tokens if self.max_tokens > 0 else 0.0

    def _collapse_old_tool_results(self, messages: List[CompactMessage],
                                    recent_start: int) -> List[CompactMessage]:
        """Replace old tool results with 1-line summaries."""
        result = []
        for i, msg in enumerate(messages):
            if (i < recent_start and
                    msg.role == MessageRole.TOOL_RESULT and
                    msg.preserve == PreservePolicy.COMPRESSIBLE and
                    len(msg.content) > 200):
                # Collapse to first line + char count
                first_line = msg.content.split('\n')[0][:150]
                summary = f"[Collapsed tool result: {first_line}... ({len(msg.content)} chars)]"
                collapsed = CompactMessage(
                    role=msg.role,
                    content=summary,
                    token_count=len(summary) // 4,
                    preserve=msg.preserve,
                    metadata={**msg.metadata, 'collapsed': True},
                )
                result.append(collapsed)
            else:
                result.append(msg)
        return result

    def _collapse_old_assistant(self, messages: List[CompactMessage],
                                 recent_start: int) -> List[CompactMessage]:
        """Replace old assistant messages with bullet summaries."""
        result = []
        for i, msg in enumerate(messages):
            if (i < recent_start and
                    msg.role == MessageRole.ASSISTANT and
                    msg.preserve == PreservePolicy.COMPRESSIBLE and
                    len(msg.content) > 500):
                # Keep first 200 chars as bullet
                summary = msg.content[:200].replace('\n', ' ').strip()
                collapsed_content = f"[Summary: {summary}...]"
                collapsed = CompactMessage(
                    role=msg.role,
                    content=collapsed_content,
                    token_count=len(collapsed_content) // 4,
                    preserve=msg.preserve,
                    metadata={**msg.metadata, 'collapsed': True},
                )
                result.append(collapsed)
            else:
                result.append(msg)
        return result


def snip_messages(messages: List[CompactMessage],
                  indices_to_remove: List[int]) -> List[CompactMessage]:
    """Remove specific messages by index (snip).

    Returns a new list with the specified messages removed.
    """
    remove_set = set(indices_to_remove)
    return [m for i, m in enumerate(messages) if i not in remove_set]
