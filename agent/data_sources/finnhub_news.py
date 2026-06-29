"""Finnhub company-news source — free tier, same FINNHUB_API_KEY.

Slice 2: the news half of "重大事件预警". Finnhub /company-news returns recent
US company news (headline / summary / source / datetime / url). Free tier
covers it (verified), so no new vendor / no paid source needed.

Used as a new evidence stream for thesis_materiality (news vs thesis →
印证/动摇/破) so a material headline triggers "该复盘" — reporter, not decider.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_BASE = "https://finnhub.io/api/v1"
_TTL_S = 1800.0        # news changes slowly enough; cache 30m
_TIMEOUT_S = 12.0
_cache: dict[str, tuple[float, List[Dict[str, Any]]]] = {}
_lock = threading.Lock()


def _key() -> str:
    return (os.getenv("FINNHUB_API_KEY") or "").strip()


def get_company_news(ticker: str, days: int = 14, limit: int = 20) -> List[Dict[str, Any]]:
    """Recent company news, newest first, deduped by headline. [] on
    no-key / error / no news."""
    key = _key()
    if not key:
        return []
    ticker = ticker.upper().strip()
    cache_key = f"{ticker}:{days}:{limit}"
    now = time.time()
    with _lock:
        hit = _cache.get(cache_key)
        if hit and (now - hit[0]) < _TTL_S:
            return hit[1]

    today = datetime.now(timezone.utc).date()
    frm = (today - timedelta(days=days)).isoformat()
    to = today.isoformat()
    url = (f"{_BASE}/company-news?symbol={urllib.parse.quote(ticker)}"
           f"&from={frm}&to={to}&token={key}")
    try:
        with urllib.request.urlopen(url, timeout=_TIMEOUT_S) as r:
            raw = json.load(r)
    except Exception as exc:  # noqa: BLE001
        logger.warning("finnhub news %s failed: %s", ticker, exc)
        return []
    if not isinstance(raw, list):
        return []

    raw.sort(key=lambda n: n.get("datetime", 0), reverse=True)
    out: List[Dict[str, Any]] = []
    seen_headlines: set[str] = set()
    for n in raw:
        headline = (n.get("headline") or "").strip()
        if not headline:
            continue
        norm = headline.lower()[:80]
        if norm in seen_headlines:
            continue
        seen_headlines.add(norm)
        ts = n.get("datetime")
        out.append({
            "id": n.get("id"),
            "datetime": (datetime.fromtimestamp(ts, timezone.utc).isoformat() if ts else None),
            "date": (datetime.fromtimestamp(ts, timezone.utc).date().isoformat() if ts else None),
            "source": n.get("source"),
            "headline": headline,
            "summary": (n.get("summary") or "").strip(),
            "url": n.get("url"),
        })
        if len(out) >= limit:
            break

    with _lock:
        _cache[cache_key] = (now, out)
    return out
