"""Scheduled daily fresh-case fetcher.

Pulls 5-8 new investing learning cases each morning from miniflux +
Tavily (Tavily-primary internet search) + LLM gate, persists into
the learning_cases table with is_fresh=1, and expires the
"is_fresh" flag on cases older than 7 days.

Wakes up at 06:00 daily by default. Adjust the cron via the
scheduler API or by editing scheduler_jobs row.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict

from agent.finance.persistence import connect, dao

logger = logging.getLogger(__name__)


JOB_NAME = "learning_daily"

# 06:00 daily local — gives the user fresh cases to read in the morning.
DEFAULT_CRON = "0 6 * * *"

DESCRIPTION = (
    "Daily fetch of investing-education cases from miniflux + Tavily, "
    "LLM-gated for relevance, Chinese-translated, into learning_cases. "
    "Drives the 📚 Learning → Today widget."
)


async def run() -> Dict[str, Any]:
    """Scheduler entrypoint. Mirrors the shape of news_pull / signal_hourly."""
    with connect() as conn:
        run_id = dao.start_analysis_run(
            conn, job_name=JOB_NAME, run_type="scheduled",
        )
    summary: Dict[str, Any] = {"run_id": run_id, "status": "running"}
    try:
        from agent.finance.learning.fetcher import fetch_fresh_cases
        # Reasonable defaults: visit ~30 candidates, accept up to 8.
        # Cost ceiling per run: ~$0.01-0.05 depending on how many
        # candidates pass the gate.
        # NOTE: fetch_fresh_cases internally calls asyncio.run() (legacy
        # sync entry point), which conflicts with the scheduler's own
        # running event loop. Run it in a thread to isolate.
        result = await asyncio.to_thread(
            fetch_fresh_cases, max_candidates=30, max_accept=8,
        )
        summary.update({
            "status":         "completed",
            "fetcher_result": result,
        })
        logger.info(
            "[learning_daily] candidates=%d accepted=%d new_slugs=%d",
            result.get("n_candidates", 0),
            result.get("n_accepted", 0),
            len(result.get("new_slugs", [])),
        )
    except Exception as exc:
        logger.exception("learning_daily failed")
        summary.update({"status": "failed", "error": str(exc)})

    with connect() as conn:
        dao.finish_analysis_run(
            conn, run_id=run_id,
            status=summary["status"],
            summary_json=summary,
        )
    return summary
