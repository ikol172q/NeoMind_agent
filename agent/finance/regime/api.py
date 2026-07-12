"""FastAPI routes for the regime pipeline.

Mounted in dashboard_server.py:

    from agent.finance.regime.api import router as regime_router
    app.include_router(regime_router)

Endpoints:

    GET  /api/regime/today            — today's fingerprint (compute if missing)
    GET  /api/regime/at?date=YYYY-MM-DD — historical fingerprint (compute if missing)
    GET  /api/regime/history           — list recent fingerprints
    POST /api/regime/ingest            — trigger one-shot yfinance pull
    POST /api/regime/backfill          — one-shot historical backfill
"""
from __future__ import annotations

import json
import logging
from datetime import date as _date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/regime", tags=["fin-regime"])


@router.get("/portfolio")
def get_portfolio(
    as_of: Optional[str] = Query(None, description="'live' or YYYY-MM-DD"),
    n_alternatives: int = Query(5, ge=1, le=8, description="how many alternatives (3-8)"),
    lambda_weight: float = Query(0.65, ge=0.0, le=1.0, description="MMR balance: 1=pure relevance, 0=pure diversity"),
) -> Dict[str, Any]:
    """Diversified portfolio selection.

    Returns top-1 most-recommended strategy plus N MMR-selected
    alternatives that are similar in regime fit but DIFFERENT in
    payoff_class / asset_class so the user has real options.
    """
    from agent.finance.regime import fingerprint_for_date
    from agent.finance.regime.scorer import (
        score_all_strategies,
        select_diversified_portfolio,
    )

    fp_date = (as_of if as_of and as_of != "live"
               else _date.today().isoformat())
    try:
        fp = fingerprint_for_date(fp_date)
    except Exception as exc:
        raise HTTPException(503, f"fingerprint unavailable: {exc}")
    if not fp or all(
        fp.get(k) is None for k in (
            "risk_appetite_score", "volatility_regime_score",
            "breadth_score", "event_density_score", "flow_score",
        )
    ):
        raise HTTPException(503, "no fingerprint for date — run regime_backfill")

    # Load persisted user prefs (4-question onboarding) so the scorer
    # respects e.g. options_level=0 (filter out options strategies).
    user_prefs: Dict[str, Any] = {}
    try:
        user_prefs = get_prefs()
        # Drop meta keys
        user_prefs = {k: v for k, v in user_prefs.items() if not k.startswith("_")}
    except Exception:
        user_prefs = {}

    scored = score_all_strategies(fp, user_prefs=user_prefs, include_unverified=True)
    portfolio = select_diversified_portfolio(
        scored,
        n_alternatives=n_alternatives,
        lambda_weight=lambda_weight,
    )
    portfolio["user_prefs_used"] = user_prefs
    portfolio["fingerprint_date"] = fp_date
    portfolio["fingerprint"] = {
        "risk_appetite_score":     fp.get("risk_appetite_score"),
        "volatility_regime_score": fp.get("volatility_regime_score"),
        "breadth_score":           fp.get("breadth_score"),
        "event_density_score":     fp.get("event_density_score"),
        "flow_score":              fp.get("flow_score"),
    }

    # Persist decision traces — one row per (date × strategy) including
    # rank within today's portfolio + MMR alternative_weight. Lets the
    # Audit tab show "what did the agent recommend on date X and why?".
    try:
        from agent.finance.regime.store import write_decision_trace
        if portfolio.get("top"):
            top = portfolio["top"]
            write_decision_trace({
                "fingerprint_date": fp_date,
                "strategy_id": top["strategy_id"],
                "score": top["score"],
                "rank": 1,
                "alternative_weight": 1.0,
                "formula": top.get("formula", "regime_v2_closed_form"),
                "breakdown": top.get("traceback") or top.get("score_breakdown") or {},
                "portfolio_fit": {
                    "selection_method": portfolio["selection_method"],
                    "lambda": portfolio["lambda"],
                    "n_alternatives": portfolio.get("n_alternatives", 0),
                },
            })
            for idx, alt in enumerate(portfolio["alternatives"]):
                write_decision_trace({
                    "fingerprint_date": fp_date,
                    "strategy_id": alt["strategy_id"],
                    "score": alt["score"],
                    "rank": idx + 2,
                    "alternative_weight": float(alt.get("_mmr_score", 0) or 0),
                    "formula": alt.get("formula", "regime_v2_closed_form"),
                    "breakdown": alt.get("traceback") or alt.get("score_breakdown") or {},
                    "portfolio_fit": {
                        "selection_method": portfolio["selection_method"],
                        "lambda": portfolio["lambda"],
                        "_mmr_score": alt.get("_mmr_score"),
                        "_diversity_from_top": alt.get("_diversity_from_top"),
                    },
                })
    except Exception as exc:
        logger.warning("decision_traces write failed: %s", exc)

    return portfolio


@router.post("/backtest/run")
def post_backtest_run(
    since:         Optional[str] = Query(None, description="YYYY-MM-DD inclusive"),
    until:         Optional[str] = Query(None, description="YYYY-MM-DD inclusive"),
    hold_days:     int            = Query(30, ge=1, le=365),
    skip_existing: bool           = Query(True),
) -> Dict[str, Any]:
    """Run the backtest harness over historical fingerprints.

    For every fingerprint_date in [since, until], scores all strategies
    (model only — no k-NN to avoid circular reference) and computes
    realized 30d P&L proxy from raw_market_data forward returns.
    """
    from agent.finance.regime.backtest import run_backtest
    try:
        result = run_backtest(
            since=since, until=until,
            hold_days=hold_days, skip_existing=skip_existing,
        )
    except Exception as exc:
        logger.exception("backtest failed")
        raise HTTPException(500, f"backtest failed: {exc}")
    return result


