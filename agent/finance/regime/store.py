"""SQLite DAO for the 4 regime-pipeline tables.

Schema lives in ``persistence/schema.sql``; this module is just the
read/write helpers downstream code uses.  Idempotent inserts via
``INSERT OR REPLACE`` so backfill can re-run without duplicates.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from agent.finance.persistence import connect, ensure_schema


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── raw_market_data ────────────────────────────────────────────────


def upsert_raw_bars(
    bars: Iterable[Dict[str, Any]],
    *,
    source: str = "yfinance",
) -> int:
    """Bulk-insert OHLCV rows.  Each ``bars`` element must have keys:
    symbol, trade_date, open, high, low, close, volume, tier.
    Optional: adjusted_close, raw_blob_sha.

    Returns count written.  Idempotent: existing (symbol, trade_date)
    rows are replaced.
    """
    ensure_schema()
    rows: List[tuple] = []
    fetched_at = _now()
    for b in bars:
        rows.append((
            b["symbol"], b["trade_date"],
            b.get("open"), b.get("high"), b.get("low"),
            b.get("close"), b.get("adjusted_close"),
            b.get("volume"),
            source, fetched_at,
            b.get("raw_blob_sha"),
            int(b.get("tier", 3)),
        ))
    if not rows:
        return 0
    with connect() as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO raw_market_data
                (symbol, trade_date, open, high, low, close, adjusted_close,
                 volume, source, fetched_at, raw_blob_sha, tier)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    return len(rows)


def latest_close(symbol: str) -> Optional[Dict[str, Any]]:
    """Most recent close for a symbol — None if not ingested yet."""
    ensure_schema()
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM raw_market_data WHERE symbol=? "
            "ORDER BY trade_date DESC LIMIT 1",
            (symbol,),
        ).fetchone()
    return dict(row) if row else None


def closes_window(symbol: str, n_days: int) -> List[Dict[str, Any]]:
    """Last ``n_days`` rows for a symbol, oldest first.  Used by the
    regime fingerprint compute (percentile / RV / MA windows)."""
    ensure_schema()
    with connect() as conn:
        rows = conn.execute(
            "SELECT trade_date, open, high, low, close, adjusted_close, volume "
            "FROM raw_market_data WHERE symbol=? "
            "ORDER BY trade_date DESC LIMIT ?",
            (symbol, n_days),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def closes_as_of(
    symbol: str,
    as_of_date: str,
    n_days: int,
) -> List[Dict[str, Any]]:
    """Last ``n_days`` rows ending at or before ``as_of_date`` (inclusive),
    oldest first.  Used to compute a fingerprint AS OF a historical
    date — the backfill path.  ``as_of_date`` is YYYY-MM-DD UTC."""
    ensure_schema()
    with connect() as conn:
        rows = conn.execute(
            "SELECT trade_date, open, high, low, close, adjusted_close, volume "
            "FROM raw_market_data "
            "WHERE symbol=? AND trade_date <= ? "
            "ORDER BY trade_date DESC LIMIT ?",
            (symbol, as_of_date, n_days),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def all_symbols_with_data(min_rows: int = 1) -> List[str]:
    """Return symbols that have at least ``min_rows`` ingested bars.
    Used to skip ones with no data yet during compute."""
    ensure_schema()
    with connect() as conn:
        rows = conn.execute(
            "SELECT symbol FROM raw_market_data "
            "GROUP BY symbol HAVING COUNT(*) >= ?",
            (min_rows,),
        ).fetchall()
    return [r["symbol"] for r in rows]


def universe_close_panel(
    symbols: List[str],
    as_of_date: str,
) -> Dict[str, float]:
    """Latest close for each ticker, as of (or before) the given date.
    Used by breadth / dispersion calcs that need a cross-section."""
    ensure_schema()
    out: Dict[str, float] = {}
    if not symbols:
        return out
    with connect() as conn:
        # SQLite limit on parametrised IN is 999. Chunk if necessary.
        for i in range(0, len(symbols), 500):
            chunk = symbols[i:i + 500]
            placeholders = ",".join("?" for _ in chunk)
            rows = conn.execute(
                f"""
                SELECT symbol, close FROM raw_market_data
                WHERE symbol IN ({placeholders})
                  AND trade_date = (
                    SELECT MAX(trade_date) FROM raw_market_data r2
                    WHERE r2.symbol = raw_market_data.symbol
                      AND r2.trade_date <= ?
                  )
                """,
                (*chunk, as_of_date),
            ).fetchall()
            for r in rows:
                out[r["symbol"]] = r["close"]
    return out


# ── regime_fingerprints ────────────────────────────────────────────


def upsert_fingerprint(fp: Dict[str, Any]) -> str:
    """Write a fingerprint row.  ``fp`` must have:
    fingerprint_date, risk_appetite_score, volatility_regime_score,
    breadth_score, event_density_score, flow_score,
    components (dict), inputs (dict), sources (dict).
    Returns the fingerprint_date written.
    """
    ensure_schema()
    with connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO regime_fingerprints
                (fingerprint_date,
                 risk_appetite_score, volatility_regime_score,
                 breadth_score, event_density_score, flow_score,
                 components_json, inputs_json, sources_json,
                 computed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fp["fingerprint_date"],
                fp.get("risk_appetite_score"),
                fp.get("volatility_regime_score"),
                fp.get("breadth_score"),
                fp.get("event_density_score"),
                fp.get("flow_score"),
                json.dumps(fp.get("components", {}), default=str),
                json.dumps(fp.get("inputs", {}), default=str),
                json.dumps(fp.get("sources", {}), default=str),
                _now(),
            ),
        )
    return fp["fingerprint_date"]


def get_fingerprint(date: str) -> Optional[Dict[str, Any]]:
    """Read a fingerprint row.  Returns dict with parsed JSON or None."""
    ensure_schema()
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM regime_fingerprints WHERE fingerprint_date=?",
            (date,),
        ).fetchone()
    if not row:
        return None
    out = dict(row)
    for k in ("components_json", "inputs_json", "sources_json"):
        if out.get(k):
            try:
                out[k.replace("_json", "")] = json.loads(out[k])
            except json.JSONDecodeError:
                out[k.replace("_json", "")] = {}
        del out[k]
    return out


def list_fingerprints(
    *, limit: int = 365, since: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Recent fingerprints, newest first.  Used by k-NN search and
    by the Audit / Data Lake list views."""
    ensure_schema()
    sql = "SELECT * FROM regime_fingerprints"
    args: List[Any] = []
    if since:
        sql += " WHERE fingerprint_date >= ?"
        args.append(since)
    sql += " ORDER BY fingerprint_date DESC LIMIT ?"
    args.append(limit)
    with connect() as conn:
        rows = conn.execute(sql, args).fetchall()
    out = []
    for row in rows:
        d = dict(row)
        for k in ("components_json", "inputs_json", "sources_json"):
            if d.get(k):
                try:
                    d[k.replace("_json", "")] = json.loads(d[k])
                except json.JSONDecodeError:
                    d[k.replace("_json", "")] = {}
            del d[k]
        out.append(d)
    return out


