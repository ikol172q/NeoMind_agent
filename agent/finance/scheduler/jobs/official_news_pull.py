"""Official newsroom pull — refresh each mapped company's newsroom RSS
into the `official_news` table hourly, so the dashboard serves fresh
primary-source PRs even when nobody has opened the drawer (真·定时).

Best-effort per ticker: one feed failing (network / feed change) does
not fail the others or the scheduler. The endpoint also live-refreshes
on demand, so this job is the "keep it warm" layer, not the only path.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from agent.finance.news_hub import OFFICIAL_FEEDS, refresh_official

logger = logging.getLogger(__name__)


JOB_NAME = "official_news_pull"
# 5 minutes past every hour — staggered off the top of the hour so it
# doesn't pile up with other hourly jobs.
DEFAULT_CRON = "5 * * * *"
DESCRIPTION = "公司官方 newsroom RSS → official_news 表 (每小时, 真·定时)"


async def run(**_: Any) -> Dict[str, Any]:
    ok, failed = [], []
    for ticker in OFFICIAL_FEEDS:
        try:
            refresh_official(ticker)
            ok.append(ticker)
        except Exception as exc:   # best-effort per ticker
            logger.warning("official_news_pull %s failed: %s", ticker, exc)
            failed.append(ticker)
    return {"status": "ok", "refreshed": ok, "failed": failed,
            "n_feeds": len(OFFICIAL_FEEDS)}
