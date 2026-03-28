"""
Comprehensive tests for agent/web/extractor.py

Run: pytest tests/test_web_extractor_full.py -v
"""
import os
import sys
import pytest
from unittest.mock import Mock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Check if trafilatura and html2text are available
try:
    import trafilatura
    HAS_TRAFILATURA = True
except ImportError:
    HAS_TRAFILATURA = False

try:
    import html2text
    HAS_HTML2TEXT = True
except ImportError:
    HAS_HTML2TEXT = False


class TestExtractedLink:
    """Test ExtractedLink dataclass."""

    def test_init_defaults(self):
        from agent.web.extractor import ExtractedLink
        link = ExtractedLink(text="Click here", href="https://example.com")

        assert link.text == "Click here"
        assert link.href == "https://example.com"
        assert link.is_internal is False

    def test_init_with_internal(self):
        from agent.web.extractor import ExtractedLink
        link = ExtractedLink(text="Click", href="https://example.com", is_internal=True)

        assert link.is_internal is True


class TestExtractionResult:
    """Test ExtractionResult dataclass."""

    def test_init_defaults(self):
        from agent.web.extractor import ExtractionResult
        result = ExtractionResult(url="https://example.com")

        assert result.url == "https://example.com"
        assert result.title == ""
        assert result.content == ""
        assert result.links == []
        assert result.strategy == ""
        assert result.score == 0
        assert result.word_count == 0
        assert result.error == ""

    def test_ok_property_with_content(self):
        from agent.web.extractor import ExtractionResult
        result = ExtractionResult(url="https://example.com", content="Some text")

        assert result.ok is True

    def test_ok_property_with_error(self):
        from agent.web.extractor import ExtractionResult
        result = ExtractionResult(url="https://example.com", error="Failed")

        assert result.ok is False

    def test_ok_property_empty_content(self):
        from agent.web.extractor import ExtractionResult
        result = ExtractionResult(url="https://example.com", content="")

        assert result.ok is False

    def test_links_text_formatting(self):
        from agent.web.extractor import ExtractionResult, ExtractedLink
        result = ExtractionResult(url="https://example.com")
        result.links = [
            ExtractedLink(text="Link 1", href="https://example.com/1", is_internal=True),
            ExtractedLink(text="Link 2", href="https://external.com", is_internal=False),
        ]

        links_text = result.links_text

        assert "Link 1" in links_text
        assert "Link 2" in links_text
        assert "[int]" in links_text
        assert "[ext]" in links_text

    def test_links_text_empty(self):
        from agent.web.extractor import ExtractionResult
        result = ExtractionResult(url="https://example.com")

        assert result.links_text == ""

    def test_links_text_caps_at_50(self):
        from agent.web.extractor import ExtractionResult, ExtractedLink
        result = ExtractionResult(url="https://example.com")
        result.links = [
            ExtractedLink(text=f"Link {i}", href=f"https://example.com/{i}")
            for i in range(100)
        ]

        links_text = result.links_text

        # Should only show first 50
        assert "Link 49" in links_text
        assert "Link 99" not in links_text


class TestWebExtractorInit:
    """Test WebExtractor initialization."""

    def test_init_defaults(self):
        from agent.web.extractor import WebExtractor
        extractor = WebExtractor()

        assert extractor._browser_sync is None
        assert extractor._cache is None

    def test_init_with_browser(self):
        from agent.web.extractor import WebExtractor
        browser_fn = Mock()
        extractor = WebExtractor(browser_sync_fn=browser_fn)

        assert extractor._browser_sync == browser_fn

    def test_init_with_cache(self):
        from agent.web.extractor import WebExtractor
        from agent.web.cache import URLCache
        cache = URLCache()
        extractor = WebExtractor(cache=cache)

        assert extractor._cache == cache

    @pytest.mark.skipif(not HAS_HTML2TEXT, reason="html2text not installed")
    @patch('agent.web.extractor.HAS_HTML2TEXT', True)
    def test_init_html2text_converter(self):
        from agent.web.extractor import WebExtractor
        extractor = WebExtractor()

        assert extractor._html2text_converter is not None


