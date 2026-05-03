"""Extract revenue-by-segment from 10-K Item 7 MD&A.

Item 7 MD&A always contains the segment financial breakdown when
the company reports under ASC 280 (most public companies). The data
appears in tables like "Revenue by Segment" or "Net sales by
operating segment".

We ask the LLM to identify each segment with its current-period
revenue % share, and quote the source line that supports the number.
The validator drops any entry whose quote isn't in the MD&A — so
the LLM can't fabricate a segment that doesn't appear.
"""
from __future__ import annotations

import logging
from typing import Optional

from agent.finance.extractors.base import call_strict_json
from agent.finance.extractors.validation import validate_quotes, ValidationOutcome

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a SEC filing analyst. From the provided 10-K Item 7
(Management's Discussion and Analysis) text, extract the revenue
breakdown BY OPERATING SEGMENT for the most recent fiscal year.

HARD RULES:
1. Only emit segments whose name and revenue figure appear IN THE
   SOURCE TEXT. Do not infer.
2. Each evidence_quote MUST be a verbatim substring (≥25 chars)
   of the source. CRITICAL — when quoting a multi-column table row,
   include the ENTIRE row exactly as it appears (the source likely
   shows several fiscal years side-by-side; do NOT condense to just
   the most recent year). Copy the row character-for-character —
   the validator drops paraphrased or condensed quotes.
3. Prefer quoting from a sentence in the MD&A narrative ("Platform
   revenue was $X.X billion, or 87% of total net revenue") if such
   a sentence exists — it's easier to quote verbatim than table data.
4. revenue_pct: percentage of total company revenue (0-100), most
   recent fiscal year only. Set to null if unclear.
5. period: short label of the period (e.g. "FY2025"). Set to null
   if not stated.
6. If MD&A doesn't disclose segments (single-segment company),
   return [].
"""

_JSON_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["segments"],
    "properties": {
        "segments": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["name", "evidence_quote"],
                "properties": {
                    "name": {"type": "string"},
                    "revenue_pct": {"type": ["number", "null"]},
                    "period": {"type": ["string", "null"]},
                    "evidence_quote": {"type": "string"},
                },
            },
        },
    },
}


def extract_segments(
    item7_text: Optional[str],
) -> tuple[list[dict], ValidationOutcome]:
    if not item7_text:
        return [], ValidationOutcome([], [], 0)
    user_content = item7_text[:60_000]
    raw = call_strict_json(
        system_prompt=_SYSTEM_PROMPT, user_content=user_content,
        json_schema=_JSON_SCHEMA, schema_name="extract_segments",
        max_tokens=10000,
    )
    items = raw.get("segments") or []
    outcome = validate_quotes(items, item7_text)
    if outcome.dropped:
        logger.info("extract_segments: dropped %d/%d (%s)",
                    len(outcome.dropped), outcome.n_total,
                    [r for _, r in outcome.dropped])
    return outcome.verified, outcome
