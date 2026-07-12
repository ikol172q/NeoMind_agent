"""Extract debt / leverage crux facts from 10-K Item 7 MD&A.

The single most decision-relevant fact for a small-cap retail thesis is
usually the balance sheet's debt structure: how much is owed, at what
rate, and — above all — WHEN it matures (a near-term maturity wall on a
levered, cash-burning name is the difference between a value play and a
bankruptcy). This lives in Item 7 MD&A's "Liquidity and Capital
Resources" narrative and its "Contractual Obligations" table (maturity
buckets), plus any net-leverage / total-debt ratio the filer discloses.

We ask the LLM to pull each debt instrument (name, principal, rate,
maturity) and any stated leverage ratio, each with a verbatim
evidence_quote. The downstream validator drops anything whose quote
isn't literally in the MD&A — so the LLM cannot fabricate a maturity
date or a leverage figure and slip it past. Sparse > fabricated.
"""
from __future__ import annotations

import logging
from typing import Optional

from agent.finance.extractors.base import call_strict_json
from agent.finance.extractors.validation import validate_quotes, ValidationOutcome

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a SEC filing analyst. From the provided 10-K Item 7
(Management's Discussion and Analysis) text — focus on the
"Liquidity and Capital Resources" narrative and the "Contractual
Obligations" table — extract the company's DEBT and LEVERAGE facts.

Emit two kinds of items:
  - kind="instrument": one per named debt instrument (term loan,
    senior notes, revolving credit facility, convertible notes, etc.),
    with its principal/outstanding amount, interest rate, and maturity
    date/year when stated in the source.
  - kind="leverage": one per disclosed leverage or coverage metric
    (e.g. "net leverage ratio", "total debt", "net debt") with its value.

HARD RULES:
1. Only emit facts whose figures appear IN THE SOURCE TEXT. Never infer
   an amount, rate, maturity, or ratio from your own knowledge.
2. Each evidence_quote MUST be a verbatim substring (>=25 chars) copied
   character-for-character from the source. When quoting a table row
   (e.g. a Contractual Obligations maturity row), copy the ENTIRE row
   exactly as it appears — do not condense or reorder columns. The
   validator drops paraphrased or condensed quotes.
3. maturity: short label as stated ("2031", "March 2028", "due 2027").
   null if the source does not state it.
4. amount / rate: copy the figure as written ("$500.0 million",
   "3.875%"). null if not stated.
5. If the MD&A discloses no debt (debt-free company), return [].
"""

_JSON_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["debt"],
    "properties": {
        "debt": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["kind", "name", "evidence_quote"],
                "properties": {
                    "kind": {"type": "string",
                             "enum": ["instrument", "leverage"]},
                    "name": {"type": "string"},
                    "amount": {"type": ["string", "null"]},
                    "rate": {"type": ["string", "null"]},
                    "maturity": {"type": ["string", "null"]},
                    "evidence_quote": {"type": "string"},
                },
            },
        },
    },
}


def extract_debt(
    item7_text: Optional[str],
) -> tuple[list[dict], ValidationOutcome]:
    if not item7_text:
        return [], ValidationOutcome([], [], 0)
    user_content = item7_text[:60_000]
    raw = call_strict_json(
        system_prompt=_SYSTEM_PROMPT, user_content=user_content,
        json_schema=_JSON_SCHEMA, schema_name="extract_debt",
        max_tokens=10000,
    )
    items = raw.get("debt") or []
    outcome = validate_quotes(items, item7_text)
    if outcome.dropped:
        logger.info("extract_debt: dropped %d/%d (%s)",
                    len(outcome.dropped), outcome.n_total,
                    [r for _, r in outcome.dropped])
    return outcome.verified, outcome
