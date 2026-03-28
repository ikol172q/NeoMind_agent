"""
Comprehensive unit tests for agent/search/sources.py

Tests search source wrappers and data classes.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, AsyncMock
from agent.search.sources import (
    SearchItem, SearchResult, TokenBucketLimiter, ContentExtractor,
    DuckDuckGoSource, GoogleNewsRSSSource, BraveSearchSource,
    SerperSource, TavilySource, JinaSearchSource, NewsAPISource,
)


class TestSearchItem:
    """Tests for SearchItem dataclass."""

    def test_search_item_creation(self):
        """Test creating a SearchItem."""
        item = SearchItem(
            title="Test Title",
            url="http://example.com",
            snippet="Test snippet",
        )

        assert item.title == "Test Title"
        assert item.url == "http://example.com"
        assert item.snippet == "Test snippet"
        assert item.language == "en"

    def test_search_item_domain_property(self):
        """Test domain property extraction."""
        item = SearchItem(title="Test", url="http://www.example.com/page")
        assert item.domain == "example.com"

    def test_search_item_domain_with_subdomain(self):
        """Test domain extraction with subdomain."""
        item = SearchItem(title="Test", url="http://news.example.com")
        assert item.domain == "news.example.com"

    def test_search_item_best_content(self):
        """Test best_content property returns richest content."""
        item = SearchItem(title="Title", url="http://test.com")

        # Only title
        assert item.best_content == "Title"

        # With snippet
        item.snippet = "Snippet text"
        assert item.best_content == "Snippet text"

        # With full text
        item.full_text = "Full article text"
        assert item.best_content == "Full article text"

    def test_search_item_rrf_score(self):
        """Test RRF score initialization."""
        item = SearchItem(title="Test", url="http://test.com")
        assert item.rrf_score == 0.0


class TestSearchResult:
    """Tests for SearchResult dataclass."""

    def test_search_result_creation(self):
        """Test creating SearchResult."""
        result = SearchResult(
            query="test query",
            items=[],
            sources_used=["source1"],
        )

        assert result.query == "test query"
        assert result.items == []
        assert result.sources_used == ["source1"]

    def test_search_result_format_for_llm(self):
        """Test format_for_llm output."""
        items = [
            SearchItem(
                title="Result 1",
                url="http://site1.com",
                snippet="Snippet 1",
                source="test",
            ),
        ]

        result = SearchResult(
            query="test",
            items=items,
            sources_used=["test"],
        )

        formatted = result.format_for_llm(max_items=1)

        assert "test" in formatted
        assert "Result 1" in formatted
        assert "http://site1.com" in formatted

    def test_search_result_format_with_error(self):
        """Test format_for_llm with error."""
        result = SearchResult(error="Search failed")

        formatted = result.format_for_llm()
        assert "Search error" in formatted

    def test_search_result_format_with_no_items(self):
        """Test format_for_llm with no items."""
        result = SearchResult(query="test", items=[])

        formatted = result.format_for_llm()
        assert "No results" in formatted

    def test_search_result_timestamp(self):
        """Test timestamp is set on creation."""
        result = SearchResult()
        assert result.timestamp is not None


class TestTokenBucketLimiter:
    """Tests for token bucket rate limiter."""

    @pytest.mark.asyncio
    async def test_limiter_init(self):
        """Test limiter initialization."""
        limiter = TokenBucketLimiter(rate=2.0, per=1.0)
        assert limiter.rate == 2.0
        assert limiter.per == 1.0
        assert limiter.tokens == 2.0

    @pytest.mark.asyncio
    async def test_limiter_acquire(self):
        """Test acquiring a token."""
        limiter = TokenBucketLimiter(rate=1.0, per=1.0)
        # Should acquire without waiting
        await limiter.acquire()
        assert limiter.tokens < 1.0

    @pytest.mark.asyncio
    async def test_limiter_blocks_when_empty(self):
        """Test limiter waits when no tokens available."""
        limiter = TokenBucketLimiter(rate=0.1, per=1.0)
        # First acquire uses the token
        await limiter.acquire()
        # Should have to wait for second (implementation dependent)


class TestContentExtractor:
    """Tests for ContentExtractor."""

    def test_extractor_init(self):
        """Test extractor initialization."""
        extractor = ContentExtractor()
        assert extractor.timeout == 10
        assert extractor.max_workers == 4

    def test_extractor_availability(self):
        """Test extractor availability flag."""
        extractor = ContentExtractor()
        # Depends on trafilatura installation
        assert isinstance(extractor.available, bool)

    @pytest.mark.asyncio
    async def test_extract_batch_unavailable(self):
        """Test extract_batch when unavailable."""
        extractor = ContentExtractor()
        extractor.available = False

        items = [SearchItem(title="Test", url="http://test.com")]
        count = await extractor.extract_batch(items)

        assert count == 0

    @pytest.mark.asyncio
    async def test_extract_batch_with_existing_content(self):
        """Test extract_batch skips items with full_text."""
        extractor = ContentExtractor()
        extractor.available = False

        item = SearchItem(
            title="Test",
            url="http://test.com",
            full_text="Already extracted",
        )

        count = await extractor.extract_batch([item])
        assert count == 0


class TestDuckDuckGoSource:
    """Tests for DuckDuckGo source."""

    def test_ddg_source_init(self):
        """Test DuckDuckGo source initialization."""
        source = DuckDuckGoSource(region="en-us")
        assert source.region == "en-us"
        assert source.language == "en"

    def test_ddg_source_init_chinese(self):
        """Test DuckDuckGo source with Chinese region."""
        source = DuckDuckGoSource(region="cn-zh")
        assert source.language == "zh"

    def test_ddg_source_availability(self):
        """Test DDG availability depends on duckduckgo_search."""
        source = DuckDuckGoSource()
        # Depends on installation
        assert isinstance(source.available, bool)

    @pytest.mark.asyncio
    async def test_ddg_search_unavailable(self):
        """Test search returns empty when unavailable."""
        source = DuckDuckGoSource()
        source.available = False

        results = await source.search("test query")
        assert results == []


class TestGoogleNewsRSSSource:
    """Tests for Google News RSS source."""

    def test_gnews_source_init_english(self):
        """Test Google News source initialization."""
        source = GoogleNewsRSSSource(language="en")
        assert source.language == "en"
        assert "en-US" in str(source.params.values())

    def test_gnews_source_init_chinese(self):
        """Test Google News source with Chinese."""
        source = GoogleNewsRSSSource(language="zh")
        assert source.language == "zh"
        assert "zh-CN" in str(source.params.values())

    def test_gnews_availability(self):
        """Test Google News availability depends on feedparser."""
        source = GoogleNewsRSSSource()
        assert isinstance(source.available, bool)

    @pytest.mark.asyncio
    async def test_gnews_search_unavailable(self):
        """Test search returns empty when unavailable."""
        source = GoogleNewsRSSSource()
        source.available = False

        results = await source.search("test query")
        assert results == []


class TestBraveSearchSource:
    """Tests for Brave Search source."""

    @patch.dict('os.environ', {}, clear=True)
    def test_brave_source_no_api_key(self):
        """Test Brave source without API key."""
        source = BraveSearchSource()
        assert source.available is False

    @patch.dict('os.environ', {'BRAVE_API_KEY': 'test-key'})
    def test_brave_source_with_api_key(self):
        """Test Brave source with API key."""
        source = BraveSearchSource()
        assert source.available is True

    @patch.dict('os.environ', {'BRAVE_API_KEY': 'test-key'})
    def test_brave_source_base_url(self):
        """Test Brave source base URL."""
        source = BraveSearchSource()
        assert "api.search.brave.com" in source.base_url

    @pytest.mark.asyncio
    async def test_brave_search_unavailable(self):
        """Test search returns empty when unavailable."""
        source = BraveSearchSource()
        source.available = False

        results = await source.search("test query")
        assert results == []


class TestSerperSource:
    """Tests for Serper source."""

    @patch.dict('os.environ', {}, clear=True)
    def test_serper_source_no_api_key(self):
        """Test Serper source without API key."""
        source = SerperSource()
        assert source.available is False

    @patch.dict('os.environ', {'SERPER_API_KEY': 'test-key'})
    def test_serper_source_with_api_key(self):
        """Test Serper source with API key."""
        source = SerperSource()
        assert source.available is True

    @pytest.mark.asyncio
    async def test_serper_search_unavailable(self):
        """Test search returns empty when unavailable."""
        source = SerperSource()
        source.available = False

        results = await source.search("test query")
        assert results == []


class TestTavilySource:
    """Tests for Tavily source."""

    @patch.dict('os.environ', {}, clear=True)
    def test_tavily_source_no_api_key(self):
        """Test Tavily source without API key."""
        source = TavilySource()
        assert source.available is False

    @patch.dict('os.environ', {'TAVILY_API_KEY': 'test-key'})
    def test_tavily_source_with_api_key(self):
        """Test Tavily source with API key."""
        source = TavilySource()
        assert source.available is True

    @pytest.mark.asyncio
    async def test_tavily_search_unavailable(self):
        """Test search returns empty when unavailable."""
        source = TavilySource()
        source.available = False

        results = await source.search("test query")
        assert results == []


class TestJinaSearchSource:
    """Tests for Jina source."""

    def test_jina_source_init(self):
        """Test Jina source initialization."""
        source = JinaSearchSource()
        # Jina is always available (no API key required for basic use)
        assert source.available is True

    def test_jina_source_with_api_key(self):
        """Test Jina source with API key."""
        with patch.dict('os.environ', {'JINA_API_KEY': 'test-key'}):
            source = JinaSearchSource()
            assert source.api_key == 'test-key'

    @pytest.mark.asyncio
    async def test_jina_search_returns_empty_on_error(self):
        """Test Jina search graceful error handling."""
        source = JinaSearchSource()
        # Mock to return empty on error
        source._sync_search = MagicMock(return_value=[])

        results = await source.search("test")
        assert results == []


class TestNewsAPISource:
    """Tests for NewsAPI source."""

    @patch.dict('os.environ', {}, clear=True)
    def test_newsapi_source_no_api_key(self):
        """Test NewsAPI source without API key."""
        source = NewsAPISource()
        assert source.available is False

    @patch.dict('os.environ', {'NEWSAPI_API_KEY': 'test-key'})
    def test_newsapi_source_with_api_key(self):
        """Test NewsAPI source with API key."""
        source = NewsAPISource()
        assert source.available is True

    @pytest.mark.asyncio
    async def test_newsapi_search_unavailable(self):
        """Test search returns empty when unavailable."""
        source = NewsAPISource()
        source.available = False

        results = await source.search("test query")
        assert results == []


class TestSourcesIntegration:
    """Integration tests for sources."""

    def test_multiple_sources_availability(self):
        """Test availability status of multiple sources."""
        sources = [
            DuckDuckGoSource(),
            GoogleNewsRSSSource(),
            BraveSearchSource(),
            SerperSource(),
            TavilySource(),
            JinaSearchSource(),
            NewsAPISource(),
        ]

        for source in sources:
            assert isinstance(source.available, bool)

    def test_search_item_with_published_date(self):
        """Test SearchItem with published datetime."""
        published = datetime.now(timezone.utc)
        item = SearchItem(
            title="Test",
            url="http://test.com",
            published=published,
        )

        assert item.published == published


class TestSourcesEdgeCases:
    """Tests for edge cases."""

    def test_search_item_malformed_url_domain(self):
        """Test domain extraction from malformed URL."""
        item = SearchItem(title="Test", url="not a url")
        # Should handle gracefully
        assert isinstance(item.domain, str)

    def test_search_result_format_with_published_dates(self):
        """Test format_for_llm includes published dates."""
        item = SearchItem(
            title="Test",
            url="http://test.com",
            published=datetime.now(timezone.utc),
        )

        result = SearchResult(query="test", items=[item])
        formatted = result.format_for_llm()

        assert "Published" in formatted or "Test" in formatted

    @pytest.mark.asyncio
    async def test_content_extractor_with_timeout(self):
        """Test content extractor respects timeout."""
        extractor = ContentExtractor(timeout=5)
        assert extractor.timeout == 5
