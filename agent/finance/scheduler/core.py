"""Scheduler core — job registry + APScheduler wiring.

The registry is the single source of truth for "which jobs exist".
Adding a new job means: write ``jobs/<name>.py`` exposing
(JOB_NAME, DEFAULT_CRON, DESCRIPTION, async def run), then register
it in ``DEFAULT_JOBS`` below.

APScheduler runs jobs in a thread pool, but our jobs are async — so we
wrap each call with ``asyncio.run`` inside a thread. This is fine for
the small Phase-1 cadence (a few jobs/day). If we later need finer
scheduling (sub-minute, fan-out to many tickers), we can switch to
APScheduler's AsyncIOScheduler — out of scope for now.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import sqlite3
from typing import Any, Awaitable, Callable, Dict, Optional

from agent.finance.persistence import connect, ensure_schema

logger = logging.getLogger(__name__)


# Modules to auto-register at startup. Add new jobs here.
DEFAULT_JOBS = [
    # Serenity (@aleabitoreddit) 一手语料库每日增量抓取 (2026-06-02).
    # Best-effort: Apify 抓取失败/额度用尽则跳过,不影响其他 job。
    "agent.finance.scheduler.jobs.serenity_sync",
    "agent.finance.scheduler.jobs.daily_market_pull",
    "agent.finance.scheduler.jobs.compliance_check",
    # IB Gateway 掉线预警 (2026-07-06): 每 20 分钟探测 API 端口,掉线→P1 推,
    # 否则 IBKR 真仓在 dashboard 上隐形、静默裸管。watchdog 拉起 app;本 job 通知。
    "agent.finance.scheduler.jobs.ibkr_gateway_health",
    # 纪律化 IC 深研 loop (2026-07-10): 每工作日扫低覆盖小盘 insider 集群 → 深研
    # (anchored crux) → 纪律 thesis(机制/缺口/invalidation/退役/sizing)。机器自己
    # 筛,让前向验证的 breadth 组合自动增长;propose-not-dispose,永不下单。
    "agent.finance.scheduler.jobs.research_loop_scan",
    # Phase B3-real (2026-04-26): pull Miniflux entries → RawStore.
    # Graceful skip if Miniflux unconfigured/unreachable, so adding
    # this module to the default registry is safe even on machines
    # without docker miniflux booted.
    "agent.finance.scheduler.jobs.news_pull",
    # Official company newsroom RSS → official_news table, hourly
    # (真·定时) so the drawer serves fresh primary-source PRs without an
    # open tab. Best-effort per ticker; endpoint also refreshes on demand.
    "agent.finance.scheduler.jobs.official_news_pull",
    # Daily metric snapshots (quote+fundamentals+holders) → metric_snapshot
    # table, so the drawer can show metrics as-of any past day (verified,
    # tool-sourced, auditable). Runs after US close.
    "agent.finance.scheduler.jobs.metric_snapshot_pull",
    # Anti-hallucination Layer 0a (2026-04-27): nightly audit of N
    # 'unverified' strategies. Promotes them to 'verified' /
    # 'partially_verified' once their numeric claims are grounded in
    # RawStore bytes via LLM-extractor + mechanical post-check.
    # Graceful skip on missing DEEPSEEK_API_KEY / network errors.
    "agent.finance.scheduler.jobs.audit_strategies",
    # Strategy pipeline v2 (2026-04-29): daily yfinance ingest + regime
    # fingerprint compute.  Powers the 5-bucket regime widget on the
    # Research tab and the new expected-utility scorer.
    "agent.finance.scheduler.jobs.regime_daily",
    # Phase L+ (2026-04-30): hourly signal scan — watchlist + news
    # scanners → confluence detector → "Today's Signals" inbox.
    # Skips gracefully if user_watchlist is empty.
    "agent.finance.scheduler.jobs.signal_hourly",
    # Phase L+ (2026-04-30): daily 13F whale scan via SEC EDGAR.
    # 7 whales × ~1s each + 0.5s sleep = ~30s.  Idempotent: re-emits
    # only when SEC publishes a new filing.
    "agent.finance.scheduler.jobs.whale_daily",
    # Learning library (2026-05-04): daily fresh investing-education
    # case fetch via miniflux + Tavily, LLM-gated, Chinese-translated.
    # ~$0.01-0.05 per run, runs 06:00 daily.
    "agent.finance.scheduler.jobs.learning_daily",
    # Phase W (2026-05-10): daily check of every active investment
    # thesis — flags thesis as 'requires_review' if supporting facts
    # went stale or supporting signal types went silent in 30d.
    # Runs 06:30 daily, after learning_daily.
    "agent.finance.scheduler.jobs.thesis_health_check",
    # Goal-2 闭环主动腿 (2026-06-29): EOD 后重算 thesis_materiality → 破/动摇
    # 生成提案写 agent_alerts(去重)→ 推 Telegram(与 dashboard 铃铛同步)。
    # propose-not-dispose。22:00 UTC,美股收盘后。
    "agent.finance.scheduler.jobs.thesis_alert_daily",
    # Goal-2 闭环 P1 即时腿 (2026-06-29): 每小时确定性事件扫描 → grounded 判断
    # → 即时推 P1(下行/生存)。P2 留给上面的每日 digest。
    "agent.finance.scheduler.jobs.alert_scan_hourly",
    # Phase 3 (2026-05-10): daily earnings calendar scan for Core +
    # Adjacent watchlist tickers. Emits earnings_upcoming signal_event
    # when within 14d (severity by proximity). Backfills
    # earnings_history table from yfinance. Runs 07:10 weekdays.
    "agent.finance.scheduler.jobs.earnings_calendar",
    # Phase 3 (2026-05-10): daily macro calendar fetch from Trading
    # Economics RSS — surfaces FOMC, CPI, NFP, GDP etc within 14d.
    # Theme-level signal (no ticker), severity always 'high' since
    # macro releases move whole sectors. Runs 06:45 daily.
    "agent.finance.scheduler.jobs.macro_calendar",
    # 2026-05-16: weekly auto-refresh of 10-K-anchored facts. Without
    # this, stock_anchored_facts rots from the day a ticker files its
    # next 10-K until a manual re-extract click. ~$1.50 per run for
    # ~50-ticker watchlist; Sunday 04:00 UTC.
    "agent.finance.scheduler.jobs.anchored_quarterly",
    # 2026-05-16: Plaid Investments daily holdings sync. No-op when
    # Plaid not configured (PLAID_CLIENT_ID + PLAID_SECRET unset);
    # otherwise pulls positions from each connected brokerage and
    # reconciles into tax_lots under account_id='plaid:<item_id>'.
    "agent.finance.scheduler.jobs.holdings_sync_daily",
    # 2026-05-17: daily snapshot of compile_strategy_signal output for
    # every watchlist ticker. After 3-6 months of daily ticks the
    # signal_snapshots table holds the historical (date, combined_score)
    # sequence needed for proper edge-validation backtests in vectorbt.
    "agent.finance.scheduler.jobs.signal_snapshot_daily",
    # 2026-05-22: short-term trading desk daily auto-scan. Scans armed
    # setups (status paper/live) for entry triggers on the latest bar and
    # auto-places risk-sized paper orders — UNLESS the global halt is on.
    # Runs the kill-switch check first. Weekday evening (after US close).
    "agent.finance.scheduler.jobs.trading_scan",
    # IBKR durable archive (2026-05-23): every 5 min in market hours, snapshot
    # paper account/positions/orders/fills into ibkr_log so backtrace never
    # loses a fill. Graceful no-op (records snapshot_error) if Gateway is down.
    "agent.finance.scheduler.jobs.ibkr_snapshot",
    # IBKR Flex backstop (2026-05-23): daily after-close pull of the official
    # statement → ibkr_log (deduped by tradeID). Lossless catch-all for fills
    # the live snapshot missed. No-op until the user configures token+query.
    "agent.finance.scheduler.jobs.ibkr_flex_sync",
]


class JobRegistry:
    """Registry of job_name → (module, cron, description, runner)."""

    def __init__(self) -> None:
        self._jobs: Dict[str, Dict[str, Any]] = {}

    def register_module(self, module_path: str) -> None:
        mod = importlib.import_module(module_path)
        for required in ("JOB_NAME", "DEFAULT_CRON", "DESCRIPTION", "run"):
            if not hasattr(mod, required):
                raise ValueError(
                    f"job module {module_path} missing required attribute {required}"
                )
        self._jobs[mod.JOB_NAME] = {
            "module": module_path,
            "cron": mod.DEFAULT_CRON,
            "description": mod.DESCRIPTION,
            "run": mod.run,  # type: ignore[attr-defined]
        }
        logger.info(
            "registered job %r (cron=%s) from %s",
            mod.JOB_NAME, mod.DEFAULT_CRON, module_path,
        )

    def names(self) -> list[str]:
        return sorted(self._jobs.keys())

    def get(self, name: str) -> Dict[str, Any]:
        if name not in self._jobs:
            raise KeyError(f"unknown job {name!r}; known: {self.names()}")
        return self._jobs[name]

    def upsert_to_db(self, conn: sqlite3.Connection) -> None:
        """Mirror the registry into the scheduler_jobs table so the UI
        can show "what jobs exist" + "when did they last run".
        Existing rows keep their cron / enabled / last_run_* state.
        """
        for name, spec in self._jobs.items():
            conn.execute(
                """
                INSERT INTO scheduler_jobs (job_name, cron_expression, description, enabled)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(job_name) DO UPDATE SET
                    description = excluded.description
                    -- intentionally don't overwrite cron_expression / enabled
                    -- so user edits persist across restarts
                """,
                (name, spec["cron"], spec["description"]),
            )


_cached_registry: Optional["JobRegistry"] = None


def build_default_registry() -> JobRegistry:
    # 2026-05-16: cache process-wide. Without this, every API call to
    # /api/scheduler/* re-imports all 12 job modules and emits a
    # "registered job" log line each — 12 lines × every request. Burned
    # the dashboard log to 42MB and wasted CPU on hot paths.
    global _cached_registry
    if _cached_registry is None:
        reg = JobRegistry()
        for path in DEFAULT_JOBS:
            reg.register_module(path)
        _cached_registry = reg
    return _cached_registry


async def _invoke(runner: Callable[..., Awaitable[Any]], **kwargs: Any) -> Any:
    return await runner(**kwargs)


async def _invoke_audited(name: str, runner: Callable[..., Awaitable[Any]],
                          **kwargs: Any) -> Any:
    """Audit-wrapped invocation. Every scheduler job becomes a NeoMind
    Live entry (agent_id=scheduler:<name>). Per-scanner sub-audits
    inside the job (signal_hourly's wl/news/cong/policy) still fire
    independently — they show up as scanner:<name> entries that the
    operator can use to drill from the parent job into per-scanner
    runs."""
    from agent.finance.agent_audit import audited_call_async
    return await audited_call_async(
        agent_id=f"scheduler:{name}",
        endpoint=f"scheduler:{name}",
        fn=runner,
        kwargs=kwargs,
        extra_request={"trigger": "scheduler"},
        summarize_result=lambda r: (
            f"job {name}: status={r.get('status', '?')}"
            if isinstance(r, dict) else str(r)[:200]),
    )


def run_job_once(name: str, **kwargs: Any) -> Dict[str, Any]:
    """Run a job synchronously (for CLI / API force-rerun).

    Sets up DB schema, ensures the job is registered, then drives the
    async runner to completion. Returns the job's summary dict (or
    ``{"error": ...}`` if the runner raised).
    """
    ensure_schema()
    reg = build_default_registry()
    spec = reg.get(name)

    runner = spec["run"]
    try:
        result = asyncio.run(_invoke_audited(name, runner, **kwargs))
        # Update scheduler_jobs.last_run_* — the runner already wrote
        # an analysis_runs row; we only mirror its identity here.
        # Mirror the actual analysis_runs.status, not just "didn't raise":
        # a job that catches all per-ticker failures and reports them
        # via failures[] should still surface as failed/partial in the
        # scheduler view.
        run_id = result.get("run_id") if isinstance(result, dict) else None
        with connect() as conn:
            reg.upsert_to_db(conn)
            run_status = "completed"
            consec_delta_sql = "consecutive_failures = 0"
            if run_id is not None:
                row = conn.execute(
                    "SELECT status FROM analysis_runs WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
                if row is not None and row["status"] in ("failed", "cancelled"):
                    run_status = row["status"]
                    consec_delta_sql = "consecutive_failures = consecutive_failures + 1"
            conn.execute(
                f"""
                UPDATE scheduler_jobs
                   SET last_run_id = COALESCE(?, last_run_id),
                       last_run_at = datetime('now'),
                       last_run_status = ?,
                       {consec_delta_sql}
                 WHERE job_name = ?
                """,
                (run_id, run_status, name),
            )
        return result if isinstance(result, dict) else {"result": result}
    except Exception as exc:  # noqa: BLE001
        logger.exception("job %r failed: %s", name, exc)
        with connect() as conn:
            reg.upsert_to_db(conn)
            conn.execute(
                """
                UPDATE scheduler_jobs
                   SET last_run_at = datetime('now'),
                       last_run_status = 'failed',
                       consecutive_failures = consecutive_failures + 1
                 WHERE job_name = ?
                """,
                (name,),
            )
        return {"error": str(exc)}
