# agent/web/crawler.py — Multi-page BFS crawler for NeoMind
#
# Crawls from a start URL, following same-domain links up to a configurable depth.
# Uses WebExtractor for content extraction and URLCache to avoid re-fetching.
#
# Usage:
#   crawler = BFSCrawler(extractor, cache)
#   results = crawler.crawl("https://docs.example.com", max_depth=2, max_pages=10)

import time
import logging
from typing import List, Optional, Set, Dict
from urllib.parse import urlparse
from dataclasses import dataclass, field

from .extractor import WebExtractor, ExtractionResult
from .cache import URLCache

logger = logging.getLogger("neomind.web.crawler")


@dataclass
class CrawlResult:
    """Result of a single crawled page."""
    url: str
    title: str = ""
    content: str = ""
    word_count: int = 0
    depth: int = 0
    strategy: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.content) and not self.error


@dataclass
class CrawlReport:
    """Aggregate result of a crawl session."""
    start_url: str
    pages: List[CrawlResult] = field(default_factory=list)
    total_words: int = 0
    elapsed_seconds: float = 0
    max_depth_reached: int = 0

    @property
    def ok_pages(self) -> List[CrawlResult]:
        return [p for p in self.pages if p.ok]

    def summary(self) -> str:
        """Human-readable summary."""
        domain = urlparse(self.start_url).netloc
        lines = [
            f"🕷️ Crawled {len(self.ok_pages)} pages from {domain} "
            f"(depth={self.max_depth_reached}, {self.elapsed_seconds:.1f}s)",
            f"   Total words: {self.total_words:,}",
            "",
        ]
        for i, page in enumerate(self.ok_pages, 1):
            depth_indent = "  " * page.depth
            title = page.title[:60] if page.title else "(no title)"
            path = urlparse(page.url).path or '/'
            lines.append(
                f"  [{i}] {depth_indent}{title} ({page.word_count:,} words)"
                f"\n       {path}"
            )

        if not self.ok_pages:
            lines.append("  (no pages successfully crawled)")

        lines.append("")
        lines.append(f"💡 Use /read <url> to read any page in full.")
        return "\n".join(lines)

    def all_content(self, max_chars_per_page: int = 3000) -> str:
        """Concatenate all page contents (for AI memory injection).

        Truncates each page to avoid blowing up context.
        """
        parts = []
        for page in self.ok_pages:
            header = f"\n## {page.title or page.url}\nURL: {page.url}\n\n"
            content = page.content[:max_chars_per_page]
            parts.append(header + content)
        return "\n".join(parts)


class BFSCrawler:
    """Breadth-first crawler that follows same-domain links.

    Args:
        extractor: WebExtractor instance for content extraction.
        cache: Optional URLCache for deduplication.
        delay: Seconds between requests (politeness). Default 1.0.
    """

    def __init__(self, extractor: WebExtractor, cache: Optional[URLCache] = None,
                 delay: float = 1.0):
        self.extractor = extractor
        self.cache = cache or URLCache()
        self.delay = delay

    def crawl(self, start_url: str, max_depth: int = 1,
              max_pages: int = 10, allow_external: bool = False) -> CrawlReport:
        """BFS crawl from start_url.

        Args:
            start_url: Entry point URL.
            max_depth: How many link-hops deep to go (0 = start page only).
            max_pages: Hard cap on total pages to fetch.
            allow_external: If True, follow cross-domain links too.

        Returns:
            CrawlReport with all crawled pages.
        """
        if not start_url.startswith(('http://', 'https://')):
            start_url = 'https://' + start_url

        parsed_start = urlparse(start_url)
        base_domain = parsed_start.netloc

        # BFS queue: (url, depth)
        queue: List[tuple] = [(start_url, 0)]
        visited: Set[str] = set()
        report = CrawlReport(start_url=start_url)

        t0 = time.time()

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
                if parsed.netloc != base_domain and not parsed.netloc.endswith('.' + base_domain):
                    continue

            visited.add(url)
            logger.info(f"Crawling [{depth}]: {url}")

            # Extract content
            extraction = self.extractor.extract(url, max_length=15000, include_links=True)

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

            # Politeness delay (skip for cached pages)
            if extraction.strategy != "cache" and queue:
                time.sleep(self.delay)

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
        if result.endswith('/') and parsed.path != '/':
            result = result.rstrip('/')
        return result

    @staticmethod
    def _should_skip(url: str) -> bool:
        """Skip URLs that are unlikely to be useful content."""
        skip_extensions = {
            '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.webp',
            '.pdf', '.zip', '.tar', '.gz', '.mp4', '.mp3', '.wav',
            '.css', '.js', '.woff', '.woff2', '.ttf', '.eot',
        }
        skip_patterns = {
            '/login', '/signup', '/register', '/auth',
            '/cart', '/checkout', '/account',
            '/wp-admin', '/wp-login',
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
