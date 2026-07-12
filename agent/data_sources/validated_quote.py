"""Cross-source validated quote — first concrete instance of the validation
layer (准确性 pillar).

Principle (per the agreed reframe): not "zero errors" (impossible), but
**known confidence per datum**. Every price reconciles Finnhub (real-time
primary) against yfinance (independent cross-check) and carries:
  · confidence: high (2 sources agree) / low (2 sources DIVERGE — suspect) /
    medium (single source) / none (no data)
  · divergence_pct + the source list, so the decision engine knows how much to
    trust the number instead of treating every quote as equally certain.

Degrades gracefully: if Finnhub has no key / errors, falls back to yfinance
(confidence=medium); if yfinance is throttled, Finnhub alone (medium). Both
down → confidence=none, price=None (honest, not fabricated).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from agent.data_sources.finnhub_quote import get_finnhub_quote

logger = logging.getLogger(__name__)

# within this %, the two sources are considered to agree
DIVERGENCE_TOL_PCT = 0.5


def _yf_price(ticker: str) -> Optional[float]:
    """Lightweight yfinance cross-check (fast_info only — avoids the heavy,
    throttle-prone .info path). FastInfo's dict key is camelCase 'lastPrice';
    attribute access is snake_case 'last_price' — try both defensively."""
    try:
        import yfinance as yf
        fi = yf.Ticker(ticker).fast_info
        v = None
        for get in (lambda: fi["lastPrice"], lambda: fi.last_price):
            try:
                v = get()
                if v:
                    break
            except Exception:
                continue
        return float(v) if v else None
    except Exception:
        return None


def get_validated_quote(ticker: str) -> Dict[str, Any]:
    ticker = ticker.upper().strip()
    fh = get_finnhub_quote(ticker)
    fh_price = fh.get("price") if fh else None
    yf_price = _yf_price(ticker)

    sources: list[str] = []
    price: Optional[float] = None
    day_change_pct: Optional[float] = None
    prev_close: Optional[float] = None
    divergence: Optional[float] = None

    if fh_price:
        sources.append("finnhub")
        price = fh_price
        day_change_pct = fh.get("day_change_pct")
        prev_close = fh.get("prev_close")
    if yf_price:
        sources.append("yfinance")

    if fh_price and yf_price:
        divergence = abs(fh_price - yf_price) / yf_price * 100.0
        confidence = "high" if divergence <= DIVERGENCE_TOL_PCT else "low"
    elif fh_price or yf_price:
        confidence = "medium"
        if price is None:        # only yfinance available
            price = yf_price
    else:
        confidence = "none"

    return {
        "ticker": ticker,
        "price": price,
        "day_change_pct": day_change_pct,
        "prev_close": prev_close,
        "confidence": confidence,
        "divergence_pct": round(divergence, 3) if divergence is not None else None,
        "sources": sources,
        "asof": datetime.now(timezone.utc).isoformat(),
    }
