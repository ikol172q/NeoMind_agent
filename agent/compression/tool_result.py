"""
Tool result compression strategy.

Compresses large tool outputs by truncating or summarizing them.
"""

import re
from typing import List, Dict, Any, Optional
from .base import CompressionStrategy, CompressionResult


class ToolResultCompressionStrategy(CompressionStrategy):
    """
    Compresses tool results in messages.

    Looks for tool results (role: 'tool' or content containing tool output patterns)
    and compresses them if they exceed a size threshold.
    """

    def compress(
        self,
        messages: List[Dict[str, str]],
        keep_system: bool = True,
        keep_recent: int = 5,
        max_tool_output_length: int = 1000,
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

        compressed_messages = []
        tool_results_compressed = 0
        tool_results_total = 0

        for msg in messages:
            # Check if this is a tool result
            is_tool_result = (
                msg.get("role") == "tool" or
                "tool_call_id" in msg or
                self._looks_like_tool_output(msg["content"])
            )

            if is_tool_result:
                tool_results_total += 1
                compressed_content = self._compress_tool_output(
                    msg["content"],
                    max_length=max_tool_output_length
                )
                if compressed_content != msg["content"]:
                    tool_results_compressed += 1
                    # Create a new message with compressed content
                    compressed_msg = msg.copy()
                    compressed_msg["content"] = compressed_content
                    compressed_msg["compressed"] = True
                    compressed_messages.append(compressed_msg)
                else:
                    compressed_messages.append(msg)
            else:
                compressed_messages.append(msg)

        # Apply truncation to keep system and recent messages
        # (We can reuse TruncationStrategy here, but for simplicity we'll implement basic truncation)
        if keep_recent > 0 or keep_system:
            compressed_messages = self._apply_truncation(
                compressed_messages,
                keep_system=keep_system,
                keep_recent=keep_recent
            )

        original_tokens = self.count_messages_tokens(messages)
        compressed_tokens = self.count_messages_tokens(compressed_messages)

        return CompressionResult(
            compressed_messages=compressed_messages,
            original_token_count=original_tokens,
            compressed_token_count=compressed_tokens,
            strategy_used=self.name,
            details={
                "tool_results_total": tool_results_total,
                "tool_results_compressed": tool_results_compressed,
                "max_tool_output_length": max_tool_output_length,
            }
        )

    def _looks_like_tool_output(self, content: str) -> bool:
        """Heuristic to detect tool output."""
        # Check for common patterns
        patterns = [
            r"✅.*tool",
            r"❌.*tool",
            r"🔧.*tool",
            r"Executing tool:",
            r"Tool result:",
            r"Command output:",
            r"Search results:",
            r"File content:",
        ]
        content_lower = content.lower()
        for pattern in patterns:
            if re.search(pattern.lower(), content_lower):
                return True
        return False

    def _compress_tool_output(self, content: str, max_length: int = 1000) -> str:
        """Compress tool output by truncating if too long."""
        if len(content) <= max_length:
            return content

        # Try to find a good truncation point
        half = max_length // 2
        truncated = content[:half] + "\n\n...[output truncated]...\n\n" + content[-half:]
        return truncated

    def _apply_truncation(
        self,
        messages: List[Dict[str, str]],
        keep_system: bool,
        keep_recent: int
    ) -> List[Dict[str, str]]:
        """Apply basic truncation to keep system and recent messages."""
        if not messages:
            return []

        system_messages = []
        other_messages = []

        for msg in messages:
            if keep_system and msg.get("role") == "system":
                system_messages.append(msg)
            else:
                other_messages.append(msg)

        # Keep most recent N other messages
        kept_other = other_messages[-keep_recent:] if keep_recent > 0 else []

        # Combine
        compressed = system_messages + kept_other

        # If compression would result in empty list, keep at least the last message
        if not compressed and messages:
            compressed = [messages[-1]]

        return compressed

    @property
    def name(self) -> str:
        return "tool_result"

    @property
    def description(self) -> str:
        return "Compress large tool outputs by truncating or summarizing them."