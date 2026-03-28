"""
Comprehensive tests for agent/browser/daemon.py

Run: pytest tests/test_browser_daemon_full.py -v
"""
import os
import sys
import pytest
import json
import asyncio
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, AsyncMock
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Check if playwright is available
try:
    import playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


class TestSnapshotRef:
    """Test SnapshotRef class for managing element references."""

    def test_init(self):
        from agent.browser.daemon import SnapshotRef
        ref = SnapshotRef()
        assert ref._counter == 0
        assert len(ref._refs) == 0

    def test_add_and_get(self):
        from agent.browser.daemon import SnapshotRef
        ref = SnapshotRef()
        locator = Mock()

        ref_id = ref.add(locator)
        assert ref_id == "@e1"
        assert ref.get(ref_id) == locator

    def test_add_increments_counter(self):
        from agent.browser.daemon import SnapshotRef
        ref = SnapshotRef()
        locator1 = Mock()
        locator2 = Mock()

        ref1 = ref.add(locator1)
        ref2 = ref.add(locator2)

        assert ref1 == "@e1"
        assert ref2 == "@e2"
        assert ref.count == 2

    def test_get_nonexistent(self):
        from agent.browser.daemon import SnapshotRef
        ref = SnapshotRef()
        assert ref.get("@e999") is None

    def test_clear(self):
        from agent.browser.daemon import SnapshotRef
        ref = SnapshotRef()
        locator = Mock()
        ref.add(locator)

        ref.clear()
        assert ref.count == 0
        assert ref._counter == 0
        assert ref.get("@e1") is None

    def test_count_property(self):
        from agent.browser.daemon import SnapshotRef
        ref = SnapshotRef()
        assert ref.count == 0

        ref.add(Mock())
        assert ref.count == 1

        ref.add(Mock())
        ref.add(Mock())
        assert ref.count == 3


class TestBrowserDaemonBasics:
    """Test BrowserDaemon initialization and basic properties."""

    def test_init(self):
        from agent.browser.daemon import BrowserDaemon
        daemon = BrowserDaemon()

        assert daemon._playwright is None
        assert daemon._browser is None
        assert daemon._context is None
        assert daemon._page is None
        assert daemon._running is False
        assert len(daemon._tabs) == 0
        assert daemon._active_tab == ""
        assert daemon.is_running is False

    def test_is_running_property(self):
        from agent.browser.daemon import BrowserDaemon
        daemon = BrowserDaemon()

        assert daemon.is_running is False
        daemon._running = True
        assert daemon.is_running is False  # Still False because _browser is None

        daemon._browser = Mock()
        assert daemon.is_running is True

    def test_data_dir_configuration(self):
        from agent.browser.daemon import BrowserDaemon
        daemon = BrowserDaemon()

        assert daemon.DATA_DIR.name == "browser"
        assert ".neomind" in str(daemon.DATA_DIR)