@router.get("/backtest/recall")
def get_backtest_recall(
    hold_days:    int   = Query(30, ge=1, le=365),
    score_cutoff: float = Query(4.0, ge=0.0, le=10.0),
    strategy_id:  Optional[str] = Query(None),
) -> Dict[str, Any]:
    """Per-strategy calibration: how well does the predicted score
    correlate with the realized P&L proxy across history?"""
    from agent.finance.regime.backtest import recall_summary
    return recall_summary(
        hold_days=hold_days,
        score_cutoff=score_cutoff,
        strategy_id=strategy_id,
    )


@router.get("/backtest/rows")
def get_backtest_rows(
    fingerprint_date: Optional[str] = Query(None),
    strategy_id:      Optional[str] = Query(None),
    hold_days:        int            = Query(30, ge=1, le=365),
    limit:            int            = Query(500, ge=1, le=5000),
) -> Dict[str, Any]:
    """Raw backtest_results rows — one per (date × strategy)."""
    from agent.finance.persistence import connect
    sql = "SELECT * FROM backtest_results WHERE hold_days = ?"
    args: List[Any] = [hold_days]
    if fingerprint_date:
        sql += " AND fingerprint_date = ?"
        args.append(fingerprint_date)
    if strategy_id:
        sql += " AND strategy_id = ?"
        args.append(strategy_id)
    sql += " ORDER BY fingerprint_date DESC, rank ASC LIMIT ?"
    args.append(limit)
    with connect() as conn:
        rows = conn.execute(sql, args).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if d.get("notes_json"):
            try:
                d["notes"] = json.loads(d["notes_json"])
            except Exception:
                d["notes"] = None
            d.pop("notes_json", None)
        out.append(d)
    return {"count": len(out), "results": out}


@router.get("/traces")
def get_traces(
    fingerprint_date: Optional[str] = Query(None, description="filter by YYYY-MM-DD"),
    strategy_id: Optional[str]      = Query(None, description="filter by strategy id"),
    limit: int                      = Query(200, ge=1, le=2000),
) -> Dict[str, Any]:
    """List decision_traces — every (date × strategy) recommendation
    persisted by the portfolio endpoint, with full breakdown for drill."""
    from agent.finance.regime.store import list_decision_traces
    rows = list_decision_traces(
        fingerprint_date=fingerprint_date,
        strategy_id=strategy_id,
        limit=limit,
    )
    return {"count": len(rows), "traces": rows}


# ── Phase L: NeoMind Live signal system ───────────────────────────


@router.get("/watchlist")
def get_watchlist() -> Dict[str, Any]:
    """User's watchlist + auto-expanded supply-chain neighbors."""
    from agent.finance.regime.signals import (
        list_watchlist, expand_supply_chain,
    )
    wl = list_watchlist()
    user_tickers = [w["ticker"] for w in wl]
    expanded = expand_supply_chain(user_tickers)
    return {
        "user_watchlist":   wl,
        "supply_chain":     expanded,
        "total_universe":   sorted(set(user_tickers + expanded)),
    }


@router.post("/watchlist")
def post_watchlist(body: Dict[str, Any]) -> Dict[str, Any]:
    """Add a ticker to the watchlist.

    body: {"ticker": "NVDA", "note": "...", "importance": 1}
    """
    from agent.finance.regime.signals import add_to_watchlist
    ticker = body.get("ticker") or ""
    if not ticker:
        raise HTTPException(400, "ticker required")
    return add_to_watchlist(
        ticker,
        note=body.get("note"),
        importance=int(body.get("importance", 1)),
    )


@router.delete("/watchlist/{ticker}")
def delete_watchlist(ticker: str) -> Dict[str, Any]:
    from agent.finance.regime.signals import remove_from_watchlist
    return {"ok": remove_from_watchlist(ticker), "ticker": ticker.upper()}


@router.post("/watchlist/bulk")
def post_watchlist_bulk(body: Dict[str, Any]) -> Dict[str, Any]:
    """Replace entire watchlist atomically.

    body: {"tickers": ["NVDA", "AAPL", ...]}  — comma-separated string also accepted
    """
    from agent.finance.regime.signals import (
        list_watchlist, add_to_watchlist, remove_from_watchlist,
    )
    raw = body.get("tickers") or []
    if isinstance(raw, str):
        raw = [t.strip() for t in raw.replace(",", " ").split()]
    new_set = {t.upper() for t in raw if t.strip()}
    existing = {w["ticker"] for w in list_watchlist()}
    added = []
    removed = []
    for t in new_set - existing:
        add_to_watchlist(t)
        added.append(t)
    for t in existing - new_set:
        remove_from_watchlist(t)
        removed.append(t)
    return {"added": sorted(added), "removed": sorted(removed),
            "current": sorted(new_set)}


# All manual /scan/* endpoints route through this so each operator-
# triggered scanner shows up as its own NeoMind Live entry
# (agent_id="scanner:<name>") with timing + emit count, alongside
# the periodic scheduler runs.
def _audited_scan(scanner_label: str, scan_fn, **scan_kwargs) -> Dict[str, Any]:
    from agent.services.agent_audit import audited_call
    from agent.finance.regime.signals import detect_confluences
    agent_id = f"scanner:{scanner_label}"
    result = audited_call(
        agent_id=agent_id, endpoint=agent_id, fn=scan_fn,
        kwargs=scan_kwargs,
        extra_request={"trigger": "manual_api"},
        summarize_result=lambda r: f"{scanner_label} scan: {r.get('n_emitted', 0)} events" if isinstance(r, dict) else str(r)[:200],
    )
    confluences = detect_confluences()
    if isinstance(result, dict):
        result["new_confluences"] = len(confluences)
    return result


@router.post("/scan/watchlist")
def post_scan_watchlist() -> Dict[str, Any]:
    """Run the watchlist scanner on demand.  Triggered by cron + UI button."""
    from agent.finance.regime.scanners.watchlist_scanner import run_watchlist_scan
    return _audited_scan("watchlist", run_watchlist_scan)


@router.post("/scan/news")
def post_scan_news() -> Dict[str, Any]:
    """Run the news scanner (yfinance per-ticker headlines)."""
    from agent.finance.regime.scanners.news_scanner import run_news_scan
    return _audited_scan("news", run_news_scan)


