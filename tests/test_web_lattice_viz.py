"""L5 · visualization ↔ graph correctness (Playwright).

Gates:
  1. DOM zero-ghost: every <g data-node-id="X"> and every
     <g data-edge-source="A" data-edge-target="B"> corresponds
     to a node/edge in /api/lattice/graph. No phantoms.
  2. Node count per layer matches graph.meta.layer_counts.
  3. Edge count per kind matches graph.meta.edge_counts.
  4. Provenance visual encoding: llm+* nodes render as diamonds,
     deterministic/source render as rects. Enforced via
     node-shape-* class names.
  5. Interaction: clicking a membership edge opens a panel whose
     displayed `final` value equals the edge's
     computation.detail.final FROM THE GRAPH PAYLOAD (no second
     computation; this test reads both from the same truth
     source to catch any UI-side rounding/drift).
"""
from __future__ import annotations

import json
import urllib.request

import pytest
from playwright.sync_api import Page, sync_playwright

from tests.web_nav import goto_tab, pin_project
from tests.fixture_project import PROJECT


BASE_URL = "http://127.0.0.1:8001/"

pytestmark = pytest.mark.lattice_slow


def _backend_up() -> bool:
    try:
        with urllib.request.urlopen(BASE_URL + "api/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def _fetch_graph() -> dict:
    with urllib.request.urlopen(
        BASE_URL + f"api/lattice/graph?project_id={PROJECT}", timeout=300,
    ) as r:
        return json.loads(r.read())


def _graph_identity(g: dict):
    """Node and edge ids, not counts.

    /graph exposes no dep_hash, and counts are too weak a fingerprint:
    a recompute that swaps obs_near_52w_low_002 for _003 leaves every
    count identical while changing what the page draws, which is
    exactly the mismatch that read as "phantom edge in DOM".
    """
    return (
        frozenset(n["id"] for n in g.get("nodes") or []),
        frozenset((e["source"], e["target"]) for e in g.get("edges") or []),
    )


def _stable_graph(attempts: int = 3):
    """A graph snapshot two consecutive fetches agree on, or None."""
    prev = _fetch_graph()
    for _ in range(attempts):
        cur = _fetch_graph()
        if _graph_identity(prev) == _graph_identity(cur):
            return cur
        prev = cur
    return None


@pytest.fixture(scope="module")
def graph_initial():
    if not _backend_up():
        pytest.skip(f"backend not reachable at {BASE_URL}")
    return _fetch_graph()


@pytest.fixture
def graph(page):
    """The graph payload **the page itself received**.

    Comparing the DOM against a separately-fetched graph is a race no
    amount of bracketing closes: the module-scoped version was read once
    at module start, a per-test re-read still lands at a different
    instant than the SPA's own fetch, and even requiring two consecutive
    identical reads is too weak — a recompute that swaps
    obs_near_52w_low_002 for _003 leaves every count identical while
    changing what gets drawn. Each variant surfaced the same way: a
    "phantom edge in DOM" that was simply an edge from a newer graph.

    So take the answer off the wire. This returns a dict seeded from a
    stable fetch (for tests that never enter trace mode) which
    _open_trace then overwrites in place with the exact body the browser
    got, leaving the window at zero. The mutable-holder shape is what
    keeps all 16 tests' signatures untouched.
    """
    if not _backend_up():
        pytest.skip(f"backend not reachable at {BASE_URL}")
    seed = _stable_graph()
    if seed is None:
        pytest.skip(
            "the lattice graph changed on every consecutive read; "
            "re-run when the scheduler is quieter"
        )
    holder = dict(seed)
    page._graph_holder = holder
    return holder


@pytest.fixture(scope="module")
def browser(graph_initial):
    if not graph_initial.get("nodes"):
        pytest.skip("graph empty")
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


def _capture_graph(page):
    """Record the body of the SPA's own /api/lattice/graph fetch."""
    def _on_response(resp):
        if "/api/lattice/graph" not in resp.url:
            return
        try:
            page._captured_graph = resp.json()
        except Exception:
            pass
    page.on("response", _on_response)


@pytest.fixture
def page(browser) -> Page:
    ctx = browser.new_context(viewport={"width": 1600, "height": 1100})
    page = ctx.new_page()
    pin_project(page)
    _capture_graph(page)
    yield page
    ctx.close()


def _open_trace(page: Page):
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    goto_tab(page, "research")
    page.wait_for_selector('[data-testid="digest-view"]', timeout=30000)
    page.click('[data-testid="digest-mode-trace"]')
    # Wait for trace mode to resolve to one of its two outcomes, then decide.
    # Reading digest-body immediately after the click races the render.
    # Measured 24.3-27.7s for the graph on a warm dashboard, so 15s could not
    # be met even when healthy; and with an empty lattice the panel shows its
    # onboarding copy ("the lattice needs real data to distil") and
    # lattice-svg never mounts at all — no error, just nothing to draw.
    page.wait_for_function(
        """() => {
            if (document.querySelector('[data-testid="lattice-svg"]')) return true
            const b = document.querySelector('[data-testid="digest-body"]')
            return !!b && b.innerText.includes('needs real data')
        }""",
        timeout=60000,
    )
    if not page.query_selector('[data-testid="lattice-svg"]'):
        pytest.skip("lattice has no distilled data on this dashboard — seed it to run this test")

    page.wait_for_timeout(500)

    # Swap in the payload the browser actually rendered from, so the
    # assertions below compare the DOM against its own source rather
    # than against a second, later read of a moving lattice.
    captured = getattr(page, "_captured_graph", None)
    holder = getattr(page, "_graph_holder", None)
    if captured and holder is not None:
        holder.clear()
        holder.update(captured)


# ── DOM zero-ghost invariants ──────────────────────────

def test_every_graph_node_has_svg_element(page, graph):
    _open_trace(page)
    for n in graph["nodes"]:
        sel = f'[data-node-id="{n["id"]}"]'
        count = page.locator(sel).count()
        assert count == 1, f"node {n['id']} has {count} DOM elements (expected 1)"


def test_every_graph_edge_has_svg_element(page, graph):
    _open_trace(page)
    for e in graph["edges"]:
        sel = f'[data-edge-source="{e["source"]}"][data-edge-target="{e["target"]}"]'
        count = page.locator(sel).count()
        assert count == 1, f"edge {e['source']}→{e['target']} has {count} DOM elements"


def test_no_phantom_nodes_in_dom(page, graph):
    """Every <g data-node-id="..."> in the DOM must have a matching
    graph node. No extra elements allowed."""
    _open_trace(page)
    dom_ids = page.evaluate("""
        () => Array.from(document.querySelectorAll('[data-node-id]'))
            .map(el => el.getAttribute('data-node-id'))
    """)
    graph_ids = {n["id"] for n in graph["nodes"]}
    for did in dom_ids:
        assert did in graph_ids, f"phantom node in DOM: {did!r}"


def test_no_phantom_edges_in_dom(page, graph):
    _open_trace(page)
    dom_edges = page.evaluate("""
        () => Array.from(document.querySelectorAll('[data-edge-source]'))
            .map(el => [el.getAttribute('data-edge-source'),
                        el.getAttribute('data-edge-target')])
    """)
    graph_edges = {(e["source"], e["target"]) for e in graph["edges"]}
    for src, tgt in dom_edges:
        assert (src, tgt) in graph_edges, f"phantom edge in DOM: {src}→{tgt}"


# ── Layer / edge-kind counts match meta ────────────────

def test_dom_node_count_matches_graph_total(page, graph):
    _open_trace(page)
    count = page.locator('[data-node-id]').count()
    assert count == len(graph["nodes"])


def test_dom_edge_count_matches_graph_total(page, graph):
    _open_trace(page)
    count = page.locator('[data-edge-source]').count()
    assert count == len(graph["edges"])


def test_dom_nodes_per_layer_match_meta(page, graph):
    _open_trace(page)
    for layer, expected in graph["meta"]["layer_counts"].items():
        count = page.locator(f'[data-layer="{layer}"]').count()
        assert count == expected, f"{layer}: DOM has {count}, meta has {expected}"


# ── Provenance visual encoding ─────────────────────────

def test_llm_nodes_render_as_diamonds(page, graph):
    _open_trace(page)
    llm_kinds = {"llm", "llm+validator", "llm+mmr"}
    for n in graph["nodes"]:
        if n["provenance"]["computed_by"] not in llm_kinds:
            continue
        cls = page.locator(f'[data-node-id="{n["id"]}"]').get_attribute("class")
        assert cls and "node-shape-diamond" in cls, (
            f"{n['id']} with provenance {n['provenance']['computed_by']} "
            f"must render as diamond, got class={cls!r}"
        )


def test_deterministic_and_source_nodes_render_as_rects(page, graph):
    _open_trace(page)
    for n in graph["nodes"]:
        kind = n["provenance"]["computed_by"]
        if kind not in ("deterministic", "source"):
            continue
        cls = page.locator(f'[data-node-id="{n["id"]}"]').get_attribute("class")
        assert cls and "node-shape-rect" in cls, (
            f"{n['id']} with provenance {kind} must render as rect, got class={cls!r}"
        )


def test_llm_validator_nodes_have_validator_badge(page, graph):
    _open_trace(page)
    any_validator = False
    for n in graph["nodes"]:
        if n["provenance"]["computed_by"] != "llm+validator":
            continue
        any_validator = True
        badge = page.locator(f'[data-testid="node-{n["id"]}-badge-validator"]').count()
        assert badge == 1, f"{n['id']} (llm+validator) missing validator badge"
    if not any_validator:
        pytest.skip("no llm+validator nodes in current payload")


def test_llm_mmr_nodes_have_mmr_badge(page, graph):
    _open_trace(page)
    any_mmr = False
    for n in graph["nodes"]:
        if n["provenance"]["computed_by"] != "llm+mmr":
            continue
        any_mmr = True
        badge = page.locator(f'[data-testid="node-{n["id"]}-badge-mmr"]').count()
        assert badge == 1, f"{n['id']} (llm+mmr) missing mmr badge"
    if not any_mmr:
        pytest.skip("no llm+mmr nodes in current payload")


# ── Edge kind encoding ─────────────────────────────────

def test_edge_kind_class_matches_graph_kind(page, graph):
    _open_trace(page)
    for e in graph["edges"]:
        sel = f'[data-edge-source="{e["source"]}"][data-edge-target="{e["target"]}"]'
        cls = page.locator(sel).get_attribute("class")
        assert cls and f"edge-kind-{e['kind']}" in cls, (
            f"edge {e['source']}→{e['target']} expected edge-kind-{e['kind']}, got {cls!r}"
        )


# ── Interaction: click edge → panel shows exact computation ──

def test_click_membership_edge_shows_exact_computation_from_graph(page, graph):
    """Pick the first membership edge from /graph, click it in the
    DOM, assert the panel displays the same `final` (full precision),
    the same `severity_bonus`, the same `base`, and the same jaccard
    num/den as the graph payload. ZERO drift allowed between
    backend-provided computation and UI-rendered computation."""
    _open_trace(page)
    membership = [e for e in graph["edges"] if e["kind"] == "membership"]
    assert membership, "need at least one membership edge to test"
    e = membership[0]
    sel = f'[data-edge-source="{e["source"]}"][data-edge-target="{e["target"]}"]'
    # dispatch_event, not click(force=True). Edges are SVG paths that
    # overlap heavily near a shared endpoint, and force=True only skips
    # the actionability wait — the event is still delivered to whatever
    # sits topmost at that coordinate. Here it consistently landed on
    # obs_anomaly_near_52w_with_earnings_001 -> theme_near_highs instead
    # of the intended -> subtheme_event_risk, and the panel then showed
    # that edge's 1/2 against the intended edge's 1/3. The "zero drift"
    # this test guards was never actually violated; it was comparing two
    # different edges. dispatch_event goes straight to the element.
    page.locator(sel).dispatch_event("click")
    page.wait_for_selector('[data-testid="trace-edge-computation-membership"]',
                           state="attached", timeout=5000)
    d = e["computation"]["detail"]
    # Jaccard num/den text
    jaccard_text = page.locator('[data-testid="trace-edge-jaccard"]').inner_text()
    assert jaccard_text.strip() == f'{d["jaccard_num"]}/{d["jaccard_den"]}'
    # base = 4 decimal places
    base_text = page.locator('[data-testid="trace-edge-base"]').inner_text()
    assert base_text.strip() == f'{d["base"]:.4f}'
    # severity_bonus = 2 decimal places
    bonus_text = page.locator('[data-testid="trace-edge-severity-bonus"]').inner_text()
    assert bonus_text.strip() == f'{d["severity_bonus"]:.2f}'
    # final = 6 decimal places (full precision preserved)
    final_text = page.locator('[data-testid="trace-edge-final"]').inner_text()
    assert final_text.strip() == f'{d["final"]:.6f}'
    # edge weight (rounded display) matches the edge's weight
    weight_text = page.locator('[data-testid="trace-edge-weight"]').inner_text()
    assert weight_text.strip() == f'{e["weight"]:.3f}'


def test_click_l3_node_shows_provenance_llm_mmr(page, graph):
    _open_trace(page)
    l3 = [n for n in graph["nodes"] if n["layer"] == "L3"]
    if not l3:
        pytest.skip("no L3 nodes")
    n = l3[0]
    page.locator(f'[data-node-id="{n["id"]}"]').click(force=True)
    page.wait_for_selector('[data-testid="trace-node-detail"]',
                           state="attached", timeout=3000)
    prov_text = page.locator('[data-testid="trace-panel-provenance"]').inner_text().lower()
    assert "llm" in prov_text and "mmr" in prov_text, (
        f"expected llm+mmr provenance label, got: {prov_text!r}"
    )


def test_click_l1_node_shows_provenance_deterministic(page, graph):
    _open_trace(page)
    l1 = [n for n in graph["nodes"] if n["layer"] == "L1"]
    if not l1:
        pytest.skip("no L1 nodes")
    page.locator(f'[data-node-id="{l1[0]["id"]}"]').click(force=True)
    page.wait_for_selector('[data-testid="trace-node-detail"]',
                           state="attached", timeout=3000)
    prov_text = page.locator('[data-testid="trace-panel-provenance"]').inner_text().lower()
    assert "deterministic" in prov_text, prov_text


# ── Panel close ───────────────────────────────────────

def test_close_panel_returns_to_empty_state(page, graph):
    _open_trace(page)
    # Open something
    node = graph["nodes"][0]
    page.locator(f'[data-node-id="{node["id"]}"]').click(force=True)
    page.wait_for_selector('[data-testid="trace-panel"]', state="attached", timeout=3000)
    page.click('[data-testid="trace-panel-close"]')
    page.wait_for_selector('[data-testid="trace-panel-empty"]', state="attached", timeout=3000)
