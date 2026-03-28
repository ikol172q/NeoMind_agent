"""
Comprehensive unit tests for agent/search/cache.py

Tests both SearchCache (in-memory) and DiskSearchCache (SQLite).
"""

import pytest
import os
import tempfile
import time
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from agent.search.cache import SearchCache, DiskSearchCache
from agent.search.sources import SearchItem, SearchResult


class TestSearchCache:
    """Tests for in-memory SearchCache."""

    def test_init_default_ttl(self):
        """Test cache initializes with default TTL."""
        cache = SearchCache()
        assert cache.ttl == 300
        assert len(cache._cache) == 0

    def test_init_custom_ttl(self):
        """Test cache initializes with custom TTL."""
        cache = SearchCache(ttl_seconds=600)
        assert cache.ttl == 600

    def test_set_and_get_basic(self):
        """Test basic set and get operations."""
        cache = SearchCache()
        result = SearchResult(
            query="test",
            items=[SearchItem(title="Test", url="http://test.com")],
        )

        cache.set("test query", result)
        retrieved = cache.get("test query")

        assert retrieved is not None
        assert retrieved.cached is True
        assert len(retrieved.items) == 1

    def test_get_nonexistent(self):
        """Test get on non-existent key returns None."""
        cache = SearchCache()
        result = cache.get("nonexistent")
        assert result is None

    def test_cache_key_normalization(self):
        """Test that cache keys are normalized (lowercase, stripped)."""
        cache = SearchCache()
        result = SearchResult(query="TEST QUERY")

        cache.set("TEST QUERY", result)
        retrieved = cache.get("test query")

        assert retrieved is not None

    def test_cache_expiration(self):
        """Test that expired cache entries are removed."""
        cache = SearchCache(ttl_seconds=1)
        result = SearchResult(query="test")

        cache.set("test", result)
        assert cache.get("test") is not None

        time.sleep(1.1)
        assert cache.get("test") is None

    def test_clear(self):
        """Test clearing all cache entries."""
        cache = SearchCache()
        result = SearchResult(query="test")

        cache.set("test1", result)
        cache.set("test2", result)
        assert cache.size() == 2

        cache.clear()
        assert cache.size() == 0

    def test_clear_expired(self):
        """Test clearing only expired entries."""
        cache = SearchCache(ttl_seconds=1)
        result = SearchResult(query="test")

        cache.set("test1", result)
        time.sleep(1.1)
        cache.set("test2", result)

        cache.clear_expired()
        assert cache.size() == 1
        assert cache.get("test2") is not None

    def test_size(self):
        """Test size() returns correct count."""
        cache = SearchCache()
        result = SearchResult(query="test")

        assert cache.size() == 0
        cache.set("test1", result)
        assert cache.size() == 1
        cache.set("test2", result)
        assert cache.size() == 2

    def test_multiple_queries_different_keys(self):
        """Test that different queries have different cache keys."""
        cache = SearchCache()
        result1 = SearchResult(query="query1", items=[SearchItem(title="A", url="a.com")])
        result2 = SearchResult(query="query2", items=[SearchItem(title="B", url="b.com")])

        cache.set("query1", result1)
        cache.set("query2", result2)

        r1 = cache.get("query1")
        r2 = cache.get("query2")

        assert r1.items[0].title == "A"
        assert r2.items[0].title == "B"

    def test_overwrite_existing_key(self):
        """Test that setting same key twice overwrites."""
        cache = SearchCache()
        result1 = SearchResult(query="test", items=[SearchItem(title="Old", url="old.com")])
        result2 = SearchResult(query="test", items=[SearchItem(title="New", url="new.com")])

        cache.set("test", result1)
        cache.set("test", result2)

        retrieved = cache.get("test")
        assert retrieved.items[0].title == "New"

    def test_cached_flag_set_on_retrieval(self):
        """Test that cached flag is set when retrieving from cache."""
        cache = SearchCache()
        result = SearchResult(query="test", cached=False)

        cache.set("test", result)
        retrieved = cache.get("test")

        assert retrieved.cached is True


