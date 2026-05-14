"""Curated entity-name → US-tradable ticker lookup.

LLM extractions on 10-K filings often pull the legal entity name
("Taiwan Semiconductor Manufacturing Company Limited") without a
ticker symbol. This module normalizes those to ADRs/equivalent
listings the user can actually research and trade.

Used by:
  · tools/backfill_data.py auto_promote_adjacent — promote name-only
    competitor/customer/supplier facts to watchlist Adjacent tier.
  · agent/finance/lattice/portfolio_view.py chain endpoint — collapse
    external chain neighbors to their watchlist ticker counterparts
    so the onion+chain viz shows the right link target.

Conservative — only entries with a public US listing or major ADR.
Update by hand when a new entity surfaces.
"""
from __future__ import annotations

NAME_TO_TICKER: dict[str, str] = {
    # Semis / NVDA supply chain
    "taiwan semiconductor manufacturing company limited": "TSM",
    "taiwan semiconductor manufacturing company": "TSM",
    "taiwan semiconductor": "TSM",
    "tsmc": "TSM",
    "samsung electronics co., ltd.": "SSNLF",
    "samsung electronics": "SSNLF",
    "sk hynix inc.": "HXSCF",
    "sk hynix": "HXSCF",
    "micron technology, inc.": "MU",
    "micron technology": "MU",
    "micron": "MU",
    "hon hai precision industry co., ltd.": "HNHPF",
    "hon hai precision industry": "HNHPF",
    "hon hai": "HNHPF",
    "fabrinet": "FN",
    # Gaming / AAPL
    "nintendo": "NTDOY",
    "nintendo co., ltd.": "NTDOY",
    # Other commonly mentioned
    "advanced micro devices, inc.": "AMD",
    "advanced micro devices": "AMD",
    "alibaba group holding limited": "BABA",
    "alibaba": "BABA",
    "tencent": "TCEHY",
    "baidu, inc.": "BIDU",
    "baidu": "BIDU",
    "asml holding n.v.": "ASML",
    "asml": "ASML",
    "qualcomm incorporated": "QCOM",
    "qualcomm": "QCOM",
    "broadcom inc.": "AVGO",
    "broadcom": "AVGO",
    "international business machines corporation": "IBM",
    "oracle corporation": "ORCL",
    "oracle": "ORCL",
    "salesforce, inc.": "CRM",
    "salesforce": "CRM",
    "snowflake inc.": "SNOW",
    "snowflake": "SNOW",
    "palantir technologies inc.": "PLTR",
    "palantir": "PLTR",
    "snap inc.": "SNAP",
    "snap": "SNAP",
    "pinterest, inc.": "PINS",
    "pinterest": "PINS",
    "netflix, inc.": "NFLX",
    "netflix": "NFLX",
    "disney": "DIS",
    "the walt disney company": "DIS",
    "spotify technology s.a.": "SPOT",
    "spotify": "SPOT",
}


def name_to_ticker(name: str | None) -> str | None:
    """Look up a US-tradable ticker for a legal entity name. Returns
    None if unmapped. Tries exact lowercased match (with and without
    a single trailing period), then strips common corporate suffixes
    ('Inc.', 'Corp.', ', Inc.', ' N.V.', ' Co., Ltd.', ...)."""
    if not name:
        return None
    key = name.strip().lower()
    # Try with trailing period intact, then without.
    for candidate in (key, key.rstrip(".")):
        if candidate in NAME_TO_TICKER:
            return NAME_TO_TICKER[candidate]
    # Strip common corporate suffixes (with and without trailing period).
    for suf in (" inc.", " inc", " corporation", " corp.", " corp",
                " co., ltd.", " co., ltd", " company limited",
                ", inc.", ", inc", " n.v.", " s.a.", " ltd.", " ltd"):
        if key.endswith(suf):
            key2 = key[: -len(suf)].strip().rstrip(",.")
            if key2 in NAME_TO_TICKER:
                return NAME_TO_TICKER[key2]
    return None
