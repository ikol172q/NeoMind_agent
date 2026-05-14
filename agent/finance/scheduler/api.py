"""FastAPI router exposing scheduler control + status.

Mounted into ``dashboard_server.py``:

    from agent.finance.scheduler.api import router as scheduler_router
    app.include_router(scheduler_router)

Endpoints
---------
GET  /api/scheduler/jobs                — list registered jobs + DB state
POST /api/scheduler/run/{job_name}      — force-run a job synchronously
                                          (the "manual rerun" button)
GET  /api/scheduler/runs/{job_name}     — last N runs for that job, with
                                          parsed metadata (the "Last Audit"
                                          panel data source)

The force-run endpoint is intentionally synchronous in V1: a single
data pull takes <30s on real Yahoo Finance, and synchronous keeps
the wiring simple. If we hit slower jobs, switch to a background
task queue (FastAPI ``BackgroundTasks`` or a separate worker).

Authentication: none in V1 because dashboard_server binds to
127.0.0.1 only. If we ever expose this beyond localhost, a request
that triggers expensive recomputation MUST be auth-gated.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from agent.finance.persistence import connect, dao, ensure_schema
from agent.finance.scheduler.core import build_default_registry, run_job_once

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scheduler", tags=["fin-scheduler"])


@router.get("/jobs")
def list_jobs() -> Dict[str, Any]:
    """Return all registered jobs joined with their scheduler_jobs row.

    The registry is the source of truth for "what jobs exist"; the DB
    row carries operational state (cron user might've edited,
    last_run_*, consecutive_failures).
    """
    ensure_schema()
    reg = build_default_registry()
    with connect() as conn:
        reg.upsert_to_db(conn)
        rows = {
            r["job_name"]: dict(r)
            for r in conn.execute("SELECT * FROM scheduler_jobs")
        }

    out = []
    for name in reg.names():
        spec = reg.get(name)
        db_row = rows.get(name, {})
        out.append({
            "name": name,
            "description": spec["description"],
            "default_cron": spec["cron"],
            "cron_expression": db_row.get("cron_expression") or spec["cron"],
            "enabled": bool(db_row.get("enabled", 1)),
            "last_run_id": db_row.get("last_run_id"),
            "last_run_at": db_row.get("last_run_at"),
            "last_run_status": db_row.get("last_run_status"),
            "consecutive_failures": db_row.get("consecutive_failures", 0),
            "next_run_at": db_row.get("next_run_at"),
        })
    return {"count": len(out), "jobs": out}


@router.post("/run/{job_name}")
def force_run(job_name: str) -> Dict[str, Any]:
    """Synchronously run a registered job. Returns its summary or error.

    Idempotent at the DB level: every write the job does goes through
    the dedup-aware DAO. Calling this twice in a row is safe — second
    call replaces / dedups, doesn't double-write.
    """
    ensure_schema()
    reg = build_default_registry()
    if job_name not in reg.names():
        raise HTTPException(
            status_code=404,
            detail=f"unknown job {job_name!r}; known: {reg.names()}",
        )

    result = run_job_once(job_name)
    return {"job": job_name, "result": result}


@router.get("/runs/{job_name}")
def list_runs(
    job_name: str,
    limit: int = Query(default=10, ge=1, le=500),
    started_after: Optional[str] = Query(
        default=None,
        description="Inclusive ISO 8601 lower bound on started_at "
                    "(e.g. '2026-04-28T00:00:00Z').",
    ),
    started_before: Optional[str] = Query(
        default=None,
        description="Inclusive ISO 8601 upper bound on started_at "
                    "(e.g. '2026-04-28T23:59:59Z').",
    ),
) -> Dict[str, Any]:
    """Return analysis_runs rows for ``job_name``.

    This is the data source for the Strategies-tab "Last Audit" panel.
    Without this endpoint the user has no way to tell whether the daily
    auditor actually ran (and produced "still unverified" because the
    corpus didn't ground the claims) vs. silently skipped (cron didn't
    fire).  Each row carries the rich summary the job stashed into
    metadata_json on completion: audited_n / promoted_n / still_unverified
    / errors_n / sample / explanation.

    With no date bounds: returns the most recent ``limit`` rows.
    With ``started_after`` / ``started_before``: scopes to that window
    (still capped by ``limit``).  The UI's TimeScope control passes:
      - "Today"        → started_after = today 00:00 UTC
      - "Single day"   → both bounds set to that day
      - "Range"        → both bounds set to user-picked range
      - "All time"     → no bounds (default)
    """
    ensure_schema()
    reg = build_default_registry()
    if job_name not in reg.names():
        raise HTTPException(
            status_code=404,
            detail=f"unknown job {job_name!r}; known: {reg.names()}",
        )

    out: List[Dict[str, Any]] = []
    with connect() as conn:
        rows = dao.list_recent_runs(
            conn,
            job_name=job_name,
            limit=int(limit),
            started_after=started_after,
            started_before=started_before,
        )

    for r in rows:
        meta_raw: Optional[str] = r["metadata_json"] if "metadata_json" in r.keys() else None
        meta: Dict[str, Any] = {}
        if meta_raw:
            try:
                parsed = json.loads(meta_raw)
                if isinstance(parsed, dict):
                    meta = parsed
            except Exception:  # pragma: no cover — defensive
                meta = {"_raw": meta_raw}

        out.append({
            "run_id":            r["run_id"],
            "run_type":          r["run_type"],
            "job_name":          r["job_name"],
            "started_at":        r["started_at"],
            "completed_at":      r["completed_at"],
            "status":            r["status"],
            "error_message":     r["error_message"],
            "rows_written":      r["rows_written"],
            "duration_seconds":  r["duration_seconds"],
            "metadata":          meta,
        })

    return {
        "job": job_name,
        "count": len(out),
        "runs": out,
        "filters": {
            "limit": int(limit),
            "started_after": started_after,
            "started_before": started_before,
        },
    }


# Phase 3 (2026-05-10) Pillar 3 — scanner health endpoint.
#
# Returns last-success time per registered job + how it compares to
# the expected interval. Dashboard header surfaces a red badge when
# any scanner is silent > 2× expected interval — defensive
# observability so the user notices broken scanners before stale
# data corrupts a decision.
@router.get("/scanner_health")
def scanner_health() -> Dict[str, Any]:
    """Returns {jobs: [{name, last_success_at, expected_interval_min,
    minutes_since, is_stale, status}, ...], n_stale}."""
    from datetime import datetime, timezone, timedelta
    ensure_schema()
    reg = build_default_registry()
    job_names = reg.names()

    # Expected intervals derived from cron — rough mapping
    # cron string → expected interval in minutes between fires
    def expected_interval_min(cron: str) -> int:
        # Common patterns we register:
        if cron.startswith("*/"):
            try:
                return int(cron.split()[0][2:])
            except Exception:
                return 60
        if "* * * *" in cron:
            return 60
        if cron.startswith("0 ") or cron.startswith("5 ") or cron.startswith("10 "):
            return 24 * 60
        if "1-5" in cron:
            return 24 * 60
        return 24 * 60

    now = datetime.now(timezone.utc)
    out = []
    n_stale = 0
    with connect() as conn:
        for jn in job_names:
            try:
                cron = reg.get(jn).get("cron") or ""
            except KeyError:
                cron = ""
            interval_min = expected_interval_min(cron)
            row = conn.execute(
                "SELECT MAX(completed_at) AS last_ok "
                "FROM analysis_runs "
                "WHERE job_name = ? AND status = 'completed'",
                (jn,),
            ).fetchone()
            last_ok = row["last_ok"] if row else None
            minutes_since = None
            is_stale = False
            if last_ok:
                try:
                    last_dt = datetime.fromisoformat(last_ok.replace("Z","+00:00"))
                    if last_dt.tzinfo is None:
                        last_dt = last_dt.replace(tzinfo=timezone.utc)
                    minutes_since = int((now - last_dt).total_seconds() / 60)
                    # 2× expected interval = stale
                    is_stale = minutes_since > interval_min * 2
                except Exception:
                    pass
            else:
                is_stale = True   # never ran = stale
            if is_stale:
                n_stale += 1
            out.append({
                "name":                  jn,
                "cron":                  cron,
                "expected_interval_min": interval_min,
                "last_success_at":       last_ok,
                "minutes_since_success": minutes_since,
                "is_stale":              is_stale,
            })
    return {
        "jobs":      out,
        "n_jobs":    len(out),
        "n_stale":   n_stale,
        "checked_at": now.isoformat(),
    }
