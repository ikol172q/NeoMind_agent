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


@router.get("/runs/{run_id}/rows")
def list_rows_for_run(
    run_id: str,
    limit: int = Query(50, ge=1, le=500),
) -> Dict[str, Any]:
    """Phase 6 followup: drill-down — what rows did this run actually
    write?  Different jobs touch different tables, so we union across
    every table that carries a run_id FK and tag each row with its
    source table.
    """
    ensure_schema()
    with connect() as conn:
        # Run-level metadata
        run_row = conn.execute(
            "SELECT * FROM analysis_runs WHERE run_id = ?", (run_id,),
        ).fetchone()
        if run_row is None:
            raise HTTPException(404, f"unknown run {run_id!r}")
        run = _row_to_dict(run_row)

        # Each table that references analysis_runs.run_id via FK.
        # Schema-driven: keep this list mirror of FOREIGN KEY rows in
        # schema.sql (run_id refs).
        sources: Dict[str, Dict[str, Any]] = {}
        for table, label in [
            ("strategy_signals",      "strategy_signals"),
            ("wash_sale_events",      "wash_sale_events"),
            ("pdt_round_trips",       "pdt_round_trips"),
            ("holding_period_snapshots", "holding_period_snapshots"),
        ]:
            try:
                rs = conn.execute(
                    f"SELECT * FROM {table} WHERE run_id = ? LIMIT {limit}",
                    (run_id,),
                ).fetchall()
            except Exception as exc:  # noqa: BLE001
                # Schema mismatch (e.g., older tables without run_id):
                # report 0 rows but don't crash the endpoint.
                sources[label] = {"count": 0, "rows": [], "error": str(exc)}
                continue
            sources[label] = {
                "count": len(rs),
                "rows":  [_row_to_dict(r) for r in rs],
            }

        # daily_market_pull writes to market_data_daily but the table
        # doesn't carry run_id (composite PK is symbol+trade_date and
        # we want it idempotent across runs). Approximate the "rows
        # written by this run" by joining on the run's window via
        # the table's `fetched_at` column.
        if run.get("job_name") == "daily_market_pull" and run.get("started_at"):
            try:
                start = run["started_at"]
                end   = run["completed_at"] or start
                rs = conn.execute(
                    "SELECT symbol, market, trade_date, close, volume, source, fetched_at "
                    "FROM market_data_daily WHERE fetched_at BETWEEN ? AND ? "
                    "ORDER BY symbol, trade_date DESC LIMIT ?",
                    (start, end, limit),
                ).fetchall()
            except Exception:  # noqa: BLE001
                rs = []
            sources["market_data_daily"] = {
                "count":        len(rs),
                "rows":         [_row_to_dict(r) for r in rs],
                "match_method": "approx_by_fetched_at_in_run_window",
            }

    total = sum(s.get("count", 0) for s in sources.values())
    return {
        "run":         run,
        "total_rows":  total,
        "by_table":    sources,
        "explanation": (
            f"All rows written by analysis_run {run_id!r}, grouped by "
            f"target table. Each table that carries a run_id FK is "
            f"queried directly; market_data_daily is matched by "
            f"updated_at falling inside the run's time window."
        ),
    }


