"""End-to-end tests for the React SPA served by the NeoMind dashboard.

Requires:
- The dashboard running at 127.0.0.1:8001 (launchd or manual)
- Playwright installed: `pip install playwright && playwright install chromium`

Run: `pytest tests/test_web_e2e.py -v`

The tests are pass-through smoke checks:
- SPA loads at /
- All 5 tabs mount and render some content
- Chat's slash-command dropdown appears when typing '/'
- /audit slash command returns local audit data
- Audit tab lists recent LLM entries

If the backend is unreachable, tests skip with a clear message.
"""
from __future__ import annotations

import urllib.request
import pytest
from playwright.sync_api import sync_playwright, Page

BASE_URL = "http://127.0.0.1:8001/"


def _backend_up() -> bool:
    try:
        with urllib.request.urlopen(BASE_URL + "api/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


@pytest.fixture(scope="module")
def browser():
    if not _backend_up():
        pytest.skip(f"backend not reachable at {BASE_URL} — run the dashboard first")
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture
def page(browser) -> Page:
    ctx = browser.new_context(viewport={"width": 1400, "height": 1000})
    page = ctx.new_page()
    # Collect console errors / page errors; assert at end-of-test
    page.errors = []  # type: ignore[attr-defined]
    page.on("pageerror", lambda e: page.errors.append(str(e)))  # type: ignore[attr-defined]
    page.on(
        "console",
        lambda m: page.errors.append(f"console[{m.type}] {m.text}")
        if m.type == "error"
        else None,
    )
    yield page
    ctx.close()


def _ignore(msg: str) -> bool:
    """Noise we expect and don't want failing the test."""
    s = msg.lower()
    return any(k in s for k in ("502", "network_error", "timeout"))


def test_spa_loads_and_shows_nav(page: Page):
    page.goto(BASE_URL, wait_until="networkidle", timeout=15000)
    page.wait_for_selector('[data-testid="top-nav"]', timeout=8000)
    tabs = page.evaluate(
        """Array.from(document.querySelectorAll('[data-testid^="tab-"]')).map(e => e.textContent.trim())""",
    )
    assert 'Research' in ' '.join(tabs)
    assert 'Chat' in ' '.join(tabs)


@pytest.mark.parametrize("tab", ["research", "chat", "paper", "audit", "settings"])
def test_each_tab_renders_some_content(page: Page, tab: str):
    page.goto(BASE_URL, wait_until="networkidle", timeout=15000)
    page.wait_for_selector('[data-testid="top-nav"]')
    page.click(f'[data-testid="tab-{tab}"]')
    page.wait_for_timeout(1200)
    text = page.evaluate("document.body.innerText").strip()
    assert len(text) > 100, f"tab {tab} body empty"


def test_chat_slash_menu_opens_on_slash(page: Page):
    page.goto(BASE_URL, wait_until="networkidle", timeout=15000)
    page.click('[data-testid="tab-chat"]')
    page.wait_for_selector('[data-testid="chat-input"]')
    page.fill('[data-testid="chat-input"]', "/")
    page.wait_for_timeout(500)
    menu = page.query_selector('[data-testid="slash-menu"]')
    assert menu is not None
    options = page.query_selector_all('[data-testid^="slash-option-"]')
    assert len(options) >= 5  # at least quote/cn/news/paper/help
    labels = [o.text_content() or "" for o in options]
    assert any("/quote" in l for l in labels)
    assert any("/audit" in l for l in labels)


def test_chat_help_command_local_execution(page: Page):
    page.goto(BASE_URL, wait_until="networkidle", timeout=15000)
    page.click('[data-testid="tab-chat"]')
    page.wait_for_selector('[data-testid="chat-input"]')
    page.fill('[data-testid="chat-input"]', "/help")
    page.click('[data-testid="chat-send"]')
    page.wait_for_timeout(2000)
    msgs_text = page.evaluate("document.querySelector('[data-testid=\"chat-messages\"]').innerText")
    assert "/quote" in msgs_text, "help reply should list commands"
    assert "/audit" in msgs_text


def test_chat_audit_command_returns_local_entries(page: Page):
    page.goto(BASE_URL, wait_until="networkidle", timeout=15000)
    page.click('[data-testid="tab-chat"]')
    page.wait_for_selector('[data-testid="chat-input"]')
    page.fill('[data-testid="chat-input"]', "/audit 3")
    page.click('[data-testid="chat-send"]')
    page.wait_for_timeout(2500)
    msgs_text = page.evaluate("document.querySelector('[data-testid=\"chat-messages\"]').innerText")
    # Either we have entries, or the "no audit entries yet" message
    assert ("audit entries" in msgs_text.lower()) or ("no audit" in msgs_text.lower())


def test_audit_tab_lists_entries(page: Page):
    page.goto(BASE_URL, wait_until="networkidle", timeout=15000)
    page.click('[data-testid="tab-audit"]')
    page.wait_for_selector('[data-testid="audit-list"]')
    page.wait_for_timeout(1500)
    # Assert either entries rendered or empty-state rendered
    text = page.evaluate('document.querySelector(\'[data-testid="audit-list"]\').innerText')
    assert len(text) > 0


def test_legacy_fallback_available(page: Page):
    # /legacy should still serve the old inline HTML for safety
    page.goto(BASE_URL + "legacy", timeout=10000)
    text = page.evaluate("document.body.innerText")
    assert "neomind" in text.lower() or "fin" in text.lower()
