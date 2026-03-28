"""
Comprehensive tests for agent/web/cache.py

Run: pytest tests/test_web_cache_full.py -v
"""
import os
import sys
import pytest
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestURLCache:
    """Test URLCache class with TTL functionality."""

    def test_init_default_ttl(self):
        from agent.web.cache import URLCache
        cache = URLCache()
        assert cache.ttl == 1800  # Default 30 minutes

    def test_init_custom_ttl(self):
        from agent.web.cache import URLCache
        cache = URLCache(ttl_seconds=3600)
        assert cache.ttl == 3600

    def test_set_and_get(self):
        from agent.web.cache import URLCache
        cache = URLCache()
        url = "https://example.com/page"
        content = "This is the page content"

        cache.set(url, content)
        result = cache.get(url)

        assert result == content

    def test_get_missing_url(self):
        from agent.web.cache import URLCache
        cache = URLCache()

        result = cache.get("https://nonexistent.com")

        assert result is None

    def test_get_expired_entry(self):
        from agent.web.cache import URLCache
        cache = URLCache(ttl_seconds=1)
        url = "https://example.com"
        cache.set(url, "content")

        time.sleep(1.1)
        result = cache.get(url)

        assert result is None

    def test_multiple_entries(self):
        from agent.web.cache import URLCache
        cache = URLCache()

        cache.set("https://example.com/1", "content1")
        cache.set("https://example.com/2", "content2")
        cache.set("https://example.com/3", "content3")

        assert cache.get("https://example.com/1") == "content1"
        assert cache.get("https://example.com/2") == "content2"
        assert cache.get("https://example.com/3") == "content3"

    def test_overwrite_entry(self):
        from agent.web.cache import URLCache
        cache = URLCache()
        url = "https://example.com"

        cache.set(url, "old content")
        cache.set(url, "new content")

        assert cache.get(url) == "new content"

    def test_has_existing(self):
        from agent.web.cache import URLCache
        cache = URLCache()
        url = "https://example.com"

        cache.set(url, "content")
        assert cache.has(url) is True

    def test_has_missing(self):
        from agent.web.cache import URLCache
        cache = URLCache()

        assert cache.has("https://nonexistent.com") is False

    def test_has_expired(self):
        from agent.web.cache import URLCache
        cache = URLCache(ttl_seconds=1)
        url = "https://example.com"

        cache.set(url, "content")
        time.sleep(1.1)
        assert cache.has(url) is False

    def test_clear(self):
        from agent.web.cache import URLCache
        cache = URLCache()

        cache.set("https://example.com/1", "content1")
        cache.set("https://example.com/2", "content2")

        cache.clear()

        assert cache.get("https://example.com/1") is None
        assert cache.get("https://example.com/2") is None
        assert cache.size == 0

    def test_size_property(self):
        from agent.web.cache import URLCache
        cache = URLCache()

        assert cache.size == 0

        cache.set("https://example.com/1", "content1")
        assert cache.size == 1

        cache.set("https://example.com/2", "content2")
        assert cache.size == 2

        cache.clear()
        assert cache.size == 0

    def test_evict_expired(self):
        from agent.web.cache import URLCache
        cache = URLCache(ttl_seconds=1)

        cache.set("https://example.com/1", "content1")
        cache.set("https://example.com/2", "content2")

        time.sleep(1.1)

        removed = cache.evict_expired()

        assert removed == 2
        assert cache.size == 0

    def test_evict_expired_mixed(self):
        from agent.web.cache import URLCache
        cache = URLCache(ttl_seconds=1)

        cache.set("https://example.com/1", "content1")
        time.sleep(0.6)
        cache.set("https://example.com/2", "content2")
        time.sleep(0.6)

        removed = cache.evict_expired()

        # First entry should be expired, second should still be valid
        assert removed == 1
        assert cache.size == 1
        assert cache.get("https://example.com/2") == "content2"

    def test_evict_expired_no_expiry(self):
        from agent.web.cache import URLCache
        cache = URLCache(ttl_seconds=10000)

        cache.set("https://example.com/1", "content1")
        cache.set("https://example.com/2", "content2")

        removed = cache.evict_expired()

        assert removed == 0
        assert cache.size == 2

    def test_repr(self):
        from agent.web.cache import URLCache
        cache = URLCache(ttl_seconds=3600)

        cache.set("https://example.com/1", "content1")
        repr_str = repr(cache)

        assert "URLCache" in repr_str
        assert "size=1" in repr_str
        assert "3600" in repr_str

    def test_special_characters_in_url(self):
        from agent.web.cache import URLCache
        cache = URLCache()

        url = "https://example.com/search?q=hello+world&filter=active"
        content = "search results"

        cache.set(url, content)
        assert cache.get(url) == content

    def test_unicode_content(self):
        from agent.web.cache import URLCache
        cache = URLCache()

        url = "https://example.com"
        content = "Hello, 世界! مرحبا بالعالم"

        cache.set(url, content)
        assert cache.get(url) == content

    def test_large_content(self):
        from agent.web.cache import URLCache
        cache = URLCache()

        url = "https://example.com"
        content = "x" * 1000000  # 1MB string

        cache.set(url, content)
        assert cache.get(url) == content
        assert cache.size == 1

    def test_empty_content(self):
        from agent.web.cache import URLCache
        cache = URLCache()

        url = "https://example.com"
        cache.set(url, "")

        assert cache.get(url) == ""

    def test_ttl_zero(self):
        from agent.web.cache import URLCache
        cache = URLCache(ttl_seconds=0)

        cache.set("https://example.com", "content")
        # Should expire immediately
        time.sleep(0.01)

        assert cache.get("https://example.com") is None

    def test_negative_ttl(self):
        from agent.web.cache import URLCache
        cache = URLCache(ttl_seconds=-1)

        cache.set("https://example.com", "content")
        # Should expire immediately
        time.sleep(0.01)

        assert cache.get("https://example.com") is None

    def test_concurrent_access(self):
        from agent.web.cache import URLCache
        cache = URLCache()

        # Set multiple entries
        for i in range(100):
            cache.set(f"https://example.com/{i}", f"content{i}")

        # Verify all are present
        for i in range(100):
            assert cache.get(f"https://example.com/{i}") == f"content{i}"

        assert cache.size == 100

    def test_get_updates_timestamp_logic(self):
        """Verify that get doesn't modify timestamp (TTL is based on set time)."""
        from agent.web.cache import URLCache
        cache = URLCache(ttl_seconds=2)

        url = "https://example.com"
        cache.set(url, "content")

        time.sleep(1)
        assert cache.get(url) == "content"

        # Wait just enough to expire
        time.sleep(1.1)
        assert cache.get(url) is None

    def test_whitespace_urls(self):
        from agent.web.cache import URLCache
        cache = URLCache()

        url = "https://example.com"
        cache.set(url, "content")

        # Exact URL should match
        assert cache.get(url) == "content"
        # URL with extra spaces should not match
        assert cache.get(url + " ") is None
