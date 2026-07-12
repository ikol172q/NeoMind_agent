"""Miniflux API proxy — read-only financial news for the fin dashboard.

Talks to a self-hosted Miniflux instance (Docker, bound to
``127.0.0.1:8080``) via HTTP Basic Auth. Returns a normalised entry
list for the dashboard UI and the /api/news endpoint. Never writes to
Miniflux or the Investment root.

Env vars (read once per request via ``_get_config``):

    MINIFLUX_URL       default http://127.0.0.1:8080
    MINIFLUX_USERNAME  required
    MINIFLUX_PASSWORD  required

If credentials are missing, /api/news returns 503 with a clear hint
rather than crashing. This keeps the dashboard functional before
Miniflux is configured.

Symbol filtering (v1): case-insensitive substring match against entry
title. Miniflux supports real tags but wiring that requires manual
feed configuration; substring match is zero-config.
"""

from __future__ import annotations

import html
import logging
import os
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import urllib.parse
import urllib.request
import base64
import json as _json

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

# Clamp limits — prevent accidental huge fetches
_MAX_LIMIT = 100
_DEFAULT_LIMIT = 20
_REQUEST_TIMEOUT_S = 5.0

# Strip naive HTML for content snippets — Miniflux returns full HTML
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


# ── Official company newsroom feeds (RSS) ───────────────────────────
# Primary-source PRs straight from the company's own newsroom, fully
# independent of Miniflux. Map ticker → RSS feed URL. ARM's newsroom is
# WordPress (/feed verified 2026-06-25).
#
# Persistence: items live in the `official_news` table so the
# `official_news_pull` scheduler job (a SEPARATE process) can keep them
# fresh hourly (真·定时) and the endpoint serves from the table
# instantly. The endpoint ALSO live-refreshes on cold start, when the
# stored copy is older than the TTL, or when ?refresh=1 is passed — so
# freshness holds even if the scheduler is down.
OFFICIAL_FEEDS: Dict[str, str] = {
    "ARM": "https://newsroom.arm.com/feed",
    # 2026-06-26: added for held names. Each URL curl-verified to return
    # valid RSS 2.0 <item> elements (NOT guessed — see anti-hallucination
    # skill). AAPL/MRVL/MP/AAOI/NBIS/CBRS deliberately omitted: no public
    # standard-RSS feed found (Apple feed returns 0 <item>; the rest 404 or
    # serve HTML SPAs). SEC-filings fallback is the scalable next step.
    "META":  "https://about.fb.com/news/feed/",            # Meta newsroom
    "GOOGL": "https://blog.google/rss/",                    # The Keyword (official)
    "AMD":   "https://ir.amd.com/rss/news-releases.xml",   # AMD IR press releases
    "PANW":  "https://www.paloaltonetworks.com/blog/feed/", # PANW blog
}
_OFFICIAL_TTL_S = 3600.0
_OFFICIAL_UA = "Mozilla/5.0 (NeoMind-Fin newsbot) research@example.com"


def _fetch_official_feed(url: str) -> List[Dict[str, str]]:
    """Fetch + parse a company newsroom RSS into normalised items.
    Server-side (no CORS); standard RSS 2.0 <item> shape."""
    import xml.etree.ElementTree as ET
    req = urllib.request.Request(url, headers={"User-Agent": _OFFICIAL_UA})
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read()
    root = ET.fromstring(raw)
    items: List[Dict[str, str]] = []
    for it in root.findall(".//item"):
        desc = it.findtext("description") or ""
        snippet = _WS_RE.sub(" ", _TAG_RE.sub("", html.unescape(desc))).strip()
        items.append({
            "title":        (it.findtext("title") or "").strip(),
            "url":          (it.findtext("link") or "").strip(),
            "published_at": (it.findtext("pubDate") or "").strip(),
            "snippet":      snippet[:280],
        })
    return items


def _age_seconds(iso: Optional[str]) -> Optional[float]:
    if not iso:
        return None
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds()
    except Exception:
        return None


