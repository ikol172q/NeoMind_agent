"""Hub-and-spoke watchlist API — backed by the SQLite user_watchlist
table (the same one scanners read from).

Distinct from watchlist_web.py, which uses a per-project watchlist.json
file for legacy reasons. That file is still read by earnings.py /
correlation.py / synthesis.py and we don't want to break them, so this
module adds NEW endpoints on top of the SQLite table without touching
the legacy ones.

Three concepts beyond the original watchlist:

  tier ∈ {core, adjacent, watching}
      core      — ≤10 deep-research names. Weekly review prompted.
      adjacent  — 10-50 names reached via a core's competitor /
                  customer / supplier from stock_anchored_facts.
                  Monthly review.
      watching  — 50-200 names. Alert-only.

  parent_ticker
      For adjacent / watching, which core ticker did this name spread
      out from. Lets the UI render the spoke graph and lets the user
      ask "if I drop AAPL, do I also drop its adjacents?".

  last_reviewed_at
      Bumped every time the user opens the ticker drawer or edits a
      note. Drives the "stale thesis" review prompt — any core ticker
      not touched in 14d gets surfaced on the Watchlist tab.

Endpoints (all live under /api/watchlist):

  GET  /tiers                    → list grouped by tier, with
                                    fact counts + last_reviewed lag
  POST /promote/{ticker}         → upsert with tier + parent_ticker
  POST /touch/{ticker}           → bump last_reviewed_at
  DEL  /tickers/{ticker}         → remove from watchlist
  GET  /suggestions/{ticker}     → adjacent candidates pulled from
                                    stock_anchored_facts (competitor /
                                    customer / supplier rows)
  GET  /outside_ring             → tickers with strong scanner signal
                                    that are NOT in any tier — anti-
                                    anchoring counter-current

The legacy /api/watchlist GET / POST / PATCH / DELETE remain
on the same /api prefix from watchlist_web.py.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from agent.finance.persistence import connect, ensure_schema

logger = logging.getLogger(__name__)


_VALID_TIERS = {"core", "adjacent", "watching"}
_TIER_LIMITS = {"core": 15, "adjacent": 100, "watching": 500}
_TICKER_RE = re.compile(r"^[A-Z0-9.-]{1,16}$")


def _t(t: str) -> str:
    """Normalize + validate a ticker (uppercased)."""
    s = (t or "").strip().upper()
    if not _TICKER_RE.match(s):
        raise HTTPException(400, f"invalid ticker {t!r}")
    return s


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Read helpers ────────────────────────────────────────────────────

def _list_by_tier() -> Dict[str, List[Dict[str, Any]]]:
    """Return {tier: [entry,...]} for the whole watchlist, with fact
    counts + last_reviewed lag in days. Ordered importance DESC then
    added_at within each tier."""
    ensure_schema()
    out: Dict[str, List[Dict[str, Any]]] = {"core": [], "adjacent": [], "watching": []}
    with connect() as conn:
        rows = conn.execute(
            "SELECT w.ticker, w.tier, w.parent_ticker, w.note, w.importance, "
            "       w.added_at, w.last_reviewed_at, "
            "       (SELECT COUNT(*) FROM stock_anchored_facts f "
            "         WHERE f.ticker = w.ticker) AS n_facts "
            "FROM user_watchlist w "
            "ORDER BY w.tier, w.importance DESC, w.added_at"
        ).fetchall()
    now_dt = datetime.now(timezone.utc)
    for r in rows:
        tier = r["tier"] or "core"
        last = r["last_reviewed_at"]
        days = None
        if last:
            try:
                days = int((now_dt - datetime.fromisoformat(last.replace("Z", "+00:00"))).total_seconds() / 86400)
            except Exception:
                pass
        out.setdefault(tier, []).append({
            "ticker":           r["ticker"],
            "tier":             tier,
            "parent_ticker":    r["parent_ticker"],
            "note":             r["note"] or "",
            "importance":       r["importance"] or 1,
            "added_at":         r["added_at"],
            "last_reviewed_at": last,
            "days_since_review": days,    # null if never reviewed
            "n_facts":          r["n_facts"] or 0,
        })
    return out


def _suggestions_for(ticker: str) -> Dict[str, List[Dict[str, str]]]:
    """For a given ticker, pull every related-company name out of its
    stock_anchored_facts rows (competitor / customer / supplier).
    Returns {kind: [{name, evidence_quote, source_url}, ...]}.

    The names are NOT validated against a ticker symbol resolver — this
    is a "candidates surfaced from 10-K text" view; the user picks
    which ones to actually add (and supplies the trading symbol)."""
    t = _t(ticker)
    ensure_schema()
    out: Dict[str, List[Dict[str, str]]] = {
        "competitor": [], "customer": [], "supplier": [],
    }
    with connect() as conn:
        rows = conn.execute(
            "SELECT fact_type, payload_json, evidence_quote, source_url "
            "FROM stock_anchored_facts "
            "WHERE ticker = ? AND fact_type IN ('competitor','customer','supplier') "
            "ORDER BY fact_type, extracted_at DESC",
            (t,),
        ).fetchall()
    for r in rows:
        ft = r["fact_type"]
        try:
            payload = json.loads(r["payload_json"] or "{}")
        except Exception:
            payload = {}
        name = payload.get("name") or payload.get("entity") or ""
        if not name:
            continue
        # evidence_quote is its OWN column on stock_anchored_facts —
        # the payload only carries fact-type specific structured fields
        # (name, ticker?, criticality?). Caught 2026-05-07 by the
        # NVDA supplier inventory check.
        quote = (r["evidence_quote"] or "")[:200]
        # If the extractor recorded a ticker symbol on the payload,
        # surface it so the frontend can pre-fill the prompt instead
        # of guessing from the company name's first word.
        related_ticker = payload.get("ticker") or ""
        out.setdefault(ft, []).append({
            "name":           name,
            "ticker":         related_ticker,
            "evidence_quote": quote,
            "source_url":     r["source_url"] or "",
        })
    return out


def _outside_ring(limit: int = 20) -> List[Dict[str, Any]]:
    """Tickers with recent strong scanner signal that are NOT in any
    tier of the watchlist. The point of this view: counter-balance
    the user's hub-and-spoke focus — surface things they'd otherwise
    never see because they're not in any core's spoke.

    Ranking: count of high/med signal_events in the last 14d, only
    counting tickers with ≥2 distinct scanner sources (multi-source
    confluence is what makes a signal worth surfacing — single-source
    events are too noisy)."""
    ensure_schema()
    cutoff = (datetime.now(timezone.utc) - _td(days=14)).isoformat()
    rows: List[Dict[str, Any]] = []
    try:
        with connect() as conn:
            rs = conn.execute(
                "SELECT e.ticker, "
                "       COUNT(*)                                          AS n_events, "
                "       COUNT(DISTINCT e.scanner_name)                    AS n_sources, "
                "       MAX(e.detected_at)                                   AS latest_at, "
                "       SUM(CASE WHEN e.severity='high' THEN 1 ELSE 0 END) AS n_high "
                "FROM signal_events e "
                "WHERE e.ticker IS NOT NULL "
                "  AND e.detected_at >= ? "
                "  AND e.severity IN ('high','med') "
                "  AND e.ticker NOT IN (SELECT ticker FROM user_watchlist) "
                "GROUP BY e.ticker "
                "HAVING COUNT(DISTINCT e.scanner_name) >= 2 "
                "ORDER BY n_high DESC, n_sources DESC, n_events DESC "
                "LIMIT ?",
                (cutoff, limit),
            ).fetchall()
            rows = [dict(r) for r in rs]
    except Exception as exc:
        # signal_events may not exist on a fresh install — fail soft so
        # the Watchlist tab still renders the rest of its data.
        logger.warning("outside_ring scan failed: %s", exc)
        return []
    return rows


def _td(days: int):
    """Local timedelta to avoid importing at module level (keeps the
    extract minimal)."""
    from datetime import timedelta
    return timedelta(days=days)


# ── Pydantic bodies ─────────────────────────────────────────────────


class PromoteBody(BaseModel):
    tier: str = Field(..., description="core | adjacent | watching")
    parent_ticker: Optional[str] = None
    note: Optional[str] = None
    importance: int = 1
    # 2026-05-10 Phase W: trigger linkage so we can answer
    # "why did I promote ARM 6 months ago" via watchlist_audit.
    trigger_kind: Optional[str] = Field(
        None, description="'fact' | 'signal' | 'thesis' | 'manual'")
    trigger_ref_id: Optional[str] = Field(
        None, description="ID of the fact/signal/thesis that prompted this")


# ── Router ──────────────────────────────────────────────────────────


def build_watchlist_tiers_router() -> APIRouter:
    router = APIRouter(prefix="/api/watchlist", tags=["watchlist-tiers"])

    @router.get("/tiers")
    def list_tiered() -> Dict[str, Any]:
        grouped = _list_by_tier()
        return {
            "tiers": grouped,
            "totals": {k: len(v) for k, v in grouped.items()},
            "fetched_at": _now(),
        }

    @router.post("/promote/{ticker}")
    def promote(ticker: str, body: PromoteBody) -> Dict[str, Any]:
        t = _t(ticker)
        if body.tier not in _VALID_TIERS:
            raise HTTPException(400, f"tier must be one of {sorted(_VALID_TIERS)}")
        parent = _t(body.parent_ticker) if body.parent_ticker else None
        if body.tier == "core" and parent is not None:
            # Core tickers don't have parents — silently drop the parent
            # rather than 400, since the UI may pass a stale parent on
            # promote-to-core.
            parent = None
        # Only `adjacent` has spoke semantics ("derived from a core's
        # 10-K"). `watching` is alert-only — requiring a parent here
        # over-constrains the data model and blocks legitimate flows
        # like the outside-ring discovery promote (no parent context
        # available there).
        if body.tier == "adjacent" and parent is None:
            raise HTTPException(400, "tier=adjacent requires parent_ticker (semantic spoke)")
        # Soft cap per tier — protects against runaway growth.
        ensure_schema()
        with connect() as conn:
            cur = conn.execute(
                "SELECT tier AS prev FROM user_watchlist WHERE ticker = ?", (t,))
            prev_row = cur.fetchone()
            from_tier = prev_row["prev"] if prev_row else None

            cur = conn.execute(
                "SELECT COUNT(*) AS n FROM user_watchlist WHERE tier = ? AND ticker != ?",
                (body.tier, t),
            )
            existing = cur.fetchone()["n"]
            if existing >= _TIER_LIMITS[body.tier]:
                raise HTTPException(
                    413,
                    f"tier={body.tier} already at limit ({_TIER_LIMITS[body.tier]}) — "
                    "demote or drop something first",
                )
            now = _now()
            conn.execute(
                "INSERT INTO user_watchlist "
                "  (ticker, tier, parent_ticker, note, importance, added_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(ticker) DO UPDATE SET "
                "  tier = excluded.tier, "
                "  parent_ticker = excluded.parent_ticker, "
                "  note = COALESCE(excluded.note, user_watchlist.note), "
                "  importance = excluded.importance",
                (t, body.tier, parent, body.note or "", body.importance, now),
            )

            # Phase W audit trail — record the action + trigger.
            # Determine action: promote (going up tier rank), demote
            # (going down), or just 'promote' for first-time add.
            tier_rank = {"core": 3, "adjacent": 2, "watching": 1}
            if from_tier is None:
                action = "promote"
            elif tier_rank[body.tier] > tier_rank[from_tier]:
                action = "promote"
            elif tier_rank[body.tier] < tier_rank[from_tier]:
                action = "demote"
            else:
                action = "review"  # same-tier update (e.g. note edit)
            import uuid as _uuid
            conn.execute(
                "INSERT INTO watchlist_audit "
                "(audit_id, ticker, action, from_tier, to_tier, "
                " trigger_kind, trigger_ref_id, ts, note) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (str(_uuid.uuid4()), t, action, from_tier, body.tier,
                 body.trigger_kind or "manual",
                 body.trigger_ref_id, now, body.note),
            )

        # 2026-05-16 (Need #7 discipline): compute velocity warning —
        # how many promotes to core have happened in the last 7 days?
        # >5 = velocity warning surfaced to frontend; not blocking.
        velocity_warning = None
        if body.tier == "core":
            with connect() as conn:
                count = conn.execute(
                    "SELECT COUNT(*) AS n FROM watchlist_audit "
                    "WHERE action = 'promote' "
                    "  AND to_tier = 'core' "
                    "  AND datetime(ts) >= datetime('now', '-7 days')"
                ).fetchone()["n"]
            if count > 5:
                velocity_warning = (
                    f"⚠ velocity: {count} promotes to core in last 7d — "
                    f"slow down? Discipline cap is 'few high-conviction', "
                    f"not 'add what's loud this week'."
                )

        return {
            "ok": True, "ticker": t, "tier": body.tier,
            "parent_ticker": parent, "from_tier": from_tier, "action": action,
            "velocity_warning": velocity_warning,
        }

    @router.post("/touch/{ticker}")
    def touch(ticker: str) -> Dict[str, Any]:
        """Bump last_reviewed_at — called by the drawer open hook so
        opening a ticker counts as 'reviewed today' and resets the
        14-day stale-thesis timer."""
        t = _t(ticker)
        ensure_schema()
        with connect() as conn:
            cur = conn.execute(
                "UPDATE user_watchlist SET last_reviewed_at = ? WHERE ticker = ?",
                (_now(), t),
            )
            if cur.rowcount == 0:
                # Ticker not in watchlist — silently no-op so opening
                # a non-watchlisted ticker doesn't 404.
                return {"ok": True, "ticker": t, "in_watchlist": False}
        return {"ok": True, "ticker": t, "in_watchlist": True}

    @router.delete("/tickers/{ticker}")
    def remove(ticker: str) -> Dict[str, Any]:
        t = _t(ticker)
        ensure_schema()
        with connect() as conn:
            cur = conn.execute(
                "SELECT tier FROM user_watchlist WHERE ticker = ?", (t,))
            row = cur.fetchone()
            from_tier = row["tier"] if row else None

            # Cascade: any adjacent/watching with parent_ticker = this t
            # is now an orphan. Null out the parent so the spoke edge
            # disappears cleanly — keeps the adjacent in the watchlist
            # (user research isn't lost) but flags it as parent-less.
            # User can re-parent later via the drawer's expand flow,
            # or drop the adjacent if it no longer makes sense.
            orphan_rows = conn.execute(
                "SELECT ticker FROM user_watchlist WHERE parent_ticker = ?",
                (t,),
            ).fetchall()
            n_orphans = len(orphan_rows)
            if n_orphans:
                conn.execute(
                    "UPDATE user_watchlist SET parent_ticker = NULL "
                    "WHERE parent_ticker = ?",
                    (t,),
                )

            cur = conn.execute("DELETE FROM user_watchlist WHERE ticker = ?", (t,))
            n = cur.rowcount
            if n > 0:
                import uuid as _uuid
                conn.execute(
                    "INSERT INTO watchlist_audit "
                    "(audit_id, ticker, action, from_tier, to_tier, "
                    " trigger_kind, ts, note) "
                    "VALUES (?, ?, 'drop', ?, NULL, 'manual', ?, ?)",
                    (str(_uuid.uuid4()), t, from_tier, _now(),
                     f"orphaned {n_orphans} adjacent(s)" if n_orphans else None),
                )
        if n == 0:
            raise HTTPException(404, f"{t} not in watchlist")
        return {"ok": True, "ticker": t, "orphaned_adjacents": n_orphans}

    @router.get("/suggestions/{ticker}")
    def suggestions(ticker: str) -> Dict[str, Any]:
        return {"ticker": _t(ticker), "suggestions": _suggestions_for(ticker)}

    @router.get("/audit/{ticker}")
    def audit_for(ticker: str, limit: int = Query(50, ge=1, le=500)) -> Dict[str, Any]:
        """History of promote/demote/drop/thesis actions for a ticker.
        Powers the chain panel's INCOMING section ('why on radar').
        Per plan §5 Pillar 4."""
        t = _t(ticker)
        ensure_schema()
        with connect() as conn:
            rows = conn.execute(
                "SELECT audit_id, action, from_tier, to_tier, "
                "       trigger_kind, trigger_ref_id, ts, note "
                "FROM watchlist_audit WHERE ticker = ? "
                "ORDER BY ts DESC LIMIT ?",
                (t, limit),
            ).fetchall()
        return {
            "ticker": t,
            "events": [dict(r) for r in rows],
            "count": len(rows),
        }

    @router.get("/outside_ring")
    def outside_ring(limit: int = Query(20, ge=1, le=100)) -> Dict[str, Any]:
        return {
            "candidates": _outside_ring(limit=limit),
            "lookback_days": 14,
            "fetched_at": _now(),
        }

    return router
