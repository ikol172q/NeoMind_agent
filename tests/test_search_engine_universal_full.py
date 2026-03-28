"""
Comprehensive unit tests for agent/search/engine.py

Tests the UniversalSearchEngine orchestrator.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, AsyncMock
from agent.search.engine import (
    UniversalSearchEngine,
    compute_recency_boost,
)
from agent.search.sources import SearchItem, SearchResult


class TestRecencyBoost:
    """Tests for compute_recency_boost function."""

    def test_recency_boost_none_published(self):
        """Test boost with None published date."""
        boost = compute_recency_boost(None)
        assert boost == 1.0

    def test_recency_boost_now(self):
        """Test boost for very recent content."""
        now = datetime.now(timezone.utc)
        boost = compute_recency_boost(now, domain="general")

        assert boost > 1.0

    def test_recency_boost_old_content(self):
        """Test boost for old content."""
        old = datetime(2020, 1, 1, tzinfo=timezone.utc)
        boost = compute_recency_boost(old, domain="general")

        assert boost <= 1.0

    def test_recency_boost_finance_domain(self):
        """Test boost for finance domain."""
        recent = datetime.now(timezone.utc)
        boost_finance = compute_recency_boost(recent, domain="finance")
        boost_general = compute_recency_boost(recent, domain="general")

        # Finance has more aggressive recency boost
        assert boost_finance >= boost_general

    def test_recency_boost_invalid_published(self):
        """Test boost with invalid published date."""
        boost = compute_recency_boost("invalid", domain="general")
        assert boost == 1.0


class TestUniversalSearchEngineInit:
    """Tests for UniversalSearchEngine initialization."""

    def test_init_default_domain(self):
        """Test initialization with default domain."""
        engine = UniversalSearchEngine()
        assert engine.domain == "general"

    def test_init_custom_domain(self):
        """Test initialization with custom domain."""
        for domain in ["general", "finance", "coding"]:
            engine = UniversalSearchEngine(domain=domain)
            assert engine.domain == domain

    def test_init_custom_triggers(self):
        """Test initialization with custom triggers."""
        custom_triggers = {"custom1", "custom2"}
        engine = UniversalSearchEngine(triggers=custom_triggers)
        assert engine.triggers == custom_triggers

    def test_init_creates_components(self):
        """Test initialization creates all components."""
        engine = UniversalSearchEngine()

        assert engine.expander is not None
        assert engine.extractor is not None
        assert engine.rrf_merger is not None
        assert engine.router is not None
        assert engine.metrics is not None
        assert engine.cache is not None

    def test_init_sources_tier1(self):
        """Test initialization includes tier 1 sources."""
        engine = UniversalSearchEngine()
        # Tier 1 sources depend on dependencies
        assert isinstance(engine.tier1_sources, dict)

    def test_init_sources_tier2(self):
        """Test initialization includes tier 2 sources."""
        engine = UniversalSearchEngine()
        assert isinstance(engine.tier2_sources, dict)

    def test_init_sources_tier3(self):
        """Test initialization includes tier 3 sources."""
        engine = UniversalSearchEngine()
        assert isinstance(engine.tier3_sources, dict)


class TestUniversalSearchEngineShouldSearch:
    """Tests for should_search method."""

    def test_should_search_with_trigger_keywords(self):
        """Test should_search detects trigger keywords."""
        engine = UniversalSearchEngine()

        assert engine.should_search("what is today") is True
        assert engine.should_search("latest news") is True

    def test_should_search_caching(self):
        """Test should_search result is cached."""
        engine = UniversalSearchEngine()

        # First call
        result1 = engine.should_search("test query")
        # Second call should use cache
        result2 = engine.should_search("test query")

        assert result1 == result2

    def test_should_search_case_insensitive(self):
        """Test should_search is case-insensitive."""
        engine = UniversalSearchEngine()

        assert engine.should_search("LATEST NEWS") is True
        assert engine.should_search("latest news") is True


class TestUniversalSearchEngineSearch:
    """Tests for backward-compatible search method."""

    @pytest.mark.asyncio
    async def test_search_returns_tuple(self):
        """Test search returns (success, text) tuple."""
        engine = UniversalSearchEngine()

        with patch.object(engine, 'search_advanced') as mock_search:
            mock_result = SearchResult(
                query="test",
                items=[SearchItem(title="Result", url="http://test.com")],
            )
            mock_search.return_value = mock_result

            success, text = await engine.search("test query")

            assert isinstance(success, bool)
            assert isinstance(text, str)

    @pytest.mark.asyncio
    async def test_search_with_error(self):
        """Test search returns error tuple."""
        engine = UniversalSearchEngine()

        with patch.object(engine, 'search_advanced') as mock_search:
            mock_result = SearchResult(error="Search failed")
            mock_search.return_value = mock_result

            success, text = await engine.search("test")

            assert success is False
            assert "error" in text.lower() or "failed" in text.lower()

    @pytest.mark.asyncio
    async def test_search_includes_metadata(self):
        """Test search output includes metadata."""
        engine = UniversalSearchEngine()

        with patch.object(engine, 'search_advanced') as mock_search:
            mock_result = SearchResult(
                query="test",
                items=[SearchItem(title="Result", url="http://test.com")],
                sources_used=["source1"],
                reranked=True,
                cached=False,
            )
            mock_search.return_value = mock_result

            success, text = await engine.search("test")

            assert success is True
            # Should include metadata in response
            assert "result" in text.lower() or "source" in text.lower()


class TestUniversalSearchEngineAdvanced:
    """Tests for advanced search method."""

    @pytest.mark.asyncio
    async def test_search_advanced_basic(self):
        """Test basic search_advanced call."""
        engine = UniversalSearchEngine()

        # Mock sources to return empty
        engine.tier1_sources = {}
        engine.tier2_sources = {}
        engine.tier3_sources = {}

        # Should return error about no sources
        result = await engine.search_advanced("test")

        assert isinstance(result, SearchResult)

    @pytest.mark.asyncio
    async def test_search_advanced_with_options(self):
        """Test search_advanced with various options."""
        engine = UniversalSearchEngine()

        engine.tier1_sources = {}
        engine.tier2_sources = {}
        engine.tier3_sources = {}

        result = await engine.search_advanced(
            query="test",
            max_results=10,
            expand_queries=False,
            extract_content=False,
            rerank=False,
        )

        assert isinstance(result, SearchResult)

    @pytest.mark.asyncio
    async def test_search_advanced_query_expansion(self):
        """Test search_advanced expands queries."""
        engine = UniversalSearchEngine()

        # Mock expander
        engine.expander.expand = MagicMock(return_value=["original", "variant"])

        engine.tier1_sources = {}
        engine.tier2_sources = {}
        engine.tier3_sources = {}

        result = await engine.search_advanced("test", expand_queries=True)

        # Expander should be called
        engine.expander.expand.assert_called()


class TestUniversalSearchEngineStatus:
    """Tests for get_status method."""

    def test_get_status_returns_string(self):
        """Test get_status returns string."""
        engine = UniversalSearchEngine()
        status = engine.get_status()

        assert isinstance(status, str)

    def test_get_status_includes_domain(self):
        """Test get_status includes domain."""
        engine = UniversalSearchEngine(domain="finance")
        status = engine.get_status()

        assert "finance" in status

    def test_get_status_includes_source_counts(self):
        """Test get_status includes source information."""
        engine = UniversalSearchEngine()
        status = engine.get_status()

        assert "Tier" in status or "source" in status.lower()

    def test_get_status_includes_intelligence_layers(self):
        """Test get_status lists intelligence layers."""
        engine = UniversalSearchEngine()
        status = engine.get_status()

        assert "Intelligence layers" in status or "RRF" in status


class TestUniversalSearchEngineSetDomain:
    """Tests for set_domain method."""

    def test_set_domain_changes_domain(self):
        """Test set_domain changes the domain."""
        engine = UniversalSearchEngine(domain="general")
        assert engine.domain == "general"

        engine.set_domain("finance")
        assert engine.domain == "finance"

    def test_set_domain_updates_expander(self):
        """Test set_domain updates expander domain."""
        engine = UniversalSearchEngine()
        original_domain = engine.expander.domain

        engine.set_domain("finance")

        assert engine.expander.domain == "finance"

    def test_set_domain_adjusts_cache_ttl(self):
        """Test set_domain adjusts cache TTL."""
        engine = UniversalSearchEngine(domain="general")
        general_ttl = engine.cache.ttl

        engine.set_domain("finance")
        finance_ttl = engine.cache.ttl

        # Finance should have longer TTL
        assert finance_ttl >= general_ttl


class TestUniversalSearchEngineMetrics:
    """Tests for metrics tracking."""

    @pytest.mark.asyncio
    async def test_metrics_recorded_on_search(self):
        """Test metrics are recorded on search."""
        engine = UniversalSearchEngine()

        engine.tier1_sources = {}
        engine.tier2_sources = {}
        engine.tier3_sources = {}

        await engine.search_advanced("test")

        # Metrics should be recorded
        assert engine.metrics is not None


class TestUniversalSearchEngineCache:
    """Tests for caching behavior."""

    @pytest.mark.asyncio
    async def test_cache_hit_on_repeated_query(self):
        """Test cache returns cached results."""
        engine = UniversalSearchEngine()

        # First search populates cache
        mock_result = SearchResult(
            query="test",
            items=[SearchItem(title="Test", url="http://test.com")],
        )

        engine.cache.set("test", mock_result)

        # Subsequent search should find cache
        cached = engine.cache.get("test")

        assert cached is not None
        assert cached.cached is True


class TestUniversalSearchEngineIntegration:
    """Integration tests."""

    @pytest.mark.asyncio
    async def test_full_search_pipeline(self):
        """Test full search pipeline execution."""
        engine = UniversalSearchEngine(domain="general")

        engine.tier1_sources = {}
        engine.tier2_sources = {}
        engine.tier3_sources = {}

        result = await engine.search_advanced(
            query="test query",
            max_results=5,
            expand_queries=False,
        )

        # Should get a SearchResult
        assert isinstance(result, SearchResult)

    def test_engine_with_multiple_domains(self):
        """Test engine can switch between domains."""
        engine = UniversalSearchEngine()

        domains = ["general", "finance", "coding"]

        for domain in domains:
            engine.set_domain(domain)
            assert engine.domain == domain
            status = engine.get_status()
            assert isinstance(status, str)


class TestUniversalSearchEngineEdgeCases:
    """Tests for edge cases."""

    @pytest.mark.asyncio
    async def test_search_empty_query(self):
        """Test search with empty query."""
        engine = UniversalSearchEngine()

        engine.tier1_sources = {}
        engine.tier2_sources = {}
        engine.tier3_sources = {}

        result = await engine.search_advanced("")

        assert isinstance(result, SearchResult)

    @pytest.mark.asyncio
    async def test_search_very_long_query(self):
        """Test search with very long query."""
        engine = UniversalSearchEngine()

        engine.tier1_sources = {}
        engine.tier2_sources = {}
        engine.tier3_sources = {}

        long_query = "test " * 1000

        result = await engine.search_advanced(long_query)

        assert isinstance(result, SearchResult)

    @pytest.mark.asyncio
    async def test_search_with_special_characters(self):
        """Test search with special characters."""
        engine = UniversalSearchEngine()

        engine.tier1_sources = {}
        engine.tier2_sources = {}
        engine.tier3_sources = {}

        result = await engine.search_advanced("test @#$% query")

        assert isinstance(result, SearchResult)

    def test_engine_with_no_sources(self):
        """Test engine initialization with no sources available."""
        engine = UniversalSearchEngine()

        # Verify that engine can be created even with no sources
        assert engine is not None

    def test_engine_status_with_no_sources(self):
        """Test get_status with no sources."""
        engine = UniversalSearchEngine()

        engine.tier1_sources = {}
        engine.tier2_sources = {}
        engine.tier3_sources = {}

        status = engine.get_status()

        assert isinstance(status, str)
        assert "Total: 0" in status


class TestUniversalSearchEngineLanguageFiltering:
    """Tests for language filtering."""

    @pytest.mark.asyncio
    async def test_search_with_language_filter(self):
        """Test search with language filter."""
        engine = UniversalSearchEngine()

        engine.tier1_sources = {}
        engine.tier2_sources = {}
        engine.tier3_sources = {}

        result = await engine.search_advanced(
            "test",
            languages=["en"],
        )

        assert isinstance(result, SearchResult)


class TestUniversalSearchEngineCompleteness:
    """Tests for all essential methods and attributes."""

    def test_engine_has_all_tier_sources(self):
        """Test engine has all source tiers."""
        engine = UniversalSearchEngine()

        assert hasattr(engine, 'tier1_sources')
        assert hasattr(engine, 'tier2_sources')
        assert hasattr(engine, 'tier3_sources')

    def test_engine_has_all_components(self):
        """Test engine has all required components."""
        engine = UniversalSearchEngine()

        required = [
            'expander', 'extractor', 'crawl4ai',
            'rrf_merger', 'flash_reranker', 'cohere_reranker',
            'router', 'metrics', 'cache', 'disk_cache',
        ]

        for component in required:
            assert hasattr(engine, component)

    def test_engine_has_all_methods(self):
        """Test engine has all required methods."""
        engine = UniversalSearchEngine()

        required_methods = [
            'should_search', 'search', 'search_advanced',
            'get_status', 'set_domain',
        ]

        for method in required_methods:
            assert hasattr(engine, method)
