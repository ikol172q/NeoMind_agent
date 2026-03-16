# agent/context_manager.py
import os
import json
from typing import List, Dict, Any, Optional, Tuple
import warnings

try:
    import tiktoken
    HAS_TIKTOKEN = True
except ImportError:
    HAS_TIKTOKEN = False
    tiktoken = None

from agent_config import agent_config


class ContextManager:
    """Manages conversation context including token counting and compression."""

    def __init__(self, conversation_history: List[Dict[str, str]]):
        self.conversation_history = conversation_history
        self._encoding = None
        self._initialize_encoding()

    def _initialize_encoding(self):
        """Initialize tiktoken encoding for LLM tokenization."""
        if not HAS_TIKTOKEN:
            self._encoding = None
            return

        # Models likely use cl100k_base (same as GPT-3.5/4)
        try:
            self._encoding = tiktoken.get_encoding("cl100k_base")
        except Exception as e:
            warnings.warn(f"Failed to load tiktoken encoding: {e}. Using fallback token estimation.")
            self._encoding = None

    def count_tokens(self, text: str) -> int:
        """
        Count tokens in a text string.

        Uses tiktoken if available, otherwise falls back to approximate estimation
        (4 characters per token).
        """
        if self._encoding is not None:
            return len(self._encoding.encode(text))
        # Fallback: approximate tokens as 4 characters per token
        # This is a rough estimate; actual tokenization varies
        return max(1, len(text) // 4)

    def count_message_tokens(self, message: Dict[str, str]) -> int:
        """Count tokens in a single message dict with role and content."""
        # Format as expected by API: role + content
        text = f"{message['role']}: {message['content']}"
        return self.count_tokens(text)

    def count_conversation_tokens(self, messages: Optional[List[Dict[str, str]]] = None) -> int:
        """Count total tokens in a list of messages (defaults to current history)."""
        if messages is None:
            messages = self.conversation_history
        total = 0
        for msg in messages:
            total += self.count_message_tokens(msg)
        return total

    def get_context_usage(self) -> Dict[str, Any]:
        """
        Get current context usage statistics.

        Returns:
            Dictionary with token counts, limits, and percentages.
        """
        total_tokens = self.count_conversation_tokens()
        max_context = agent_config.max_context_tokens
        warning_threshold = agent_config.context_warning_threshold
        break_threshold = agent_config.context_break_threshold

        warning_tokens = int(max_context * warning_threshold)
        break_tokens = int(max_context * break_threshold)

        return {
            "total_tokens": total_tokens,
            "max_context_tokens": max_context,
            "warning_threshold": warning_threshold,
            "break_threshold": break_threshold,
            "warning_tokens": warning_tokens,
            "break_tokens": break_tokens,
            "percent_used": total_tokens / max_context if max_context > 0 else 0.0,
            "is_near_limit": total_tokens >= warning_tokens,
            "is_over_break": total_tokens >= break_tokens,
        }

    def check_context_limit(self, additional_tokens: int = 0) -> Tuple[bool, Dict[str, Any]]:
        """
        Check if context is near or over limits.

        Args:
            additional_tokens: Tokens that will be added (e.g., completion tokens).

        Returns:
            (should_warn, stats) where should_warn is True if warning threshold exceeded.
        """
        stats = self.get_context_usage()
        total_with_additional = stats["total_tokens"] + additional_tokens
        max_context = stats["max_context_tokens"]

        # Check if exceeding max context (hard limit)
        if total_with_additional > max_context:
            return True, {**stats, "exceeds_max": True}

        # Check warning threshold
        if stats["is_near_limit"]:
            return True, {**stats, "exceeds_max": False}

        return False, stats

    def compress_history(self, strategy: Optional[str] = None) -> Dict[str, Any]:
        """
        Compress conversation history to reduce token count.

        Args:
            strategy: Compression strategy override.

        Returns:
            Dictionary with compression results.
        """
        strategy = strategy or agent_config.compression_strategy
        keep_system = agent_config.keep_system_messages
        keep_recent = agent_config.keep_recent_messages

        original_count = len(self.conversation_history)
        original_tokens = self.count_conversation_tokens()

        if strategy == "truncate":
            compressed = self._truncate_history(keep_system, keep_recent)
        elif strategy == "summarize":
            compressed = self._summarize_history(keep_system, keep_recent)
        else:
            raise ValueError(f"Unknown compression strategy: {strategy}")

        # Replace history with compressed version
        self.conversation_history[:] = compressed

        new_tokens = self.count_conversation_tokens()
        reduction = original_tokens - new_tokens

        return {
            "original_messages": original_count,
            "compressed_messages": len(compressed),
            "original_tokens": original_tokens,
            "compressed_tokens": new_tokens,
            "token_reduction": reduction,
            "strategy": strategy,
        }

    def _truncate_history(self, keep_system: bool, keep_recent: int) -> List[Dict[str, str]]:
        """
        Truncate history by keeping system messages and recent messages.

        Args:
            keep_system: Whether to keep all system messages.
            keep_recent: Number of recent messages to keep (including user/assistant).

        Returns:
            Compressed message list.
        """
        if not self.conversation_history:
            return []

        # Separate system messages
        system_messages = []
        other_messages = []

        for msg in self.conversation_history:
            if keep_system and msg["role"] == "system":
                system_messages.append(msg)
            else:
                other_messages.append(msg)

        # Keep most recent N other messages
        kept_other = other_messages[-keep_recent:] if keep_recent > 0 else []

        # Combine: system messages first, then recent other messages
        compressed = system_messages + kept_other

        # If compression would result in empty list, keep at least the last message
        if not compressed and self.conversation_history:
            compressed = [self.conversation_history[-1]]

        return compressed

    def _summarize_history(self, keep_system: bool, keep_recent: int) -> List[Dict[str, str]]:
        """
        Summarize old messages using AI (not yet implemented).

        For now, falls back to truncation.
        """
        warnings.warn("Summarization strategy not implemented yet. Using truncation.")
        return self._truncate_history(keep_system, keep_recent)

    def prompt_user_for_action(self, stats: Dict[str, Any]) -> str:
        """
        Prompt user for action when context limit is reached.

        Returns:
            User's choice: 'continue', 'compress', 'clear', or 'cancel'.
        """
        print(f"⚠️  Context limit warning:")
        print(f"   • Current tokens: {stats['total_tokens']} / {stats['max_context_tokens']} ({stats['percent_used']:.1%})")
        print(f"   • Warning threshold: {stats['warning_threshold']:.0%} ({stats['warning_tokens']} tokens)")
        print(f"   • Break threshold: {stats['break_threshold']:.0%} ({stats['break_tokens']} tokens)")

        if stats.get('exceeds_max', False):
            print("❌ Total tokens would exceed model's maximum context length.")

        print("\nOptions:")
        print("  1. Continue anyway (risk of API error)")
        print("  2. Compress history (remove old messages)")
        print("  3. Clear history and start fresh")
        print("  4. Cancel current operation")

        while True:
            try:
                choice = input("Enter choice (1-4): ").strip()
                if choice == "1":
                    return "continue"
                elif choice == "2":
                    return "compress"
                elif choice == "3":
                    return "clear"
                elif choice == "4":
                    return "cancel"
                else:
                    print("Invalid choice. Please enter 1, 2, 3, or 4.")
            except KeyboardInterrupt:
                return "cancel"

    def interactive_context_management(self, additional_tokens: int = 0) -> bool:
        """
        Interactive context management when limits are approached.

        Args:
            additional_tokens: Tokens that will be added.

        Returns:
            True if operation should proceed, False if cancelled.
        """
        should_warn, stats = self.check_context_limit(additional_tokens)

        if not should_warn:
            return True

        choice = self.prompt_user_for_action(stats)

        if choice == "continue":
            print("Continuing with current context...")
            return True
        elif choice == "compress":
            print("Compressing history...")
            result = self.compress_history()
            print(f"Compressed from {result['original_tokens']} to {result['compressed_tokens']} tokens (-{result['token_reduction']}).")
            # Re-check after compression
            should_warn, stats = self.check_context_limit(additional_tokens)
            if should_warn:
                print("Still near limit after compression.")
                # Recursive call (should terminate due to reduced tokens)
                return self.interactive_context_management(additional_tokens)
            return True
        elif choice == "clear":
            print("Clearing conversation history...")
            self.conversation_history.clear()
            # Add system prompt back if needed
            # (caller should handle re-adding system prompt)
            return True
        elif choice == "cancel":
            print("Operation cancelled.")
            return False
        else:
            # Should not happen
            return False