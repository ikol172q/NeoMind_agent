# agent/search/sources.py
"""
Search source wrappers — each source implements a common async interface.

Sources are organized into tiers:
  Tier 1 (Free Unlimited): DuckDuckGo, Google News RSS
  Tier 2 (Free with Limits): Brave, Serper, Tavily, Jina
  Tier 3 (Self-Hosted):     SearXNG

Every source must implement:
  async def search(query: str, max_results: int) -> List[SearchItem]
"""

import os
import re
import time
import asyncio
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from urllib.parse import urlparse, quote_plus

import requests

from agent.constants.models import DEFAULT_MODEL

# ── Optional imports (graceful degradation) ──────────────────────────

try:
    from duckduckgo_search import DDGS
    HAS_DDG = True
except ImportError:
    HAS_DDG = False
    DDGS = None

try:
    import trafilatura
    HAS_TRAFILATURA = True
except ImportError:
    HAS_TRAFILATURA = False

try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False
    feedparser = None

try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False
    aiohttp = None


# ── Data Classes ─────────────────────────────────────────────────────

@dataclass
class SearchItem:
    """A single search result from any source."""
    title: str
    url: str
    snippet: str = ""
    full_text: str = ""
    source: str = ""           # which search engine found this
    original_source: str = ""  # which outlet published it
    language: str = "en"
    published: Optional[datetime] = None
    trust_score: float = 0.5
    rrf_score: float = 0.0
    relevance_score: float = 0.0
    recency_boost: float = 0.0
    rerank_score: float = 0.0  # NEW: FlashRank / semantic reranker score
    extraction_quality: str = ""

    @property
    def domain(self) -> str:
        try:
            return urlparse(self.url).netloc.replace("www.", "")
        except Exception:
            return ""

    @property
    def best_content(self) -> str:
        """Return the richest content available."""
        return self.full_text or self.snippet or self.title


@dataclass
class SearchResult:
    """Aggregated search results from all sources."""
    items: List[SearchItem] = field(default_factory=list)
    sources_used: List[str] = field(default_factory=list)
    sources_failed: List[str] = field(default_factory=list)
    expanded_queries: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    query: str = ""
    cached: bool = False
    error: Optional[str] = None
    extraction_count: int = 0
    reranked: bool = False  # NEW: whether FlashRank was applied

    def format_for_llm(self, max_items: int = 10, include_full_text: bool = True) -> str:
        """Format results as LLM-friendly text with citations."""
        if self.error:
            return f"Search error: {self.error}"
        if not self.items:
            return f"No results found for '{self.query}'."

        lines = [f"Search results for '{self.query}' ({len(self.items)} results from {', '.join(self.sources_used)}):"]
        lines.append("")

        for i, item in enumerate(self.items[:max_items], 1):
            tag = f"[{item.source}] " if item.source else ""
            lines.append(f"{i}. {tag}**{item.title}**")
            lines.append(f"   Source: {item.original_source or item.domain} | {item.url}")
            if item.published:
                lines.append(f"   Published: {item.published.strftime('%Y-%m-%d %H:%M UTC')}")

            content = item.best_content
            if include_full_text and item.full_text:
                # Truncate full text for LLM context
                content = item.full_text[:1500]
            elif item.snippet:
                content = item.snippet[:500]

            if content:
                lines.append(f"   {content}")
            lines.append("")

        meta = []
        if self.expanded_queries and len(self.expanded_queries) > 1:
            meta.append(f"Query variants: {', '.join(self.expanded_queries)}")
        if self.reranked:
            meta.append("Results reranked by semantic relevance")
        if self.extraction_count > 0:
            meta.append(f"Full text extracted for {self.extraction_count} articles")
        if meta:
            lines.append(f"[{' | '.join(meta)}]")

        return "\n".join(lines)


# ── Rate Limiter ─────────────────────────────────────────────────────

class TokenBucketLimiter:
    """Rate limiter to prevent API abuse."""

    def __init__(self, rate: float = 1.0, per: float = 1.5):
        self.rate = rate
        self.per = per
        self.tokens = rate
        self.last_refill = time.time()

    async def acquire(self):
        while True:
            now = time.time()
            elapsed = now - self.last_refill
            self.tokens = min(self.rate, self.tokens + elapsed * (self.rate / self.per))
            self.last_refill = now
            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return
            wait_time = (1.0 - self.tokens) * (self.per / self.rate)
            await asyncio.sleep(wait_time)


