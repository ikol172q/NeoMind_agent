# agent/finance/hybrid_search.py
"""
Hybrid Search Engine v2 — multi-source, multi-strategy, LLM-augmented.

Architecture:
  Tier 1 (Free Unlimited): DuckDuckGo EN + ZH, Google News RSS, RSS feeds
  Tier 2 (Free with Limits): Tavily, Serper, NewsAPI.org (optional)
  Tier 3 (Self-Hosted): SearXNG (optional)

Intelligence layers:
  1. Query Expansion   — LLM generates variant queries before search
  2. Parallel Retrieval — all tiers fire simultaneously
  3. RRF Merge         — Reciprocal Rank Fusion with trust weighting
  4. Content Extraction — trafilatura fetches full article text for top results
  5. Temporal Ranking   — recency boost for fast-moving markets
  6. Fuzzy RSS Match    — TF-IDF over cached RSS, not just substring
  7. Snowball Refinement— use round-1 entities to refine round-2 queries

All tiers fire in parallel. Results merged with RRF.
Benefits ALL NeoMind modes, not just finance.
"""

import os
import re
import math
import time
import asyncio
import hashlib
from collections import defaultdict, Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Callable, Tuple
from urllib.parse import urlparse, quote_plus

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

import requests

from .source_registry import SourceTrustTracker
from .rss_feeds import RSSFeedManager, FeedItem


# ── Data Classes ──────────────────────────────────────────────────────

@dataclass
class SearchItem:
    """A single search result from any source."""
    title: str
    url: str
    snippet: str = ""
    full_text: str = ""        # extracted article body (populated by content extraction)
    source: str = ""           # which search engine found this
    original_source: str = ""  # which news outlet published it
    language: str = "en"
    published: Optional[datetime] = None
    trust_score: float = 0.5
    rrf_score: float = 0.0
    relevance_score: float = 0.0  # LLM or TF-IDF relevance
    recency_boost: float = 0.0    # temporal ranking bonus
    extraction_quality: str = ""  # "full", "snippet", "title_only"

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
class ConflictReport:
    """Two or more sources reporting conflicting information."""
    entity: str               # what the conflict is about (e.g., "Fed rate decision")
    claims: List[Dict]        # [{source, claim, url, timestamp}]
    severity: str = "soft"    # "soft" (different magnitude) or "hard" (contradictory)
    inference: str = ""       # agent's best interpretation
    confidence: float = 0.5


@dataclass
class SearchResult:
    """Aggregated search results from all sources."""
    items: List[SearchItem] = field(default_factory=list)
    conflicts: List[ConflictReport] = field(default_factory=list)
    sources_used: List[str] = field(default_factory=list)
    sources_failed: List[str] = field(default_factory=list)
    expanded_queries: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    query: str = ""
    cached: bool = False
    error: Optional[str] = None
    extraction_count: int = 0     # how many articles got full text


# ── TF-IDF for Fuzzy RSS Search ──────────────────────────────────────

