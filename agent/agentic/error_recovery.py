"""
Multi-Stage Error Recovery Pipeline for NeoMind.

When the LLM call fails (context overflow, max output tokens, API errors),
this pipeline attempts recovery before surfacing the error to the user.

4-stage recovery hierarchy:
  Stage 1: Micro-compact — truncate old tool outputs
  Stage 2: Full compact — LLM-based conversation summarization
  Stage 3: Recovery message — inject synthetic message with instructions
  Stage 4: Surface error — show error to user with context

Errors are WITHHELD until all recovery stages are exhausted.
"""

import logging
from typing import Optional, Tuple, List, Dict, Any, Callable, Awaitable

logger = logging.getLogger(__name__)


class ErrorRecoveryPipeline:
    """Multi-stage error recovery for LLM calls.

    Usage:
        pipeline = ErrorRecoveryPipeline(compact_fn=my_compact, micro_compact_fn=my_micro)
        success, messages = await pipeline.recover(error, messages, llm_caller)
    """

    # Error types that trigger recovery
    RECOVERABLE_ERRORS = {
        'context_length_exceeded', 'prompt_too_long',
        'max_tokens_exceeded', 'max_output_tokens',
        'rate_limit', 'overloaded',
    }

    def __init__(
        self,
        compact_fn: Optional[Callable] = None,
        micro_compact_fn: Optional[Callable] = None,
        max_recovery_attempts: int = 3,
    ):
        self.compact_fn = compact_fn
        self.micro_compact_fn = micro_compact_fn
        self.max_recovery_attempts = max_recovery_attempts
        self._recovery_count = 0
        self._circuit_broken = False

    def classify_error(self, error: Exception) -> Optional[str]:
        """Classify an error into a recoverable category."""
        error_str = str(error).lower()
        if 'context' in error_str and ('length' in error_str or 'too long' in error_str):
            return 'context_length_exceeded'
        if 'prompt' in error_str and 'long' in error_str:
            return 'prompt_too_long'
        if 'max' in error_str and ('token' in error_str or 'output' in error_str):
            return 'max_tokens_exceeded'
        if 'rate' in error_str and 'limit' in error_str:
            return 'rate_limit'
        if 'overloaded' in error_str or '529' in error_str:
            return 'overloaded'
        return None

    def is_recoverable(self, error: Exception) -> bool:
        """Check if this error can be recovered from."""
        if self._circuit_broken:
            return False
        if self._recovery_count >= self.max_recovery_attempts:
            self._circuit_broken = True
            logger.warning("Error recovery circuit breaker tripped after %d attempts",
                           self._recovery_count)
            return False
        return self.classify_error(error) is not None

    async def recover(
        self,
        error: Exception,
        messages: List[Dict[str, Any]],
        llm_caller: Optional[Callable] = None,
    ) -> Tuple[bool, List[Dict[str, Any]], Optional[str]]:
        """Attempt multi-stage recovery from an LLM error.

        Returns:
            (recovered: bool, updated_messages: list, recovery_note: str or None)
        """
        error_type = self.classify_error(error)
        if not error_type:
            return False, messages, None

        self._recovery_count += 1
        logger.info("Error recovery attempt %d for: %s", self._recovery_count, error_type)

        # Stage 1: Micro-compact
        if error_type in ('context_length_exceeded', 'prompt_too_long'):
            if self.micro_compact_fn:
                try:
                    messages, tokens_freed = self.micro_compact_fn(messages)
                    if tokens_freed > 0:
                        logger.info("Stage 1 (micro-compact): freed %d tokens", tokens_freed)
                        return True, messages, f"Context reduced by ~{tokens_freed} tokens via micro-compact"
                except Exception as e:
                    logger.debug("Stage 1 failed: %s", e)

        # Stage 2: Full compact
        if error_type in ('context_length_exceeded', 'prompt_too_long'):
            if self.compact_fn:
                try:
                    messages = await self.compact_fn(messages)
                    logger.info("Stage 2 (full compact): conversation compacted")
                    return True, messages, "Conversation compacted to free context space"
                except Exception as e:
                    logger.debug("Stage 2 failed: %s", e)

        # Stage 3: Recovery message injection
        if error_type in ('context_length_exceeded', 'prompt_too_long', 'max_tokens_exceeded'):
            # Remove old messages aggressively (keep system + last 4)
            if len(messages) > 6:
                system_msgs = [m for m in messages if m.get('role') == 'system']
                recent = messages[-4:]
                recovery_msg = {
                    'role': 'system',
                    'content': (
                        "[Context recovered] Previous conversation was too long and has been "
                        "trimmed. Continue with the most recent context. If you were in the "
                        "middle of a task, summarize what you've done so far and what remains."
                    ),
                }
                messages = system_msgs + [recovery_msg] + recent
                logger.info("Stage 3 (recovery message): trimmed to %d messages", len(messages))
                return True, messages, "Context trimmed with recovery message"

        # Stage 4: Surface error (no recovery possible)
        logger.warning("All recovery stages exhausted for: %s", error_type)
        return False, messages, None

    @property
    def recovery_count(self) -> int:
        return self._recovery_count

    def reset(self):
        """Reset recovery state for a new conversation."""
        self._recovery_count = 0
        self._circuit_broken = False
