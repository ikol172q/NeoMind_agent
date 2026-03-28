"""
Comprehensive unit tests for agent/finance/hybrid_search.py
Tests search engine, ranking, content extraction, and query expansion.
"""

import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from pathlib import Path

from agent.finance.hybrid_search import (
    SearchItem,
    ConflictReport,
    SearchResult,
    SimpleTFIDF,
    SearchCache,
    TokenBucketLimiter,
    QueryExpander,
    compute_recency_boost,
    HybridSearchEngine,
)


# ── SearchItem Tests ────────────────────────────────────────────────

class TestSearchItem:
    def test_creation_minimal(self):
        item = SearchItem(title="Test Title", url="https://example.com")
        assert item.title == "Test Title"
        assert item.url == "https://example.com"
        assert item.snippet == ""
        assert item.language == "en"
        assert item.trust_score == 0.5

    def test_creation_full(self):
        pub_time = datetime.now(timezone.utc)
        item = SearchItem(
            title="Full Article",
            url="https://example.com/article",
            snippet="This is the snippet",
            source="google",
            original_source="Reuters",
            published=pub_time,
            trust_score=0.85,
            relevance_score=0.9,
        )
        assert item.title == "Full Article"
        assert item.source == "google"
        assert item.original_source == "Reuters"
        assert item.trust_score == 0.85

    def test_domain_extraction(self):
        item = SearchItem(title="Test", url="https://www.example.com/path")
        assert item.domain == "example.com"

    def test_domain_extraction_no_www(self):
        item = SearchItem(title="Test", url="https://example.com/path")
        assert item.domain == "example.com"

    def test_best_content_priority(self):
        item = SearchItem(
            title="Title",
            url="https://example.com",
            snippet="Snippet text",
            full_text="Full article text with much more content",
        )
        assert item.best_content == item.full_text

    def test_best_content_fallback_to_snippet(self):
        item = SearchItem(title="Title", url="https://example.com", snippet="Snippet")
        assert item.best_content == "Snippet"

    def test_best_content_fallback_to_title(self):
        item = SearchItem(title="Title Only", url="https://example.com")
        assert item.best_content == "Title Only"


# ── ConflictReport Tests ────────────────────────────────────────────

class TestConflictReport:
    def test_creation(self):
        claims = [
            {"source": "Reuters", "claim": "Rate cut coming", "url": "https://reuters.com"},
            {"source": "FT", "claim": "No rate cut expected", "url": "https://ft.com"},
        ]
        report = ConflictReport(
            entity="Fed Rate Decision",
            claims=claims,
            severity="hard",
            confidence=0.8,
        )
        assert report.entity == "Fed Rate Decision"
        assert len(report.claims) == 2
        assert report.severity == "hard"
        assert report.confidence == 0.8


# ── SearchResult Tests ──────────────────────────────────────────────

class TestSearchResult:
    def test_creation_empty(self):
        result = SearchResult()
        assert result.items == []
        assert result.conflicts == []
        assert result.sources_used == []

    def test_creation_with_data(self):
        items = [SearchItem(title="Item 1", url="https://example.com")]
        result = SearchResult(items=items, sources_used=["google"], query="test")
        assert len(result.items) == 1
        assert result.sources_used == ["google"]
        assert result.query == "test"


# ── SimpleTFIDF Tests ───────────────────────────────────────────────

