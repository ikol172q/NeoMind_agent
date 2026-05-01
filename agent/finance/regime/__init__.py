"""Regime pipeline — Tier 2/3 ingest, fingerprint computation, k-NN.

See ``docs/design/2026-04-29_strategy-pipeline-v2.md`` for architecture.
This package converts raw market data into a 5-bucket regime fingerprint
that the strategy scorer consumes.
"""
from agent.finance.regime.tiers import TIER2_ANCHORS, TIER3_SP500
from agent.finance.regime.fingerprint import (
    compute_fingerprint,
    fingerprint_for_date,
)
from agent.finance.regime.ingest import (
    ingest_yfinance_daily,
    backfill_history,
)
from agent.finance.regime.store import (
    upsert_raw_bars,
    upsert_fingerprint,
    get_fingerprint,
    list_fingerprints,
)

__all__ = [
    "TIER2_ANCHORS",
    "TIER3_SP500",
    "compute_fingerprint",
    "fingerprint_for_date",
    "ingest_yfinance_daily",
    "backfill_history",
    "upsert_raw_bars",
    "upsert_fingerprint",
    "get_fingerprint",
    "list_fingerprints",
]
