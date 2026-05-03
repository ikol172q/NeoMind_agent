"""Verbatim-quote validation — the trust gate.

Every fact extracted by an LLM from a source document MUST come with
an ``evidence_quote`` string. This module checks (deterministically,
no AI involved) that the quote is a verbatim substring of the source
text. Items whose quote can't be verified are dropped.

Why this matters: prompt rules ("don't fabricate") are not enforceable
on LLM outputs. The only enforcement is post-hoc verification. If the
LLM made up a competitor that isn't in the 10-K, its quote won't be
found in the source — and we drop the entry.

A small amount of normalization is allowed (whitespace collapse,
case insensitivity) because LLMs paraphrase whitespace even when
they intend to quote verbatim. We do NOT normalize content (no
synonym matching, no fuzzy Levenshtein); the LLM must reproduce
the actual words.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

# Minimum quote length to verify. Shorter than this is too easy to
# find "by accident" in long documents and gives false confidence.
MIN_QUOTE_LEN = 25


def _normalize(s: str) -> str:
    """Lowercase + collapse all whitespace runs to single space.
    Strip non-text artifacts (bullet glyphs, smart quotes that LLMs
    sometimes substitute) but preserve everything else verbatim."""
    s = s.lower()
    # Smart quote → ASCII; SEC documents and LLMs disagree on these
    s = s.replace("“", '"').replace("”", '"')
    s = s.replace("‘", "'").replace("’", "'")
    s = s.replace("–", "-").replace("—", "-")
    s = s.replace("•", "")  # bullet
    s = s.replace(" ", " ")  # nbsp
    s = re.sub(r"\s+", " ", s)
    return s.strip()


@dataclass
class ValidationOutcome:
    verified: list[dict]            # passed quote check
    dropped: list[tuple[dict, str]] # (item, reason) for each rejected
    n_total: int

    @property
    def verification_rate(self) -> float:
        return (len(self.verified) / self.n_total) if self.n_total else 1.0

    def summary(self) -> str:
        return (f"{len(self.verified)}/{self.n_total} verified "
                f"({self.verification_rate*100:.0f}%)")


def validate_quotes(items: Iterable[dict[str, Any]],
                    source_text: str,
                    quote_field: str = "evidence_quote",
                    ) -> ValidationOutcome:
    """Drop any item whose ``evidence_quote`` is not a verbatim substring
    of ``source_text`` (after normalization).

    The verified-list preserves order and item shape. The dropped-list
    pairs each rejected item with a one-word reason for diagnosis.
    """
    items_list = list(items)
    verified: list[dict] = []
    dropped: list[tuple[dict, str]] = []

    norm_src = _normalize(source_text)

    for item in items_list:
        q = (item.get(quote_field) or "").strip()
        if not q:
            dropped.append((item, "missing"))
            continue
        if len(q) < MIN_QUOTE_LEN:
            dropped.append((item, "too_short"))
            continue
        norm_q = _normalize(q)
        if norm_q not in norm_src:
            dropped.append((item, "not_verbatim"))
            continue
        verified.append(item)

    return ValidationOutcome(
        verified=verified,
        dropped=dropped,
        n_total=len(items_list),
    )
