"""Empty-state discoverability tests.

When the user opens a fresh dashboard (no watchlist, no positions),
the widgets must actively tell them what to do to light up each
feature. The previous behavior was a bland 'Empty' placeholder,
which hid the tier-drill / hover-insight / attribution features
behind invisible prerequisites.
"""
from __future__ import annotations

import json
import urllib.request

import pytest
from playwright.sync_api import Page, sync_playwright

BASE_URL = "http://127.0.0.1:8001/"
PROJECT = "fin-core"


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


def _backend_up() -> bool:
    try:
        with urllib.request.urlopen(BASE_URL + "api/health", timeout=3) as r:
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
    _reset()
    ctx = browser.new_context(viewport={"width": 1600, "height": 1200})
    page = ctx.new_page()
    yield page
    ctx.close()


def test_watchlist_empty_hint_names_each_feature(page: Page):
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    page.click('[data-testid="tab-research"]')
    page.wait_for_selector('[data-testid="watchlist-empty-hint"]', timeout=10000)
    txt = page.evaluate(
        "document.querySelector('[data-testid=\"watchlist-empty-hint\"]').innerText"
    )
    # Must mention all four unlocks the user asked about
    assert "Hover" in txt or "hover" in txt.lower()
    assert "factor pills" in txt.lower() or "M V Q G R" in txt
    assert "correlation" in txt.lower()


def test_portfolio_empty_hint_routes_to_paper(page: Page):
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    page.click('[data-testid="tab-research"]')
    page.wait_for_selector('[data-testid="portfolio-empty-hint"]', timeout=10000)
    txt = page.evaluate(
        "document.querySelector('[data-testid=\"portfolio-empty-hint\"]').innerText"
    )
    assert "Paper" in txt
    assert "attribution" in txt.lower()
    assert "anomaly" in txt.lower() or "flag" in txt.lower()


def test_brief_shows_quickstart_on_fresh_install(page: Page):
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    page.click('[data-testid="tab-research"]')
    page.wait_for_selector('[data-testid="brief-quickstart"]', timeout=10000)
    txt = page.evaluate(
        "document.querySelector('[data-testid=\"brief-quickstart\"]').innerText"
    )
    for keyword in ("Watchlist", "AAPL", "Hover", "Paper", "⌘K"):
        assert keyword in txt, f"quickstart missing: {keyword!r} in {txt[:400]!r}"


def test_quickstart_hides_when_watchlist_has_entries(page: Page):
    """Once the user adds a watchlist entry, the quickstart should
    be replaced by the real 3-line brief."""
    # Seed a watchlist entry
    req = urllib.request.Request(
        BASE_URL + f"api/watchlist?project_id={PROJECT}",
        data=json.dumps({"symbol": "AAPL", "market": "US", "note": ""}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=5).read()

    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    page.click('[data-testid="tab-research"]')
    page.wait_for_selector('[data-testid="research-brief-widget"]', timeout=10000)
    # Wait for at least one of the Market / Book / Next lines to render
    page.wait_for_selector(
        '[data-testid^="brief-line-"]',
        timeout=45000,
    )
    assert page.query_selector('[data-testid="brief-quickstart"]') is None
