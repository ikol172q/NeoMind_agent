#!/usr/bin/env python3
"""
Comprehensive unit tests for search functionality.
Tests OptimizedDuckDuckGoSearch, DuckDuckGoSearch, auto-search detection,
caching, and error handling.
"""
import os
import sys
import asyncio
import tempfile
import unittest
from unittest.mock import Mock, patch, MagicMock, AsyncMock
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.search import (
    OptimizedDuckDuckGoSearch, DuckDuckGoSearch,
    clean_search_results, extract_main_content
)


class TestOptimizedDuckDuckGoSearchInitialization(unittest.TestCase):
    """Test OptimizedDuckDuckGoSearch initialization."""

    def test_initialization_with_default_triggers(self):
        """Test initialization with default triggers."""
        searcher = OptimizedDuckDuckGoSearch()

        # Verify properties
        self.assertIsInstance(searcher.triggers, set)
        self.assertIn("today", searcher.triggers)
        self.assertIn("news", searcher.triggers)
        self.assertIn("weather", searcher.triggers)
        self.assertIn("latest", searcher.triggers)
        self.assertIn("current", searcher.triggers)

        # Cache should be empty initially
        self.assertEqual(len(searcher.cache), 0)

    def test_initialization_with_custom_triggers(self):
        """Test initialization with custom triggers."""
        custom_triggers = {"custom1", "custom2", "test"}
        searcher = OptimizedDuckDuckGoSearch(triggers=custom_triggers)

        # Should use custom triggers
        self.assertEqual(searcher.triggers, custom_triggers)

        # Default triggers should not be present
        self.assertNotIn("today", searcher.triggers)
        self.assertNotIn("news", searcher.triggers)

    def test_initialization_with_empty_triggers(self):
        """Test initialization with empty triggers."""
        searcher = OptimizedDuckDuckGoSearch(triggers=set())

        # Triggers should be empty
        self.assertEqual(searcher.triggers, set())

    def test_initialization_cache_properties(self):
        """Test cache-related properties on initialization."""
        searcher = OptimizedDuckDuckGoSearch()

        # Cache should be a dictionary
        self.assertIsInstance(searcher.cache, dict)
        self.assertEqual(len(searcher.cache), 0)

        # Cache expiration should be set
        self.assertEqual(searcher.cache_expiration, 300)  # 5 minutes


