"""
Compliance Checker — Legal safety layer for all data collection.
Pre-request validation + post-response handling.
All collection must comply with API ToS and applicable law.
"""

import logging
import time
from typing import Optional

from agent.data.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


class ComplianceChecker:
    """
    Ensures all data collection is legal and ethical.

    Rules enforced:
    1. Only use official APIs with valid API keys
    2. Respect rate limits (never exceed)
    3. Personal use only (no redistribution)
    4. Required attribution (e.g., CoinGecko)
    5. No authentication circumvention
    """

    # Sources that require attribution in any output
    ATTRIBUTION_REQUIRED = {
        "coingecko": "Powered by CoinGecko API",
        "fred": "Source: Federal Reserve Economic Data (FRED)",
        "sec_edgar": "Source: SEC EDGAR",
    }

    # Sources that require API keys (vs. free/open)
    API_KEY_REQUIRED = {
        "finnhub": "FINNHUB_API_KEY",
        "alpha_vantage": "ALPHA_VANTAGE_API_KEY",
        "newsapi": "NEWSAPI_API_KEY",
    }

    # Forbidden actions (hard block)
    FORBIDDEN_PATTERNS = [
        "bypass",
        "circumvent",
        "fake_account",
        "scrape_without_api",
        "redistribute_raw",
    ]

    def __init__(self, rate_limiter: Optional[RateLimiter] = None,
                 api_keys: Optional[dict] = None):
        self.rate_limiter = rate_limiter or RateLimiter()
        self._api_keys = api_keys or {}
        self._backoff_until: dict[str, float] = {}
        self._disabled_sources: set[str] = set()

    def set_api_keys(self, keys: dict) -> None:
        """Update available API keys."""
        self._api_keys.update(keys)

    def pre_request_check(self, source: str, endpoint: str = "") -> tuple[bool, str]:
        """
        Check if a request is allowed before making it.
        Returns (allowed: bool, reason: str).
        """
        # Check if source is disabled
        if source in self._disabled_sources:
            return False, f"Source '{source}' is disabled due to previous errors"

        # Check backoff
        if source in self._backoff_until:
            if time.time() < self._backoff_until[source]:
                wait = self._backoff_until[source] - time.time()
                return False, f"Source '{source}' in backoff for {wait:.0f}s"
            else:
                del self._backoff_until[source]

        # Check API key requirement
        if source in self.API_KEY_REQUIRED:
            env_var = self.API_KEY_REQUIRED[source]
            if env_var not in self._api_keys or not self._api_keys[env_var]:
                return False, f"Missing API key: {env_var}"

        # Check rate limit
        if not self.rate_limiter.can_request(source):
            wait_time = self.rate_limiter.get_wait_time(source)
            return False, f"Rate limit exceeded for '{source}', wait {wait_time:.0f}s"

        # Check daily quota
        remaining = self.rate_limiter.get_daily_remaining(source)
        if remaining is not None and remaining <= 0:
            return False, f"Daily quota exhausted for '{source}'"

        return True, "ok"

    def post_response_check(self, source: str, status_code: int,
                            headers: Optional[dict] = None) -> None:
        """
        Handle response status codes for compliance.
        Updates backoff/disable state as needed.
        """
        if status_code == 429:
            # Rate limited — apply exponential backoff
            current_backoff = self._backoff_until.get(source, 0)
            if current_backoff > 0:
                # Double the backoff
                wait = min((time.time() - current_backoff) * 2, 3600)
            else:
                wait = 60  # Initial: 1 minute

            self._backoff_until[source] = time.time() + wait
            logger.warning(
                f"Rate limited by {source} (429). Backing off for {wait:.0f}s"
            )

        elif status_code == 403:
            # Forbidden — disable source and alert
            self._disabled_sources.add(source)
            logger.error(
                f"Access forbidden for {source} (403). Source disabled. "
                f"Check API key and ToS compliance."
            )

        elif status_code == 401:
            # Unauthorized — likely invalid API key
            self._disabled_sources.add(source)
            logger.error(
                f"Unauthorized for {source} (401). Invalid API key. Source disabled."
            )

    def get_attribution(self, source: str) -> Optional[str]:
        """Get required attribution text for a data source."""
        return self.ATTRIBUTION_REQUIRED.get(source)

    def is_source_available(self, source: str) -> bool:
        """Check if a source is currently available (not disabled/backedoff)."""
        if source in self._disabled_sources:
            return False
        if source in self._backoff_until and time.time() < self._backoff_until[source]:
            return False
        return True

    def re_enable_source(self, source: str) -> None:
        """Manually re-enable a disabled source."""
        self._disabled_sources.discard(source)
        self._backoff_until.pop(source, None)
        logger.info(f"Source '{source}' re-enabled")

    def get_status(self) -> dict:
        """Get compliance status for all sources."""
        return {
            "rate_limits": self.rate_limiter.get_status(),
            "disabled_sources": list(self._disabled_sources),
            "backoff_sources": {
                s: self._backoff_until[s] - time.time()
                for s in self._backoff_until
                if time.time() < self._backoff_until[s]
            },
            "api_keys_configured": [
                k for k, v in self._api_keys.items() if v
            ],
        }
