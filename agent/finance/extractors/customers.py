"""Extract named major customers from 10-K Item 1 → Customers subsection.

SEC FRR 33 requires companies to disclose any single customer that
represents ≥10% of revenue (named or unnamed). The "Customers" or
"Customer Concentration" subsection is where these appear.

Many companies (B2C consumer brands like ROKU, AAPL) have no such
disclosure → no Customers subsection → slicer returns None →
extractor returns [] cleanly. This is honest behavior, not a bug.
"""
from __future__ import annotations

import logging
from typing import Optional

from agent.finance.extractors.base import call_strict_json
from agent.finance.extractors.validation import validate_quotes, ValidationOutcome

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a SEC filing analyst. From the provided 10-K Item 1 →
Customers subsection text, extract MAJOR CUSTOMERS that the filer
specifically discloses (typically ≥10% revenue concentration per
SEC FRR 33).

HARD RULES:
1. Only include customers NAMED in the source text (or named via
   common identifier like "our largest customer" if the source
   gives the percentage). If the section only describes the customer
   base in aggregate ("we serve consumers globally"), return [].
2. Each evidence_quote MUST be a verbatim substring (≥25 chars) of
   the source. Include enough surrounding context that a reader
   can verify.
3. concentration_pct is the numeric % the filer cites for that
   customer's share of revenue. Set to null if filer doesn't quantify.
4. Do NOT include the filer itself, suppliers, partners, or
   competitors — only entities that buy from / pay the filer.
"""

_JSON_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["customers"],
    "properties": {
        "customers": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["name", "evidence_quote"],
                "properties": {
                    "name": {"type": "string"},
                    "ticker": {"type": ["string", "null"]},
                    "concentration_pct": {"type": ["number", "null"]},
                    "evidence_quote": {"type": "string"},
                },
            },
        },
    },
}


def extract_customers(
    customers_text: Optional[str],
) -> tuple[list[dict], ValidationOutcome]:
    if not customers_text:
        return [], ValidationOutcome([], [], 0)
    user_content = customers_text[:60_000]
    raw = call_strict_json(
        system_prompt=_SYSTEM_PROMPT, user_content=user_content,
        json_schema=_JSON_SCHEMA, schema_name="extract_customers",
        max_tokens=8000,
    )
    items = raw.get("customers") or []
    outcome = validate_quotes(items, customers_text)
    if outcome.dropped:
        logger.info("extract_customers: dropped %d/%d (%s)",
                    len(outcome.dropped), outcome.n_total,
                    [r for _, r in outcome.dropped])
    return outcome.verified, outcome
