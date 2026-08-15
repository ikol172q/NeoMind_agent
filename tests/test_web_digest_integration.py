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

from tests.web_nav import goto_tab

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
    goto_tab(page, "research")
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


def _lattice_rows_mentioning(symbol: str) -> bool:
    """True when the lattice payload DigestView renders has a row that
    findFocusTarget(symbol) could match, mirroring its observation ->
    theme -> call precedence.

    Hits /api/lattice/calls, which is what the SPA actually fetches —
    there is no /api/lattice/digest endpoint, and asking for one returns
    404, which a try/except turns into a permanent false skip.
    """
    import json
    import urllib.request
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:8001/api/lattice/calls?project_id=fin-core",
            # 45s, not 10s: this endpoint recomputes and has been
            # measured timing out past 10s, and a timeout here lands in
            # the except below as "no rows" — a false skip rather than a
            # loud failure.
            timeout=45
        ) as r:
            d = json.loads(r.read().decode())
    except Exception:
        return False
    sym = symbol.upper()
    for o in d.get("observations") or []:
        tags = o.get("tags") or []
        if f"symbol:{sym}" in tags or f"position:{sym}" in tags:
            return True
        if sym in (o.get("text") or "").upper():
            return True
    for t in d.get("themes") or []:
        if sym in (t.get("narrative") or "").upper():
            return True
    for c in d.get("calls") or []:
        if sym in (c.get("claim") or "").upper():
            return True
    return False


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

    # Wait for the lattice rows before clicking. The anomaly strip comes
    # from /api/anomalies and paints well before /api/lattice/calls
    # lands, and onFocusSymbol resolves findFocusTarget exactly once in a
    # 60ms timeout — over empty arrays it returns null, no highlight is
    # set, and nothing retries when the payload finally arrives. Clicking
    # a flag on a still-loading digest therefore does nothing at all,
    # which is worth knowing about but is not what this test is for.
    # Mode-independent "the payload landed" signal: obs- rows only exist
    # once flat mode is on, which is what the click itself turns on, so
    # waiting for them here would deadlock.
    page.wait_for_function(
        """() => {
            const b = document.querySelector('[data-testid="digest-body"]')
            return !!b && b.innerText.trim().length > 0
                   && !b.innerText.includes('reading the lattice')
        }""",
        timeout=60000,
    )
    page.click(f'[data-testid="{first_flag}"]')
    # Flat mode selected — this half is deterministic.
    page.wait_for_selector('[data-testid="digest-mode-flat"].bg-\\[var\\(--color-accent\\)\\]', timeout=30000)

    # The highlight half is data-dependent. DigestView's onFocusSymbol
    # runs findFocusTarget(sym, calls, themes, observations) and only
    # highlights `if (t)` — so when the lattice digest has no row
    # mentioning that symbol there is genuinely nothing to scroll to,
    # and no-highlight is correct behaviour, not a regression.
    # (Verified against the live DOM: clicking a flag flips to flat mode
    # correctly, and stays un-highlighted exactly when no lattice row
    # mentions that flag's symbol.)
    symbol = first_flag.rsplit("-", 1)[-1].upper()
    if not _lattice_rows_mentioning(symbol):
        pytest.skip(
            f"no lattice observation/theme/call mentions {symbol}, so the "
            f"anomaly click has no evidence row to scroll to; re-enable "
            f"once the lattice covers that symbol"
        )

    # The highlight is a one-shot that auto-clears after HIGHLIGHT_MS
    # (2500ms), so poll rather than wait on a steady-state selector.
    page.wait_for_function(
        "() => document.querySelectorAll('[data-highlighted=\"true\"]').length > 0",
        timeout=10000,
    )


# ── chat citation → Research focus ─────────────────────

def test_cite_click_in_chat_routes_to_research_with_focus(page: Page):
    """Send `/prep AAPL` (which reliably emits an [[AAPL]] cite in
    the reply), click the chip, and verify the Research tab becomes
    active + DigestView either highlights a row or settles into
    flat mode on the lattice."""
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    page.wait_for_selector('[data-testid="chat-input"]')
    page.wait_for_selector('[data-testid="chat-input"]', timeout=30000)
    # /prep is a workflow slash command that names the target symbol
    # in its reply — much more reliable cite emission than open prose.
    page.fill('[data-testid="chat-input"]', "/prep AAPL")
    page.click('[data-testid="chat-send"]')
    try:
        page.wait_for_selector('[data-testid="cite-symbol-AAPL"]', timeout=90000)
    except Exception:
        pytest.skip("agent didn't emit an [[AAPL]] cite in its /prep reply")
    page.click('[data-testid="cite-symbol-AAPL"]')
    # Research must activate. This used to assert the accent class on
    # [data-testid="tab-research"], which the nav-group refactor made
    # unsatisfiable: only a top-level tab keeps its own button, and a
    # grouped tab like research renders its button solely inside the
    # (closed) 研究 menu, so the selector resolves to null forever.
    # Verified against the live DOM — after goto_tab(page, "research")
    # the element is None while the tab is unmistakably active.
    #
    # Rendering DigestView is the load-bearing proof anyway, so wait on
    # that instead of on a class name that describes the nav's internals.
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
