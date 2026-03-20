# agent/finance/rss_feeds.py
"""
RSS Feed Manager — always-on, zero-cost news backbone.

Provides EN + ZH financial news from 20+ sources.
Uses feedparser for parsing. Chinese feeds use RSSHub as bridge.
"""

import os
import time
import asyncio
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False
    feedparser = None


# ── Feed Registry ─────────────────────────────────────────────────────

# RSSHub base URL — self-hosted recommended, public instance as fallback
RSSHUB_URL = os.getenv("RSSHUB_URL", "https://rsshub.app")

RSS_FEEDS: Dict[str, Dict[str, str]] = {
    "en": {
        # Wire services & major press
        "reuters_business": "https://feeds.reuters.com/reuters/businessNews",
        "reuters_markets": "https://feeds.reuters.com/reuters/marketsNews",

        # Financial news
        "cnbc_finance": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664",
        "wsj_markets": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
        "marketwatch": "https://feeds.marketwatch.com/marketwatch/topstories",
        "yahoo_finance": "https://finance.yahoo.com/news/rssindex",
        "investing_com": "https://www.investing.com/rss/news.rss",

        # Crypto
        "coindesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "cointelegraph": "https://cointelegraph.com/rss",
    },
    "zh": {
        # Chinese financial press (via RSSHub)
        "caixin_finance": f"{RSSHUB_URL}/caixin/finance",            # 财新财经
        "yicai": f"{RSSHUB_URL}/yicai/brief",                       # 第一财经
        "cls_telegraph": f"{RSSHUB_URL}/cls/telegraph",              # 财联社电报
        "eastmoney_news": f"{RSSHUB_URL}/eastmoney/report",         # 东方财富
        "sina_finance": f"{RSSHUB_URL}/sina/finance",                # 新浪财经
        "wallstreetcn": f"{RSSHUB_URL}/wallstreetcn/news/global",   # 华尔街见闻
        "gelonghui": f"{RSSHUB_URL}/gelonghui/live",                # 格隆汇
        "jinse": f"{RSSHUB_URL}/jinse/lives",                       # 金色财经 (crypto)
    },
}


@dataclass
class FeedItem:
    """A single RSS feed item."""
    title: str
    url: str
    source: str
    language: str
    published: Optional[datetime] = None
    summary: str = ""
    categories: List[str] = field(default_factory=list)
    fetched_at: float = 0.0

    def age_hours(self) -> float:
        """Hours since publication."""
        if not self.published:
            return float('inf')
        delta = datetime.now(timezone.utc) - self.published
        return delta.total_seconds() / 3600


@dataclass
class FeedHealth:
    """Health status of a feed."""
    name: str
    url: str
    language: str
    alive: bool = False
    last_check: float = 0.0
    consecutive_failures: int = 0
    last_error: str = ""
    item_count: int = 0
    disabled_until: float = 0.0  # timestamp when re-enable

    @property
    def is_disabled(self) -> bool:
        return self.disabled_until > time.time()

    @property
    def status_icon(self) -> str:
        if self.is_disabled:
            return "❌"
        if not self.alive:
            return "⚠️"
        return "✅"


