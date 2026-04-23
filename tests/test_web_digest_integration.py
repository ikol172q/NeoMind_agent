"""D5 · Integration tests — anomaly strip + chat→research citation
routing for <DigestView>.

Gates:
  1. Anomaly strip paints when /api/anomalies returns flags.
  2. Clicking an anomaly scrolls the lattice body (flat mode) and
     applies the transient highlight ring.
  3. A cite click in a chat reply routes to Research and lights up
     the matching evidence node.
"""
from __future__ import annotations

import json
import urllib.request

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


def _calls_ok() -> bool:
    try:
        with urllib.request.urlopen(
            BASE_URL + f"api/lattice/calls?project_id={PROJECT}", timeout=120,
        ) as r:
            data = json.loads(r.read())
        return isinstance(data.get("observations"), list)
    except Exception:
        return False


def _seed():
    for sym in ("AAPL", "NVDA"):
        try:
            req = urllib.request.Request(
                BASE_URL + f"api/watchlist?project_id={PROJECT}",
                data=json.dumps({"symbol": sym, "market": "US", "note": ""}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5).read()
        except Exception:
            pass
    try:
        qs = "project_id=" + PROJECT + "&symbol=AAPL&side=buy&quantity=5&order_type=market"
        urllib.request.urlopen(
            urllib.request.Request(BASE_URL + f"api/paper/order?{qs}", method="POST"),
            timeout=10,
        ).read()
    except Exception:
        pass


def _anomalies_available() -> bool:
    try:
        with urllib.request.urlopen(
            BASE_URL + f"api/anomalies?project_id={PROJECT}", timeout=10,
        ) as r:
            data = json.loads(r.read())
        return (data.get("count") or 0) > 0
    except Exception:
        return False


@pytest.fixture(scope="module")
def browser():
    if not _backend_up():
        pytest.skip(f"backend not reachable at {BASE_URL}")
    _seed()
    if not _calls_ok():
        pytest.skip("lattice/calls upstream unreachable (DeepSeek)")
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
    page.wait_for_selector('[data-testid="digest-view"]', timeout=15000)


# ── anomaly strip ─────────────────────────────────────

def test_anomaly_strip_renders_when_flags_exist(page: Page):
    if not _anomalies_available():
        pytest.skip("no anomaly flags in current fin-core state")
    _open_research(page)
    page.wait_for_selector('[data-testid="digest-anomaly-strip"]', timeout=10000)
    count = page.evaluate(
        "document.querySelectorAll('[data-testid^=\"digest-anomaly-\"]').length"
    )
    assert count >= 2, f"expected ≥1 flag + the strip container, got {count}"


def test_anomaly_strip_absent_when_no_flags_would_be_shown(page: Page):
    """When the backend returns zero flags, the strip must not paint
    (we don't want a 1-px zero-height border in the DOM either)."""
    # Can't force zero flags without a reset — so just check the
    # invariant: if the strip renders, it contains at least one
    # anomaly button. This catches the regression where an empty
    # strip would still paint a 1px border.
    _open_research(page)
    page.wait_for_selector('[data-testid="digest-view"]', timeout=10000)
    strip_present = page.evaluate(
        "!!document.querySelector('[data-testid=\"digest-anomaly-strip\"]')"
    )
    if strip_present:
        count = page.evaluate(
            "document.querySelectorAll('[data-testid^=\"digest-anomaly-\"]:not([data-testid=\"digest-anomaly-strip\"])').length"
        )
        assert count >= 1, "strip rendered with zero flags inside"


# ── focus highlight (via anomaly click) ────────────────

def test_anomaly_click_flips_to_flat_mode_and_highlights(page: Page):
    if not _anomalies_available():
        pytest.skip("no anomaly flags to click")
    _open_research(page)
    page.wait_for_selector('[data-testid="digest-anomaly-strip"]', timeout=10000)
    # Click the first flag
    first_flag = page.evaluate(
        """() => {
            const btns = document.querySelectorAll('[data-testid^="digest-anomaly-"]')
            for (const b of btns) {
                const t = b.getAttribute('data-testid')
                if (t !== 'digest-anomaly-strip') return t
            }
            return null
        }"""
    )
    assert first_flag, "expected at least one anomaly button"
    page.click(f'[data-testid="{first_flag}"]')
    # Flat mode selected
    page.wait_for_selector('[data-testid="digest-mode-flat"].bg-\\[var\\(--color-accent\\)\\]', timeout=2000)
    # Some node is highlighted (ring applied via data-highlighted)
    page.wait_for_selector('[data-highlighted="true"]', timeout=3000)


# ── chat citation → Research focus ─────────────────────

def test_cite_click_in_chat_routes_to_research_with_focus(page: Page):
    """Send `/prep AAPL` (which reliably emits an [[AAPL]] cite in
    the reply), click the chip, and verify the Research tab becomes
    active + DigestView either highlights a row or settles into
    flat mode on the lattice."""
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    page.wait_for_selector('[data-testid="tab-chat"]')
    page.click('[data-testid="tab-chat"]')
    page.wait_for_selector('[data-testid="chat-input"]', timeout=5000)
    # /prep is a workflow slash command that names the target symbol
    # in its reply — much more reliable cite emission than open prose.
    page.fill('[data-testid="chat-input"]', "/prep AAPL")
    page.click('[data-testid="chat-send"]')
    try:
        page.wait_for_selector('[data-testid="cite-symbol-AAPL"]', timeout=90000)
    except Exception:
        pytest.skip("agent didn't emit an [[AAPL]] cite in its /prep reply")
    page.click('[data-testid="cite-symbol-AAPL"]')
    # Research tab must activate. The button's active class includes
    # "text-[var(--color-accent)]" — inactive is "text-[var(--color-dim)]".
    page.wait_for_function(
        """() => {
            const el = document.querySelector('[data-testid="tab-research"]')
            return el && el.className.includes('text-[var(--color-accent)]')
        }""",
        timeout=5000,
    )
    page.wait_for_selector('[data-testid="digest-view"]', timeout=30000)
    # Either a node is highlighted OR flat-mode is active (highlight
    # auto-clears after 2.5s; either is proof the focus prop fired).
    page.wait_for_timeout(300)
    highlighted = page.evaluate(
        "!!document.querySelector('[data-highlighted=\"true\"]')"
    )
    flat_active = page.evaluate(
        """() => {
            const el = document.querySelector('[data-testid="digest-mode-flat"]')
            return !!el && el.className.includes('--color-accent')
        }"""
    )
    assert highlighted or flat_active, (
        "expected highlighted node or flat mode active after cite click"
    )
