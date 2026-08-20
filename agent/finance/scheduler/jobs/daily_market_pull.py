"""Daily market data pull — first scheduler job.

Iterates the active universe, calls ``FinanceDataHub.get_history`` for
each ticker, and writes the bars into ``market_data_daily`` via the
DAO layer's ``INSERT OR REPLACE`` (so re-runs are idempotent).

Cron default: ``5 22 * * 1-5`` (22:05 UTC, weekdays — about 18:05 ET,
shortly after the US market close on a workday). Can be tweaked per
deployment in ``scheduler_jobs.cron_expression``.

Manual rerun:
    python -m agent.finance.scheduler.runner --run-once daily_market_pull
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict

from agent.finance.persistence import connect, ensure_schema
from agent.finance.persistence import dao

logger = logging.getLogger(__name__)


JOB_NAME = "daily_market_pull"
# 🔴 2026-08-07: `1-5` → `mon-fri`。**APScheduler 的 day_of_week 用 0=周一**,
#    与标准 crontab (0=周日) 差一位 —— 写 `1-5` 本意"周一~周五", 实际跑 **周二~周六**:
#    每个周一(交易日)不跑, 每个周六(非交易日)白跑。
#    这批 job 在 2026-08-03 修过 13 个, 本文件在**另一个仓**所以漏网, 又活了 4 天。
#    症状之所以难发现: job 每次都 status=completed / consecutive_failures=0 ——
#    **它没有失败, 它只是在错误的日子成功**, 任何只看"跑没跑完"的巡检都报绿灯。
#    ⚠️ 只改这里不生效: `scheduler_jobs` 的 upsert **故意不覆盖 cron_expression**
#    (为保留用户手改), 必须同步 UPDATE 数据库。
DEFAULT_CRON = "5 22 * * mon-fri"
DESCRIPTION = (
    "Pull last ~3 months of daily OHLCV for every active ticker and "
    "upsert into market_data_daily. Idempotent — re-runs replace rows."
)


async def run(period: str = "3mo", interval: str = "1d") -> Dict[str, Any]:
    """Execute the job. Returns a summary dict suitable for logging.

    Lazy-imports FinanceDataHub so a missing yfinance install doesn't
    crash the scheduler at startup; it'll fail at job execution
    instead, which is reported via analysis_runs.error_message.
    """
    ensure_schema()  # cheap & idempotent — every job is self-defending

    # Lazy import keeps scheduler module load cheap even when this job
    # isn't being used.
    from agent.finance.data_hub import FinanceDataHub

    hub = FinanceDataHub()

    with connect() as conn:
        run_id = dao.start_analysis_run(
            conn,
            job_name=JOB_NAME,
            run_type="scheduled",
            metadata={"period": period, "interval": interval},
        )

        universe = dao.list_active_universe(conn, market="us")
        logger.info("daily_market_pull: %d tickers in universe", len(universe))

    # We close the conn before going async on network I/O — SQLite
    # locks are short-lived and we re-open per write batch.

    rows_written_total = 0
    failures: list[Dict[str, str]] = []

    for ticker in universe:
        symbol = ticker["symbol"]
        market = ticker["market"]
        try:
            bars = await hub.get_history(symbol, period=period, interval=interval)
        except Exception as exc:  # noqa: BLE001 — we log and continue
            logger.warning("get_history(%s) failed: %s", symbol, exc)
            failures.append({"symbol": symbol, "error": str(exc)})
            continue

        if not bars:
            failures.append({"symbol": symbol, "error": "empty bars"})
            continue

        with connect() as conn:
            n = dao.upsert_market_data_daily(
                conn,
                symbol=symbol,
                market=market,
                bars=bars,
                source="yfinance",
            )
            rows_written_total += n

    with connect() as conn:
        status = "completed" if not failures or len(failures) < len(universe) else "failed"
        err = (
            f"{len(failures)}/{len(universe)} tickers failed: "
            + ", ".join(f["symbol"] for f in failures[:5])
            if failures else None
        )
        dao.complete_analysis_run(
            conn,
            run_id,
            status=status,
            error_message=err,
            universe_size=len(universe),
            rows_written=rows_written_total,
        )

    summary = {
        "run_id": run_id,
        "universe_size": len(universe),
        "rows_written": rows_written_total,
        "failures": failures,
    }
    logger.info("daily_market_pull complete: %s", summary)
    return summary
