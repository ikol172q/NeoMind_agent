"""Daily Plaid holdings sync.

No-op when Plaid not configured. Otherwise pulls latest investments/
holdings for every persisted plaid_item and reconciles into tax_lots
(account_id='plaid:<item_id>' so it doesn't clash with manual lots).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict

from agent.finance.persistence import connect, dao

logger = logging.getLogger(__name__)

JOB_NAME = "holdings_sync_daily"
DEFAULT_CRON = "30 21 * * *"  # 21:30 UTC daily (after US market close)
DESCRIPTION = (
    "Daily Plaid Investments sync: pulls current holdings for each "
    "connected brokerage, reconciles into tax_lots (account_id="
    "'plaid:<item_id>'). No-op when PLAID_CLIENT_ID + PLAID_SECRET "
    "are not set. Manual lots (other account_ids) are untouched."
)


async def run() -> Dict[str, Any]:
    with connect() as conn:
        run_id = dao.start_analysis_run(
            conn, job_name=JOB_NAME, run_type="scheduled",
        )
    summary: Dict[str, Any] = {"run_id": run_id, "status": "running"}
    try:
        from agent.finance.integrations.plaid import is_configured, sync_all_items
        if not is_configured():
            summary.update({"status": "completed",
                            "skipped": "PLAID_CLIENT_ID not set"})
            logger.info("[holdings_sync_daily] skipped — Plaid not configured")
        else:
            result = await sync_all_items()
            summary.update({"status": "completed", "sync": result})
            n_items = len((result or {}).get("items", []))
            logger.info("[holdings_sync_daily] synced %d items", n_items)
    except Exception as exc:
        logger.exception("holdings_sync_daily failed")
        summary.update({"status": "failed", "error": str(exc)})

    with connect() as conn:
        dao.finish_analysis_run(
            conn, run_id=run_id,
            status=summary["status"],
            summary_json=summary,
        )
    return summary
