"""Phase-3 validation: factor grades + 3-tier drill in the watchlist."""
from __future__ import annotations

import json
import urllib.request

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


def _factors_ok() -> bool:
    try:
        with urllib.request.urlopen(BASE_URL + "api/factors/AAPL", timeout=30) as r:
            d = json.loads(r.read())
            return bool(d.get("overall_grade"))
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
    if not _factors_ok():
        pytest.skip("factors upstream unavailable")
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


def test_factors_endpoint_returns_all_five_axes():
    with urllib.request.urlopen(BASE_URL + "api/factors/AAPL", timeout=30) as r:
        d = json.loads(r.read())
    assert d["symbol"] == "AAPL"
    assert d["overall_grade"] in {"A", "B", "C", "D", "F", "—"}
    assert set(d["axes"].keys()) == {"momentum", "value", "quality", "growth", "revisions"}
    for axis, body in d["axes"].items():
        assert "grade" in body
        assert body["grade"] in {"A+", "A", "B", "C", "D", "F", "—"}


def test_factors_second_call_hits_cache():
    import time
    urllib.request.urlopen(BASE_URL + "api/factors/AAPL", timeout=30).read()
    t0 = time.time()
    with urllib.request.urlopen(BASE_URL + "api/factors/AAPL", timeout=5) as r:
        json.loads(r.read())
    assert time.time() - t0 < 2.0


def test_factors_unknown_symbol_graceful():
    """Unknown symbol should not 500. Grades default to '—'."""
    try:
        with urllib.request.urlopen(BASE_URL + "api/factors/ZZZZZZ", timeout=30) as r:
            d = json.loads(r.read())
        # All axes should be '—' since no data
        for axis in d["axes"].values():
            assert axis["grade"] == "—" or axis["raw"] is None
    except urllib.error.HTTPError as e:
        # 502 is acceptable if yfinance errors — but not 500
        assert e.code != 500


def test_watchlist_tier1_is_default(page: Page):
    _seed("AAPL")
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    page.wait_for_selector('[data-testid="tab-research"]', timeout=8000)
    page.click('[data-testid="tab-research"]')
    page.wait_for_selector('[data-testid="watchlist-widget"]', timeout=10000)
    page.wait_for_selector('[data-testid="watchlist-row-US-AAPL"]', timeout=15000)
    # Factor pills should NOT be visible at default tier
    assert page.query_selector('[data-testid="factor-pills-AAPL"]') is None
    assert page.query_selector('[data-testid="watchlist-tier2-US-AAPL"]') is None


def test_tier_toggle_cycles_tiers(page: Page):
    _seed("AAPL")
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    page.click('[data-testid="tab-research"]')
    page.wait_for_selector('[data-testid="watchlist-tier-toggle-US-AAPL"]', timeout=10000)
    # Click once → tier 2 (factor pills)
    page.click('[data-testid="watchlist-tier-toggle-US-AAPL"]')
    page.wait_for_selector('[data-testid="watchlist-tier2-US-AAPL"]', timeout=5000)
    page.wait_for_selector('[data-testid="factor-pills-AAPL"]', timeout=30000)
    # Click twice → tier 3 (raw + narrative)
    page.click('[data-testid="watchlist-tier-toggle-US-AAPL"]')
    page.wait_for_selector('[data-testid="watchlist-tier3-AAPL"]', timeout=5000)
    # Click thrice → collapse back
    page.click('[data-testid="watchlist-tier-toggle-US-AAPL"]')
    page.wait_for_timeout(300)
    assert page.query_selector('[data-testid="watchlist-tier2-US-AAPL"]') is None
    assert page.query_selector('[data-testid="watchlist-tier3-AAPL"]') is None


def test_factor_pills_render_five_axes(page: Page):
    _seed("AAPL")
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    page.click('[data-testid="tab-research"]')
    page.wait_for_selector('[data-testid="watchlist-tier-toggle-US-AAPL"]', timeout=10000)
    page.click('[data-testid="watchlist-tier-toggle-US-AAPL"]')
    for axis in ("momentum", "value", "quality", "growth", "revisions"):
        page.wait_for_selector(f'[data-testid="factor-axis-AAPL-{axis}"]', timeout=30000)


def test_cn_symbol_shows_factors_unavailable_message(page: Page):
    """CN symbols are skipped for the factor tier — widget shows a
    polite note instead of trying and failing."""
    _seed("600519", market="CN")
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    page.click('[data-testid="tab-research"]')
    page.wait_for_selector('[data-testid="watchlist-tier-toggle-CN-600519"]', timeout=10000)
    page.click('[data-testid="watchlist-tier-toggle-CN-600519"]')
    page.wait_for_selector('[data-testid="watchlist-tier2-CN-600519"]', timeout=5000)
    txt = page.evaluate(
        """() => document.querySelector('[data-testid="watchlist-tier2-CN-600519"]').innerText"""
    )
    assert "US symbols only" in txt or "US" in txt
