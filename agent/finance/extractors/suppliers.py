"""Extract named key suppliers from 10-K Item 1 → Sources / Manufacturing.

The relevant subsection has many possible names ("Sources and
Availability of Materials", "Manufacturing", "Suppliers", "Supply
Chain"). Slicer tries them in order.

Many filings also disclose supplier concentration / single-source risk
in Item 1A — but for clarity we only consume the Item 1 subsection
here. Sole-source risks named in Item 1A are caught by extract_risks.
"""
from __future__ import annotations

import logging
from typing import Optional

from agent.finance.extractors.base import call_strict_json
from agent.finance.extractors.validation import validate_quotes, ValidationOutcome

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a SEC filing analyst. From the provided 10-K Item 1 →
Sources / Manufacturing / Suppliers subsection text, extract NAMED
KEY SUPPLIERS or sole-source dependencies.

HARD RULES:
1. Only include suppliers NAMED in the source text. If the section
   describes manufacturing in aggregate ("we use multiple contract
   manufacturers in Asia") without naming any, return [].
2. Each evidence_quote MUST be a verbatim substring (≥25 chars) of
   the source.
3. criticality is "sole_source" if the filer says "sole source",
   "single source", "only supplier"; "key" if the filer flags the
   supplier as material; "named" otherwise.
4. Do NOT include customers, partners, or distribution channels.
"""

_JSON_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["suppliers"],
    "properties": {
        "suppliers": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["name", "evidence_quote"],
                "properties": {
                    "name": {"type": "string"},
                    "ticker": {"type": ["string", "null"]},
                    "criticality": {"type": ["string", "null"]},
                    "evidence_quote": {"type": "string"},
                },
            },
        },
    },
}


def extract_suppliers(
    suppliers_text: Optional[str],
) -> tuple[list[dict], ValidationOutcome]:
    if not suppliers_text:
        return [], ValidationOutcome([], [], 0)
    user_content = suppliers_text[:60_000]
    raw = call_strict_json(
        system_prompt=_SYSTEM_PROMPT, user_content=user_content,
        json_schema=_JSON_SCHEMA, schema_name="extract_suppliers",
        max_tokens=8000,
    )
    items = raw.get("suppliers") or []
    outcome = validate_quotes(items, suppliers_text)
    if outcome.dropped:
        logger.info("extract_suppliers: dropped %d/%d (%s)",
                    len(outcome.dropped), outcome.n_total,
                    [r for _, r in outcome.dropped])
    return outcome.verified, outcome
