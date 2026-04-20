"""End-to-end validation for the Fund/ETF explorer widget."""
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


def _fund_ok() -> bool:
    try:
        with urllib.request.urlopen(BASE_URL + "api/fund/VTI", timeout=20) as r:
            return r.status == 200
    except Exception:
        return False


@pytest.fixture(scope="module")
def browser():
    if not _backend_up():
        pytest.skip(f"backend not reachable at {BASE_URL}")
    if not _fund_ok():
        pytest.skip("fund upstream unreachable")
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture
def page(browser) -> Page:
    ctx = browser.new_context(viewport={"width": 1600, "height": 1200})
    page = ctx.new_page()
    yield page
    ctx.close()


def _open_research(page: Page):
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    page.wait_for_selector('[data-testid="tab-research"]')
    page.click('[data-testid="tab-research"]')
    page.wait_for_selector('[data-testid="fund-explorer-widget"]', timeout=10000)
    # Scroll the fund widget into view (it's in the detail band, below the fold)
    page.evaluate("""() => {
        document.querySelector('[data-testid="fund-explorer-widget"]')?.scrollIntoView({block:'center'})
    }""")


def test_default_vti_loads_with_holdings(page: Page):
    _open_research(page)
    page.wait_for_selector('[data-testid="fund-headline"]', timeout=15000)
    page.wait_for_selector('[data-testid="fund-holdings"]', timeout=15000)
    # At least one holding should render
    holdings = page.query_selector_all('[data-testid^="fund-holding-"]')
    assert len(holdings) >= 5, f"expected ≥5 holdings for VTI, got {len(holdings)}"


def test_swap_symbol_to_qqq(page: Page):
    _open_research(page)
    page.wait_for_selector('[data-testid="fund-symbol-input"]', timeout=10000)
    page.fill('[data-testid="fund-symbol-input"]', 'qqq')
    page.click('[data-testid="fund-load"]')
    # Wait for QQQ's distinctive holdings (NVDA is #1 in QQQ typically)
    page.wait_for_function(
        """() => {
            const rows = document.querySelectorAll('[data-testid^="fund-holding-"]')
            if (!rows.length) return false
            // Subtitle should reflect the new symbol's name
            const sub = document.querySelector('[data-testid="fund-explorer-widget"]')?.innerText?.toLowerCase() || ''
            return sub.includes('qqq') || sub.includes('nasdaq') || sub.includes('invesco')
        }""",
        timeout=15000,
    )


def test_ask_button_prefills_chat_with_symbol_and_ratios(page: Page):
    _open_research(page)
    page.wait_for_selector('[data-testid="fund-ask"]', timeout=15000)
    page.click('[data-testid="fund-ask"]')
    page.wait_for_selector('[data-testid="chat-input"]', timeout=5000)
    page.wait_for_function(
        """() => {
            const el = document.querySelector('[data-testid="chat-input"]')
            return el && el.value && el.value.includes('VTI')
        }""",
        timeout=5000,
    )
    val = page.input_value('[data-testid="chat-input"]')
    assert "VTI" in val
    # Prompt carries at least one numeric context bit
    assert any(k in val.lower() for k in ("ytd", "aum", "expense", "yield"))
