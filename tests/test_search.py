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

# These live in search_legacy, not in the newer agent.search package: the
# multi-source UniversalSearchEngine replaced them there, but agent/core.py
# still imports OptimizedDuckDuckGoSearch from search_legacy as its fallback,
# so this file keeps testing the code that is actually still reachable.
# Importing from agent.search raised ImportError at collection time, so none of
# these tests had ever run.
from agent.search_legacy import (
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


class TestSearchExecution(unittest.TestCase):
    """OptimizedDuckDuckGoSearch — the legacy fallback agent/core.py keeps.

    This class carried @unittest.skip("Incomplete implementation"). The
    tests behind it drove an API that never shipped: search_sync(query,
    max_results) returning a list of dicts via a module-level
    agent.search.ddg. What exists is an async search() returning
    (ok, formatted_text), fed by _fetch_html and _parse_fast. Rewritten
    against that, since this is the path taken whenever
    UniversalSearchEngine fails.
    """

    def setUp(self):
        self.searcher = OptimizedDuckDuckGoSearch()

    def test_should_search_on_trigger_keyword(self):
        self.assertTrue(self.searcher.should_search("what is the latest news"))

    def test_should_search_on_time_sensitive_pattern(self):
        self.assertTrue(self.searcher.should_search("stock price of AAPL"))

    def test_should_not_search_for_a_timeless_question(self):
        self.assertFalse(self.searcher.should_search("explain recursion to me"))

    def test_custom_triggers_replace_the_default_keywords(self):
        """Only the keyword set is swappable — time_patterns always apply.

        Passing triggers={"bananas"} drops "news" as a keyword, but
        should_search still matches the built-in r"latest.*news" pattern,
        so a custom set narrows keywords without disabling the
        time-sensitivity heuristics.
        """
        searcher = OptimizedDuckDuckGoSearch(triggers={"bananas"})
        self.assertTrue(searcher.should_search("about bananas"))
        self.assertFalse(searcher.should_search("a news article"),
                         "'news' is no longer a trigger keyword")
        self.assertTrue(searcher.should_search("the latest news"),
                        "time_patterns are not affected by custom triggers")

    def test_cached_result_round_trips(self):
        self.searcher.cache_result("q", ["a", "b"])
        self.assertEqual(self.searcher.get_cached_result("q"), ["a", "b"])

    def test_cache_miss_returns_none(self):
        self.assertIsNone(self.searcher.get_cached_result("never asked"))

    def test_expired_entry_is_dropped_on_read(self):
        self.searcher.cache_result("q", ["a"])
        self.searcher.cache["q"]["timestamp"] -= self.searcher.cache_expiration + 1
        self.assertIsNone(self.searcher.get_cached_result("q"))
        self.assertNotIn("q", self.searcher.cache, "read should evict, not just hide")

    def test_clear_expired_cache_keeps_fresh_entries(self):
        self.searcher.cache_result("old", ["x"])
        self.searcher.cache_result("new", ["y"])
        self.searcher.cache["old"]["timestamp"] -= self.searcher.cache_expiration + 1
        self.searcher.clear_expired_cache()
        self.assertNotIn("old", self.searcher.cache)
        self.assertIn("new", self.searcher.cache)

    def test_parse_fast_extracts_snippets(self):
        html = (
            '<html><body>'
            '<a class="snippet">This snippet is comfortably longer than the thirty char floor.</a>'
            '</body></html>'
        )
        results = self.searcher._parse_fast(html)
        self.assertTrue(results)
        self.assertIn("thirty char floor", results[0])

    def test_parse_fast_drops_short_text(self):
        html = '<html><body><a class="snippet">too short</a></body></html>'
        self.assertEqual(self.searcher._parse_fast(html), [])

    def test_parse_fast_deduplicates(self):
        one = "The very same snippet text repeated twice over here."
        html = f'<html><body><a class="snippet">{one}</a><a class="snippet">{one}</a></body></html>'
        self.assertEqual(len(self.searcher._parse_fast(html)), 1)

    def test_parse_fast_caps_at_five(self):
        items = "".join(
            f'<a class="snippet">Snippet number {i} padded out past the thirty char floor.</a>'
            for i in range(12)
        )
        self.assertLessEqual(len(self.searcher._parse_fast(f"<html><body>{items}</body></html>")), 5)

    def test_parse_fast_survives_garbage(self):
        self.assertEqual(self.searcher._parse_fast("<<<not html"), [])

    def test_search_reports_results(self):
        html = '<html><body><a class="snippet">A result long enough to clear the floor.</a></body></html>'
        with patch.object(self.searcher, "_fetch_html", new=AsyncMock(return_value=html)):
            ok, text = asyncio.run(self.searcher.search("q"))
        self.assertTrue(ok)
        self.assertIn("Found 1 results", text)

    def test_search_reports_no_results(self):
        with patch.object(self.searcher, "_fetch_html", new=AsyncMock(return_value="<html></html>")):
            ok, text = asyncio.run(self.searcher.search("q"))
        self.assertFalse(ok)
        self.assertEqual(text, "No results found")

    def test_search_turns_a_fetch_error_into_a_failed_tuple(self):
        """Never raises into the caller — core.py treats this as a fallback."""
        with patch.object(self.searcher, "_fetch_html", new=AsyncMock(side_effect=RuntimeError("boom"))):
            ok, text = asyncio.run(self.searcher.search("q"))
        self.assertFalse(ok)
        self.assertIn("boom", text)

    def test_search_reports_a_timeout_as_such(self):
        with patch.object(self.searcher, "_fetch_html", new=AsyncMock(side_effect=asyncio.TimeoutError)):
            ok, text = asyncio.run(self.searcher.search("q"))
        self.assertFalse(ok)
        self.assertEqual(text, "Search timeout")


class TestDuckDuckGoSearchClass(unittest.TestCase):
    """DuckDuckGoSearch — the synchronous fallback."""

    def setUp(self):
        self.searcher = DuckDuckGoSearch()
        self.searcher.min_interval = 0  # the real sleep is not what's under test

    def _response(self, html: str):
        resp = MagicMock()
        resp.text = html
        resp.raise_for_status = MagicMock()
        return resp

    def test_search_formats_found_snippets(self):
        html = (
            '<html><body>'
            '<a class="result__snippet">A snippet with enough characters to survive.</a>'
            '</body></html>'
        )
        with patch("agent.services.search_legacy.requests.post", return_value=self._response(html)):
            ok, text = self.searcher.search("python")
        self.assertTrue(ok)
        self.assertIn("python", text)
        self.assertIn("enough characters", text)

    def test_search_honours_max_results(self):
        items = "".join(
            f'<a class="result__snippet">Snippet {i} with enough characters to survive.</a>'
            for i in range(6)
        )
        with patch("agent.services.search_legacy.requests.post",
                   return_value=self._response(f"<html><body>{items}</body></html>")):
            ok, text = self.searcher.search("q", max_results=2)
        self.assertTrue(ok)
        self.assertEqual(text.count("Snippet"), 2)

    def test_search_reports_empty_results(self):
        with patch("agent.services.search_legacy.requests.post",
                   return_value=self._response("<html><body></body></html>")):
            ok, text = self.searcher.search("q")
        self.assertFalse(ok)
        self.assertEqual(text, "No results found.")

    def test_search_returns_a_tuple_on_network_error(self):
        with patch("agent.services.search_legacy.requests.post", side_effect=OSError("no route")):
            ok, text = self.searcher.search("q")
        self.assertFalse(ok)
        self.assertIn("Search failed", text)


class TestSearchResultProcessing(unittest.TestCase):
    """clean_search_results / extract_main_content.

    Both are exported but have no production caller, so these pin what
    they do rather than what their names suggest — see the note on
    extract_main_content below.
    """

    def test_clean_search_results_strips_and_drops_empties(self):
        cleaned = clean_search_results([
            {"title": "  Title with extra spaces  ", "url": "http://example.com", "snippet": "Snippet here."},
            {"title": "", "url": "", "snippet": ""},
            {"title": "Valid", "url": "http://test.com", "snippet": None},
        ])
        self.assertEqual(len(cleaned), 2)
        self.assertEqual(cleaned[0]["title"], "Title with extra spaces")
        self.assertEqual(cleaned[1]["snippet"], "", "None snippet should become empty string")

    def test_clean_search_results_handles_empty_and_none(self):
        self.assertEqual(clean_search_results([]), [])
        self.assertEqual(clean_search_results(None), [])

    def test_extract_main_content_removes_script_and_style_only(self):
        """Despite the name, boilerplate is not stripped.

        The implementation decomposes script and style and then dumps all
        remaining text, so nav and footer come through. The skipped test
        asserted they were removed; nothing calls this function, so the
        contract to record is the real one — changing it would be a new
        feature, not a fix.
        """
        html = """
        <html>
            <head><title>Test Page</title><style>.a{}</style></head>
            <body>
                <script>var x = 1;</script>
                <nav>Navigation</nav>
                <main><h1>Main Heading</h1><p>Main content paragraph.</p></main>
                <footer>Footer content</footer>
            </body>
        </html>
        """
        text = extract_main_content(html)
        self.assertIn("Main content paragraph.", text)
        self.assertNotIn("var x = 1", text)
        self.assertNotIn(".a{}", text)
        self.assertIn("Navigation", text)      # known gap, asserted so it is visible
        self.assertIn("Footer content", text)  # ditto

    def test_extract_main_content_handles_empty_input(self):
        self.assertEqual(extract_main_content(""), "")
        self.assertEqual(extract_main_content(None), "")

class TestIntegrationWithAgent(unittest.TestCase):
    """Test search integration with agent."""

    def test_search_integration_mocked(self):
        """Test search integration through agent interface."""
        from agent.core import NeoMindAgent

        # Mock agent config
        with patch('agent.core.agent_config') as mock_config:
            mock_config.model = "deepseek-v4-flash"
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