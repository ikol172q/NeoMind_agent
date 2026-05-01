"""Scheduler job — daily yfinance ingest + fingerprint compute.

Runs once a day after US market close (default 21:30 UTC = 4:30 PM ET).
Pulls the last 5 days of bars (gives us safety margin if a previous day
was skipped due to outage), then computes today's fingerprint from the
fresh bars.

Manual rerun:
    python -m agent.finance.scheduler.runner --run-once regime_daily
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from agent.finance.persistence import connect, dao, ensure_schema

logger = logging.getLogger(__name__)


JOB_NAME = "regime_daily"
DEFAULT_CRON = "30 21 * * 1-5"   # 21:30 UTC weekdays = 4:30 PM ET (after US close)
DESCRIPTION = (
    "Daily: pull last 5 days of yfinance bars for the 3-tier watchlist "
    "(~480 symbols, ~5s) and compute today's regime fingerprint from "
    "the fresh data.  Powers the 5-bucket regime widget on the "
    "Research tab and feeds the strategy scorer."
)


async def run() -> Dict[str, Any]:
    ensure_schema()

    with connect() as conn:
        run_id = dao.start_analysis_run(
            conn, job_name=JOB_NAME, run_type="scheduled",
        )

    summary: Dict[str, Any] = {"run_id": run_id, "status": "running"}
    try:
        from agent.finance.regime.ingest import ingest_yfinance_daily
        from agent.finance.regime.fingerprint import fingerprint_for_date
        from datetime import date

        ingest_result = ingest_yfinance_daily(lookback_days=5)
        today = date.today().isoformat()
        fp = fingerprint_for_date(today, recompute=True)

        summary.update({
            "status": "completed",
            "ingest": ingest_result,
            "fingerprint_date": today,
            "fingerprint_scores": {
                "risk_appetite":     fp.get("risk_appetite_score"),
                "volatility_regime": fp.get("volatility_regime_score"),
                "breadth":           fp.get("breadth_score"),
                "event_density":     fp.get("event_density_score"),
                "flow":              fp.get("flow_score"),
            },
        })

        with connect() as conn:
            dao.complete_analysis_run(
                conn, run_id, status="completed",
                rows_written=ingest_result.get("n_rows_written", 0),
                metadata=summary,
            )
    except Exception as exc:
        logger.exception("regime_daily failed")
        summary["status"] = "failed"
        summary["error"] = str(exc)
        with connect() as conn:
            dao.complete_analysis_run(
                conn, run_id, status="failed",
                error_message=str(exc),
                metadata=summary,
            )

    return summary
