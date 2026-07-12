"""Daily metric snapshots — verified, timestamped, as-of queryable.

Each day we fetch quote + fundamentals + holders via the yfinance tool
(get_live_quote / get_fundamentals / get_holders) and upsert ONE row per
(ticker, snapshot_date) into `metric_snapshot`. This makes the metrics:

  - tool-sourced  — never hand-computed; values come straight from the
    fetch tool, stored verbatim.
  - historical    — query "what was ARM's PE on 2026-04-15" via as-of
    (latest snapshot on-or-before the date).
  - auditable     — immutable daily rows + source + fetched_at.

The `metric_snapshot_pull` scheduler job calls snapshot_metrics() for the
whole watchlist after US close; the endpoints read it back.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from agent.data_sources.market import get_live_quote, get_fundamentals, get_holders


def _ensure_table(conn) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS metric_snapshot ("
        " ticker TEXT, snapshot_date TEXT, metrics_json TEXT,"
        " fetched_at TEXT, source TEXT,"
        " PRIMARY KEY (ticker, snapshot_date))"
    )


def snapshot_metrics(ticker: str, snapshot_date: Optional[str] = None) -> Dict[str, Any]:
    """Fetch quote + fundamentals + holders and upsert today's snapshot."""
    from agent.finance.persistence import connect
    tk = ticker.upper().strip()
    day = snapshot_date or datetime.now(timezone.utc).date().isoformat()
    q = get_live_quote(tk)
    f = get_fundamentals(tk)
    h = get_holders(tk)
    metrics = {
        "quote":        q.to_dict() if q else None,
        "fundamentals": f.to_dict() if f else None,
        "holders":      h.to_dict() if h else None,
    }
    now = datetime.now(timezone.utc).isoformat()
    with connect() as conn:
        _ensure_table(conn)
        conn.execute(
            "INSERT INTO metric_snapshot (ticker, snapshot_date, metrics_json, fetched_at, source) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(ticker, snapshot_date) DO UPDATE SET "
            " metrics_json = excluded.metrics_json, fetched_at = excluded.fetched_at",
            (tk, day, json.dumps(metrics, ensure_ascii=False), now, "yfinance"),
        )
    return {"ticker": tk, "snapshot_date": day, "metrics": metrics, "fetched_at": now}


def read_metrics_asof(ticker: str, as_of: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Latest snapshot on-or-before `as_of` (default = most recent row)."""
    from agent.finance.persistence import connect
    tk = ticker.upper().strip()
    with connect() as conn:
        _ensure_table(conn)
        if as_of:
            row = conn.execute(
                "SELECT snapshot_date, metrics_json, fetched_at FROM metric_snapshot "
                "WHERE ticker = ? AND snapshot_date <= ? ORDER BY snapshot_date DESC LIMIT 1",
                (tk, as_of)).fetchone()
        else:
            row = conn.execute(
                "SELECT snapshot_date, metrics_json, fetched_at FROM metric_snapshot "
                "WHERE ticker = ? ORDER BY snapshot_date DESC LIMIT 1",
                (tk,)).fetchone()
    if not row:
        return None
    try:
        metrics = json.loads(row[1] or "{}")
    except Exception:
        metrics = {}
    return {"ticker": tk, "snapshot_date": row[0], "fetched_at": row[2], "metrics": metrics}


def list_snapshot_dates(ticker: str, limit: int = 90) -> List[str]:
    from agent.finance.persistence import connect
    tk = ticker.upper().strip()
    with connect() as conn:
        _ensure_table(conn)
        rows = conn.execute(
            "SELECT snapshot_date FROM metric_snapshot WHERE ticker = ? "
            "ORDER BY snapshot_date DESC LIMIT ?",
            (tk, limit)).fetchall()
    return [r[0] for r in rows]
