# agent/web/cache.py — URL response cache with TTL
#
# Shared by /read, /links, /crawl commands.
# Does NOT interfere with search engine's own cache (agent/search/engine.py).

import time
from typing import Optional, Dict, Tuple


class URLCache:
    """In-memory URL → content cache with per-entry TTL.

    Usage:
        cache = URLCache(ttl_seconds=1800)  # 30 min default
        cache.set(url, content)
        hit = cache.get(url)  # None if expired or missing
        cache.clear()
    """

    def __init__(self, ttl_seconds: int = 1800):
        self.ttl = ttl_seconds
        self._store: Dict[str, Tuple[str, float]] = {}  # url → (content, timestamp)

    def get(self, url: str) -> Optional[str]:
        """Return cached content if present and not expired, else None."""
        entry = self._store.get(url)
        if entry is None:
            return None
        content, ts = entry
        if time.time() - ts > self.ttl:
            del self._store[url]
            return None
        return content

    def set(self, url: str, content: str) -> None:
        """Store content for url with current timestamp."""
        self._store[url] = (content, time.time())

    def has(self, url: str) -> bool:
        """Check if url is cached and not expired (without returning content)."""
        return self.get(url) is not None

    def clear(self) -> None:
        """Drop all cached entries."""
        self._store.clear()

    def evict_expired(self) -> int:
        """Remove all expired entries. Returns count removed."""
        now = time.time()
        expired = [url for url, (_, ts) in self._store.items() if now - ts > self.ttl]
        for url in expired:
            del self._store[url]
        return len(expired)

    @property
    def size(self) -> int:
        return len(self._store)

    def __repr__(self):
        return f"URLCache(size={self.size}, ttl={self.ttl}s)"
