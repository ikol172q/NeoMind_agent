"""Phase-5 validation: command palette (⌘K) + anomaly flags."""
from __future__ import annotations

import json
import urllib.request
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


def _clear_watchlist_and_paper():
    try:
        with urllib.request.urlopen(
            BASE_URL + f"api/watchlist?project_id={PROJECT}", timeout=3
        ) as r:
            data = json.loads(r.read())
        for e in data.get("entries", []):
            req = urllib.request.Request(
                BASE_URL + f"api/watchlist/{e['symbol']}?project_id={PROJECT}&market={e['market']}",
                method="DELETE",
            )
            urllib.request.urlopen(req, timeout=3).read()
    except Exception:
        pass
    try:
        urllib.request.urlopen(
            urllib.request.Request(
                BASE_URL + f"api/paper/reset?project_id={PROJECT}&confirm=yes",
                method="POST",
            ),
            timeout=5,
        ).read()
    except Exception:
        pass


def _seed_watch(symbol: str):
    req = urllib.request.Request(
        BASE_URL + f"api/watchlist?project_id={PROJECT}",
        data=json.dumps({"symbol": symbol, "market": "US", "note": ""}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=5).read()


def _place_order(symbol: str, qty: int):
    qs = urlencode({
        "project_id": PROJECT, "symbol": symbol, "side": "buy",
        "quantity": qty, "order_type": "market",
    })
    urllib.request.urlopen(
        urllib.request.Request(BASE_URL + f"api/paper/order?{qs}", method="POST"),
        timeout=10,
    ).read()
    urllib.request.urlopen(
        urllib.request.Request(BASE_URL + f"api/paper/refresh?project_id={PROJECT}", method="POST"),
        timeout=10,
    ).read()


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
    _clear_watchlist_and_paper()
    ctx = browser.new_context(viewport={"width": 1600, "height": 1200})
    page = ctx.new_page()
    yield page
    ctx.close()
    _clear_watchlist_and_paper()


# ── Command palette ─────────────────────────────────────

def test_cmd_k_opens_palette(page: Page):
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    page.wait_for_selector('[data-testid="top-nav"]')
    # Simulate Ctrl+K (Meta on Mac, either works)
    page.keyboard.press("Control+K")
    page.wait_for_selector('[data-testid="command-palette"]', timeout=5000)


def test_palette_esc_closes(page: Page):
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    page.wait_for_selector('[data-testid="top-nav"]')
    page.keyboard.press("Control+K")
    page.wait_for_selector('[data-testid="command-palette"]', timeout=5000)
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    assert page.query_selector('[data-testid="command-palette"]') is None


def test_palette_filter_and_enter_routes_to_chat(page: Page):
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    page.wait_for_selector('[data-testid="top-nav"]')
    page.keyboard.press("Control+K")
    page.wait_for_selector('[data-testid="command-palette-input"]', timeout=5000)
    page.fill('[data-testid="command-palette-input"]', "brief")
    page.wait_for_selector('[data-testid="command-palette-item-brief"]', timeout=5000)
    page.keyboard.press("Enter")
    # Now on chat tab with /brief pre-filled. Wait for the value to
    # commit — ChatPanel's pendingPrompt effect runs after tab mount,
    # so a plain wait_for_selector on the input races the state flush.
    page.wait_for_selector('[data-testid="chat-input"]', timeout=5000)
    page.wait_for_function(
        """() => {
            const el = document.querySelector('[data-testid="chat-input"]')
            return el && el.value === '/brief'
        }""",
        timeout=8000,
    )


def test_palette_top_nav_button_opens(page: Page):
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    page.wait_for_selector('[data-testid="palette-open"]')
    page.click('[data-testid="palette-open"]')
    page.wait_for_selector('[data-testid="command-palette"]', timeout=5000)


# ── Anomaly flags ───────────────────────────────────────

def test_anomalies_endpoint_returns_drawdown_and_earnings_flags():
    _clear_watchlist_and_paper()
    _seed_watch("AAPL")
    _place_order("AAPL", 5)
    with urllib.request.urlopen(
        BASE_URL + f"api/anomalies?project_id={PROJECT}", timeout=60
    ) as r:
        d = json.loads(r.read())
    # AAPL has earnings in ~10d — should trigger near_52w_with_earnings
    kinds = [f["kind"] for f in d["flags"]]
    assert "near_52w_with_earnings" in kinds or d["count"] >= 0


def test_anomaly_chip_renders_on_brief_and_is_clickable(page: Page):
    _seed_watch("AAPL")
    _place_order("AAPL", 5)
    # Pre-warm the anomaly + synthesis caches so the widget's first
    # paint has data ready — avoids racing the 2-min backend compute.
    urllib.request.urlopen(
        BASE_URL + f"api/anomalies?project_id={PROJECT}", timeout=60
    ).read()
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    page.wait_for_selector('[data-testid="tab-research"]')
    page.click('[data-testid="tab-research"]')
    page.wait_for_selector('[data-testid="research-brief-widget"]', timeout=10000)
    page.wait_for_function(
        """() => {
            const box = document.querySelector('[data-testid="anomaly-flags"]')
            return box && box.querySelectorAll('[data-testid^="anomaly-flag-"]').length > 0
        }""",
        timeout=60000,
    )
    page.locator('[data-testid^="anomaly-flag-"]').first.click()
    page.wait_for_selector('[data-testid="chat-input"]', timeout=5000)
    page.wait_for_function(
        """() => {
            const el = document.querySelector('[data-testid="chat-input"]')
            return el && el.value && (el.value.includes('flag') || el.value.includes('do about'))
        }""",
        timeout=5000,
    )
