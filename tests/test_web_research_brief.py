"""Validation for the Phase-1 narrative hero (ResearchBriefWidget +
/api/research_brief). The brief should land on first paint of the
Research tab, have three labelled lines, and not crash if the
LLM is slow (skip when DeepSeek is unreachable)."""
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


def _brief_ok() -> bool:
    try:
        with urllib.request.urlopen(
            BASE_URL + "api/research_brief?project_id=fin-core", timeout=45
        ) as r:
            data = json.loads(r.read())
            return bool((data.get("text") or "").strip())
    except Exception:
        return False


@pytest.fixture(scope="module")
def browser():
    if not _backend_up():
        pytest.skip(f"backend not reachable at {BASE_URL}")
    if not _brief_ok():
        pytest.skip("research_brief upstream unreachable (DeepSeek)")
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


def test_brief_endpoint_returns_three_labelled_lines():
    with urllib.request.urlopen(
        BASE_URL + "api/research_brief?project_id=fin-core", timeout=45
    ) as r:
        data = json.loads(r.read())
    text = data.get("text", "")
    # Model should hit the 3-line structure: Market / Book / Next
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    prefixes = [l.split(":", 1)[0].strip() for l in lines if ":" in l]
    assert any("Market" in p for p in prefixes), f"missing Market line: {text!r}"
    assert any("Book" in p for p in prefixes), f"missing Book line: {text!r}"
    assert any("Next" in p for p in prefixes), f"missing Next line: {text!r}"


def test_brief_second_call_hits_cache_and_returns_same_text():
    """The 5-min server cache means the second call must be fast AND
    return the same text (otherwise cache invalidated for a reason
    the frontend doesn't expect)."""
    import time
    with urllib.request.urlopen(
        BASE_URL + "api/research_brief?project_id=fin-core", timeout=45
    ) as r:
        first = json.loads(r.read())
    t0 = time.time()
    with urllib.request.urlopen(
        BASE_URL + "api/research_brief?project_id=fin-core", timeout=10
    ) as r:
        second = json.loads(r.read())
    elapsed = time.time() - t0
    assert second["text"] == first["text"], "cache returned different text"
    assert elapsed < 2.0, f"cache hit should be instant, took {elapsed:.2f}s"


def test_brief_widget_renders_three_labelled_lines(page: Page):
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    page.wait_for_selector('[data-testid="tab-research"]')
    page.click('[data-testid="tab-research"]')
    page.wait_for_selector('[data-testid="research-brief-widget"]', timeout=10000)
    # Wait for all three labelled lines to render
    for label in ("market", "book", "next"):
        page.wait_for_selector(f'[data-testid="brief-line-{label}"]', timeout=45000)


def test_brief_widget_is_top_of_research_tab(page: Page):
    """The narrative hero must sit above everything else — that's
    the design intent (agent read first, widgets below as evidence)."""
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    page.wait_for_selector('[data-testid="tab-research"]')
    page.click('[data-testid="tab-research"]')
    page.wait_for_selector('[data-testid="research-brief-widget"]', timeout=10000)
    tops = page.evaluate(
        """() => {
            const brief = document.querySelector('[data-testid="research-brief-widget"]')
            const news = document.querySelector('[data-testid="news-tabs"]')
            const watch = document.querySelector('[data-testid="watchlist-widget"]')
            return {
                brief: brief?.getBoundingClientRect().top,
                news: news?.getBoundingClientRect().top,
                watch: watch?.getBoundingClientRect().top,
            }
        }"""
    )
    assert tops["brief"] is not None
    if tops["news"] is not None:
        assert tops["brief"] < tops["news"], \
            f"brief ({tops['brief']}) must sit above news ({tops['news']})"
    if tops["watch"] is not None:
        assert tops["brief"] < tops["watch"], \
            f"brief must sit above watchlist ({tops})"


def test_brief_ask_more_jumps_to_chat_with_project_context(page: Page):
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    page.wait_for_selector('[data-testid="tab-research"]')
    page.click('[data-testid="tab-research"]')
    page.wait_for_selector('[data-testid="brief-ask-more"]', timeout=10000)
    page.click('[data-testid="brief-ask-more"]')
    page.wait_for_selector('[data-testid="chat-input"]', timeout=5000)
    page.wait_for_selector('[data-testid="chat-context-chip"]', timeout=5000)
    chip_text = page.evaluate(
        "document.querySelector('[data-testid=\"chat-context-chip\"]').innerText"
    )
    assert "project" in chip_text.lower(), f"expected project context, got {chip_text!r}"