# ── Content Extractor ────────────────────────────────────────────────

class ContentExtractor:
    """Extracts full article text from URLs using trafilatura + fallbacks."""

    def __init__(self, max_workers: int = 4, timeout: int = 10):
        self.available = HAS_TRAFILATURA
        self.timeout = timeout
        self.max_workers = max_workers
        self._limiter = TokenBucketLimiter(rate=2.0, per=1.0)

    async def extract_batch(self, items: List[SearchItem], top_n: int = 5) -> int:
        """Extract full text for the top N search results. Returns success count."""
        if not self.available:
            return 0
        count = 0
        tasks = []
        for item in items[:top_n]:
            if item.full_text:
                continue
            tasks.append(self._extract_one(item))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, int):
                count += r
        return count

    async def _extract_one(self, item: SearchItem) -> int:
        await self._limiter.acquire()
        try:
            loop = asyncio.get_event_loop()
            text = await loop.run_in_executor(None, self._sync_extract, item.url)
            if text and len(text) > 100:
                item.full_text = text[:5000]
                item.extraction_quality = "full"
                return 1
            else:
                item.extraction_quality = "snippet"
                return 0
        except Exception:
            item.extraction_quality = "snippet"
            return 0

    def _sync_extract(self, url: str) -> Optional[str]:
        try:
            downloaded = trafilatura.fetch_url(url)
            if not downloaded:
                return None
            return trafilatura.extract(
                downloaded,
                include_links=False,
                include_images=False,
                include_tables=True,
                output_format='txt',
                favor_recall=True,
            )
        except Exception:
            return None


# ══════════════════════════════════════════════════════════════════════
# TIER 1 — Free, Unlimited
# ══════════════════════════════════════════════════════════════════════

class DuckDuckGoSource:
    """DuckDuckGo search — free, no API key, but rate-limited."""

    def __init__(self, region: str = "en-us"):
        self.region = region
        self.available = HAS_DDG
        self.limiter = TokenBucketLimiter(rate=1.0, per=2.0)
        self.language = "zh" if "cn" in region or "zh" in region else "en"

    async def search(self, query: str, max_results: int = 10) -> List[SearchItem]:
        if not self.available:
            return []
        await self.limiter.acquire()
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._sync_search, query, max_results)
        except Exception:
            return []

    def _sync_search(self, query: str, max_results: int) -> List[SearchItem]:
        items = []
        try:
            with DDGS() as ddgs:
                for r in ddgs.text(query, region=self.region, max_results=max_results):
                    items.append(SearchItem(
                        title=r.get("title", ""),
                        url=r.get("href", ""),
                        snippet=r.get("body", ""),
                        source=f"ddg_{self.language}",
                        language=self.language,
                    ))
        except Exception:
            pass
        return items


class GoogleNewsRSSSource:
    """Google News RSS — free, no API key, no rate limit."""

    _BASE = "https://news.google.com/rss/search"

    def __init__(self, language: str = "en"):
        self.language = language
        self.available = HAS_FEEDPARSER
        if language == "zh":
            self.params = {"hl": "zh-CN", "gl": "CN", "ceid": "CN:zh-Hans"}
        else:
            self.params = {"hl": "en-US", "gl": "US", "ceid": "US:en"}

    async def search(self, query: str, max_results: int = 10) -> List[SearchItem]:
        if not self.available:
            return []
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._sync_search, query, max_results)
        except Exception:
            return []

    def _sync_search(self, query: str, max_results: int) -> List[SearchItem]:
        items = []
        try:
            params = {**self.params, "q": query}
            url = f"{self._BASE}?{'&'.join(f'{k}={quote_plus(str(v))}' for k, v in params.items())}"
            feed = feedparser.parse(url)

            for entry in feed.entries[:max_results]:
                published = None
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    try:
                        published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                    except (TypeError, ValueError):
                        pass

                title = re.sub(r'<[^>]+>', '', entry.get('title', '')).strip()
                original_source = ""
                if " - " in title:
                    parts = title.rsplit(" - ", 1)
                    original_source = parts[-1].strip()

                items.append(SearchItem(
                    title=title,
                    url=entry.get('link', ''),
                    snippet=re.sub(r'<[^>]+>', '', entry.get('summary', ''))[:300],
                    source=f"gnews_{self.language}",
                    original_source=original_source,
                    language=self.language,
                    published=published,
                ))
        except Exception:
            pass
        return items


