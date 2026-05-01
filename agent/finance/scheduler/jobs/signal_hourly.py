"""Scheduler job — hourly signal scan (Phase L+).

Runs all NeoMind Live scanners back-to-back every hour, then promotes
≥2-source confluences for the frontend's "Today's Signals" inbox.

Cron: ``5 * * * *`` (5 minutes past every hour) — gives prior cron jobs
breathing room and avoids thundering-herd minutes.

Manual rerun:
    python -m agent.finance.scheduler.runner --run-once signal_hourly
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from agent.finance.persistence import connect, dao, ensure_schema

logger = logging.getLogger(__name__)


JOB_NAME = "signal_hourly"
DEFAULT_CRON = "5 * * * *"      # 5 minutes past every hour
DESCRIPTION = (
    "Hourly: run watchlist (price/RSI/MA/volume) + news (yfinance "
    "headlines) scanners across the watchlist + auto-expanded supply "
    "chain.  Promotes ≥2-source confluences to signal_confluences "
    "for the Today's Signals inbox."
)


async def run() -> Dict[str, Any]:
    ensure_schema()

    with connect() as conn:
        run_id = dao.start_analysis_run(
            conn, job_name=JOB_NAME, run_type="scheduled",
        )

    summary: Dict[str, Any] = {"run_id": run_id, "status": "running"}
    try:
        from agent.finance.regime.scanners.watchlist_scanner import run_watchlist_scan
        from agent.finance.regime.scanners.news_scanner       import run_news_scan
        from agent.finance.regime.signals                     import (
            detect_confluences, list_watchlist,
        )

        wl = list_watchlist()
        if not wl:
            logger.info("[signal_hourly] empty watchlist — skipping")
            summary.update({"status": "completed", "skipped": "empty_watchlist"})
            with connect() as conn:
                dao.finish_analysis_run(conn, run_id=run_id, status="completed",
                                        summary_json=summary)
            return summary

        try:
            wl_result = run_watchlist_scan()
        except Exception as exc:
            logger.exception("watchlist scanner failed")
            wl_result = {"error": str(exc)}

        try:
            news_result = run_news_scan()
        except Exception as exc:
            logger.exception("news scanner failed")
            news_result = {"error": str(exc)}

        # Congressional + policy: fast HTTP, low rate-limit risk
        try:
            from agent.finance.regime.scanners.congressional_scanner import run_congressional_scan
            cong_result = run_congressional_scan(lookback_days=30)
        except Exception as exc:
            logger.exception("congressional scanner failed")
            cong_result = {"error": str(exc)}

        try:
            from agent.finance.regime.scanners.policy_scanner import run_policy_scan
            policy_result = run_policy_scan()
        except Exception as exc:
            logger.exception("policy scanner failed")
            policy_result = {"error": str(exc)}

        confluences = detect_confluences()

        summary.update({
            "status":            "completed",
            "watchlist_scan":    wl_result,
            "news_scan":         news_result,
            "congressional_scan": cong_result,
            "policy_scan":       policy_result,
            "new_confluences":   len(confluences),
            "n_user_tickers":    len(wl),
        })
        logger.info(
            "[signal_hourly] watchlist=%s news=%s stock_act=%s policy=%s confluences=%d",
            wl_result.get("n_emitted") if isinstance(wl_result, dict) else "err",
            news_result.get("n_emitted") if isinstance(news_result, dict) else "err",
            cong_result.get("n_emitted") if isinstance(cong_result, dict) else "err",
            policy_result.get("n_emitted") if isinstance(policy_result, dict) else "err",
            len(confluences),
        )
    except Exception as exc:
        logger.exception("signal_hourly failed")
        summary.update({"status": "failed", "error": str(exc)})
    finally:
        with connect() as conn:
            dao.finish_analysis_run(
                conn, run_id=run_id,
                status=summary["status"], summary_json=summary,
            )

    return summary