class TestDiskSearchCache:
    """Tests for SQLite-backed DiskSearchCache."""

    @pytest.fixture
    def temp_db(self):
        """Create temporary database file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test_cache.db")
            yield db_path

    def test_init_creates_database(self, temp_db):
        """Test that initialization creates database and tables."""
        cache = DiskSearchCache(db_path=temp_db)

        assert cache.available is True
        assert os.path.exists(temp_db)

    def test_init_without_sqlite(self, temp_db):
        """Test graceful degradation when sqlite3 fails."""
        with patch('sqlite3.connect', side_effect=Exception("DB error")):
            cache = DiskSearchCache(db_path=temp_db)
            assert cache.available is False

    def test_set_and_get(self, temp_db):
        """Test basic set and get operations."""
        cache = DiskSearchCache(db_path=temp_db)
        result_data = {
            "query": "test",
            "items": [{"title": "Test", "url": "http://test.com"}],
        }

        cache.set("test query", result_data)
        retrieved = cache.get("test query")

        assert retrieved is not None
        assert retrieved["query"] == "test"

    def test_get_nonexistent(self, temp_db):
        """Test get on non-existent key returns None."""
        cache = DiskSearchCache(db_path=temp_db)
        result = cache.get("nonexistent")
        assert result is None

    def test_expiration_cleanup(self, temp_db):
        """Test that expired entries are cleaned up on retrieval."""
        cache = DiskSearchCache(db_path=temp_db, ttl_seconds=1)
        result_data = {"query": "test"}

        cache.set("test", result_data)
        assert cache.get("test") is not None

        time.sleep(1.1)
        assert cache.get("test") is None

    def test_clear_expired(self, temp_db):
        """Test clear_expired() removes only expired entries."""
        cache = DiskSearchCache(db_path=temp_db, ttl_seconds=1)

        cache.set("test1", {"query": "test1"})
        time.sleep(1.1)
        cache.set("test2", {"query": "test2"})

        cache.clear_expired()
        # test1 should be expired and removed
        assert cache.get("test1") is None
        # test2 should still exist
        assert cache.get("test2") is not None

    def test_json_serialization(self, temp_db):
        """Test that result_data is properly serialized/deserialized."""
        cache = DiskSearchCache(db_path=temp_db)
        result_data = {
            "query": "test",
            "items": [
                {"title": "A", "url": "http://a.com", "snippet": "Content A"},
                {"title": "B", "url": "http://b.com", "snippet": "Content B"},
            ],
            "count": 2,
            "nested": {"key": "value"},
        }

        cache.set("test", result_data)
        retrieved = cache.get("test")

        assert retrieved == result_data

    def test_key_normalization(self, temp_db):
        """Test that cache keys are normalized."""
        cache = DiskSearchCache(db_path=temp_db)
        result_data = {"query": "TEST"}

        cache.set("TEST QUERY", result_data)
        retrieved = cache.get("test query")

        assert retrieved is not None

    def test_graceful_degradation_when_unavailable(self, temp_db):
        """Test set/get gracefully return when cache is unavailable."""
        cache = DiskSearchCache(db_path=temp_db)
        cache._conn = None  # Simulate unavailable

        # Should not raise
        cache.set("test", {"query": "test"})
        result = cache.get("test")
        assert result is None

    def test_json_serialization_with_datetime(self, temp_db):
        """Test serialization with non-JSON-serializable objects."""
        cache = DiskSearchCache(db_path=temp_db)
        # Include a datetime object which isn't JSON serializable
        result_data = {
            "query": "test",
            "timestamp": datetime.now(timezone.utc),
        }

        cache.set("test", result_data)
        retrieved = cache.get("test")

        # Should have been converted to string
        assert retrieved is not None

    def test_close(self, temp_db):
        """Test close() closes the database connection."""
        cache = DiskSearchCache(db_path=temp_db)
        assert cache._conn is not None

        cache.close()
        assert cache._conn is None

    def test_multiple_sets_same_key(self, temp_db):
        """Test that setting same key twice updates the entry."""
        cache = DiskSearchCache(db_path=temp_db)

        cache.set("test", {"query": "test1"})
        cache.set("test", {"query": "test2"})

        retrieved = cache.get("test")
        assert retrieved["query"] == "test2"


class TestSearchCacheIntegration:
    """Integration tests for cache layer."""

    def test_cache_with_complex_search_result(self):
        """Test cache with realistic SearchResult."""
        cache = SearchCache()

        items = [
            SearchItem(
                title="Result 1",
                url="http://example1.com",
                snippet="Snippet 1",
                source="source1",
                published=datetime.now(timezone.utc),
            ),
            SearchItem(
                title="Result 2",
                url="http://example2.com",
                snippet="Snippet 2",
                source="source2",
            ),
        ]

        result = SearchResult(
            query="test query",
            items=items,
            sources_used=["source1", "source2"],
            reranked=True,
            cached=False,
        )

        cache.set("test query", result)
        retrieved = cache.get("test query")

        assert len(retrieved.items) == 2
        assert retrieved.sources_used == ["source1", "source2"]
        assert retrieved.reranked is True
        assert retrieved.cached is True

    @pytest.fixture
    def temp_db(self):
        """Create temporary database file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test_cache.db")
            yield db_path

    def test_disk_cache_with_complex_result(self, temp_db):
        """Test disk cache with realistic SearchResult."""
        cache = DiskSearchCache(db_path=temp_db)

        result_data = {
            "query": "test query",
            "items": [
                {
                    "title": "Result 1",
                    "url": "http://example1.com",
                    "snippet": "Snippet 1",
                    "source": "source1",
                },
            ],
            "sources_used": ["source1"],
            "reranked": True,
        }

        cache.set("test query", result_data)
        retrieved = cache.get("test query")

        assert retrieved["query"] == "test query"
        assert len(retrieved["items"]) == 1
        assert retrieved["reranked"] is True