@pytest.mark.asyncio
@pytest.mark.skipif(not HAS_PLAYWRIGHT, reason="playwright not installed")
class TestBrowserDaemonStartStop:
    """Test start/stop lifecycle methods."""

    @patch('agent.browser.daemon.HAS_PLAYWRIGHT', False)
    async def test_start_without_playwright(self):
        from agent.browser.daemon import BrowserDaemon
        daemon = BrowserDaemon()

        with pytest.raises(ImportError, match="playwright not installed"):
            await daemon.start()

    @patch('agent.browser.daemon.HAS_PLAYWRIGHT', True)
    @patch('playwright.async_api.async_playwright')
    async def test_start_creates_context(self, mock_playwright):
        from agent.browser.daemon import BrowserDaemon

        # Mock playwright context
        mock_pw = AsyncMock()
        mock_context = AsyncMock()
        mock_page = AsyncMock()

        mock_pw.chromium.launch_persistent_context = AsyncMock(return_value=mock_context)
        mock_context.pages = [mock_page]
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_pw.stop = AsyncMock()

        mock_playwright.return_value.__aenter__.return_value = mock_pw

        daemon = BrowserDaemon()
        await daemon.start()

        assert daemon._running is True
        assert daemon._page is not None
        assert len(daemon._tabs) == 1

    @patch('agent.browser.daemon.HAS_PLAYWRIGHT', True)
    @patch('playwright.async_api.async_playwright')
    async def test_start_idempotent(self, mock_playwright):
        from agent.browser.daemon import BrowserDaemon

        mock_pw = AsyncMock()
        mock_context = AsyncMock()
        mock_page = AsyncMock()

        mock_pw.chromium.launch_persistent_context = AsyncMock(return_value=mock_context)
        mock_context.pages = [mock_page]
        mock_pw.stop = AsyncMock()

        mock_playwright.return_value.__aenter__.return_value = mock_pw

        daemon = BrowserDaemon()
        await daemon.start()
        await daemon.start()  # Second call should be no-op

        # Should only be called once
        assert mock_pw.chromium.launch_persistent_context.call_count == 1

    @patch('agent.browser.daemon.HAS_PLAYWRIGHT', True)
    @patch('playwright.async_api.async_playwright')
    async def test_stop_closes_context(self, mock_playwright):
        from agent.browser.daemon import BrowserDaemon

        mock_pw = AsyncMock()
        mock_context = AsyncMock()
        mock_page = AsyncMock()

        mock_pw.chromium.launch_persistent_context = AsyncMock(return_value=mock_context)
        mock_context.pages = [mock_page]
        mock_context.close = AsyncMock()
        mock_pw.stop = AsyncMock()

        mock_playwright.return_value.__aenter__.return_value = mock_pw

        daemon = BrowserDaemon()
        await daemon.start()
        await daemon.stop()

        assert daemon._running is False
        assert daemon._context is None
        assert daemon._playwright is None
        assert daemon._page is None
        mock_context.close.assert_called_once()
        mock_pw.stop.assert_called_once()


@pytest.mark.asyncio
class TestBrowserDaemonNavigation:
    """Test navigation commands."""

    async def _setup_daemon(self):
        """Helper to create a mock daemon for testing."""
        from agent.browser.daemon import BrowserDaemon
        daemon = BrowserDaemon()
        daemon._running = True
        daemon._page = AsyncMock()
        daemon._page.title = AsyncMock(return_value="Test Page")
        daemon._page.url = "https://example.com"
        daemon._page.go_back = AsyncMock()
        daemon._page.go_forward = AsyncMock()
        daemon._page.reload = AsyncMock()
        return daemon

    async def test_goto_command(self):
        daemon = await self._setup_daemon()
        daemon._page.goto = AsyncMock()

        result = await daemon.execute("goto", ["https://example.com"])

        daemon._page.goto.assert_called_once()
        assert "Navigated to" in result or "Title" in result

    async def test_goto_adds_https(self):
        daemon = await self._setup_daemon()
        daemon._page.goto = AsyncMock()

        await daemon.execute("goto", ["example.com"])

        call_args = daemon._page.goto.call_args
        assert "https://" in call_args[0][0]

    async def test_back_command(self):
        daemon = await self._setup_daemon()

        result = await daemon.execute("back", [])

        daemon._page.go_back.assert_called_once()
        assert "back" in result.lower()

    async def test_forward_command(self):
        daemon = await self._setup_daemon()

        result = await daemon.execute("forward", [])

        daemon._page.go_forward.assert_called_once()
        assert "forward" in result.lower()

    async def test_reload_command(self):
        daemon = await self._setup_daemon()

        result = await daemon.execute("reload", [])

        daemon._page.reload.assert_called_once()
        assert "reload" in result.lower()