@router.post("/scan/whale")
def post_scan_whale() -> Dict[str, Any]:
    """Run the 13F whale scanner.  ~30 seconds (12 whales × 2 filings × SEC EDGAR HTTP)."""
    from agent.finance.regime.scanners.whale_scanner import run_whale_scan
    return _audited_scan("13f", run_whale_scan)


@router.post("/scan/whale/backfill/{key}")
def post_whale_backfill(key: str, n_quarters: int = Query(5, ge=1, le=20)) -> Dict[str, Any]:
    """Backfill N quarters of 13F history for a single whale.

    Use when you just added a whale to WHALES (e.g. Aschenbrenner) and
    want the prior quarters' moves in the DB, not just the most recent
    diff. Idempotent — already-emitted events are skipped.
    """
    from agent.finance.regime.scanners.whale_scanner import backfill_whale_history
    return _audited_scan(
        f"13f_backfill_{key}",
        lambda: backfill_whale_history(key, n_quarters=n_quarters),
    )


@router.get("/whales")
def list_whales(
    bias:    Optional[str] = Query(None, description="filter by bias"),
    horizon: Optional[str] = Query(None, description="filter by horizon"),
) -> Dict[str, Any]:
    """List all tracked whales with full investment-philosophy metadata.

    Optional filters let the UI build a "whales by theme" browser —
    e.g. ?bias=tech_bear shows hedging perspectives.
    """
    from agent.finance.regime.scanners.whale_scanner import (
        WHALES, HORIZON_EMOJI, BIAS_EMOJI,
    )
    out = []
    for w in WHALES:
        if bias and w.get("bias") != bias:
            continue
        if horizon and w.get("horizon") != horizon:
            continue
        out.append({
            "key":             w["key"],
            "name":            w["short"],
            "cik":             w["cik"],
            "horizon":         w.get("horizon", "unknown"),
            "horizon_emoji":   HORIZON_EMOJI.get(w.get("horizon", "unknown"), "·"),
            "style":           w.get("style", "unknown"),
            "signal_weight":   w.get("signal_weight", 1.0),
            "bias":            w.get("bias", "unknown"),
            "bias_emoji":      BIAS_EMOJI.get(w.get("bias", "unknown"), "·"),
            "philosophy":      w.get("philosophy"),
            "famous_for":      w.get("famous_for"),
            "letters_url":     w.get("letters_url"),
            "derivative_note": w.get("derivative_exposure_note"),
        })
    # Provide aggregate view so the UI can build a quick browser
    bias_counts: Dict[str, int] = {}
    horizon_counts: Dict[str, int] = {}
    for w in WHALES:
        b = w.get("bias", "unknown"); h = w.get("horizon", "unknown")
        bias_counts[b] = bias_counts.get(b, 0) + 1
        horizon_counts[h] = horizon_counts.get(h, 0) + 1
    return {
        "whales":          out,
        "n":               len(out),
        "n_total":         len(WHALES),
        "bias_counts":     bias_counts,
        "horizon_counts":  horizon_counts,
    }


@router.get("/scorecard/{ticker}")
def get_decision_scorecard(ticker: str) -> Dict[str, Any]:
    """Decision scorecard for a ticker — synthesizes all signals into a
    suggested lean (add/hold/trim/sell/watch/pass) + degree + transparent
    per-lens breakdown. Rule-based, deterministic. Signal summary, NOT advice."""
    from agent.finance.decision_scorecard import build_scorecard
    try:
        return build_scorecard(ticker)
    except Exception as exc:
        logger.exception("scorecard failed for %s", ticker)
        raise HTTPException(500, f"scorecard failed: {exc}")


@router.get("/whales/{key}/research")
def get_whale_research(key: str) -> Dict[str, Any]:
    """Latest research summary for a whale (Tavily + LLM synthesis,
    URL-validated). Returns 404-style empty dict if never generated."""
    from agent.finance.regime.whale_research import get_active_summary
    s = get_active_summary(key)
    if not s:
        return {
            "whale_key":    key,
            "exists":       False,
            "summary":      None,
            "generated_at": None,
        }
    s["exists"] = True
    return s


@router.post("/whales/{key}/research/regenerate")
async def regenerate_whale_research(key: str) -> Dict[str, Any]:
    """Trigger a fresh research generation for one whale (Tavily search +
    LLM + URL validation). Synchronous — typically 30-90 seconds. Stores
    the new version with is_active=1 and marks previous as is_active=0."""
    from agent.finance.regime.whale_research import generate_summary
    try:
        summary = await generate_summary(key)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    except Exception as exc:
        logger.exception("whale research regen failed for %s", key)
        raise HTTPException(500, f"regeneration failed: {exc}")
    return {
        "whale_key":   key,
        "regenerated": True,
        "summary":     summary,
    }


@router.get("/whales/{key}/research/history")
def get_whale_research_history(
    key: str, limit: int = Query(10, ge=1, le=50),
) -> Dict[str, Any]:
    """List past versions of research summaries (most recent first).
    Lets the user diff the agent's read of a whale over time."""
    from agent.finance.regime.whale_research import list_history
    rows = list_history(key, limit=limit)
    return {"whale_key": key, "n": len(rows), "history": rows}


