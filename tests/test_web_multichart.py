"""End-to-end validation for the multi-symbol comparison chart."""
from __future__ import annotations

import urllib.request

import pytest
from playwright.sync_api import Page, sync_playwright

BASE_URL = "http://127.0.0.1:8001/"


def _backend_up() -> bool:
    try:
        with urllib.request.urlopen(BASE_URL + "api/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def _chart_ok() -> bool:
    try:
        with urllib.request.urlopen(BASE_URL + "api/chart/AAPL?period=3mo&interval=1d", timeout=15) as r:
            return r.status == 200
    except Exception:
        return False


@pytest.fixture(scope="module")
def browser():
    if not _backend_up():
        pytest.skip(f"backend not reachable at {BASE_URL}")
    if not _chart_ok():
        pytest.skip("chart upstream unreachable")
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture
def page(browser) -> Page:
    ctx = browser.new_context(viewport={"width": 1600, "height": 1100})
    page = ctx.new_page()
    yield page
    ctx.close()


def _open_research(page: Page):
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    page.wait_for_selector('[data-testid="tab-research"]')
    page.click('[data-testid="tab-research"]')
    page.wait_for_selector('[data-testid="multi-chart-widget"]', timeout=10000)


def test_initial_symbols_render_plot(page: Page):
    _open_research(page)
    # Default seeded with AAPL + MSFT — wait for plotly SVG
    page.wait_for_function(
        """() => {
            const root = document.querySelector('[data-testid="multi-chart-plot"]')
            return root && root.querySelector('svg') !== null
        }""",
        timeout=15000,
    )
    # Chip testids present
    page.wait_for_selector('[data-testid="multi-chart-chip-AAPL"]')
    page.wait_for_selector('[data-testid="multi-chart-chip-MSFT"]')


def test_add_and_remove_symbol(page: Page):
    _open_research(page)
    # Scroll the widget into view so interactive elements are clickable
    page.evaluate("""() => {
        document.querySelector('[data-testid="multi-chart-widget"]')?.scrollIntoView({block:'center'})
    }""")
    page.fill('[data-testid="multi-chart-new-symbol"]', "nvda")
    page.click('[data-testid="multi-chart-add"]')
    page.wait_for_selector('[data-testid="multi-chart-chip-NVDA"]', timeout=10000)
    # Now remove AAPL
    page.click('[data-testid="multi-chart-remove-AAPL"]')
    page.wait_for_timeout(400)
    assert page.query_selector('[data-testid="multi-chart-chip-AAPL"]') is None


def test_ask_button_prefills_chat_with_symbols(page: Page):
    _open_research(page)
    page.wait_for_selector('[data-testid="multi-chart-chip-AAPL"]', timeout=10000)
    page.wait_for_selector('[data-testid="multi-chart-chip-MSFT"]', timeout=10000)
    # Ask button only appears when >= 2 symbols — default state satisfies that
    page.click('[data-testid="multi-chart-ask"]')
    page.wait_for_selector('[data-testid="chat-input"]', timeout=5000)
    page.wait_for_function(
        """() => {
            const el = document.querySelector('[data-testid="chat-input"]')
            return el && el.value && el.value.includes('AAPL') && el.value.includes('MSFT')
        }""",
        timeout=5000,
    )
    val = page.input_value('[data-testid="chat-input"]')
    assert "Compare" in val or "compare" in val


def test_period_switch_updates_subtitle(page: Page):
    _open_research(page)
    page.wait_for_selector('[data-testid="multi-chart-period-1y"]', timeout=10000)
    page.evaluate("""() => {
        document.querySelector('[data-testid="multi-chart-widget"]')?.scrollIntoView({block:'center'})
    }""")
    page.click('[data-testid="multi-chart-period-1y"]')
    page.wait_for_timeout(500)
    subtitle = page.evaluate(
        """() => {
            const w = document.querySelector('[data-testid="multi-chart-widget"]')
            return w?.innerText || ''
        }"""
    )
    assert "1y" in subtitle