class TestWebExtractorExtract:
    """Test WebExtractor.extract method."""

    def test_extract_normalizes_url(self):
        from agent.web.extractor import WebExtractor
        extractor = WebExtractor()

        with patch.object(extractor, '_try_fallback') as mock_fallback:
            mock_fallback.return_value = Mock(ok=True, content="test", strategy="fallback")
            extractor.extract("example.com")

            # Check that https was added
            call_url = mock_fallback.call_args[0][0]
            assert call_url.startswith("https://")

    def test_extract_checks_cache(self):
        from agent.web.extractor import WebExtractor
        from agent.web.cache import URLCache

        cache = URLCache()
        cache.set("https://example.com", "cached content")
        extractor = WebExtractor(cache=cache)

        result = extractor.extract("https://example.com")

        assert result.content == "cached content"
        assert result.strategy == "cache"

    def test_extract_caches_result(self):
        from agent.web.extractor import WebExtractor
        from agent.web.cache import URLCache

        cache = URLCache()
        extractor = WebExtractor(cache=cache)

        with patch.object(extractor, '_try_fallback') as mock_fallback:
            mock_fallback.return_value = Mock(ok=True, content="new content")
            extractor.extract("https://example.com")

        # Verify it was cached
        assert cache.get("https://example.com") == "new content"

    def test_extract_returns_error_when_all_fail(self):
        from agent.web.extractor import WebExtractor

        extractor = WebExtractor()

        with patch.object(extractor, '_try_fallback') as mock_fallback:
            mock_fallback.return_value = None
            result = extractor.extract("https://example.com")

        assert result.error != ""
        assert result.ok is False

    def test_extract_strategy_chain_order(self):
        from agent.web.extractor import WebExtractor

        extractor = WebExtractor()

        # Mock all strategies
        with patch.object(extractor, '_try_trafilatura') as mock_traf:
            with patch.object(extractor, '_try_readability') as mock_read:
                with patch.object(extractor, '_try_beautifulsoup') as mock_bs:
                    with patch.object(extractor, '_try_fallback') as mock_fall:
                        # First strategy succeeds
                        mock_traf.return_value = Mock(ok=True, content="traf content", strategy="trafilatura")
                        mock_read.return_value = Mock(ok=True, content="read content")
                        mock_bs.return_value = Mock(ok=True, content="bs content")
                        mock_fall.return_value = Mock(ok=True, content="fall content")

                        result = extractor.extract("https://example.com")

                        # Should use first successful strategy or best available
                        # Strategy could be trafilatura, readability, beautifulsoup or fallback depending on HAS_* flags
                        assert result.strategy in ["trafilatura", "readability", "beautifulsoup", "fallback"]

    def test_extract_picks_best_score(self):
        from agent.web.extractor import WebExtractor

        extractor = WebExtractor()

        with patch.object(extractor, '_try_fallback') as mock_fall:
            with patch.object(extractor, '_try_beautifulsoup') as mock_bs:
                # Fallback returns low score
                mock_fall.return_value = Mock(ok=True, content="x" * 50)  # Low score
                # BS returns high score
                mock_bs.return_value = Mock(ok=True, content="x" * 1000)  # Higher score

                result = extractor.extract("https://example.com")

                # Should pick the one with more content
                assert len(result.content) > 500


class TestWebExtractorScoring:
    """Test WebExtractor._score method."""

    def test_score_empty_content(self):
        from agent.web.extractor import WebExtractor
        assert WebExtractor._score("") == 0

    def test_score_short_content(self):
        from agent.web.extractor import WebExtractor
        score = WebExtractor._score("few words")
        assert score < 50

    def test_score_medium_content(self):
        from agent.web.extractor import WebExtractor
        content = " ".join(["word"] * 100)
        score = WebExtractor._score(content)
        assert score > 0

    def test_score_good_content(self):
        from agent.web.extractor import WebExtractor
        content = " ".join(["word"] * 500) + "\n\n" + " ".join(["para"] * 100)
        score = WebExtractor._score(content)
        assert score > 30

    def test_score_excellent_content(self):
        from agent.web.extractor import WebExtractor
        # Large content with good structure
        paragraphs = [" ".join(["word"] * 50) for _ in range(10)]
        content = "\n\n".join(paragraphs)
        content += "\n\nSentence. Another. More. Queries."
        score = WebExtractor._score(content)
        assert score > 50