# ══════════════════════════════════════════════════════════════════════
# TIER 2 — Free with Limits (API key required)
# ══════════════════════════════════════════════════════════════════════

class BraveSearchSource:
    """Brave Search API — independent index (30B+ pages), LLM-optimized.

    Free tier: ~$5 credit on signup ≈ 1000 queries/month.
    Returns clean snippets and optional full-text via summarizer API.

    Set BRAVE_API_KEY in environment.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("BRAVE_API_KEY")
        self.available = bool(self.api_key)
        self.base_url = "https://api.search.brave.com/res/v1/web/search"

    async def search(self, query: str, max_results: int = 10) -> List[SearchItem]:
        if not self.available:
            return []
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._sync_search, query, max_results)
        except Exception:
            return []

    def _sync_search(self, query: str, max_results: int) -> List[SearchItem]:
        items = []
        try:
            resp = requests.get(
                self.base_url,
                params={
                    "q": query,
                    "count": min(max_results, 20),
                    "text_decorations": False,
                    "search_lang": "en",
                },
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "X-Subscription-Token": self.api_key,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()

                # Web results
                for r in data.get("web", {}).get("results", []):
                    published = None
                    if r.get("page_age"):
                        try:
                            published = datetime.fromisoformat(r["page_age"].replace("Z", "+00:00"))
                        except (ValueError, TypeError):
                            pass

                    items.append(SearchItem(
                        title=r.get("title", ""),
                        url=r.get("url", ""),
                        snippet=r.get("description", ""),
                        source="brave",
                        original_source=r.get("meta_url", {}).get("hostname", ""),
                        published=published,
                        language=r.get("language", "en"),
                    ))

                # News results (if available in response)
                for r in data.get("news", {}).get("results", []):
                    published = None
                    if r.get("age"):
                        # Brave news age is relative, we skip exact parsing
                        pass
                    items.append(SearchItem(
                        title=r.get("title", ""),
                        url=r.get("url", ""),
                        snippet=r.get("description", ""),
                        source="brave_news",
                        original_source=r.get("meta_url", {}).get("hostname", ""),
                        published=published,
                    ))
        except Exception:
            pass
        return items


class SerperSource:
    """Serper.dev — fastest, cheapest Google SERP API (<1s, $0.30/1k).

    Free tier: 2500 queries on signup.
    Set SERPER_API_KEY in environment.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("SERPER_API_KEY")
        self.available = bool(self.api_key)
        self.base_url = "https://google.serper.dev/search"

    async def search(self, query: str, max_results: int = 10) -> List[SearchItem]:
        if not self.available:
            return []
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._sync_search, query, max_results)
        except Exception:
            return []

    def _sync_search(self, query: str, max_results: int) -> List[SearchItem]:
        items = []
        try:
            resp = requests.post(
                self.base_url,
                json={"q": query, "num": max_results},
                headers={
                    "X-API-KEY": self.api_key,
                    "Content-Type": "application/json",
                },
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()

                # Organic results
                for r in data.get("organic", []):
                    items.append(SearchItem(
                        title=r.get("title", ""),
                        url=r.get("link", ""),
                        snippet=r.get("snippet", ""),
                        source="serper",
                    ))

                # Knowledge graph
                kg = data.get("knowledgeGraph", {})
                if kg.get("title"):
                    items.insert(0, SearchItem(
                        title=kg.get("title", ""),
                        url=kg.get("website", ""),
                        snippet=kg.get("description", ""),
                        source="serper_kg",
                        trust_score=0.9,
                    ))

                # News box results (if present)
                for r in data.get("news", []):
                    items.append(SearchItem(
                        title=r.get("title", ""),
                        url=r.get("link", ""),
                        snippet=r.get("snippet", ""),
                        source="serper_news",
                        original_source=r.get("source", ""),
                    ))
        except Exception:
            pass
        return items


class TavilySource:
    """Tavily — AI-optimized search (93.3% SimpleQA accuracy).

    Free tier: 1000 queries/month.
    Set TAVILY_API_KEY in environment.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("TAVILY_API_KEY")
        self.available = bool(self.api_key)
        self.base_url = "https://api.tavily.com/search"

    async def search(self, query: str, max_results: int = 5) -> List[SearchItem]:
        if not self.available:
            return []
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._sync_search, query, max_results)
        except Exception:
            return []

    def _sync_search(self, query: str, max_results: int) -> List[SearchItem]:
        items = []
        try:
            resp = requests.post(
                self.base_url,
                json={
                    "api_key": self.api_key,
                    "query": query,
                    "max_results": max_results,
                    "search_depth": "advanced",
                    "include_answer": False,
                    "include_raw_content": False,
                },
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                for r in data.get("results", []):
                    # Tavily already provides extracted content
                    content = r.get("content", "")
                    items.append(SearchItem(
                        title=r.get("title", ""),
                        url=r.get("url", ""),
                        snippet=content[:500],
                        full_text=content if len(content) > 500 else "",
                        source="tavily",
                        extraction_quality="full" if len(content) > 500 else "snippet",
                        relevance_score=r.get("score", 0.0),
                    ))
        except Exception:
            pass
        return items


class JinaSearchSource:
    """Jina AI Search — semantic search + content extraction in one call.

    s.jina.ai: search endpoint (returns LLM-friendly results)
    r.jina.ai: reader endpoint (extracts content from any URL)

    Free tier: 1M tokens/month.
    Set JINA_API_KEY in environment (optional for basic use).
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("JINA_API_KEY")
        # Jina search works without API key but with limits
        self.available = True
        self.search_url = "https://s.jina.ai/"

    async def search(self, query: str, max_results: int = 5) -> List[SearchItem]:
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._sync_search, query, max_results)
        except Exception:
            return []

    def _sync_search(self, query: str, max_results: int) -> List[SearchItem]:
        items = []
        try:
            headers = {
                "Accept": "application/json",
                "X-Return-Format": "text",
            }
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            resp = requests.get(
                f"{self.search_url}{quote_plus(query)}",
                headers=headers,
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                for r in data.get("data", [])[:max_results]:
                    content = r.get("content", "")
                    items.append(SearchItem(
                        title=r.get("title", ""),
                        url=r.get("url", ""),
                        snippet=content[:500] if content else r.get("description", ""),
                        full_text=content if len(content) > 500 else "",
                        source="jina",
                        extraction_quality="full" if len(content) > 500 else "snippet",
                    ))
        except Exception:
            pass
        return items


class ExaSearchSource:
    """Exa.ai — neural/semantic search engine (PAID — placeholder).

    Exa uses embeddings-based "next-link prediction" for semantic search.
    Modes: Auto, Fast, Keyword, Neural, Deep.
    Exa Deep agentically searches until it finds highest-quality info.

    Free tier: 1000 credits on signup.
    Set EXA_API_KEY in environment.

    Install: pip install exa_py
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("EXA_API_KEY")
        self._client = None
        self.available = False
        if self.api_key:
            try:
                from exa_py import Exa
                self._client = Exa(self.api_key)
                self.available = True
            except ImportError:
                pass

    async def search(self, query: str, max_results: int = 5) -> List[SearchItem]:
        if not self.available or not self._client:
            return []
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._sync_search, query, max_results)
        except Exception:
            return []

    def _sync_search(self, query: str, max_results: int) -> List[SearchItem]:
        items = []
        try:
            result = self._client.search_and_contents(
                query,
                num_results=max_results,
                text={"max_characters": 1500},
                type="auto",
            )
            for r in result.results:
                text = getattr(r, 'text', '') or ''
                items.append(SearchItem(
                    title=getattr(r, 'title', '') or '',
                    url=getattr(r, 'url', '') or '',
                    snippet=text[:500],
                    full_text=text if len(text) > 500 else "",
                    source="exa",
                    extraction_quality="full" if len(text) > 500 else "snippet",
                    relevance_score=getattr(r, 'score', 0.0),
                ))
        except Exception:
            pass
        return items


class NewsAPISource:
    """NewsAPI.org — 100 req/day free, excellent for news queries.

    Set NEWSAPI_API_KEY in environment.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("NEWSAPI_API_KEY")
        self.available = bool(self.api_key)
        self.base_url = "https://newsapi.org/v2/everything"

    async def search(self, query: str, max_results: int = 10) -> List[SearchItem]:
        if not self.available:
            return []
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._sync_search, query, max_results)
        except Exception:
            return []

    def _sync_search(self, query: str, max_results: int) -> List[SearchItem]:
        items = []
        try:
            resp = requests.get(self.base_url, params={
                "q": query,
                "pageSize": min(max_results, 20),
                "sortBy": "publishedAt",
                "language": "en",
                "apiKey": self.api_key,
            }, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                for a in data.get("articles", []):
                    published = None
                    if a.get("publishedAt"):
                        try:
                            published = datetime.fromisoformat(
                                a["publishedAt"].replace("Z", "+00:00")
                            )
                        except (ValueError, TypeError):
                            pass
                    items.append(SearchItem(
                        title=a.get("title", ""),
                        url=a.get("url", ""),
                        snippet=a.get("description", "") or (a.get("content", "") or "")[:300],
                        source="newsapi",
                        original_source=a.get("source", {}).get("name", ""),
                        published=published,
                    ))
        except Exception:
            pass
        return items


class Crawl4AIExtractor:
    """Content extractor using Crawl4AI — LLM-optimized web crawler.

    Crawl4AI is an open-source (Apache 2.0) async crawler designed for LLMs.
    It returns clean markdown content, handles JavaScript-rendered pages,
    and supports parallel crawling.

    Install: pip install crawl4ai
    """

    def __init__(self):
        try:
            from crawl4ai import AsyncWebCrawler
            self._crawler_class = AsyncWebCrawler
            self.available = True
        except ImportError:
            self._crawler_class = None
            self.available = False

    async def extract(self, url: str, timeout: int = 15) -> Optional[str]:
        """Extract content from a URL using Crawl4AI.

        Returns clean markdown text or None on failure.
        """
        if not self.available:
            return None
        try:
            async with self._crawler_class() as crawler:
                result = await crawler.arun(url=url)
                if result.success and result.markdown:
                    # Truncate for LLM context
                    return result.markdown[:5000]
            return None
        except Exception:
            return None

    async def extract_batch(self, items: List[SearchItem], top_n: int = 5) -> int:
        """Extract content for top search results. Returns success count."""
        if not self.available:
            return 0

        count = 0
        for item in items[:top_n]:
            if item.full_text:
                continue
            try:
                text = await self.extract(item.url)
                if text and len(text) > 100:
                    item.full_text = text
                    item.extraction_quality = "full_crawl4ai"
                    count += 1
            except Exception:
                continue
        return count


class YouComSource:
    """You.com API — AI search with 93% SimpleQA accuracy (PAID — placeholder).

    You.com provides web search, news search, and AI snippets.
    Supports MCP integration.

    Free tier: limited usage.
    Set YOUCOM_API_KEY in environment.

    Docs: https://documentation.you.com/api-reference/
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("YOUCOM_API_KEY")
        self.available = bool(self.api_key)
        self.base_url = "https://api.ydc-index.io/search"

    async def search(self, query: str, max_results: int = 10) -> List[SearchItem]:
        if not self.available:
            return []
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._sync_search, query, max_results)
        except Exception:
            return []

    def _sync_search(self, query: str, max_results: int) -> List[SearchItem]:
        items = []
        try:
            resp = requests.get(
                self.base_url,
                headers={"X-API-Key": self.api_key},
                params={"query": query, "num_web_results": min(max_results, 20)},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                for hit in data.get("hits", [])[:max_results]:
                    snippets = hit.get("snippets", [])
                    snippet_text = snippets[0] if snippets else hit.get("description", "")
                    items.append(SearchItem(
                        title=hit.get("title", ""),
                        url=hit.get("url", ""),
                        snippet=snippet_text[:500] if snippet_text else "",
                        source="youcom",
                    ))
        except Exception:
            pass
        return items


class PerplexitySonarSource:
    """Perplexity Sonar API — LLM-generated answers with citations (PAID — placeholder).

    Unlike traditional search, Sonar returns an LLM-generated answer with
    inline citations instead of a list of links. Uses OpenAI-compatible API.

    Price: ~$5/1k requests (sonar), ~$1/1k (sonar-small).
    Set PERPLEXITY_API_KEY in environment.

    Docs: https://docs.perplexity.ai/
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "sonar"):
        self.api_key = api_key or os.getenv("PERPLEXITY_API_KEY")
        self._model = model
        self.available = bool(self.api_key)
        self.base_url = "https://api.perplexity.ai/chat/completions"

    async def search(self, query: str, max_results: int = 10) -> List[SearchItem]:
        if not self.available:
            return []
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._sync_search, query, max_results)
        except Exception:
            return []

    def _sync_search(self, query: str, max_results: int) -> List[SearchItem]:
        items = []
        try:
            resp = requests.post(
                self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": "Be precise and concise."},
                        {"role": "user", "content": query},
                    ],
                },
                timeout=30,
            )
            if resp.status_code == 200:
                data = resp.json()
                # Extract the answer content
                answer = ""
                citations = []
                if data.get("choices"):
                    answer = data["choices"][0].get("message", {}).get("content", "")
                citations = data.get("citations", [])

                # Create a synthetic SearchItem from the answer
                if answer:
                    items.append(SearchItem(
                        title=f"Perplexity Sonar: {query[:80]}",
                        url=citations[0] if citations else "https://perplexity.ai",
                        snippet=answer[:500],
                        full_text=answer,
                        source="perplexity",
                        extraction_quality="full",
                    ))

                # Also add citation URLs as individual items
                for i, url in enumerate(citations[:max_results - 1]):
                    items.append(SearchItem(
                        title=f"Citation {i + 1}",
                        url=url,
                        snippet="",
                        source="perplexity",
                    ))
        except Exception:
            pass
        return items


