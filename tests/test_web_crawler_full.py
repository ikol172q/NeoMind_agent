"""
Comprehensive tests for agent/web/crawler.py

Run: pytest tests/test_web_crawler_full.py -v
"""
import os
import sys
import pytest
from unittest.mock import Mock, patch
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestCrawlResult:
    """Test CrawlResult dataclass."""

    def test_init_defaults(self):
        from agent.web.crawler import CrawlResult
        result = CrawlResult(url="https://example.com")

        assert result.url == "https://example.com"
        assert result.title == ""
        assert result.content == ""
        assert result.word_count == 0
        assert result.depth == 0
        assert result.strategy == ""
        assert result.error == ""

    def test_ok_property_with_content(self):
        from agent.web.crawler import CrawlResult
        result = CrawlResult(url="https://example.com", content="Some text")

        assert result.ok is True

    def test_ok_property_with_error(self):
        from agent.web.crawler import CrawlResult
        result = CrawlResult(url="https://example.com", error="Failed to fetch")

        assert result.ok is False

    def test_ok_property_no_content(self):
        from agent.web.crawler import CrawlResult
        result = CrawlResult(url="https://example.com")

        assert result.ok is False


class TestCrawlReport:
    """Test CrawlReport dataclass."""

    def test_init(self):
        from agent.web.crawler import CrawlReport
        report = CrawlReport(start_url="https://example.com")

        assert report.start_url == "https://example.com"
        assert report.pages == []
        assert report.total_words == 0
        assert report.elapsed_seconds == 0
        assert report.max_depth_reached == 0

    def test_ok_pages_property(self):
        from agent.web.crawler import CrawlReport, CrawlResult
        report = CrawlReport(start_url="https://example.com")

        ok_page = CrawlResult(url="https://example.com/1", content="text")
        error_page = CrawlResult(url="https://example.com/2", error="Failed")
        no_content = CrawlResult(url="https://example.com/3", content="")

        report.pages = [ok_page, error_page, no_content]

        assert len(report.ok_pages) == 1
        assert report.ok_pages[0].url == "https://example.com/1"

    def test_summary_output(self):
        from agent.web.crawler import CrawlReport, CrawlResult
        report = CrawlReport(start_url="https://example.com")

        page1 = CrawlResult(
            url="https://example.com",
            title="Home",
            content="Welcome to the site",
            word_count=50,
            depth=0,
        )
        report.pages = [page1]
        report.total_words = 50
        report.elapsed_seconds = 1.5
        report.max_depth_reached = 0

        summary = report.summary()

        assert "example.com" in summary
        assert "Home" in summary
        assert "50" in summary

    def test_summary_no_pages(self):
        from agent.web.crawler import CrawlReport
        report = CrawlReport(start_url="https://example.com")

        summary = report.summary()

        assert "no pages" in summary.lower()

    def test_all_content(self):
        from agent.web.crawler import CrawlReport, CrawlResult
        report = CrawlReport(start_url="https://example.com")

        page1 = CrawlResult(
            url="https://example.com/1",
            title="Page 1",
            content="Content 1",
        )
        page2 = CrawlResult(
            url="https://example.com/2",
            title="Page 2",
            content="Content 2",
        )
        report.pages = [page1, page2]

        all_content = report.all_content()

        assert "Page 1" in all_content
        assert "Content 1" in all_content
        assert "Page 2" in all_content


