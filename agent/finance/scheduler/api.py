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
