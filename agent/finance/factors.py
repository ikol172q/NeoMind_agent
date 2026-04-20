"""Factor grades per symbol — the Seeking-Alpha-Quant pattern.

Five axes, each scored A..F based on a percentile-ish heuristic
against sector/market norms. No LLM involvement at this tier —
this is the 初级 (tier 1) data primitive that powers the tier 2
factor-pills view and that the agent cites at tier 3.

Axes:

    Momentum       — derived from our RS module's 3M/6M/YTD rank
    Value          — trailingPE vs category norm (lower = better)
    Quality        — ROE + debt/equity + profit margin combined
    Growth         — revenue growth + earnings growth
    Revisions      — EPS estimate direction (forward EPS vs current)

Rules:
- Each axis returns {grade, raw, note}. Grade is A+ / A / B / C / D / F.
- Missing data → grade "—", raw null. Never 500; degrade gracefully.
- 10-min cache per symbol.
- US only for now (yfinance fundamentals coverage is best for US).

Scoring philosophy: honest, not precise. An A isn't "top decile of the
S&P 500" — it's "well above the market norm on the axis we're scoring."
This is 10k-ft color for the user's eye, not a quantitative ranking.
"""
from __future__ import annotations

import logging
import math
import re
import threading
import time
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

_SYMBOL_RE = re.compile(r"^[A-Z0-9._-]{1,16}$")
_TTL_S = 600.0
_cache: Dict[str, tuple[float, Dict[str, Any]]] = {}
_cache_lock = threading.Lock()

# Heuristic cut-points per axis. Calibrated against current large-cap
# US norms; tune if the composition of the universe shifts.
# Each band is (lower_bound, grade) — first match wins, descending.
_VALUE_BANDS: list[tuple[float, str]] = [
    # trailingPE: lower is cheaper
    # (threshold, grade). If PE <= threshold, grade applies.
    (10, "A+"), (15, "A"), (22, "B"), (30, "C"), (45, "D"), (math.inf, "F"),
]

_QUALITY_SCORE_BANDS: list[tuple[float, str]] = [
    # composite 0-100 score: higher = better
    (85, "A+"), (70, "A"), (55, "B"), (40, "C"), (25, "D"), (-math.inf, "F"),
]

_GROWTH_SCORE_BANDS: list[tuple[float, str]] = [
    (30, "A+"), (20, "A"), (10, "B"), (5, "C"), (0, "D"), (-math.inf, "F"),
]


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


def _safe_float(v) -> Optional[float]:
    try:
        if v is None:
            return None
        f = float(v)
        if not math.isfinite(f):
            return None
        return f
    except Exception:
        return None


def _grade_lte(value: Optional[float], bands: list[tuple[float, str]]) -> Tuple[str, Optional[float]]:
    """Assign a grade if value ≤ threshold. For "lower is better" axes."""
    if value is None:
        return ("—", None)
    for threshold, grade in bands:
        if value <= threshold:
            return (grade, round(value, 3))
    return ("F", round(value, 3))


def _grade_gte(value: Optional[float], bands: list[tuple[float, str]]) -> Tuple[str, Optional[float]]:
    """Assign a grade if value ≥ threshold. For "higher is better" axes."""
    if value is None:
        return ("—", None)
    for threshold, grade in bands:
        if value >= threshold:
            return (grade, round(value, 3))
    return ("F", round(value, 3))


def _compose_letter_grade(grades: Dict[str, str]) -> str:
    """Combine the 5 axis grades into one overall letter. Simple mean
    mapped back to a letter. Missing axes don't pull you down."""
    to_num = {"A+": 4.3, "A": 4.0, "B": 3.0, "C": 2.0, "D": 1.0, "F": 0.0}
    scored = [to_num[g] for g in grades.values() if g in to_num]
    if not scored:
        return "—"
    avg = sum(scored) / len(scored)
    if avg >= 4.0: return "A"
    if avg >= 3.0: return "B"
    if avg >= 2.0: return "C"
    if avg >= 1.0: return "D"
    return "F"


def _momentum_from_rs(symbol: str) -> Dict[str, Any]:
    """Use our S&P 100 RS rank as the momentum primitive. Rank 1-10 =
    A+, 11-25 = A, 26-50 = B, 51-75 = C, 76-98 = D, else F."""
    try:
        from agent.finance import relative_strength as rs
        payload = rs._cached("US")
        if payload is None:
            rows = rs._compute_us_rs()
            payload = {"market": "US", "count": len(rows), "entries": rows,
                       "fetched_at_epoch": int(time.time())}
            rs._put("US", payload)
        entries = payload.get("entries", [])
        by_3m = sorted(
            [e for e in entries if e.get("return_3m") is not None],
            key=lambda e: -e["return_3m"],
        )
        rank = next(
            (i + 1 for i, e in enumerate(by_3m) if e["symbol"].upper() == symbol.upper()),
            None,
        )
        if rank is None:
            return {"grade": "—", "raw": None, "note": "not in S&P 100 universe"}
        total = len(by_3m)
        # Tighter bands: being top-10 is meaningfully different from top-50
        if rank <= total * 0.10: g = "A+"
        elif rank <= total * 0.25: g = "A"
        elif rank <= total * 0.50: g = "B"
        elif rank <= total * 0.75: g = "C"
        elif rank <= total * 0.95: g = "D"
        else: g = "F"
        return {"grade": g, "raw": rank, "note": f"rank {rank}/{total} by 3M"}
    except Exception as exc:
        logger.debug("momentum failed for %s: %s", symbol, exc)
        return {"grade": "—", "raw": None, "note": "unavailable"}


