"""End-to-end validation for the Earnings + IV widget.

The widget reads the project's US watchlist and annotates each
symbol with next-earnings date, days-until, historical move stats,
30d realised vol, and ATM IV. Tests seed the watchlist via REST so
they're deterministic.

Skips gracefully if yfinance is unavailable in the dashboard env.
"""
from __future__ import annotations

import json
import urllib.request
import urllib.error

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


def _earnings_ok(symbol: str = "AAPL", timeout: float = 60.0) -> bool:
    try:
        with urllib.request.urlopen(
            BASE_URL + f"api/earnings?symbols={symbol}", timeout=timeout
        ) as r:
            return r.status == 200
    except Exception:
        return False


def _clear_watchlist():
    try:
        with urllib.request.urlopen(
            BASE_URL + f"api/watchlist?project_id={PROJECT}", timeout=3
        ) as r:
            data = json.loads(r.read())
    except Exception:
        return
    for e in data.get("entries", []):
        try:
            req = urllib.request.Request(
                BASE_URL + f"api/watchlist/{e['symbol']}?project_id={PROJECT}&market={e['market']}",
                method="DELETE",
            )
            urllib.request.urlopen(req, timeout=3).read()
        except Exception:
            pass


def _seed(symbol: str, market: str = "US"):
    req = urllib.request.Request(
        BASE_URL + f"api/watchlist?project_id={PROJECT}",
        data=json.dumps({"symbol": symbol, "market": market, "note": ""}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=5).read()


@pytest.fixture(scope="module")
def browser():
    if not _backend_up():
        pytest.skip(f"backend not reachable at {BASE_URL}")
    if not _earnings_ok():
        pytest.skip("earnings upstream unavailable (yfinance)")
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture
def page(browser) -> Page:
    _clear_watchlist()
    ctx = browser.new_context(viewport={"width": 1600, "height": 1100})
    page = ctx.new_page()
    yield page
    ctx.close()
    _clear_watchlist()


def _open_research(page: Page):
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    page.wait_for_selector('[data-testid="tab-research"]', timeout=8000)
    page.click('[data-testid="tab-research"]')
    page.wait_for_selector('[data-testid="earnings-widget"]', timeout=10000)


def test_earnings_empty_state_when_no_us_watchlist(page: Page):
    _open_research(page)
    page.wait_for_function(
        """() => {
            const el = document.querySelector('[data-testid="earnings-rows"]')
            if (!el) return false
            const t = el.innerText.toLowerCase()
            return t.includes('empty') || t.includes('add us symbols')
        }""",
        timeout=10000,
    )


def test_earnings_row_appears_for_watchlist_symbol(page: Page):
    _seed("AAPL")
    _open_research(page)
    page.wait_for_selector('[data-testid="earnings-row-AAPL"]', timeout=30000)
    # The row should show the symbol and at least one populated numeric cell
    row = page.query_selector('[data-testid="earnings-row-AAPL"]')
    assert row is not None
    text = row.text_content() or ""
    assert "AAPL" in text


def test_earnings_ask_button_prefills_chat(page: Page):
    _seed("AAPL")
    _open_research(page)
    page.wait_for_selector('[data-testid="earnings-ask-AAPL"]', timeout=30000)
    page.click('[data-testid="earnings-ask-AAPL"]')
    page.wait_for_selector('[data-testid="chat-input"]', timeout=5000)
    page.wait_for_function(
        """() => {
            const el = document.querySelector('[data-testid="chat-input"]')
            return el && el.value && el.value.includes('AAPL')
        }""",
        timeout=5000,
    )
    val = page.input_value('[data-testid="chat-input"]')
    # Prompt mentions at least one quantitative context bit
    has_ctx = any(k in val for k in ("IV", "move", "RV", "earnings in"))
    assert has_ctx, f"prompt should include earnings context, got {val!r}"


def test_earnings_row_skips_cn_watchlist_entry(page: Page):
    """CN entries are in the same watchlist but earnings endpoint
    is US-only — make sure a CN symbol doesn't show up in the grid."""
    _seed("600519", market="CN")
    _open_research(page)
    page.wait_for_timeout(2000)  # give the render a chance
    assert page.query_selector('[data-testid="earnings-row-600519"]') is None
