"""Scheduler job — IBKR Flex Web Service daily sync (authoritative backstop).

Once a day after the US close, pull the official Flex statement (trades /
positions / cash) and archive it into ``ibkr_log``. Trades dedupe on IBKR's
tradeID, so this is the lossless catch-all: any fill the live snapshot missed
(e.g. Gateway was off) still lands here from IBKR's server-side record.

No-ops cleanly (records nothing) if Flex isn't configured yet.

Cron: ``0 22 * * 1-5`` (22:00 UTC weekdays, ~18:00 ET, after the cash close).
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from agent.finance.persistence import connect, dao, ensure_schema

logger = logging.getLogger(__name__)

JOB_NAME = "ibkr_flex_sync"
DEFAULT_CRON = "0 22 * * 1-5"
DESCRIPTION = (
    "Daily after-close pull of the IBKR Flex statement (trades/positions/cash) "
    "into ibkr_log — authoritative lossless backstop, deduped by tradeID."
)


async def run() -> Dict[str, Any]:
    ensure_schema()
    with connect() as conn:
        run_id = dao.start_analysis_run(conn, job_name=JOB_NAME, run_type="scheduled")

    summary: Dict[str, Any] = {"run_id": run_id, "status": "running"}
    try:
        from agent.finance.trading_desk import flex_sync, flex_config_status
        if not flex_config_status().get("configured"):
            summary.update({"status": "completed", "skipped": "flex_not_configured"})
        else:
            res = flex_sync()
            summary.update({"status": "completed", "ok": res.get("ok"),
                            "archived": res.get("archived"), "error": res.get("error")})
        logger.info("[ibkr_flex_sync] %s", summary)
    except Exception as exc:
        logger.exception("ibkr_flex_sync job failed")
        summary.update({"status": "failed", "error": str(exc)})
    finally:
        with connect() as conn:
            dao.finish_analysis_run(conn, run_id=run_id,
                                    status=summary.get("status", "completed"),
                                    summary_json=summary)
    return summary
