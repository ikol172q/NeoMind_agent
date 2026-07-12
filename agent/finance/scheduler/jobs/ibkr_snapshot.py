"""Scheduler job — IBKR durable archive snapshot.

Every few minutes during US market hours, pull the IBKR paper account's
account values / positions / open orders / today's fills and append them to
the local ``ibkr_log`` table. This is what makes the archive lossless: IBKR's
API only returns the CURRENT day's executions, so a fill that happens while
nothing is polling would be lost forever. Frequent snapshots guarantee every
fill is captured on the same UTC day it occurs.

Best-effort: if the Gateway isn't running it records a ``snapshot_error`` row
(never silent) and returns cleanly — it does not error the scheduler.

Cron: ``*/5 13-21 * * 1-5`` — every 5 min, 13:00–21:59 UTC weekdays
(~09:00–17:59 ET, covering pre-open through the cash close).
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from agent.finance.persistence import connect, dao, ensure_schema

logger = logging.getLogger(__name__)

JOB_NAME = "ibkr_snapshot"
DEFAULT_CRON = "*/5 13-21 * * 1-5"
DESCRIPTION = (
    "Every 5 min during US market hours: archive IBKR paper account / "
    "positions / open orders / today's fills into the durable ibkr_log so "
    "backtrace never loses a fill (IBKR API only returns the current day)."
)


async def run() -> Dict[str, Any]:
    ensure_schema()
    with connect() as conn:
        run_id = dao.start_analysis_run(conn, job_name=JOB_NAME, run_type="scheduled")

    summary: Dict[str, Any] = {"run_id": run_id, "status": "running"}
    try:
        from agent.finance.trading_desk import ibkr_snapshot
        res = ibkr_snapshot()
        summary.update({
            "status": "completed",
            "ok": res.get("ok"),
            "captured": res.get("captured"),
            "errors": res.get("errors"),
        })
        logger.info("[ibkr_snapshot] ok=%s captured=%s", res.get("ok"), res.get("captured"))
    except Exception as exc:
        logger.exception("ibkr_snapshot job failed")
        summary.update({"status": "failed", "error": str(exc)})
    finally:
        with connect() as conn:
            dao.finish_analysis_run(conn, run_id=run_id,
                                    status=summary.get("status", "completed"),
                                    summary_json=summary)
    return summary