@pytest.mark.asyncio
class TestBrowserDaemonReading:
    """Test content reading commands."""

    async def _setup_daemon(self):
        from agent.browser.daemon import BrowserDaemon
        daemon = BrowserDaemon()
        daemon._running = True
        daemon._page = AsyncMock()
        daemon._page.url = "https://example.com"
        return daemon

    async def test_text_command(self):
        daemon = await self._setup_daemon()
        daemon._page.inner_text = AsyncMock(return_value="Some text content")

        result = await daemon.execute("text", [])

        assert "Some text content" in result
        daemon._page.inner_text.assert_called_once_with("body")

    async def test_text_caps_output(self):
        daemon = await self._setup_daemon()
        long_text = "A" * 15000
        daemon._page.inner_text = AsyncMock(return_value=long_text)

        result = await daemon.execute("text", [])

        assert len(result) <= 10100  # 10K chars + some overhead

    async def test_html_command(self):
        daemon = await self._setup_daemon()
        daemon._page.inner_html = AsyncMock(return_value="<div>content</div>")

        result = await daemon.execute("html", [])

        assert "div" in result
        daemon._page.inner_html.assert_called_once_with("body")

    async def test_html_with_selector(self):
        daemon = await self._setup_daemon()
        daemon._page.inner_html = AsyncMock(return_value="<p>test</p>")

        result = await daemon.execute("html", [".container"])

        daemon._page.inner_html.assert_called_once_with(".container")

    async def test_title_command(self):
        daemon = await self._setup_daemon()
        daemon._page.title = AsyncMock(return_value="Page Title")

        result = await daemon.execute("title", [])

        assert "Page Title" in result

    async def test_url_command(self):
        daemon = await self._setup_daemon()
        daemon._page.url = "https://example.com/path"

        result = await daemon.execute("url", [])

        assert "example.com" in result

    async def test_links_command(self):
        daemon = await self._setup_daemon()
        daemon._page.eval_on_selector_all = AsyncMock(return_value=[
            {"text": "Link 1", "href": "https://example.com/1"},
            {"text": "Link 2", "href": "https://example.com/2"},
        ])

        result = await daemon.execute("links", [])

        assert "Link 1" in result
        assert "Link 2" in result

    async def test_forms_command(self):
        daemon = await self._setup_daemon()
        daemon._page.eval_on_selector_all = AsyncMock(return_value=[
            {"tag": "INPUT", "type": "text", "name": "username", "placeholder": "User"},
            {"tag": "BUTTON", "type": "", "name": "", "placeholder": ""},
        ])

        result = await daemon.execute("forms", [])

        assert "INPUT" in result
        assert "username" in result


@pytest.mark.asyncio
class TestBrowserDaemonInteraction:
    """Test interaction commands (click, fill, etc)."""

    async def _setup_daemon(self):
        from agent.browser.daemon import BrowserDaemon
        daemon = BrowserDaemon()
        daemon._running = True
        daemon._page = AsyncMock()
        daemon._context = AsyncMock()
        daemon._page.url = "https://example.com"
        return daemon

    async def test_click_with_ref(self):
        daemon = await self._setup_daemon()
        locator = AsyncMock()
        locator.click = AsyncMock()
        daemon._refs.add(locator)

        result = await daemon.execute("click", ["@e1"])

        locator.click.assert_called_once()
        assert "@e1" in result

    async def test_click_with_selector(self):
        daemon = await self._setup_daemon()
        daemon._page.click = AsyncMock()

        result = await daemon.execute("click", [".button"])

        daemon._page.click.assert_called_once()
        assert ".button" in result

    async def test_fill_with_ref(self):
        daemon = await self._setup_daemon()
        locator = AsyncMock()
        locator.fill = AsyncMock()
        daemon._refs.add(locator)

        result = await daemon.execute("fill", ["@e1", "test value"])

        locator.fill.assert_called_once_with("test value", timeout=5000)
        assert "Filled" in result

    async def test_select_option(self):
        daemon = await self._setup_daemon()
        daemon._page.select_option = AsyncMock()

        result = await daemon.execute("select", ["select-id", "option-value"])

        daemon._page.select_option.assert_called_once()
        assert "Selected" in result

    async def test_type_command(self):
        daemon = await self._setup_daemon()
        daemon._page.keyboard = AsyncMock()
        daemon._page.keyboard.type = AsyncMock()

        result = await daemon.execute("type", ["hello", "world"])

        daemon._page.keyboard.type.assert_called_once()
        assert "hello" in result and "world" in result

    async def test_press_key(self):
        daemon = await self._setup_daemon()
        daemon._page.keyboard = AsyncMock()
        daemon._page.keyboard.press = AsyncMock()

        result = await daemon.execute("press", ["Enter"])

        daemon._page.keyboard.press.assert_called_once_with("Enter")
        assert "Pressed" in result

    async def test_scroll_down(self):
        daemon = await self._setup_daemon()
        daemon._page.mouse = AsyncMock()
        daemon._page.mouse.wheel = AsyncMock()

        result = await daemon.execute("scroll", ["down", "500"])

        daemon._page.mouse.wheel.assert_called_once_with(0, 500)
        assert "down" in result.lower()

    async def test_scroll_up(self):
        daemon = await self._setup_daemon()
        daemon._page.mouse = AsyncMock()
        daemon._page.mouse.wheel = AsyncMock()

        result = await daemon.execute("scroll", ["up", "300"])

        daemon._page.mouse.wheel.assert_called_once_with(0, -300)

    async def test_hover_command(self):
        daemon = await self._setup_daemon()
        locator = AsyncMock()
        locator.hover = AsyncMock()
        daemon._refs.add(locator)

        result = await daemon.execute("hover", ["@e1"])

        locator.hover.assert_called_once()

    async def test_wait_command(self):
        daemon = await self._setup_daemon()

        result = await daemon.execute("wait", ["1.5"])

        assert "1.5" in result


