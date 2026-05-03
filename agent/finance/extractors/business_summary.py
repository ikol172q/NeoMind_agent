"""Extract a 2-3 sentence business summary anchored to Item 1.

Pattern differs slightly from competitors / risks: the summary is
SYNTHESIZED (paraphrased) but each clause must be backed by a
verbatim quote from the source. We ask for an array of {sentence,
evidence_quote} pairs — the UI can stitch the sentences together
and show the supporting quote on hover.

This solves "LLM 训练记忆" for business summary: the LLM rephrases
real Item 1 prose rather than reciting from memory.
"""
from __future__ import annotations

import logging
from typing import Optional

from agent.finance.extractors.base import call_strict_json
from agent.finance.extractors.validation import validate_quotes, ValidationOutcome

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a SEC filing analyst. From the provided 10-K Item 1 Business
text, write a concise 2-3 sentence business summary.

Output structure: an ARRAY of sentences. Each entry is one sentence
of the summary plus a verbatim quote from Item 1 that supports it.

HARD RULES:
1. Each sentence is your synthesis (allowed to paraphrase / condense),
   BUT it must accurately reflect what the source says.
2. Each evidence_quote MUST be a verbatim substring of the source
   text (≥ 25 chars), drawn from a passage that supports your
   sentence. Multi-sentence quote is fine if needed.
3. 2-3 sentences total — first about WHAT the company does, second
   about HOW it makes money / segment mix, third (optional) about
   the current strategic narrative the filer emphasizes.
4. No marketing language. No filler ("the company is committed to…").
   Specific concrete content only.
5. If Item 1 doesn't disclose enough for one of the sentence types,
   skip that sentence — output 1 or 2 sentences instead of padding.
"""

_JSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["sentences"],
    "properties": {
        "sentences": {
            "type": "array",
            "minItems": 1,
            "maxItems": 3,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["sentence", "evidence_quote"],
                "properties": {
                    "sentence": {
                        "type": "string",
                        "description": "Synthesized 1-sentence summary clause"
                    },
                    "evidence_quote": {
                        "type": "string",
                        "description": "Verbatim Item 1 substring supporting the sentence (≥25 chars)"
                    },
                },
            },
        },
    },
}


def extract_business_summary(
    item1_text: Optional[str],
) -> tuple[list[dict], ValidationOutcome]:
    """LLM extract 2-3 sentence summary anchored to Item 1 + validate.

    item1_text is Item 1 (Business). Slicer hands us this directly.
    Truncate to 60K chars; the most-meaty business description
    (segments, products, strategy) is always early in the section.
    """
    if not item1_text:
        return [], ValidationOutcome([], [], 0)

    user_content = item1_text[:60_000]
    if len(item1_text) > 60_000:
        user_content += "\n[…truncated…]"

    raw = call_strict_json(
        system_prompt=_SYSTEM_PROMPT,
        user_content=user_content,
        json_schema=_JSON_SCHEMA,
        schema_name="extract_business_summary",
        max_tokens=10000,
    )
    items = raw.get("sentences") or []

    # Validate against the FULL item1_text (not the truncated input)
    # so the LLM can quote from anywhere in the section
    outcome = validate_quotes(items, item1_text)
    if outcome.dropped:
        logger.info("extract_business_summary: dropped %d/%d (%s)",
                    len(outcome.dropped), outcome.n_total,
                    [r for _, r in outcome.dropped])
    return outcome.verified, outcome