def _value_from_info(info: Dict[str, Any]) -> Dict[str, Any]:
    pe = _safe_float(info.get("trailingPE"))
    if pe is None or pe < 0:
        # Negative PE — unprofitable company; don't punish or reward,
        # flag with "—" so the user knows this axis doesn't apply.
        return {"grade": "—", "raw": None, "note": "negative or missing PE"}
    grade, raw = _grade_lte(pe, _VALUE_BANDS)
    return {"grade": grade, "raw": raw, "note": f"trailing PE {raw}"}


def _quality_from_info(info: Dict[str, Any]) -> Dict[str, Any]:
    roe = _safe_float(info.get("returnOnEquity"))     # decimal: 0.15 = 15%
    dte = _safe_float(info.get("debtToEquity"))        # in %: 100 = 1:1
    margin = _safe_float(info.get("profitMargins"))    # decimal

    # Normalize each sub-signal to 0-100, then mean.
    sub = []
    notes = []
    if roe is not None:
        # ROE 30% → 100; 0% → 50; -30% → 0 (squashed)
        sub.append(max(0, min(100, (roe * 100 + 30) * (100 / 60))))
        notes.append(f"ROE {roe * 100:.1f}%")
    if dte is not None:
        # Debt/equity: <50 → 100; 200 → 0
        sub.append(max(0, min(100, 100 - (dte / 2))))
        notes.append(f"D/E {dte:.0f}%")
    if margin is not None:
        # Profit margin 30% → 100; 0% → 50; -30% → 0
        sub.append(max(0, min(100, (margin * 100 + 30) * (100 / 60))))
        notes.append(f"margin {margin * 100:.1f}%")

    if not sub:
        return {"grade": "—", "raw": None, "note": "no fundamentals"}
    composite = sum(sub) / len(sub)
    grade, _ = _grade_gte(composite, _QUALITY_SCORE_BANDS)
    return {
        "grade": grade,
        "raw": round(composite, 1),
        "note": " · ".join(notes),
    }


def _growth_from_info(info: Dict[str, Any]) -> Dict[str, Any]:
    rg = _safe_float(info.get("revenueGrowth"))   # decimal
    eg = _safe_float(info.get("earningsGrowth"))
    if rg is None and eg is None:
        return {"grade": "—", "raw": None, "note": "no growth data"}
    # Average, convert to percent
    vals = [v for v in (rg, eg) if v is not None]
    avg_pct = sum(vals) / len(vals) * 100.0
    grade, _ = _grade_gte(avg_pct, _GROWTH_SCORE_BANDS)
    notes = []
    if rg is not None: notes.append(f"rev {rg * 100:.1f}%")
    if eg is not None: notes.append(f"eps {eg * 100:.1f}%")
    return {"grade": grade, "raw": round(avg_pct, 1), "note": " · ".join(notes)}


def _revisions_from_info(info: Dict[str, Any]) -> Dict[str, Any]:
    """Use forwardEPS vs trailing as a cheap revision proxy. Positive
    delta = analysts raising numbers; negative = cutting."""
    fwd = _safe_float(info.get("epsForward"))
    cur = _safe_float(info.get("epsCurrentYear")) or _safe_float(info.get("trailingEps"))
    if fwd is None or cur is None or cur == 0:
        return {"grade": "—", "raw": None, "note": "no EPS data"}
    delta_pct = (fwd - cur) / abs(cur) * 100.0
    # Tighter bands — revisions are narrow
    if delta_pct >= 20: g = "A+"
    elif delta_pct >= 10: g = "A"
    elif delta_pct >= 3: g = "B"
    elif delta_pct >= -3: g = "C"
    elif delta_pct >= -10: g = "D"
    else: g = "F"
    return {"grade": g, "raw": round(delta_pct, 1), "note": f"EPS fwd/cur +{delta_pct:.1f}%"}


def _compute(symbol: str) -> Dict[str, Any]:
    import yfinance as yf
    t = yf.Ticker(symbol)
    info = {}
    try:
        info = t.info or {}
    except Exception as exc:
        logger.debug("info failed for %s: %s", symbol, exc)

    axes = {
        "momentum": _momentum_from_rs(symbol),
        "value": _value_from_info(info),
        "quality": _quality_from_info(info),
        "growth": _growth_from_info(info),
        "revisions": _revisions_from_info(info),
    }

    overall = _compose_letter_grade({k: v["grade"] for k, v in axes.items()})

    return {
        "symbol": symbol,
        "overall_grade": overall,
        "axes": axes,
        "fetched_at_epoch": int(time.time()),
    }


def build_factors_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/factors/{symbol}")
    def factors(symbol: str) -> Dict[str, Any]:
        sym = symbol.upper().strip()
        if not _SYMBOL_RE.match(sym):
            raise HTTPException(400, f"invalid symbol {symbol!r}")
        cached = _cached(sym)
        if cached is not None:
            return cached
        try:
            data = _compute(sym)
        except ImportError as exc:
            raise HTTPException(503, f"yfinance unavailable: {exc}")
        except Exception as exc:
            logger.exception("factors compute failed for %s", sym)
            raise HTTPException(502, f"factors failed: {exc}")
        _put(sym, data)
        return data

    return router