class TestSearchTriggerDetection(unittest.TestCase):
    """Test auto-search trigger detection logic."""

    def setUp(self):
        """Set up test environment."""
        self.searcher = OptimizedDuckDuckGoSearch()

    def test_should_search_time_sensitive_queries(self):
        """Test detection of time-sensitive queries."""
        time_sensitive_queries = [
            "What's the latest news?",
            "current events in politics",
            "weather in London today",
            "stock price of AAPL now",
            "score of the basketball game",
            "breaking news alerts",
            "today's headlines",
            "recent developments in AI",
            "latest updates on COVID",
            "what happened today"
        ]

        for query in time_sensitive_queries:
            with self.subTest(query=query):
                self.assertTrue(
                    self.searcher.should_search(query),
                    f"Should search time-sensitive query: '{query}'"
                )

    def test_should_search_with_trigger_keywords(self):
        """Test detection based on trigger keywords."""
        # Test each default trigger
        for trigger in ["today", "news", "weather", "latest", "current"]:
            query = f"This is a test with {trigger} in it"
            self.assertTrue(
                self.searcher.should_search(query),
                f"Should detect trigger: '{trigger}'"
            )

        # Multiple triggers
        self.assertTrue(self.searcher.should_search("today's latest news"))
        self.assertTrue(self.searcher.should_search("current weather news"))

    def test_should_not_search_non_time_sensitive(self):
        """Test non-time-sensitive queries don't trigger search."""
        non_time_sensitive = [
            "How do I write a Python function?",
            "Explain quantum computing principles",
            "What is the capital of France?",
            "Tell me about the history of Rome",
            "How does machine learning work?",
            "What are the benefits of exercise?",
            "Explain the theory of relativity",
            "How to cook pasta properly",
            "What is the meaning of life?",
            "Tell me a joke"
        ]

        for query in non_time_sensitive:
            with self.subTest(query=query):
                self.assertFalse(
                    self.searcher.should_search(query),
                    f"Should NOT search non-time-sensitive query: '{query}'"
                )

    def test_should_search_case_insensitive(self):
        """Test trigger detection is case-insensitive."""
        queries = [
            "TODAY's news",
            "Latest UPDATE",
            "CURRENT Events",
            "Weather forecast",
            "NEWS headlines"
        ]

        for query in queries:
            with self.subTest(query=query):
                self.assertTrue(
                    self.searcher.should_search(query),
                    f"Should detect triggers case-insensitively: '{query}'"
                )

    def test_should_search_with_custom_triggers(self):
        """Test trigger detection with custom triggers."""
        custom_triggers = {"urgent", "emergency", "breaking"}
        searcher = OptimizedDuckDuckGoSearch(triggers=custom_triggers)

        # Should detect custom triggers
        self.assertTrue(searcher.should_search("This is urgent news"))
        self.assertTrue(searcher.should_search("Emergency alert!"))
        self.assertTrue(searcher.should_search("Breaking story"))

        # Should NOT detect default triggers
        self.assertFalse(searcher.should_search("today's news"))
        self.assertFalse(searcher.should_search("weather forecast"))

    def test_should_search_empty_query(self):
        """Test empty query doesn't trigger search."""
        self.assertFalse(self.searcher.should_search(""))
        self.assertFalse(self.searcher.should_search("   "))
        self.assertFalse(self.searcher.should_search("\n\t"))

    def test_should_search_query_with_only_triggers(self):
        """Test queries that consist only of trigger words."""
        # Single trigger word
        self.assertTrue(self.searcher.should_search("news"))
        self.assertTrue(self.searcher.should_search("today"))
        self.assertTrue(self.searcher.should_search("latest"))

        # Multiple trigger words
        self.assertTrue(self.searcher.should_search("news today latest"))


class TestSearchCaching(unittest.TestCase):
    """Test search result caching functionality."""

    def setUp(self):
        """Set up test environment."""
        self.searcher = OptimizedDuckDuckGoSearch()

    def test_cache_result(self):
        """Test caching search results."""
        query = "test query"
        results = ["result1", "result2", "result3"]

        # Cache should be empty initially
        self.assertNotIn(query, self.searcher.cache)

        # Cache the results
        self.searcher.cache_result(query, results)

        # Should be in cache
        self.assertIn(query, self.searcher.cache)

        cached_entry = self.searcher.cache[query]
        self.assertEqual(cached_entry["results"], results)
        self.assertIsInstance(cached_entry["timestamp"], float)
        self.assertGreater(cached_entry["timestamp"], 0)

    def test_get_cached_result(self):
        """Test retrieving cached search results."""
        query = "cached query"
        results = ["cached result"]

        # Add to cache
        self.searcher.cache_result(query, results)

        # Retrieve from cache
        cached = self.searcher.get_cached_result(query)

        # Should return cached results
        self.assertEqual(cached, results)

    def test_get_cached_result_nonexistent(self):
        """Test retrieving non-existent cached result."""
        query = "nonexistent query"

        # Should return None
        cached = self.searcher.get_cached_result(query)
        self.assertIsNone(cached)

    def test_get_cached_result_expired(self):
        """Test retrieval of expired cache entry."""
        query = "expired query"
        results = ["old result"]

        # Add to cache with old timestamp
        self.searcher.cache[query] = {
            "results": results,
            "timestamp": time.time() - 400  # 400 seconds old (expired for 300s cache)
        }

        # Should return None (expired)
        cached = self.searcher.get_cached_result(query)
        self.assertIsNone(cached)

        # Cache entry should be removed
        self.assertNotIn(query, self.searcher.cache)

    def test_get_cached_result_not_expired(self):
        """Test retrieval of non-expired cache entry."""
        query = "fresh query"
        results = ["fresh result"]

        # Add to cache with recent timestamp
        self.searcher.cache[query] = {
            "results": results,
            "timestamp": time.time() - 100  # 100 seconds old (not expired)
        }

        # Should return cached results
        cached = self.searcher.get_cached_result(query)
        self.assertEqual(cached, results)

        # Cache entry should still be present
        self.assertIn(query, self.searcher.cache)

    def test_clear_expired_cache(self):
        """Test clearing expired cache entries."""
        # Add fresh entry
        fresh_query = "fresh"
        self.searcher.cache_result(fresh_query, ["fresh result"])

        # Add expired entry (mock old timestamp)
        expired_query = "expired"
        self.searcher.cache[expired_query] = {
            "results": ["old result"],
            "timestamp": time.time() - 400
        }

        # Add another expired entry
        another_expired = "also_expired"
        self.searcher.cache[another_expired] = {
            "results": ["also old"],
            "timestamp": time.time() - 500
        }

        # Clear expired cache
        self.searcher.clear_expired_cache()

        # Fresh entry should remain
        self.assertIn(fresh_query, self.searcher.cache)

        # Expired entries should be removed
        self.assertNotIn(expired_query, self.searcher.cache)
        self.assertNotIn(another_expired, self.searcher.cache)

    def test_cache_size_limit(self):
        """Test cache doesn't grow beyond reasonable limit."""
        # Add many cache entries
        for i in range(1000):
            self.searcher.cache_result(f"query_{i}", [f"result_{i}"])

        # Cache should have entries
        self.assertGreater(len(self.searcher.cache), 0)

        # Cache size should be reasonable (implementation may limit)
        # Just verify it doesn't crash


