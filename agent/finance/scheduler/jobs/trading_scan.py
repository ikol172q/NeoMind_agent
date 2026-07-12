"""Scheduler job — short-term trading desk daily auto-scan.

Scans every ARMED setup (status paper/live) for entry triggers on the
latest bar and auto-places risk-sized paper orders + protective stops —
UNLESS the global halt is engaged. Runs the kill-switch check first
(auto-halts on a policy breach: drawdown / consecutive losses).

This is the automation backbone: the user doesn't click anything. The
only manual controls are the emergency brakes (global halt / flatten /
per-setup disarm) and resuming after a kill-switch trip.

Cron: ``30 21 * * 1-5`` (21:30 UTC weekdays, after the US cash close).
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from agent.finance.persistence import connect, dao, ensure_schema

logger = logging.getLogger(__name__)

JOB_NAME = "trading_scan"
DEFAULT_CRON = "30 21 * * 1-5"
DESCRIPTION = (
    "Daily weekday auto-scan of armed short-term setups → risk-sized paper "
    "entries (gated by global halt + kill-switch). The trading desk's "
    "automation backbone; manual controls are emergency brakes only."
)

_PROJECT = "fin-core"


async def run() -> Dict[str, Any]:
    ensure_schema()
    with connect() as conn:
        run_id = dao.start_analysis_run(conn, job_name=JOB_NAME, run_type="scheduled")

    summary: Dict[str, Any] = {"run_id": run_id, "status": "running"}
    try:
        # scan_and_trade refreshes positions first (settles stop/target/OCO),
        # then evaluates new entries.
        from agent.finance.trading_desk import scan_and_trade
        result = scan_and_trade(_PROJECT, auto_execute=True)
        summary.update({
            "status": "completed",
            "halted": result.get("halted"),
            "orders_settled": (result.get("refresh") or {}).get("orders_settled"),
            "n_triggers": result.get("n_triggers"),
            "n_executed": result.get("n_executed"),
            "kill_switch_breached": (result.get("kill_switch") or {}).get("breached"),
        })
        logger.info("[trading_scan] triggers=%s executed=%s halted=%s",
                    result.get("n_triggers"), result.get("n_executed"), result.get("halted"))
    except Exception as exc:
        logger.exception("trading_scan failed")
        summary.update({"status": "failed", "error": str(exc)})
    finally:
        with connect() as conn:
            dao.finish_analysis_run(conn, run_id=run_id,
                                    status=summary["status"], summary_json=summary)
    return summary
