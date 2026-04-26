"""FastAPI router exposing scheduler control + status.

Mounted into ``dashboard_server.py``:

    from agent.finance.scheduler.api import router as scheduler_router
    app.include_router(scheduler_router)

Endpoints
---------
GET  /api/scheduler/jobs            — list registered jobs + DB state
POST /api/scheduler/run/{job_name}  — force-run a job synchronously
                                       (the "manual rerun" button)

The force-run endpoint is intentionally synchronous in V1: a single
data pull takes <30s on real Yahoo Finance, and synchronous keeps
the wiring simple. If we hit slower jobs, switch to a background
task queue (FastAPI ``BackgroundTasks`` or a separate worker).

Authentication: none in V1 because dashboard_server binds to
127.0.0.1 only. If we ever expose this beyond localhost, a request
that triggers expensive recomputation MUST be auth-gated.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from agent.finance.persistence import connect, ensure_schema
from agent.finance.scheduler.core import build_default_registry, run_job_once

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
