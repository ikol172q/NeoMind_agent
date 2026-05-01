"""NeoMind Live — push signal system.

Replaces the pull-dashboard approach with an agentic monitor: 5 background
scanners continuously emit ``signal_events`` rows, a confluence detector
promotes ≥2-source agreements to ``signal_confluences``, and the frontend
shows only the top 3 today + a transparency stream of agent activity.

This module is the data-access + business-logic layer.  Scanners live
in ``agent/finance/regime/scanners/*.py``.

Tables (schema v4):
    user_watchlist      — hand-curated tickers
    signal_events       — every scanner emission
    signal_confluences  — promoted multi-source agreements

Public API:
    Watchlist:
        list_watchlist()           → [{"ticker": str, "added_at": str, ...}]
        add_to_watchlist(ticker, note=None, importance=1)
        remove_from_watchlist(ticker)

    Signal events:
        emit_event(scanner, ...) → event_id
        recent_events(limit=50, since=None, ticker=None)

    Confluences:
        detect_confluences(window_hours=72, min_sources=2)
            → list of newly-promoted confluences
        list_confluences(active_only=True, limit=10)
        dismiss_confluence(confluence_id)

    Supply chain expansion (no DB; pure function):
        expand_supply_chain(watchlist_tickers) → list of related tickers
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── watchlist ─────────────────────────────────────────────────────


def list_watchlist() -> List[Dict[str, Any]]:
    from agent.finance.persistence import connect
    with connect() as conn:
        cur = conn.execute(
            "SELECT ticker, added_at, note, importance "
            "FROM user_watchlist ORDER BY importance DESC, added_at"
        )
        return [dict(r) for r in cur.fetchall()]


def add_to_watchlist(
    ticker: str,
    *,
    note: Optional[str] = None,
    importance: int = 1,
) -> Dict[str, Any]:
    from agent.finance.persistence import connect
    ticker = ticker.strip().upper()
    if not ticker:
        raise ValueError("empty ticker")
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO user_watchlist (ticker, added_at, note, importance) "
            "VALUES (?, ?, ?, ?)",
            (ticker, _now_iso(), note, int(importance)),
        )
    return {"ticker": ticker, "added_at": _now_iso(),
            "note": note, "importance": int(importance)}


def remove_from_watchlist(ticker: str) -> bool:
    from agent.finance.persistence import connect
    ticker = ticker.strip().upper()
    with connect() as conn:
        cur = conn.execute(
            "DELETE FROM user_watchlist WHERE ticker = ?", (ticker,)
        )
        return cur.rowcount > 0


# ── supply chain expansion ───────────────────────────────────────


# Hand-curated US tech supply chain map.  Keys are user-watchlist
# tickers; values are upstream/downstream tickers that produce signals
# the user should care about.  Updated periodically — NOT data-mined
# (because that would introduce hallucination risk).  Citations live
# in the AlgorithmAppendix.
SUPPLY_CHAIN_MAP: Dict[str, List[str]] = {
    "AAPL":  ["TSM", "QCOM", "AVGO", "ARM", "STM", "JBL"],
    "TSLA":  ["NVDA", "AMD", "ON", "ALB", "MP", "PANW", "LSCC"],
    "META":  ["NVDA", "AVGO", "TSM", "ANET", "CDNS", "VRT"],
    "MSFT":  ["NVDA", "AMD", "AVGO", "ANET", "VRT", "CRM"],
    "NVDA":  ["TSM", "ASML", "AMAT", "LRCX", "MU", "AVGO", "ANET"],
    "AMD":   ["TSM", "ASML", "AMAT", "LRCX", "AVGO"],
    "ARM":   ["QCOM", "AAPL", "AMD", "NVDA"],   # ARM IP licensees
    "GOOGL": ["TSM", "NVDA", "AVGO", "ANET", "VRT", "BRCM"],
    "GOOG":  ["TSM", "NVDA", "AVGO", "ANET", "VRT", "BRCM"],
    "APP":   ["TTD", "ROKU", "RBLX", "META", "GOOGL"],   # ad ecosystem
}


def expand_supply_chain(tickers: List[str]) -> List[str]:
    """Return upstream/downstream tickers related to the given set,
    deduplicated and excluding the input.  Pure function — no I/O."""
    related: set = set()
    upper = [t.upper() for t in tickers]
    src = set(upper)
    for t in upper:
        for r in SUPPLY_CHAIN_MAP.get(t, []):
            if r not in src:
                related.add(r)
    return sorted(related)


# ── signal events ────────────────────────────────────────────────


def emit_event(
    scanner_name: str,
    *,
    signal_type: str,
    severity: str = "med",
    title: str,
    ticker: Optional[str] = None,
    theme: Optional[str] = None,
    body: Optional[Dict[str, Any]] = None,
    source_url: Optional[str] = None,
    source_timestamp: Optional[str] = None,
) -> str:
    """Persist a single signal event from a scanner.

    Returns the new event_id.
    """
    from agent.finance.persistence import connect
    if not (ticker or theme):
        raise ValueError("event must have at least one of ticker / theme")
    if severity not in ("high", "med", "low"):
        raise ValueError(f"bad severity {severity}")

    eid = str(uuid.uuid4())
    body_json = json.dumps(body or {}, default=str)
    detected = _now_iso()
    src_ts = source_timestamp or detected

    with connect() as conn:
        conn.execute(
            """INSERT INTO signal_events
                  (event_id, scanner_name, ticker, theme,
                   signal_type, severity, title, body_json,
                   source_url, source_timestamp, detected_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (eid, scanner_name, ticker, theme, signal_type, severity,
             title, body_json, source_url, src_ts, detected),
        )
    logger.info("[signal] %s · %s · %s · %s", scanner_name, ticker or theme, signal_type, title)
    return eid