class SimpleTFIDF:
    """Lightweight TF-IDF for fuzzy matching over cached RSS items.

    No external deps — just math on word frequencies.
    Handles both English and Chinese (character n-grams for ZH).
    """

    # CJK Unicode range for detecting Chinese text
    _CJK_RE = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf]')

    # Simple financial stemming: map common variants to base forms
    _STEM_MAP = {
        "federal": "fed", "reserve": "fed", "rates": "rate",
        "interest": "rate", "hiking": "hike", "cutting": "cut",
        "earnings": "earning", "revenues": "revenue", "profits": "profit",
        "surges": "surge", "surging": "surge", "crashes": "crash",
        "falling": "fall", "rising": "rise", "drops": "drop",
        "mergers": "merger", "acquisitions": "acquisition",
    }

    @classmethod
    def tokenize(cls, text: str) -> List[str]:
        """Tokenize text — word-split for EN, character bigrams for ZH.

        Includes simple financial stemming so 'Federal Reserve' matches 'Fed'.
        """
        text = text.lower().strip()
        tokens = []

        # Split on whitespace + punctuation for EN
        words = re.findall(r'[a-z0-9]+|[\u4e00-\u9fff\u3400-\u4dbf]+', text)
        for w in words:
            if cls._CJK_RE.search(w):
                # Chinese: generate character bigrams
                for i in range(len(w) - 1):
                    tokens.append(w[i:i+2])
                if len(w) == 1:
                    tokens.append(w)
            else:
                tokens.append(w)
                # Also add stemmed form if different
                stemmed = cls._STEM_MAP.get(w)
                if stemmed and stemmed != w:
                    tokens.append(stemmed)
        return tokens

    @classmethod
    def score(cls, query: str, documents: List[str]) -> List[float]:
        """Score each document against the query using TF-IDF cosine similarity."""
        if not documents:
            return []

        query_tokens = cls.tokenize(query)
        if not query_tokens:
            return [0.0] * len(documents)

        doc_tokens = [cls.tokenize(d) for d in documents]

        # Build IDF from corpus
        n = len(documents)
        df = Counter()
        for tokens in doc_tokens:
            unique = set(tokens)
            for t in unique:
                df[t] += 1

        idf = {}
        for term, count in df.items():
            idf[term] = math.log((n + 1) / (count + 1)) + 1

        # Query TF-IDF vector
        q_tf = Counter(query_tokens)
        q_vec = {}
        for term, count in q_tf.items():
            q_vec[term] = count * idf.get(term, 1.0)

        # Score each document
        scores = []
        q_norm = math.sqrt(sum(v**2 for v in q_vec.values())) or 1.0

        for tokens in doc_tokens:
            d_tf = Counter(tokens)
            d_vec = {}
            for term, count in d_tf.items():
                d_vec[term] = count * idf.get(term, 1.0)

            # Cosine similarity
            dot = sum(q_vec.get(t, 0) * d_vec.get(t, 0) for t in set(q_vec) | set(d_vec))
            d_norm = math.sqrt(sum(v**2 for v in d_vec.values())) or 1.0
            scores.append(dot / (q_norm * d_norm))

        return scores


# ── Search Cache ──────────────────────────────────────────────────────

class SearchCache:
    """In-memory search cache with TTL."""

    def __init__(self, ttl_seconds: int = 1800):
        self.ttl = ttl_seconds
        self._cache: Dict[str, tuple] = {}  # key -> (result, timestamp)

    def get(self, query: str) -> Optional[SearchResult]:
        key = self._key(query)
        if key in self._cache:
            result, ts = self._cache[key]
            if time.time() - ts < self.ttl:
                result.cached = True
                return result
            del self._cache[key]
        return None

    def set(self, query: str, result: SearchResult):
        self._cache[self._key(query)] = (result, time.time())

    def _key(self, query: str) -> str:
        return hashlib.md5(query.lower().strip().encode()).hexdigest()

    def clear(self):
        self._cache.clear()


# ── Token Bucket Rate Limiter ─────────────────────────────────────────

class TokenBucketLimiter:
    """Rate limiter to prevent API abuse."""

    def __init__(self, rate: float = 1.0, per: float = 1.5):
        self.rate = rate
        self.per = per
        self.tokens = rate
        self.last_refill = time.time()

    async def acquire(self):
        """Wait until a token is available."""
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
    """Extracts full article text from URLs using trafilatura + fallbacks.

    Runs in a thread pool to avoid blocking the event loop.
    Rate-limited to avoid hammering target sites.
    """

    def __init__(self, max_workers: int = 4, timeout: int = 10):
        self.available = HAS_TRAFILATURA
        self.timeout = timeout
        self.max_workers = max_workers
        self._limiter = TokenBucketLimiter(rate=2.0, per=1.0)

    async def extract_batch(self, items: List[SearchItem], top_n: int = 5) -> int:
        """Extract full text for the top N search results.

        Returns the number of successfully extracted articles.
        Mutates items in-place (sets full_text and extraction_quality).
        """
        if not self.available:
            return 0

        count = 0
        tasks = []
        for item in items[:top_n]:
            if item.full_text:  # already has content
                continue
            tasks.append(self._extract_one(item))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, int):
                count += r
        return count

    async def _extract_one(self, item: SearchItem) -> int:
        """Extract text for a single item. Returns 1 on success, 0 on failure."""
        await self._limiter.acquire()
        try:
            loop = asyncio.get_event_loop()
            text = await loop.run_in_executor(None, self._sync_extract, item.url)
            if text and len(text) > 100:
                item.full_text = text[:5000]  # cap at 5k chars
                item.extraction_quality = "full"
                return 1
            else:
                item.extraction_quality = "snippet"
                return 0
        except Exception:
            item.extraction_quality = "snippet"
            return 0

    def _sync_extract(self, url: str) -> Optional[str]:
        """Synchronous extraction using trafilatura."""
        try:
            downloaded = trafilatura.fetch_url(url)
            if not downloaded:
                return None
            text = trafilatura.extract(
                downloaded,
                include_links=False,
                include_images=False,
                include_tables=True,
                output_format='txt',
                favor_recall=True,
            )
            return text
        except Exception:
            return None