class TestSimpleTFIDF:
    def test_tokenize_english(self):
        text = "Federal Reserve rates hiking inflation"
        tokens = SimpleTFIDF.tokenize(text)
        assert "federal" in tokens or "fed" in tokens
        assert len(tokens) > 0

    def test_tokenize_with_numbers(self):
        text = "Bitcoin 45000 Ethereum 2500"
        tokens = SimpleTFIDF.tokenize(text)
        assert "bitcoin" in tokens
        assert "ethereum" in tokens
        assert "45000" in tokens

    def test_tokenize_chinese(self):
        text = "中央银行 降息 股票"
        tokens = SimpleTFIDF.tokenize(text)
        # Should have character bigrams
        assert len(tokens) > 0

    def test_tokenize_mixed_language(self):
        text = "Federal Reserve 降息 rates"
        tokens = SimpleTFIDF.tokenize(text)
        assert len(tokens) > 0

    def test_score_single_document(self):
        query = "inflation rates"
        documents = ["Federal Reserve raises rates due to inflation"]
        scores = SimpleTFIDF.score(query, documents)
        assert len(scores) == 1
        assert scores[0] > 0

    def test_score_multiple_documents(self):
        query = "earnings beat"
        documents = [
            "Apple earnings beat expectations",
            "Microsoft misses earnings forecast",
            "Tech stocks rally on earnings",
        ]
        scores = SimpleTFIDF.score(query, documents)
        assert len(scores) == 3
        # First doc should score higher
        assert scores[0] > scores[1]

    def test_score_empty_query(self):
        query = ""
        documents = ["doc1", "doc2"]
        scores = SimpleTFIDF.score(query, documents)
        assert all(s == 0.0 for s in scores)

    def test_score_empty_documents(self):
        query = "test"
        documents = []
        scores = SimpleTFIDF.score(query, documents)
        assert scores == []

    def test_score_no_matching_documents(self):
        query = "quantum computing"
        documents = ["weather forecast", "sports results"]
        scores = SimpleTFIDF.score(query, documents)
        assert all(s == 0.0 for s in scores)


# ── SearchCache Tests ───────────────────────────────────────────────

class TestSearchCache:
    def test_cache_set_get(self):
        cache = SearchCache(ttl_seconds=300)
        result = SearchResult(items=[], query="test")
        cache.set("test query", result)

        cached = cache.get("test query")
        assert cached is not None
        assert cached.query == "test"
        assert cached.cached is True

    def test_cache_ttl_expired(self):
        cache = SearchCache(ttl_seconds=0)  # Immediate expiration
        result = SearchResult(query="test")
        cache.set("query", result)

        # Immediately should be expired
        cached = cache.get("query")
        assert cached is None

    def test_cache_case_insensitive(self):
        cache = SearchCache()
        result = SearchResult(query="TEST")
        cache.set("Test Query", result)

        cached = cache.get("test query")
        assert cached is not None

    def test_cache_clear(self):
        cache = SearchCache()
        cache.set("key1", SearchResult())
        cache.set("key2", SearchResult())

        cache.clear()
        assert cache.get("key1") is None
        assert cache.get("key2") is None


# ── TokenBucketLimiter Tests ────────────────────────────────────────

class TestTokenBucketLimiter:
    @pytest.mark.asyncio
    async def test_acquire_immediate(self):
        """Test that initial token is available immediately."""
        limiter = TokenBucketLimiter(rate=1.0, per=1.0)
        # Should complete immediately
        await asyncio.wait_for(limiter.acquire(), timeout=0.5)

    @pytest.mark.asyncio
    async def test_acquire_multiple(self):
        """Test acquiring multiple tokens with rate limiting."""
        limiter = TokenBucketLimiter(rate=2.0, per=1.0)  # 2 tokens per second

        # First two should be immediate
        await limiter.acquire()
        await limiter.acquire()

        # Third should wait
        start = asyncio.get_event_loop().time()
        await asyncio.wait_for(limiter.acquire(), timeout=2.0)
        elapsed = asyncio.get_event_loop().time() - start
        assert elapsed > 0  # Should have waited


# ── QueryExpander Tests ──────────────────────────────────────────────

