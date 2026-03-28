# agent/search/engine.py
"""
Universal Search Engine — the orchestrator.

Replaces the single-source OptimizedDuckDuckGoSearch with a multi-source,
multi-strategy search engine that works across ALL NeoMind modes.

Pipeline:
  1. Check cache
  2. Expand query → [original, variant1, variant2]
  3. Fire all available sources in parallel
  4. Merge with Reciprocal Rank Fusion (trust-weighted)
  5. Apply temporal ranking (recency boost)
  6. Semantic reranking with FlashRank (if available)
  7. Extract full text for top-N results (trafilatura)
  8. Cache results
  9. Format for LLM consumption

Design principles:
  - Tier 1 sources always fire (free, no limits)
  - Tier 2 sources fire only if API keys are configured
  - Tier 3 (self-hosted) fire if available
  - Graceful degradation: works with zero API keys (DDG + Google News RSS)
  - All tiers fire in parallel for minimum latency
"""

import os
import re
import time
import asyncio
from datetime import datetime, timezone
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

from .sources import (
    SearchItem, SearchResult, ContentExtractor, Crawl4AIExtractor,
    DuckDuckGoSource, GoogleNewsRSSSource, NewsAPISource,
    BraveSearchSource, SerperSource, TavilySource,
    SearXNGSource, JinaSearchSource, ExaSearchSource,
    YouComSource, PerplexitySonarSource,
)
from .reranker import RRFMerger, FlashReranker, CohereReranker
from .query_expansion import QueryExpander
from .cache import SearchCache, DiskSearchCache
from .router import QueryRouter
from .metrics import SearchMetrics
from .vector_store import LocalVectorStore


# ── Temporal Ranking ─────────────────────────────────────────────────

def compute_recency_boost(published: Optional[datetime], domain: str = "general") -> float:
    """Compute a recency multiplier for search results.

    Domain-specific decay curves:
    - finance: fast decay (news has hours-level half-life)
    - general: moderate decay (days-level half-life)
    """
    if not published:
        return 1.0

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
        elif age_hours < 168:
            return 1.0
        else:
            return 0.8
    else:  # general / coding
        if age_hours < 24:
            return 1.2
        elif age_hours < 168:
            return 1.05
        elif age_hours < 720:  # 30 days
            return 1.0
        else:
            return 0.9


# ── Universal Search Engine ──────────────────────────────────────────

