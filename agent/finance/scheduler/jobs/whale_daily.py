"""Scheduler job — daily 13F whale scan (Phase L+).

13F filings drop quarterly with 45-day delay, so checking once daily
catches new ones reasonably quickly.  Scan takes ~30s due to SEC
EDGAR rate limiting (we sleep 0.5s between whales).

Cron: ``20 22 * * *`` (10:20 PM UTC daily, after EDGAR's nightly
processing)
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from agent.finance.persistence import connect, dao, ensure_schema

logger = logging.getLogger(__name__)


JOB_NAME = "whale_daily"
DEFAULT_CRON = "20 22 * * *"
DESCRIPTION = (
    "Daily: scan SEC EDGAR for new 13F-HR filings from 7 time-tested "
    "whales (Buffett, Druckenmiller, Tepper, Ackman, Klarman, Loeb, "
    "Marks); diff vs previous filing; emit signal_event for any "
    "ticker change in the user's watchlist + supply chain."
)


async def run() -> Dict[str, Any]:
    ensure_schema()

    with connect() as conn:
        run_id = dao.start_analysis_run(
            conn, job_name=JOB_NAME, run_type="scheduled",
        )

    summary: Dict[str, Any] = {"run_id": run_id, "status": "running"}
    try:
        from agent.finance.regime.scanners.whale_scanner import run_whale_scan
        from agent.finance.regime.signals import detect_confluences
        from agent.finance.agent_audit import audited_call

        # Wrap so 13F whale scanner shows as own entry in NeoMind Live
        # (agent_id="scanner:13f"), separate from this job's wrapper.
        result = audited_call(
            agent_id="scanner:13f",
            endpoint="scanner:13f",
            fn=run_whale_scan,
            extra_request={"job": JOB_NAME},
            summarize_result=lambda r: f"13F scan: {r.get('n_emitted', 0)} events across {r.get('n_whales', 0)} whales",
        )
        confluences = detect_confluences()
        summary.update({
            "status":          "completed",
            "scan":            result,
            "new_confluences": len(confluences),
        })
        logger.info("[whale_daily] emitted=%d new_confluences=%d",
                    result.get("n_emitted", 0), len(confluences))
    except Exception as exc:
        logger.exception("whale_daily failed")
        summary.update({"status": "failed", "error": str(exc)})
    finally:
        with connect() as conn:
            dao.finish_analysis_run(
                conn, run_id=run_id,
                status=summary["status"], summary_json=summary,
            )

    return summary
