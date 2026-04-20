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
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    page.wait_for_selector('[data-testid="tab-chat"]', timeout=8000)
    page.click('[data-testid="tab-chat"]')
    page.wait_for_selector('[data-testid="chat-input"]', timeout=5000)


def _type_and_wait_for_request(page: Page, text: str, url_predicate):
    page.fill('[data-testid="chat-input"]', text)
    with page.expect_request(url_predicate, timeout=20000) as req_info:
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
    page.wait_for_selector('[data-testid^="audit-link-"]', timeout=30000)
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
    page.wait_for_timeout(1200)
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
    page.wait_for_selector('[data-testid^="audit-link-"]', timeout=30000)
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
    page.wait_for_timeout(1200)
    msgs_text = page.evaluate(
        "document.querySelector('[data-testid=\"chat-messages\"]').innerText"
    )
    for name in ("/brief", "/prep", "/check"):
        assert name in msgs_text, f"{name} missing from /help output"
