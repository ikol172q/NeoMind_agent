"""End-to-end validation for the market-sentiment gauge."""
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


def _sentiment_ok() -> bool:
    try:
        with urllib.request.urlopen(BASE_URL + "api/sentiment", timeout=30) as r:
            if r.status != 200:
                return False
            data = json.loads(r.read())
            return data.get("composite_score") is not None
    except Exception:
        return False


@pytest.fixture(scope="module")
def browser():
    if not _backend_up():
        pytest.skip(f"backend not reachable at {BASE_URL}")
    if not _sentiment_ok():
        pytest.skip("sentiment upstream unreachable")
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
    page.wait_for_selector('[data-testid="tab-research"]')
    page.click('[data-testid="tab-research"]')
    page.wait_for_selector('[data-testid="sentiment-gauge-widget"]', timeout=10000)


def test_gauge_renders_with_score(page: Page):
    _open_research(page)
    # Plotly gauge injects an SVG inside the plot container
    page.wait_for_function(
        """() => {
            const root = document.querySelector('[data-testid="sentiment-plot"]')
            return root && root.querySelector('svg') !== null
        }""",
        timeout=15000,
    )
    # Subtitle should reflect one of the expected labels
    body = page.evaluate(
        "document.querySelector('[data-testid=\"sentiment-gauge-widget\"]').innerText.toLowerCase()"
    )
    assert any(k in body for k in ("greed", "fear", "neutral")), \
        f"expected a sentiment label in widget, got: {body[:200]}"


def test_ask_button_prefills_chat_with_subscores(page: Page):
    _open_research(page)
    page.wait_for_selector('[data-testid="sentiment-ask"]', timeout=15000)
    page.click('[data-testid="sentiment-ask"]')
    page.wait_for_selector('[data-testid="chat-input"]', timeout=5000)
    page.wait_for_function(
        """() => {
            const el = document.querySelector('[data-testid="chat-input"]')
            return el && el.value && el.value.includes('VIX')
        }""",
        timeout=5000,
    )
    val = page.input_value('[data-testid="chat-input"]')
    # Prompt should mention the three sub-signals
    assert "VIX" in val and "SPY" in val.upper() and ("breadth" in val.lower() or "up" in val.lower())


def test_sentiment_in_hero_viewport(page: Page):
    """Gauge sits in the hero row — it must be visible on first
    paint without scrolling."""
    _open_research(page)
    info = page.evaluate(
        """() => {
            const el = document.querySelector('[data-testid="sentiment-gauge-widget"]')
            if (!el) return null
            const r = el.getBoundingClientRect()
            return {top: r.top, visible: r.top < window.innerHeight && r.bottom > 0}
        }"""
    )
    assert info and info["visible"], \
        f"sentiment gauge should sit in the hero row viewport: {info}"