@pytest.mark.asyncio
class TestBrowserDaemonScreenshots:
    """Test screenshot commands."""

    async def _setup_daemon(self):
        from agent.browser.daemon import BrowserDaemon
        daemon = BrowserDaemon()
        daemon._running = True
        daemon._page = AsyncMock()
        daemon._page.url = "https://example.com"
        return daemon

    async def test_screenshot_default_path(self):
        daemon = await self._setup_daemon()
        daemon._page.screenshot = AsyncMock()

        result = await daemon.execute("screenshot", [])

        daemon._page.screenshot.assert_called_once()
        assert "Screenshot saved" in result

    async def test_screenshot_custom_path(self):
        daemon = await self._setup_daemon()
        daemon._page.screenshot = AsyncMock()

        result = await daemon.execute("screenshot", ["/tmp/custom.png"])

        call_args = daemon._page.screenshot.call_args
        assert "/tmp/custom.png" in str(call_args)

    async def test_pdf_command(self):
        daemon = await self._setup_daemon()
        daemon._page.pdf = AsyncMock()

        result = await daemon.execute("pdf", ["/tmp/page.pdf"])

        daemon._page.pdf.assert_called_once()
        assert "PDF saved" in result


@pytest.mark.asyncio
class TestBrowserDaemonTabManagement:
    """Test tab management commands."""

    async def _setup_daemon(self):
        from agent.browser.daemon import BrowserDaemon
        daemon = BrowserDaemon()
        daemon._running = True
        daemon._page = AsyncMock()
        daemon._context = AsyncMock()
        daemon._page.url = "https://example.com"
        daemon._tabs["tab-1"] = daemon._page
        daemon._active_tab = "tab-1"
        return daemon

    async def test_newtab_command(self):
        daemon = await self._setup_daemon()
        new_page = AsyncMock()
        new_page.url = "about:blank"
        daemon._context.new_page = AsyncMock(return_value=new_page)

        result = await daemon.execute("newtab", [])

        assert "tab-2" in result
        assert len(daemon._tabs) == 2

    async def test_tabs_command(self):
        daemon = await self._setup_daemon()
        daemon._page.title = AsyncMock(return_value="Page 1")

        result = await daemon.execute("tabs", [])

        assert "tab-1" in result
        assert "active" in result.lower()

    async def test_tab_switch(self):
        daemon = await self._setup_daemon()
        page2 = AsyncMock()
        daemon._tabs["tab-2"] = page2

        result = await daemon.execute("tab", ["tab-2"])

        assert daemon._active_tab == "tab-2"
        assert daemon._page == page2
        assert "tab-2" in result

    async def test_closetab_command(self):
        daemon = await self._setup_daemon()
        page2 = AsyncMock()
        page2.close = AsyncMock()
        daemon._tabs["tab-2"] = page2

        result = await daemon.execute("closetab", ["tab-2"])

        page2.close.assert_called_once()
        assert "tab-2" not in daemon._tabs

    async def test_closetab_prevents_closing_last_tab(self):
        daemon = await self._setup_daemon()

        result = await daemon.execute("closetab", ["tab-1"])

        assert "tab-1" in daemon._tabs
        assert "Cannot close last tab" in result


