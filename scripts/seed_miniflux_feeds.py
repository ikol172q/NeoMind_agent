#!/usr/bin/env python3
"""Seed the local Miniflux instance with a curated finance+tech feed
set, categorised for the NeoMind fin dashboard.

Idempotent: creates missing categories, adds missing feeds (keyed by
URL), leaves everything else alone. Re-categorises feeds that already
exist but are mis-assigned.

Run:
    .venv/bin/python scripts/seed_miniflux_feeds.py

Reads ``MINIFLUX_URL / MINIFLUX_USERNAME / MINIFLUX_PASSWORD`` from
the environment (same as the dashboard).

Categories produced:
    US         — 美股 + broad US markets
    A-Shares   — 中国 A股 + HK + China-focused English
    Global     — FT / Economist / global wire-style
    Tech       — Hacker News + tech business
    Macro      — central bank + macro data releases

Every category maps 1:1 to a Miniflux category. The "All" default
category is preserved as-is (Miniflux requires it).
"""
from __future__ import annotations

import json
import os
import sys
import base64
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional


DESIRED_CATEGORIES: List[str] = ["US", "A-Shares", "Global", "Tech", "Macro"]

# (category, title, feed_url)
# Keep the list deliberate — every feed a real person would want to
# open. Order roughly reflects signal-per-day.
DESIRED_FEEDS: List[tuple[str, str, str]] = [
    # ── US markets / equities ──
    ("US", "Bloomberg Markets", "https://feeds.bloomberg.com/markets/news.rss"),
    ("US", "WSJ.com: Markets", "https://feeds.a.dj.com/rss/RSSMarketsMain.xml"),
    ("US", "MarketWatch Top Stories", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("US", "CNBC US Top News", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("US", "Yahoo Finance", "https://finance.yahoo.com/news/rssindex"),
    ("US", "Seeking Alpha — Market Currents", "https://seekingalpha.com/market_currents.xml"),

    # ── A-Shares / HK / China ──
    ("A-Shares", "36氪", "https://36kr.com/feed"),
    # Caixin English (global covers China from HK desk — good signal, English)
    ("A-Shares", "Caixin Global — Finance", "https://www.caixinglobal.com/rss/finance.xml"),
    # SCMP Business — Hong Kong / greater-China business news
    ("A-Shares", "SCMP Business", "https://www.scmp.com/rss/92/feed"),

    # ── Global wire ──
    ("Global", "Financial Times", "https://www.ft.com/rss/home"),
    ("Global", "The Economist — Finance and economics", "https://www.economist.com/finance-and-economics/rss.xml"),
    ("Global", "Al Jazeera Economy", "https://www.aljazeera.com/xml/rss/all.xml"),

    # ── Tech (includes Hacker News as requested) ──
    ("Tech", "Hacker News — Frontpage", "https://hnrss.org/frontpage"),
    ("Tech", "Hacker News — Show HN", "https://hnrss.org/show"),
    ("Tech", "TechCrunch", "https://techcrunch.com/feed/"),
    ("Tech", "The Verge", "https://www.theverge.com/rss/index.xml"),

    # ── Macro / policy ──
    ("Macro", "Federal Reserve — All Press Releases",
     "https://www.federalreserve.gov/feeds/press_all.xml"),
    ("Macro", "BLS — All Recent News Releases",
     "https://www.bls.gov/feed/news_release.rss"),
    ("Macro", "BEA — News Releases", "https://www.bea.gov/news/rss.xml"),
]


def _config() -> Dict[str, str]:
    url = os.environ.get("MINIFLUX_URL", "http://127.0.0.1:8080").rstrip("/")
    user = os.environ.get("MINIFLUX_USERNAME", "").strip()
    pw = os.environ.get("MINIFLUX_PASSWORD", "").strip()
    if not user or not pw:
        # Try loading from .env if env vars not set
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env_path = os.path.join(repo, ".env")
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("MINIFLUX_USERNAME=") and not user:
                        user = line.split("=", 1)[1].strip()
                    elif line.startswith("MINIFLUX_PASSWORD=") and not pw:
                        pw = line.split("=", 1)[1].strip()
    if not user or not pw:
        print(
            "✗ MINIFLUX_USERNAME / MINIFLUX_PASSWORD not set. "
            "Run scripts/gen_miniflux_creds.sh first.",
            file=sys.stderr,
        )
        sys.exit(1)
    return {"url": url, "user": user, "pw": pw}


def _auth_header(cfg: Dict[str, str]) -> str:
    return "Basic " + base64.b64encode(
        f"{cfg['user']}:{cfg['pw']}".encode()
    ).decode()


def _api(
    cfg: Dict[str, str],
    path: str,
    method: str = "GET",
    body: Optional[Dict[str, Any]] = None,
) -> Any:
    url = f"{cfg['url']}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": _auth_header(cfg),
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:200]
        raise RuntimeError(f"miniflux {method} {path} → {exc.code}: {detail}") from None


def ensure_categories(cfg: Dict[str, str]) -> Dict[str, int]:
    """Return {title: id} for every desired category, creating what's missing."""
    existing = {c["title"]: c["id"] for c in _api(cfg, "/v1/categories")}
    out: Dict[str, int] = {}
    for title in DESIRED_CATEGORIES:
        if title in existing:
            out[title] = existing[title]
            continue
        res = _api(cfg, "/v1/categories", "POST", {"title": title})
        out[title] = res["id"]
        print(f"  + category {title!r} (id={res['id']})")
    return out


def ensure_feeds(cfg: Dict[str, str], cat_ids: Dict[str, int]) -> None:
    existing_feeds = _api(cfg, "/v1/feeds")  # list of feed dicts
    # index by normalised feed_url
    by_url: Dict[str, Dict[str, Any]] = {
        f["feed_url"].rstrip("/"): f for f in existing_feeds
    }

    added = 0
    moved = 0
    for cat_title, name, url in DESIRED_FEEDS:
        key = url.rstrip("/")
        cat_id = cat_ids[cat_title]
        if key in by_url:
            f = by_url[key]
            current_cat = (f.get("category") or {}).get("id")
            if current_cat != cat_id:
                # re-categorise
                _api(
                    cfg,
                    f"/v1/feeds/{f['id']}",
                    "PUT",
                    {"category_id": cat_id},
                )
                print(f"  ↻ re-categorised {f.get('title') or name!r} → {cat_title}")
                moved += 1
            continue
        # Add the feed under the target category
        try:
            res = _api(
                cfg,
                "/v1/feeds",
                "POST",
                {"feed_url": url, "category_id": cat_id},
            )
            print(f"  + feed [{cat_title:9}] {name}  (feed_id={res['feed_id']})")
            added += 1
        except RuntimeError as exc:
            # Non-fatal — keep going. Some feeds 502/404 transiently.
            print(f"  ✗ could not add {name}: {exc}", file=sys.stderr)

    print(f"seed complete — added {added}, re-categorised {moved}")


def main() -> None:
    cfg = _config()
    print(f"Miniflux @ {cfg['url']}  user={cfg['user']}")
    cat_ids = ensure_categories(cfg)
    ensure_feeds(cfg, cat_ids)


if __name__ == "__main__":
    main()
