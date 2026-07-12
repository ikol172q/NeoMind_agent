"""Finnhub quote source — reliable (near-)real-time US equity quotes.

Replaces the throttle-prone yfinance path for the PRICE dimension. Finnhub's
free tier gives real-time US stock quotes at 60 req/min — far more stable than
yfinance's session-throttled `fast_info`/`info`. Personal-use license (this is
a local dashboard, no commercial redistribution).

Key from FINNHUB_API_KEY (env, set in ~/.zshrc per project convention). If the
key is absent, returns None so callers degrade gracefully to yfinance.

/quote returns: c=current, d=Δ, dp=Δ%, h/l/o=day high/low/open, pc=prev close.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_BASE = "https://finnhub.io/api/v1"
_TTL_S = 30.0          # real-time, but cache 30s to stay well under 60/min
_TIMEOUT_S = 10.0
_cache: dict[str, tuple[float, Dict[str, Any]]] = {}
_lock = threading.Lock()


def _key() -> str:
    return (os.getenv("FINNHUB_API_KEY") or "").strip()


def has_key() -> bool:
    return bool(_key())


def get_finnhub_quote(ticker: str) -> Optional[Dict[str, Any]]:
    """Real-time quote dict, or None (no key / invalid ticker / API error)."""
    key = _key()
    if not key:
        return None
    ticker = ticker.upper().strip()
    now = time.time()
    with _lock:
        hit = _cache.get(ticker)
        if hit and (now - hit[0]) < _TTL_S:
            return hit[1]
    try:
        url = f"{_BASE}/quote?symbol={urllib.parse.quote(ticker)}&token={key}"
        with urllib.request.urlopen(url, timeout=_TIMEOUT_S) as r:
            d = json.load(r)
    except Exception as exc:  # noqa: BLE001 — any network/parse error → degrade
        logger.warning("finnhub quote %s failed: %s", ticker, exc)
        return None
    c = d.get("c")
    # Finnhub returns c=0 (and pc=0) for symbols it has no data for.
    if not c:
        return None
    out = {
        "ticker": ticker, "price": c, "day_change_pct": d.get("dp"),
        "prev_close": d.get("pc"), "high": d.get("h"), "low": d.get("l"),
        "open": d.get("o"), "ts": d.get("t"), "source": "finnhub",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    with _lock:
        _cache[ticker] = (now, out)
    return out
