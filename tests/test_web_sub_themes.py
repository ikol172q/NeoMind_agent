"""D6 · Playwright — DigestView renders L1.5 sub_themes section
when the endpoint payload has a non-empty sub_themes array.
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


def _calls_ok_with_sub_themes() -> bool:
    """Skip when the live endpoint doesn't have sub_themes populated
    — either the YAML didn't ship the block or the cluster produced
    zero matches (in which case the section intentionally won't
    render)."""
    try:
        with urllib.request.urlopen(
            BASE_URL + f"api/lattice/calls?project_id={PROJECT}", timeout=120,
        ) as r:
            d = json.loads(r.read())
        return len(d.get("sub_themes") or []) > 0
    except Exception:
        return False


@pytest.fixture(scope="module")
def browser():
    if not _backend_up():
        pytest.skip(f"backend not reachable at {BASE_URL}")
    if not _calls_ok_with_sub_themes():
        pytest.skip("no sub_themes in live payload (YAML absent or zero matches)")
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture
def page(browser) -> Page:
    ctx = browser.new_context(viewport={"width": 1600, "height": 1200})
    page = ctx.new_page()
    yield page
    ctx.close()


def _open_research(page: Page):
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    page.wait_for_selector('[data-testid="tab-research"]')
    page.click('[data-testid="tab-research"]')
    page.wait_for_selector('[data-testid="digest-view"]', timeout=15000)


def test_drilldown_mode_shows_l15_section(page: Page):
    _open_research(page)
    page.click('[data-testid="digest-mode-drilldown"]')
    page.wait_for_selector('[data-testid="section-l15"]', timeout=5000)


def test_flat_mode_expands_sub_themes(page: Page):
    """Flat mode opens every accordion — L1.5 section's theme rows
    should be visible directly after switching."""
    _open_research(page)
    page.click('[data-testid="digest-mode-flat"]')
    page.wait_for_selector('[data-testid="section-l15"]', timeout=5000)
    # At least one sub-theme row rendered (drill-theme-subtheme_...)
    page.wait_for_selector('[data-testid^="drill-theme-subtheme_"]', timeout=5000)


def test_summary_mode_hides_sub_themes_section(page: Page):
    """Summary mode is L3-only by design — sub_themes section must
    not leak into it."""
    _open_research(page)
    page.click('[data-testid="digest-mode-summary"]')
    page.wait_for_timeout(400)
    present = page.evaluate(
        "!!document.querySelector('[data-testid=\"section-l15\"]')"
    )
    assert not present, "L1.5 section leaked into summary mode"