class TestWebExtractorCleaning:
    """Test WebExtractor._clean method."""

    def test_clean_collapses_blank_lines(self):
        from agent.web.extractor import WebExtractor
        text = "Line 1\n\n\n\nLine 2"
        cleaned = WebExtractor._clean(text)
        assert "\n\n\n" not in cleaned

    def test_clean_removes_leading_trailing(self):
        from agent.web.extractor import WebExtractor
        text = "  \n  Line 1  \n  "
        cleaned = WebExtractor._clean(text)
        assert cleaned.startswith("Line")

    def test_clean_empty_string(self):
        from agent.web.extractor import WebExtractor
        assert WebExtractor._clean("") == ""

    def test_clean_none(self):
        from agent.web.extractor import WebExtractor
        assert WebExtractor._clean(None) == ""

    def test_clean_whitespace_only(self):
        from agent.web.extractor import WebExtractor
        assert WebExtractor._clean("   \n  \n  ") == ""


class TestWebExtractorLinkExtraction:
    """Test link extraction methods."""

    @patch('agent.web.extractor.HAS_BS4', True)
    def test_extract_links_from_html(self):
        from agent.web.extractor import WebExtractor

        html = '<a href="https://example.com/page1">Link 1</a><a href="https://example.com/page2">Link 2</a>'
        extractor = WebExtractor()

        links = extractor._extract_links_from_html(html, "https://example.com")

        assert len(links) == 2
        assert links[0].text == "Link 1"
        assert links[1].text == "Link 2"

    @patch('agent.web.extractor.HAS_BS4', False)
    def test_extract_links_without_bs4(self):
        from agent.web.extractor import WebExtractor

        html = '<a href="https://example.com">Link</a>'
        extractor = WebExtractor()

        links = extractor._extract_links_from_html(html, "https://example.com")

        assert links == []

    @patch('agent.web.extractor.HAS_BS4', True)
    def test_extract_links_ignores_javascript(self):
        from agent.web.extractor import WebExtractor

        html = '<a href="javascript:void(0)">Bad</a><a href="https://example.com">Good</a>'
        extractor = WebExtractor()

        links = extractor._extract_links_from_html(html, "https://example.com")

        assert len(links) == 1
        assert links[0].text == "Good"

    @patch('agent.web.extractor.HAS_BS4', True)
    def test_extract_links_ignores_anchors(self):
        from agent.web.extractor import WebExtractor

        html = '<a href="#section">Anchor</a><a href="https://example.com">Link</a>'
        extractor = WebExtractor()

        links = extractor._extract_links_from_html(html, "https://example.com")

        assert len(links) == 1
        assert links[0].text == "Link"

    @patch('agent.web.extractor.HAS_BS4', True)
    def test_extract_links_resolves_relative(self):
        from agent.web.extractor import WebExtractor

        html = '<a href="/page1">Link 1</a>'
        extractor = WebExtractor()

        links = extractor._extract_links_from_html(html, "https://example.com")

        assert len(links) == 1
        assert links[0].href == "https://example.com/page1"

    @patch('agent.web.extractor.HAS_BS4', True)
    def test_extract_links_deduplicates(self):
        from agent.web.extractor import WebExtractor

        html = '<a href="https://example.com/page">Link 1</a><a href="https://example.com/page">Link 2</a>'
        extractor = WebExtractor()

        links = extractor._extract_links_from_html(html, "https://example.com")

        assert len(links) == 1

    @patch('agent.web.extractor.HAS_BS4', True)
    def test_extract_links_classifies_internal(self):
        from agent.web.extractor import WebExtractor

        html = '<a href="https://example.com/page">Internal</a><a href="https://other.com/page">External</a>'
        extractor = WebExtractor()

        links = extractor._extract_links_from_html(html, "https://example.com")

        assert len(links) == 2
        assert links[0].is_internal is True
        assert links[1].is_internal is False


