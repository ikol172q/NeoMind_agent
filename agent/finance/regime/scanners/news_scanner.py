"""News scanner — per-ticker headlines via yfinance.

For each watchlist + supply-chain ticker, fetch the last N news items
attached to that symbol on Yahoo Finance.  Each item is already
ticker-tagged by Yahoo, so we don't need to do entity recognition.

Emits signal_event with scanner_name='news'.  Dedup by source_url
(content hash) so re-runs within an hour don't double-emit.

Severity heuristic (deliberately simple — LLM sentiment is too noisy
for confluence triggering):
  - "high" if title contains any of:
      ['surge', 'jump', 'rally', 'record', 'beats', 'tops',
       'plunge', 'crash', 'tumble', 'miss', 'cuts', 'downgrade',
       'investigation', 'lawsuit', 'recall', 'earnings']
  - "med" otherwise
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


_HIGH_SIGNAL_KEYWORDS = [
    # bullish
    "surge", "surged", "surges",
    "jump", "jumped", "jumps",
    "rally", "rallied", "rallies",
    "record", "high", "ath",
    "beat", "beats", "tops", "topped",
    "upgrade", "upgraded", "upgrades",
    "soars", "soared",
    # bearish
    "plunge", "plunged", "plunges",
    "crash", "crashed", "crashes",
    "tumble", "tumbled", "tumbles",
    "miss", "missed", "misses",
    "cut", "cuts", "slash", "slashes",
    "downgrade", "downgraded", "downgrades",
    "investigation", "lawsuit", "recall", "fraud",
    "loss", "losses",
    "warning", "warns",
    # neutral but high-importance
    "earnings", "dividend",
    "acquisition", "acquires", "acquired",
    "merger", "buyback",
    "guidance", "forecast",
    "fed", "fomc",
]


def _classify_severity(title: str) -> str:
    """Simple keyword-based severity. Med default; high if any signal keyword."""
    if not title:
        return "low"
    lower = title.lower()
    for kw in _HIGH_SIGNAL_KEYWORDS:
        if re.search(rf"\b{re.escape(kw)}\b", lower):
            return "high"
    return "med"


def _import_yfinance() -> Any:
    try:
        import yfinance as yf
        return yf
    except ImportError as exc:
        raise RuntimeError(
            f"yfinance not installed in this venv ({exc}). "
            f"In .venv-host: pip install yfinance"
        )


def _already_emitted_url(source_url: str) -> bool:
    """Idempotency: have we emitted this exact news URL before (any time)?"""
    from agent.finance.persistence import connect
    if not source_url:
        return False
    with connect() as conn:
        cur = conn.execute(
            "SELECT event_id FROM signal_events "
            "WHERE scanner_name = 'news' AND source_url = ? LIMIT 1",
            (source_url,),
        )
        return cur.fetchone() is not None


def scan_news_for_ticker(
    ticker: str,
    *,
    max_items: int = 5,
) -> Dict[str, Any]:
    """Pull last N news items for one ticker, emit unseen ones."""
    from agent.finance.regime.signals import emit_event

    yf = _import_yfinance()
    try:
        t = yf.Ticker(ticker)
        news = t.news or []
    except Exception as exc:
        logger.warning("news pull failed for %s: %s", ticker, exc)
        return {"ticker": ticker, "emitted": 0, "error": str(exc)}

    n_emitted = 0
    n_seen = 0
    for raw_item in news[:max_items]:
        # yfinance returns either a flat dict (older) or {'content': {...}} (newer).
        # Normalize both shapes.
        item = raw_item.get("content", raw_item) if isinstance(raw_item, dict) else {}
        title = item.get("title") or ""
        link = (
            item.get("clickThroughUrl", {}).get("url")
            if isinstance(item.get("clickThroughUrl"), dict) else None
        ) or item.get("link") or item.get("canonicalUrl", {}).get("url") if isinstance(item.get("canonicalUrl"), dict) else None
        publisher = (
            item.get("provider", {}).get("displayName")
            if isinstance(item.get("provider"), dict) else None
        ) or item.get("publisher") or "yahoo_news"
        # Time can be unix epoch (older) or ISO (newer)
        pub_ts = item.get("pubDate") or item.get("providerPublishTime")
        ts_iso = None
        if isinstance(pub_ts, (int, float)):
            ts_iso = datetime.fromtimestamp(pub_ts, tz=timezone.utc).isoformat(timespec="seconds")
        elif isinstance(pub_ts, str) and pub_ts:
            ts_iso = pub_ts

        if not title or not link:
            continue
        n_seen += 1
        if _already_emitted_url(link):
            continue

        sev = _classify_severity(title)
        emit_event(
            "news",
            signal_type="news_mention",
            severity=sev,
            ticker=ticker,
            title=f"{ticker}: {title[:200]}",
            body={
                "publisher": publisher,
                "headline":  title,
            },
            source_url=link,
            source_timestamp=ts_iso,
        )
        n_emitted += 1

    return {"ticker": ticker, "n_seen": n_seen, "emitted": n_emitted}


def run_news_scan() -> Dict[str, Any]:
    """Scan all watchlist + supply-chain tickers for news."""
    from agent.finance.regime.signals import (
        list_watchlist, expand_supply_chain,
    )
    t0 = time.monotonic()
    wl = list_watchlist()
    user_tickers = [w["ticker"] for w in wl]
    expanded = expand_supply_chain(user_tickers)
    all_tickers = sorted(set(user_tickers + expanded))

    n_emitted = 0
    per_ticker: List[Dict[str, Any]] = []
    for t in all_tickers:
        try:
            r = scan_news_for_ticker(t)
            per_ticker.append(r)
            n_emitted += r.get("emitted", 0)
        except Exception as exc:
            logger.warning("news scan failed for %s: %s", t, exc)
            per_ticker.append({"ticker": t, "error": str(exc)})

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    return {
        "scanner":    "news",
        "n_tickers":  len(all_tickers),
        "n_user":     len(user_tickers),
        "n_expanded": len(expanded),
        "n_emitted":  n_emitted,
        "took_ms":    elapsed_ms,
        "per_ticker": per_ticker,
    }
