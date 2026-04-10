"""
Token Budget Manager for NeoMind.

Tracks token usage per turn and per session, enforces budgets,
and detects diminishing returns.

Features:
- Per-model token tracking (input, output)
- Tool result budget enforcement (auto-truncate large results)
- Diminishing returns detection (triggers wrap-up prompt)
- Session cost tracking
"""

import logging
from typing import Dict, Optional, Any

logger = logging.getLogger(__name__)


class TokenBudget:
    """Manages token budget for agentic loop iterations.

    Usage:
        budget = TokenBudget(max_context=128000, tool_result_max=3000)
        budget.record_usage(input_tokens=5000, output_tokens=1000)
        if budget.should_wrap_up():
            # Inject wrap-up prompt
    """

    def __init__(
        self,
        max_context_tokens: int = 128000,
        tool_result_max_chars: int = 3000,
        compact_threshold: float = 0.85,
        diminishing_threshold: int = 500,
    ):
        self.max_context = max_context_tokens
        self.tool_result_max_chars = tool_result_max_chars
        self.compact_threshold = compact_threshold
        self.diminishing_threshold = diminishing_threshold

        # Per-turn tracking
        self._turn_input_tokens = 0
        self._turn_output_tokens = 0
        self._turn_tool_results_chars = 0

        # Session tracking
        self._session_input_tokens = 0
        self._session_output_tokens = 0
        self._session_cost_usd = 0.0

        # Per-model tracking
        self._model_usage: Dict[str, Dict[str, int]] = {}

        # Diminishing returns detection
        self._previous_output_delta = 0
        self._consecutive_small_deltas = 0

    def record_usage(self, input_tokens: int = 0, output_tokens: int = 0,
                     model: str = None):
        """Record token usage for the current turn."""
        self._turn_input_tokens += input_tokens
        self._turn_output_tokens += output_tokens
        self._session_input_tokens += input_tokens
        self._session_output_tokens += output_tokens

        if model:
            if model not in self._model_usage:
                self._model_usage[model] = {'input': 0, 'output': 0}
            self._model_usage[model]['input'] += input_tokens
            self._model_usage[model]['output'] += output_tokens

        # Diminishing returns detection
        if output_tokens > 0:
            delta = output_tokens
            if delta < self.diminishing_threshold:
                self._consecutive_small_deltas += 1
            else:
                self._consecutive_small_deltas = 0
            self._previous_output_delta = delta

    def record_cost(self, cost_usd: float):
        """Record API cost."""
        self._session_cost_usd += cost_usd

    def apply_tool_result_budget(self, output: str) -> str:
        """Truncate tool result if it exceeds the budget.

        Returns the (possibly truncated) output string.
        """
        if len(output) <= self.tool_result_max_chars:
            self._turn_tool_results_chars += len(output)
            return output

        # Middle truncation — keep beginning and end
        keep = self.tool_result_max_chars // 2
        truncated = (
            output[:keep]
            + f"\n\n... [{len(output):,} chars, truncated to {self.tool_result_max_chars:,}] ...\n\n"
            + output[-keep:]
        )
        self._turn_tool_results_chars += len(truncated)
        return truncated

    def should_compact(self) -> bool:
        """Check if context usage exceeds compact threshold."""
        estimated_context = self._turn_input_tokens + self._turn_output_tokens
        return estimated_context >= int(self.max_context * self.compact_threshold)

    def should_wrap_up(self) -> bool:
        """Check if the model is producing diminishing returns.

        Returns True if the last 3+ outputs were very small (below threshold),
        suggesting the model is spinning without making progress.
        """
        return self._consecutive_small_deltas >= 3

    def new_turn(self):
        """Reset per-turn tracking for a new conversation turn."""
        self._turn_input_tokens = 0
        self._turn_output_tokens = 0
        self._turn_tool_results_chars = 0
        self._consecutive_small_deltas = 0

    @property
    def session_usage(self) -> Dict[str, Any]:
        """Return session-level usage statistics."""
        return {
            'total_input_tokens': self._session_input_tokens,
            'total_output_tokens': self._session_output_tokens,
            'total_tokens': self._session_input_tokens + self._session_output_tokens,
            'total_cost_usd': round(self._session_cost_usd, 4),
            'model_usage': dict(self._model_usage),
        }

    @property
    def turn_usage(self) -> Dict[str, int]:
        """Return current turn usage."""
        return {
            'input_tokens': self._turn_input_tokens,
            'output_tokens': self._turn_output_tokens,
            'tool_result_chars': self._turn_tool_results_chars,
        }

    def format_usage(self) -> str:
        """Format usage statistics for display."""
        usage = self.session_usage
        lines = [
            f"Session Tokens: {usage['total_tokens']:,} "
            f"(in: {usage['total_input_tokens']:,}, out: {usage['total_output_tokens']:,})",
        ]
        if usage['total_cost_usd'] > 0:
            lines.append(f"Session Cost: ${usage['total_cost_usd']:.4f}")
        if usage['model_usage']:
            for model, mu in usage['model_usage'].items():
                lines.append(f"  {model}: in={mu['input']:,}, out={mu['output']:,}")
        return "\n".join(lines)