class TestBFSCrawler:
    """Test BFSCrawler class."""

    def test_init(self):
        from agent.web.crawler import BFSCrawler
        from agent.web.extractor import WebExtractor
        from agent.web.cache import URLCache

        extractor = WebExtractor()
        cache = URLCache()
        crawler = BFSCrawler(extractor, cache, delay=0.5)

        assert crawler.extractor == extractor
        assert crawler.cache == cache
        assert crawler.delay == 0.5

    def test_init_default_cache(self):
        from agent.web.crawler import BFSCrawler
        from agent.web.extractor import WebExtractor

        extractor = WebExtractor()
        crawler = BFSCrawler(extractor)

        assert crawler.cache is not None

    def test_normalize_url_removes_fragment(self):
        from agent.web.crawler import BFSCrawler

        url = "https://example.com/page#section"
        normalized = BFSCrawler._normalize_url(url)

        assert "#" not in normalized

    def test_normalize_url_removes_trailing_slash(self):
        from agent.web.crawler import BFSCrawler

        url = "https://example.com/page/"
        normalized = BFSCrawler._normalize_url(url)

        assert normalized == "https://example.com/page"

    def test_normalize_url_keeps_root_slash(self):
        from agent.web.crawler import BFSCrawler

        url = "https://example.com/"
        normalized = BFSCrawler._normalize_url(url)

        assert normalized == "https://example.com/"

    def test_should_skip_image_extensions(self):
        from agent.web.crawler import BFSCrawler

        assert BFSCrawler._should_skip("https://example.com/image.png") is True
        assert BFSCrawler._should_skip("https://example.com/image.jpg") is True
        assert BFSCrawler._should_skip("https://example.com/image.gif") is True
        assert BFSCrawler._should_skip("https://example.com/image.webp") is True

    def test_should_skip_media_extensions(self):
        from agent.web.crawler import BFSCrawler

        assert BFSCrawler._should_skip("https://example.com/video.mp4") is True
        assert BFSCrawler._should_skip("https://example.com/audio.mp3") is True
        assert BFSCrawler._should_skip("https://example.com/file.pdf") is True
        assert BFSCrawler._should_skip("https://example.com/file.zip") is True

    def test_should_skip_css_js(self):
        from agent.web.crawler import BFSCrawler

        assert BFSCrawler._should_skip("https://example.com/style.css") is True
        assert BFSCrawler._should_skip("https://example.com/script.js") is True

    def test_should_skip_auth_urls(self):
        from agent.web.crawler import BFSCrawler

        assert BFSCrawler._should_skip("https://example.com/login") is True
        assert BFSCrawler._should_skip("https://example.com/signup") is True
        assert BFSCrawler._should_skip("https://example.com/register") is True
        assert BFSCrawler._should_skip("https://example.com/auth") is True

    def test_should_skip_special_paths(self):
        from agent.web.crawler import BFSCrawler

        assert BFSCrawler._should_skip("https://example.com/wp-admin") is True
        assert BFSCrawler._should_skip("https://example.com/cart") is True
        assert BFSCrawler._should_skip("https://example.com/checkout") is True
        assert BFSCrawler._should_skip("https://example.com/account") is True

    def test_should_allow_content_urls(self):
        from agent.web.crawler import BFSCrawler

        assert BFSCrawler._should_skip("https://example.com/page") is False
        assert BFSCrawler._should_skip("https://example.com/blog/article") is False
        assert BFSCrawler._should_skip("https://example.com/docs") is False

    @patch('agent.web.crawler.time')
    def test_crawl_single_page(self, mock_time):
        from agent.web.crawler import BFSCrawler
        from agent.web.extractor import WebExtractor, ExtractionResult

        # Mock time
        mock_time.time.return_value = 0
        mock_time.sleep = Mock()

        # Mock extractor
        extractor = Mock(spec=WebExtractor)
        extractor.extract = Mock(return_value=ExtractionResult(
            url="https://example.com",
            title="Example",
            content="Example content",
            word_count=2,
        ))

        crawler = BFSCrawler(extractor, delay=0)
        report = crawler.crawl("https://example.com", max_depth=0, max_pages=10)

        assert len(report.ok_pages) == 1
        assert report.ok_pages[0].title == "Example"

    @patch('agent.web.crawler.time')
    def test_crawl_follow_links(self, mock_time):
        from agent.web.crawler import BFSCrawler, CrawlResult
        from agent.web.extractor import WebExtractor, ExtractionResult, ExtractedLink

        mock_time.time.return_value = 0
        mock_time.sleep = Mock()

        extractor = Mock(spec=WebExtractor)

        # First page returns links
        result1 = ExtractionResult(
            url="https://example.com",
            title="Home",
            content="Home content",
            word_count=2,
            links=[
                ExtractedLink(text="Page 1", href="https://example.com/page1", is_internal=True),
                ExtractedLink(text="Page 2", href="https://example.com/page2", is_internal=True),
            ],
        )

        # Following pages
        result2 = ExtractionResult(
            url="https://example.com/page1",
            title="Page 1",
            content="Page 1 content",
            word_count=3,
        )

        result3 = ExtractionResult(
            url="https://example.com/page2",
            title="Page 2",
            content="Page 2 content",
            word_count=3,
        )

        extractor.extract.side_effect = [result1, result2, result3]

        crawler = BFSCrawler(extractor, delay=0)
        report = crawler.crawl("https://example.com", max_depth=1, max_pages=10)

        assert len(report.ok_pages) == 3
        assert report.total_words >= 8

    @patch('agent.web.crawler.time')
    def test_crawl_respects_max_depth(self, mock_time):
        from agent.web.crawler import BFSCrawler
        from agent.web.extractor import WebExtractor, ExtractionResult, ExtractedLink

        mock_time.time.return_value = 0
        mock_time.sleep = Mock()

        extractor = Mock(spec=WebExtractor)

        # All pages return links (infinite loop potential)
        def extract_fn(url, **kwargs):
            return ExtractionResult(
                url=url,
                content="content",
                word_count=1,
                links=[
                    ExtractedLink(text="Next", href="https://example.com/page" + str(len(url)), is_internal=True),
                ],
            )

        extractor.extract.side_effect = extract_fn

        crawler = BFSCrawler(extractor, delay=0)
        report = crawler.crawl("https://example.com", max_depth=1, max_pages=100)

        # Should respect max_depth=1, so only 1 level of links
        assert report.max_depth_reached <= 1

    @patch('agent.web.crawler.time')
    def test_crawl_respects_max_pages(self, mock_time):
        from agent.web.crawler import BFSCrawler
        from agent.web.extractor import WebExtractor, ExtractionResult, ExtractedLink

        mock_time.time.return_value = 0
        mock_time.sleep = Mock()

        extractor = Mock(spec=WebExtractor)

        # All pages return links
        call_count = [0]

        def extract_fn(url, **kwargs):
            call_count[0] += 1
            return ExtractionResult(
                url=url,
                content="content",
                word_count=1,
                links=[
                    ExtractedLink(text="Next", href=f"https://example.com/page{call_count[0]}", is_internal=True),
                ],
            )

        extractor.extract.side_effect = extract_fn

        crawler = BFSCrawler(extractor, delay=0)
        report = crawler.crawl("https://example.com", max_depth=10, max_pages=5)

        # Should respect max_pages=5
        assert len(report.pages) <= 5

    @patch('agent.web.crawler.time')
    def test_crawl_blocks_external_links(self, mock_time):
        from agent.web.crawler import BFSCrawler
        from agent.web.extractor import WebExtractor, ExtractionResult, ExtractedLink

        mock_time.time.return_value = 0
        mock_time.sleep = Mock()

        extractor = Mock(spec=WebExtractor)

        # First page returns both internal and external links
        result = ExtractionResult(
            url="https://example.com",
            content="content",
            word_count=1,
            links=[
                ExtractedLink(text="Internal", href="https://example.com/page1", is_internal=True),
                ExtractedLink(text="External", href="https://other.com/page", is_internal=False),
            ],
        )

        extractor.extract.return_value = result

        crawler = BFSCrawler(extractor, delay=0)
        report = crawler.crawl("https://example.com", max_depth=1, max_pages=100, allow_external=False)

        # Should only crawl internal links, not external
        # Will crawl root page (1st call), then the internal link found (2nd call)
        # External link should be blocked
        assert extractor.extract.call_count == 2

    @patch('agent.web.crawler.time')
    def test_crawl_allows_external_links(self, mock_time):
        from agent.web.crawler import BFSCrawler
        from agent.web.extractor import WebExtractor, ExtractionResult, ExtractedLink

        mock_time.time.return_value = 0
        mock_time.sleep = Mock()

        extractor = Mock(spec=WebExtractor)

        # First page returns links
        result1 = ExtractionResult(
            url="https://example.com",
            content="content",
            word_count=1,
            links=[
                ExtractedLink(text="External", href="https://other.com/page", is_internal=False),
            ],
        )

        # External page result
        result2 = ExtractionResult(
            url="https://other.com/page",
            content="other content",
            word_count=2,
        )

        extractor.extract.side_effect = [result1, result2]

        crawler = BFSCrawler(extractor, delay=0)
        report = crawler.crawl("https://example.com", max_depth=1, max_pages=100, allow_external=True)

        # Should crawl external links
        assert extractor.extract.call_count == 2

    @patch('agent.web.crawler.time')
    def test_crawl_deduplication(self, mock_time):
        from agent.web.crawler import BFSCrawler
        from agent.web.extractor import WebExtractor, ExtractionResult, ExtractedLink

        mock_time.time.return_value = 0
        mock_time.sleep = Mock()

        extractor = Mock(spec=WebExtractor)

        # Both pages link to the same page
        result1 = ExtractionResult(
            url="https://example.com",
            content="content",
            word_count=1,
            links=[
                ExtractedLink(text="Shared", href="https://example.com/shared", is_internal=True),
                ExtractedLink(text="Page 1", href="https://example.com/page1", is_internal=True),
            ],
        )

        result2 = ExtractionResult(
            url="https://example.com/page1",
            content="page1",
            word_count=1,
            links=[
                ExtractedLink(text="Shared", href="https://example.com/shared", is_internal=True),
            ],
        )

        result3 = ExtractionResult(
            url="https://example.com/shared",
            content="shared",
            word_count=1,
        )

        extractor.extract.side_effect = [result1, result2, result3]

        crawler = BFSCrawler(extractor, delay=0)
        report = crawler.crawl("https://example.com", max_depth=2, max_pages=100)

        # Should crawl root, page1, and shared (not duplicate shared)
        assert extractor.extract.call_count == 3

    def test_crawl_adds_https_to_url(self):
        from agent.web.crawler import BFSCrawler
        from agent.web.extractor import WebExtractor, ExtractionResult

        extractor = Mock(spec=WebExtractor)
        extractor.extract = Mock(return_value=ExtractionResult(
            url="https://example.com",
            content="content",
            word_count=1,
        ))

        crawler = BFSCrawler(extractor, delay=0)
        report = crawler.crawl("example.com", max_depth=0)

        # Check that https was added
        assert extractor.extract.call_args[0][0].startswith("https://")

    @patch('agent.web.crawler.time')
    def test_crawl_elapsed_time(self, mock_time):
        from agent.web.crawler import BFSCrawler
        from agent.web.extractor import WebExtractor, ExtractionResult

        mock_time.time.side_effect = [0, 5]  # Simulate 5 second crawl
        mock_time.sleep = Mock()

        extractor = Mock(spec=WebExtractor)
        extractor.extract = Mock(return_value=ExtractionResult(
            url="https://example.com",
            content="content",
            word_count=1,
        ))

        crawler = BFSCrawler(extractor, delay=0)
        report = crawler.crawl("https://example.com", max_depth=0)

        assert report.elapsed_seconds == 5
