"""Synthesize a 1-line investment style verdict from already-anchored facts.

Unlike the other extractors (which extract FROM source text), this one
SYNTHESIZES from a structured bag of already-verified facts:
- live quote (price, PE, forward PE, 1y return, market cap)
- anchored business_summary sentences
- anchored risks (top categories)
- anchored segments (revenue mix)
- anchored competitor count

The LLM may paraphrase but must EXPLICITLY CITE specific numbers /
values from the input. The validator drops the verdict if any quoted
number isn't present in the input bag (substring check on the
serialized facts string).

Output: one short paragraph + a 1-line summary tag (e.g. "🟠 高估值
高增长 · 等待广告复苏"). Cited values must appear verbatim in the bag.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from agent.finance.extractors.base import call_strict_json
from agent.finance.extractors.validation import validate_quotes, ValidationOutcome

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You synthesize a one-paragraph investment style verdict from
already-verified facts about a company. Do NOT introduce numbers
or claims not present in the input.

Output JSON shape:
- "tag": short 1-line verdict (≤60 chars). May include 1 emoji
   (🟢 long-term hold candidate / 🟡 watch / 🟠 caution / 🔴 avoid).
- "paragraph": 2-4 sentences synthesizing the style perspective.
- "evidence_quote": a verbatim substring of the input (≥25 chars)
   containing the SPECIFIC NUMBER OR FACT your paragraph centers on.
   Pick the single most-load-bearing fact. The validator drops your
   verdict if this quote isn't a verbatim substring of input.

HARD RULES:
1. Every numeric claim in your paragraph MUST appear verbatim in the
   input (e.g. if you say "PE 91.5" the input must contain "91.5").
2. No vague language ("could be a good buy"). Concrete: "trades at
   91.5x trailing PE which is rich for a company with X risk".
3. If the input doesn't contain enough fact basis (e.g. only the
   live quote, no anchored facts), produce a tag like "🟡 数据不足
   待 SEC 10-K 抽取" and an empty paragraph. Better honest than
   making up.
"""

_JSON_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["tag", "paragraph", "evidence_quote"],
    "properties": {
        "tag": {"type": "string"},
        "paragraph": {"type": "string"},
        "evidence_quote": {"type": "string"},
    },
}


def _serialize_input_bag(
    *,
    ticker: str,
    live_quote: Optional[dict],
    business_summary: Optional[list[dict]],
    segments: Optional[list[dict]],
    risks: Optional[list[dict]],
    competitors_count: int = 0,
) -> str:
    """Build the input bag the LLM will see and the validator will
    cite-check against. The string format must be deterministic so
    the LLM's verbatim quote pattern matches."""
    parts: list[str] = [f"=== TICKER: {ticker} ==="]
    if live_quote:
        parts.append("=== LIVE QUOTE ===")
        for k, v in live_quote.items():
            if v is None:
                continue
            if isinstance(v, float):
                parts.append(f"{k}: {v:.4f}")
            else:
                parts.append(f"{k}: {v}")
    if business_summary:
        parts.append("=== BUSINESS SUMMARY (anchored) ===")
        for s in business_summary:
            parts.append(f"- {s.get('sentence','')}")
    if segments:
        parts.append("=== SEGMENTS (anchored) ===")
        for s in segments:
            pct = s.get('revenue_pct')
            parts.append(f"- {s.get('name')}: {pct}% of revenue")
    if risks:
        parts.append("=== RISKS (anchored) ===")
        for r in risks:
            parts.append(f"- [{r.get('category','?')}] {r.get('headline','')}")
    parts.append(f"=== COMPETITOR COUNT: {competitors_count} named in 10-K ===")
    return "\n".join(parts)


def synthesize_style_verdict(
    *,
    ticker: str,
    live_quote: Optional[dict],
    business_summary: Optional[list[dict]] = None,
    segments: Optional[list[dict]] = None,
    risks: Optional[list[dict]] = None,
    competitors_count: int = 0,
) -> tuple[Optional[dict], ValidationOutcome]:
    """Returns (verdict_or_None, ValidationOutcome).
    Verdict is None if the verbatim-quote check failed."""
    bag = _serialize_input_bag(
        ticker=ticker, live_quote=live_quote,
        business_summary=business_summary, segments=segments, risks=risks,
        competitors_count=competitors_count,
    )

    raw = call_strict_json(
        system_prompt=_SYSTEM_PROMPT,
        user_content=bag,
        json_schema=_JSON_SCHEMA,
        schema_name="style_verdict",
        max_tokens=4000,
    )
    items = [raw]  # validator works on lists; wrap single verdict
    outcome = validate_quotes(items, bag)
    if outcome.dropped:
        logger.info("style_verdict: dropped (claimed quote not in bag): %s",
                    [r for _, r in outcome.dropped])
        return None, outcome
    return outcome.verified[0] if outcome.verified else None, outcome
