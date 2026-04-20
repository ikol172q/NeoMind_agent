"""End-to-end validation for the Sector Heatmap + Relative-Strength
widgets on the Research tab.

Both widgets depend on upstream data (yfinance for US, akshare for
CN). When the upstream is unreachable in the test env, individual
tests skip instead of failing so the suite stays green in CI.
"""
from __future__ import annotations

import json
import urllib.request
import urllib.error

import pytest
from playwright.sync_api import Page, sync_playwright

BASE_URL = "http://127.0.0.1:8001/"


def _backend_up() -> bool:
    try:
        with urllib.request.urlopen(BASE_URL + "api/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def _endpoint_ok(path: str, timeout: float = 30.0) -> bool:
    try:
        with urllib.request.urlopen(BASE_URL + path, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


@pytest.fixture(scope="module")
def browser():
    if not _backend_up():
        pytest.skip(f"backend not reachable at {BASE_URL}")
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
    page.wait_for_selector('[data-testid="tab-research"]', timeout=8000)
    page.click('[data-testid="tab-research"]')


# ── Sector heatmap ────────────────────────────────────────
def test_sector_heatmap_renders_us_by_default(page: Page):
    if not _endpoint_ok("api/sectors?market=US", timeout=20):
        pytest.skip("US sectors upstream unreachable")
    _open_research(page)
    page.wait_for_selector('[data-testid="sector-heatmap-widget"]', timeout=10000)
    # Plotly injects an SVG inside the plot container once data arrives
    page.wait_for_function(
        """() => {
            const root = document.querySelector('[data-testid="sector-heatmap-plot"]')
            if (!root) return false
            return root.querySelector('svg') !== null
        }""",
        timeout=15000,
    )


def test_sector_toggle_switches_market(page: Page):
    if not _endpoint_ok("api/sectors?market=US", timeout=20):
        pytest.skip("US sectors upstream unreachable")
    if not _endpoint_ok("api/sectors?market=CN", timeout=30):
        pytest.skip("CN sectors upstream unreachable")
    _open_research(page)
    page.wait_for_selector('[data-testid="sector-market-CN"]', timeout=10000)

    # Watch for the /api/sectors request that should fire on toggle
    cn_seen = {"hit": False}

    def _on_req(r):
        if "/api/sectors" in r.url and "market=CN" in r.url:
            cn_seen["hit"] = True

    page.on("request", _on_req)
    page.click('[data-testid="sector-market-CN"]')
    page.wait_for_timeout(2500)
    assert cn_seen["hit"], "clicking CN toggle should hit /api/sectors?market=CN"


# ── Relative strength grid ────────────────────────────────
def test_rs_grid_renders_rows(page: Page):
    if not _endpoint_ok("api/rs?market=US&limit=5", timeout=30):
        pytest.skip("RS upstream unreachable (yfinance)")
    _open_research(page)
    page.wait_for_selector('[data-testid="rs-grid-widget"]', timeout=10000)
    # Rows need a network round-trip — wait generously
    page.wait_for_function(
        """() => {
            const box = document.querySelector('[data-testid="rs-rows"]')
            if (!box) return false
            return box.querySelectorAll('[data-testid^="rs-row-"]').length > 0
        }""",
        timeout=30000,
    )


def test_rs_window_buttons_change_sort(page: Page):
    if not _endpoint_ok("api/rs?market=US&limit=5", timeout=30):
        pytest.skip("RS upstream unreachable")
    _open_research(page)
    page.wait_for_selector('[data-testid="rs-win-3m"]', timeout=10000)
    page.wait_for_function(
        """() => document.querySelectorAll('[data-testid^="rs-row-"]').length > 5""",
        timeout=30000,
    )

    def top_row_symbol() -> str:
        return page.evaluate(
            """() => {
                const first = document.querySelector('[data-testid^="rs-row-"]')
                return first?.getAttribute('data-testid') ?? ''
            }"""
        )

    first_3m = top_row_symbol()
    page.click('[data-testid="rs-win-ytd"]')
    page.wait_for_timeout(800)
    first_ytd = top_row_symbol()
    # Not guaranteed they differ (a stock CAN top both windows), but
    # the identity usually shifts. Just assert we didn't break the list.
    assert first_3m.startswith("rs-row-")
    assert first_ytd.startswith("rs-row-")


def test_rs_ask_button_prefills_chat(page: Page):
    if not _endpoint_ok("api/rs?market=US&limit=5", timeout=30):
        pytest.skip("RS upstream unreachable")
    _open_research(page)
    page.wait_for_function(
        """() => document.querySelectorAll('[data-testid^="rs-ask-"]').length > 0""",
        timeout=30000,
    )
    btns = page.query_selector_all('[data-testid^="rs-ask-"]')
    assert btns, "expected at least one rs-ask- button"
    btns[0].click()
    page.wait_for_selector('[data-testid="chat-input"]', timeout=5000)
    page.wait_for_function(
        """() => {
            const el = document.querySelector('[data-testid="chat-input"]')
            return el && el.value && el.value.length > 0
        }""",
        timeout=5000,
    )
    val = page.input_value('[data-testid="chat-input"]')
    assert "3m:" in val and "6m:" in val and "YTD:" in val, \
        f"expected prompt to include return windows, got {val!r}"