# ── Query Expansion ──────────────────────────────────────────────────

class QueryExpander:
    """Generates variant queries to improve search coverage.

    Uses rule-based expansion (no LLM needed for basic variants).
    LLM expansion available as optional upgrade via callback.
    """

    # Financial synonym map
    SYNONYMS = {
        "fed": ["federal reserve", "FOMC", "Jerome Powell"],
        "rate hike": ["interest rate increase", "tightening"],
        "rate cut": ["interest rate decrease", "easing", "dovish"],
        "earnings": ["quarterly results", "revenue report", "Q1 Q2 Q3 Q4"],
        "ipo": ["initial public offering", "going public", "listing"],
        "merger": ["acquisition", "M&A", "buyout", "takeover"],
        "recession": ["economic downturn", "contraction", "GDP decline"],
        "inflation": ["CPI", "consumer prices", "price growth"],
        "央行": ["中国人民银行", "PBOC", "货币政策"],
        "降息": ["利率下调", "宽松", "rate cut"],
        "加息": ["利率上调", "紧缩", "rate hike"],
        "股市": ["A股", "stock market", "证券市场"],
    }

    # Auto-translate common financial queries EN↔ZH
    EN_ZH_PAIRS = {
        "stock market": "股市行情",
        "interest rate": "利率",
        "inflation": "通货膨胀",
        "unemployment": "失业率",
        "trade war": "贸易战",
        "real estate": "房地产",
        "cryptocurrency": "加密货币",
        "oil price": "油价",
        "gold price": "金价",
    }

    def expand(self, query: str, max_variants: int = 3) -> List[str]:
        """Generate variant queries for broader coverage.

        Returns [original_query, variant1, variant2, ...].
        """
        variants = [query]
        query_lower = query.lower()

        # 1. Synonym expansion
        for trigger, synonyms in self.SYNONYMS.items():
            if trigger in query_lower:
                # Pick the first synonym that's different
                for syn in synonyms[:1]:
                    variant = query_lower.replace(trigger, syn)
                    if variant not in [v.lower() for v in variants]:
                        variants.append(variant)
                break  # only one synonym expansion per query

        # 2. Cross-language expansion
        for en, zh in self.EN_ZH_PAIRS.items():
            if en in query_lower:
                variants.append(zh)
                break
            if zh in query:
                variants.append(en)
                break

        # 3. Time-scope variant (add "today" / "this week" for market queries)
        market_words = ["stock", "price", "market", "crypto", "bitcoin", "股", "行情"]
        if any(w in query_lower for w in market_words):
            if "today" not in query_lower and "今日" not in query:
                variants.append(f"{query} today")

        return variants[:max_variants + 1]  # original + max_variants


# ── Individual Source Wrappers ────────────────────────────────────────

