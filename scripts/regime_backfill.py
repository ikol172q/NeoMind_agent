#!/usr/bin/env python
"""One-shot regime backfill — run on host with .venv-host (has yfinance).

Usage:
    .venv-host/bin/python scripts/regime_backfill.py [--period 1y] [--no-fingerprints]

After this:
  • SQLite has ~120 000 raw_market_data rows (480 symbols × 252 days)
  • SQLite has ~252 regime_fingerprints rows
  • Cron job 'regime_daily' takes over for incremental updates
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, timedelta


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--period", default="1y",
        help="yfinance period: 1mo / 3mo / 6mo / 1y / 2y / 5y / max (default: 1y)",
    )
    parser.add_argument(
        "--no-fingerprints", action="store_true",
        help="Skip fingerprint computation (just ingest raw bars)",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    log = logging.getLogger("regime_backfill")

    # 1) Ingest yfinance
    log.info("─── Step 1: yfinance ingest (period=%s) ───", args.period)
    t0 = time.monotonic()
    from agent.finance.regime.ingest import backfill_history
    ingest = backfill_history(period=args.period)
    elapsed = time.monotonic() - t0
    log.info(
        "ingest done in %.1fs · wrote %d rows for %d symbols (%d missing)",
        elapsed,
        ingest["n_rows_written"],
        ingest["n_symbols"],
        len(ingest["missing_symbols"]),
    )
    log.info(
        "coverage: min=%d max=%d avg=%.1f bars/symbol",
        ingest["coverage_min"], ingest["coverage_max"], ingest["coverage_avg"],
    )
    if ingest["missing_symbols"]:
        log.warning(
            "%d symbols had no data: %s",
            len(ingest["missing_symbols"]),
            ", ".join(ingest["missing_symbols"][:20]),
        )

    if args.no_fingerprints:
        log.info("skipping fingerprint compute (--no-fingerprints)")
        return 0

    # 2) Compute fingerprints for every trading day
    period_to_days = {
        "1mo": 31, "3mo": 92, "6mo": 183,
        "1y": 365, "2y": 730, "5y": 1826, "max": 3650,
    }
    days = period_to_days.get(args.period, 365)
    since = (date.today() - timedelta(days=days)).isoformat()

    log.info("─── Step 2: fingerprint compute since %s ───", since)
    t0 = time.monotonic()
    from agent.finance.regime.fingerprint import backfill_fingerprints
    fp = backfill_fingerprints(since=since, skip_existing=False)
    elapsed = time.monotonic() - t0
    log.info(
        "fingerprints done in %.1fs · written=%d skipped=%d failed=%d",
        elapsed, fp["written"], fp["skipped"], fp["failed"],
    )

    # 3) Sanity check
    from agent.finance.regime.store import list_fingerprints
    sample = list_fingerprints(limit=5)
    log.info("─── Latest 5 fingerprints ───")
    for s in sample:
        log.info(
            "%s · risk=%s vol=%s breadth=%s events=%s flow=%s",
            s["fingerprint_date"],
            s.get("risk_appetite_score"),
            s.get("volatility_regime_score"),
            s.get("breadth_score"),
            s.get("event_density_score"),
            s.get("flow_score"),
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
