"""China policy RSS scanner.

Pulls headlines from authoritative sources, matches against curated
sector-→theme-→ticker maps, emits signal_events with
``theme=china_<sector>`` so confluences fire when ≥2 sources hit the
same policy theme within 72h.

Sources (free RSS, no auth):
  - Caixin Global  (英文版财新, 最深度的市场报道)
  - Xinhua / 新华社 (官方叙事)
  - China Daily Business (政府对外口径, 商业新闻)
  - SCMP China (港媒, 大湾区视角)

Severity:
  - high: keyword in 政策 / regulation / fund-launch / approval / sanctions
  - med:  generic mention

NOT done (LLM-style sentiment): too noisy.  We do simple keyword AND
match against curated theme dictionaries.
"""
from __future__ import annotations

import gzip
import logging
import re
import time
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)


# ── RSS source registry ───────────────────────────────────────────


SOURCES = [
    # ✅ SCMP works — best free China-business RSS we've found.
    {
        "name":  "SCMP China",
        "url":   "https://www.scmp.com/rss/4/feed",
        "lang":  "en",
    },
    {
        "name":  "SCMP Business",
        "url":   "https://www.scmp.com/rss/2/feed",
        "lang":  "en",
    },
    {
        "name":  "Reuters Business",
        "url":   "https://feeds.reuters.com/reuters/businessNews",
        "lang":  "en",
    },
    {
        "name":  "Yahoo Finance Top Stories",
        "url":   "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC&region=US&lang=en-US",
        "lang":  "en",
    },
    # ❌ TODO: these returned 404 — URLs need verification or sites
    # have changed. Caixin Global may have moved RSS behind paywall;
    # Xinhua / China Daily may have restructured feeds.  Drop until
    # we confirm working URLs (or use lattice's news_hub crawler).
    # {"name": "Caixin Global", "url": "https://www.caixinglobal.com/feed/"},
    # {"name": "Xinhua World",  "url": "https://english.news.cn/world/rss/world.xml"},
    # {"name": "China Daily",   "url": "https://usa.chinadaily.com.cn/rss/business_rss.xml"},
]


# ── theme → keywords + tickers map ────────────────────────────────


THEMES: Dict[str, Dict[str, Any]] = {
    "china_ai_chip": {
        "label":   "China AI / 芯片自主",
        "keywords": [
            "Big Fund", "国家集成电路", "SMIC", "Hua Hong", "华虹",
            "中芯", "Cambricon", "AMEC", "NAURA",
            "AI chip", "Ascend", "domestic chip", "国产芯片",
            "semiconductor self-sufficiency",
        ],
        "tickers": ["BABA", "BIDU", "TCEHY"],
    },
    "china_ai_capex": {
        "label":   "China AI / Cloud capex",
        "keywords": [
            "Alibaba Cloud", "Qwen", "DeepSeek", "Tencent Hunyuan",
            "Baidu Ernie", "ByteDance", "Moonshot", "Zhipu",
            "AI investment", "AI infrastructure", "AI capex",
            "datacenter China",
        ],
        "tickers": ["BABA", "BIDU", "TCEHY"],
    },
    "china_ev": {
        "label":   "China EV / battery",
        "keywords": [
            "BYD", "NIO", "XPeng", "Li Auto", "电动汽车",
            "新能源汽车", "NEV", "trade-in subsidy", "battery",
            "CATL", "solid-state battery",
        ],
        "tickers": ["NIO", "LI", "XPEV"],
    },
    "china_biotech": {
        "label":   "China innovative drugs / biotech",
        "keywords": [
            "Hengrui", "Innovent", "BeiGene", "BeOne",
            "Wuxi", "innovative drug", "license-out", "NMPA",
            "PD-1", "biosimilar", "BIOSECURE",
        ],
        "tickers": ["BGNE"],
    },
    "china_real_estate": {
        "label":   "China real estate stabilization",
        "keywords": [
            "Vanke", "Country Garden", "Sunac", "白名单", "white list",
            "property stabilization", "mortgage rate", "pre-sale",
            "developer bailout", "real estate fund",
        ],
        "tickers": [],   # mostly HK / A-share, not US-listed
    },
    "china_consumer": {
        "label":   "China consumer / trade-in stimulus",
        "keywords": [
            "trade-in subsidy", "appliance subsidy", "consumption coupon",
            "domestic demand", "扩大内需", "Midea", "Haier",
            "Pinduoduo", "JD.com", "Alibaba",
        ],
        "tickers": ["BABA", "PDD", "JD", "MNST"],
    },
    "china_robotics": {
        "label":   "Humanoid robotics / embodied AI",
        "keywords": [
            "humanoid robot", "embodied intelligence", "具身智能",
            "Unitree", "Estun", "Inovance", "robotics standard",
            "MIIT robot", "low-altitude economy",
        ],
        "tickers": ["XPEV"],
    },
    "china_macro": {
        "label":   "PBOC / fiscal / yuan",
        "keywords": [
            "PBOC", "央行", "RRR cut", "rate cut", "loose policy",
            "ultra-long bond", "special treasury", "fiscal stimulus",
            "RMB", "yuan stability", "deflation",
        ],
        "tickers": ["MCHI", "FXI", "KWEB"],
    },
    "us_china_trade": {
        "label":   "US-China sanctions / tariffs",
        "keywords": [
            "BIS export control", "entity list", "tariff",
            "Section 1260H", "OFAC", "PCAOB", "delisting",
            "TikTok divestiture", "outbound investment",
            "rare earth", "稀土",
        ],
        "tickers": ["BABA", "BIDU", "MCHI", "FXI", "KWEB", "NVDA", "AMD", "ASML", "TSM"],
    },
    "fed_macro": {
        "label":   "Fed / FOMC",
        "keywords": [
            "FOMC", "Fed rate", "Powell", "rate cut", "rate hike",
            "monetary policy", "inflation", "PCE", "CPI",
        ],
        "tickers": ["SPY", "QQQ", "TLT"],
    },
}


