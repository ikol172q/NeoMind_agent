"""Market temperature gauge — a pragmatic Fear/Greed proxy.

Full Xueqiu-polarity / news-sentiment classification was deferred
because it demands a local NLP model (≥200 MB) and doesn't fit our
"dashboard boots with no extra downloads" constraint. This module
computes a useful sentiment-ish reading from numbers we already
fetch: VIX level, SPY momentum, and S&P 100 breadth.

Three sub-scores, each mapped to 0–100 (higher = greedier):

  VIX percentile  — position of current VIX close in trailing 252d
                    history. Inverted: low VIX percentile = low fear
                    = higher greed score.
  SPY momentum    — 20-day SPY % return, mapped from -10%..+10% to
                    0..100.
  Breadth         — % of the S&P 100 universe up today (last day's
                    close > prior close). Directly mapped to 0..100.

Composite = simple mean of the three (each contributes equally).
Weights can be revisited; equal weighting is neutral and keeps the
widget explainable ("which lever moved the needle?").

Cached 10 min.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

_TTL_S = 600.0
_cache: Dict[str, tuple[float, Dict[str, Any]]] = {}
_cache_lock = threading.Lock()

# Reuse the RS module's S&P 100 list — same "large caps, liquid"
# universe; breadth across it is a cleaner signal than "full SPX
# members" (which would need a constituent feed).
from agent.finance.relative_strength import _US_UNIVERSE  # noqa: E402


def _cached() -> Optional[Dict[str, Any]]:
    with _cache_lock:
        entry = _cache.get("market")
    if entry is None:
        return None
    if time.time() - entry[0] > _TTL_S:
        return None
    return entry[1]


def _put(value: Dict[str, Any]) -> None:
    with _cache_lock:
        _cache["market"] = (time.time(), value)


def _vix_subscore():
    """Returns (score_0_100, {raw, percentile_pct})."""
    import yfinance as yf
    v = yf.Ticker("^VIX")
    hist = v.history(period="1y", interval="1d", auto_adjust=False)
    if hist is None or hist.empty or len(hist) < 20:
        return None, {}
    closes = hist["Close"].dropna()
    current = float(closes.iloc[-1])
    pct = float((closes < current).mean() * 100.0)
    # Invert: high VIX percentile = high fear = low greed score
    score = max(0.0, min(100.0, 100.0 - pct))
    return round(score, 1), {"raw": round(current, 2), "percentile_pct": round(pct, 1)}


def _spy_momentum_subscore():
    """Returns (score_0_100, {return_20d_pct})."""
    import yfinance as yf
    hist = yf.Ticker("SPY").history(period="3mo", interval="1d", auto_adjust=False)
    if hist is None or hist.empty or len(hist) < 21:
        return None, {}
    closes = hist["Close"].dropna()
    mom = float((closes.iloc[-1] / closes.iloc[-21] - 1.0) * 100.0)
    # Map -10% → 0, +10% → 100, linear
    score = max(0.0, min(100.0, 50.0 + mom * 5.0))
    return round(score, 1), {"return_20d_pct": round(mom, 2)}


def _breadth_subscore():
    """% of S&P 100 universe up today. Returns (score_0_100, {up, down, total})."""
    import yfinance as yf
    df = yf.download(
        _US_UNIVERSE,
        period="5d",
        interval="1d",
        group_by="ticker",
        progress=False,
        auto_adjust=False,
        threads=False,
    )
    up = 0
    down = 0
    for sym in _US_UNIVERSE:
        try:
            sub = df[sym]["Close"].dropna()
            if len(sub) < 2:
                continue
            last, prev = float(sub.iloc[-1]), float(sub.iloc[-2])
            if last > prev:
                up += 1
            elif last < prev:
                down += 1
        except Exception:
            continue
    total = up + down
    if total == 0:
        return None, {}
    score = round(up / total * 100.0, 1)
    return score, {"up": up, "down": down, "total": total}


def _compute() -> Dict[str, Any]:
    vix_score, vix_extra = _vix_subscore()
    mom_score, mom_extra = _spy_momentum_subscore()
    br_score, br_extra = _breadth_subscore()

    parts = [s for s in (vix_score, mom_score, br_score) if s is not None]
    composite = round(sum(parts) / len(parts), 1) if parts else None

    def label_for(score: Optional[float]) -> str:
        if score is None:
            return "unknown"
        if score >= 75:
            return "extreme greed"
        if score >= 55:
            return "greed"
        if score >= 45:
            return "neutral"
        if score >= 25:
            return "fear"
        return "extreme fear"

    return {
        "composite_score": composite,
        "label": label_for(composite),
        "components": {
            "vix": {"score": vix_score, **vix_extra},
            "spy_momentum": {"score": mom_score, **mom_extra},
            "breadth": {"score": br_score, **br_extra},
        },
        "fetched_at_epoch": int(time.time()),
    }


def build_sentiment_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/sentiment")
    def get_sentiment() -> Dict[str, Any]:
        cached = _cached()
        if cached is not None:
            return cached
        try:
            data = _compute()
        except ImportError as exc:
            raise HTTPException(503, f"yfinance unavailable: {exc}")
        except Exception as exc:
            logger.exception("sentiment compute failed")
            raise HTTPException(502, f"sentiment compute failed: {exc}")
        _put(data)
        return data

    return router
