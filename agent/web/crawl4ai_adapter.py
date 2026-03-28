# agent/web/crawl4ai_adapter.py — Crawl4AI async adapter for NeoMind
#
# Wraps crawl4ai's AsyncWebCrawler to match the BFSCrawler API.
# Provides advanced JS rendering and browser control.
#
# Graceful degradation: if crawl4ai is not installed, falls back to BFSCrawler.
#
# Usage:
#   adapter = Crawl4AIAdapter()
#   report = await adapter.crawl("https://example.com", max_depth=2, max_pages=10)

import time
import logging
import asyncio
from typing import Optional, List, Set
from urllib.parse import urlparse
from dataclasses import dataclass, field

from .crawler import CrawlReport, CrawlResult
from .extractor import WebExtractor, ExtractionResult
from .cache import URLCache

logger = logging.getLogger("neomind.web.crawl4ai")

# ── Optional imports with graceful fallback ──────────────────────

try:
    from crawl4ai import AsyncWebCrawler
    HAS_CRAWL4AI = True
except ImportError:
    HAS_CRAWL4AI = False
    AsyncWebCrawler = None

try:
    from playwright_stealth import stealth_async
    HAS_STEALTH = True
except ImportError:
    HAS_STEALTH = False


class Crawl4AIAdapter:
    """Adapter wrapping crawl4ai's AsyncWebCrawler for async crawling.

    Provides a crawl() method that returns CrawlReport for compatibility
    with BFSCrawler. Includes JS rendering and configurable browser options.

    Falls back to synchronous BFSCrawler if crawl4ai is not installed.

    Args:
        extractor: WebExtractor instance for content extraction.
        cache: Optional URLCache for deduplication.
        delay: Seconds between requests (politeness). Default 1.0.
        browser_type: "chromium", "firefox", or "webkit". Default "chromium".
        headless: Run browser headless. Default True.
        use_stealth: Use playwright-stealth to avoid detection. Default True.
    """

    def __init__(
        self,
        extractor: Optional[WebExtractor] = None,
        cache: Optional[URLCache] = None,
        delay: float = 1.0,
        browser_type: str = "chromium",
        headless: bool = True,
        use_stealth: bool = True,
    ):
        if not HAS_CRAWL4AI:
            logger.warning(
                "crawl4ai not installed. Falling back to BFSCrawler. "
                "Install via: pip install 'neomind[web]' or pip install crawl4ai"
            )

        self.extractor = extractor or WebExtractor()
        self.cache = cache or URLCache()
        self.delay = delay
        self.browser_type = browser_type
        self.headless = headless
        self.use_stealth = use_stealth and HAS_STEALTH

    async def crawl(
        self,
        start_url: str,
        max_depth: int = 1,
        max_pages: int = 10,
        allow_external: bool = False,
    ) -> CrawlReport:
        """Crawl website asynchronously using crawl4ai (or fall back to sync).

        Args:
            start_url: Entry point URL.
            max_depth: How many link-hops deep to go (0 = start page only).
            max_pages: Hard cap on total pages to fetch.
            allow_external: If True, follow cross-domain links too.

        Returns:
            CrawlReport with all crawled pages.
        """
        if not HAS_CRAWL4AI:
            # Fall back to synchronous BFSCrawler
            logger.info("Using fallback BFSCrawler (crawl4ai not installed)")
            from .crawler import BFSCrawler

            crawler = BFSCrawler(self.extractor, cache=self.cache, delay=self.delay)
            return crawler.crawl(
                start_url,
                max_depth=max_depth,
                max_pages=max_pages,
                allow_external=allow_external,
            )

        # Use crawl4ai for async crawling
        return await self._crawl_async(
            start_url,
            max_depth=max_depth,
            max_pages=max_pages,
            allow_external=allow_external,
        )

    async def _crawl_async(
        self,
        start_url: str,
        max_depth: int = 1,
        max_pages: int = 10,
        allow_external: bool = False,
    ) -> CrawlReport:
        """Internal async crawl using crawl4ai."""
        if not start_url.startswith(("http://", "https://")):
            start_url = "https://" + start_url

        parsed_start = urlparse(start_url)
        base_domain = parsed_start.netloc

        # BFS queue: (url, depth)
        queue: List[tuple] = [(start_url, 0)]
        visited: Set[str] = set()
        report = CrawlReport(start_url=start_url)

        t0 = time.time()

        # Create crawler with stealth if available
        crawler_kwargs = {
            "browser_type": self.browser_type,
            "headless": self.headless,
        }

        try:
            async with AsyncWebCrawler(**crawler_kwargs) as crawler:
                # Apply stealth if available
                if self.use_stealth:
                    try:
                        await stealth_async(crawler.page)
                    except Exception as e:
                        logger.debug(f"Failed to apply stealth: {e}")

                while queue and len(visited) < max_pages:
                    url, depth = queue.pop(0)

                    # Normalize and dedup
                    url = self._normalize_url(url)
                    if url in visited:
                        continue
                    if depth > max_depth:
                        continue

                    # Domain filter
                    if not allow_external:
                        parsed = urlparse(url)
                        if parsed.netloc != base_domain and not parsed.netloc.endswith(
                            "." + base_domain
                        ):
                            continue

                    visited.add(url)
                    logger.info(f"Crawling [{depth}]: {url}")

                    # Crawl with crawl4ai
                    try:
                        result = await crawler.arun(url)
                        html = result.html if result else ""
                    except Exception as e:
                        logger.warning(f"crawl4ai failed for {url}: {e}")
                        html = ""

                    # Extract content
                    extraction = self.extractor.extract(
                        url, max_length=15000, include_links=True
                    )

                    page = CrawlResult(
                        url=url,
                        title=extraction.title,
                        content=extraction.content if extraction.ok else "",
                        word_count=extraction.word_count,
                        depth=depth,
                        strategy=extraction.strategy,
                        error=extraction.error,
                    )
                    report.pages.append(page)

                    if page.ok:
                        report.total_words += page.word_count
                        report.max_depth_reached = max(report.max_depth_reached, depth)

                    # Enqueue child links (same-domain only unless allow_external)
                    if depth < max_depth and extraction.links:
                        for link in extraction.links:
                            href = link.href
                            if href in visited:
                                continue
                            if not allow_external and not link.is_internal:
                                continue
                            # Skip obvious non-content URLs
                            if self._should_skip(href):
                                continue
                            queue.append((href, depth + 1))

                    # Politeness delay
                    if queue:
                        await asyncio.sleep(self.delay)

        except Exception as e:
            logger.error(f"crawl4ai async context failed: {e}")
            # Degrade to sync crawl
            logger.info("Degrading to synchronous BFSCrawler")
            from .crawler import BFSCrawler

            crawler_sync = BFSCrawler(
                self.extractor, cache=self.cache, delay=self.delay
            )
            return crawler_sync.crawl(
                start_url,
                max_depth=max_depth,
                max_pages=max_pages,
                allow_external=allow_external,
            )

        report.elapsed_seconds = time.time() - t0
        return report

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Remove fragments and trailing slashes for dedup."""
        parsed = urlparse(url)
        # Remove fragment
        clean = parsed._replace(fragment="")
        result = clean.geturl()
        # Remove trailing slash (except for root)
        if result.endswith("/") and parsed.path != "/":
            result = result.rstrip("/")
        return result

    @staticmethod
    def _should_skip(url: str) -> bool:
        """Skip URLs that are unlikely to be useful content."""
        skip_extensions = {
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".svg",
            ".ico",
            ".webp",
            ".pdf",
            ".zip",
            ".tar",
            ".gz",
            ".mp4",
            ".mp3",
            ".wav",
            ".css",
            ".js",
            ".woff",
            ".woff2",
            ".ttf",
            ".eot",
        }
        skip_patterns = {
            "/login",
            "/signup",
            "/register",
            "/auth",
            "/cart",
            "/checkout",
            "/account",
            "/wp-admin",
            "/wp-login",
        }

        parsed = urlparse(url)
        path_lower = parsed.path.lower()

        for ext in skip_extensions:
            if path_lower.endswith(ext):
                return True
        for pattern in skip_patterns:
            if pattern in path_lower:
                return True
        return False
