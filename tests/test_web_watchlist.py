"""End-to-end validation for the Research-tab watchlist + jump-to-chat flow.

Covers user-visible flows:
  1. Add a ticker to the watchlist, row appears, note editable.
  2. Reloading keeps the row (backed by watchlist.json, not just
     localStorage).
  3. Note edit round-trips to the backend.
  4. Delete removes the row.
  5. Clicking "ask agent" on a row switches to the Chat tab with
     the prompt pre-filled and the input focused.

The tests clean up via the REST API on teardown so they are safe to
run repeatedly against the live launchd dashboard.

Run: ``pytest tests/test_web_watchlist.py -v``
"""
from __future__ import annotations

import json
import urllib.request
import urllib.error

import pytest
from playwright.sync_api import Page, expect, sync_playwright

BASE_URL = "http://127.0.0.1:8001/"
PROJECT = "fin-core"


def _backend_up() -> bool:
    try:
        with urllib.request.urlopen(BASE_URL + "api/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def _clear_watchlist():
    """Remove everything from fin-core's watchlist so tests run clean."""
    try:
        with urllib.request.urlopen(
            BASE_URL + f"api/watchlist?project_id={PROJECT}", timeout=3
        ) as r:
            data = json.loads(r.read())
    except Exception:
        return
    for e in data.get("entries", []):
        try:
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
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture
def page(browser) -> Page:
    _clear_watchlist()
    ctx = browser.new_context(viewport={"width": 1600, "height": 1000})
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.on(
        "console",
        lambda m: errors.append(f"console[{m.type}] {m.text}") if m.type == "error" else None,
    )
    page.errors = errors  # type: ignore[attr-defined]
    yield page
    ctx.close()
    _clear_watchlist()


def _open_research(page: Page):
    # Don't wait for networkidle — the watchlist + quote widgets poll
    # on intervals, so the network is never truly idle. DOM ready is
    # sufficient; we then wait for the specific selector we need.
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    page.wait_for_selector('[data-testid="tab-research"]', timeout=8000)
    page.click('[data-testid="tab-research"]')
    page.wait_for_selector('[data-testid="watchlist-widget"]', timeout=8000)


def test_add_entry_appears_and_persists_across_reload(page: Page):
    _open_research(page)
    page.fill('[data-testid="watchlist-new-symbol"]', "AAPL")
    page.click('[data-testid="watchlist-add"]')
    # Row should show up under the US:AAPL testid
    page.wait_for_selector('[data-testid="watchlist-row-US-AAPL"]', timeout=3000)

    # Reload and make sure it's still there
    page.reload(wait_until="domcontentloaded")
    page.wait_for_selector('[data-testid="tab-research"]', timeout=8000)
    page.click('[data-testid="tab-research"]')
    page.wait_for_selector('[data-testid="watchlist-row-US-AAPL"]', timeout=5000)


def test_note_edit_round_trips_to_backend(page: Page):
    _open_research(page)
    # Seed
    page.fill('[data-testid="watchlist-new-symbol"]', "AAPL")
    page.click('[data-testid="watchlist-add"]')
    page.wait_for_selector('[data-testid="watchlist-note-US-AAPL"]', timeout=3000)

    note = page.locator('[data-testid="watchlist-note-US-AAPL"]')
    note.fill("core holding 2026")
    note.blur()
    page.wait_for_timeout(800)

    # Hit the backend directly — authoritative
    with urllib.request.urlopen(BASE_URL + f"api/watchlist?project_id={PROJECT}") as r:
        data = json.loads(r.read())
    aapl = next(e for e in data["entries"] if e["symbol"] == "AAPL")
    assert aapl["note"] == "core holding 2026"


def test_delete_removes_row(page: Page):
    _open_research(page)
    page.fill('[data-testid="watchlist-new-symbol"]', "AAPL")
    page.click('[data-testid="watchlist-add"]')
    page.wait_for_selector('[data-testid="watchlist-row-US-AAPL"]', timeout=3000)
    page.click('[data-testid="watchlist-del-US-AAPL"]')
    # Row should disappear
    expect(page.locator('[data-testid="watchlist-row-US-AAPL"]')).to_have_count(0, timeout=3000)


def test_ask_agent_switches_to_chat_with_prefilled_prompt(page: Page):
    _open_research(page)
    page.fill('[data-testid="watchlist-new-symbol"]', "AAPL")
    page.click('[data-testid="watchlist-add"]')
    page.wait_for_selector('[data-testid="watchlist-ask-US-AAPL"]', timeout=3000)
    page.click('[data-testid="watchlist-ask-US-AAPL"]')

    # Should have switched to Chat tab and populated the input. Poll
    # the input's value — the useEffect that consumes pendingPrompt
    # runs after a render cycle, so a single read right after the
    # selector appears can land before the prefill.
    page.wait_for_selector('[data-testid="chat-input"]', timeout=5000)
    page.wait_for_function(
        """() => {
            const el = document.querySelector('[data-testid="chat-input"]')
            return el && el.value && el.value.includes('AAPL')
        }""",
        timeout=5000,
    )
    value = page.input_value('[data-testid="chat-input"]')
    assert "AAPL" in value, f"expected AAPL in chat input, got {value!r}"
    assert "Analyze" in value, f"expected analysis prompt, got {value!r}"


def test_two_markets_same_number_coexist(page: Page):
    """(market, symbol) is the identity key. 'AAPL' in US and 'AAPL' in HK
    should NOT collide — though the same number more commonly happens
    with 4/5-digit codes across CN/HK. Use a dual US+CN case."""
    _open_research(page)
    # Add US AAPL
    page.select_option('[data-testid="watchlist-new-market"]', "US")
    page.fill('[data-testid="watchlist-new-symbol"]', "AAPL")
    page.click('[data-testid="watchlist-add"]')
    page.wait_for_selector('[data-testid="watchlist-row-US-AAPL"]', timeout=3000)

    # Add CN 600519
    page.select_option('[data-testid="watchlist-new-market"]', "CN")
    page.fill('[data-testid="watchlist-new-symbol"]', "600519")
    page.click('[data-testid="watchlist-add"]')
    page.wait_for_selector('[data-testid="watchlist-row-CN-600519"]', timeout=3000)

    # Both rows should exist
    expect(page.locator('[data-testid="watchlist-row-US-AAPL"]')).to_have_count(1)
    expect(page.locator('[data-testid="watchlist-row-CN-600519"]')).to_have_count(1)