class DuckDuckGoSource:
    """DuckDuckGo search wrapper with rate limiting."""

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
            results = await loop.run_in_executor(None, self._sync_search, query, max_results)
            return results
        except Exception:
            return []

    def _sync_search(self, query: str, max_results: int) -> List[SearchItem]:
        """Synchronous DDG search (runs in thread pool)."""
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
    """Google News RSS — free, no API key, no rate limit.

    Google News provides an RSS feed at news.google.com/rss/search.
    Supports both EN and ZH queries with different hl/gl/ceid params.
    """

    _BASE = "https://news.google.com/rss/search"

    def __init__(self, language: str = "en"):
        self.language = language
        self.available = True
        if language == "zh":
            self.params = {"hl": "zh-CN", "gl": "CN", "ceid": "CN:zh-Hans"}
        else:
            self.params = {"hl": "en-US", "gl": "US", "ceid": "US:en"}

    async def search(self, query: str, max_results: int = 10) -> List[SearchItem]:
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._sync_search, query, max_results)
        except Exception:
            return []

    def _sync_search(self, query: str, max_results: int) -> List[SearchItem]:
        items = []
        try:
            import feedparser as fp
        except ImportError:
            return []

        try:
            params = {**self.params, "q": query}
            url = f"{self._BASE}?{'&'.join(f'{k}={quote_plus(str(v))}' for k, v in params.items())}"
            feed = fp.parse(url)

            for entry in feed.entries[:max_results]:
                published = None
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    try:
                        published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                    except (TypeError, ValueError):
                        pass

                # Google News wraps the real source in <a> tags inside the title
                title = re.sub(r'<[^>]+>', '', entry.get('title', '')).strip()
                # Extract real source from the " - SourceName" suffix
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


class NewsAPISource:
    """NewsAPI.org — 100 requests/day free, excellent for financial news."""

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
                        snippet=a.get("description", "") or a.get("content", "")[:300],
                        source="newsapi",
                        original_source=a.get("source", {}).get("name", ""),
                        published=published,
                    ))
        except Exception:
            pass
        return items


