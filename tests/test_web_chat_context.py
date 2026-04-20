"""End-to-end validation for chat context injection.

Covers: clicking "ask agent" on a watchlist row pre-fills the input
AND attaches a context chip; the next send hits /api/chat_stream
with `context_symbol=AAPL`; the audit log's recorded system prompt
contains a DASHBOARD STATE block for that symbol.
"""
from __future__ import annotations

import json
import time
import urllib.request
import urllib.error
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


def _deepseek_up() -> bool:
    try:
        req = urllib.request.Request(
            BASE_URL + "api/chat_stream?project_id=fin-core&message=ping",
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            return len(r.read(64)) > 0
    except urllib.error.HTTPError as e:
        return e.code < 500
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


@pytest.fixture(scope="module")
def browser():
    if not _backend_up():
        pytest.skip(f"backend not reachable at {BASE_URL}")
    if not _deepseek_up():
        pytest.skip("chat_stream upstream not reachable")
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture
def page(browser) -> Page:
    _clear_watchlist()
    ctx = browser.new_context(viewport={"width": 1600, "height": 1100})
    page = ctx.new_page()
    yield page
    ctx.close()
    _clear_watchlist()


def _seed_watch(symbol: str):
    req = urllib.request.Request(
        BASE_URL + f"api/watchlist?project_id={PROJECT}",
        data=json.dumps({"symbol": symbol, "market": "US", "note": ""}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=5).read()


def test_ask_agent_surfaces_context_chip(page: Page):
    _seed_watch("AAPL")
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    page.wait_for_selector('[data-testid="tab-research"]')
    page.click('[data-testid="tab-research"]')
    page.wait_for_selector('[data-testid="watchlist-ask-US-AAPL"]', timeout=10000)
    page.click('[data-testid="watchlist-ask-US-AAPL"]')
    page.wait_for_selector('[data-testid="chat-context-chip"]', timeout=5000)
    text = page.evaluate(
        "document.querySelector('[data-testid=\"chat-context-chip\"]').innerText"
    )
    assert "AAPL" in text, f"chip should name symbol, got {text!r}"


def test_context_clear_button_drops_the_chip(page: Page):
    _seed_watch("AAPL")
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    page.wait_for_selector('[data-testid="tab-research"]')
    page.click('[data-testid="tab-research"]')
    page.wait_for_selector('[data-testid="watchlist-ask-US-AAPL"]', timeout=10000)
    page.click('[data-testid="watchlist-ask-US-AAPL"]')
    page.wait_for_selector('[data-testid="chat-context-chip"]', timeout=5000)
    page.click('[data-testid="chat-context-clear"]')
    page.wait_for_timeout(200)
    assert page.query_selector('[data-testid="chat-context-chip"]') is None


def test_send_includes_context_symbol_query_param(page: Page):
    """The chat_stream request must actually include ?context_symbol=
    — otherwise the chip is lying about enriching the next send."""
    _seed_watch("AAPL")
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    page.wait_for_selector('[data-testid="tab-research"]')
    page.click('[data-testid="tab-research"]')
    page.wait_for_selector('[data-testid="watchlist-ask-US-AAPL"]', timeout=10000)
    page.click('[data-testid="watchlist-ask-US-AAPL"]')
    page.wait_for_selector('[data-testid="chat-input"]', timeout=5000)
    page.wait_for_selector('[data-testid="chat-context-chip"]', timeout=5000)

    # Block on the specific request firing — more reliable than
    # polling a captured[] list, which races the app's async send.
    with page.expect_request(
        lambda r: "/api/chat_stream" in r.url and "context_symbol=AAPL" in r.url,
        timeout=15000,
    ) as req_info:
        page.click('[data-testid="chat-send"]')
    assert req_info.value is not None


def test_audit_request_contains_dashboard_state_block(page: Page):
    """Verify the end-to-end story: send with context → audit log's
    recorded system prompt contains the DASHBOARD STATE block the
    server-side injector built."""
    _seed_watch("AAPL")
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    page.wait_for_selector('[data-testid="tab-research"]')
    page.click('[data-testid="tab-research"]')
    page.wait_for_selector('[data-testid="watchlist-ask-US-AAPL"]', timeout=10000)
    page.click('[data-testid="watchlist-ask-US-AAPL"]')
    page.wait_for_selector('[data-testid="chat-context-chip"]', timeout=5000)
    page.click('[data-testid="chat-send"]')
    # Wait for the response to complete so the audit request row exists
    page.wait_for_selector('[data-testid^="audit-link-"]', timeout=30000)

    with urllib.request.urlopen(
        BASE_URL + "api/audit/recent?kind=request&limit=5", timeout=5
    ) as r:
        entries = json.loads(r.read()).get("entries", [])
    stream_entries = [
        e for e in entries
        if (e.get("endpoint") or "") == "/api/chat_stream"
    ]
    assert stream_entries, "no /api/chat_stream request audit entries found"
    # Most-recent first
    latest = stream_entries[0]
    sys_prompt = latest["payload"]["messages"][0]["content"]
    assert "DASHBOARD STATE" in sys_prompt, \
        "system prompt should carry DASHBOARD STATE block"
    assert "AAPL" in sys_prompt, "system prompt should mention the symbol"
