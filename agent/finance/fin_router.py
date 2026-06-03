"""fin_router — difficulty/intent routing for the fin agent harness.

Phase 1 of the Fin Harness Evolution Loop
(``plans/2026-06-01_fin-harness-evolution-loop.md``).

The fin agent used to hard-code ``deepseek-v4-flash`` for every message.
That wastes the frozen model's two big levers:

  - **flash vs pro**: pro (1.6T total / 49B active) is ~12x the price of
    flash (284B / 13B active) per token. Paying pro on a freshness lookup
    is waste; answering "should I trim META?" on flash is under-powered.
  - **reasoning_effort**: DeepSeek V4 exposes thinking budget via the
    ``reasoning_effort`` request field. Verified valid values (from the
    live API's own 400 message):  low / medium / high / max / xhigh.
    Both models *think by default* (return ``reasoning_content``); there
    is no "off" — ``low`` is the lightest.

Routing = test-time-compute allocation. We classify the user's *intent*
and map it to (model, reasoning_effort, max_tokens).

Policy (user choice 2026-06-02 — "平衡档" / balanced):
  - decision   (该不该买/卖/清仓/对冲/加减仓 …)  → pro  · high · 6000
  - synthesis  (为什么/对比/分析/自上次变了啥 …)   → pro  · high · 6000
  - lookup     (取数/freshness/单票查询/事实 …)     → flash· low  · 2000

Rule-based + zero added latency (no classifier round-trip). Intent
priority: decision > synthesis > lookup (an actionable question that also
asks "why" is still a decision). The structure leaves room for a learned
router later (cost_optimizer success-rate history) without changing call
sites — that was the rejected "让它自己学" option.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

# Models served by the local router (verified via /v1/models).
MODEL_PRO = "deepseek-v4-pro"
MODEL_FLASH = "deepseek-v4-flash"

# Intent → policy. Tune here; everything downstream reads this table.
ROUTE_POLICY: Dict[str, Dict[str, Any]] = {
    "decision":  {"model": MODEL_PRO,   "reasoning_effort": "high", "max_tokens": 6000},
    "synthesis": {"model": MODEL_PRO,   "reasoning_effort": "high", "max_tokens": 6000},
    "lookup":    {"model": MODEL_FLASH, "reasoning_effort": "low",  "max_tokens": 2000},
}

# Actionable "should I move money" questions. Highest priority — these are
# the ones worth paying pro + heavy thinking for.
_DECISION_PATTERNS = [
    r"该不该", r"要不要", r"(应该|该)(买|卖|加|减|清|建|平|持)",
    r"买不买", r"卖不卖", r"加不加", r"减不减", r"能不能(买|卖)",
    r"值(不值)?得(买|入|加)", r"清仓", r"减仓", r"加仓", r"建仓",
    r"平仓", r"调仓", r"换仓", r"止损", r"止盈", r"对冲", r"套保",
    r"抄底", r"逃顶", r"进场", r"出场", r"加杠杆", r"要不要(买|卖|加|减|对冲)",
    r"\bshould i\b", r"\bbuy or sell\b", r"\b(hedge|rebalance)\b",
    r"\btake profit\b", r"\bstop[- ]?loss\b", r"\bcut (my|the)\b",
    r"\badd to (my|the)\b", r"\btrim\b", r"\bdump\b",
]

# Analysis / multi-source synthesis. Worth pro, but not "place an order".
_SYNTHESIS_PATTERNS = [
    r"为什么", r"为何", r"怎么看", r"如何看", r"怎么样", r"怎样",
    r"分析", r"对比", r"比较", r"自上次", r"变了", r"变化", r"综合",
    r"解释", r"影响", r"传导", r"怎么办", r"看法", r"评估", r"复盘",
    r"利弊", r"逻辑", r"前景", r"展望", r"风险(在|有|是)", r"如何理解",
    r"\bwhy\b", r"\bcompare\b", r"\bvs\.?\b", r"\bversus\b",
    r"what changed", r"\banaly(ze|sis)\b", r"\bexplain\b", r"\bimpact\b",
    r"\boutlook\b", r"\bthesis\b", r"pros and cons", r"walk me through",
    r"break ?down", r"how do you see",
]

_DECISION_RE = re.compile("|".join(_DECISION_PATTERNS), re.IGNORECASE)
_SYNTHESIS_RE = re.compile("|".join(_SYNTHESIS_PATTERNS), re.IGNORECASE)


def classify(query: str) -> str:
    """Return the intent bucket: 'decision' | 'synthesis' | 'lookup'."""
    q = query or ""
    if _DECISION_RE.search(q):
        return "decision"
    if _SYNTHESIS_RE.search(q):
        return "synthesis"
    return "lookup"


def route(query: str, *, explicit_model: Optional[str] = None) -> Dict[str, Any]:
    """Pick (model, reasoning_effort, max_tokens) for a user query.

    Args:
        query: the user's message.
        explicit_model: if the caller forced a model (e.g. via ``/model``),
            honour it but still classify intent to pick a sensible effort
            (pro → high, flash → low) and max_tokens.

    Returns:
        ``{"intent", "model", "reasoning_effort", "max_tokens", "reason"}``
        — all JSON-serializable so it can be logged into an episode.
    """
    intent = classify(query)
    policy = ROUTE_POLICY[intent]

    if explicit_model:
        is_pro = "pro" in explicit_model.lower()
        return {
            "intent": intent,
            "model": explicit_model,
            "reasoning_effort": "high" if is_pro else "low",
            "max_tokens": 6000 if is_pro else 2000,
            "reason": f"intent={intent}; explicit model override={explicit_model}",
        }

    return {
        "intent": intent,
        "model": policy["model"],
        "reasoning_effort": policy["reasoning_effort"],
        "max_tokens": policy["max_tokens"],
        "reason": f"intent={intent} → {policy['model']}/{policy['reasoning_effort']}",
    }