HIGH_SEVERITY_KW = [
    "approve", "approved", "ban", "banned", "sanction", "sanctioned",
    "launch", "launched", "raise", "raised", "cut", "cuts",
    "delist", "delisted", "policy", "regulation", "subsidy",
    "fund", "billion", "trillion",
]


# ── RSS fetch ────────────────────────────────────────────────────


def _http_get(url: str, *, timeout: int = 15) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent":      "NeoMind Fin Research neomind@example.com",
        "Accept-Encoding": "gzip, deflate",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        if resp.headers.get('Content-Encoding') == 'gzip':
            raw = gzip.decompress(raw)
        return raw


def _parse_rss(xml_bytes: bytes) -> List[Dict[str, Any]]:
    """Lightweight RSS / Atom parser — returns [{title, link, desc, pub}]."""
    items: List[Dict[str, Any]] = []
    try:
        root = ET.fromstring(xml_bytes)
    except Exception as exc:
        logger.debug("RSS parse failed: %s", exc)
        return items

    ns_re = re.compile(r'\{[^}]+\}')

    # RSS 2.0: rss/channel/item
    for item in root.iter():
        tag = ns_re.sub('', item.tag)
        if tag != 'item' and tag != 'entry':
            continue
        rec: Dict[str, Any] = {}
        for child in item:
            ctag = ns_re.sub('', child.tag)
            text = (child.text or '').strip() if child.text else ''
            if ctag == 'title':
                rec['title'] = text
            elif ctag == 'link':
                # Atom: link is href attribute; RSS: link is element text
                href = child.get('href')
                rec['link'] = href or text
            elif ctag == 'description' or ctag == 'summary':
                rec['desc'] = text
            elif ctag in ('pubDate', 'published', 'updated'):
                rec['pub'] = text
        if rec.get('title') and rec.get('link'):
            items.append(rec)
    return items


# ── theme matching ───────────────────────────────────────────────


def _match_themes(text: str) -> List[str]:
    """Return list of theme keys whose keywords appear in text."""
    if not text:
        return []
    lower = text.lower()
    matches: List[str] = []
    for theme_key, theme in THEMES.items():
        for kw in theme["keywords"]:
            kw_lower = kw.lower()
            # Whole-word match for ASCII kw; substring for CJK
            if any(ord(c) > 127 for c in kw_lower):
                if kw_lower in lower:
                    matches.append(theme_key)
                    break
            else:
                if re.search(rf"\b{re.escape(kw_lower)}\b", lower):
                    matches.append(theme_key)
                    break
    return matches


def _classify_severity(text: str) -> str:
    if not text:
        return "med"
    lower = text.lower()
    for kw in HIGH_SEVERITY_KW:
        if re.search(rf"\b{re.escape(kw)}\b", lower):
            return "high"
    return "med"


def _already_emitted_url(url: str) -> bool:
    """Idempotency by URL (across all themes)."""
    from agent.finance.persistence import connect
    if not url:
        return False
    with connect() as conn:
        cur = conn.execute(
            "SELECT event_id FROM signal_events "
            "WHERE scanner_name = 'policy' AND source_url = ? LIMIT 1",
            (url,),
        )
        return cur.fetchone() is not None


# ── public scan ──────────────────────────────────────────────────


def run_policy_scan() -> Dict[str, Any]:
    from agent.finance.regime.signals import emit_event

    t0 = time.monotonic()
    n_emitted = 0
    per_source: List[Dict[str, Any]] = []

    for src in SOURCES:
        s_emitted = 0
        s_items = 0
        s_matched = 0
        try:
            raw = _http_get(src["url"])
            items = _parse_rss(raw)
            s_items = len(items)
        except Exception as exc:
            per_source.append({"source": src["name"], "error": str(exc)})
            continue

        for it in items:
            text = (it.get("title") or "") + " " + (it.get("desc") or "")
            themes = _match_themes(text)
            if not themes:
                continue
            s_matched += 1

            url = it.get("link", "")
            if _already_emitted_url(url):
                continue

            # Emit one signal per matched theme (so confluence groups by theme)
            sev = _classify_severity(text)
            for theme_key in themes:
                theme = THEMES[theme_key]
                title = f"📰 [{src['name']}] {it.get('title', '')[:200]}"
                emit_event(
                    "policy",
                    signal_type=f"policy_{theme_key}",
                    severity=sev,
                    theme=theme_key,
                    title=title,
                    body={
                        "source":      src["name"],
                        "source_lang": src["lang"],
                        "theme_label": theme["label"],
                        "tickers":     theme["tickers"],
                        "headline":    it.get("title"),
                    },
                    source_url=url,
                    source_timestamp=it.get("pub"),
                )
                s_emitted += 1
                n_emitted += 1

        per_source.append({
            "source":   src["name"],
            "n_items":  s_items,
            "n_matched": s_matched,
            "n_emitted": s_emitted,
        })

    return {
        "scanner":   "policy",
        "n_sources": len(SOURCES),
        "n_emitted": n_emitted,
        "took_ms":   int((time.monotonic() - t0) * 1000),
        "per_source": per_source,
    }