@router.get("/whales_by_whale")
def get_signals_by_whale(
    scanner: str = Query("13f", description="signal scanner_name to filter (default 13f)"),
    limit_per_whale: int = Query(10, ge=1, le=200,
                                  description="Top N most-recent events per whale"),
) -> Dict[str, Any]:
    """Per-whale top-N events, all 30 whales represented if they have any history.

    Solves the 'firehose ORDER BY detected_at LIMIT N' problem where 2-3
    whales with heavy filings monopolize the slots and others vanish.
    Uses SQLite window functions (ROW_NUMBER PARTITION BY whale_key) so
    the query is a single round-trip regardless of whale count.

    Frontend uses this for the 13F tab's "by whale" view; the timeline
    view still uses the firehose endpoint.
    """
    from agent.finance.persistence import connect
    from agent.finance.regime.scanners.whale_scanner import WHALES_BY_KEY

    sql = """
        WITH ranked AS (
            SELECT
                event_id, scanner_name, signal_type, severity, ticker,
                title, body_json, source_timestamp, source_url, detected_at,
                json_extract(body_json, '$.whale_key') AS whale_key,
                ROW_NUMBER() OVER (
                    PARTITION BY json_extract(body_json, '$.whale_key')
                    ORDER BY source_timestamp DESC, detected_at DESC
                ) AS rn
            FROM signal_events
            WHERE scanner_name = ?
        )
        SELECT * FROM ranked WHERE rn <= ?
        ORDER BY whale_key, source_timestamp DESC
    """
    by_whale: Dict[str, List[Dict[str, Any]]] = {}
    with connect() as conn:
        rows = conn.execute(sql, (scanner, int(limit_per_whale))).fetchall()
    for r in rows:
        d = dict(r)
        wk = d.get("whale_key") or "unknown"
        if d.get("body_json"):
            try:
                d["body"] = json.loads(d["body_json"])
            except Exception:
                d["body"] = None
            d.pop("body_json", None)
        d.pop("rn", None)
        by_whale.setdefault(wk, []).append(d)

    # Build whale groups, enrich with current metadata. Include all known
    # whales even if they have 0 events so the UI can render placeholder rows.
    groups: List[Dict[str, Any]] = []
    seen: set = set()
    for key, events in by_whale.items():
        if key == "unknown":
            continue
        w = WHALES_BY_KEY.get(key)
        if not w:
            continue
        seen.add(key)
        groups.append({
            "whale_key":     key,
            "whale":         w["short"],
            "horizon":       w.get("horizon", "unknown"),
            "bias":          w.get("bias", "unknown"),
            "style":         w.get("style", "unknown"),
            "signal_weight": w.get("signal_weight", 1.0),
            "n_events":      len(events),
            "events":        events,
        })
    # Add zero-event placeholders for whales with no history yet
    for key, w in WHALES_BY_KEY.items():
        if key in seen:
            continue
        groups.append({
            "whale_key":     key,
            "whale":         w["short"],
            "horizon":       w.get("horizon", "unknown"),
            "bias":          w.get("bias", "unknown"),
            "style":         w.get("style", "unknown"),
            "signal_weight": w.get("signal_weight", 1.0),
            "n_events":      0,
            "events":        [],
        })
    # Sort: events-having whales by latest event desc; empty by name asc.
    has_events = [g for g in groups if g["events"]]
    no_events  = [g for g in groups if not g["events"]]
    has_events.sort(
        key=lambda g: g["events"][0].get("source_timestamp", "") or "",
        reverse=True,
    )
    no_events.sort(key=lambda g: g["whale"].lower())

    return {
        "scanner":          scanner,
        "limit_per_whale":  limit_per_whale,
        "n_whales_with_events": len(has_events),
        "n_whales_total":   len(WHALES_BY_KEY),
        "whales":           has_events + no_events,
    }


@router.get("/whales/{key}")
def get_whale_detail(key: str) -> Dict[str, Any]:
    """Detailed whale profile for the drawer: curated bilingual content +
    live recent 13F moves from signal_events. News fetched separately
    via /whales/{key}/news (async + slower).

    Powers the WhaleProfileDrawer that opens when user clicks any whale
    name in the dashboard. Designed so the drawer renders instantly
    with curated + 13F, then a second fetch fills the news section.
    """
    from agent.finance.regime.scanners.whale_scanner import (
        WHALES_BY_KEY, whale_meta, HORIZON_EMOJI, BIAS_EMOJI,
    )
    from agent.finance.regime.whale_profiles import get_profile
    from agent.finance.persistence import connect

    w = WHALES_BY_KEY.get(key)
    if not w:
        raise HTTPException(404, f"unknown whale: {key}")

    profile = get_profile(key)

    # Recent 13F moves for this whale (last 24 months max)
    recent_moves: List[Dict[str, Any]] = []
    try:
        with connect() as conn:
            rows = conn.execute(
                "SELECT event_id, signal_type, severity, ticker, title, "
                "       body_json, source_timestamp, source_url "
                "  FROM signal_events "
                " WHERE scanner_name = '13f' "
                "   AND body_json LIKE ? "
                " ORDER BY source_timestamp DESC LIMIT 30",
                (f'%"whale_key": "{key}"%',),
            ).fetchall()
        for r in rows:
            try:
                body = json.loads(r["body_json"]) if r["body_json"] else {}
            except Exception:
                body = {}
            recent_moves.append({
                "event_id":         r["event_id"],
                "signal_type":      r["signal_type"],
                "ticker":           r["ticker"],
                "title":            r["title"],
                "severity":         r["severity"],
                "filing_date":      r["source_timestamp"],
                "change_type":      body.get("change_type"),
                "delta_pct":        body.get("delta_pct"),
                "current_shares":   body.get("current_shares"),
                "previous_shares":  body.get("previous_shares"),
                "source_url":       r["source_url"],
            })
    except Exception as exc:
        logger.warning("recent_moves lookup failed for %s: %s", key, exc)

    return {
        "key":            w["key"],
        "name":           w["short"],
        "cik":            w["cik"],
        "horizon":        w.get("horizon", "unknown"),
        "horizon_emoji":  HORIZON_EMOJI.get(w.get("horizon", "unknown"), "·"),
        "style":          w.get("style", "unknown"),
        "signal_weight":  w.get("signal_weight", 1.0),
        "bias":           w.get("bias", "unknown"),
        "bias_emoji":     BIAS_EMOJI.get(w.get("bias", "unknown"), "·"),
        "philosophy":     w.get("philosophy"),
        "famous_for":     w.get("famous_for"),
        "letters_url":    w.get("letters_url"),
        "derivative_note": w.get("derivative_exposure_note"),
        "profile":        profile,           # bilingual curated content or None
        "recent_moves":   recent_moves,
        "n_recent_moves": len(recent_moves),
    }


