"""Extract named competitors from 10-K Item 1 + Item 1A text.

Inputs:
    competition_text — Item 1 → Competition subsection (may describe
                       competitors by category without naming them)
    risks_text       — Item 1A Risk Factors (often names competitors
                       in "we compete with X, Y, Z" phrasing)

Output: list of {name, evidence_quote} where evidence_quote is verbatim
from one of the inputs. The downstream validator drops any entry whose
quote can't be found in the provided source — so the LLM cannot
fabricate competitors and slip them past.

Returns the JOIN of both source texts so the validator can run a
single substring check.
"""
from __future__ import annotations

import logging
from typing import Optional

from agent.finance.extractors.base import call_strict_json
from agent.finance.extractors.validation import validate_quotes, ValidationOutcome

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a SEC filing analyst. Extract NAMED COMPANIES that the
filer describes as competitors, from the provided 10-K Item 1
(Business → Competition subsection) and Item 1A (Risk Factors)
text.

HARD RULES:
1. Only include companies that are NAMED IN THE SOURCE TEXT.
2. If the source describes competitors by category only ("companies
   that offer streaming devices") WITHOUT naming them, return an
   empty list. NEVER fill from your own knowledge.
3. Each entry's evidence_quote MUST be a substring copied verbatim
   from the source text — no paraphrasing, no abbreviating, no
   reformatting whitespace inside the quote. Include enough context
   (≥ 25 chars) that a reader can locate it.
4. The same company mentioned multiple times → one entry, with the
   most informative quote.
5. Do NOT include the filer itself.
6. Do NOT include partners, customers, or suppliers — only entities
   the filer says compete with them.
"""

_JSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["competitors"],
    "properties": {
        "competitors": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "evidence_quote"],
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Company name as it appears in the filing"
                    },
                    "ticker": {
                        "type": ["string", "null"],
                        "description": "Stock ticker if you are confident, else null"
                    },
                    "evidence_quote": {
                        "type": "string",
                        "description": "Verbatim substring from source text (≥25 chars)"
                    },
                },
            },
        },
    },
}


def extract_competitors(
    competition_text: Optional[str],
    risks_text: Optional[str],
) -> tuple[list[dict], ValidationOutcome]:
    """Run the LLM extractor + verbatim validator.

    Returns (verified_competitors, validation_outcome). The outcome
    object includes dropped items and reasons for diagnostics.
    """
    parts: list[str] = []
    if competition_text:
        parts.append("=== ITEM 1 — COMPETITION SUBSECTION ===\n" + competition_text)
    if risks_text:
        parts.append("=== ITEM 1A — RISK FACTORS ===\n" + risks_text)
    if not parts:
        return [], ValidationOutcome([], [], 0)

    user_content = "\n\n".join(parts)
    # Truncate Risk Factors if combined size exceeds budget. Item 1A
    # alone can be 200KB; LLM context is fine but cost grows linearly.
    # 60K chars ≈ 15K tokens, plenty for naming competitors.
    if len(user_content) > 60_000:
        user_content = user_content[:60_000] + "\n[…truncated for length…]"

    # max_tokens budgets BOTH reasoning_tokens AND output. DeepSeek-v4
    # spends ~2-5K on reasoning before any output appears, plus the
    # JSON itself can be 1-3K when the filing names many competitors
    # (NVDA names ~20). 16K is a safe cap that doesn't blow the wallet.
    raw = call_strict_json(
        system_prompt=_SYSTEM_PROMPT,
        user_content=user_content,
        json_schema=_JSON_SCHEMA,
        schema_name="extract_competitors",
        max_tokens=16000,
    )
    items = raw.get("competitors") or []

    # Validate every item's quote is in the SOURCE TEXT we sent
    source_for_validation = "\n\n".join(filter(None, [competition_text, risks_text]))
    outcome = validate_quotes(items, source_for_validation)

    if outcome.dropped:
        logger.info("extract_competitors: dropped %d/%d (%s)",
                    len(outcome.dropped), outcome.n_total,
                    [r for _, r in outcome.dropped])

    return outcome.verified, outcome