# ── decision_traces ───────────────────────────────────────────────


def write_decision_trace(trace: Dict[str, Any]) -> str:
    """Persist one decision (one strategy on one date)."""
    ensure_schema()
    trace_id = trace.get("trace_id") or str(uuid.uuid4())
    with connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO decision_traces
                (trace_id, fingerprint_date, strategy_id, score, rank,
                 alternative_weight, formula, breakdown_json,
                 lattice_node_refs, knn_neighbor_dates,
                 constraint_check_json, portfolio_fit_json,
                 computed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trace_id,
                trace["fingerprint_date"], trace["strategy_id"],
                float(trace["score"]), int(trace["rank"]),
                float(trace.get("alternative_weight", 1.0)),
                trace["formula"],
                json.dumps(trace.get("breakdown", {}), default=str),
                json.dumps(trace.get("lattice_node_refs", []), default=str),
                json.dumps(trace.get("knn_neighbor_dates", []), default=str),
                json.dumps(trace.get("constraint_check", {}), default=str),
                json.dumps(trace.get("portfolio_fit", {}), default=str),
                _now(),
            ),
        )
    return trace_id


def list_decision_traces(
    *, fingerprint_date: Optional[str] = None,
    strategy_id: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Read decision_traces, with parsed JSON fields."""
    ensure_schema()
    where: List[str] = []
    args: List[Any] = []
    if fingerprint_date:
        where.append("fingerprint_date = ?")
        args.append(fingerprint_date)
    if strategy_id:
        where.append("strategy_id = ?")
        args.append(strategy_id)
    sql = "SELECT * FROM decision_traces"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY computed_at DESC LIMIT ?"
    args.append(limit)
    with connect() as conn:
        rows = conn.execute(sql, args).fetchall()
    out = []
    for row in rows:
        d = dict(row)
        for k in ("breakdown_json", "lattice_node_refs", "knn_neighbor_dates",
                  "constraint_check_json", "portfolio_fit_json"):
            if d.get(k):
                try:
                    d[k.replace("_json", "")] = json.loads(d[k])
                except json.JSONDecodeError:
                    d[k.replace("_json", "")] = None
            d.pop(k, None)
        out.append(d)
    return out


# ── knn_lookups ───────────────────────────────────────────────────


def write_knn_lookups(
    target_date: str,
    used_for_strategy: str,
    neighbors: List[Dict[str, Any]],
) -> int:
    """Bulk-insert k-NN search records.  Each neighbor:
    {neighbor_date, similarity_score, weight_in_prior}."""
    ensure_schema()
    rows = [
        (
            str(uuid.uuid4()),
            target_date,
            n["neighbor_date"],
            float(n["similarity_score"]),
            float(n["weight_in_prior"]),
            used_for_strategy,
            _now(),
        )
        for n in neighbors
    ]
    if not rows:
        return 0
    with connect() as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO knn_lookups
                (lookup_id, target_date, neighbor_date,
                 similarity_score, weight_in_prior,
                 used_for_strategy, computed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    return len(rows)
