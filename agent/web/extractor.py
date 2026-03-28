# agent/web/extractor.py — Unified content extraction for NeoMind
#
# Consolidates the extraction logic that was duplicated in:
#   - agent/core.py   (read_webpage, _try_trafilatura, _try_beautifulsoup, ...)
#   - agent/search/sources.py  (ContentExtractor._sync_extract)
#
# Strategy chain (best quality first):
#   1. trafilatura   — F1=0.945, articles/news
#   2. readability   — F1=0.937, article body + html2text for Markdown
#   3. beautifulsoup — General HTML with link extraction
#   4. playwright    — JS-rendered pages via BrowserDaemon
#   5. fallback      — Raw regex strip
#
# All strategies are optional — graceful degradation if a library is missing.

import re
import logging
from typing import Optional, List, Tuple, Dict, Any
from urllib.parse import urlparse
from dataclasses import dataclass, field

import requests

logger = logging.getLogger("neomind.web.extractor")

# ── Optional imports with graceful fallback ──────────────────────

try:
    import trafilatura
    HAS_TRAFILATURA = True
except ImportError:
    HAS_TRAFILATURA = False

try:
    from readability import Document as ReadabilityDocument
    HAS_READABILITY = True
except ImportError:
    HAS_READABILITY = False

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

try:
    import html2text as _html2text
    HAS_HTML2TEXT = True
except ImportError:
    HAS_HTML2TEXT = False


# ── Data classes ─────────────────────────────────────────────────

@dataclass
class ExtractedLink:
    """A single link extracted from a page."""
    text: str
    href: str
    is_internal: bool = False


@dataclass
class ExtractionResult:
    """Result from content extraction."""
    url: str
    title: str = ""
    content: str = ""          # Main text content (Markdown or plain text)
    links: List[ExtractedLink] = field(default_factory=list)
    strategy: str = ""         # Which strategy produced this result
    score: int = 0             # Quality score 0-100
    word_count: int = 0
    error: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.content) and not self.error

    @property
    def links_text(self) -> str:
        """Format links as numbered list."""
        if not self.links:
            return ""
        lines = ["--- Links Found ---"]
        for i, link in enumerate(self.links[:50], 1):
            tag = "int" if link.is_internal else "ext"
            lines.append(f"[{i}] [{tag}] {link.text} → {link.href}")
        return "\n".join(lines)


# ── Default headers ──────────────────────────────────────────────

DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7',
    'Accept-Charset': 'utf-8, iso-8859-1, utf-16, *;q=0.7',
}


# ── WebExtractor ─────────────────────────────────────────────────

