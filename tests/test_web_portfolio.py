"""End-to-end validation for the Research-tab Portfolio Heatmap.

The widget consumes existing Paper-trading state. Tests seed and
tear down positions through /api/paper/order + /api/paper/reset
so they don't pollute a real paper account.

Skips if yfinance upstream is unreachable (quote feed is needed to
populate current_price → unrealized_pnl on the engine).
"""
from __future__ import annotations

import json
import urllib.request
import urllib.error
from urllib.parse import urlencode

import pytest
from playwright.sync_api import Page, sync_playwright

BASE_URL = "http://127.0.0.1:8001/"
PROJECT = "fin-core"


def _backend_up() -> bool:
    try:
        with urllib.request.urlopen(BASE_URL + "api/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def _quote_ok() -> bool:
    try:
        with urllib.request.urlopen(BASE_URL + "api/quote/AAPL", timeout=10) as r:
            return r.status == 200
    except Exception:
        return False


def _reset_paper():
    try:
        url = BASE_URL + f"api/paper/reset?project_id={PROJECT}&confirm=yes"
        req = urllib.request.Request(url, method="POST")
        urllib.request.urlopen(req, timeout=5).read()
    except Exception:
        pass


def _place_order(symbol: str, qty: int, side: str = "buy"):
    qs = urlencode({
        "project_id": PROJECT,
        "symbol": symbol,
        "side": side,
        "quantity": qty,
        "order_type": "market",
    })
    req = urllib.request.Request(BASE_URL + f"api/paper/order?{qs}", method="POST")
    urllib.request.urlopen(req, timeout=10).read()


def _refresh_paper():
    try:
        req = urllib.request.Request(
            BASE_URL + f"api/paper/refresh?project_id={PROJECT}", method="POST"
        )
        urllib.request.urlopen(req, timeout=10).read()
    except Exception:
        pass


@pytest.fixture(scope="module")
def browser():
    if not _backend_up():
        pytest.skip(f"backend not reachable at {BASE_URL}")
    if not _quote_ok():
        pytest.skip("quote upstream not reachable — paper positions can't price")
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture
def page(browser) -> Page:
    _reset_paper()
    ctx = browser.new_context(viewport={"width": 1600, "height": 1100})
    page = ctx.new_page()
    yield page
    ctx.close()
    _reset_paper()


def _open_research(page: Page):
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    page.wait_for_selector('[data-testid="tab-research"]', timeout=8000)
    page.click('[data-testid="tab-research"]')
    page.wait_for_selector('[data-testid="portfolio-heatmap-widget"]', timeout=10000)


def test_empty_state_when_no_positions(page: Page):
    _open_research(page)
    page.wait_for_function(
        """() => {
            const box = document.querySelector('[data-testid="portfolio-rows"]')
            if (!box) return false
            const t = box.innerText.toLowerCase()
            return t.includes('empty')
        }""",
        timeout=10000,
    )


def test_row_renders_for_seeded_position(page: Page):
    _place_order("AAPL", 5)
    _refresh_paper()
    _open_research(page)
    page.wait_for_selector('[data-testid="portfolio-row-AAPL"]', timeout=15000)
    row = page.query_selector('[data-testid="portfolio-row-AAPL"]')
    assert row is not None
    text = row.text_content() or ""
    assert "AAPL" in text
    # P&L% column has the signed number
    pnl_cell = page.query_selector('[data-testid="portfolio-pnl-pct-AAPL"]')
    assert pnl_cell is not None
    pnl_text = (pnl_cell.text_content() or "").strip()
    assert "%" in pnl_text


def test_ask_agent_prefills_chat_with_pnl_context(page: Page):
    _place_order("AAPL", 5)
    _refresh_paper()
    _open_research(page)
    page.wait_for_selector('[data-testid="portfolio-ask-AAPL"]', timeout=15000)
    page.click('[data-testid="portfolio-ask-AAPL"]')
    page.wait_for_selector('[data-testid="chat-input"]', timeout=5000)
    page.wait_for_function(
        """() => {
            const el = document.querySelector('[data-testid="chat-input"]')
            return el && el.value && el.value.includes('AAPL')
        }""",
        timeout=5000,
    )
    val = page.input_value('[data-testid="chat-input"]')
    # Prompt should carry at least entry / now / qty context
    assert "entry" in val.lower() and "qty" in val.lower(), \
        f"expected P&L context in prompt, got {val!r}"


def test_multiple_positions_all_render(page: Page):
    _place_order("AAPL", 3)
    _place_order("MSFT", 2)
    _refresh_paper()
    _open_research(page)
    page.wait_for_selector('[data-testid="portfolio-row-AAPL"]', timeout=15000)
    page.wait_for_selector('[data-testid="portfolio-row-MSFT"]', timeout=15000)