@router.get("/whales/{key}/news")
async def get_whale_news(
    key: str,
    limit: int = Query(5, ge=1, le=10),
) -> Dict[str, Any]:
    """Latest news for a whale via Tavily-primary search engine.

    Async endpoint — typically 1-3 seconds. Drawer fires this AFTER the
    main /whales/{key} call so the curated profile + 13F render instantly
    and the news section shows a spinner while this runs.

    Gracefully degrades if Tavily / engine unavailable — returns empty
    items + a search-link fallback the user can click.
    """
    from agent.finance.regime.scanners.whale_scanner import WHALES_BY_KEY

    w = WHALES_BY_KEY.get(key)
    if not w:
        raise HTTPException(404, f"unknown whale: {key}")

    # The "short" field is already "PM (Fund)" pattern e.g. "Buffett (Berkshire)",
    # which gives Tavily enough to disambiguate from coincidental name matches.
    query = w["short"]

    items: List[Dict[str, Any]] = []
    sources_used: List[str] = []
    error: Optional[str] = None
    try:
        from agent.search.engine import UniversalSearchEngine
        engine = UniversalSearchEngine()
        result = await engine.search_advanced(
            query=query,
            max_results=limit,
            extract_content=False,
            expand_queries=False,
        )
        items = [{
            "title":     it.title,
            "url":       it.url,
            "source":    it.source,
            "snippet":   (it.snippet or "")[:300],
            "published": it.published.isoformat() if it.published else None,
        } for it in (result.items or [])[:limit]]
        sources_used = list(result.sources_used or [])
    except Exception as exc:
        logger.warning("whale news search failed for %s: %s", key, exc)
        error = str(exc)

    fallback_url = f"https://news.google.com/search?q={query.replace(' ', '+')}"
    return {
        "key":           key,
        "query":         query,
        "items":         items,
        "sources_used":  sources_used,
        "total":         len(items),
        "error":         error,
        "fallback_url":  fallback_url,
    }


@router.post("/scan/congressional")
def post_scan_congressional(
    lookback_days: int = Query(30, ge=1, le=365),
) -> Dict[str, Any]:
    """Run the Congressional STOCK Act scanner (House + Senate)."""
    from agent.finance.regime.scanners.congressional_scanner import run_congressional_scan
    return _audited_scan("congressional", run_congressional_scan, lookback_days=lookback_days)


@router.post("/scan/policy")
def post_scan_policy() -> Dict[str, Any]:
    """Run the China policy + macro RSS scanner."""
    from agent.finance.regime.scanners.policy_scanner import run_policy_scan
    return _audited_scan("policy", run_policy_scan)


@router.post("/scan/insider_form4")
def post_scan_insider_form4() -> Dict[str, Any]:
    """Run the SEC Form 4 insider trading scanner — pulls cluster buys
    + large CEO/CFO open-market purchases from openinsider.com. 2-day
    disclosure window, freshest signal in the Smart Money stack."""
    from agent.finance.regime.scanners.insider_form4_scanner import (
        run_insider_form4_scan,
    )
    return _audited_scan("insider_form4", run_insider_form4_scan)


@router.post("/scan/13d")
def post_scan_13d() -> Dict[str, Any]:
    """Run the SC 13D activist scanner — EDGAR full-text search for
    Schedule 13D / 13D-A filed against watchlist+held tickers (someone
    taking an active >5% stake with intent to influence). Feeds the
    decision scorecard's positioning lens."""
    from agent.finance.regime.scanners.activist_13d_scanner import (
        run_activist_13d_scan,
    )
    return _audited_scan("13d", run_activist_13d_scan)


@router.post("/scan/house_clerk_pdf")
def post_scan_house_clerk_pdf() -> Dict[str, Any]:
    """Run the House Clerk PTR PDF scanner — covers Pelosi + Khanna
    (and any other reps in FOLLOWED_REPS) which Quiver Quant's free
    /beta/live tier doesn't include. Each emitted event links to the
    official PDF on disclosures-clerk.house.gov so the user can
    click through to the legal record."""
    from agent.finance.regime.scanners.house_clerk_pdf_scanner import (
        run_house_clerk_pdf_scan,
    )
    return _audited_scan("house_clerk_pdf", run_house_clerk_pdf_scan)


