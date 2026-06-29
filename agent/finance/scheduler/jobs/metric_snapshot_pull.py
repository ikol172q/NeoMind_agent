"""Daily metric snapshot — snapshot quote + fundamentals + holders for
every watchlist ticker after US close, into `metric_snapshot`, so the
drawer can show metrics current AND as-of any past day (verified,
tool-sourced, auditable). Best-effort per ticker.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


JOB_NAME = "metric_snapshot_pull"
# 22:30 UTC weekdays (~after US close) — values settle post-close.
DEFAULT_CRON = "30 22 * * 1-5"
DESCRIPTION = "每日 metrics 快照(quote+fundamentals+holders) → metric_snapshot 表 (供 as-of 历史)"


async def run(**_: Any) -> Dict[str, Any]:
    from agent.finance.persistence import connect
    from agent.finance.metric_snapshots import snapshot_metrics

    with connect() as conn:
        try:
            rows = conn.execute("SELECT DISTINCT ticker FROM user_watchlist").fetchall()
        except Exception:
            rows = []
    tickers = [r[0] for r in rows]

    ok, failed = [], []
    for tk in tickers:
        try:
            snapshot_metrics(tk)
            ok.append(tk)
        except Exception as exc:   # best-effort per ticker
            logger.warning("metric_snapshot_pull %s failed: %s", tk, exc)
            failed.append(tk)
    return {"status": "ok", "snapshotted": len(ok), "failed": failed,
            "n_tickers": len(tickers)}