class TestQueryExpander:
    def test_expand_with_synonyms(self):
        expander = QueryExpander()
        variants = expander.expand("fed rate hike")
        assert len(variants) >= 1
        assert "fed rate hike" in [v.lower() for v in variants]

    def test_expand_with_cross_language(self):
        expander = QueryExpander()
        variants = expander.expand("stock market")
        # Should include English and Chinese variants
        assert len(variants) >= 1

    def test_expand_chinese_to_english(self):
        expander = QueryExpander()
        variants = expander.expand("股票")
        # Should try to expand to English
        assert len(variants) >= 1

    def test_expand_max_variants(self):
        expander = QueryExpander()
        variants = expander.expand("cryptocurrency", max_variants=2)
        assert len(variants) <= 3  # original + max_variants

    def test_expand_no_synonyms(self):
        expander = QueryExpander()
        variants = expander.expand("obscure technical term")
        # Should at least return original
        assert "obscure technical term" in [v.lower() for v in variants]

    def test_expand_market_keywords(self):
        expander = QueryExpander()
        variants = expander.expand("bitcoin price")
        # Should expand with "today"
        assert len(variants) > 1


# ── compute_recency_boost Tests ──────────────────────────────────────

class TestComputeRecencyBoost:
    def test_boost_very_recent(self):
        """Test boost for very recent article."""
        now = datetime.now(timezone.utc)
        recent = now - timedelta(minutes=30)
        boost = compute_recency_boost(recent, domain="finance")
        assert boost >= 1.3

    def test_boost_1_hour_old(self):
        """Test boost for 1-hour-old article."""
        now = datetime.now(timezone.utc)
        old = now - timedelta(hours=1)
        boost = compute_recency_boost(old, domain="finance")
        assert 1.2 <= boost <= 1.5

    def test_boost_one_day_old(self):
        """Test boost for 1-day-old article."""
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=1)
        boost = compute_recency_boost(old, domain="finance")
        assert 1.0 <= boost <= 1.2

    def test_boost_one_week_old(self):
        """Test boost for 1-week-old article."""
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=7)
        boost = compute_recency_boost(old, domain="finance")
        assert 0.9 <= boost <= 1.0

    def test_boost_very_old(self):
        """Test boost for very old article."""
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=30)
        boost = compute_recency_boost(old, domain="finance")
        assert boost == 0.8

    def test_boost_none_date(self):
        """Test boost when published date is None."""
        boost = compute_recency_boost(None)
        assert boost == 1.0  # Neutral

    def test_boost_different_domain(self):
        """Test boost for non-finance domain."""
        now = datetime.now(timezone.utc)
        recent = now - timedelta(hours=1)
        boost = compute_recency_boost(recent, domain="general")
        assert boost > 1.0


# ── HybridSearchEngine Tests ────────────────────────────────────────