def recent_events(
    *,
    limit: int = 50,
    since:  Optional[str] = None,
    ticker: Optional[str] = None,
    scanner: Optional[str] = None,
) -> List[Dict[str, Any]]:
    from agent.finance.persistence import connect

    sql = "SELECT * FROM signal_events"
    where: List[str] = []
    args:  List[Any] = []
    if since:
        where.append("detected_at >= ?"); args.append(since)
    if ticker:
        where.append("ticker = ?"); args.append(ticker.upper())
    if scanner:
        where.append("scanner_name = ?"); args.append(scanner)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY detected_at DESC LIMIT ?"
    args.append(int(limit))

    with connect() as conn:
        rows = conn.execute(sql, args).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if d.get("body_json"):
            try:
                d["body"] = json.loads(d["body_json"])
            except Exception:
                d["body"] = None
            d.pop("body_json", None)
        out.append(d)
    return out


# ── confluence detection ─────────────────────────────────────────


def detect_confluences(
    *,
    window_hours: int = 72,
    min_sources: int = 2,
) -> List[Dict[str, Any]]:
    """Scan signal_events for cases where ≥``min_sources`` distinct
    scanners hit the same ticker (or theme) within the rolling window.

    Promotes new ones to signal_confluences.  Idempotent: skips
    duplicates already recorded for the same (ticker, day).

    Returns the list of newly-promoted confluences.
    """
    from agent.finance.persistence import connect

    since_dt = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    since_iso = since_dt.isoformat(timespec="seconds")

    with connect() as conn:
        cur = conn.execute(
            "SELECT * FROM signal_events WHERE detected_at >= ? "
            "ORDER BY detected_at DESC",
            (since_iso,),
        )
        events = [dict(r) for r in cur.fetchall()]

    # Group by (ticker, theme); count distinct scanner_name; collect events
    groups: Dict[str, Dict[str, Any]] = {}
    for e in events:
        key = e.get("ticker") or f"theme:{e.get('theme')}"
        g = groups.setdefault(key, {
            "ticker": e.get("ticker"),
            "theme":  e.get("theme"),
            "scanners": set(),
            "events":  [],
            "max_severity": "low",
        })
        g["scanners"].add(e["scanner_name"])
        g["events"].append(e)
        if _severity_rank(e["severity"]) > _severity_rank(g["max_severity"]):
            g["max_severity"] = e["severity"]

    new_confluences: List[Dict[str, Any]] = []
    today = datetime.now(timezone.utc).date().isoformat()
    for key, g in groups.items():
        if len(g["scanners"]) < min_sources:
            continue

        # Skip if we've already promoted today for this ticker/theme
        with connect() as conn:
            cur = conn.execute(
                "SELECT confluence_id FROM signal_confluences "
                "WHERE (ticker = ? AND ticker IS NOT NULL) OR (theme = ? AND theme IS NOT NULL) "
                "AND date(detected_at) = ?",
                (g["ticker"], g["theme"], today),
            )
            if cur.fetchone():
                continue

        # Build headline
        headline = _build_confluence_headline(g)
        color = _severity_to_color(g["max_severity"])
        interp = _build_confluence_interp(g)

        cid = str(uuid.uuid4())
        detected = _now_iso()
        expires = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(timespec="seconds")
        event_ids = [e["event_id"] for e in g["events"]]

        with connect() as conn:
            conn.execute(
                """INSERT INTO signal_confluences
                      (confluence_id, ticker, theme, headline,
                       n_sources, color, interpretation,
                       detected_at, expires_at, event_ids_json, dismissed)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                (cid, g["ticker"], g["theme"], headline,
                 len(g["scanners"]), color, interp,
                 detected, expires, json.dumps(event_ids)),
            )
        new_confluences.append({
            "confluence_id":  cid,
            "ticker":         g["ticker"],
            "theme":          g["theme"],
            "headline":       headline,
            "n_sources":      len(g["scanners"]),
            "color":          color,
            "interpretation": interp,
            "scanners":       sorted(g["scanners"]),
            "events":         g["events"],
        })
        logger.info("[confluence] %s · %d sources · %s", key, len(g["scanners"]), headline)

    return new_confluences


def _severity_rank(s: str) -> int:
    return {"low": 0, "med": 1, "high": 2}.get(s, 0)


def _severity_to_color(s: str) -> str:
    return {"low": "amber", "med": "amber", "high": "green"}.get(s, "amber")


def _build_confluence_headline(g: Dict[str, Any]) -> str:
    target = g["ticker"] or g["theme"]
    n = len(g["scanners"])
    scanner_list = ", ".join(sorted(g["scanners"]))
    return f"{target} — {n}-source confluence ({scanner_list})"


def _build_confluence_interp(g: Dict[str, Any]) -> str:
    parts = []
    for e in g["events"][:5]:
        ts = e.get("source_timestamp") or e.get("detected_at", "")
        parts.append(f"• {e['scanner_name']}: {e['title']} ({_relative_time(ts)})")
    return "\n".join(parts)


def _relative_time(iso: str) -> str:
    """Convert ISO datetime to '3h ago' / '5d ago' / '2w ago'."""
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
    except Exception:
        return iso
    secs = abs(delta.total_seconds())
    if secs < 60:
        return f"{int(secs)}s 前"
    if secs < 3600:
        return f"{int(secs / 60)}m 前"
    if secs < 86400:
        return f"{int(secs / 3600)}h 前"
    if secs < 86400 * 14:
        return f"{int(secs / 86400)}d 前"
    return f"{int(secs / 86400 / 7)}w 前"


def list_confluences(
    *,
    active_only: bool = True,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    from agent.finance.persistence import connect
    sql = "SELECT * FROM signal_confluences"
    where: List[str] = []
    args:  List[Any] = []
    if active_only:
        now_iso = _now_iso()
        where.append("expires_at > ? AND dismissed = 0")
        args.append(now_iso)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY detected_at DESC LIMIT ?"
    args.append(int(limit))

    with connect() as conn:
        rows = conn.execute(sql, args).fetchall()

    out = []
    for r in rows:
        d = dict(r)
        if d.get("event_ids_json"):
            try:
                d["event_ids"] = json.loads(d["event_ids_json"])
            except Exception:
                d["event_ids"] = []
            d.pop("event_ids_json", None)
        # Hydrate events
        if d.get("event_ids"):
            with connect() as conn:
                placeholders = ",".join("?" * len(d["event_ids"]))
                cur = conn.execute(
                    f"SELECT * FROM signal_events WHERE event_id IN ({placeholders})",
                    d["event_ids"],
                )
                events = []
                for row in cur.fetchall():
                    e = dict(row)
                    if e.get("body_json"):
                        try:
                            e["body"] = json.loads(e["body_json"])
                        except Exception:
                            e["body"] = None
                        e.pop("body_json", None)
                    events.append(e)
                d["events"] = events
        out.append(d)
    return out


def dismiss_confluence(confluence_id: str) -> bool:
    from agent.finance.persistence import connect
    with connect() as conn:
        cur = conn.execute(
            "UPDATE signal_confluences SET dismissed = 1 WHERE confluence_id = ?",
            (confluence_id,),
        )
        return cur.rowcount > 0


# ── helper: today's top 3 ────────────────────────────────────────


def todays_top_signals(limit: int = 3) -> List[Dict[str, Any]]:
    """Frontend's "Today's 3 things" — most recent active confluences,
    optionally sorted by severity color (green/red > amber > gray)."""
    rows = list_confluences(active_only=True, limit=20)
    # Sort: severity rank desc, then detected_at desc
    color_rank = {"red": 3, "green": 2, "amber": 1, "gray": 0}
    rows.sort(key=lambda r: (-color_rank.get(r.get("color", ""), 0), r.get("detected_at", "")), reverse=False)
    rows.sort(key=lambda r: -color_rank.get(r.get("color", ""), 0))
    return rows[:limit]