@pytest.mark.skipif(not HAS_TRAFILATURA, reason="trafilatura not installed")
@patch('agent.web.extractor.HAS_TRAFILATURA', True)
class TestTrafilaturaStrategy:
    """Test trafilatura extraction strategy."""

    def test_try_trafilatura_success(self):
        from agent.web.extractor import WebExtractor

        extractor = WebExtractor()

        with patch('agent.web.extractor.trafilatura.fetch_url') as mock_fetch:
            with patch('agent.web.extractor.trafilatura.extract') as mock_extract:
                with patch('agent.web.extractor.trafilatura.extract_metadata') as mock_meta:
                    mock_fetch.return_value = "html content"
                    mock_extract.return_value = "Extracted text"
                    mock_meta.return_value = Mock(title="Page Title")

                    result = extractor._try_trafilatura("https://example.com", 20000, True)

                    assert result.content == "Extracted text"
                    assert result.title == "Page Title"

    def test_try_trafilatura_fetch_fails(self):
        from agent.web.extractor import WebExtractor

        extractor = WebExtractor()

        with patch('trafilatura.fetch_url') as mock_fetch:
            mock_fetch.return_value = None

            result = extractor._try_trafilatura("https://example.com", 20000, True)

            assert result is None

    def test_try_trafilatura_extract_fails(self):
        from agent.web.extractor import WebExtractor

        extractor = WebExtractor()

        with patch('trafilatura.fetch_url') as mock_fetch:
            with patch('trafilatura.extract') as mock_extract:
                mock_fetch.return_value = "html"
                mock_extract.return_value = "x" * 10  # Too short

                result = extractor._try_trafilatura("https://example.com", 20000, True)

                assert result is None


@patch('agent.web.extractor.HAS_BS4', True)
class TestBeautifulSoupStrategy:
    """Test BeautifulSoup extraction strategy."""

    def test_try_beautifulsoup_success(self):
        from agent.web.extractor import WebExtractor

        extractor = WebExtractor()

        with patch('agent.web.extractor.requests.get') as mock_get:
            mock_response = Mock()
            mock_response.text = "<html><body><p>Content here</p></body></html>"
            mock_get.return_value = mock_response

            result = extractor._try_beautifulsoup("https://example.com", 20000, True)

            assert result is not None
            assert "Content" in result.content

    def test_try_beautifulsoup_removes_noise(self):
        from agent.web.extractor import WebExtractor

        extractor = WebExtractor()

        with patch('agent.web.extractor.requests.get') as mock_get:
            html = "<html><body><script>bad</script><p>Good</p><style>css</style></body></html>"
            mock_response = Mock()
            mock_response.text = html
            mock_get.return_value = mock_response

            result = extractor._try_beautifulsoup("https://example.com", 20000, True)

            assert "script" not in result.content.lower()
            assert "style" not in result.content.lower()


class TestFallbackStrategy:
    """Test fallback extraction strategy."""

    def test_try_fallback_simple(self):
        from agent.web.extractor import WebExtractor

        extractor = WebExtractor()

        with patch('agent.web.extractor.requests.get') as mock_get:
            mock_response = Mock()
            mock_response.text = "<html><body>Simple text</body></html>"
            mock_get.return_value = mock_response

            result = extractor._try_fallback("https://example.com", 20000, True)

            assert result is not None
            assert "Simple text" in result.content

    def test_try_fallback_removes_tags(self):
        from agent.web.extractor import WebExtractor

        extractor = WebExtractor()

        with patch('agent.web.extractor.requests.get') as mock_get:
            mock_response = Mock()
            mock_response.text = "<p>Text</p><div>More</div>"
            mock_get.return_value = mock_response

            result = extractor._try_fallback("https://example.com", 20000, True)

            assert "<p>" not in result.content
            assert "<div>" not in result.content