class TestHybridSearchEngine:
    @pytest.fixture
    def engine(self):
        """Create search engine with mocked sources."""
        with patch("agent.finance.hybrid_search.DuckDuckGoSource"):
            with patch("agent.finance.hybrid_search.RSSFeedManager"):
                engine = HybridSearchEngine()
                return engine

    def test_initialization(self, engine):
        assert engine.expander is not None
        assert engine.cache is not None
        assert engine.source_trust is not None

    def test_cache_get_miss(self, engine):
        """Test cache miss."""
        result = engine.cache.get("nonexistent query")
        assert result is None

    def test_cache_hit(self, engine):
        """Test cache hit."""
        original = SearchResult(query="test", items=[])
        engine.cache.set("test", original)

        cached = engine.cache.get("test")
        assert cached is not None
        assert cached.cached is True

    def test_dedup_key_identical_urls(self, engine):
        """Test that identical URLs produce same dedup key."""
        key1 = engine._dedup_key("https://example.com/article")
        key2 = engine._dedup_key("https://example.com/article")
        assert key1 == key2

    def test_dedup_key_ignores_trailing_slash(self, engine):
        """Test that trailing slash is normalized."""
        key1 = engine._dedup_key("https://example.com/article/")
        key2 = engine._dedup_key("https://example.com/article")
        assert key1 == key2

    def test_dedup_key_case_insensitive(self, engine):
        """Test that URL comparison is case-insensitive."""
        key1 = engine._dedup_key("https://EXAMPLE.com/article")
        key2 = engine._dedup_key("https://example.com/article")
        assert key1 == key2

    def test_rrf_basic(self, engine):
        """Test basic RRF merging."""
        results_by_source = {
            "source1": [
                SearchItem(title="Article A", url="https://a.com"),
                SearchItem(title="Article B", url="https://b.com"),
            ],
            "source2": [
                SearchItem(title="Article A", url="https://a.com"),
                SearchItem(title="Article C", url="https://c.com"),
            ],
        }

        merged = engine._reciprocal_rank_fusion(results_by_source)

        # Article A appears in both sources, should rank higher
        urls = [m.url for m in merged]
        assert urls[0] == "https://a.com"  # Highest score

    def test_rrf_cross_source_bonus(self, engine):
        """Test that items appearing in multiple sources get bonus."""
        results_by_source = {
            "s1": [SearchItem(title="Hit", url="https://hit.com")],
            "s2": [SearchItem(title="Hit", url="https://hit.com")],
            "s3": [SearchItem(title="Hit", url="https://hit.com")],
            "s4": [SearchItem(title="Miss", url="https://miss.com")],
        }

        merged = engine._reciprocal_rank_fusion(results_by_source)

        # Item in 3 sources should rank above item in 1 source
        assert merged[0].url == "https://hit.com"

    def test_get_status(self, engine):
        """Test status report generation."""
        status = engine.get_status()
        assert isinstance(status, str)
        assert "Search Engine Status" in status or "Tier" in status

    @pytest.mark.asyncio
    async def test_search_empty_sources(self):
        """Test search when no sources are available."""
        engine = HybridSearchEngine()
        # Clear all sources
        engine.tier1_sources = {}
        engine.tier2_sources = {}
        engine.tier3_sources = {}

        result = await engine.search("test query")
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_search_cache_hit(self, engine):
        """Test that cached results are returned."""
        cached_result = SearchResult(query="cached", items=[])
        engine.cache.set("cached", cached_result)

        result = await engine.search("cached")
        assert result.cached is True


# ── Edge Cases and Error Handling ────────────────────────────────────

class TestHybridSearchEdgeCases:
    def test_search_item_empty_url(self):
        item = SearchItem(title="No URL", url="")
        assert item.url == ""
        assert item.domain == ""

    def test_search_item_invalid_url(self):
        item = SearchItem(title="Bad URL", url="not a url")
        # Should handle gracefully
        assert isinstance(item.domain, str)

    def test_tfidf_unicode_handling(self):
        """Test TF-IDF with unicode."""
        query = "中文查询"
        documents = ["中文文档一", "中文文档二"]
        scores = SimpleTFIDF.score(query, documents)
        assert len(scores) == 2

    def test_recency_boost_invalid_date(self):
        """Test recency boost with invalid date."""
        boost = compute_recency_boost("invalid date")
        assert boost == 1.0

    def test_search_cache_complex_query(self):
        """Test caching with complex query."""
        cache = SearchCache()
        query = "Fed rate decision impact on tech stocks Q2 2024"
        result = SearchResult(query=query)
        cache.set(query, result)

        cached = cache.get(query)
        assert cached is not None

    def test_query_expander_empty_string(self):
        """Test expanding empty query."""
        expander = QueryExpander()
        variants = expander.expand("")
        # Should handle gracefully
        assert len(variants) >= 1

    def test_search_result_timestamp(self):
        """Test that search result has timestamp."""
        result = SearchResult()
        assert result.timestamp is not None
        assert isinstance(result.timestamp, datetime)

    def test_search_item_special_characters_in_title(self):
        """Test search item with special characters."""
        item = SearchItem(
            title="Breaking: \"Stock\" Market & Economy",
            url="https://example.com",
        )
        assert len(item.title) > 0

    def test_conflict_report_empty_claims(self):
        """Test conflict report with no claims."""
        report = ConflictReport(entity="Test", claims=[])
        assert len(report.claims) == 0

    def test_search_result_large_items_list(self):
        """Test search result with many items."""
        items = [
            SearchItem(title=f"Item {i}", url=f"https://example.com/{i}")
            for i in range(1000)
        ]
        result = SearchResult(items=items)
        assert len(result.items) == 1000
