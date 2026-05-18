"""Daily strategy-signal snapshot.

Captures compile_strategy_signal output for every watchlist ticker into
the signal_snapshots table. After 3-6 months of daily ticks, this is
the historical sequence the vectorbt backtest needs to validate edge.

Runs after all the data-pulling scanners are done — 22:00 UTC.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict

from agent.finance.persistence import connect, dao, ensure_schema

logger = logging.getLogger(__name__)

JOB_NAME = "signal_snapshot_daily"
DEFAULT_CRON = "0 22 * * *"  # 22:00 UTC daily
DESCRIPTION = (
    "Daily snapshot of compile_strategy_signal for every watchlist "
    "ticker into signal_snapshots. After 3-6 months of daily ticks, "
    "this table provides the historical (date, combined_score) "
    "sequence needed for edge-validation backtests in vectorbt."
)


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def run() -> Dict[str, Any]:
    with connect() as conn:
        run_id = dao.start_analysis_run(
            conn, job_name=JOB_NAME, run_type="scheduled",
        )
    summary: Dict[str, Any] = {"run_id": run_id, "status": "running"}
    snap_date = _today()
    n_ok = n_skip = n_err = 0
    try:
        from agent.finance.strategy_signals import compile_strategy_signal
        ensure_schema()
        with connect() as conn:
            tickers = [r["ticker"] for r in conn.execute(
                "SELECT ticker FROM user_watchlist"
            ).fetchall()]
            # held but not in watchlist
            held_extra = [r["symbol"] for r in conn.execute(
                "SELECT DISTINCT symbol FROM tax_lots "
                "WHERE close_date IS NULL "
                "  AND symbol NOT IN (SELECT ticker FROM user_watchlist)"
            ).fetchall()]
            tickers = list(dict.fromkeys(tickers + held_extra))

            for t in tickers:
                try:
                    s = compile_strategy_signal(t)
                    if not s.get("data_complete"):
                        n_skip += 1
                        # still record but flag
                    conn.execute(
                        "INSERT OR REPLACE INTO signal_snapshots "
                        "(ticker, snapshot_date, combined, fundamental, "
                        " smart_money, technical, news_sentiment, "
                        " anchor_relevance, earnings_days, data_complete, "
                        " detail_json, created_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            t, snap_date,
                            s["scores"]["combined"],
                            s["scores"]["fundamental"],
                            s["scores"]["smart_money"],
                            s["scores"]["technical"],
                            s["scores"]["news_sentiment"],
                            s["scores"]["anchor_relevance"],
                            s["detail"]["earnings_proximity_days"],
                            1 if s["data_complete"] else 0,
                            json.dumps(s["detail"], ensure_ascii=False),
                            _now(),
                        ),
                    )
                    n_ok += 1
                except Exception as exc:
                    logger.warning("signal_snapshot for %s failed: %s", t, exc)
                    n_err += 1
        summary.update({
            "status":     "completed",
            "snapshot_date": snap_date,
            "n_tickers":  len(tickers),
            "n_ok":       n_ok,
            "n_skipped":  n_skip,
            "n_err":      n_err,
        })
        logger.info("[signal_snapshot_daily] %s: ok=%d skip=%d err=%d",
                    snap_date, n_ok, n_skip, n_err)
    except Exception as exc:
        logger.exception("signal_snapshot_daily failed")
        summary.update({"status": "failed", "error": str(exc)})

    with connect() as conn:
        dao.finish_analysis_run(
            conn, run_id=run_id,
            status=summary["status"],
            summary_json=summary,
        )
    return summary