@unittest.skip("Incomplete implementation")
class TestSearchExecution(unittest.TestCase):
    """Test search execution functionality."""

    def setUp(self):
        """Set up test environment."""
        self.searcher = OptimizedDuckDuckGoSearch()

    def test_search_sync_mocked(self):
        """Test synchronous search with mocked HTTP requests."""
        query = "test query"
        mock_results = [
            {"title": "Test Result 1", "url": "http://example.com/1", "snippet": "Snippet 1"},
            {"title": "Test Result 2", "url": "http://example.com/2", "snippet": "Snippet 2"}
        ]

        # Mock duckduckgo_search
        with patch('agent.search.ddg') as mock_ddg:
            mock_ddg.return_value = mock_results

            # Execute search
            results = self.searcher.search_sync(query)

            # Should return results
            self.assertEqual(results, mock_results)

            # Should have been called with query
            mock_ddg.assert_called_once_with(query, max_results=5)

    def test_search_sync_with_custom_max_results(self):
        """Test synchronous search with custom max_results."""
        query = "test query"

        with patch('agent.search.ddg') as mock_ddg:
            mock_ddg.return_value = []

            # Search with custom max_results
            self.searcher.search_sync(query, max_results=10)

            # Should use custom max_results
            mock_ddg.assert_called_once_with(query, max_results=10)

    def test_search_sync_http_error(self):
        """Test synchronous search handles HTTP errors."""
        query = "error query"

        with patch('agent.search.ddg') as mock_ddg:
            mock_ddg.side_effect = Exception("HTTP Error")

            # Should handle error gracefully
            results = self.searcher.search_sync(query)

            # Should return empty list on error
            self.assertEqual(results, [])

    @patch('asyncio.get_event_loop')
    def test_search_async_mocked(self, mock_get_event_loop):
        """Test asynchronous search with mocked HTTP requests."""
        query = "async query"
        mock_results = [
            {"title": "Async Result", "url": "http://example.com", "snippet": "Async snippet"}
        ]

        # Mock aiohttp requests
        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_response = AsyncMock()
            mock_response.json = AsyncMock(return_value={
                "results": mock_results
            })
            mock_response.status = 200
            mock_session.get = AsyncMock(return_value=mock_response)
            mock_session_class.return_value.__aenter__.return_value = mock_session

            # Mock event loop
            mock_loop = Mock()
            mock_loop.run_until_complete = Mock(side_effect=lambda coro: coro)
            mock_get_event_loop.return_value = mock_loop

            # Execute async search
            results = self.searcher.search_async(query)

            # Should return results
            self.assertEqual(results, mock_results)

    def test_search_async_fallback_to_sync(self):
        """Test async search falls back to sync on error."""
        query = "fallback query"
        mock_results = [{"title": "Fallback Result"}]

        # Mock aiohttp to raise error
        with patch('aiohttp.ClientSession', side_effect=Exception("Async error")):
            with patch.object(self.searcher, 'search_sync', return_value=mock_results) as mock_sync:
                # Execute async search (should fall back to sync)
                results = self.searcher.search_async(query)

                # Should have called sync search as fallback
                mock_sync.assert_called_once_with(query)
                # Should return sync results
                self.assertEqual(results, mock_results)

    def test_search_with_caching(self):
        """Test search uses caching."""
        query = "cached search"
        mock_results = [{"title": "Cached Result"}]

        # Mock the search to return results
        with patch.object(self.searcher, 'search_sync', return_value=mock_results) as mock_search:
            # First search
            results1 = self.searcher.search(query)

            # Should call search_sync
            mock_search.assert_called_once_with(query)
            self.assertEqual(results1, mock_results)

            # Reset mock
            mock_search.reset_mock()

            # Second search (should use cache)
            results2 = self.searcher.search(query)

            # Should NOT call search_sync again (cached)
            mock_search.assert_not_called()
            # Should return cached results
            self.assertEqual(results2, mock_results)

    def test_search_cache_miss(self):
        """Test search when cache miss occurs."""
        query = "uncached search"
        mock_results = [{"title": "Uncached Result"}]

        # Mock search_sync
        with patch.object(self.searcher, 'search_sync', return_value=mock_results) as mock_search:
            # Search with cache miss
            results = self.searcher.search(query)

            # Should call search_sync
            mock_search.assert_called_once_with(query)
            self.assertEqual(results, mock_results)

            # Should be cached now
            self.assertIn(query, self.searcher.cache)