class WebExtractor:
    """Unified content extraction with multi-strategy fallback.

    Usage:
        extractor = WebExtractor()
        result = extractor.extract("https://example.com")
        print(result.content)
        print(result.links_text)
    """

    def __init__(self, browser_sync_fn=None, cache=None):
        """
        Args:
            browser_sync_fn: Optional callable(command, args) → str
                             for BrowserDaemon calls (from core._browser_sync).
            cache: Optional URLCache instance for response caching.
        """
        self._browser_sync = browser_sync_fn
        self._cache = cache
        self._html2text_converter = None
        if HAS_HTML2TEXT:
            self._html2text_converter = _html2text.HTML2Text()
            self._html2text_converter.ignore_links = False
            self._html2text_converter.ignore_images = True
            self._html2text_converter.body_width = 0       # No line wrapping
            self._html2text_converter.unicode_snob = True   # Preserve unicode
            self._html2text_converter.protect_links = True

    def extract(self, url: str, max_length: int = 20000,
                include_links: bool = True) -> ExtractionResult:
        """Extract content from URL using best available strategy.

        Returns ExtractionResult with content, links, metadata.
        """
        # Normalize
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url

        # Check cache
        if self._cache:
            cached = self._cache.get(url)
            if cached:
                logger.debug(f"Cache hit: {url}")
                return ExtractionResult(
                    url=url, content=cached, strategy="cache",
                    score=100, word_count=len(cached.split())
                )

        # Build strategy chain
        strategies: List[Tuple[str, Any]] = []
        if HAS_TRAFILATURA:
            strategies.append(("trafilatura", self._try_trafilatura))
        if HAS_READABILITY and HAS_HTML2TEXT:
            strategies.append(("readability", self._try_readability))
        if HAS_BS4:
            strategies.append(("beautifulsoup", self._try_beautifulsoup))
        if self._browser_sync:
            strategies.append(("playwright", self._try_playwright))
        strategies.append(("fallback", self._try_fallback))

        best: Optional[ExtractionResult] = None

        for name, strategy_fn in strategies:
            try:
                result = strategy_fn(url, max_length, include_links)
                if result and result.ok:
                    result.strategy = name
                    result.score = self._score(result.content)
                    result.word_count = len(result.content.split())

                    if best is None or result.score > best.score:
                        best = result

                    if result.score > 50:
                        break  # Good enough
            except Exception as e:
                logger.debug(f"Strategy {name} failed for {url}: {e}")
                continue

        if best is None:
            return ExtractionResult(url=url, error=f"All strategies failed for {url}")

        # Cache the result
        if self._cache and best.ok:
            self._cache.set(url, best.content)

        return best

    # ── Strategy: trafilatura ────────────────────────────────────

    def _try_trafilatura(self, url: str, max_length: int,
                         include_links: bool) -> Optional[ExtractionResult]:
        if not HAS_TRAFILATURA:
            return None

        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return None

        text = trafilatura.extract(
            downloaded,
            include_links=include_links,
            include_images=False,
            include_tables=True,
            no_fallback=False,
            include_formatting=True,
            output_format='txt',
        )

        if not text or len(text.strip()) < 50:
            return None

        # Extract title from metadata
        metadata = trafilatura.extract_metadata(downloaded)
        title = metadata.title if metadata and metadata.title else ""

        return ExtractionResult(
            url=url,
            title=title,
            content=self._clean(text)[:max_length],
        )

    # ── Strategy: readability + html2text ────────────────────────

    def _try_readability(self, url: str, max_length: int,
                         include_links: bool) -> Optional[ExtractionResult]:
        if not (HAS_READABILITY and HAS_HTML2TEXT):
            return None

        response = requests.get(url, headers=DEFAULT_HEADERS, timeout=15)
        response.raise_for_status()

        doc = ReadabilityDocument(response.text)
        clean_html = doc.summary()
        title = doc.title()

        if not clean_html or len(clean_html) < 100:
            return None

        # Convert to Markdown via html2text
        markdown = self._html2text_converter.handle(clean_html)

        # Extract links from the clean HTML
        links = []
        if include_links and HAS_BS4:
            links = self._extract_links_from_html(clean_html, url)

        return ExtractionResult(
            url=url,
            title=title or "",
            content=self._clean(markdown)[:max_length],
            links=links,
        )

    # ── Strategy: BeautifulSoup ──────────────────────────────────

    def _try_beautifulsoup(self, url: str, max_length: int,
                           include_links: bool) -> Optional[ExtractionResult]:
        if not HAS_BS4:
            return None

        response = requests.get(url, headers=DEFAULT_HEADERS, timeout=15)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')

        # Remove noise
        for tag in ['script', 'style', 'nav', 'footer', 'header',
                     'aside', 'form', 'iframe', 'noscript', 'svg']:
            for el in soup.find_all(tag):
                el.decompose()

        # Find main content
        main = None
        for sel in ['main', 'article', '[role="main"]', '.main-content',
                     '.content', '.post-content', '.article-content',
                     '#content', '.markdown-body']:
            main = soup.select_one(sel)
            if main:
                break

        root = main or soup.find('body') or soup
        text = root.get_text(separator='\n', strip=True)
        title_tag = soup.find('title')
        title = title_tag.get_text(strip=True) if title_tag else ""

        # Extract links
        links = []
        if include_links:
            links = self._extract_links_from_soup(root, url)

        return ExtractionResult(
            url=url,
            title=title,
            content=self._clean(text)[:max_length],
            links=links,
        )

    # ── Strategy: Playwright (BrowserDaemon) ─────────────────────

    def _try_playwright(self, url: str, max_length: int,
                        include_links: bool) -> Optional[ExtractionResult]:
        if not self._browser_sync:
            return None

        result = self._browser_sync("goto", [url])
        if result and "Error" in result:
            return None

        text = self._browser_sync("text", [])
        if not text or len(text.strip()) < 100:
            return None

        title = self._browser_sync("title", [])

        # Get links via browser
        links = []
        if include_links:
            raw_links = self._browser_sync("links", [])
            if raw_links and "No links" not in raw_links:
                parsed_base = urlparse(url)
                for line in raw_links.split('\n'):
                    # Format: [text](href)
                    m = re.match(r'\[(.+?)\]\((.+?)\)', line.strip())
                    if m:
                        link_text, href = m.group(1), m.group(2)
                        parsed_href = urlparse(href)
                        is_internal = (parsed_href.netloc == parsed_base.netloc)
                        links.append(ExtractedLink(text=link_text, href=href, is_internal=is_internal))

        return ExtractionResult(
            url=url,
            title=title or "",
            content=self._clean(text)[:max_length],
            links=links[:50],
        )

    # ── Strategy: raw fallback ───────────────────────────────────

    def _try_fallback(self, url: str, max_length: int,
                      include_links: bool) -> Optional[ExtractionResult]:
        response = requests.get(url, timeout=10)
        text = re.sub(r'<[^>]+>', ' ', response.text)
        text = re.sub(r'\s+', ' ', text).strip()
        return ExtractionResult(url=url, content=text[:max_length])

    # ── Link extraction helpers ──────────────────────────────────

    def _extract_links_from_html(self, html: str, base_url: str) -> List[ExtractedLink]:
        """Extract links from raw HTML string."""
        if not HAS_BS4:
            return []
        soup = BeautifulSoup(html, 'html.parser')
        return self._extract_links_from_soup(soup, base_url)

    def _extract_links_from_soup(self, root, base_url: str) -> List[ExtractedLink]:
        """Extract, deduplicate, and classify links from a BS4 element."""
        parsed_base = urlparse(base_url)
        seen = set()
        links = []

        for a_tag in root.find_all('a', href=True):
            href = a_tag['href'].strip()
            text = a_tag.get_text(strip=True)[:80]
            if not text or not href or href.startswith(('#', 'javascript:', 'mailto:', 'tel:')):
                continue

            # Resolve relative
            if href.startswith('/'):
                href = f"{parsed_base.scheme}://{parsed_base.netloc}{href}"
            elif not href.startswith(('http://', 'https://')):
                continue

            if href in seen:
                continue
            seen.add(href)

            parsed_href = urlparse(href)
            is_internal = (
                parsed_href.netloc == parsed_base.netloc or
                parsed_href.netloc.endswith('.' + parsed_base.netloc)
            )
            links.append(ExtractedLink(text=text, href=href, is_internal=is_internal))

        return links[:100]  # Cap

    # ── Scoring & cleaning ───────────────────────────────────────

    @staticmethod
    def _score(content: str) -> int:
        """Score content quality 0-100."""
        if not content:
            return 0
        score = 0
        words = content.split()
        word_count = len(words)

        if word_count > 50:
            score += 20
        if word_count > 200:
            score += 15
        if word_count > 500:
            score += 10

        # Paragraph structure
        paragraphs = [p for p in content.split('\n\n') if len(p.strip()) > 30]
        if len(paragraphs) > 2:
            score += 15
        if len(paragraphs) > 5:
            score += 10

        # Sentence-like structure
        sentences = re.findall(r'[.!?。！？]\s', content)
        if len(sentences) > 3:
            score += 15

        # Low noise (no excessive special chars)
        alnum_ratio = sum(c.isalnum() or c.isspace() for c in content[:2000]) / max(len(content[:2000]), 1)
        if alnum_ratio > 0.7:
            score += 15

        return min(score, 100)

    @staticmethod
    def _clean(text: str) -> str:
        """Clean extracted text."""
        if not text:
            return ""
        # Collapse excessive blank lines
        text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
        # Remove leading/trailing whitespace per line
        lines = [line.strip() for line in text.split('\n')]
        text = '\n'.join(lines)
        return text.strip()