class ScrapeGraphAIExtractor:
    """ScrapeGraphAI — LLM-driven structured web extraction (OPTIONAL).

    Uses natural language prompts to describe what data to extract from pages.
    Ideal for structured data extraction (tables, product info, etc.).

    Open source (MIT license). Requires an LLM backend (OpenAI, local, etc.).
    Install: pip install scrapegraphai

    Usage:
        extractor = ScrapeGraphAIExtractor()
        data = await extractor.extract_structured(url, "Extract all product names and prices")
    """

    def __init__(self):
        try:
            from scrapegraphai.graphs import SmartScraperGraph
            self._graph_class = SmartScraperGraph
            self.available = True
        except ImportError:
            self._graph_class = None
            self.available = False

    async def extract_structured(
        self, url: str, prompt: str, llm_config: Optional[Dict] = None
    ) -> Optional[Dict]:
        """Extract structured data from a URL using natural language prompt.

        Args:
            url: The URL to scrape
            prompt: Natural language description of what to extract
            llm_config: LLM configuration dict (provider, model, api_key, etc.)
                       Defaults to using OPENAI_API_KEY from environment.

        Returns:
            Extracted data as a dict, or None on failure.
        """
        if not self.available or not self._graph_class:
            return None

        if llm_config is None:
            openai_key = os.getenv("OPENAI_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
            if not openai_key:
                return None
            llm_config = {
                "llm": {
                    "api_key": openai_key,
                    "model": DEFAULT_MODEL,
                    "base_url": os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com/v1"),
                },
            }

        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None, self._sync_extract, url, prompt, llm_config
            )
        except Exception:
            return None

    def _sync_extract(self, url: str, prompt: str, llm_config: Dict) -> Optional[Dict]:
        try:
            graph = self._graph_class(
                prompt=prompt,
                source=url,
                config=llm_config,
            )
            result = graph.run()
            return result
        except Exception:
            return None

    async def search(self, query: str, max_results: int = 5) -> List[SearchItem]:
        """Compatibility interface — ScrapeGraphAI is primarily an extractor,
        not a search engine. Returns empty list for search() calls.
        Use extract_structured() for actual extraction."""
        return []


class SearXNGSource:
    """Self-hosted SearXNG meta-search (optional, unlimited).

    Set SEARXNG_URL in environment.
    """

    def __init__(self, url: Optional[str] = None):
        self.base_url = url or os.getenv("SEARXNG_URL")
        self.available = bool(self.base_url)

    async def search(self, query: str, max_results: int = 10) -> List[SearchItem]:
        if not self.available:
            return []
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._sync_search, query, max_results)
        except Exception:
            return []

    def _sync_search(self, query: str, max_results: int) -> List[SearchItem]:
        items = []
        try:
            resp = requests.get(
                f"{self.base_url}/search",
                params={
                    "q": query,
                    "format": "json",
                    "categories": "general,news",
                },
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                for r in data.get("results", [])[:max_results]:
                    items.append(SearchItem(
                        title=r.get("title", ""),
                        url=r.get("url", ""),
                        snippet=r.get("content", ""),
                        source="searxng",
                    ))
        except Exception:
            pass
        return items
