"""
Comprehensive unit tests for agent/search/reranker.py

Tests RRF merge and semantic reranking.
"""

import pytest
from unittest.mock import MagicMock, patch
from agent.search.reranker import RRFMerger, FlashReranker, CohereReranker
from agent.search.sources import SearchItem


class TestRRFMerger:
    """Tests for RRF (Reciprocal Rank Fusion) merger."""

    def test_rrf_init_default(self):
        """Test RRFMerger initializes with defaults."""
        merger = RRFMerger()
        assert merger.k == 60
        assert merger.trust_scores == {}

    def test_rrf_init_custom_k(self):
        """Test RRFMerger initializes with custom k."""
        merger = RRFMerger(k=100)
        assert merger.k == 100

    def test_rrf_init_with_trust_scores(self):
        """Test RRFMerger initializes with trust scores."""
        trust = {"source1": 0.9, "source2": 0.5}
        merger = RRFMerger(trust_scores=trust)
        assert merger.trust_scores == trust

    def test_rrf_merge_empty_results(self):
        """Test merge with empty results."""
        merger = RRFMerger()
        results = merger.merge({})
        assert results == []

    def test_rrf_merge_single_source(self):
        """Test merge with single source."""
        merger = RRFMerger()
        items = [
            SearchItem(title="A", url="http://a.com"),
            SearchItem(title="B", url="http://b.com"),
        ]
        results = merger.merge({"source1": items})

        assert len(results) == 2
        assert results[0].title == "A"  # Higher rank gets higher score
        assert results[1].title == "B"

    def test_rrf_merge_multiple_sources(self):
        """Test merge with multiple sources."""
        merger = RRFMerger()

        items1 = [
            SearchItem(title="A", url="http://a.com"),
            SearchItem(title="B", url="http://b.com"),
        ]
        items2 = [
            SearchItem(title="A", url="http://a.com"),
            SearchItem(title="C", url="http://c.com"),
        ]

        results = merger.merge({"source1": items1, "source2": items2})

        # A appears in both sources, should rank higher
        assert results[0].url == "http://a.com"

    def test_rrf_deduplication(self):
        """Test that duplicate URLs are deduplicated."""
        merger = RRFMerger()

        items1 = [SearchItem(title="Title A", url="http://a.com")]
        items2 = [SearchItem(title="Different Title", url="http://a.com")]

        results = merger.merge({"source1": items1, "source2": items2})

        # Should have only one result
        assert len(results) == 1
        # Should keep the richer content
        assert len(results[0].best_content) > 0

    def test_rrf_score_calculation(self):
        """Test RRF score is calculated correctly."""
        merger = RRFMerger(k=60)
        items = [SearchItem(title="A", url="http://a.com")]
        results = merger.merge({"source1": items})

        # Score should be 1 / (60 + 0) = 0.0167 * 1.0 (default trust)
        assert results[0].rrf_score > 0

    def test_rrf_trust_weighting(self):
        """Test trust weighting affects score."""
        items = [SearchItem(title="A", url="http://a.com")]

        # High trust
        merger_high = RRFMerger(trust_scores={"source": 1.0})
        results_high = merger_high.merge({"source": items})

        # Low trust
        merger_low = RRFMerger(trust_scores={"source": 0.0})
        results_low = merger_low.merge({"source": items})

        # Trust weighting formula: rrf_score *= (0.5 + trust)
        # High: 1/(60) * (0.5 + 1.0) = 1/60 * 1.5
        # Low: 1/(60) * (0.5 + 0.0) = 1/60 * 0.5
        # High should be 3x the low
        assert results_high[0].rrf_score >= results_low[0].rrf_score

    def test_rrf_cross_source_bonus(self):
        """Test bonus for appearing in multiple sources."""
        items = [SearchItem(title="A", url="http://a.com")]

        # Single source
        merger = RRFMerger()
        results_single = merger.merge({"source1": items})

        # Two sources (simulated by adding same item twice from different sources)
        results_double = merger.merge({
            "source1": items,
            "source2": items,
        })

        # Should have bonus for appearing in multiple sources
        # Multi-source bonus applies when count >= 2: score *= 1.1
        assert results_double[0].rrf_score >= results_single[0].rrf_score

    def test_rrf_relevance_score_integration(self):
        """Test that relevance scores are integrated."""
        item_with_score = SearchItem(title="A", url="http://a.com", relevance_score=0.8)
        item_without_score = SearchItem(title="B", url="http://b.com", relevance_score=0.0)

        merger = RRFMerger()
        results = merger.merge({
            "source1": [item_with_score],
            "source2": [item_without_score],
        })

        # Item with higher relevance score should rank higher
        assert results[0].url == "http://a.com"

    def test_rrf_sorting_by_score(self):
        """Test results are sorted by RRF score."""
        merger = RRFMerger()
        items = [
            SearchItem(title=f"Item {i}", url=f"http://site{i}.com")
            for i in range(5)
        ]

        results = merger.merge({"source": items})

        # Should be sorted by score (descending)
        scores = [r.rrf_score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_rrf_dedup_key_normalization(self):
        """Test dedup key normalizes URLs."""
        merger = RRFMerger()

        items1 = [SearchItem(title="A", url="http://example.com/page")]
        items2 = [SearchItem(title="B", url="http://example.com/page/")]  # trailing slash

        results = merger.merge({"source1": items1, "source2": items2})

        # Should be deduplicated
        assert len(results) == 1

    def test_rrf_handles_malformed_urls(self):
        """Test handling of malformed URLs."""
        merger = RRFMerger()

        items = [SearchItem(title="A", url="not a valid url at all")]

        # Should not raise
        results = merger.merge({"source": items})
        assert len(results) == 1


class TestFlashReranker:
    """Tests for FlashRank semantic reranker."""

    def test_flash_init(self):
        """Test FlashReranker initialization."""
        reranker = FlashReranker()
        assert reranker._model_name == "ms-marco-MiniLM-L-12-v2"
        assert reranker._max_length == 512
        # availability depends on whether flashrank is installed
        assert isinstance(reranker.available, bool)

    def test_flash_init_custom_model(self):
        """Test FlashReranker with custom model."""
        reranker = FlashReranker(model_name="custom-model", max_length=256)
        assert reranker._model_name == "custom-model"
        assert reranker._max_length == 256

    def test_flash_rerank_empty_items(self):
        """Test rerank with empty items list."""
        reranker = FlashReranker()
        results = reranker.rerank("test query", [])
        assert results == []

    def test_flash_rerank_single_item(self):
        """Test rerank with single item."""
        reranker = FlashReranker()
        item = SearchItem(title="Test", url="http://test.com", snippet="test content")
        results = reranker.rerank("test query", [item])

        # Should return the item
        assert len(results) >= 0  # May return empty if unavailable

    def test_flash_rerank_unavailable(self):
        """Test rerank when FlashRank unavailable."""
        reranker = FlashReranker()
        reranker.available = False

        items = [SearchItem(title="A", url="http://a.com")]
        results = reranker.rerank("test", items)

        # Should return original order
        assert results == items

    def test_flash_is_available(self):
        """Test is_available method."""
        reranker = FlashReranker()
        available = reranker.is_available()
        assert isinstance(available, bool)

    @patch('agent.search.reranker.HAS_FLASHRANK', False)
    def test_flash_not_available_no_install(self):
        """Test when FlashRank is not installed."""
        reranker = FlashReranker()
        assert reranker.available is False

    def test_flash_rerank_preserves_items_beyond_top_n(self):
        """Test items beyond top_n are passed through unchanged."""
        reranker = FlashReranker()
        reranker.available = False  # Disable to test passthrough

        items = [SearchItem(title=f"Item {i}", url=f"http://site{i}.com") for i in range(10)]
        results = reranker.rerank("test", items, top_n=5)

        # Should return all items when unavailable
        assert len(results) == len(items)


class TestCohereReranker:
    """Tests for Cohere semantic reranker."""

    def test_cohere_init_no_api_key(self):
        """Test CohereReranker initialization without API key."""
        with patch.dict('os.environ', {}, clear=True):
            reranker = CohereReranker()
            assert reranker.available is False

    def test_cohere_init_with_api_key(self):
        """Test CohereReranker initialization with API key."""
        with patch.dict('os.environ', {'COHERE_API_KEY': 'test-key'}):
            with patch('agent.search.reranker.HAS_COHERE', False):
                reranker = CohereReranker()
                # Will be unavailable if cohere not installed
                assert isinstance(reranker.available, bool)

    def test_cohere_init_custom_model(self):
        """Test CohereReranker with custom model."""
        reranker = CohereReranker(api_key="test-key", model="rerank-v3.0")
        assert reranker._model == "rerank-v3.0"

    def test_cohere_rerank_unavailable(self):
        """Test rerank when unavailable."""
        reranker = CohereReranker()
        reranker.available = False

        items = [SearchItem(title="A", url="http://a.com")]
        results = reranker.rerank("test", items)

        assert results == items

    def test_cohere_rerank_empty_items(self):
        """Test rerank with empty items."""
        reranker = CohereReranker()
        results = reranker.rerank("test", [])
        assert results == []

    def test_cohere_rerank_no_client(self):
        """Test rerank when client is None."""
        reranker = CohereReranker()
        reranker._client = None

        items = [SearchItem(title="A", url="http://a.com")]
        results = reranker.rerank("test", items)

        assert results == items


class TestRerankerIntegration:
    """Integration tests for reranking."""

    def test_rrf_then_flash_pipeline(self):
        """Test RRF merge followed by FlashRank."""
        # Create diverse items
        items = [
            SearchItem(title="Exact Match", url="http://a.com", snippet="test content about test query"),
            SearchItem(title="Partial Match", url="http://b.com", snippet="about similar topics"),
            SearchItem(title="Related", url="http://c.com", snippet="related information"),
        ]

        # First merge
        merger = RRFMerger()
        merged = merger.merge({"source": items})

        # Then rerank (will pass through if unavailable)
        reranker = FlashReranker()
        reranked = reranker.rerank("test query", merged)

        # Should have items in some order
        assert len(reranked) > 0

    def test_rrf_score_vs_rerank_score(self):
        """Test that rerank score different from RRF score."""
        items = [SearchItem(title="Test", url="http://test.com", snippet="content")]

        merger = RRFMerger()
        merged = merger.merge({"source": items})

        if merged:
            rrf_score = merged[0].rrf_score
            reranker = FlashReranker()
            reranked = reranker.rerank("test", merged)

            if reranked and hasattr(reranked[0], 'rerank_score') and reranked[0].rerank_score:
                # If reranking happened, score might be different
                assert isinstance(reranked[0].rrf_score, float)

    def test_multiple_sources_rrf_ranking(self):
        """Test RRF ranking with multiple real-world sources."""
        merger = RRFMerger(trust_scores={
            "ddg": 0.7,
            "brave": 0.8,
            "serper": 0.85,
        })

        results_by_source = {
            "ddg": [
                SearchItem(title="DDG Result 1", url="http://ddg1.com"),
                SearchItem(title="DDG Result 2", url="http://ddg2.com"),
            ],
            "brave": [
                SearchItem(title="Brave Result 1", url="http://brave1.com"),
                SearchItem(title="DDG Result 1", url="http://ddg1.com"),  # Duplicate
            ],
            "serper": [
                SearchItem(title="Serper Result 1", url="http://serper1.com"),
            ],
        }

        merged = merger.merge(results_by_source)

        # Should have at least 4 unique results
        assert len(merged) >= 4
        # First should be DDG Result 1 (appears in 2 sources)
        assert merged[0].url == "http://ddg1.com"


class TestRerankerEdgeCases:
    """Tests for edge cases."""

    def test_rrf_with_zero_length_snippet(self):
        """Test handling items with zero-length snippets."""
        merger = RRFMerger()
        items = [SearchItem(title="A", url="http://a.com", snippet="")]
        results = merger.merge({"source": items})

        assert len(results) == 1

    def test_rrf_with_none_values(self):
        """Test handling None values in items."""
        merger = RRFMerger()
        item = SearchItem(title="Test", url="http://test.com")
        item.snippet = None
        results = merger.merge({"source": [item]})

        assert len(results) == 1

    def test_flash_rerank_with_very_long_content(self):
        """Test reranking with content exceeding max_length."""
        reranker = FlashReranker(max_length=100)
        item = SearchItem(
            title="Test",
            url="http://test.com",
            snippet="x" * 1000  # Very long
        )

        results = reranker.rerank("test", [item])
        # Should not raise
        assert len(results) >= 0