@router.post("/scan/all")
def post_scan_all(
    include_13f: bool = Query(False, description="Include 13F whale scan (~30s SEC HTTP)"),
) -> Dict[str, Any]:
    """Run all scanners back-to-back, then promote confluences once.

    13F is opt-in by default because it hits SEC EDGAR (slower + rate
    limited). Hourly cron runs only watchlist + news; 13F has its own
    daily cron.

    Phase M1b: wraps the scan in an analysis_runs row so the user can
    see in NeoMindLive ops view that the scan actually ran (even when
    every emission was dedup-killed).
    """
    from agent.finance.regime.scanners.watchlist_scanner import run_watchlist_scan
    from agent.finance.regime.scanners.news_scanner       import run_news_scan
    from agent.finance.regime.signals                     import detect_confluences
    from agent.finance.persistence import connect, dao, ensure_schema

    ensure_schema()
    with connect() as conn:
        run_id = dao.start_analysis_run(
            conn, job_name="scan_all_manual", run_type="manual",
        )

    out: Dict[str, Any] = {"run_id": run_id, "scanners": {}}
    status = "completed"
    try:
        try:
            out["scanners"]["watchlist_scan"] = run_watchlist_scan()
        except Exception as exc:
            logger.exception("watchlist scan failed")
            out["scanners"]["watchlist_scan"] = {"error": str(exc)}
        try:
            out["scanners"]["news_scan"] = run_news_scan()
        except Exception as exc:
            logger.exception("news scan failed")
            out["scanners"]["news_scan"] = {"error": str(exc)}

        if include_13f:
            try:
                from agent.finance.regime.scanners.whale_scanner import run_whale_scan
                out["scanners"]["whale_scan"] = run_whale_scan()
            except Exception as exc:
                logger.exception("13f scan failed")
                out["scanners"]["whale_scan"] = {"error": str(exc)}
            # 13D activist scan piggybacks on the 13F opt-in (both hit SEC
            # EDGAR, both slow-moving).
            try:
                from agent.finance.regime.scanners.activist_13d_scanner import run_activist_13d_scan
                out["scanners"]["scan_13d"] = run_activist_13d_scan()
            except Exception as exc:
                logger.exception("13d scan failed")
                out["scanners"]["scan_13d"] = {"error": str(exc)}

        # Congressional + policy scanners are fast HTTP fetches; safe to
        # include in every /scan/all call.
        try:
            from agent.finance.regime.scanners.congressional_scanner import run_congressional_scan
            out["scanners"]["congressional_scan"] = run_congressional_scan(lookback_days=30)
        except Exception as exc:
            logger.exception("stock_act scan failed")
            out["scanners"]["congressional_scan"] = {"error": str(exc)}

        # House Clerk PDF scanner — followed reps (Pelosi/Khanna) only.
        # Quick when caught up (just a 20KB ZIP + DocID diff), only
        # downloads PDFs for new filings. Safe to include every scan.
        try:
            from agent.finance.regime.scanners.house_clerk_pdf_scanner import run_house_clerk_pdf_scan
            out["scanners"]["house_clerk_pdf_scan"] = run_house_clerk_pdf_scan()
        except Exception as exc:
            logger.exception("house clerk pdf scan failed")
            out["scanners"]["house_clerk_pdf_scan"] = {"error": str(exc)}

        # Insider Form 4 — openinsider.com cluster buys + large CEO buys.
        # 2-day SEC disclosure window, freshest signal. Two HTTP fetches.
        try:
            from agent.finance.regime.scanners.insider_form4_scanner import run_insider_form4_scan
            out["scanners"]["insider_form4_scan"] = run_insider_form4_scan()
        except Exception as exc:
            logger.exception("insider form 4 scan failed")
            out["scanners"]["insider_form4_scan"] = {"error": str(exc)}

        try:
            from agent.finance.regime.scanners.policy_scanner import run_policy_scan
            out["scanners"]["policy_scan"] = run_policy_scan()
        except Exception as exc:
            logger.exception("policy scan failed")
            out["scanners"]["policy_scan"] = {"error": str(exc)}

        confluences = detect_confluences()
        out["new_confluences"] = len(confluences)
        out["confluences"]     = confluences
    except Exception as exc:
        status = "failed"
        out["error"] = str(exc)
        raise
    finally:
        # Build a flat summary the ops UI can render.  It expects
        # per-scanner sub-dicts with n_emitted etc., plus
        # new_confluences at top level.
        summary = dict(out["scanners"])
        if "new_confluences" in out:
            summary["new_confluences"] = out["new_confluences"]
        with connect() as conn:
            dao.finish_analysis_run(
                conn, run_id=run_id, status=status, summary_json=summary,
            )

    return out


@router.get("/signals/today")
def get_signals_today(limit: int = Query(3, ge=1, le=10)) -> Dict[str, Any]:
    """Top N currently active confluences — frontend "Today's 3 things"."""
    from agent.finance.regime.signals import todays_top_signals
    sigs = todays_top_signals(limit=limit)
    return {"n": len(sigs), "signals": sigs}


@router.get("/signals/recent")
def get_signals_recent(
    limit:   int = Query(50, ge=1, le=500),
    ticker:  Optional[str] = Query(None),
    scanner: Optional[str] = Query(None),
    since:   Optional[str] = Query(None, description="ISO datetime filter"),
) -> Dict[str, Any]:
    """Recent signal events for the live activity stream."""
    from agent.finance.regime.signals import recent_events
    events = recent_events(limit=limit, since=since,
                           ticker=ticker, scanner=scanner)
    return {"n": len(events), "events": events}


@router.post("/signals/dismiss/{confluence_id}")
def post_dismiss(confluence_id: str) -> Dict[str, Any]:
    """User dismisses a signal — hides it from "Today's 3 things"."""
    from agent.finance.regime.signals import dismiss_confluence
    return {"ok": dismiss_confluence(confluence_id),
            "confluence_id": confluence_id}


@router.get("/runs")
def get_runs(limit: int = Query(50, ge=1, le=500)) -> Dict[str, Any]:
    """Phase M1b — recent analysis_runs (scheduler / scanner ops log).

    Powers the NeoMindLive "ops" view so the user can see whether
    scanners actually ran when they clicked refresh — even when
    dedup made the run emit 0 new events, an analysis_runs row is
    still recorded with started_at / status / summary_json."""
    from agent.finance.persistence import connect, dao
    out: List[Dict[str, Any]] = []
    with connect() as conn:
        rows = dao.list_recent_runs(conn, job_name=None, limit=int(limit))
    for r in rows:
        keys = r.keys()
        meta_raw = r["metadata_json"] if "metadata_json" in keys else None
        meta: Dict[str, Any] = {}
        if meta_raw:
            try:
                meta = json.loads(meta_raw) or {}
            except Exception:
                meta = {"raw": meta_raw[:200]}
        out.append({
            "run_id":        r["run_id"]        if "run_id"        in keys else "",
            "job_name":      r["job_name"]      if "job_name"      in keys else "",
            "run_type":      r["run_type"]      if "run_type"      in keys else None,
            "status":        r["status"]        if "status"        in keys else "",
            "started_at":    r["started_at"]    if "started_at"    in keys else "",
            "completed_at":  r["completed_at"]  if "completed_at"  in keys else None,
            "duration_s":    r["duration_s"]    if "duration_s"    in keys else None,
            "rows_written":  r["rows_written"]  if "rows_written"  in keys else None,
            "error_message": r["error_message"] if "error_message" in keys else None,
            "summary":       meta,
        })
    return {"n": len(out), "runs": out}


