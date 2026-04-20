"""Locally-computed anomaly flags — the 52w-high-meets-earnings
kind of signal that turns a grid of numbers into an actionable
attention list.

All flags are cheap pure-math heuristics. No LLM involvement —
these are the things a careful analyst would eyeball, distilled
to one-line alerts that render as chips on the narrative hero.

Flags implemented:

    near_52w_high_with_earnings
        Position or watchlist symbol within 2% of 52w high AND
        earnings in ≤14 days. Classic vol-crush setup.

    iv_richness
        ATM IV implies a daily move >1.5× the historical avg
        |post-earnings move|. Option market is pricing a bigger
        event than history supports.

    position_drawdown
        Paper position down >5% from entry. Not a stop but a
        "check the thesis" prompt.

    sector_divergence
        Position is in today's bottom-3 sector movers. The tape
        is moving against you on this name.

    oversold_watch
        Watchlist symbol with RSI14 < 30 (potentially oversold).

Caching: 2 min — these are derived from fresh synthesis snapshots,
so don't stale for long.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from agent.finance import investment_projects, synthesis

logger = logging.getLogger(__name__)

_TTL_S = 120.0
_cache: Dict[str, tuple[float, Dict[str, Any]]] = {}
_cache_lock = threading.Lock()


def _cached(key: str) -> Optional[Dict[str, Any]]:
    with _cache_lock:
        entry = _cache.get(key)
    if entry is None:
        return None
    if time.time() - entry[0] > _TTL_S:
        return None
    return entry[1]


def _put(key: str, value: Dict[str, Any]) -> None:
    with _cache_lock:
        _cache[key] = (time.time(), value)


def _near_52w_with_earnings(proj: Dict[str, Any], sym_snaps: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Symbol near 52w high AND earnings in ≤14 days."""
    out: List[Dict[str, Any]] = []
    upcoming_by_sym = {e["symbol"]: e for e in (proj.get("upcoming_earnings") or [])}
    for sym, s in sym_snaps.items():
        if sym not in upcoming_by_sym:
            continue
        days = upcoming_by_sym[sym].get("days_until")
        if days is None or days < 0 or days > 14:
            continue
        tech = s.get("technical") or {}
        rng = tech.get("range_pos_20d_pct")
        # Use 20d range position as a proxy for 52w high proximity.
        # 100% = at the top of the 20d range (yfinance history isn't
        # 52w-true but it catches the "running hot into earnings" case).
        if rng is None or rng < 85:
            continue
        out.append({
            "kind": "near_52w_with_earnings",
            "symbol": sym,
            "message": f"{sym} at top of 20d range going into earnings in {days}d",
            "severity": "warn",
        })
    return out


def _iv_richness(proj: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for e in proj.get("upcoming_earnings") or []:
        iv = e.get("atm_iv_pct")
        mv = e.get("avg_abs_move_pct")
        if iv is None or mv is None or mv <= 0:
            continue
        # IV is annualised — daily implied move ≈ IV/sqrt(252) ≈ IV/16
        implied_daily = iv / 16.0
        if implied_daily >= mv * 1.5:
            out.append({
                "kind": "iv_richness",
                "symbol": e["symbol"],
                "message": f"{e['symbol']} IV {iv:.0f}% pricing ≈{implied_daily:.1f}% daily vs avg {mv:.1f}% historical",
                "severity": "info",
            })
    return out


def _position_drawdown(proj: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for p in proj.get("positions") or []:
        pct = p.get("unrealized_pnl_pct")
        if pct is None or pct > -5:
            continue
        out.append({
            "kind": "position_drawdown",
            "symbol": p["symbol"],
            "message": f"{p['symbol']} position down {pct:.2f}% — check thesis",
            "severity": "alert" if pct < -10 else "warn",
        })
    return out


def _sector_divergence(proj: Dict[str, Any], sym_snaps: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    sm = proj.get("sector_movers") or {}
    bottom_names = {s["name"].lower() for s in (sm.get("bottom") or [])}
    if not bottom_names:
        return out
    held = {p["symbol"] for p in (proj.get("positions") or [])}
    for sym in held:
        s = sym_snaps.get(sym) or {}
        sec = (s.get("sector") or {}).get("sector") or ""
        if sec.lower() in bottom_names:
            out.append({
                "kind": "sector_divergence",
                "symbol": sym,
                "message": f"{sym} sits in a red-zone sector today ({sec})",
                "severity": "warn",
            })
    return out


def _oversold_watch(proj: Dict[str, Any], sym_snaps: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    wl_us = {e["symbol"] for e in (proj.get("watchlist") or [])
             if str(e.get("market", "")).upper() == "US"}
    for sym in wl_us:
        s = sym_snaps.get(sym) or {}
        rsi = (s.get("technical") or {}).get("rsi14")
        if rsi is None or rsi >= 30:
            continue
        out.append({
            "kind": "oversold_watch",
            "symbol": sym,
            "message": f"{sym} RSI14 {rsi:.1f} (oversold territory)",
            "severity": "info",
        })
    return out


def _compute(project_id: str) -> Dict[str, Any]:
    proj = synthesis.synth_project_data(project_id)
    # For every US symbol we'll evaluate, pull its own synthesis snapshot.
    syms: set[str] = set()
    for w in proj.get("watchlist") or []:
        if str(w.get("market", "")).upper() == "US":
            syms.add(w["symbol"])
    for p in proj.get("positions") or []:
        syms.add(p["symbol"])
    sym_snaps: Dict[str, Dict[str, Any]] = {}
    for s in syms:
        try:
            sym_snaps[s] = synthesis.synth_symbol_data(project_id, s)
        except Exception as exc:
            logger.debug("anomaly: symbol synth failed for %s: %s", s, exc)

    flags: List[Dict[str, Any]] = []
    flags.extend(_near_52w_with_earnings(proj, sym_snaps))
    flags.extend(_iv_richness(proj))
    flags.extend(_position_drawdown(proj))
    flags.extend(_sector_divergence(proj, sym_snaps))
    flags.extend(_oversold_watch(proj, sym_snaps))

    severity_order = {"alert": 0, "warn": 1, "info": 2}
    flags.sort(key=lambda f: severity_order.get(f["severity"], 99))

    return {
        "project_id": project_id,
        "count": len(flags),
        "flags": flags,
        "fetched_at_epoch": int(time.time()),
    }


def build_anomalies_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/anomalies")
    def anomalies(project_id: str = Query(...)) -> Dict[str, Any]:
        if project_id not in investment_projects.list_projects():
            raise HTTPException(404, f"project {project_id!r} not registered")
        cached = _cached(project_id)
        if cached is not None:
            return cached
        try:
            data = _compute(project_id)
        except Exception as exc:
            logger.exception("anomalies failed for %s", project_id)
            raise HTTPException(502, f"anomalies compute failed: {exc}")
        _put(project_id, data)
        return data

    return router
