"""V7 · Playwright — SVG zoom/pan + L1→L0 widget jump.

Gates:
  - Zoom controls exist and change lattice-zoom-level text
  - Zoom in/out toggles the SVG's viewport <g> transform (data-
    zoom-scale attr moves with it)
  - Reset view returns to scale=1
  - L1 node panel shows a "jump to widget" button when the obs has
    a source.widget; clicking scrolls + adds lattice-source-
    highlight class to the correct widget wrapper
"""
from __future__ import annotations

import json
import urllib.request

import pytest
from playwright.sync_api import Page, sync_playwright


BASE_URL = "http://127.0.0.1:8001/"

pytestmark = pytest.mark.lattice_slow


def _backend_up() -> bool:
    try:
        with urllib.request.urlopen(BASE_URL + "api/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


@pytest.fixture(scope="module")
def graph():
    if not _backend_up():
        pytest.skip(f"backend not reachable at {BASE_URL}")
    with urllib.request.urlopen(
        BASE_URL + "api/lattice/graph?project_id=fin-core", timeout=300,
    ) as r:
        return json.loads(r.read())


@pytest.fixture(scope="module")
def browser(graph):
    if not graph.get("nodes"):
        pytest.skip("graph empty")
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


def _open_trace(page: Page):
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    page.wait_for_selector('[data-testid="tab-research"]')
    page.click('[data-testid="tab-research"]')
    page.wait_for_selector('[data-testid="digest-view"]', timeout=15000)
    page.click('[data-testid="digest-mode-trace"]')
    page.wait_for_selector('[data-testid="lattice-svg"]', state="attached", timeout=15000)
    page.wait_for_timeout(600)


# ── Zoom controls ──────────────────────────────────────

def test_zoom_controls_visible(page):
    _open_trace(page)
    for tid in ("lattice-zoom-in", "lattice-zoom-out", "lattice-zoom-reset", "lattice-zoom-level"):
        assert page.locator(f'[data-testid="{tid}"]').count() == 1, f"missing {tid}"


def test_initial_zoom_is_100(page):
    _open_trace(page)
    lvl = page.locator('[data-testid="lattice-zoom-level"]').inner_text().strip()
    assert lvl == "100%"
    scale = page.get_attribute('[data-testid="lattice-svg"]', "data-zoom-scale")
    assert scale == "1.000"


def test_zoom_in_increases_scale_and_level(page):
    _open_trace(page)
    page.click('[data-testid="lattice-zoom-in"]')
    page.wait_for_timeout(200)
    level_text = page.locator('[data-testid="lattice-zoom-level"]').inner_text().strip()
    # 1.18x ≈ 118%
    assert level_text == "118%", level_text
    scale = float(page.get_attribute('[data-testid="lattice-svg"]', "data-zoom-scale"))
    assert 1.17 < scale < 1.19


def test_zoom_out_decreases_scale(page):
    _open_trace(page)
    page.click('[data-testid="lattice-zoom-out"]')
    page.wait_for_timeout(200)
    scale = float(page.get_attribute('[data-testid="lattice-svg"]', "data-zoom-scale"))
    assert scale < 1.0


def test_zoom_reset_returns_to_identity(page):
    _open_trace(page)
    page.click('[data-testid="lattice-zoom-in"]')
    page.click('[data-testid="lattice-zoom-in"]')
    page.wait_for_timeout(100)
    page.click('[data-testid="lattice-zoom-reset"]')
    page.wait_for_timeout(200)
    level = page.locator('[data-testid="lattice-zoom-level"]').inner_text().strip()
    assert level == "100%"
    scale = page.get_attribute('[data-testid="lattice-svg"]', "data-zoom-scale")
    assert scale == "1.000"


def test_zoom_has_clamped_upper_and_lower_bounds(page):
    """Spam zoom-in many times — must cap at 200% (ZOOM_MAX=2.0).
    Same for zoom-out bottom (ZOOM_MIN=0.5 → 50%).

    Post-V8: bounds tightened because at ≥2.5x the node-bbox clamp
    lets the viewport show mostly whitespace between columns/rows,
    which the user perceives as a 'black screen'."""
    _open_trace(page)
    for _ in range(20):
        page.click('[data-testid="lattice-zoom-in"]')
    page.wait_for_timeout(200)
    scale = float(page.get_attribute('[data-testid="lattice-svg"]', "data-zoom-scale"))
    assert scale <= 2.0 + 1e-6, f"zoom should cap at 2.0x, got {scale}"

    page.click('[data-testid="lattice-zoom-reset"]')
    page.wait_for_timeout(100)
    for _ in range(20):
        page.click('[data-testid="lattice-zoom-out"]')
    page.wait_for_timeout(200)
    scale = float(page.get_attribute('[data-testid="lattice-svg"]', "data-zoom-scale"))
    assert scale >= 0.5 - 1e-6, f"zoom should floor at 0.5x, got {scale}"


# ── L1 → L0 widget jump ───────────────────────────────

def test_l1_obs_with_widget_source_has_jump_button(page, graph):
    """L1 nodes whose attrs.source.widget is mapped to a Research
    widget must expose a 'jump to widget' button when selected."""
    _open_trace(page)
    obs_with_widget = next(
        (n for n in graph["nodes"]
         if n["layer"] == "L1"
         and (n["attrs"].get("source") or {}).get("widget") in
             ("earnings", "portfolio", "sectors", "sentiment", "news", "technical")),
        None,
    )
    if not obs_with_widget:
        pytest.skip("no L1 obs with a mapped source.widget in current state")
    page.locator(f'[data-node-id="{obs_with_widget["id"]}"]').click(force=True)
    page.wait_for_selector('[data-testid="trace-node-detail"]', state="attached", timeout=3000)
    assert page.locator('[data-testid="trace-jump-to-widget"]').count() == 1


def test_click_jump_adds_highlight_class_to_target_widget(page, graph):
    _open_trace(page)
    # Find an L1 obs whose source.widget has a data-widget-source
    # attribute in the DOM
    sources = page.evaluate("""
        () => Array.from(document.querySelectorAll('[data-widget-source]'))
            .map(el => el.getAttribute('data-widget-source'))
    """)
    assert sources, "no data-widget-source attrs present in DOM"
    target_widget = sources[0]
    obs = next(
        (n for n in graph["nodes"]
         if n["layer"] == "L1"
         and (n["attrs"].get("source") or {}).get("widget") == target_widget),
        None,
    )
    if not obs:
        pytest.skip(f"no L1 obs maps to widget {target_widget!r} today")
    page.locator(f'[data-node-id="{obs["id"]}"]').click(force=True)
    page.wait_for_selector('[data-testid="trace-jump-to-widget"]', timeout=3000)
    page.click('[data-testid="trace-jump-to-widget"]')
    # Highlight is applied synchronously; check immediately
    page.wait_for_timeout(150)
    cls = page.evaluate(
        f"document.querySelector('[data-widget-source=\"{target_widget}\"]').className"
    )
    assert "lattice-source-highlight" in cls, (
        f"expected lattice-source-highlight on {target_widget!r}, got: {cls}"
    )