@pytest.mark.asyncio
class TestBrowserDaemonSnapshot:
    """Test snapshot functionality."""

    async def _setup_daemon(self):
        from agent.browser.daemon import BrowserDaemon
        daemon = BrowserDaemon()
        daemon._running = True
        daemon._page = AsyncMock()
        daemon._page.url = "https://example.com"
        return daemon

    async def test_snapshot_command(self):
        daemon = await self._setup_daemon()
        element = AsyncMock()
        element.is_visible = AsyncMock(return_value=True)
        element.evaluate = AsyncMock(side_effect=lambda code: "button" if "tagName" in code else {
            "type": "submit",
            "name": "submit-btn",
            "placeholder": "",
            "href": "",
            "alt": "",
            "role": "",
            "value": "",
        })
        element.inner_text = AsyncMock(return_value="Click me")

        daemon._page.query_selector_all = AsyncMock(return_value=[element])

        result = await daemon.execute("snapshot", [])

        assert "example.com" in result
        assert "Elements:" in result


@pytest.mark.asyncio
class TestBrowserDaemonInspection:
    """Test inspection commands (console, network, etc)."""

    async def _setup_daemon(self):
        from agent.browser.daemon import BrowserDaemon
        daemon = BrowserDaemon()
        daemon._running = True
        daemon._page = AsyncMock()
        daemon._context = AsyncMock()
        daemon._page.url = "https://example.com"
        return daemon

    async def test_console_command(self):
        daemon = await self._setup_daemon()
        daemon._console_logs = ["[log] Hello", "[error] Failed"]

        result = await daemon.execute("console", [])

        assert "log" in result or "Hello" in result

    async def test_network_command(self):
        daemon = await self._setup_daemon()
        daemon._network_logs = [
            {"method": "GET", "status": 200, "url": "https://example.com/api/data"},
        ]

        result = await daemon.execute("network", [])

        assert "GET" in result or "200" in result

    async def test_cookies_command(self):
        daemon = await self._setup_daemon()
        daemon._context.cookies = AsyncMock(return_value=[
            {"name": "session", "value": "abc123def456", "domain": "example.com"},
        ])

        result = await daemon.execute("cookies", [])

        assert "session" in result or "example.com" in result

    async def test_js_command(self):
        daemon = await self._setup_daemon()
        daemon._page.evaluate = AsyncMock(return_value={"count": 42})

        result = await daemon.execute("js", ["({count: 42})"])

        assert "42" in result or "count" in result

    async def test_status_command(self):
        daemon = await self._setup_daemon()
        daemon._tabs["tab-1"] = daemon._page
        daemon._active_tab = "tab-1"

        result = await daemon.execute("status", [])

        assert "Running" in result
        assert "Tabs" in result
        assert "URL" in result


@pytest.mark.asyncio
class TestBrowserDaemonErrors:
    """Test error handling."""

    async def test_unknown_command(self):
        from agent.browser.daemon import BrowserDaemon
        daemon = BrowserDaemon()
        daemon._running = True
        daemon._page = AsyncMock()

        result = await daemon.execute("invalid_command", [])

        assert "Unknown command" in result

    async def test_command_exception_handling(self):
        from agent.browser.daemon import BrowserDaemon
        daemon = BrowserDaemon()
        daemon._running = True
        daemon._page = AsyncMock()
        daemon._page.goto = AsyncMock(side_effect=Exception("Network error"))

        result = await daemon.execute("goto", ["https://example.com"])

        assert "Error" in result


@pytest.mark.skipif(not HAS_PLAYWRIGHT, reason="playwright not installed")
class TestBrowserSingleton:
    """Test the browser daemon singleton."""

    @pytest.mark.asyncio
    @patch('agent.browser.daemon.HAS_PLAYWRIGHT', True)
    @patch('playwright.async_api.async_playwright')
    async def test_get_browser_singleton(self, mock_playwright):
        from agent.browser.daemon import get_browser

        mock_pw = AsyncMock()
        mock_context = AsyncMock()
        mock_page = AsyncMock()

        mock_pw.chromium.launch_persistent_context = AsyncMock(return_value=mock_context)
        mock_context.pages = [mock_page]
        mock_pw.stop = AsyncMock()

        mock_playwright.return_value.__aenter__.return_value = mock_pw

        browser1 = await get_browser()
        browser2 = await get_browser()

        assert browser1 is browser2