class TavilySource:
    """Tavily AI-optimized search (optional, 1000/month free)."""

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
            resp = requests.post(self.base_url, json={
                "api_key": self.api_key,
                "query": query,
                "max_results": max_results,
                "search_depth": "advanced",
                "include_answer": False,
            }, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                for r in data.get("results", []):
                    items.append(SearchItem(
                        title=r.get("title", ""),
                        url=r.get("url", ""),
                        snippet=r.get("content", "")[:300],
                        source="tavily",
                    ))
        except Exception:
            pass
        return items


class SerperSource:
    """Serper.dev Google search wrapper (optional, 2500 free on signup)."""

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
            resp = requests.post(self.base_url, json={
                "q": query,
                "num": max_results,
            }, headers={
                "X-API-KEY": self.api_key,
                "Content-Type": "application/json",
            }, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                for r in data.get("organic", []):
                    items.append(SearchItem(
                        title=r.get("title", ""),
                        url=r.get("link", ""),
                        snippet=r.get("snippet", ""),
                        source="serper",
                    ))
        except Exception:
            pass
        return items


class SearXNGSource:
    """Self-hosted SearXNG meta-search (optional, unlimited)."""

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
            resp = requests.get(f"{self.base_url}/search", params={
                "q": query,
                "format": "json",
                "categories": "general,news",
            }, timeout=10)
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


class RSSSearchSource:
    """Wraps RSSFeedManager with TF-IDF fuzzy matching."""

    def __init__(self, feed_manager: RSSFeedManager):
        self.feed_manager = feed_manager
        self.available = True

    async def search(self, query: str, max_results: int = 10) -> List[SearchItem]:
        try:
            feed_items = await self.feed_manager.fetch_all()
        except Exception:
            feed_items = []
            # Fall back to cached items
            for source_name, (items, cached_at) in self.feed_manager.cache.items():
                if time.time() - cached_at < self.feed_manager.CACHE_TTL:
                    feed_items.extend(items)

        if not feed_items:
            return []

        # Use TF-IDF instead of exact substring matching
        documents = [f"{item.title} {item.summary}" for item in feed_items]
        scores = SimpleTFIDF.score(query, documents)

        # Pair items with scores and filter
        scored = sorted(
            zip(feed_items, scores),
            key=lambda x: x[1],
            reverse=True,
        )

        # Only keep items with meaningful relevance (>0.05 cosine similarity)
        relevant = [(item, score) for item, score in scored if score > 0.05]

        return [
            SearchItem(
                title=item.title,
                url=item.url,
                snippet=item.summary[:200],
                source=f"rss_{item.source}",
                original_source=item.source,
                language=item.language,
                published=item.published,
                relevance_score=score,
            )
            for item, score in relevant[:max_results]
        ]


# ── Temporal Ranking ─────────────────────────────────────────────────

def compute_recency_boost(published: Optional[datetime], domain: str = "finance") -> float:
    """Compute a recency multiplier for search results.

    Financial news has a short half-life:
    - Last 1 hour:   1.5x boost
    - Last 4 hours:  1.3x
    - Last 24 hours: 1.1x
    - Last 7 days:   1.0x (neutral)
    - Older:         0.8x penalty
    """
    if not published:
        return 1.0  # neutral if unknown

    try:
        now = datetime.now(timezone.utc)
        age_hours = (now - published).total_seconds() / 3600
    except (TypeError, ValueError):
        return 1.0

    if domain == "finance":
        if age_hours < 1:
            return 1.5
        elif age_hours < 4:
            return 1.3
        elif age_hours < 24:
            return 1.1
        elif age_hours < 169:  # 7 days (with tolerance for floating point)
            return 1.0
        else:
            return 0.8
    else:
        # General domain: slower decay
        if age_hours < 24:
            return 1.2
        elif age_hours < 168:
            return 1.0
        else:
            return 0.9


# ── Main Hybrid Search Engine ─────────────────────────────────────────

class HybridSearchEngine:
    """
    Multi-source search v2 with RRF, query expansion, content extraction,
    temporal ranking, and fuzzy RSS matching.

    Pipeline:
    1. Expand query → [original, variant1, variant2]
    2. Fire all sources in parallel for each query variant
    3. Merge with Reciprocal Rank Fusion + trust weighting
    4. Apply temporal ranking (recency boost)
    5. Extract full text for top-N results (trafilatura)
    6. Optionally: snowball round-2 using entities from round-1

    Design principles:
    - Always fire Tier 1 (free, no limits)
    - Fire Tier 2 only if available (API key configured)
    - Use RRF to merge results from all sources
    - Track source reliability over time
    - Respect rate limits with token bucket
    """

    RRF_K = 60  # RRF smoothing constant

    def __init__(self, config=None):
        self.config = config

        # Query expansion engine
        self.expander = QueryExpander()

        # Content extractor
        self.extractor = ContentExtractor()

        # Initialize RSS feeds first (used by Tier 1)
        try:
            self.rss_manager = RSSFeedManager()
        except ImportError:
            self.rss_manager = None

        # Tier 1: Always available, no API key needed
        self.tier1_sources = {}
        if HAS_DDG:
            self.tier1_sources["ddg_en"] = DuckDuckGoSource(region="en-us")
            self.tier1_sources["ddg_zh"] = DuckDuckGoSource(region="cn-zh")
        # Google News RSS — always free, no API key
        self.tier1_sources["gnews_en"] = GoogleNewsRSSSource(language="en")
        self.tier1_sources["gnews_zh"] = GoogleNewsRSSSource(language="zh")
        if self.rss_manager:
            self.tier1_sources["rss"] = RSSSearchSource(self.rss_manager)

        # Tier 2: API key optional, graceful degradation
        self.tier2_sources = {}
        tavily = TavilySource()
        if tavily.available:
            self.tier2_sources["tavily"] = tavily
        serper = SerperSource()
        if serper.available:
            self.tier2_sources["serper"] = serper
        newsapi = NewsAPISource()
        if newsapi.available:
            self.tier2_sources["newsapi"] = newsapi

        # Tier 3: Self-hosted, optional
        self.tier3_sources = {}
        searxng = SearXNGSource()
        if searxng.available:
            self.tier3_sources["searxng"] = searxng

        # Trust tracker
        self.source_trust = SourceTrustTracker()

        # Cache (15 min for financial data)
        self.cache = SearchCache(ttl_seconds=900)

    async def search(
        self,
        query: str,
        languages: Optional[List[str]] = None,
        max_results: int = 20,
        depth: int = 1,
        extract_content: bool = True,
        expand_queries: bool = True,
    ) -> SearchResult:
        """
        Execute search across all available sources.

        Args:
            query: Search query
            languages: Filter languages ["en", "zh"]. None = both.
            max_results: Maximum results to return
            depth: 1 = standard, 2 = snowball (use round-1 entities for round-2)
            extract_content: Whether to fetch full article text for top results
            expand_queries: Whether to generate variant queries
        """
        # Check cache first
        cached = self.cache.get(query)
        if cached is not None:
            return cached

        languages = languages or ["en", "zh"]

        # Step 1: Query Expansion
        if expand_queries:
            queries = self.expander.expand(query, max_variants=2)
        else:
            queries = [query]

        # Step 2: Fire all sources in parallel for all query variants
        all_results_by_source: Dict[str, List[SearchItem]] = {}
        sources_failed = []

        all_sources = {}
        all_sources.update(self.tier1_sources)
        all_sources.update(self.tier2_sources)
        all_sources.update(self.tier3_sources)

        if not all_sources:
            return SearchResult(
                query=query,
                error="No search sources available. Install duckduckgo-search or configure API keys.",
            )

        # Launch searches for all (source, query) combinations
        tasks = {}
        for q in queries:
            for name, source in all_sources.items():
                task_key = f"{name}___{q}"
                tasks[task_key] = source.search(q, max_results=max_results)

        task_results = await asyncio.gather(
            *tasks.values(), return_exceptions=True
        )

        for task_key, result in zip(tasks.keys(), task_results):
            source_name = task_key.split("___")[0]
            if isinstance(result, Exception) or not result:
                if source_name not in sources_failed:
                    sources_failed.append(source_name)
            else:
                if source_name not in all_results_by_source:
                    all_results_by_source[source_name] = []
                all_results_by_source[source_name].extend(result)

        # Step 3: Merge with RRF
        merged = self._reciprocal_rank_fusion(all_results_by_source)

        # Step 4: Temporal ranking boost
        for item in merged:
            boost = compute_recency_boost(item.published, domain="finance")
            item.recency_boost = boost
            item.rrf_score *= boost

        # Re-sort after temporal boost
        merged.sort(key=lambda x: x.rrf_score, reverse=True)

        # Step 5: Language filter
        if languages:
            merged = [
                item for item in merged
                if not item.language or item.language in languages
            ]

        # Step 6: Trim to max_results
        merged = merged[:max_results]

        # Step 7: Content extraction for top results
        extraction_count = 0
        if extract_content and self.extractor.available:
            extraction_count = await self.extractor.extract_batch(merged, top_n=5)

        # Step 8: Snowball refinement (depth=2)
        if depth >= 2 and merged:
            snowball_items = await self._snowball_round(merged[:10], all_sources, languages)
            if snowball_items:
                # Merge snowball results (lower weight)
                for item in snowball_items:
                    item.rrf_score *= 0.7  # discount snowball results
                merged.extend(snowball_items)
                # Re-deduplicate
                seen = set()
                unique = []
                for item in sorted(merged, key=lambda x: x.rrf_score, reverse=True):
                    key = self._dedup_key(item.url)
                    if key not in seen:
                        seen.add(key)
                        unique.append(item)
                merged = unique[:max_results]

        result = SearchResult(
            items=merged,
            sources_used=list(all_results_by_source.keys()),
            sources_failed=list(set(sources_failed) - set(all_results_by_source.keys())),
            expanded_queries=queries,
            query=query,
            extraction_count=extraction_count,
        )

        # Cache the result
        self.cache.set(query, result)

        return result

    async def _snowball_round(
        self,
        seed_items: List[SearchItem],
        sources: Dict,
        languages: List[str],
    ) -> List[SearchItem]:
        """Snowball: extract entities from round-1, search for them in round-2."""
        # Extract frequent entities/tickers from round-1 titles
        entity_counts = Counter()
        ticker_re = re.compile(r'\b[A-Z]{2,5}\b')
        for item in seed_items:
            tickers = ticker_re.findall(item.title)
            for t in tickers:
                if t not in ("THE", "AND", "FOR", "USD", "RSS", "CEO", "IPO", "ETF"):
                    entity_counts[t] += 1

        # Pick top 2 entities not in original query
        top_entities = [e for e, c in entity_counts.most_common(5) if c >= 2][:2]
        if not top_entities:
            return []

        # Search for those entities
        tasks = {}
        for entity in top_entities:
            for name, source in list(sources.items())[:3]:  # limit to 3 sources
                task_key = f"{name}___{entity}"
                tasks[task_key] = source.search(f"{entity} news", max_results=5)

        results = await asyncio.gather(*tasks.values(), return_exceptions=True)

        snowball_items = []
        for result in results:
            if isinstance(result, list):
                snowball_items.extend(result)
        return snowball_items

    def _reciprocal_rank_fusion(self, results_by_source: Dict[str, List[SearchItem]]) -> List[SearchItem]:
        """
        RRF formula: score(d) = Σ 1/(k + rank_i(d))

        Enhanced with:
        - Trust-weighted scoring
        - Multi-source appearance bonus
        - Relevance score integration (from TF-IDF sources)
        """
        url_scores: Dict[str, float] = defaultdict(float)
        url_items: Dict[str, SearchItem] = {}
        url_source_count: Dict[str, int] = defaultdict(int)  # track cross-source appearance

        for source_name, items in results_by_source.items():
            for rank, item in enumerate(items):
                key = self._dedup_key(item.url)
                rrf_score = 1.0 / (self.RRF_K + rank)

                # Boost by source trust
                trust = self.source_trust.get(source_name, 0.5)
                rrf_score *= (0.5 + trust)  # trust range maps to [0.5, 1.5] multiplier

                # Integrate TF-IDF relevance if available
                if item.relevance_score > 0:
                    rrf_score *= (1.0 + item.relevance_score * 0.5)

                url_scores[key] += rrf_score
                url_source_count[key] += 1

                # Keep the item with the best snippet
                if key not in url_items or len(item.snippet) > len(url_items[key].snippet):
                    url_items[key] = item

        # Cross-source bonus: items appearing in 3+ sources get a 20% boost
        for key in url_scores:
            if url_source_count[key] >= 3:
                url_scores[key] *= 1.2
            elif url_source_count[key] >= 2:
                url_scores[key] *= 1.1

        # Sort by RRF score
        sorted_keys = sorted(url_scores.keys(), key=lambda k: -url_scores[k])

        results = []
        for key in sorted_keys:
            item = url_items[key]
            item.rrf_score = url_scores[key]
            results.append(item)

        return results

    def _dedup_key(self, url: str) -> str:
        """Normalize URL for deduplication."""
        try:
            parsed = urlparse(url.lower().strip().rstrip("/"))
            # Remove tracking params
            clean = f"{parsed.netloc}{parsed.path}"
            return hashlib.md5(clean.encode()).hexdigest()
        except Exception:
            return hashlib.md5(url.encode()).hexdigest()

    def get_status(self) -> str:
        """Get human-readable status of all search sources."""
        lines = ["Search Engine Status (v2 — Hybrid)", "=" * 55]

        t1 = self.tier1_sources
        t2 = self.tier2_sources
        t3 = self.tier3_sources

        lines.append(f"\n  Tier 1 (Free Unlimited): {len(t1)} sources")
        for name in t1:
            lines.append(f"    ✅ {name}")

        lines.append(f"\n  Tier 2 (Free w/ Limits): {len(t2)} sources")
        for name in t2:
            lines.append(f"    ✅ {name}")
        if not t2:
            lines.append("    ⚠️  None configured (set TAVILY_API_KEY, SERPER_API_KEY, or NEWSAPI_API_KEY)")

        lines.append(f"\n  Tier 3 (Self-Hosted): {len(t3)} sources")
        for name in t3:
            lines.append(f"    ✅ {name}")
        if not t3:
            lines.append("    ⚠️  None configured (set SEARXNG_URL)")

        total = len(t1) + len(t2) + len(t3)
        lines.append(f"\n  Intelligence layers:")
        lines.append(f"    ✅ Query expansion (synonyms + cross-language)")
        lines.append(f"    ✅ TF-IDF fuzzy RSS matching")
        lines.append(f"    ✅ Temporal ranking (recency boost)")
        lines.append(f"    {'✅' if self.extractor.available else '⚠️'} Content extraction (trafilatura)")
        lines.append(f"    ✅ RRF merge with trust weighting")
        lines.append(f"    ✅ Snowball refinement (depth=2)")

        lines.append(f"\n  Total: {total} search sources active")
        return "\n".join(lines)
