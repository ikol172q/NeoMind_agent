"""Phase-2 validation: hover-synthesis tooltip on watchlist rows.

Hover a row → agent's 1-line read appears. Cache warm = instant.
Cache cold = brief "thinking…" then the text.
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


def _insight_ok() -> bool:
    try:
        with urllib.request.urlopen(
            BASE_URL + f"api/insight/symbol/AAPL?project_id={PROJECT}", timeout=40
        ) as r:
            d = json.loads(r.read())
            return bool((d.get("text") or "").strip())
    except Exception:
        return False


def _clear_watchlist():
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
    if not _insight_ok():
        pytest.skip("insight upstream (DeepSeek) unreachable")
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture
def page(browser) -> Page:
    _clear_watchlist()
    ctx = browser.new_context(viewport={"width": 1600, "height": 1200})
    page = ctx.new_page()
    yield page
    ctx.close()
    _clear_watchlist()


def test_insight_endpoint_returns_one_sentence():
    with urllib.request.urlopen(
        BASE_URL + f"api/insight/symbol/AAPL?project_id={PROJECT}", timeout=40
    ) as r:
        d = json.loads(r.read())
    text = d.get("text", "")
    # Short — "one sentence, under 25 words" per the prompt
    assert 5 <= len(text.split()) <= 60, f"unexpected length: {text!r}"
    assert "AAPL" in text or "$" in text or "%" in text, \
        f"insight should cite a symbol or number: {text!r}"


def test_insight_second_call_is_cache_hit():
    import time
    # Warm
    urllib.request.urlopen(
        BASE_URL + f"api/insight/symbol/AAPL?project_id={PROJECT}", timeout=40
    ).read()
    # Hit
    t0 = time.time()
    with urllib.request.urlopen(
        BASE_URL + f"api/insight/symbol/AAPL?project_id={PROJECT}", timeout=5
    ) as r:
        d = json.loads(r.read())
    elapsed = time.time() - t0
    assert elapsed < 2.0, f"cache hit should be instant, took {elapsed:.2f}s"
    assert d.get("text")


def test_hover_on_watchlist_row_shows_insight_popover(page: Page):
    _seed("AAPL")
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    page.click('[data-testid="tab-research"]')
    page.wait_for_selector('[data-testid="watchlist-row-US-AAPL"]', timeout=10000)
    # Warm the cache so the tooltip renders fast
    urllib.request.urlopen(
        BASE_URL + f"api/insight/symbol/AAPL?project_id={PROJECT}", timeout=40
    ).read()
    # Hover the watchlist row target
    page.locator('[data-testid="insight-target-AAPL"]').first.hover()
    page.wait_for_selector('[data-testid="insight-popover-AAPL"]', timeout=8000)
    # Popover should contain non-trivial text (not just the loading state)
    page.wait_for_function(
        """() => {
            const el = document.querySelector('[data-testid="insight-popover-AAPL"]')
            if (!el) return false
            const t = el.innerText.toLowerCase()
            return !t.includes('thinking') && t.length > 20
        }""",
        timeout=8000,
    )


def test_hover_away_hides_popover(page: Page):
    _seed("AAPL")
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    page.click('[data-testid="tab-research"]')
    page.wait_for_selector('[data-testid="watchlist-row-US-AAPL"]', timeout=10000)
    urllib.request.urlopen(
        BASE_URL + f"api/insight/symbol/AAPL?project_id={PROJECT}", timeout=40
    ).read()
    page.locator('[data-testid="insight-target-AAPL"]').first.hover()
    page.wait_for_selector('[data-testid="insight-popover-AAPL"]', timeout=5000)
    # Move away — popover should vanish
    page.mouse.move(1, 1)
    page.wait_for_timeout(400)
    assert page.query_selector('[data-testid="insight-popover-AAPL"]') is None


def test_unknown_symbol_doesnt_crash_the_page(page: Page):
    """Hover over a symbol that may have thin data — the popover should
    either show the fallback text or simply not crash the page."""
    _seed("ZZZZZ")
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    page.click('[data-testid="tab-research"]')
    page.wait_for_selector('[data-testid="watchlist-row-US-ZZZZZ"]', timeout=10000)
    page.locator('[data-testid="insight-target-ZZZZZ"]').first.hover()
    page.wait_for_timeout(1500)
    # The page should still be interactive
    assert page.query_selector('[data-testid="watchlist-widget"]') is not None
