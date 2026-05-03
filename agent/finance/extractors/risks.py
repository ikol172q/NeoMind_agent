"""Extract top risks from 10-K Item 1A Risk Factors.

Item 1A is typically 50-200 pages of risk language the company itself
disclosed under penalty of perjury. We ask the LLM to identify the
N most material risks, each with a verbatim quote from the source.
The validator drops anything whose quote isn't in the actual filing.

This solves the "LLM 编 risks" problem from the original audit:
old behavior was the LLM emitting plausible-sounding risks
(e.g., "regulatory uncertainty", "supply chain disruption") that
weren't actually in the filing.
"""
from __future__ import annotations

import logging
from typing import Optional

from agent.finance.extractors.base import call_strict_json
from agent.finance.extractors.validation import validate_quotes, ValidationOutcome

logger = logging.getLogger(__name__)

DEFAULT_TOP_N = 5

_SYSTEM_PROMPT = """\
You are a SEC filing analyst. From the provided Item 1A (Risk Factors)
text, identify the {n} MOST MATERIAL risks the filer discloses.

HARD RULES:
1. Each risk must be drawn from a risk header / paragraph that ACTUALLY
   appears in the source text — no synthesis from general knowledge.
2. Each entry's evidence_quote MUST be a verbatim substring of the
   source text — no paraphrasing, no abbreviating. Include the
   risk header sentence and enough surrounding text (≥ 25 chars,
   prefer 80-200 chars) so the reader sees the company's own framing.
3. The "category" field is your single-word grouping
   ("operational" / "regulatory" / "financial" / "competitive" /
   "macro" / "litigation" / "cybersecurity" / "supply_chain" / etc.)
   — pick what fits, no enum constraint.
4. The "severity_signal" field is "high" only if the company itself
   uses language like "material adverse effect", "significant",
   "substantial harm". Otherwise "medium" by default. Never invent.
5. Pick the top {n} risks by importance to the company's stated
   business model. Skip generic boilerplate (cybersecurity warnings
   that any tech company has) unless the filer flags it as material.
"""

_JSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["risks"],
    "properties": {
        "risks": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["headline", "category", "evidence_quote"],
                "properties": {
                    "headline": {
                        "type": "string",
                        "description": "1-line summary of the risk in your own words"
                    },
                    "category": {
                        "type": "string",
                    },
                    "severity_signal": {
                        "type": ["string", "null"],
                    },
                    "evidence_quote": {
                        "type": "string",
                        "description": "Verbatim substring from Item 1A (≥25 chars)"
                    },
                },
            },
        },
    },
}


def extract_risks(
    risks_text: Optional[str],
    top_n: int = DEFAULT_TOP_N,
) -> tuple[list[dict], ValidationOutcome]:
    """LLM extract top-N risks from Item 1A + verbatim validate.

    Item 1A can be 200KB+ — DeepSeek-v4-flash has 128K context but cost
    grows linearly. We truncate to 80K chars (≈20K tokens), which still
    captures the entire risk section for any normal-sized 10-K.
    """
    if not risks_text:
        return [], ValidationOutcome([], [], 0)

    user_content = risks_text
    if len(user_content) > 80_000:
        user_content = user_content[:80_000] + "\n[…truncated for length…]"

    raw = call_strict_json(
        system_prompt=_SYSTEM_PROMPT.format(n=top_n),
        user_content=user_content,
        json_schema=_JSON_SCHEMA,
        schema_name="extract_risks",
        max_tokens=16000,
    )
    items = raw.get("risks") or []

    outcome = validate_quotes(items, risks_text)
    if outcome.dropped:
        logger.info("extract_risks: dropped %d/%d (%s)",
                    len(outcome.dropped), outcome.n_total,
                    [r for _, r in outcome.dropped])
    return outcome.verified, outcome