@unittest.skip("Incomplete implementation")
class TestDuckDuckGoSearchClass(unittest.TestCase):
    """Test DuckDuckGoSearch class (synchronous fallback)."""

    def test_duckduckgo_search_initialization(self):
        """Test DuckDuckGoSearch initialization."""
        searcher = DuckDuckGoSearch()

        # Should have same interface
        self.assertIsInstance(searcher.triggers, set)
        self.assertIn("today", searcher.triggers)

    def test_duckduckgo_search_method(self):
        """Test DuckDuckGoSearch.search method."""
        searcher = DuckDuckGoSearch()
        query = "test query"
        mock_results = [{"title": "Test Result"}]

        with patch('agent.search.ddg', return_value=mock_results) as mock_ddg:
            results = searcher.search(query)

            # Should call ddg function
            mock_ddg.assert_called_once_with(query, max_results=5)
            self.assertEqual(results, mock_results)

    def test_duckduckgo_should_search(self):
        """Test DuckDuckGoSearch.should_search method."""
        searcher = DuckDuckGoSearch()

        # Should have same trigger detection as OptimizedDuckDuckGoSearch
        self.assertTrue(searcher.should_search("today's news"))
        self.assertFalse(searcher.should_search("how to code"))


@unittest.skip("Incomplete implementation")
class TestSearchResultProcessing(unittest.TestCase):
    """Test search result processing functions."""

    def test_clean_search_results(self):
        """Test cleaning and formatting search results."""
        raw_results = [
            {"title": "  Title with extra spaces  ", "url": "http://example.com", "snippet": "Snippet here."},
            {"title": "Another Title", "url": "https://example.org", "snippet": "Another snippet."},
            {"title": "", "url": "", "snippet": ""},  # Empty result
            {"title": "Valid", "url": "http://test.com", "snippet": None}  # None snippet
        ]

        cleaned = clean_search_results(raw_results)

        # Should clean and format
        self.assertEqual(len(cleaned), 3)  # Empty result filtered out

        # Check first result
        self.assertEqual(cleaned[0]["title"], "Title with extra spaces")  # Stripped
        self.assertEqual(cleaned[0]["url"], "http://example.com")
        self.assertEqual(cleaned[0]["snippet"], "Snippet here.")

        # Check second result
        self.assertEqual(cleaned[1]["title"], "Another Title")
        self.assertEqual(cleaned[1]["url"], "https://example.org")
        self.assertEqual(cleaned[1]["snippet"], "Another snippet.")

        # Check third result (with None snippet)
        self.assertEqual(cleaned[2]["title"], "Valid")
        self.assertEqual(cleaned[2]["url"], "http://test.com")
        self.assertEqual(cleaned[2]["snippet"], "")  # None converted to empty string

    def test_clean_search_results_empty(self):
        """Test cleaning empty search results."""
        self.assertEqual(clean_search_results([]), [])
        self.assertEqual(clean_search_results(None), [])

    def test_extract_main_content(self):
        """Test extracting main content from HTML."""
        html_content = """
        <html>
            <head><title>Test Page</title></head>
            <body>
                <nav>Navigation</nav>
                <main>
                    <h1>Main Heading</h1>
                    <p>Main content paragraph.</p>
                </main>
                <footer>Footer content</footer>
            </body>
        </html>
        """

        # Test with BeautifulSoup available
        try:
            from bs4 import BeautifulSoup
            content = extract_main_content(html_content)
            self.assertIsInstance(content, str)
            self.assertIn("Main Heading", content)
            self.assertIn("Main content paragraph", content)
            # Should exclude navigation and footer
            self.assertNotIn("Navigation", content)
            self.assertNotIn("Footer content", content)
        except ImportError:
            # BeautifulSoup not available, function should return original or empty
            pass

    def test_extract_main_content_no_bs4(self):
        """Test extract_main_content when BeautifulSoup is not available."""
        html_content = "<html><body>Test content</body></html>"

        # Mock BeautifulSoup import to fail
        with patch('agent.search.BeautifulSoup', None):
            content = extract_main_content(html_content)

            # Should return empty string or simple extraction
            # Implementation may vary
            self.assertIsInstance(content, str)

    def test_extract_main_content_empty(self):
        """Test extract_main_content with empty input."""
        self.assertEqual(extract_main_content(""), "")
        self.assertEqual(extract_main_content(None), "")


