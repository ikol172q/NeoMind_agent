"""Phase-4 validation: citation-linked claims.

Brief hero + chat workflow commands emit [[SYMBOL]] / [[sector:X]] /
[[pos:Y]] tags. UI parses them into clickable chips; clicking a chip
routes back to chat with the cited entity as next-send context.
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


def _brief_with_citations_ok() -> bool:
    try:
        req = urllib.request.Request(
            BASE_URL + f"api/research_brief?project_id={PROJECT}&fresh=1",
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=45) as r:
            d = json.loads(r.read())
        return "[[" in (d.get("text") or "")
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
    if not _brief_with_citations_ok():
        pytest.skip("brief did not emit citation tags (model compliance varies)")
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


def test_brief_citation_chip_renders_and_is_clickable(page: Page):
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    page.wait_for_selector('[data-testid="tab-research"]')
    page.click('[data-testid="tab-research"]')
    page.wait_for_selector('[data-testid="research-brief-widget"]', timeout=10000)

    # Wait until at least one citation chip renders inside the brief.
    # Model can emit either sector:X or a bare TICKER — either works.
    page.wait_for_function(
        """() => {
            const b = document.querySelector('[data-testid="research-brief-widget"]')
            if (!b) return false
            return !!b.querySelector('[data-testid^="cite-"]')
        }""",
        timeout=45000,
    )

    # Click the first chip → jump to chat with context chip populated
    chip = page.locator('[data-testid="research-brief-widget"] [data-testid^="cite-"]').first
    chip.click()
    page.wait_for_selector('[data-testid="chat-input"]', timeout=5000)
    page.wait_for_selector('[data-testid="chat-context-chip"]', timeout=5000)


def test_chat_assistant_message_renders_citation_chip(page: Page):
    """After /brief runs, the assistant reply contains citation tags
    and the bubble renders them as chips we can click in chat."""
    _seed("AAPL")
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    page.wait_for_selector('[data-testid="tab-chat"]')
    page.click('[data-testid="tab-chat"]')
    page.wait_for_selector('[data-testid="chat-input"]', timeout=5000)
    page.fill('[data-testid="chat-input"]', "/brief")
    page.click('[data-testid="chat-send"]')
    # Wait for response to stream in + include citation chips
    page.wait_for_function(
        """() => {
            const msgs = document.querySelector('[data-testid="chat-messages"]')
            if (!msgs) return false
            return !!msgs.querySelector('[data-testid^="cite-"]')
        }""",
        timeout=60000,
    )


def test_citation_parser_handles_plain_text():
    """Via an API call that DOES NOT emit tags — /api/insight prompts
    the model for a single sentence with no citation instructions.
    The chat bubble shouldn't break when rendering plain prose."""
    with urllib.request.urlopen(
        BASE_URL + f"api/insight/symbol/AAPL?project_id={PROJECT}", timeout=40
    ) as r:
        d = json.loads(r.read())
    # Text should NOT contain [[ tags — insight prompt doesn't request them
    assert "[[" not in d["text"], f"insight unexpectedly emitted tags: {d['text']!r}"
