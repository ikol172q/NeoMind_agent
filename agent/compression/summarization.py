"""
Summarization compression strategy.

Uses LLM to summarize old messages while keeping recent messages intact.
"""

from typing import List, Dict, Any, Optional, Callable
from .base import CompressionStrategy, CompressionResult


class SummarizationStrategy(CompressionStrategy):
    """
    Summarization strategy: use LLM to summarize old messages.

    Requires a summarizer function that takes a list of messages and returns a summary.
    """

    def __init__(self, summarizer: Optional[Callable[[List[Dict[str, str]]], str]] = None):
        """
        Args:
            summarizer: Function that summarizes a list of messages.
                If None, uses a fallback truncation.
        """
        self.summarizer = summarizer

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

        # Separate system messages and recent messages
        system_messages = []
        recent_messages = []
        old_messages = []

        for msg in messages:
            if keep_system and msg["role"] == "system":
                system_messages.append(msg)
            else:
                # We'll decide later which are recent
                old_messages.append(msg)

        # Keep most recent N non-system messages
        if keep_recent > 0 and old_messages:
            recent_messages = old_messages[-keep_recent:]
            old_messages = old_messages[:-keep_recent]
        else:
            recent_messages = []
            # If keep_recent is 0, all non-system messages are old

        # Summarize old messages if we have a summarizer
        summary_message = None
        if old_messages and self.summarizer:
            try:
                summary_text = self.summarizer(old_messages)
                summary_message = {
                    "role": "system",
                    "content": f"Summary of previous conversation:\n{summary_text}"
                }
            except Exception as e:
                # If summarization fails, keep old messages as-is
                recent_messages = old_messages + recent_messages
                summary_message = None
        elif old_messages:
            # No summarizer available, keep old messages
            recent_messages = old_messages + recent_messages

        # Build compressed list
        compressed = system_messages.copy()
        if summary_message:
            compressed.append(summary_message)
        compressed.extend(recent_messages)

        # Ensure we don't return empty list
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
                "old_messages_summarized": len(old_messages) if summary_message else 0,
                "old_messages_kept": len(old_messages) if not summary_message else 0,
                "summary_included": summary_message is not None,
            }
        )

    @property
    def name(self) -> str:
        return "summarize"

    @property
    def description(self) -> str:
        return "Use LLM to summarize old messages while keeping recent messages intact."


def create_default_summarizer(api_key: str, model: str = "deepseek-chat"):
    """
    Create a default summarizer using DeepSeek API.

    Args:
        api_key: DeepSeek API key.
        model: Model to use for summarization.

    Returns:
        Callable that summarizes messages.
    """
    import requests
    import json

    def summarizer(messages: List[Dict[str, str]]) -> str:
        # Convert messages to a single prompt
        conversation_text = "\n".join(
            f"{msg['role']}: {msg['content']}" for msg in messages
        )

        prompt = f"""Please summarize the following conversation concisely, preserving key information, decisions, and action items.

Conversation:
{conversation_text}

Summary:"""

        try:
            response = requests.post(
                "https://api.deepseek.com/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 500
                },
                timeout=30
            )
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"].strip()
        except Exception as e:
            raise RuntimeError(f"Summarization failed: {e}") from e

    return summarizer