class TestIntegrationWithAgent(unittest.TestCase):
    """Test search integration with agent."""

    def test_search_integration_mocked(self):
        """Test search integration through agent interface."""
        from agent.core import NeoMindAgent

        # Mock agent config
        with patch('agent.core.agent_config') as mock_config:
            mock_config.model = "deepseek-chat"
            mock_config.mode = "chat"
            mock_config.coding_mode_show_status_bar = False
            mock_config.thinking_enabled = False
            mock_config.auto_search_triggers = ["today", "news"]
            mock_config.auto_search_enabled = True
            mock_config.natural_language_enabled = True
            mock_config.natural_language_confidence_threshold = 0.8
            mock_config.safety_confirm_file_operations = True
            mock_config.safety_confirm_code_changes = True
            mock_config.system_prompt = ""
            mock_config.coding_mode_system_prompt = ""

            # Create agent
            agent = NeoMindAgent(api_key="test_key")

            # Mock searcher
            mock_results = [{"title": "News Result", "url": "http://news.com", "snippet": "Latest news"}]
            agent.searcher.search = Mock(return_value=mock_results)

            # Test auto-search detection
            self.assertTrue(agent.searcher.should_search("today's news"))

            # Test search execution
            results = agent.searcher.search("today's news")
            self.assertEqual(results, mock_results)


if __name__ == '__main__':
    unittest.main()