@router.get("/walkforward")
def get_walkforward(
    strategy_id: str            = Query(..., description="strategy to validate"),
    hold_days:   int            = Query(30, ge=1, le=365),
    is_pct:      float          = Query(0.8, ge=0.5, le=0.95),
) -> Dict[str, Any]:
    """Walk-forward IS/OOS Sharpe + Deflated Sharpe Ratio for one
    strategy.  See agent/finance/regime/walk_forward.py for math
    (Bailey & Lopez de Prado, 2014)."""
    from agent.finance.regime.walk_forward import walk_forward_sharpe
    return walk_forward_sharpe(strategy_id, hold_days=hold_days, is_pct=is_pct)


@router.get("/walkforward/all")
def get_walkforward_all(
    hold_days: int   = Query(30, ge=1, le=365),
    is_pct:    float = Query(0.8, ge=0.5, le=0.95),
) -> Dict[str, Any]:
    """Walk-forward + DSR for every strategy.  Headline number = how
    many strategies survive multiple-testing correction at DSR > 0.95."""
    from agent.finance.regime.walk_forward import walk_forward_all
    return walk_forward_all(hold_days=hold_days, is_pct=is_pct)


@router.get("/dashboard")
def get_dashboard(
    strategy_id: str            = Query(..., description="strategy to inspect"),
    as_of:       Optional[str]  = Query(None, description="'live' or YYYY-MM-DD"),
    hold_days:   int            = Query(30, ge=1, le=365),
) -> Dict[str, Any]:
    """6-dimension Risk Dashboard for one strategy at a regime.

    Returns return_distribution / tail_risk / position_sizing /
    hedge_candidates / stop_loss / regime_fit + composite recommendation.
    Math-grounded — no future prediction, only describes historical
    distribution conditional on current regime.
    """
    from agent.finance.regime import fingerprint_for_date
    from agent.finance.regime.risk import risk_dashboard
    from agent.finance.lattice.strategy_matcher import _load_strategies

    fp_date = (as_of if as_of and as_of != "live"
               else _date.today().isoformat())
    fp = fingerprint_for_date(fp_date)
    strats = {s["id"]: s for s in _load_strategies(include_unverified=True)}
    s = strats.get(strategy_id)
    if not s:
        raise HTTPException(404, f"unknown strategy: {strategy_id}")
    return risk_dashboard(s, fp, hold_days=hold_days)


@router.get("/dashboard/all")
def get_dashboard_all(
    as_of:     Optional[str] = Query(None),
    hold_days: int           = Query(30, ge=1, le=365),
    limit:     int           = Query(36, ge=1, le=36),
) -> Dict[str, Any]:
    """Compute Risk Dashboard for every strategy (or top N).  Heavy —
    use with caution; ~1-3 seconds per strategy."""
    from agent.finance.regime import fingerprint_for_date
    from agent.finance.regime.risk import risk_dashboard
    from agent.finance.lattice.strategy_matcher import _load_strategies

    fp_date = (as_of if as_of and as_of != "live"
               else _date.today().isoformat())
    fp = fingerprint_for_date(fp_date)
    out = []
    for s in _load_strategies(include_unverified=True)[:limit]:
        try:
            out.append(risk_dashboard(s, fp, hold_days=hold_days))
        except Exception as exc:
            logger.warning("dashboard for %s failed: %s", s.get("id"), exc)
    # Sort by recommendation color (green first) then by half-Kelly desc
    color_rank = {"green": 0, "amber": 1, "red": 2}
    def _key(d):
        rec = d.get("recommendation") or {}
        ps  = d.get("position_sizing") or {}
        return (color_rank.get(rec.get("color", "amber"), 1),
                -(ps.get("half_kelly") or 0))
    out.sort(key=_key)
    return {
        "fingerprint_date": fp_date,
        "n":                len(out),
        "strategies":       out,
    }


@router.post("/v3/train")
def post_v3_train(
    purge_days: int   = Query(35, ge=1, le=180),
    test_frac:  float = Query(0.2, ge=0.05, le=0.5),
) -> Dict[str, Any]:
    """Retrain the v3 PDS model from backtest_results.  Returns
    per-family test metrics."""
    from agent.finance.regime.scorer_v3 import train_pds, reload_models
    try:
        meta = train_pds(purge_days=purge_days, test_frac=test_frac)
        n_loaded = reload_models()
        meta["models_loaded"] = n_loaded
        return meta
    except Exception as exc:
        logger.exception("v3 train failed")
        raise HTTPException(500, f"v3 train failed: {exc}")


@router.get("/v3/score")
def get_v3_score(
    strategy_id: str               = Query(...),
    as_of:       Optional[str]     = Query(None),
) -> Dict[str, Any]:
    """Score a single strategy with v3 PDS at the given fingerprint."""
    from agent.finance.regime import fingerprint_for_date
    from agent.finance.regime.scorer_v3 import score_pds
    from agent.finance.lattice.strategy_matcher import _load_strategies

    fp_date = (as_of if as_of and as_of != "live"
               else _date.today().isoformat())
    fp = fingerprint_for_date(fp_date)
    strats = {s["id"]: s for s in _load_strategies(include_unverified=True)}
    s = strats.get(strategy_id)
    if not s:
        raise HTTPException(404, f"unknown strategy: {strategy_id}")
    out = score_pds(fp, s)
    out["fingerprint_date"] = fp_date
    out["strategy_id"]      = strategy_id
    return out


