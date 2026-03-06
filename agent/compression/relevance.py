"""
Relevance filtering compression strategy.

Uses embeddings or keyword analysis to keep the most relevant messages.
"""

from typing import List, Dict, Any, Optional, Callable
from .base import CompressionStrategy, CompressionResult


class RelevanceFilteringStrategy(CompressionStrategy):
    """
    Relevance filtering: keep messages most relevant to recent context.

    Requires a relevance scorer function that scores each message's relevance.
    """

    def __init__(self, relevance_scorer: Optional[Callable[[Dict[str, str]], float]] = None):
        """
        Args:
            relevance_scorer: Function that scores a message's relevance (0-1).
                If None, uses a simple keyword-based fallback.
        """
        self.relevance_scorer = relevance_scorer

    def compress(
        self,
        messages: List[Dict[str, str]],
        keep_system: bool = True,
        keep_recent: int = 5,
        relevance_threshold: float = 0.3,
        **kwargs
    ) -> CompressionResult:
        if not messages:
            return CompressionResult(
                compressed_messages=[],
                original_token_count=0,
                compressed_token_count=0,
                strategy_used=self.name,
                details={"message": "Empty input"}
            )

        # Separate system messages
        system_messages = []
        other_messages = []

        for msg in messages:
            if keep_system and msg["role"] == "system":
                system_messages.append(msg)
            else:
                other_messages.append(msg)

        # Keep most recent N messages regardless of relevance
        recent_messages = []
        if keep_recent > 0 and other_messages:
            recent_messages = other_messages[-keep_recent:]
            other_messages = other_messages[:-keep_recent]

        # Score remaining messages for relevance
        scored_messages = []
        for msg in other_messages:
            if self.relevance_scorer:
                score = self.relevance_scorer(msg)
            else:
                score = self._fallback_relevance_score(msg, recent_messages)
            scored_messages.append((score, msg))

        # Keep messages above threshold
        relevant_messages = [
            msg for score, msg in scored_messages if score >= relevance_threshold
        ]

        # Combine: system messages first, then relevant messages, then recent messages
        compressed = system_messages + relevant_messages + recent_messages

        # If compression would result in empty list, keep at least the last message
        if not compressed and messages:
            compressed = [messages[-1]]

        original_tokens = self.count_messages_tokens(messages)
        compressed_tokens = self.count_messages_tokens(compressed)

        return CompressionResult(
            compressed_messages=compressed,
            original_token_count=original_tokens,
            compressed_token_count=compressed_tokens,
            strategy_used=self.name,
            details={
                "system_messages_kept": len(system_messages),
                "recent_messages_kept": len(recent_messages),
                "relevant_messages_kept": len(relevant_messages),
                "total_messages_scored": len(scored_messages),
                "relevance_threshold": relevance_threshold,
            }
        )

    def _fallback_relevance_score(
        self,
        message: Dict[str, str],
        recent_messages: List[Dict[str, str]]
    ) -> float:
        """
        Fallback relevance scoring based on keyword matching.

        Scores higher if message contains keywords that appear in recent messages.
        """
        if not recent_messages:
            return 0.2  # Default low score if no recent context

        # Extract keywords (simple word splitting)
        message_text = message["content"].lower()
        message_words = set(word for word in message_text.split() if len(word) > 3)

        # Collect words from recent messages
        recent_words = set()
        for recent_msg in recent_messages:
            recent_text = recent_msg["content"].lower()
            recent_words.update(word for word in recent_text.split() if len(word) > 3)

        # Calculate overlap
        if not message_words:
            return 0.1
        overlap = len(message_words & recent_words) / len(message_words)
        return min(overlap, 1.0)

    @property
    def name(self) -> str:
        return "relevance"

    @property
    def description(self) -> str:
        return "Keep messages most relevant to recent context using embeddings or keyword analysis."