class RSSFeedManager:
    """
    Manages all RSS feeds with health monitoring and caching.

    Features:
    - Parallel feed fetching with ThreadPoolExecutor
    - Feed health monitoring (auto-disable after 3 consecutive failures)
    - In-memory cache with configurable TTL
    - Language-aware filtering
    """

    CACHE_TTL = 900            # 15 minutes
    FETCH_TIMEOUT = 10         # seconds per feed
    MAX_FAILURES = 3           # disable feed after N consecutive failures
    DISABLE_DURATION = 3600    # re-enable after 1 hour
    MAX_WORKERS = 8            # parallel fetch threads

    def __init__(self, feeds: Optional[Dict] = None):
        if not HAS_FEEDPARSER:
            raise ImportError(
                "feedparser is required for RSS feeds. "
                "Install with: pip install feedparser"
            )
        self.feeds = feeds or RSS_FEEDS
        self.cache: Dict[str, Tuple[List[FeedItem], float]] = {}
        self.health: Dict[str, FeedHealth] = {}
        self._init_health()
        self._executor = ThreadPoolExecutor(max_workers=self.MAX_WORKERS)

    def _init_health(self):
        """Initialize health records for all feeds."""
        for lang, feeds in self.feeds.items():
            for name, url in feeds.items():
                self.health[name] = FeedHealth(
                    name=name, url=url, language=lang
                )

    def fetch_feed(self, name: str, url: str, language: str) -> List[FeedItem]:
        """
        Fetch a single RSS feed synchronously.
        Called from thread pool.
        """
        health = self.health.get(name)
        if health and health.is_disabled:
            return []

        try:
            feed = feedparser.parse(url)

            if feed.bozo and not feed.entries:
                raise ValueError(f"Feed parse error: {feed.bozo_exception}")

            items = []
            for entry in feed.entries[:20]:  # cap at 20 items per feed
                published = None
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    try:
                        published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                    except (TypeError, ValueError):
                        pass

                items.append(FeedItem(
                    title=entry.get('title', '').strip(),
                    url=entry.get('link', '').strip(),
                    source=name,
                    language=language,
                    published=published,
                    summary=entry.get('summary', '')[:500],
                    categories=[t.get('term', '') for t in entry.get('tags', [])],
                    fetched_at=time.time(),
                ))

            # Update health
            if health:
                health.alive = True
                health.consecutive_failures = 0
                health.last_check = time.time()
                health.item_count = len(items)

            return items

        except Exception as e:
            if health:
                health.alive = False
                health.consecutive_failures += 1
                health.last_error = str(e)[:200]
                health.last_check = time.time()
                if health.consecutive_failures >= self.MAX_FAILURES:
                    health.disabled_until = time.time() + self.DISABLE_DURATION

            return []

    async def fetch_all(self, languages: Optional[List[str]] = None) -> List[FeedItem]:
        """
        Fetch all feeds in parallel.

        Args:
            languages: Filter by language ["en", "zh"]. None = all.

        Returns:
            Deduplicated, sorted list of FeedItems (newest first).
        """
        languages = languages or ["en", "zh"]
        loop = asyncio.get_event_loop()
        tasks = []

        for lang in languages:
            if lang not in self.feeds:
                continue
            for name, url in self.feeds[lang].items():
                # Check cache first
                cached = self._get_cached(name)
                if cached is not None:
                    tasks.append(asyncio.coroutine(lambda c=cached: c)())
                    continue
                tasks.append(
                    loop.run_in_executor(
                        self._executor,
                        self.fetch_feed, name, url, lang
                    )
                )

        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_items = []
        for result in results:
            if isinstance(result, Exception):
                continue
            if isinstance(result, list):
                all_items.extend(result)

        # Cache results by source
        source_items: Dict[str, List[FeedItem]] = {}
        for item in all_items:
            source_items.setdefault(item.source, []).append(item)
        for source, items in source_items.items():
            self.cache[source] = (items, time.time())

        # Deduplicate by URL
        seen_urls = set()
        unique_items = []
        for item in all_items:
            if item.url and item.url not in seen_urls:
                seen_urls.add(item.url)
                unique_items.append(item)

        # Sort by publication date (newest first)
        unique_items.sort(key=lambda x: x.published or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

        return unique_items

    def search(self, query: str, languages: Optional[List[str]] = None, max_results: int = 20) -> List[FeedItem]:
        """
        Search cached feed items by keyword (synchronous).
        For async, use fetch_all() first then filter.
        """
        query_lower = query.lower()
        results = []

        for source, (items, cached_at) in self.cache.items():
            if time.time() - cached_at > self.CACHE_TTL:
                continue
            for item in items:
                if languages and item.language not in languages:
                    continue
                if (query_lower in item.title.lower() or
                        query_lower in item.summary.lower()):
                    results.append(item)

        # Sort by relevance (title match first, then recency)
        results.sort(key=lambda x: (
            query_lower in x.title.lower(),
            x.published or datetime.min.replace(tzinfo=timezone.utc),
        ), reverse=True)

        return results[:max_results]

    def _get_cached(self, source_name: str) -> Optional[List[FeedItem]]:
        """Get cached results if not expired."""
        if source_name in self.cache:
            items, cached_at = self.cache[source_name]
            if time.time() - cached_at < self.CACHE_TTL:
                return items
        return None

    def get_health_report(self) -> str:
        """Format a human-readable health report of all feeds."""
        lines = ["RSS Feed Health", "=" * 60]

        for lang in ["en", "zh"]:
            lines.append(f"\n  {'English' if lang == 'en' else 'Chinese (中文)'} Sources:")
            for name, health in self.health.items():
                if health.language != lang:
                    continue
                status = health.status_icon
                items = f"{health.item_count} items" if health.alive else health.last_error[:40]
                lines.append(f"    {status} {name:<25s} {items}")

        alive = sum(1 for h in self.health.values() if h.alive)
        total = len(self.health)
        lines.append(f"\n  Total: {alive}/{total} feeds active")
        return "\n".join(lines)
