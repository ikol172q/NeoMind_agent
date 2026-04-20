"""Phase-6 validation: portfolio attribution + correlation heatmap."""
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


def _quote_ok() -> bool:
    try:
        with urllib.request.urlopen(BASE_URL + "api/quote/AAPL", timeout=10) as r:
            return r.status == 200
    except Exception:
        return False


def _reset():
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
    if not _quote_ok():
        pytest.skip("quote upstream unreachable")
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture
def page(browser) -> Page:
    _reset()
    ctx = browser.new_context(viewport={"width": 1600, "height": 1200})
    page = ctx.new_page()
    yield page
    ctx.close()
    _reset()


# ── Attribution ─────────────────────────────────────────

def test_attribution_endpoint_breaks_down_pnl():
    _reset()
    _place_order("AAPL", 5)
    with urllib.request.urlopen(
        BASE_URL + f"api/attribution?project_id={PROJECT}&fresh=1", timeout=60
    ) as r:
        d = json.loads(r.read())
    assert len(d["by_position"]) == 1
    assert d["by_position"][0]["symbol"] == "AAPL"
    assert d["by_position"][0]["sector"] == "Technology"
    # Prior close should resolve to a real number
    assert d["by_position"][0]["prior_close"] is not None
    assert d["by_sector"][0]["sector"] == "Technology"


def test_portfolio_widget_shows_attribution_strip(page: Page):
    _place_order("AAPL", 5)
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    page.click('[data-testid="tab-research"]')
    page.wait_for_selector('[data-testid="portfolio-attribution"]', timeout=30000)
    page.wait_for_selector('[data-testid="attrib-pos-AAPL"]', timeout=30000)


# ── Correlation ─────────────────────────────────────────

def test_correlation_endpoint_returns_matrix():
    _reset()
    _seed_watch("AAPL")
    _seed_watch("MSFT")
    with urllib.request.urlopen(
        BASE_URL + f"api/correlation?project_id={PROJECT}&days=60", timeout=60
    ) as r:
        d = json.loads(r.read())
    assert set(d["symbols"]) == {"AAPL", "MSFT"}
    assert len(d["matrix"]) == 2
    assert len(d["matrix"][0]) == 2
    # Diagonal = 1
    assert d["matrix"][0][0] == 1.0
    assert d["matrix"][1][1] == 1.0


def test_correlation_endpoint_explains_insufficient_data():
    _reset()
    _seed_watch("AAPL")   # only 1 symbol
    with urllib.request.urlopen(
        BASE_URL + f"api/correlation?project_id={PROJECT}&days=60&fresh=1", timeout=60
    ) as r:
        d = json.loads(r.read())
    assert d["matrix"] == []
    assert "at least 2" in (d.get("note") or "")


def test_correlation_widget_renders_heatmap(page: Page):
    _seed_watch("AAPL")
    _seed_watch("MSFT")
    _seed_watch("NVDA")
    # Warm the correlation cache so the widget doesn't stall waiting
    # on a fresh yfinance download while we wait for it to render.
    urllib.request.urlopen(
        BASE_URL + f"api/correlation?project_id={PROJECT}&days=90&fresh=1", timeout=60
    ).read()
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    page.click('[data-testid="tab-research"]')
    page.wait_for_selector('[data-testid="correlation-widget"]', timeout=10000)
    # Scroll it into view — analytics band is below the fold
    page.evaluate(
        "document.querySelector('[data-testid=\"correlation-widget\"]')?.scrollIntoView({block:'center'})"
    )
    page.wait_for_selector('[data-testid="correlation-table"]', timeout=30000)
    for s in ("AAPL", "MSFT", "NVDA"):
        page.wait_for_selector(f'[data-testid="corr-cell-{s}-{s}"]', timeout=10000)


def test_correlation_window_toggle_changes_request(page: Page):
    _seed_watch("AAPL")
    _seed_watch("MSFT")
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    page.click('[data-testid="tab-research"]')
    page.wait_for_selector('[data-testid="correlation-widget"]', timeout=10000)
    captured: list[str] = []
    page.on("request", lambda r: captured.append(r.url)
        if "/api/correlation" in r.url else None)
    page.click('[data-testid="corr-window-30"]')
    page.wait_for_timeout(1500)
    assert any("days=30" in u for u in captured), \
        f"expected a correlation request with days=30, got: {captured}"
