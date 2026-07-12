"""Scheduler job — Serenity (@aleabitoreddit) 每日增量抓取.

每天拉他在 X 上的最新推文,upsert 进 `research_corpus`(一手研究语料库)。
增量:`daily_sync` 拉最新 N 条、按 post_id 去重,既补新帖也刷新互动数。
Best-effort:Apify 失败(额度用尽/反爬)只记 failed,不让 scheduler 崩。

Cron: ``0 12 * * *`` — 每天 12:00 UTC 一次(~07:00 ET)。他日均 ~30 推,
拉最新 100 条足以覆盖(含跨日重叠,漏一天次日也能补上)。
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from agent.finance.persistence import connect, dao, ensure_schema

logger = logging.getLogger(__name__)

JOB_NAME = "serenity_sync"
DEFAULT_CRON = "0 12 * * *"
DESCRIPTION = (
    "每日拉 @aleabitoreddit 最新推文增量 upsert 进 research_corpus 一手语料库 "
    "(Apify kaitoeasyapi;失败则 best-effort 跳过)。"
)


async def run() -> Dict[str, Any]:
    ensure_schema()
    with connect() as conn:
        run_id = dao.start_analysis_run(conn, job_name=JOB_NAME, run_type="scheduled")

    summary: Dict[str, Any] = {"run_id": run_id, "status": "running"}
    try:
        from agent.finance.research_corpus import daily_sync
        res = daily_sync(max_items=100)
        summary.update({"status": "completed", **res})
        logger.info("[serenity_sync] pulled=%s new=%s", res.get("pulled"), res.get("new"))
    except Exception as exc:
        logger.exception("serenity_sync job failed")
        summary.update({"status": "failed", "error": str(exc)[:300]})
    finally:
        with connect() as conn:
            dao.finish_analysis_run(conn, run_id=run_id,
                                    status=summary.get("status", "completed"),
                                    summary_json=summary)
    return summary
