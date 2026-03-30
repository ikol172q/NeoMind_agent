"""
Rate Limiter — Per-source API rate limit enforcement.
Ensures NeoMind never exceeds API ToS limits.
"""

import time
import threading
import logging
from collections import defaultdict
from typing import Optional

logger = logging.getLogger(__name__)


class RateLimiter:
    """Token bucket rate limiter with per-source tracking."""

    LIMITS = {
        # source: {rpm: requests per minute, daily: daily cap or None}
        "finnhub":        {"rpm": 55, "daily": None},       # Official: 60, keep 5 margin
        "alpha_vantage":  {"rpm": 5,  "daily": 25},
        "coingecko":      {"rpm": 25, "daily": None},       # Official: 30, keep 5 margin
        "fred":           {"rpm": 100, "daily": None},      # Official: 120
        "yfinance":       {"rpm": 15, "daily": None},       # Unofficial, conservative
        "sec_edgar":      {"rpm": 8,  "daily": None},       # Official: 10
        "akshare":        {"rpm": 10, "daily": None},       # Conservative for A-share
        "newsapi":        {"rpm": 10, "daily": 100},        # Free tier: 100/day
        "rss":            {"rpm": 30, "daily": None},       # RSS feeds, relaxed
    }

    def __init__(self):
        self._lock = threading.Lock()
        # {source: [timestamp, timestamp, ...]}
        self._minute_window: dict[str, list[float]] = defaultdict(list)
        # {source: {date_str: count}}
        self._daily_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    def can_request(self, source: str) -> bool:
        """Check if a request to this source is allowed right now."""
        limits = self.LIMITS.get(source)
        if not limits:
            return True  # Unknown source, allow but log

        now = time.time()
        today = time.strftime("%Y-%m-%d")

        with self._lock:
            # Clean old entries from minute window
            window = self._minute_window[source]
            cutoff = now - 60
            self._minute_window[source] = [t for t in window if t > cutoff]

            # Check RPM
            if len(self._minute_window[source]) >= limits["rpm"]:
                return False

            # Check daily limit
            if limits["daily"] is not None:
                if self._daily_counts[source][today] >= limits["daily"]:
                    return False

        return True

    def record_request(self, source: str) -> None:
        """Record that a request was made."""
        now = time.time()
        today = time.strftime("%Y-%m-%d")

        with self._lock:
            self._minute_window[source].append(now)
            self._daily_counts[source][today] += 1

    def wait_if_needed(self, source: str, timeout: float = 120.0) -> bool:
        """Block until request is allowed, or timeout. Returns True if allowed."""
        start = time.time()
        while not self.can_request(source):
            if time.time() - start > timeout:
                logger.warning(f"Rate limit timeout for {source} after {timeout}s")
                return False
            time.sleep(1.0)
        self.record_request(source)
        return True

    def get_wait_time(self, source: str) -> float:
        """Estimate seconds until next request is allowed."""
        limits = self.LIMITS.get(source)
        if not limits:
            return 0.0

        now = time.time()
        with self._lock:
            window = self._minute_window[source]
            cutoff = now - 60
            active = [t for t in window if t > cutoff]

            if len(active) < limits["rpm"]:
                return 0.0

            # Wait until oldest request expires from window
            return max(0.0, active[0] + 60 - now)

    def get_daily_remaining(self, source: str) -> Optional[int]:
        """Get remaining daily requests, or None if unlimited."""
        limits = self.LIMITS.get(source)
        if not limits or limits["daily"] is None:
            return None

        today = time.strftime("%Y-%m-%d")
        with self._lock:
            used = self._daily_counts[source][today]
            return max(0, limits["daily"] - used)

    def get_status(self) -> dict:
        """Get rate limit status for all sources."""
        now = time.time()
        today = time.strftime("%Y-%m-%d")
        status = {}

        with self._lock:
            for source, limits in self.LIMITS.items():
                window = self._minute_window[source]
                active = [t for t in window if t > now - 60]
                daily_used = self._daily_counts[source][today]

                status[source] = {
                    "rpm_used": len(active),
                    "rpm_limit": limits["rpm"],
                    "daily_used": daily_used,
                    "daily_limit": limits["daily"],
                    "available": len(active) < limits["rpm"] and (
                        limits["daily"] is None or daily_used < limits["daily"]
                    ),
                }

        return status