class UniversalSearchEngine:
    """
    Multi-source search engine for all NeoMind modes.

    Drop-in replacement for OptimizedDuckDuckGoSearch with the same
    `search()` and `should_search()` interface, plus richer output.

    Usage:
        engine = UniversalSearchEngine(domain="general")
        result = await engine.search_advanced("latest AI news")
        # or for backward compatibility:
        success, text = await engine.search("latest AI news")
    """

    def __init__(self, domain: str = "general", triggers: Optional[set] = None):
        """
        Args:
            domain: "general", "finance", or "coding"
            triggers: Auto-search trigger keywords (for should_search)
        """
        self.domain = domain

        # Query expansion
        self.expander = QueryExpander(domain=domain)

        # Content extractors (trafilatura primary, Crawl4AI fallback)
        self.extractor = ContentExtractor()
        self.crawl4ai = Crawl4AIExtractor()

        # Reranking
        self.rrf_merger = RRFMerger(k=60)
        self.flash_reranker = FlashReranker()
        self.cohere_reranker = CohereReranker()

        # Query router — classifies queries and adjusts source trust weights
        self.router = QueryRouter()

        # Metrics tracker
        self.metrics = SearchMetrics()

        # Local vector store (optional — for "have I searched this before?" queries)
        try:
            self.vector_store = LocalVectorStore()
        except Exception:
            self.vector_store = None

        # Layered cache: memory (fast, short TTL) + disk (persistent, longer TTL)
        cache_ttl = 900 if domain == "finance" else 300
        self.cache = SearchCache(ttl_seconds=cache_ttl)
        # Disk cache for longer persistence (24h, optional)
        try:
            import os as _os
            cache_dir = _os.path.expanduser("~/.neomind")
            _os.makedirs(cache_dir, exist_ok=True)
            self.disk_cache = DiskSearchCache(
                db_path=_os.path.join(cache_dir, "search_cache.db"),
                ttl_seconds=86400,  # 24 hours
            )
        except Exception:
            self.disk_cache = None

        # ── Source initialization ────────────────────────────────────

        # Tier 1: Always available, no API key needed
        self.tier1_sources: Dict[str, object] = {}
        ddg_en = DuckDuckGoSource(region="en-us")
        if ddg_en.available:
            self.tier1_sources["ddg_en"] = ddg_en
        ddg_zh = DuckDuckGoSource(region="cn-zh")
        if ddg_zh.available:
            self.tier1_sources["ddg_zh"] = ddg_zh
        gnews_en = GoogleNewsRSSSource(language="en")
        if gnews_en.available:
            self.tier1_sources["gnews_en"] = gnews_en
        gnews_zh = GoogleNewsRSSSource(language="zh")
        if gnews_zh.available:
            self.tier1_sources["gnews_zh"] = gnews_zh

        # Tier 2: API key optional, graceful degradation
        self.tier2_sources: Dict[str, object] = {}
        brave = BraveSearchSource()
        if brave.available:
            self.tier2_sources["brave"] = brave
        serper = SerperSource()
        if serper.available:
            self.tier2_sources["serper"] = serper
        tavily = TavilySource()
        if tavily.available:
            self.tier2_sources["tavily"] = tavily
        jina = JinaSearchSource()
        if jina.available and os.getenv("JINA_API_KEY"):
            # Only add Jina if API key is set (to avoid hitting free limits)
            self.tier2_sources["jina"] = jina
        newsapi = NewsAPISource()
        if newsapi.available:
            self.tier2_sources["newsapi"] = newsapi
        exa = ExaSearchSource()
        if exa.available:
            self.tier2_sources["exa"] = exa
        youcom = YouComSource()
        if youcom.available:
            self.tier2_sources["youcom"] = youcom
        perplexity = PerplexitySonarSource()
        if perplexity.available:
            self.tier2_sources["perplexity"] = perplexity

        # Tier 3: Self-hosted, optional
        self.tier3_sources: Dict[str, object] = {}
        searxng = SearXNGSource()
        if searxng.available:
            self.tier3_sources["searxng"] = searxng

        # ── Auto-search detection ───────────────────────────────────

        self.triggers = triggers if triggers is not None else {
            "today", "news", "weather", "latest", "current", "now", "recent",
            "2026", "2025", "2024", "yesterday", "tomorrow", "update", "breaking",
            "stock", "price", "score", "results", "announcement", "release",
            "search", "find", "look up", "what happened", "who is", "how to",
        }

        self.time_patterns = [
            r"what.*happened.*today",
            r"current.*events",
            r"latest.*news",
            r"recent.*developments",
            r"stock.*price.*of",
            r"score.*of.*game",
            r"weather.*in.*",
            r"forecast.*for.*",
            r"breaking.*news",
            r"who is the.*",
            r"what is the.*price",
        ]

    # ── Backward-compatible interface (drop-in for OptimizedDDGSearch) ──

    @lru_cache(maxsize=100)
    def should_search(self, query: str) -> bool:
        """Detect if a query needs web search (auto-search trigger)."""
        query_lower = query.lower()
        if any(trigger in query_lower for trigger in self.triggers):
            return True
        if any(re.search(pattern, query_lower) for pattern in self.time_patterns):
            return True
        return False

    async def search(self, query: str) -> Tuple[bool, str]:
        """Backward-compatible search returning (success, formatted_text).

        This is the drop-in replacement for OptimizedDuckDuckGoSearch.search().
        """
        start = time.time()
        result = await self.search_advanced(query)

        if result.error:
            return False, result.error
        if not result.items:
            return False, f"No results found for '{query}'."

        elapsed = time.time() - start
        text = result.format_for_llm(max_items=8, include_full_text=True)
        src_names = ", ".join(result.sources_used) if result.sources_used else "none"
        header = f"🔍 [{elapsed:.2f}s | {src_names}"
        if result.reranked:
            header += " | reranked"
        if result.cached:
            header += " | cached"
        header += f"] {len(result.items)} results"

        return True, f"{header}\n\n{text}"

    # ── Advanced search interface ────────────────────────────────────

    async def search_advanced(
        self,
        query: str,
        max_results: int = 20,
        expand_queries: bool = True,
        extract_content: bool = True,
        rerank: bool = True,
        languages: Optional[List[str]] = None,
    ) -> SearchResult:
        """Full search pipeline with all intelligence layers.

        Args:
            query: Search query
            max_results: Maximum results to return
            expand_queries: Whether to generate query variants
            extract_content: Whether to fetch full article text
            rerank: Whether to apply FlashRank semantic reranking
            languages: Language filter ["en", "zh"]. None = both.
        """
        _search_start = time.time()

        # Step 0: Check cache
        cached = self.cache.get(query)
        if cached is not None:
            # Record cache hit
            self.metrics.record(
                query=query, query_type="cached",
                sources_used=cached.sources_used, sources_failed=[],
                result_count=len(cached.items), extraction_count=0,
                reranked=cached.reranked, cached=True,
                latency_ms=(time.time() - _search_start) * 1000,
            )
            return cached

        # Step 1: Query expansion
        if expand_queries:
            queries = self.expander.expand(query, max_variants=2)
        else:
            queries = [query]

        # Step 2: Fire all sources in parallel
        all_sources = {}
        all_sources.update(self.tier1_sources)
        all_sources.update(self.tier2_sources)
        all_sources.update(self.tier3_sources)

        if not all_sources:
            return SearchResult(
                query=query,
                error="No search sources available. Install duckduckgo-search or configure API keys.",
            )

        all_results_by_source: Dict[str, List[SearchItem]] = {}
        sources_failed = []

        # Launch all (source, query) combinations in parallel
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

        # Step 3: RRF Merge (with router-optimized trust weights)
        query_type, trust_weights = self.router.route(query)
        self.rrf_merger.trust_scores = trust_weights
        merged = self.rrf_merger.merge(all_results_by_source)

        # Step 4: Temporal ranking
        for item in merged:
            boost = compute_recency_boost(item.published, domain=self.domain)
            item.recency_boost = boost
            item.rrf_score *= boost
        merged.sort(key=lambda x: x.rrf_score, reverse=True)

        # Step 5: Language filter
        if languages:
            merged = [
                item for item in merged
                if not item.language or item.language in languages
            ]

        # Step 6: Trim to max_results
        merged = merged[:max_results]

        # Step 7: Semantic reranking
        # Prefer Cohere (higher accuracy) if available, otherwise FlashRank (free)
        reranked = False
        if rerank and len(merged) > 1:
            if self.cohere_reranker.available:
                merged = self.cohere_reranker.rerank(query, merged, top_n=min(20, len(merged)))
                reranked = True
            elif self.flash_reranker.available:
                merged = self.flash_reranker.rerank(query, merged, top_n=min(20, len(merged)))
                reranked = True

        # Step 8: Content extraction for top results
        # Primary: trafilatura (fast, reliable)
        # Fallback: Crawl4AI (handles JS-rendered pages)
        extraction_count = 0
        if extract_content:
            if self.extractor.available:
                extraction_count = await self.extractor.extract_batch(merged, top_n=5)
            # Use Crawl4AI for items that trafilatura missed
            if self.crawl4ai.available:
                remaining = [item for item in merged[:5] if not item.full_text]
                if remaining:
                    extra = await self.crawl4ai.extract_batch(remaining, top_n=3)
                    extraction_count += extra

        # Build result
        result = SearchResult(
            items=merged,
            sources_used=list(all_results_by_source.keys()),
            sources_failed=list(set(sources_failed) - set(all_results_by_source.keys())),
            expanded_queries=queries,
            query=query,
            extraction_count=extraction_count,
            reranked=reranked,
        )

        # Step 9: Cache
        self.cache.set(query, result)

        # Step 9b: Index in vector store (for future similarity queries)
        if self.vector_store and self.vector_store.available:
            try:
                self.vector_store.add_results(query, merged[:10])
            except Exception:
                pass  # Non-critical — don't break search if indexing fails

        # Step 10: Record metrics
        elapsed_ms = (time.time() - _search_start) * 1000 if '_search_start' in dir() else 0
        self.metrics.record(
            query=query,
            query_type=query_type,
            sources_used=result.sources_used,
            sources_failed=result.sources_failed,
            result_count=len(result.items),
            extraction_count=extraction_count,
            reranked=reranked,
            cached=False,
            latency_ms=elapsed_ms,
            expanded_queries=queries,
        )

        return result

    # ── Status & diagnostics ─────────────────────────────────────────

    def get_status(self) -> str:
        """Get human-readable status of all search sources."""
        lines = ["Universal Search Engine Status", "=" * 55]

        t1 = self.tier1_sources
        t2 = self.tier2_sources
        t3 = self.tier3_sources

        lines.append(f"\n  Domain: {self.domain}")

        lines.append(f"\n  Tier 1 (Free Unlimited): {len(t1)} sources")
        for name in t1:
            lines.append(f"    + {name}")

        lines.append(f"\n  Tier 2 (Free w/ Limits): {len(t2)} sources")
        for name in t2:
            lines.append(f"    + {name}")
        if not t2:
            lines.append("    (none — set BRAVE_API_KEY, SERPER_API_KEY, TAVILY_API_KEY, or JINA_API_KEY)")

        lines.append(f"\n  Tier 3 (Self-Hosted): {len(t3)} sources")
        for name in t3:
            lines.append(f"    + {name}")
        if not t3:
            lines.append("    (none — set SEARXNG_URL)")

        total = len(t1) + len(t2) + len(t3)
        lines.append(f"\n  Intelligence layers:")
        lines.append(f"    + Query expansion ({self.domain} domain)")
        lines.append(f"    + Smart query router (news/tech/finance/academic/general)")
        lines.append(f"    + RRF merge with trust weighting")
        lines.append(f"    + Temporal ranking (recency boost)")
        lines.append(f"    {'+ ' if self.cohere_reranker.available else '- '}Cohere Rerank (high-accuracy, paid)")
        lines.append(f"    {'+ ' if self.flash_reranker.available else '- '}FlashRank semantic reranking (free)")
        lines.append(f"    {'+ ' if self.extractor.available else '- '}Content extraction (trafilatura)")
        lines.append(f"    {'+ ' if self.crawl4ai.available else '- '}Crawl4AI fallback extractor")
        vs_ok = self.vector_store and self.vector_store.available
        lines.append(f"    {'+ ' if vs_ok else '- '}Local vector search (FAISS)")

        lines.append(f"\n  Total: {total} search sources active")
        lines.append(f"  Cache: {self.cache.size()} entries ({self.cache.ttl}s TTL)")

        return "\n".join(lines)

    def set_domain(self, domain: str):
        """Switch domain (e.g., when mode changes)."""
        self.domain = domain
        self.expander.set_domain(domain)
        # Adjust cache TTL
        self.cache.ttl = 900 if domain == "finance" else 300
