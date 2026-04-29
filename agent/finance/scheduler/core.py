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
    "agent.finance.scheduler.jobs.daily_market_pull",
    "agent.finance.scheduler.jobs.compliance_check",
    # Phase B3-real (2026-04-26): pull Miniflux entries → RawStore.
    # Graceful skip if Miniflux unconfigured/unreachable, so adding
    # this module to the default registry is safe even on machines
    # without docker miniflux booted.
    "agent.finance.scheduler.jobs.news_pull",
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


def build_default_registry() -> JobRegistry:
    reg = JobRegistry()
    for path in DEFAULT_JOBS:
        reg.register_module(path)
    return reg


async def _invoke(runner: Callable[..., Awaitable[Any]], **kwargs: Any) -> Any:
    return await runner(**kwargs)


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
        result = asyncio.run(_invoke(runner, **kwargs))
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