@router.get("/lots")
def list_lots(
    open_only: bool = Query(False, description="filter to lots not yet closed"),
    limit: int = Query(100, ge=1, le=500),
) -> Dict[str, Any]:
    """Tax lots with their compliance state attached.

    Each lot is augmented with:
      - ``has_wash_sale_event``: any wash_sale_events row references this lot
      - ``latest_holding_period``: most recent snapshot row (open lots only)

    Used by the upcoming Portfolio tab; for V1 the fin integrity
    badge's drill-down also surfaces top-level counts.
    """
    ensure_schema()
    with connect() as conn:
        sql = """
            SELECT t.*,
                   EXISTS (
                       SELECT 1 FROM wash_sale_events w
                       WHERE w.sell_lot_id = t.lot_id
                          OR w.replacement_lot_id = t.lot_id
                   ) AS has_wash_sale_event
            FROM tax_lots t
        """
        if open_only:
            sql += " WHERE t.close_date IS NULL"
        sql += " ORDER BY t.open_date DESC LIMIT ?"
        rows = list(conn.execute(sql, (limit,)))

        # attach the latest holding-period snapshot for open lots
        hp_map: Dict[int, Dict[str, Any]] = {}
        for r in conn.execute(
            """
            SELECT h.lot_id, h.snapshot_date, h.days_held, h.days_to_long_term, h.qualified_today
            FROM holding_period_snapshots h
            JOIN (
                SELECT lot_id, MAX(snapshot_date) AS d FROM holding_period_snapshots GROUP BY lot_id
            ) x ON x.lot_id = h.lot_id AND x.d = h.snapshot_date
            """
        ):
            hp_map[r["lot_id"]] = _row_to_dict(r)

    out: List[Dict[str, Any]] = []
    for r in rows:
        d = _row_to_dict(r)
        d["is_simulated"] = bool(d.get("is_simulated"))
        d["has_wash_sale_event"] = bool(d.get("has_wash_sale_event"))
        d["latest_holding_period"] = hp_map.get(d["lot_id"])
        out.append(d)
    return {"count": len(out), "lots": out}


@router.get("/lattice-obs")
def list_lattice_obs() -> Dict[str, Any]:
    """Return the L1 observations the fin SQLite store would emit into
    the lattice graph right now.

    This is the **lineage view**: clicking the fin integrity badge
    shows not just "13/13 pass" but also "and here's the 2 L1 obs we
    just synthesised from these tables — they'll appear in the
    lattice graph under sub-theme subtheme_tax_compliance, and any
    L3 call grounded in that sub-theme has these as direct evidence."

    Calls ``gen_fin_compliance_signals`` directly (no synth project,
    no LLMs) so it's cheap and side-effect-free. Returns the raw
    Observation dicts.
    """
    try:
        from agent.finance.lattice.observations import gen_fin_compliance_signals
    except Exception as exc:
        return {"available": False, "reason": str(exc), "obs": []}

    obs = gen_fin_compliance_signals(proj={})
    # build_observations() stamps source.generator from the lambda name
    # at orchestration time. We're calling the generator directly so we
    # need to stamp it ourselves — keeps the trace UI honest.
    for o in obs:
        o.source.setdefault("generator", "gen_fin_compliance_signals")
    return {
        "available": True,
        "count": len(obs),
        "obs": [o.to_dict() for o in obs],
        "feeds_into": "subtheme_tax_compliance",
        "explanation": (
            "These observations are emitted by gen_fin_compliance_signals "
            "into the lattice every time build_observations runs. They cluster "
            "into the L2 sub-theme `subtheme_tax_compliance`, which any L3 "
            "call can ground in — making the wash sale / PDT / holding-"
            "period reasoning chain fully traceable from SQLite row to "
            "LLM recommendation."
        ),
    }


@router.get("/wash-sales")
def list_wash_sales(limit: int = Query(50, ge=1, le=500)) -> Dict[str, Any]:
    """All detected wash_sale_events, joined with both linked lots."""
    ensure_schema()
    with connect() as conn:
        rows = list(conn.execute(
            """
            SELECT w.*,
                   s.symbol AS sell_symbol, s.close_date AS sell_close_date,
                   s.open_price AS sell_open_price, s.close_price AS sell_close_price,
                   r.open_date AS replacement_open_date,
                   r.open_price AS replacement_open_price
            FROM wash_sale_events w
            JOIN tax_lots s ON s.lot_id = w.sell_lot_id
            JOIN tax_lots r ON r.lot_id = w.replacement_lot_id
            ORDER BY w.detected_at DESC LIMIT ?
            """,
            (limit,),
        ))
    return {"count": len(rows), "events": [_row_to_dict(r) for r in rows]}


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
