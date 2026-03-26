# agent/search/cache.py
"""
Layered search cache — memory (fast) + optional disk (persistent).

Layer 1: In-memory dict with TTL (default 5 minutes)
Layer 2: SQLite on disk with longer TTL (default 24 hours) — optional
"""

import time
import json
import hashlib
from typing import Optional, Dict, Any
from dataclasses import asdict

from .sources import SearchResult, SearchItem


class SearchCache:
    """In-memory search cache with TTL.

    Simple, fast, zero-dependency cache for search results.
    For disk persistence, use DiskSearchCache (requires sqlite3).
    """

    def __init__(self, ttl_seconds: int = 300):
        """
        Args:
            ttl_seconds: Time-to-live for cached results (default 5 minutes).
        """
        self.ttl = ttl_seconds
        self._cache: Dict[str, tuple] = {}  # key -> (result, timestamp)

    def get(self, query: str) -> Optional[SearchResult]:
        """Retrieve cached results if not expired."""
        key = self._key(query)
        if key in self._cache:
            result, ts = self._cache[key]
            if time.time() - ts < self.ttl:
                result.cached = True
                return result
            del self._cache[key]
        return None

    def set(self, query: str, result: SearchResult):
        """Store search results in cache."""
        self._cache[self._key(query)] = (result, time.time())

    def clear(self):
        """Clear all cached results."""
        self._cache.clear()

    def clear_expired(self):
        """Remove only expired entries."""
        now = time.time()
        expired = [k for k, (_, ts) in self._cache.items() if now - ts >= self.ttl]
        for k in expired:
            del self._cache[k]

    def size(self) -> int:
        """Number of cached entries."""
        return len(self._cache)

    def _key(self, query: str) -> str:
        """Normalize query to cache key."""
        return hashlib.md5(query.lower().strip().encode()).hexdigest()


class DiskSearchCache:
    """SQLite-backed search cache for longer persistence.

    Falls back to memory-only if sqlite3 is not available.
    Stores serialized SearchResult as JSON.
    """

    def __init__(self, db_path: str = "search_cache.db", ttl_seconds: int = 86400):
        self.ttl = ttl_seconds
        self.db_path = db_path
        self._conn = None
        try:
            import sqlite3
            self._conn = sqlite3.connect(db_path)
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS search_cache (
                    key TEXT PRIMARY KEY,
                    query TEXT,
                    result_json TEXT,
                    created_at REAL
                )
            """)
            self._conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_created_at ON search_cache(created_at)
            """)
            self._conn.commit()
        except Exception:
            self._conn = None

    @property
    def available(self) -> bool:
        return self._conn is not None

    def get(self, query: str) -> Optional[Dict]:
        """Retrieve cached result as dict (caller reconstructs SearchResult)."""
        if not self._conn:
            return None
        key = self._key(query)
        try:
            cursor = self._conn.execute(
                "SELECT result_json, created_at FROM search_cache WHERE key = ?",
                (key,)
            )
            row = cursor.fetchone()
            if row:
                result_json, created_at = row
                if time.time() - created_at < self.ttl:
                    return json.loads(result_json)
                else:
                    self._conn.execute("DELETE FROM search_cache WHERE key = ?", (key,))
                    self._conn.commit()
        except Exception:
            pass
        return None

    def set(self, query: str, result_data: Dict):
        """Store serializable search result data."""
        if not self._conn:
            return
        key = self._key(query)
        try:
            self._conn.execute(
                "INSERT OR REPLACE INTO search_cache (key, query, result_json, created_at) VALUES (?, ?, ?, ?)",
                (key, query, json.dumps(result_data, ensure_ascii=False, default=str), time.time())
            )
            self._conn.commit()
        except Exception:
            pass

    def clear_expired(self):
        """Remove expired entries."""
        if not self._conn:
            return
        try:
            cutoff = time.time() - self.ttl
            self._conn.execute("DELETE FROM search_cache WHERE created_at < ?", (cutoff,))
            self._conn.commit()
        except Exception:
            pass

    def _key(self, query: str) -> str:
        return hashlib.md5(query.lower().strip().encode()).hexdigest()

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None
