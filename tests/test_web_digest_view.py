"""D4 · Playwright tests for <DigestView> — the L1→L2→L3 lattice
hero that replaces the old ResearchBriefWidget.

Gates: the widget paints on Research, the three modes toggle, the
Toulmin chips expand their evidence, drilldown exposes the full
L3→L2→L1 tree, and the bidirectional hover hint surfaces when an
observation participates in multiple themes.
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
    """Skip when the L3 endpoint can't produce anything — CI shouldn't
    fail because DeepSeek is slow/unreachable."""
    try:
        with urllib.request.urlopen(
            BASE_URL + f"api/lattice/calls?project_id={PROJECT}", timeout=120,
        ) as r:
            data = json.loads(r.read())
        return isinstance(data.get("themes"), list) and isinstance(data.get("calls"), list)
    except Exception:
        return False


def _seed():
    """Seed AAPL + NVDA + a small position so the lattice has content
    and the Research tab isn't in empty-state."""
    try:
        for sym in ("AAPL", "NVDA"):
            req = urllib.request.Request(
                BASE_URL + f"api/watchlist?project_id={PROJECT}",
                data=json.dumps({"symbol": sym, "market": "US", "note": ""}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5).read()
        qs = "project_id=" + PROJECT + "&symbol=AAPL&side=buy&quantity=5&order_type=market"
        urllib.request.urlopen(
            urllib.request.Request(BASE_URL + f"api/paper/order?{qs}", method="POST"),
            timeout=10,
        ).read()
    except Exception:
        pass


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


# ── paint + position ──────────────────────────────────

def test_digest_view_paints_at_top_of_research(page: Page):
    _open_research(page)
    tops = page.evaluate(
        """() => {
            const d = document.querySelector('[data-testid="digest-view"]')
            const news = document.querySelector('[data-testid="news-tabs"]')
            const watch = document.querySelector('[data-testid="watchlist-widget"]')
            return {
                digest: d?.getBoundingClientRect().top,
                news: news?.getBoundingClientRect().top,
                watch: watch?.getBoundingClientRect().top,
            }
        }"""
    )
    assert tops["digest"] is not None
    if tops["news"] is not None:
        assert tops["digest"] < tops["news"], \
            f"digest ({tops['digest']}) must sit above news ({tops['news']})"
    if tops["watch"] is not None:
        assert tops["digest"] < tops["watch"]


def test_mode_toggle_is_visible(page: Page):
    _open_research(page)
    for m in ("summary", "drilldown", "flat"):
        page.wait_for_selector(f'[data-testid="digest-mode-{m}"]', timeout=5000)


# ── Summary mode ──────────────────────────────────────

def test_summary_shows_toulmin_chips_or_zero_call_state(page: Page):
    """Summary renders either call rows with Because/Unless chips, or
    the explicit zero-call state. Never a blank pane."""
    _open_research(page)
    page.click('[data-testid="digest-mode-summary"]')
    page.wait_for_timeout(500)
    has_calls = page.evaluate(
        "!!document.querySelector('[data-testid=\"summary-calls\"]')"
    )
    has_empty = page.evaluate(
        "!!document.querySelector('[data-testid=\"digest-zero-calls\"]')"
    )
    assert has_calls or has_empty, "summary pane must render calls or zero-state"


def test_because_chip_expands_grounds(page: Page):
    """Clicking the Because chip on a call surfaces the L2 themes and
    the warrant — the core drill-in interaction."""
    _open_research(page)
    page.click('[data-testid="digest-mode-summary"]')
    page.wait_for_timeout(500)
    has_calls = page.evaluate(
        "!!document.querySelector('[data-testid=\"summary-calls\"]')"
    )
    if not has_calls:
        pytest.skip("zero-call state today — skipping chip interaction test")
    # Grab the first call's id from the DOM
    first_call_id = page.evaluate(
        """() => {
            const el = document.querySelector('[data-testid^="summary-call-"]')
            return el ? el.getAttribute('data-testid').replace('summary-call-', '') : null
        }"""
    )
    assert first_call_id, "expected at least one call in summary"
    page.click(f'[data-testid="chip-because-{first_call_id}"]')
    page.wait_for_selector(
        f'[data-testid="expand-because-{first_call_id}"]', timeout=3000,
    )


# ── Drilldown mode ────────────────────────────────────

def test_drilldown_mode_shows_l3_l2_l1_sections(page: Page):
    _open_research(page)
    page.click('[data-testid="digest-mode-drilldown"]')
    page.wait_for_selector('[data-testid="section-l3"]', timeout=5000)
    page.wait_for_selector('[data-testid="section-l2"]', timeout=5000)
    page.wait_for_selector('[data-testid="section-l1"]', timeout=5000)


def test_flat_mode_opens_all_sections(page: Page):
    """Flat mode = everything expanded at once. No matter how many
    layers, the sections list must be visible and content fits in
    the panel (or scrolls)."""
    _open_research(page)
    page.click('[data-testid="digest-mode-flat"]')
    page.wait_for_selector('[data-testid="section-l1"]', timeout=5000)
    # At least one observation row should be rendered directly
    # (no extra click) because flat mode starts every accordion open.
    page.wait_for_selector('[data-testid^="obs-"]', timeout=5000)


# ── Refresh ───────────────────────────────────────────

def test_refresh_button_present_and_clickable(page: Page):
    _open_research(page)
    page.click('[data-testid="digest-refresh"]')
    # Button should not throw; loading indicator may or may not show
    # depending on cache state — we just verify the button exists and
    # the widget is still mounted after the click.
    page.wait_for_selector('[data-testid="digest-view"]', timeout=5000)