def _ensure_official_table(conn) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS official_news ("
        " ticker TEXT PRIMARY KEY, fetched_at TEXT, items_json TEXT)"
    )


def _read_official(ticker: str):
    """Return (fetched_at_iso, items) from the table, or None."""
    from agent.finance.persistence import connect
    with connect() as conn:
        _ensure_official_table(conn)
        row = conn.execute(
            "SELECT fetched_at, items_json FROM official_news WHERE ticker = ?",
            (ticker,),
        ).fetchone()
    if not row:
        return None
    try:
        items = _json.loads(row[1] or "[]")
    except Exception:
        items = []
    return row[0], items


def refresh_official(ticker: str):
    """Fetch the live feed + upsert into official_news. Returns
    (fetched_at_iso, items). Used by the endpoint (cold start / forced
    refresh) AND the official_news_pull scheduler job."""
    from agent.finance.persistence import connect
    feed = OFFICIAL_FEEDS.get(ticker)
    if not feed:
        return None
    items = _fetch_official_feed(feed)
    now = datetime.now(timezone.utc).isoformat()
    with connect() as conn:
        _ensure_official_table(conn)
        conn.execute(
            "INSERT INTO official_news (ticker, fetched_at, items_json) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(ticker) DO UPDATE SET "
            "  fetched_at = excluded.fetched_at, items_json = excluded.items_json",
            (ticker, now, _json.dumps(items, ensure_ascii=False)),
        )
    return now, items


@dataclass(frozen=True)
class NewsEntry:
    id: int
    title: str
    url: str
    published_at: str
    feed_title: str
    snippet: str


def _get_config() -> Dict[str, str]:
    url = os.environ.get("MINIFLUX_URL", "http://127.0.0.1:8080").rstrip("/")
    user = os.environ.get("MINIFLUX_USERNAME", "").strip()
    pw = os.environ.get("MINIFLUX_PASSWORD", "").strip()
    if not user or not pw:
        raise HTTPException(
            503,
            "Miniflux credentials missing — set MINIFLUX_USERNAME and "
            "MINIFLUX_PASSWORD in .env, then `docker compose up -d miniflux`",
        )
    return {"url": url, "user": user, "pw": pw}


def _basic_auth_header(user: str, pw: str) -> str:
    raw = f"{user}:{pw}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _strip_html(s: str, max_len: int = 220) -> str:
    if not s:
        return ""
    txt = html.unescape(_TAG_RE.sub(" ", s))
    txt = _WS_RE.sub(" ", txt).strip()
    if len(txt) > max_len:
        txt = txt[: max_len - 1].rstrip() + "…"
    return txt


def _normalise_entry(raw: Dict[str, Any]) -> Optional[NewsEntry]:
    try:
        return NewsEntry(
            id=int(raw.get("id") or 0),
            title=str(raw.get("title") or "").strip(),
            url=str(raw.get("url") or "").strip(),
            published_at=str(raw.get("published_at") or ""),
            feed_title=str((raw.get("feed") or {}).get("title") or ""),
            snippet=_strip_html(str(raw.get("content") or "")),
        )
    except Exception as exc:
        logger.debug("news_hub: dropping malformed entry: %s", exc)
        return None


