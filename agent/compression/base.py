"""
Base classes for compression strategies.
"""

import abc
from typing import List, Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class CompressionResult:
    """Result of compression operation."""
    compressed_messages: List[Dict[str, str]]
    original_token_count: int
    compressed_token_count: int
    strategy_used: str
    details: Dict[str, Any]


class CompressionStrategy(abc.ABC):
    """Abstract base class for compression strategies."""

    @abc.abstractmethod
    def compress(
        self,
        messages: List[Dict[str, str]],
        keep_system: bool = True,
        keep_recent: int = 5,
        **kwargs
    ) -> CompressionResult:
        """
        Compress a list of messages.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            keep_system: Whether to keep system messages.
            keep_recent: Number of recent non-system messages to keep.
            **kwargs: Strategy-specific parameters.

        Returns:
            CompressionResult with compressed messages and statistics.
        """
        pass

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Name of this compression strategy."""
        pass

    @property
    @abc.abstractmethod
    def description(self) -> str:
        """Description of this compression strategy."""
        pass

    def estimate_tokens(self, text: str) -> int:
        """
        Estimate token count for text.

        Args:
            text: Text to estimate.

        Returns:
            Estimated token count.
        """
        # Rough estimate: 4 characters per token
        return max(1, len(text) // 4)

    def count_message_tokens(self, message: Dict[str, str]) -> int:
        """Count tokens in a single message."""
        text = f"{message['role']}: {message['content']}"
        return self.estimate_tokens(text)

    def count_messages_tokens(self, messages: List[Dict[str, str]]) -> int:
        """Count total tokens in messages."""
        total = 0
        for msg in messages:
            total += self.count_message_tokens(msg)
        return total