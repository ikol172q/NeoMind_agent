"""FastAPI router exposing read-only views of the fin SQLite store.

Mounted into ``dashboard_server.py`` at app construction time:

    from agent.finance.persistence.api import router as db_router
    app.include_router(db_router)

All endpoints are namespaced under ``/api/db/`` to make it obvious they
read from the new SQLite layer (not the older file-based analyses
under ``Investment/<project>/analyses/``). Both stores can coexist —
the UI can render either.

Read-only on purpose: writes happen only through scheduler jobs and
the manual force-rerun in scheduler.api. Conflating UI writes with
scheduler writes invites consistency bugs we don't want.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from agent.finance.persistence import (
    SCHEMA_VERSION,
    connect,
    ensure_schema,
    get_db_path,
)
from agent.finance.persistence import dao

router = APIRouter(prefix="/api/db", tags=["fin-db"])


def _row_to_dict(row: Any) -> Dict[str, Any]:
    return {k: row[k] for k in row.keys()}


@router.get("/health")
def db_health() -> Dict[str, Any]:
    """Report DB liveness, schema version, and row counts per table.

    Useful as the first thing the UI hits — if this fails, the rest
    of /api/db/ won't work either.
    """
    ensure_schema()
    counts: Dict[str, int] = {}
    with connect() as conn:
        tables = [
            "tickers_universe",
            "market_data_daily",
            "analysis_runs",
            "strategy_signals",
            "tax_lots",
            "wash_sale_events",
            "pdt_round_trips",
            "scheduler_jobs",
        ]
        for t in tables:
            row = conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()
            counts[t] = int(row["n"])

    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "db_path": str(get_db_path()),
        "counts": counts,
    }


@router.get("/universe")
def list_universe(
    market: Optional[str] = Query(None, description="filter by market: us, cn, hk, crypto, global"),
    asset_class: Optional[str] = Query(None, description="filter by class: stock, etf, crypto, ..."),
) -> Dict[str, Any]:
    ensure_schema()
    with connect() as conn:
        rows = dao.list_active_universe(conn, market=market, asset_class=asset_class)
    return {"count": len(rows), "tickers": [_row_to_dict(r) for r in rows]}


@router.get("/market-data/{symbol}")
def get_market_data(
    symbol: str,
    market: str = Query("us"),
    limit: int = Query(60, ge=1, le=2000),
) -> Dict[str, Any]:
    ensure_schema()
    with connect() as conn:
        rows = dao.get_latest_market_data(conn, symbol, market, limit=limit)
    if not rows:
        return {"symbol": symbol.upper(), "market": market.lower(), "count": 0, "bars": []}
    return {
        "symbol": symbol.upper(),
        "market": market.lower(),
        "count": len(rows),
        "bars": [_row_to_dict(r) for r in rows],
    }


@router.get("/runs")
def list_runs(
    job_name: Optional[str] = None,
    limit: int = Query(20, ge=1, le=200),
) -> Dict[str, Any]:
    ensure_schema()
    with connect() as conn:
        rows = dao.list_recent_runs(conn, job_name=job_name, limit=limit)
    out = []
    for r in rows:
        d = _row_to_dict(r)
        if d.get("metadata_json"):
            try:
                d["metadata"] = json.loads(d["metadata_json"])
            except json.JSONDecodeError:
                d["metadata"] = None
        out.append(d)
    return {"count": len(out), "runs": out}


@router.get("/signals")
def list_signals(
    symbol: Optional[str] = None,
    strategy_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
) -> Dict[str, Any]:
    """Recent strategy signals — ordered by last_seen_at DESC.

    Each signal carries dedup metadata: ``seen_count`` tells you how
    many runs have produced this exact signal, ``created_at`` is when
    we first saw it, ``last_seen_at`` is the most recent run that
    re-emitted it. A signal that's been ``last_seen`` an hour ago is
    still live; one not seen for a week is probably stale.
    """
    ensure_schema()
    with connect() as conn:
        rows = dao.list_recent_signals(
            conn, symbol=symbol, strategy_id=strategy_id, limit=limit,
        )
    out: List[Dict[str, Any]] = []
    for r in rows:
        d = _row_to_dict(r)
        d["pdt_relevant"] = bool(d.get("pdt_relevant"))
        if d.get("sources_json"):
            try:
                d["sources"] = json.loads(d["sources_json"])
            except json.JSONDecodeError:
                d["sources"] = None
        out.append(d)
    return {"count": len(out), "signals": out}
