"""End-to-end validation for /brief, /prep, /check workflow commands.

These three commands bind dashboard state to chat. Each must:
- fire /api/chat_stream with the right context_* query param
- leave an audit trail whose system prompt contains a DASHBOARD STATE block
"""
from __future__ import annotations

import json
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


def _reset_paper():
    try:
        req = urllib.request.Request(
            BASE_URL + f"api/paper/reset?project_id={PROJECT}&confirm=yes",
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5).read()
    except Exception:
        pass


@pytest.fixture(scope="module")
def browser():
    if not _backend_up():
        pytest.skip(f"backend not reachable at {BASE_URL}")
    if not _deepseek_up():
        pytest.skip("chat_stream upstream unreachable")
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture
def page(browser) -> Page:
    _clear_watchlist()
    _reset_paper()
    ctx = browser.new_context(viewport={"width": 1600, "height": 1100})
    page = ctx.new_page()
    yield page
    ctx.close()
    _clear_watchlist()
    _reset_paper()


def _open_chat(page: Page):
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_selector('[data-testid="chat-input"]')
    page.wait_for_selector('[data-testid="chat-input"]', timeout=30000)


def _type_and_wait_for_request(page: Page, text: str, url_predicate):
    page.fill('[data-testid="chat-input"]', text)
    with page.expect_request(url_predicate, timeout=60000) as req_info:
        page.click('[data-testid="chat-send"]')
    return req_info.value


def _latest_stream_request_audit():
    with urllib.request.urlopen(
        BASE_URL + "api/audit/recent?kind=request&limit=5", timeout=5
    ) as r:
        entries = json.loads(r.read()).get("entries", [])
    for e in entries:
        if (e.get("endpoint") or "") == "/api/chat_stream":
            return e["payload"]["messages"][0]["content"]
    return None




# 90s, not 30s: the agent answers a slash command in ~14s on an idle
# dashboard, but the full suite drives the same backend from many
# browsers at once and every test in this file waits on a streamed
# reply. A rotating subset of them timed out in four consecutive
# full runs while the file passed alone every time.
def _wait_for_reply(page, needle, timeout=90000):
    """Wait until the chat transcript contains `needle`.

    Replies stream in; a fixed wait_for_timeout samples a pane holding only
    the echoed command.
    """
    page.wait_for_function(
        """(n) => {
            const m = document.querySelector('[data-testid="chat-messages"]')
            return !!m && m.innerText.includes(n)
        }""",
        arg=needle,
        timeout=timeout,
    )

def test_brief_streams_with_context_project(page: Page):
    _open_chat(page)
    req = _type_and_wait_for_request(
        page, "/brief",
        lambda r: "/api/chat_stream" in r.url and "context_project=true" in r.url,
    )
    assert req is not None
    # Confirm the user bubble still shows /brief (workflow doesn't overwrite
    # the visible slash command — we just send a longer prompt behind the scenes)
    page.wait_for_timeout(500)
    msgs_text = page.evaluate(
        "document.querySelector('[data-testid=\"chat-messages\"]').innerText"
    )
    assert "/brief" in msgs_text


def test_brief_system_prompt_has_project_snapshot(page: Page):
    _open_chat(page)
    _type_and_wait_for_request(
        page, "/brief",
        lambda r: "/api/chat_stream" in r.url and "context_project=true" in r.url,
    )
    # The audit link only renders once the reply cites an audit entry, which
    # needs the upstream to actually answer.
    if not page.query_selector('[data-testid^="audit-link-"]'):
        try:
            page.wait_for_selector('[data-testid^="audit-link-"]', timeout=90000)
        except Exception:
            pytest.skip("reply produced no audit link — upstream did not answer")
    sys_prompt = _latest_stream_request_audit()
    assert sys_prompt is not None
    assert "DASHBOARD STATE" in sys_prompt
    assert "Project:" in sys_prompt
    # Workflow-specific instruction leaks into the system? No —
    # workflow prompt goes as the USER message. System carries
    # only the base persona + DASHBOARD STATE. Just verify that.


def test_prep_requires_symbol(page: Page):
    _open_chat(page)
    page.fill('[data-testid="chat-input"]', "/prep")
    page.click('[data-testid="chat-send"]')
    # /prep with no symbol answers with usage text; wait for that, not for the
    # echoed command.
    page.wait_for_function(
        """() => {
            const m = document.querySelector('[data-testid="chat-messages"]')
            if (!m) return false
            const t = m.innerText
            return t.includes('用法') || t.includes('AAPL')
        }""",
        timeout=90000,
    )
    msgs_text = page.evaluate(
        "document.querySelector('[data-testid=\"chat-messages\"]').innerText"
    )
    assert "用法" in msgs_text or "AAPL" in msgs_text


def test_prep_aapl_streams_with_context_symbol(page: Page):
    _open_chat(page)
    req = _type_and_wait_for_request(
        page, "/prep AAPL",
        lambda r: "/api/chat_stream" in r.url and "context_symbol=AAPL" in r.url,
    )
    assert req is not None


def test_prep_system_prompt_has_symbol_snapshot(page: Page):
    _open_chat(page)
    _type_and_wait_for_request(
        page, "/prep AAPL",
        lambda r: "/api/chat_stream" in r.url and "context_symbol=AAPL" in r.url,
    )
    # The audit link only renders once the reply cites an audit entry, which
    # needs the upstream to actually answer.
    if not page.query_selector('[data-testid^="audit-link-"]'):
        try:
            page.wait_for_selector('[data-testid^="audit-link-"]', timeout=90000)
        except Exception:
            pytest.skip("reply produced no audit link — upstream did not answer")
    sys_prompt = _latest_stream_request_audit()
    assert sys_prompt is not None
    assert "DASHBOARD STATE" in sys_prompt
    assert "AAPL" in sys_prompt


def test_check_streams_with_context_project(page: Page):
    _open_chat(page)
    req = _type_and_wait_for_request(
        page, "/check",
        lambda r: "/api/chat_stream" in r.url and "context_project=true" in r.url,
    )
    assert req is not None


def test_help_lists_workflow_commands(page: Page):
    _open_chat(page)
    page.fill('[data-testid="chat-input"]', "/help")
    page.click('[data-testid="chat-send"]')
    # Wait on something only the reply contains — "/help" is the echoed
    # command and is present the instant it is sent.
    _wait_for_reply(page, "/brief")
    msgs_text = page.evaluate(
        "document.querySelector('[data-testid=\"chat-messages\"]').innerText"
    )
    for name in ("/brief", "/prep", "/check"):
        assert name in msgs_text, f"{name} missing from /help output"
