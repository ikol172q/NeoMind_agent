"""Shared navigation helpers for the dashboard SPA tests.

Two changes in the SPA broke roughly a hundred web tests at once, and every
test file had open-coded the same two lines, so every file broke the same way.

1. ``wait_until="networkidle"`` never settles. The dashboard polls quotes, the
   scheduler and the live clock continuously, so the network is never idle and
   ``page.goto`` just times out. Load with ``domcontentloaded`` and then wait on
   a real element instead.

2. The top nav became grouped dropdowns (研究 / 账户 / 学习 / 系统). Only the
   active tab's button is in the DOM; every other tab button renders solely
   inside its opened group menu. So
   ``page.click('[data-testid="tab-research"]')`` waits forever on an element
   that will never appear until 研究 is opened first.

   The group buttons carry no data-testid — they are identified by their label
   text, which is what ``_GROUP_OF`` encodes.
"""

from __future__ import annotations

BASE_URL = "http://127.0.0.1:8001/"

# tab id -> the nav group that has to be opened before its button exists.
# Mirrors NAV_GROUPS / SYSTEM_ITEMS in web/src/App.tsx. Tabs absent from this
# map (currently only "strategies", the home tab) sit at the top level.
_GROUP_OF = {
    "research": "研究",
    "serenity": "研究",
    "keystone": "研究",
    "core": "账户",
    "trading": "账户",
    "learning": "学习",
    "principles": "学习",
    "audit": "系统",
    "data_lake": "系统",
    "settings": "系统",
}

DEFAULT_TIMEOUT = 8000


def open_dashboard(page, *, timeout: int = 20000):
    """Load the SPA and wait until the nav is actually rendered.

    Deliberately not networkidle — see the module docstring.
    """
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=timeout)
    page.wait_for_selector('[data-testid="top-nav"]', timeout=timeout)
    return page


def goto_tab(page, tab_id: str, *, timeout: int = DEFAULT_TIMEOUT):
    """Switch to a tab, opening its nav group first when it has one.

    Safe to call for the already-active tab: its button is top-level in that
    case and the group open is skipped.
    """
    selector = f'[data-testid="tab-{tab_id}"]'

    # Already on screen (active tab, or a group left open by a previous call).
    if page.query_selector(selector):
        page.click(selector)
        return page

    group = _GROUP_OF.get(tab_id)
    if group:
        # Located by button role rather than by position: 研究/账户/学习 live
        # inside [data-testid="top-nav"], but 系统 is rendered in its own
        # right-aligned div outside it, so a top-nav-scoped selector silently
        # misses audit / data_lake / settings.
        page.get_by_role("button", name=group).first.click(timeout=timeout)
        page.wait_for_selector(selector, timeout=timeout)

    page.wait_for_selector(selector, timeout=timeout)
    page.click(selector)
    return page


def goto_legacy(page, *, timeout: int = DEFAULT_TIMEOUT):
    """Open the legacy dashboard (the old widget grid).

    V11 moved Watchlist / Quote / Heatmap / Earnings / RS / Correlation /
    Sectors and friends off the Research tab into LegacyTab, on the grounds
    that they duplicated TradingView/Yahoo/Koyfin without adding value. The
    tab is deliberately absent from the main nav — App.tsx says so — and is
    reached through Settings, so widget tests have to go the same way.
    """
    goto_tab(page, "settings", timeout=timeout)
    page.wait_for_selector('[data-testid="open-legacy-dashboard"]', timeout=timeout)
    page.click('[data-testid="open-legacy-dashboard"]')
    return page


def pin_project(page, project: str | None = None):
    """Point the SPA at the fixture project before it boots.

    App.tsx resolves its project as
    ``localStorage.getItem('neomind.project') ?? 'fin-core'``, so seeding
    a different project over REST is not enough on its own: the browser
    keeps reading fin-core and the test asserts against data it never
    wrote. Every browser-driven test needs this alongside the REST-side
    PROJECT constant, or the two halves disagree.

    add_init_script runs before page scripts on every navigation, so it
    has to be installed on the fresh page, not after the first goto.
    """
    from tests.fixture_project import PROJECT
    pid = project or PROJECT
    page.add_init_script(
        f"try {{ localStorage.setItem('neomind.project', {pid!r}) }} catch (e) {{}}"
    )
    return page
