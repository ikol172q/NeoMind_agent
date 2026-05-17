"""Portfolio onion+chain unified graph endpoint — Phase 5.

Per plan plans/2026-05-10_lattice-onion-integration.md §5 Pillar 1
(Visualization). Returns a single graph payload the frontend renders
as concentric rings (onion) with selectively-materialized chain
edges (per progressive-disclosure design).

Data sources (all pre-existing):
  - user_watchlist     → ring assignment (Core/Adjacent/Watching)
  - stock_anchored_facts → 10-K relationship edges (competitor / customer / supplier)
  - signal_events      → fresh-signal pulse markers
  - tax_lots           → ME node + position weights
  - investment_theses  → thesis health badge per ticker

Endpoints:
  GET /api/lattice/portfolio_view → full graph (nodes + edges + metadata)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query

from agent.finance.persistence import connect, ensure_schema
from agent.finance.ticker_aliases import name_to_ticker

logger = logging.getLogger(__name__)


_FRESH_SIGNAL_HOURS = 24
_STALE_REVIEW_DAYS = {"core": 14, "adjacent": 30, "watching": 90, "outside": 9999}
_OUTSIDE_LOOKBACK_DAYS = 14
_OUTSIDE_LIMIT = 12


def build_portfolio_view_router() -> APIRouter:
    router = APIRouter(prefix="/api/lattice", tags=["portfolio-view"])

    @router.get("/portfolio_view")
    def portfolio_view(
        as_of: Optional[str] = Query(None, description="ISO date YYYY-MM-DD; filters derived data to <= as_of"),
        include_external_edges: bool = Query(
            False,
            description=(
                "Include 10-K relation edges (competitor/customer/supplier) "
                "whose target is OUTSIDE the user's watchlist. Off by default "
                "to avoid cluttering the main onion; toggle on for discovery."
            ),
        ),
    ) -> Dict[str, Any]:
        return _build_graph(as_of=as_of, include_external_edges=include_external_edges)

    @router.get("/chain/{ticker}")
    def chain_for_ticker(ticker: str, hop: int = 2) -> Dict[str, Any]:
        """Lazy multi-hop chain expansion (plan §5 Pillar 1 enhancement #1).
        Returns the nodes/edges reachable from `ticker` within `hop`
        steps, INCLUDING entities not in the user watchlist (e.g.
        TSMC's risks). Non-watchlist nodes are tagged `tier='external'`
        so the frontend renders them as faint discovery placeholders.

        Edges only traverse 10-K extracted relations (competitor /
        customer / supplier). Spoke edges from watchlist are already
        covered by portfolio_view.
        """
        ticker = ticker.upper()
        hop = max(1, min(3, hop))
        ensure_schema()
        with connect() as conn:
            wl = {r["ticker"] for r in conn.execute(
                "SELECT ticker FROM user_watchlist"
            ).fetchall()}
            # BFS: for each ticker in frontier, fetch its rel facts and
            # add new nodes/edges. Track depth so caller can render
            # hop level (1 = origin, 2 = direct, 3 = neighbors-of).
            depth: Dict[str, int] = {ticker: 0}
            nodes_map: Dict[str, Dict[str, Any]] = {}
            edges_out: List[Dict[str, Any]] = []
            frontier = [ticker]
            for _ in range(hop):
                if not frontier:
                    break
                rows = conn.execute(
                    f"SELECT ticker AS owner, fact_type, payload_json "
                    f"FROM stock_anchored_facts "
                    f"WHERE ticker IN ({','.join('?' * len(frontier))}) "
                    f"  AND fact_type IN ('competitor','customer','supplier')",
                    tuple(frontier),
                ).fetchall()
                next_frontier: List[str] = []
                for r in rows:
                    owner = r["owner"]
                    try:
                        payload = json.loads(r["payload_json"] or "{}")
                    except json.JSONDecodeError:
                        continue
                    rel_ticker = (payload.get("ticker") or "").strip().upper()
                    rel_name = (payload.get("name") or "").strip()
                    # If the LLM only gave us a name, try the curated
                    # NAME_TO_TICKER lookup so external entities collapse
                    # to their watchlist ticker counterparts.
                    if not rel_ticker and rel_name:
                        mapped = name_to_ticker(rel_name)
                        if mapped:
                            rel_ticker = mapped
                    rel_id = rel_ticker or f"name:{rel_name}"
                    if not rel_id or rel_id == owner:
                        continue
                    if rel_id not in depth:
                        d = depth[owner] + 1
                        depth[rel_id] = d
                        nodes_map[rel_id] = {
                            "id":          rel_id,
                            "label":       rel_ticker or rel_name,
                            "ticker":      rel_ticker or None,
                            "name":        rel_name or None,
                            "in_watchlist": rel_ticker in wl if rel_ticker else False,
                            "tier":        ("watchlist" if rel_ticker and rel_ticker in wl
                                            else "external"),
                            "hop":         d,
                        }
                        if rel_ticker and rel_ticker not in wl:
                            # External: don't recurse further — we
                            # have no facts on it.
                            pass
                        elif rel_ticker and rel_ticker in wl:
                            next_frontier.append(rel_ticker)
                    edges_out.append({
                        "source": owner,
                        "target": rel_id,
                        "kind":   r["fact_type"],
                        "hop":    depth[owner] + 1,
                    })
                frontier = next_frontier
            # Origin node
            if ticker not in nodes_map:
                nodes_map[ticker] = {
                    "id":          ticker,
                    "label":       ticker,
                    "ticker":      ticker,
                    "name":        None,
                    "in_watchlist": ticker in wl,
                    "tier":        "watchlist" if ticker in wl else "external",
                    "hop":         0,
                }
        return {
            "origin":  ticker,
            "hop":     hop,
            "nodes":   list(nodes_map.values()),
            "edges":   edges_out,
            "n_nodes": len(nodes_map),
            "n_edges": len(edges_out),
        }

    @router.get("/disagreements/{ticker}")
    def disagreements_for_ticker(ticker: str) -> Dict[str, Any]:
        """Per-ticker unresolved signal disagreements for the chain panel.
        Sources_json is parsed AND each source is enriched with the
        actual signal_event that triggered it (matched by ticker +
        scanner_name + signal_type within ±24h of detected_at).
        Honors the "有根有据" principle: every scanner claim in the
        disagreement is one click away from its source URL.
        """
        ensure_schema()
        with connect() as conn:
            rows = conn.execute(
                "SELECT disagreement_id, headline, sources_json, detected_at "
                "FROM signal_disagreements "
                "WHERE ticker = ? AND resolved_at IS NULL "
                "ORDER BY detected_at DESC",
                (ticker.upper(),),
            ).fetchall()
            items: List[Dict[str, Any]] = []
            for r in rows:
                try:
                    sources = json.loads(r["sources_json"] or "[]")
                except json.JSONDecodeError:
                    sources = []
                detected_at = r["detected_at"]
                # Enrich each source: match the underlying signal_event
                # by (ticker, scanner, signal_type) closest to detected_at.
                # ±24h window because confluence detector usually groups
                # within a day.
                try:
                    dt = datetime.fromisoformat(detected_at.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    win_lo = (dt - timedelta(hours=24)).isoformat()
                    win_hi = (dt + timedelta(hours=24)).isoformat()
                except Exception:
                    win_lo = None
                    win_hi = None
                enriched_sources = []
                for s in sources:
                    scanner = (s or {}).get("scanner")
                    signal_type = (s or {}).get("signal_type")
                    enrich = {**(s if isinstance(s, dict) else {}),
                              "event_id": None, "source_url": None,
                              "title": None, "severity": None, "ts": None}
                    if scanner and signal_type and win_lo and win_hi:
                        ev = conn.execute(
                            "SELECT event_id, source_url, title, severity, detected_at "
                            "FROM signal_events "
                            "WHERE ticker = ? AND scanner_name = ? "
                            "  AND signal_type = ? "
                            "  AND detected_at BETWEEN ? AND ? "
                            "ORDER BY detected_at DESC LIMIT 1",
                            (ticker.upper(), scanner, signal_type, win_lo, win_hi),
                        ).fetchone()
                        if ev:
                            enrich["event_id"]   = ev["event_id"]
                            enrich["source_url"] = ev["source_url"]
                            enrich["title"]      = ev["title"]
                            enrich["severity"]   = ev["severity"]
                            enrich["ts"]         = ev["detected_at"]
                    enriched_sources.append(enrich)
                items.append({
                    "disagreement_id": r["disagreement_id"],
                    "headline":        r["headline"],
                    "sources":         enriched_sources,
                    "detected_at":     detected_at,
                })
        return {"ticker": ticker.upper(), "items": items, "n": len(items)}

    @router.post("/disagreements/{disagreement_id}/resolve")
    def resolve_disagreement(disagreement_id: str, note: str = "") -> Dict[str, Any]:
        """Mark a disagreement resolved with optional note."""
        ensure_schema()
        with connect() as conn:
            cur = conn.execute(
                "UPDATE signal_disagreements "
                "SET resolved_at = ?, resolution_note = ? "
                "WHERE disagreement_id = ? AND resolved_at IS NULL",
                (datetime.now(timezone.utc).isoformat(), note or None, disagreement_id),
            )
            if cur.rowcount == 0:
                from fastapi import HTTPException
                raise HTTPException(404, f"disagreement {disagreement_id} not found or already resolved")
        return {"ok": True, "disagreement_id": disagreement_id}

    return router


def _parse_as_of(as_of: Optional[str]) -> Optional[datetime]:
    """Accept 'YYYY-MM-DD' (interpreted as end-of-day UTC) or full ISO.
    Returns None if as_of is unset / empty / invalid."""
    if not as_of:
        return None
    try:
        # Plain date → end-of-day so user including "today" gets all of today.
        if len(as_of) == 10 and as_of[4] == "-" and as_of[7] == "-":
            d = datetime.fromisoformat(as_of)
            return d.replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
        return datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    except Exception:
        return None


def _build_graph(as_of: Optional[str] = None, include_external_edges: bool = False) -> Dict[str, Any]:
    """Compose nodes + edges from watchlist + facts + signals + positions.

    `as_of` (ISO date or datetime) filters derived per-node data to what
    existed on or before that timestamp. Watchlist tier membership is
    NOT replayed from audit (yet) — only entries with `added_at <= as_of`
    are included. So time-travel is approximate for watchlist
    composition; precise for facts / signals / theses / disagreements /
    positions.
    """
    ensure_schema()
    now = datetime.now(timezone.utc)
    cutoff_dt = _parse_as_of(as_of)
    is_historical = cutoff_dt is not None and cutoff_dt < now - timedelta(minutes=5)
    # Effective "now" for staleness / freshness calcs. When time-traveling,
    # this is the as_of timestamp so "fresh in last 24h" means
    # "fresh in the 24h preceding as_of".
    ref_now = cutoff_dt or now
    fresh_cutoff = (ref_now - timedelta(hours=_FRESH_SIGNAL_HOURS)).isoformat()
    cutoff_iso = cutoff_dt.isoformat() if cutoff_dt else None

    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    watchlist_tickers: set = set()

    with connect() as conn:
        # Time-travel: replay watchlist tier history from audit log so
        # `as_of` views reflect the state AT that timestamp, not "current
        # tiers minus late additions". Builds a {ticker → effective_tier
        # at as_of} dict (None = not in watchlist at as_of). The
        # outer SQL still uses `added_at <= ?` for tickers without
        # audit history (i.e., original seeds).
        tier_at_asof: Dict[str, Optional[str]] = {}
        if cutoff_iso:
            # Only tier-changing actions matter for replay. thesis_create
            # / thesis_invalidate / note / review are audit-only events
            # with to_tier=NULL — they do NOT mean the ticker was dropped.
            audit_rows = conn.execute(
                "SELECT ticker, action, to_tier, ts FROM watchlist_audit "
                "WHERE ts <= ? "
                "  AND action IN ('promote','demote','drop') "
                "ORDER BY ts ASC",
                (cutoff_iso,),
            ).fetchall()
            history: Dict[str, List[Any]] = {}
            for r in audit_rows:
                history.setdefault(r["ticker"], []).append(r)
            for ticker, evs in history.items():
                last = evs[-1]
                if last["action"] == "drop":
                    tier_at_asof[ticker] = None
                else:
                    tier_at_asof[ticker] = last["to_tier"]

        # Build SQL filters conditionally. When as_of is set:
        #  · watchlist: only entries added on/before as_of
        #  · facts:    only extracted on/before as_of
        #  · signals:  detected_at between fresh_cutoff..as_of
        #  · theses:   created_at <= as_of AND (invalidated_at IS NULL OR > as_of)
        #  · disagreements: detected_at <= as_of AND (resolved_at IS NULL OR > as_of)
        watch_filter   = "AND w.added_at <= ?"        if cutoff_iso else ""
        fact_filter    = "AND f.extracted_at <= ?"    if cutoff_iso else ""
        signal_filter  = "AND e.detected_at <= ?"     if cutoff_iso else ""
        thesis_active_filter = (
            "AND t.created_at <= ? "
            "AND (t.invalidated_at IS NULL OR t.invalidated_at > ?)"
        ) if cutoff_iso else ""
        disagreement_filter = (
            "AND d.detected_at <= ? "
            "AND (d.resolved_at IS NULL OR d.resolved_at > ?)"
        ) if cutoff_iso else ""

        # Build parameter tuple in the textual order of placeholders:
        #   1. n_facts.fact_filter            ? (if cutoff)
        #   2. has_fresh_signal.fresh_cutoff  ? (always)
        #   3. has_fresh_signal.signal_filter ? (if cutoff)
        #   4-5. n_active_theses.thesis_active_filter (2 params, if cutoff)
        #   6-7. thesis_status.thesis_active_filter   (2 params, if cutoff)
        #   8-9. disagreements.disagreement_filter    (2 params, if cutoff)
        #   10. watch_filter                  ? (if cutoff)
        params: list = []
        if cutoff_iso:
            params.append(cutoff_iso)                # fact_filter (n_facts)
        params.append(fresh_cutoff)                  # has_fresh_signal ≥
        if cutoff_iso:
            params.append(cutoff_iso)                # signal_filter
            params.extend([cutoff_iso, cutoff_iso])  # n_active_theses
            params.extend([cutoff_iso, cutoff_iso])  # thesis_status MIN
            params.extend([cutoff_iso, cutoff_iso])  # n_unresolved_disagreements
            params.append(cutoff_iso)                # watch_filter (outer)

        rows = conn.execute(
            f"SELECT w.ticker, w.tier, w.parent_ticker, w.last_reviewed_at, w.importance, "
            f"       (SELECT COUNT(*) FROM stock_anchored_facts f "
            f"         WHERE f.ticker = w.ticker {fact_filter}) AS n_facts, "
            f"       (SELECT 1 FROM signal_events e "
            f"         WHERE e.ticker = w.ticker AND e.detected_at >= ? "
            f"               {signal_filter} "
            f"         LIMIT 1) AS has_fresh_signal, "
            f"       (SELECT COUNT(*) FROM investment_theses t "
            f"         WHERE t.ticker = w.ticker "
            f"           AND t.status IN ('active','requires_review') "
            f"           {thesis_active_filter}) AS n_active_theses, "
            # thesis_status: priority-aware. requires_review wins over
            # active when both exist on the same ticker — otherwise the
            # MIN() alphabetical sort would silently hide the
            # review-needed warning ('active' < 'requires_review'
            # lexicographically). We collapse the two into a CASE so the
            # rollup preserves the priority order.
            f"       (SELECT CASE "
            f"                 WHEN MAX(CASE WHEN t.status='requires_review' THEN 1 ELSE 0 END) = 1 "
            f"                   THEN 'requires_review' "
            f"                 WHEN MAX(CASE WHEN t.status='active' THEN 1 ELSE 0 END) = 1 "
            f"                   THEN 'active' "
            f"                 ELSE NULL END "
            f"        FROM investment_theses t "
            f"         WHERE t.ticker = w.ticker "
            f"           AND t.status IN ('active','requires_review') "
            f"           {thesis_active_filter}) AS thesis_status, "
            f"       (SELECT COUNT(*) FROM signal_disagreements d "
            f"         WHERE d.ticker = w.ticker "
            f"           AND d.resolved_at IS NULL "
            f"           {disagreement_filter}) AS n_unresolved_disagreements "
            f"FROM user_watchlist w "
            f"WHERE 1=1 {watch_filter} "
            f"ORDER BY w.tier, w.ticker",
            tuple(params),
        ).fetchall()
        for r in rows:
            ticker = r["ticker"]
            # Apply audit replay: skip if dropped at as_of, else use
            # historical tier when audit captured a change.
            if cutoff_iso and ticker in tier_at_asof:
                replayed = tier_at_asof[ticker]
                if replayed is None:
                    continue  # was dropped at/before as_of
                tier = replayed
            else:
                tier = r["tier"] or "core"
            watchlist_tickers.add(ticker)
            stale_days = None
            if r["last_reviewed_at"]:
                try:
                    last = datetime.fromisoformat(r["last_reviewed_at"].replace("Z", "+00:00"))
                    if last.tzinfo is None:
                        last = last.replace(tzinfo=timezone.utc)
                    stale_days = int((now - last).total_seconds() / 86400)
                except Exception:
                    pass
            review_window = _STALE_REVIEW_DAYS.get(tier, 14)
            is_stale = (stale_days is None) or (stale_days > review_window)
            nodes.append({
                "id":               ticker,
                "tier":             tier,
                "parent":           r["parent_ticker"],
                "n_facts":          r["n_facts"] or 0,
                "stale_days":       stale_days,
                "is_stale":         is_stale,
                "fresh_signal_24h": bool(r["has_fresh_signal"]),
                "n_active_theses":  r["n_active_theses"] or 0,
                "thesis_status":    r["thesis_status"],
                "n_unresolved_disagreements": r["n_unresolved_disagreements"] or 0,
                "is_conflicted":    (r["n_unresolved_disagreements"] or 0) > 0,
                "importance":       r["importance"] or 1,
            })
            # Spoke edge: Adjacent/Watching → parent (always shown).
            # Skip emitting the edge when the parent has been dropped
            # from user_watchlist — otherwise ForceGraph2D rejects the
            # link with `Error: node not found: <parent>` because no
            # node was emitted for the orphaned parent. The adjacent
            # row keeps its parent_ticker reference in the DB (so the
            # link can be restored if the parent is re-promoted), but
            # the graph payload only emits resolvable edges.
            parent = r["parent_ticker"]
            if parent and parent != ticker:
                # We can't check watchlist_tickers yet because we're
                # mid-iteration over the same query. Defer this edge
                # until after the loop completes and we know which
                # tickers actually made it into nodes.
                edges.append({
                    "source":   ticker,
                    "target":   parent,
                    "kind":     "spoke",
                    "label":    f"adjacent of {parent}",
                    "_pending": True,  # filtered below
                })

        # Next-earnings overlay: per ticker, the smallest days_until from
        # any recent earnings_upcoming signal_event. Lets the frontend draw
        # a glow ring on nodes whose ticker reports within 5d — high-
        # priority catalyst the user must visually catch when scanning.
        try:
            earnings_rows = conn.execute(
                "SELECT ticker, "
                "       MIN(CAST(json_extract(body_json,'$.days_until') AS INTEGER)) AS days "
                "FROM signal_events "
                "WHERE signal_type = 'earnings_upcoming' "
                "  AND datetime(detected_at) >= datetime('now', '-14 days') "
                "  AND ticker IS NOT NULL "
                "GROUP BY ticker"
            ).fetchall()
            earnings_by_ticker = {
                r["ticker"]: r["days"] for r in earnings_rows
                if r["days"] is not None and r["days"] >= 0
            }
            for n in nodes:
                d = earnings_by_ticker.get(n["id"])
                if d is not None:
                    n["next_earnings_days"] = d
        except Exception as exc:
            logger.debug("earnings overlay failed: %s", exc)

        # Held-but-unwatched: positions in tax_lots whose ticker is NOT in
        # any watchlist tier. Without this, the user has real $ on a
        # ticker that has zero research surface (no facts, no thesis,
        # no signal pulse). Surface it as its own ring so the gap is
        # impossible to miss — the user can either promote it to a tier
        # or close the lot.
        try:
            if cutoff_iso:
                held_unwatched_rows = conn.execute(
                    "SELECT DISTINCT symbol, SUM(open_quantity) AS qty, "
                    "       SUM(open_price * open_quantity + open_fees) AS cost "
                    "FROM tax_lots "
                    "WHERE open_date <= ? "
                    "  AND (close_date IS NULL OR close_date > ?) "
                    "  AND symbol NOT IN (SELECT ticker FROM user_watchlist) "
                    "GROUP BY symbol",
                    (cutoff_iso, cutoff_iso),
                ).fetchall()
            else:
                held_unwatched_rows = conn.execute(
                    "SELECT DISTINCT symbol, SUM(open_quantity) AS qty, "
                    "       SUM(open_price * open_quantity + open_fees) AS cost "
                    "FROM tax_lots "
                    "WHERE close_date IS NULL "
                    "  AND symbol NOT IN (SELECT ticker FROM user_watchlist) "
                    "GROUP BY symbol"
                ).fetchall()
            for r in held_unwatched_rows:
                tk = r["symbol"]
                if not tk:
                    continue
                nodes.append({
                    "id":               tk,
                    "tier":             "held_unwatched",
                    "parent":           None,
                    "n_facts":          0,
                    "stale_days":       None,
                    "is_stale":         False,
                    "fresh_signal_24h": False,
                    "n_active_theses":  0,
                    "thesis_status":    None,
                    "n_unresolved_disagreements": 0,
                    "is_conflicted":    False,
                    "importance":       1,
                    "held_qty":         r["qty"],
                    "held_cost":        r["cost"],
                })
        except Exception as exc:
            logger.debug("held-unwatched scan failed: %s", exc)

        # Position weight overlay — for any watchlist ticker that user owns.
        # When time-traveling, include lots opened on/before as_of and not
        # closed before as_of (close_date NULL or > as_of).
        try:
            if cutoff_iso:
                pos_rows = conn.execute(
                    "SELECT symbol, SUM(open_quantity) AS qty, "
                    "       SUM(open_price * open_quantity + open_fees) AS cost "
                    "FROM tax_lots "
                    "WHERE open_date <= ? "
                    "  AND (close_date IS NULL OR close_date > ?) "
                    "GROUP BY symbol",
                    (cutoff_iso, cutoff_iso),
                ).fetchall()
            else:
                pos_rows = conn.execute(
                    "SELECT symbol, SUM(open_quantity) AS qty, "
                    "       SUM(open_price * open_quantity + open_fees) AS cost "
                    "FROM tax_lots WHERE close_date IS NULL "
                    "GROUP BY symbol"
                ).fetchall()
            held = {r["symbol"]: dict(r) for r in pos_rows}
            for n in nodes:
                if n["id"] in held:
                    n["held_qty"] = held[n["id"]]["qty"]
                    n["held_cost"] = held[n["id"]]["cost"]
                else:
                    n["held_qty"] = None
        except Exception as exc:
            logger.debug("position overlay failed: %s", exc)

        # Outside-ring candidates — high-confluence scanner signals on
        # tickers NOT in any watchlist tier (anti-anchoring per
        # plan §5 Pillar 1 ring 4). Reuse the same lookback+ranking
        # already exposed via /api/watchlist/outside_ring. When time-
        # traveling, lookback ends at as_of (not real-now).
        try:
            outside_cutoff = (ref_now - timedelta(days=_OUTSIDE_LOOKBACK_DAYS)).isoformat()
            outside_params: list = [outside_cutoff]
            outside_upper = ""
            if cutoff_iso:
                outside_upper = "AND e.detected_at <= ? "
                outside_params.append(cutoff_iso)
            outside_params.append(_OUTSIDE_LIMIT)
            outside_rows = conn.execute(
                f"SELECT e.ticker, "
                f"       COUNT(*) AS n_events, "
                f"       COUNT(DISTINCT e.scanner_name) AS n_sources, "
                f"       MAX(e.detected_at) AS latest_at, "
                f"       SUM(CASE WHEN e.severity='high' THEN 1 ELSE 0 END) AS n_high "
                f"FROM signal_events e "
                f"WHERE e.ticker IS NOT NULL "
                f"  AND e.detected_at >= ? "
                f"  {outside_upper}"
                f"  AND e.severity IN ('high','med') "
                f"  AND e.ticker NOT IN (SELECT ticker FROM user_watchlist) "
                f"GROUP BY e.ticker "
                f"HAVING COUNT(DISTINCT e.scanner_name) >= 2 "
                f"ORDER BY n_high DESC, n_sources DESC, n_events DESC "
                f"LIMIT ?",
                tuple(outside_params),
            ).fetchall()
            for r in outside_rows:
                ticker = r["ticker"]
                if not ticker:
                    continue
                nodes.append({
                    "id":               ticker,
                    "tier":             "outside",
                    "parent":           None,
                    "n_facts":          0,
                    "stale_days":       None,
                    "is_stale":         False,
                    "fresh_signal_24h": False,
                    "n_active_theses":  0,
                    "thesis_status":    None,
                    "n_unresolved_disagreements": 0,
                    "is_conflicted":    False,
                    "n_outside_events": r["n_events"] or 0,
                    "n_outside_sources": r["n_sources"] or 0,
                    "n_outside_high":   r["n_high"] or 0,
                    "outside_latest_at": r["latest_at"],
                })
        except Exception as exc:
            logger.debug("outside ring scan failed (signal_events table may be empty): %s", exc)

        # 10-K relationship edges — competitor / customer / supplier.
        # Marked kind != 'spoke' so frontend can default-hide and only
        # show on selected node. When time-traveling, only edges
        # extracted on/before as_of are included.
        if cutoff_iso:
            rel_rows = conn.execute(
                "SELECT ticker, fact_type, payload_json "
                "FROM stock_anchored_facts "
                "WHERE fact_type IN ('competitor','customer','supplier') "
                "  AND extracted_at <= ?",
                (cutoff_iso,),
            ).fetchall()
        else:
            rel_rows = conn.execute(
                "SELECT ticker, fact_type, payload_json "
                "FROM stock_anchored_facts "
                "WHERE fact_type IN ('competitor','customer','supplier')"
            ).fetchall()
        for r in rel_rows:
            owner = r["ticker"]
            if owner not in watchlist_tickers:
                continue   # only edges where origin is in our universe
            try:
                payload = json.loads(r["payload_json"] or "{}")
            except json.JSONDecodeError:
                continue
            related = (payload.get("ticker") or "").strip().upper()
            related_name = payload.get("name", "")
            if not related:
                # Name-only entity (no ticker resolved). Skip even with
                # include_external_edges because the chain endpoint
                # handles name-only discovery via BFS.
                continue
            if related not in watchlist_tickers:
                if not include_external_edges:
                    continue
                # Emit a node for the external target so ForceGraph2D
                # has somewhere to anchor the edge. Tier='external'
                # places it in the outer ring.
                # Avoid duplicate nodes when multiple edges point to the
                # same external ticker.
                already_node = any(n["id"] == related for n in nodes)
                if not already_node:
                    nodes.append({
                        "id":               related,
                        "tier":             "external",
                        "parent":           None,
                        "n_facts":          0,
                        "stale_days":       None,
                        "is_stale":         False,
                        "fresh_signal_24h": False,
                        "n_active_theses":  0,
                        "thesis_status":    None,
                        "n_unresolved_disagreements": 0,
                        "is_conflicted":    False,
                        "importance":       1,
                        "external_label":   related_name,
                    })
            edges.append({
                "source": owner,
                "target": related,
                "kind":   r["fact_type"],
                "label":  f"{owner} → {related} ({r['fact_type']}: {related_name})",
            })

    # Resolve pending spoke edges: only keep those where the parent is
    # actually in our nodes set (i.e. still in user_watchlist). Drop
    # the marker key from the emitted payload.
    node_ids = {n["id"] for n in nodes}
    resolved_edges: List[Dict[str, Any]] = []
    n_orphan_spokes = 0
    for e in edges:
        if e.get("_pending") and e["target"] not in node_ids:
            n_orphan_spokes += 1
            continue
        if "_pending" in e:
            del e["_pending"]
        resolved_edges.append(e)

    return {
        "nodes":        nodes,
        "edges":        resolved_edges,
        "n_nodes":      len(nodes),
        "n_edges":      len(resolved_edges),
        "n_spoke":      sum(1 for e in resolved_edges if e["kind"] == "spoke"),
        "n_relations":  sum(1 for e in resolved_edges if e["kind"] != "spoke"),
        "n_orphan_spokes": n_orphan_spokes,
        "fetched_at":   now.isoformat(),
        "as_of":        cutoff_dt.isoformat() if cutoff_dt else None,
        "is_historical": is_historical,
    }
