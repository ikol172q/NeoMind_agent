"""Scheduler job — auto-sync REAL IBKR fills into the trade journal.

After the US cash close — and after ``ibkr_flex_sync`` (22:00 UTC) lands the
authoritative day's trades in ``ibkr_log`` — reconcile the journal: any OPEN
entry whose symbol is no longer an IBKR position is auto-closed using the
most-recent SELL fill from the durable archive. This makes the whole trading
process leave an automatic paper trail — no manual marking, no zombie open
entries — and revives the kill-switch's consecutive-loss signal for the real
account.

Depends on ``ibkr_log`` being populated by ``ibkr_snapshot`` (live, today-only)
and ``ibkr_flex_sync`` (authoritative backstop). If IBKR is disconnected or no
SELL fills are on record, it honestly closes 0 — it never fabricates an exit.

Cron: ``30 22 * * 1-5`` (22:30 UTC weekdays, right after ibkr_flex_sync so the
authoritative fills are already in the archive). The task's example 16:30 would
fire mid-session in the UTC scheduler; 22:30 honors the "after close" intent.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from agent.finance.persistence import connect, dao, ensure_schema

logger = logging.getLogger(__name__)

JOB_NAME = "journal_sync_daily"
DEFAULT_CRON = "30 22 * * 1-5"
DESCRIPTION = (
    "Weekday after-close reconcile of the trade journal against real IBKR "
    "fills (durable ibkr_log) — auto-closes open entries whose position left "
    "the book, using the archived SELL as the exit. Runs after ibkr_flex_sync; "
    "honest 0 when IBKR is disconnected or no sell fills are on record."
)


async def run() -> Dict[str, Any]:
    ensure_schema()
    with connect() as conn:
        run_id = dao.start_analysis_run(conn, job_name=JOB_NAME, run_type="scheduled")

    summary: Dict[str, Any] = {"run_id": run_id, "status": "running"}
    try:
        from agent.finance.trading_desk import _journal_sync_ibkr
        res = _journal_sync_ibkr()
        summary.update({"status": "completed", "closed": res.get("closed"),
                        "note": res.get("note"), "venue": res.get("venue")})
        logger.info("[journal_sync_daily] closed=%s note=%s",
                    res.get("closed"), res.get("note"))
    except Exception as exc:
        logger.exception("journal_sync_daily job failed")
        summary.update({"status": "failed", "error": str(exc)})
    finally:
        with connect() as conn:
            dao.finish_analysis_run(conn, run_id=run_id,
                                    status=summary.get("status", "completed"),
                                    summary_json=summary)
    return summary
