"""Route a provider's reported usage into cost accounting.

The Phase 2 gate requires that moving streaming behind `LLMPort` does not
orphan `/cost`. Today the numbers come from `code_commands.stream_response()`
calling `_query_engine.budget.record_usage(...)` from inside the SSE loop, so
extracting that loop would silently take the accounting with it.

This is the seam that stops it. `record_usage_chunk()` takes the `UsageChunk`
the adapter already yields and the pricing table, and writes to whatever
implements `UsageRecorderPort` — which the real `TokenBudget` satisfies
structurally, without inheriting anything.

One correctness note carried over deliberately. The baseline never used the
provider's numbers: it re-estimated both counts locally
(`context_manager.count_conversation_tokens()` for input,
`count_tokens(full_response)` for output) and billed those. The provider sends
exact counts in the final SSE frame. This function bills what the provider
said, which is why `prompt_tokens` here can differ from what `/cost` reported
for the same call before the migration — the new number is the accurate one.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Protocol, runtime_checkable

from agent.runtime.llm_stream import UsageChunk


@runtime_checkable
class UsageRecorderPort(Protocol):
    """What accounting needs. `agent.query_engine.TokenBudget` already fits."""

    def record_usage(
        self,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
    ) -> Any: ...


def cost_for(
    usage: UsageChunk,
    pricing: Optional[Mapping[str, Any]] = None,
) -> float:
    """Dollar cost for one call, from a per-million-token pricing entry.

    Mirrors the arithmetic in `code_commands`: prices are per 1M tokens, and an
    absent entry costs zero rather than raising — an unpriced model should
    still stream.
    """
    pricing = pricing or {}
    input_price = float(pricing.get("input", 0.0) or 0.0)
    output_price = float(pricing.get("output", 0.0) or 0.0)
    return (
        usage.prompt_tokens * input_price + usage.completion_tokens * output_price
    ) / 1_000_000


def record_usage_chunk(
    recorder: UsageRecorderPort,
    usage: UsageChunk,
    pricing: Optional[Mapping[str, Any]] = None,
) -> float:
    """Write one provider-reported usage into the budget. Returns the cost."""
    cost = cost_for(usage, pricing)
    recorder.record_usage(
        input_tokens=usage.prompt_tokens,
        output_tokens=usage.completion_tokens,
        cost_usd=cost,
    )
    return cost


def pricing_for_model(model: str) -> Mapping[str, Any]:
    """Look the model up in the same config table `code_commands` reads.

    Guarded: a missing or malformed cost table must not stop a turn.
    """
    try:
        from agent_config import agent_config

        table = agent_config._config.get("cost", {}).get("model_pricing", {})
        return table.get(model, {}) or {}
    except Exception:
        return {}
