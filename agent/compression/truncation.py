"""
Truncation compression strategy.

Keeps system messages and most recent messages, discarding older messages.
"""

from typing import List, Dict, Any
from .base import CompressionStrategy, CompressionResult


class TruncationStrategy(CompressionStrategy):
    """Truncation strategy: keep system messages and most recent messages."""

    def compress(
        self,
        messages: List[Dict[str, str]],
        keep_system: bool = True,
        keep_recent: int = 5,
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

        # Keep most recent N other messages
        kept_other = other_messages[-keep_recent:] if keep_recent > 0 else []

        # Combine: system messages first, then recent other messages
        compressed = system_messages + kept_other

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
                "recent_messages_kept": len(kept_other),
                "total_messages_original": len(messages),
                "total_messages_compressed": len(compressed),
            }
        )

    @property
    def name(self) -> str:
        return "truncate"

    @property
    def description(self) -> str:
        return "Keep system messages and most recent messages, discard older messages."