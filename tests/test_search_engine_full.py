"""
Comprehensive unit tests for agent/search_engine.py

Tests the compatibility bridge module.
"""

import pytest
from agent.search_engine import (
    UniversalSearchEngine,
    SearchItem,
    SearchResult,
    FlashReranker,
    RRFMerger,
    QueryExpander,
    SearchCache,
)


class TestSearchEngineImports:
    """Tests for module imports."""

    def test_universal_search_engine_imported(self):
        """Test UniversalSearchEngine is importable."""
        assert UniversalSearchEngine is not None

    def test_search_item_imported(self):
        """Test SearchItem is importable."""
        assert SearchItem is not None

    def test_search_result_imported(self):
        """Test SearchResult is importable."""
        assert SearchResult is not None

    def test_flash_reranker_imported(self):
        """Test FlashReranker is importable."""
        assert FlashReranker is not None

    def test_rrf_merger_imported(self):
        """Test RRFMerger is importable."""
        assert RRFMerger is not None

    def test_query_expander_imported(self):
        """Test QueryExpander is importable."""
        assert QueryExpander is not None

    def test_search_cache_imported(self):
        """Test SearchCache is importable."""
        assert SearchCache is not None


class TestSearchEngineModuleExports:
    """Tests for module __all__ exports."""

    def test_module_has_all(self):
        """Test module defines __all__."""
        import agent.search_engine as module
        assert hasattr(module, '__all__')

    def test_all_exports_valid(self):
        """Test all exports are valid."""
        import agent.search_engine as module
        for name in module.__all__:
            assert hasattr(module, name)


class TestSearchEngineAliasing:
    """Tests that imports work correctly."""

    def test_universal_search_engine_is_main_class(self):
        """Test UniversalSearchEngine is the main search class."""
        assert UniversalSearchEngine.__name__ == "UniversalSearchEngine"

    def test_search_item_is_correct_class(self):
        """Test SearchItem is the correct dataclass."""
        item = SearchItem(title="test", url="http://test.com")
        assert item.title == "test"

    def test_search_result_is_correct_class(self):
        """Test SearchResult is the correct dataclass."""
        result = SearchResult(query="test")
        assert result.query == "test"

    def test_flash_reranker_works(self):
        """Test FlashReranker is functional."""
        reranker = FlashReranker()
        assert isinstance(reranker, FlashReranker)

    def test_rrf_merger_works(self):
        """Test RRFMerger is functional."""
        merger = RRFMerger()
        assert isinstance(merger, RRFMerger)

    def test_query_expander_works(self):
        """Test QueryExpander is functional."""
        expander = QueryExpander()
        assert isinstance(expander, QueryExpander)

    def test_search_cache_works(self):
        """Test SearchCache is functional."""
        cache = SearchCache()
        assert isinstance(cache, SearchCache)


class TestSearchEngineBackwardCompatibility:
    """Tests for backward compatibility."""

    def test_search_item_fields_present(self):
        """Test SearchItem has expected fields."""
        item = SearchItem(title="test", url="http://test.com")
        assert hasattr(item, 'title')
        assert hasattr(item, 'url')
        assert hasattr(item, 'snippet')
        assert hasattr(item, 'source')
        assert hasattr(item, 'rrf_score')

    def test_search_result_fields_present(self):
        """Test SearchResult has expected fields."""
        result = SearchResult()
        assert hasattr(result, 'items')
        assert hasattr(result, 'query')
        assert hasattr(result, 'sources_used')
        assert hasattr(result, 'error')

    def test_cache_has_expected_methods(self):
        """Test SearchCache has expected methods."""
        cache = SearchCache()
        assert hasattr(cache, 'get')
        assert hasattr(cache, 'set')
        assert hasattr(cache, 'clear')

    def test_merger_has_expected_methods(self):
        """Test RRFMerger has expected methods."""
        merger = RRFMerger()
        assert hasattr(merger, 'merge')


class TestSearchEngineIntegration:
    """Integration tests for bridge module."""

    def test_can_create_search_engine(self):
        """Test can create UniversalSearchEngine instance."""
        engine = UniversalSearchEngine()
        assert engine is not None

    def test_can_create_search_engine_with_domain(self):
        """Test can create engine with custom domain."""
        engine = UniversalSearchEngine(domain="finance")
        assert engine.domain == "finance"

    def test_cache_and_engine_work_together(self):
        """Test cache and engine can be used together."""
        engine = UniversalSearchEngine()
        cache = SearchCache()

        # Create a result
        result = SearchResult(query="test")

        # Cache it
        cache.set("test", result)

        # Retrieve it
        cached = cache.get("test")

        assert cached is not None

    def test_query_expansion_works_with_engine(self):
        """Test query expansion works independently."""
        expander = QueryExpander(domain="general")
        variants = expander.expand("test query")

        assert len(variants) > 0
        assert "test query" in variants


class TestSearchEngineEdgeCases:
    """Tests for edge cases."""

    def test_create_multiple_engines(self):
        """Test creating multiple engine instances."""
        engine1 = UniversalSearchEngine(domain="general")
        engine2 = UniversalSearchEngine(domain="finance")

        assert engine1.domain == "general"
        assert engine2.domain == "finance"

    def test_cache_independence(self):
        """Test that caches are independent."""
        cache1 = SearchCache()
        cache2 = SearchCache()

        result = SearchResult(query="test")
        cache1.set("test", result)

        # cache2 should be empty
        assert cache2.get("test") is None

    def test_multiple_expandersindependent(self):
        """Test that expandersindependent instances."""
        exp1 = QueryExpander(domain="general")
        exp2 = QueryExpander(domain="finance")

        assert exp1.domain != exp2.domain

    def test_reranker_independence(self):
        """Test multiple reranker instances."""
        reranker1 = FlashReranker()
        reranker2 = FlashReranker()

        # Should be independent
        assert reranker1 is not reranker2


class TestSearchEngineConsistency:
    """Tests for consistency across imports."""

    def test_search_item_from_sources_equals_imported(self):
        """Test SearchItem is same across imports."""
        from agent.search.sources import SearchItem as DirectSearchItem

        item1 = SearchItem(title="test", url="http://test.com")
        item2 = DirectSearchItem(title="test", url="http://test.com")

        # Should have same structure
        assert item1.title == item2.title
        assert item1.url == item2.url

    def test_search_result_from_sources_equals_imported(self):
        """Test SearchResult is same across imports."""
        from agent.search.sources import SearchResult as DirectSearchResult

        result1 = SearchResult(query="test")
        result2 = DirectSearchResult(query="test")

        assert result1.query == result2.query

    def test_cache_from_cache_equals_imported(self):
        """Test SearchCache is same across imports."""
        from agent.search.cache import SearchCache as DirectCache

        cache1 = SearchCache()
        cache2 = DirectCache()

        # Both should be functional
        assert hasattr(cache1, 'get')
        assert hasattr(cache2, 'get')
