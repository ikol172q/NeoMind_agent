"""End-to-end validation for the News widget's category tabs and
clickable-link behaviour.

The earlier version had a single Chinese-dominated firehose and a
draggable wrapper that was swallowing link activations. These tests
lock in the fix: tabs render, switching a tab changes the entry set,
and clicking an entry opens a new tab to its source URL.
"""
from __future__ import annotations

import json
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


def _news_configured() -> bool:
    """Miniflux needs credentials — skip these tests in CI where it
    isn't set up, rather than fail."""
    try:
        with urllib.request.urlopen(BASE_URL + "api/news/health", timeout=3) as r:
            data = json.loads(r.read())
        return bool(data.get("ok"))
    except Exception:
        return False


@pytest.fixture(scope="module")
def browser():
    if not _backend_up():
        pytest.skip(f"backend not reachable at {BASE_URL}")
    if not _news_configured():
        pytest.skip("Miniflux not configured — skipping news UI tests")
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture
def page(browser) -> Page:
    ctx = browser.new_context(viewport={"width": 1600, "height": 1000})
    page = ctx.new_page()
    yield page
    ctx.close()


def _open_research(page: Page):
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    page.wait_for_selector('[data-testid="tab-research"]', timeout=8000)
    page.click('[data-testid="tab-research"]')
    page.wait_for_selector('[data-testid="news-tabs"]', timeout=8000)


def test_news_tabs_render(page: Page):
    _open_research(page)
    # Always-present synthetic tab
    page.wait_for_selector('[data-testid="news-tab-all"]', timeout=5000)
    # At least one category tab should have landed from the backend
    page.wait_for_function(
        """() => {
            const bar = document.querySelector('[data-testid="news-tabs"]')
            if (!bar) return false
            return bar.querySelectorAll('[data-testid^="news-tab-"]').length > 1
        }""",
        timeout=5000,
    )


def test_clicking_tech_tab_shows_hacker_news_items(page: Page):
    _open_research(page)
    # Locate the Tech tab — it should exist because the seed script
    # adds at least one Hacker News feed there. Wait briefly for
    # the categories fetch to land.
    try:
        page.wait_for_selector('[data-testid="news-tab-tech"]', timeout=4000)
    except Exception:
        pytest.skip("Tech category not populated — rerun seed_miniflux_feeds.py")
    page.click('[data-testid="news-tab-tech"]')
    page.wait_for_timeout(1500)
    body_text = page.evaluate(
        "document.querySelector('[data-testid=\"news-entries\"]').innerText"
    ).lower()
    # In the Tech tab, the feed names should contain "Hacker News" —
    # we don't assert exact titles because those change with the feed.
    assert "hacker news" in body_text or "techcrunch" in body_text or "verge" in body_text, \
        f"expected tech feeds in Tech tab, got: {body_text[:300]}"


def test_news_entry_is_a_link_to_external_source(page: Page):
    _open_research(page)
    # Wait for at least one entry to render
    page.wait_for_selector('[data-testid^="news-entry-"]', timeout=8000)
    first = page.query_selector('[data-testid^="news-entry-"]')
    assert first is not None
    href = first.get_attribute("href") or ""
    target = first.get_attribute("target") or ""
    rel = first.get_attribute("rel") or ""
    assert href.startswith("http"), f"entry href must be http(s), got {href!r}"
    assert target == "_blank", f"entry should open in new tab, got target={target!r}"
    assert "noopener" in rel, f"rel should include noopener, got {rel!r}"


def test_clicking_news_entry_opens_new_tab(page: Page):
    """Confirm the draggable-wrapper doesn't swallow clicks — this
    was the original complaint. We listen for a new-page event."""
    _open_research(page)
    page.wait_for_selector('[data-testid^="news-entry-"]', timeout=8000)
    first = page.query_selector('[data-testid^="news-entry-"]')
    assert first is not None

    ctx = page.context
    with ctx.expect_page(timeout=6000) as new_info:
        first.click()
    new_page = new_info.value
    try:
        # We don't want to actually load the destination (it may 401
        # or be slow), but we do expect a new page to have been opened.
        assert new_page is not None
    finally:
        try:
            new_page.close()
        except Exception:
            pass


def test_switching_tabs_issues_scoped_request(page: Page):
    """Regression guard: selecting a category must hit the backend
    with category_id so we don't quietly fall back to the global
    firehose (the prior-state bug)."""
    _open_research(page)
    requested: list[str] = []
    page.on(
        "request",
        lambda r: requested.append(r.url) if "/api/news" in r.url and "categories" not in r.url else None,
    )

    try:
        page.wait_for_selector('[data-testid="news-tab-us"]', timeout=4000)
    except Exception:
        pytest.skip("US category not populated")
    page.click('[data-testid="news-tab-us"]')
    page.wait_for_timeout(1200)
    assert any("category_id=" in u for u in requested), \
        f"expected a request with category_id after clicking US, got: {requested}"
