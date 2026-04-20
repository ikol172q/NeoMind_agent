"""End-to-end validation for chat streaming + session persistence +
audit linking.

Covers user-visible flows:
  1. Send a free-form prompt → reply streams in token-by-token
     (content length grows over multiple animation frames, not one
     big dump).
  2. Each assistant bubble carries a ``raw`` button with a valid
     req_id — clicking it switches to the Audit tab, seeds the
     search box, and expands the matching entry.
  3. After a turn, the session appears in the sidebar. Switching
     tabs away and back preserves the message list. Reloading the
     page also preserves it (localStorage cache).
  4. Clicking a past session in the sidebar loads its messages.
  5. The "new session" button starts fresh (empty message list,
     new session id).

All tests require DEEPSEEK_API_KEY visible to the dashboard process;
if the streaming endpoint 503s, tests skip (not fail) so this suite
can run in CI without leaking credentials.

Run: ``pytest tests/test_web_chat_persistence.py -v``
"""
from __future__ import annotations

import json
import time
import urllib.request
import urllib.error

import pytest
from playwright.sync_api import Page, expect, sync_playwright

BASE_URL = "http://127.0.0.1:8001/"


def _backend_up() -> bool:
    try:
        with urllib.request.urlopen(BASE_URL + "api/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def _deepseek_up() -> bool:
    """Probe a trivial streaming request to see whether the upstream
    credential is reachable. We don't need the full response — a
    200-with-SSE header is enough."""
    try:
        req = urllib.request.Request(
            BASE_URL + "api/chat_stream?project_id=fin-core&message=ping",
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            # If the endpoint returns a stream, reading one chunk is enough
            first = r.read(64)
            return len(first) > 0
    except urllib.error.HTTPError as e:
        return e.code < 500  # 400 means validation worked but key ok
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
    ctx = browser.new_context(viewport={"width": 1400, "height": 1000})
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


def _open_chat(page: Page):
    page.goto(BASE_URL, wait_until="networkidle", timeout=15000)
    page.click('[data-testid="tab-chat"]')
    page.wait_for_selector('[data-testid="chat-input"]')
    page.wait_for_selector('[data-testid="chat-session-sidebar"]')


def test_streaming_delivers_incremental_tokens(page: Page):
    """The reply should grow over time, not land in one chunk."""
    if not _deepseek_up():
        pytest.skip("DEEPSEEK upstream not reachable — skipping streaming test")

    _open_chat(page)
    page.fill('[data-testid="chat-input"]', "Say exactly: ONE TWO THREE FOUR FIVE")
    page.click('[data-testid="chat-send"]')

    # Sample content length over 2 seconds — it should monotonically
    # grow (not just pop to final length immediately).
    samples: list[int] = []
    deadline = time.monotonic() + 6.0
    while time.monotonic() < deadline:
        txt = page.evaluate(
            "document.querySelector('[data-testid=\"chat-messages\"]').innerText"
        )
        samples.append(len(txt))
        # Stop once we have enough distinct samples to detect growth
        if len(samples) >= 8 and samples[-1] > samples[0]:
            break
        page.wait_for_timeout(300)

    distinct = len(set(samples))
    assert distinct >= 2, f"reply not streaming (all samples identical): {samples}"
    assert samples[-1] > 0, "no content rendered"


def test_raw_button_jumps_to_audit(page: Page):
    if not _deepseek_up():
        pytest.skip("DEEPSEEK upstream not reachable — skipping streaming test")

    _open_chat(page)
    page.fill('[data-testid="chat-input"]', "What is 2+2? answer very briefly.")
    page.click('[data-testid="chat-send"]')

    # Wait for the raw button to appear (means stream completed w/ req_id)
    raw_btn_sel = '[data-testid^="audit-link-"]'
    page.wait_for_selector(raw_btn_sel, timeout=30000)

    btn = page.query_selector(raw_btn_sel)
    assert btn is not None
    test_id = btn.get_attribute("data-testid") or ""
    # Shape: audit-link-<first 8 of req_id>
    assert test_id.startswith("audit-link-"), test_id

    btn.click()
    # We should now be on the Audit tab, search box prepopulated
    page.wait_for_selector('[data-testid="audit-list"]', timeout=4000)
    search = page.locator('[data-testid="audit-search"]')
    expect(search).not_to_have_value("")


def test_session_persists_across_tab_switch(page: Page):
    _open_chat(page)
    # Slash command → instant reply, no DeepSeek dependency
    page.fill('[data-testid="chat-input"]', "/help")
    page.click('[data-testid="chat-send"]')
    page.wait_for_timeout(1500)

    before = page.evaluate(
        "document.querySelector('[data-testid=\"chat-messages\"]').innerText"
    )
    assert "/quote" in before

    sid_el = page.query_selector('[data-testid="chat-session-id"]')
    assert sid_el is not None, "session id should be shown after first message"
    sid_before = sid_el.text_content() or ""
    assert len(sid_before) >= 4

    # Switch to Research then back
    page.click('[data-testid="tab-research"]')
    page.wait_for_timeout(500)
    page.click('[data-testid="tab-chat"]')
    page.wait_for_selector('[data-testid="chat-input"]')
    page.wait_for_timeout(300)

    after = page.evaluate(
        "document.querySelector('[data-testid=\"chat-messages\"]').innerText"
    )
    assert "/quote" in after, "messages should persist across tab switch"
    sid_after = page.text_content('[data-testid="chat-session-id"]') or ""
    assert sid_after == sid_before, "session id should stay stable on re-mount"


def test_session_persists_across_page_reload(page: Page):
    _open_chat(page)
    page.fill('[data-testid="chat-input"]', "/help")
    page.click('[data-testid="chat-send"]')
    page.wait_for_timeout(1500)

    sid_before = page.text_content('[data-testid="chat-session-id"]') or ""
    assert sid_before, "should have a session id after /help"

    page.reload(wait_until="networkidle")
    page.click('[data-testid="tab-chat"]')
    page.wait_for_selector('[data-testid="chat-input"]')
    page.wait_for_timeout(300)

    sid_after = page.text_content('[data-testid="chat-session-id"]') or ""
    assert sid_after == sid_before, \
        f"session should restore from localStorage after reload: {sid_before!r} → {sid_after!r}"
    text = page.evaluate(
        "document.querySelector('[data-testid=\"chat-messages\"]').innerText"
    )
    assert "/quote" in text, "message body should restore from localStorage"


def test_reload_does_not_create_phantom_session(page: Page):
    """Regression: reload was creating a brand-new session each time
    instead of restoring the one from localStorage, leaving orphan
    records on disk."""
    _open_chat(page)
    page.fill('[data-testid="chat-input"]', "/help")
    page.click('[data-testid="chat-send"]')
    page.wait_for_timeout(1500)
    sid_before = page.text_content('[data-testid="chat-session-id"]') or ""
    assert sid_before

    # Count session files currently on disk, via the API
    import json as _json
    before_list = _json.loads(
        urllib.request.urlopen(
            BASE_URL + "api/chat_sessions?project_id=fin-core&limit=500", timeout=5
        ).read()
    )
    before_count = before_list["count"]

    page.reload(wait_until="networkidle")
    page.click('[data-testid="tab-chat"]')
    page.wait_for_selector('[data-testid="chat-input"]')
    # Do a second turn on the SAME session (should reuse, not create)
    page.fill('[data-testid="chat-input"]', "/help")
    page.click('[data-testid="chat-send"]')
    page.wait_for_timeout(1500)

    sid_after = page.text_content('[data-testid="chat-session-id"]') or ""
    assert sid_after == sid_before, \
        f"reload must reuse session, got {sid_before!r} → {sid_after!r}"

    after_list = _json.loads(
        urllib.request.urlopen(
            BASE_URL + "api/chat_sessions?project_id=fin-core&limit=500", timeout=5
        ).read()
    )
    after_count = after_list["count"]
    assert after_count == before_count, \
        f"reload must not create a new session ({before_count} → {after_count})"


def test_sidebar_lists_session_and_new_button_starts_fresh(page: Page):
    _open_chat(page)
    page.fill('[data-testid="chat-input"]', "/help")
    page.click('[data-testid="chat-send"]')
    page.wait_for_timeout(1500)

    # Wait for the sidebar list to populate (ignore the known non-row
    # testids that also start with "chat-session-")
    page.wait_for_function(
        """() => {
            const list = document.querySelector('[data-testid="chat-session-list"]')
            if (!list) return false
            const rows = list.querySelectorAll('[data-testid^="chat-session-"]')
            return rows.length > 0
        }""",
        timeout=5000,
    )
    rows = page.evaluate(
        """() => Array.from(
            document.querySelector('[data-testid="chat-session-list"]')
                ?.querySelectorAll('[data-testid^="chat-session-"]') ?? []
        ).map(e => e.getAttribute('data-testid'))"""
    )
    assert len(rows) >= 1, f"sidebar should list at least one session, got {rows}"

    sid_before = page.text_content('[data-testid="chat-session-id"]') or ""

    # Click new-session
    page.click('[data-testid="chat-new-session"]')
    page.wait_for_timeout(300)

    # Empty view, no session id chip yet
    text = page.evaluate(
        "document.querySelector('[data-testid=\"chat-messages\"]').innerText"
    )
    assert "/quote" not in text, "new-session button should clear messages"
    sid_chip = page.query_selector('[data-testid="chat-session-id"]')
    assert sid_chip is None, "new-session button should clear the session id chip"

    # Click the original session to reload it
    original_row = f'[data-testid="chat-session-{sid_before[:8]}"]'
    page.click(original_row)
    page.wait_for_selector('[data-testid="chat-session-id"]', timeout=4000)
    page.wait_for_timeout(300)
    text2 = page.evaluate(
        "document.querySelector('[data-testid=\"chat-messages\"]').innerText"
    )
    assert "/quote" in text2, "loading past session should restore messages"