def search_entries(query: str, limit: int = _DEFAULT_LIMIT) -> List[NewsEntry]:
    """Use Miniflux's native /v1/entries?search= which matches both
    title AND content. Much higher recall than the post-hoc title
    substring filter in fetch_entries(). Best for ticker-scoped
    drawer queries where the ticker symbol may not be in the title."""
    cfg = _get_config()
    limit = max(1, min(int(limit), _MAX_LIMIT))
    qs = urllib.parse.urlencode({
        "search": query,
        "limit": limit,
        "order": "published_at",
        "direction": "desc",
    })
    req = urllib.request.Request(
        f"{cfg['url']}/v1/entries?{qs}",
        headers={
            "Authorization": _basic_auth_header(cfg["user"], cfg["pw"]),
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT_S) as resp:
            payload = _json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise HTTPException(503, "Miniflux 401 — check credentials")
        raise HTTPException(502, f"miniflux upstream {exc.code}: {exc.reason}")
    except urllib.error.URLError as exc:
        raise HTTPException(503, f"miniflux unreachable: {exc.reason}")
    entries: List[NewsEntry] = []
    for r in (payload.get("entries") or []):
        n = _normalise_entry(r)
        if n is not None:
            entries.append(n)
    return entries


def fetch_entries(
    limit: int = _DEFAULT_LIMIT,
    symbols: Optional[List[str]] = None,
    order: str = "published_at",
    direction: str = "desc",
    category_id: Optional[int] = None,
) -> List[NewsEntry]:
    """Pull recent entries from Miniflux. Raises HTTPException on
    config / network errors — callers (the FastAPI route) propagate
    to the client as-is.

    When ``category_id`` is set, uses Miniflux's per-category entries
    endpoint instead of the global feed, so we get only that
    category's items (e.g. 美股, A股, Tech, Macro).
    """
    cfg = _get_config()
    limit = max(1, min(int(limit), _MAX_LIMIT))
    query = urllib.parse.urlencode({
        "limit": limit,
        "order": order,
        "direction": direction,
    })
    if category_id is not None:
        req_url = f"{cfg['url']}/v1/categories/{int(category_id)}/entries?{query}"
    else:
        req_url = f"{cfg['url']}/v1/entries?{query}"
    req = urllib.request.Request(
        req_url,
        headers={
            "Authorization": _basic_auth_header(cfg["user"], cfg["pw"]),
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT_S) as resp:
            payload = _json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise HTTPException(
                503, "Miniflux 401 — check MINIFLUX_USERNAME / MINIFLUX_PASSWORD"
            )
        raise HTTPException(502, f"miniflux upstream {exc.code}: {exc.reason}")
    except urllib.error.URLError as exc:
        raise HTTPException(
            503,
            f"miniflux unreachable at {cfg['url']} ({exc.reason}). "
            f"Run `docker compose up -d miniflux`.",
        )
    except Exception as exc:
        raise HTTPException(502, f"miniflux fetch failed: {exc}")

    raw_entries = payload.get("entries") or []
    entries: List[NewsEntry] = []
    for r in raw_entries:
        n = _normalise_entry(r)
        if n is not None:
            entries.append(n)

    if symbols:
        wanted = {s.strip().upper() for s in symbols if s and s.strip()}
        if wanted:
            entries = [
                e for e in entries
                if any(sym in e.title.upper() for sym in wanted)
            ]
    return entries


def build_news_router() -> APIRouter:
    """Expose `/api/news` on the dashboard FastAPI app."""
    router = APIRouter()

    @router.get("/api/news")
    def list_news(
        limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
        symbols: Optional[str] = Query(
            None,
            description="comma-separated list of tickers to filter "
                        "titles against (case-insensitive substring)",
        ),
        category_id: Optional[int] = Query(
            None,
            description="Miniflux category id. When set, only entries "
                        "in that category are returned.",
        ),
    ) -> Dict[str, Any]:
        sym_list: Optional[List[str]] = None
        if symbols:
            sym_list = [
                s for s in symbols.split(",") if s.strip()
            ][:20]
        entries = fetch_entries(limit=limit, symbols=sym_list, category_id=category_id)
        return {
            "count": len(entries),
            "entries": [asdict(e) for e in entries],
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "category_id": category_id,
        }

    @router.get("/api/news/by_ticker/{ticker}")
    def news_by_ticker(
        ticker: str,
        limit: int = Query(20, ge=1, le=_MAX_LIMIT),
    ) -> Dict[str, Any]:
        """Per-ticker news for the Stock Research Drawer News tab.

        Uses Miniflux's native /v1/entries?search= so we match BOTH
        title and content — much higher recall than the post-hoc
        substring filter on /api/news (the ticker symbol often
        appears in body but not headline)."""
        sym = (ticker or "").strip().upper()
        if not sym:
            raise HTTPException(400, "ticker required")
        entries = search_entries(sym, limit=limit)
        return {
            "ticker": sym,
            "count": len(entries),
            "entries": [asdict(e) for e in entries],
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "fallback_search_url":
                f"https://news.google.com/search?q={urllib.parse.quote(sym)}+stock",
        }

    @router.get("/api/news/official/{ticker}")
    def official_news(
        ticker: str,
        limit: int = Query(8, ge=1, le=30),
        refresh: bool = Query(False, description="force a live re-fetch now"),
    ) -> Dict[str, Any]:
        """Primary-source PRs from the company's OWN newsroom RSS,
        DB-backed (official_news table). Served instantly from the table
        (kept fresh hourly by the official_news_pull scheduler job).
        Live-refreshes on cold start, when the stored copy is older than
        the TTL, or when ?refresh=1. `source` = 'live' (fetched this
        request) or 'store'; `stale` = older than the TTL."""
        sym = (ticker or "").strip().upper()
        feed = OFFICIAL_FEEDS.get(sym)
        if not feed:
            return {"ticker": sym, "supported": False, "items": [], "feed_url": None}
        stored = _read_official(sym)            # (fetched_at, items) | None
        age = _age_seconds(stored[0]) if stored else None
        did_fetch = False
        if refresh or stored is None or age is None or age > _OFFICIAL_TTL_S:
            try:
                fetched_at, items = refresh_official(sym)
                stored = (fetched_at, items)
                did_fetch = True
            except Exception as exc:
                logger.warning("official feed refresh failed for %s: %s", sym, exc)
                # keep whatever was stored (serve stale) — endpoint never 500s
        fetched_at, items = stored if stored else (None, [])
        age = _age_seconds(fetched_at)
        return {
            "ticker": sym, "supported": True, "feed_url": feed,
            "count": len(items), "items": items[:limit],
            "fetched_at": fetched_at,
            "age_seconds": age,
            "source": "live" if did_fetch else "store",
            "stale": (age is not None and age > _OFFICIAL_TTL_S),
        }

    @router.get("/api/news/categories")
    def list_categories() -> Dict[str, Any]:
        """Return Miniflux categories enriched with feed count, sorted
        by feed count desc so the most-populated category leads. Empty
        categories are dropped — they add tabs the user can't use.
        The UI overlays a synthetic 'All' tab that uses no filter."""
        cfg = _get_config()
        auth = _basic_auth_header(cfg["user"], cfg["pw"])

        def _get(path: str) -> Any:
            req = urllib.request.Request(
                f"{cfg['url']}{path}",
                headers={"Authorization": auth, "Accept": "application/json"},
            )
            try:
                with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT_S) as resp:
                    return _json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                raise HTTPException(502, f"miniflux {path} {exc.code}: {exc.reason}")
            except urllib.error.URLError as exc:
                raise HTTPException(
                    503,
                    f"miniflux unreachable at {cfg['url']} ({exc.reason})",
                )

        cats = _get("/v1/categories")
        feeds = _get("/v1/feeds")
        counts: Dict[int, int] = {}
        for f in feeds:
            cid = (f.get("category") or {}).get("id")
            if cid:
                counts[int(cid)] = counts.get(int(cid), 0) + 1

        out = []
        for c in cats:
            try:
                cid = int(c.get("id") or 0)
            except Exception:
                continue
            feed_count = counts.get(cid, 0)
            if feed_count == 0:
                continue
            out.append({
                "id": cid,
                "title": str(c.get("title") or ""),
                "feed_count": feed_count,
            })
        out.sort(key=lambda x: (-x["feed_count"], x["title"]))
        return {"categories": out}

    @router.get("/api/news/health")
    def news_health() -> Dict[str, Any]:
        """Quick check: is Miniflux reachable with configured creds?"""
        try:
            _get_config()
        except HTTPException as exc:
            return {"ok": False, "reason": exc.detail}
        try:
            fetch_entries(limit=1)
        except HTTPException as exc:
            return {"ok": False, "reason": exc.detail}
        return {"ok": True}

    return router