@router.get("/v3/all")
def get_v3_all(
    as_of: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """Score every strategy with v3 at the given fingerprint."""
    from agent.finance.regime import fingerprint_for_date
    from agent.finance.regime.scorer_v3 import score_pds
    from agent.finance.lattice.strategy_matcher import _load_strategies

    fp_date = (as_of if as_of and as_of != "live"
               else _date.today().isoformat())
    fp = fingerprint_for_date(fp_date)
    out = []
    for s in _load_strategies(include_unverified=True):
        scored = score_pds(fp, s)
        scored["strategy_id"] = s["id"]
        scored["name_zh"]     = s.get("name_zh")
        scored["name_en"]     = s.get("name_en")
        scored["horizon"]     = s.get("horizon")
        scored["asset_class"] = s.get("asset_class")
        scored["difficulty"]  = s.get("difficulty")
        out.append(scored)
    out.sort(key=lambda x: -(x.get("score") or 0))
    return {
        "fingerprint_date": fp_date,
        "n":                len(out),
        "scored":           out,
    }


@router.get("/today")
def get_today() -> Dict[str, Any]:
    """Today's fingerprint, computed on demand from raw_market_data."""
    from agent.finance.regime import fingerprint_for_date
    today = _date.today().isoformat()
    fp = fingerprint_for_date(today)
    return fp


# ── Settings #92: 4-question user prefs (persisted JSON) ──────────


_PREFS_KEYS = (
    "options_level",                 # 0 = no options, 1 = covered only, 2 = spreads, 3 = naked
    "max_drawdown_tolerance",        # 0..1 fraction
    "income_vs_growth",              # 0 = pure growth, 1 = pure income
    "max_position_concentration",    # 0..1 fraction
)


def _prefs_path() -> str:
    import os
    from agent.finance.persistence import DEFAULT_DB_PATH
    base = os.path.dirname(str(DEFAULT_DB_PATH))
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "user_prefs.json")


@router.get("/prefs")
def get_prefs() -> Dict[str, Any]:
    """Read persisted user prefs. Falls back to scorer DEFAULT_PREFS."""
    import json
    import os
    from agent.finance.regime.scorer import DEFAULT_PREFS

    path = _prefs_path()
    saved: Dict[str, Any] = {}
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                saved = json.load(f)
        except Exception:
            saved = {}

    out = {k: saved.get(k, DEFAULT_PREFS.get(k)) for k in _PREFS_KEYS}
    out["_source"]   = "saved" if saved else "default"
    out["_path"]     = path
    out["_defaults"] = {k: DEFAULT_PREFS.get(k) for k in _PREFS_KEYS}
    return out


@router.post("/prefs")
def post_prefs(body: Dict[str, Any]) -> Dict[str, Any]:
    """Persist user prefs.  Body is a partial dict; only known keys
    are saved. Returns the merged result."""
    import json
    import os

    cleaned: Dict[str, Any] = {}
    for k in _PREFS_KEYS:
        if k in body:
            v = body[k]
            if k == "options_level":
                cleaned[k] = max(0, min(3, int(v)))
            else:
                cleaned[k] = max(0.0, min(1.0, float(v)))

    path = _prefs_path()
    existing: Dict[str, Any] = {}
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                existing = json.load(f)
        except Exception:
            existing = {}
    existing.update(cleaned)
    with open(path, "w") as f:
        json.dump(existing, f, indent=2)
    return {"saved": cleaned, "merged": existing, "path": path}


@router.get("/at")
def get_at(
    date: str = Query(..., description="YYYY-MM-DD UTC"),
    recompute: bool = Query(False, description="Force recompute (ignore cache)"),
) -> Dict[str, Any]:
    """Fingerprint for a specific date.  Computes on demand if missing."""
    from agent.finance.regime import fingerprint_for_date
    try:
        fp = fingerprint_for_date(date, recompute=recompute)
    except Exception as exc:
        logger.exception("fingerprint compute failed")
        raise HTTPException(500, f"fingerprint compute failed: {exc}")
    return fp


@router.get("/history")
def get_history(
    limit: int = Query(120, ge=1, le=500),
    since: Optional[str] = Query(None, description="YYYY-MM-DD UTC inclusive"),
) -> Dict[str, Any]:
    """Recent fingerprints, newest first.  Used by the k-NN UI / sparkline."""
    from agent.finance.regime.store import list_fingerprints
    rows = list_fingerprints(limit=limit, since=since)
    return {"count": len(rows), "fingerprints": rows}


@router.post("/ingest")
def post_ingest(
    lookback_days: int = Query(5, ge=1, le=30),
) -> Dict[str, Any]:
    """Pull last N days of yfinance data for the 3-tier watchlist.
    Idempotent — re-runs replace existing rows."""
    from agent.finance.regime.ingest import ingest_yfinance_daily
    try:
        result = ingest_yfinance_daily(lookback_days=lookback_days)
    except Exception as exc:
        logger.exception("yfinance ingest failed")
        raise HTTPException(502, f"yfinance ingest failed: {exc}")
    return result


@router.post("/backfill")
def post_backfill(
    period: str = Query("1y", description="yfinance period: '1mo'/'3mo'/'6mo'/'1y'/'2y'/'5y'/'max'"),
    compute_fingerprints: bool = Query(True, description="Also compute fingerprints for every trading day"),
) -> Dict[str, Any]:
    """One-shot historical backfill.  Pulls bulk yfinance data for the
    full 3-tier watchlist, then optionally computes fingerprints for
    each trading day in the window."""
    from agent.finance.regime.ingest import backfill_history
    from agent.finance.regime.fingerprint import backfill_fingerprints
    from datetime import timedelta

    try:
        ingest_result = backfill_history(period=period)
    except Exception as exc:
        logger.exception("backfill ingest failed")
        raise HTTPException(502, f"backfill ingest failed: {exc}")

    fp_result: Dict[str, Any] = {"skipped": True}
    if compute_fingerprints:
        period_to_days = {
            "1mo": 31, "3mo": 92, "6mo": 183,
            "1y": 365, "2y": 730, "5y": 1826, "max": 3650,
        }
        d = period_to_days.get(period, 365)
        since = (_date.today() - timedelta(days=d)).isoformat()
        try:
            fp_result = backfill_fingerprints(since=since, skip_existing=True)
        except Exception as exc:
            logger.exception("fingerprint backfill failed")
            fp_result = {"error": str(exc)}

    return {"ingest": ingest_result, "fingerprints": fp_result}
