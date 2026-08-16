"""Shared test configuration for all test modules."""

import asyncio
import os

import pytest

# Disable vault side-effects during tests (vault writes to ~/neomind-vault,
# which leaks state across test runs and breaks conversation_history assertions).
# Vault-specific tests in test_vault_*.py use their own tmp_path fixtures.
os.environ["NEOMIND_DISABLE_VAULT"] = "1"

# Import the agent package before any test module runs, so every `agent.<sub>`
# submodule is bound as an attribute of the parent package.
#
# Why: mock.patch("agent.coding.tool_parser.ToolCallParser") resolves the target
# with getattr(agent, "coding"), falling back to __import__("agent.coding") and
# retrying. When some earlier test has already put "agent.coding" in sys.modules
# without the parent attribute being set, that __import__ is a no-op and the
# retry fails too:
#
#   AttributeError: module 'agent' has no attribute 'coding'
#
# The suite hit that in 36+ tests across test_agentic_loop_canonical.py,
# test_formatter.py and test_task_manager.py — all of which pass in isolation
# and only fail after tests/llm/test_conversation_scenarios.py has run. A
# single early package import makes the order irrelevant. Verified as the
# minimal difference: a plugin doing nothing but `import agent` at configure
# time was enough to turn those failures green.
import agent  # noqa: E402,F401  (import for its binding side effect)
import agent.coding  # noqa: E402,F401
import agent.command_executor  # noqa: E402,F401
import agent.formatter  # noqa: E402,F401
import agent.help_system  # noqa: E402,F401
import agent.task_manager  # noqa: E402,F401
import agent.tools  # noqa: E402,F401


@pytest.fixture(autouse=True)
def _ensure_event_loop():
    """Guarantee a usable asyncio event loop exists for every test.

    Why this is needed: test_fleet_fin_end_to_end.py (and any other
    test that calls ``asyncio.run()``) leaves the event loop policy in
    a state where ``get_event_loop()`` raises ``RuntimeError: There is
    no current event loop in thread 'MainThread'`` — because Python
    3.9's ``asyncio.run()`` sets ``_set_called = True`` on the policy,
    which permanently disables the auto-create fallback in
    ``get_event_loop()``.

    Subsequent tests that instantiate objects requiring a loop at
    construction time (e.g. ``asyncio.Lock()`` inside
    ``FleetBackend.__init__``, or ``TestClient`` for async FastAPI
    routes) then fail at fixture setup with a cryptic RuntimeError
    even though they have nothing to do with async.

    Fix: before each test, check if there's a current loop. If not
    (or if it's closed), create and set a fresh one. After the test,
    leave it in place — the next test or ``asyncio.run()`` call can
    replace it if needed.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    yield


@pytest.fixture(autouse=True)
def _stop_leaked_heartbeats():
    """Join heartbeat threads a test left running.

    Every evolution scheduler lazily builds a ``HeartbeatWriter``; before this
    fixture nothing ever called ``stop()``, so each such test parked one more
    daemon thread for the rest of the run (115 were observed in one suite run,
    all of them re-``mkdir``-ing and rewriting the same file on a 30s timer —
    the likely source of the "Too many open files" seen during teardown).

    Imported lazily and guarded: a collection-time import failure here would
    take down every test in the suite, which is exactly the blast radius this
    fixture exists to reduce.
    """
    yield
    try:
        from agent.evolution.health_monitor import stop_all_heartbeats
    except Exception:
        return
    stop_all_heartbeats()


# ── shared live-dashboard state ────────────────────────

_DASH = "http://127.0.0.1:8001/"
from tests.fixture_project import PROJECT as _DASH_PROJECT


def _watchlist_entries():
    """Current watchlist, or None when the dashboard isn't answering."""
    import json
    import urllib.request
    try:
        with urllib.request.urlopen(
            _DASH + f"api/watchlist?project_id={_DASH_PROJECT}", timeout=5
        ) as r:
            return json.loads(r.read()).get("entries", []) or []
    except Exception:
        return None


@pytest.fixture(scope="module", autouse=True)
def _restore_dashboard_watchlist():
    """Put back watchlist entries a module wiped off the shared dashboard.

    Thirteen web/lattice test modules empty the whole watchlist in their
    setup — legitimately, since they test empty states or want a known
    starting point — but none of them put it back. Whichever module ran
    next then saw a dashboard with nothing to distil: the lattice fell to
    its "needs real data" copy, so the 16 lattice_viz tests skipped as
    undistilled and a rotating handful of others failed outright. Which
    ones got hit depended only on collection order, which is why the
    full-run failures reshuffled every run while each file passed alone.

    Restoring is additive on purpose — it re-POSTs entries that went
    missing and never deletes. A cleanup fixture that removes things is
    one more polluter, and the whole point here is to stop being one.

    No-ops when the dashboard isn't running, so the non-web suite is
    unaffected beyond one cheap request per module.
    """
    before = _watchlist_entries()
    yield
    if before is None:
        return
    after = _watchlist_entries()
    if after is None:
        return
    have = {(e.get("symbol"), e.get("market")) for e in after}
    import json
    import urllib.request
    for e in before:
        key = (e.get("symbol"), e.get("market"))
        if key in have:
            continue
        try:
            req = urllib.request.Request(
                _DASH + f"api/watchlist?project_id={_DASH_PROJECT}",
                data=json.dumps({
                    "symbol": e.get("symbol"),
                    "market": e.get("market", "US"),
                    "note": e.get("note", "") or "",
                }).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5).read()
        except Exception:
            pass


# Baseline the fixture project holds at the start of a session. Small on
# purpose: enough for the widgets to have something to draw and for the
# lattice to distil, not so much that a test has to fight it. Tests that
# need an empty watchlist clear it themselves; tests that need positions
# place their own orders.
_FIXTURE_BASELINE = (("AAPL", "US"), ("MSFT", "US"), ("NVDA", "US"))


@pytest.fixture(scope="session", autouse=True)
def _seed_fixture_project():
    """Give the fixture project a known starting point.

    The per-module restore fixture below only puts back what was there
    when that module started, so with nothing establishing a baseline the
    project drifts to whatever the last module left — which is the
    determinism this whole fixture-project move was for.

    Refuses to touch fin-core. Pointing NEOMIND_TEST_PROJECT at a real
    project is a deliberate act, but seeding one is not something to do
    by accident.
    """
    if _DASH_PROJECT == "fin-core":
        yield
        return
    if _watchlist_entries() is None:      # dashboard not running
        yield
        return
    import json
    import urllib.request
    have = {(e.get("symbol"), e.get("market")) for e in (_watchlist_entries() or [])}
    for sym, market in _FIXTURE_BASELINE:
        if (sym, market) in have:
            continue
        try:
            urllib.request.urlopen(urllib.request.Request(
                _DASH + f"api/watchlist?project_id={_DASH_PROJECT}",
                data=json.dumps({"symbol": sym, "market": market, "note": ""}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            ), timeout=10).read()
        except Exception:
            pass
    yield


# ── test tiers ────────────────────────────────────────────────────────────
#
# 6000+ tests run in about six minutes, but that is not evenly spread: the 25
# slowest account for roughly 240 of the 360 seconds, and they fall into three
# groups that are slow for the same reason each time — they leave the process.
#
#   llm     a real provider call
#   proc    spawns a subprocess, usually a whole python
#   slow    waits on a real timeout on purpose
#
# Everything else — the other ~6000 — finishes in about two and a half
# minutes, which is a fine inner loop. So the default run excludes those three
# and says so out loud. Silently not running tests is how a suite starts
# lying; the summary line at the end of every run names what was held back and
# how to get it.
#
#   default            fast tier only
#   NEOMIND_TESTS=all  everything
#   -m llm             just that tier
#
# Tiers are assigned by path and name rather than by decorating each test, so
# a new file under tests/llm/ is tiered the moment it exists and nobody has to
# remember.

_TIER_PATHS = {
    "llm": ("tests/llm/", "test_integration_live", "test_simulation_llm"),
    "proc": ("test_headless_subprocess", "cross_mode_boot_smoke", "test_fleet_"),
    "slow": ("repl_fidelity_check", "repl_session_path_check", "repl_phase4_gate"),
}

#: Individual slow tests that live in otherwise fast files. Measured, not
#: guessed: each of these spends its time inside a real timeout.
_SLOW_TESTS = (
    "test_persistent_bash_timeout",
    "test_bash_timeout",
    "test_no_matches",
    "test_new_command_handlers_smoke",
)


def _tier_for(item) -> str:
    path = str(getattr(item, "fspath", "")).replace("\\", "/")
    for tier, needles in _TIER_PATHS.items():
        if any(n in path for n in needles):
            return tier
    if any(name in item.name for name in _SLOW_TESTS):
        return "slow"
    return "fast"


def pytest_collection_modifyitems(config, items):
    import os as _os

    import pytest as _pytest

    run_all = _os.environ.get("NEOMIND_TESTS", "").strip().lower() in ("all", "1", "true")
    selected_marker = (config.getoption("-m") or "").strip()

    held = {"llm": 0, "proc": 0, "slow": 0}
    for item in items:
        tier = _tier_for(item)
        if tier == "fast":
            continue
        item.add_marker(getattr(_pytest.mark, tier))
        # An explicit -m selection means the caller asked for a tier by name;
        # do not second-guess it.
        if run_all or selected_marker:
            continue
        held[tier] += 1
        item.add_marker(
            _pytest.mark.skip(
                reason=f"{tier} tier held back; NEOMIND_TESTS=all to include"
            )
        )
    config._neomind_held = held


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    held = getattr(config, "_neomind_held", None)
    if not held or not any(held.values()):
        return
    total = sum(held.values())
    parts = ", ".join(f"{n} {t}" for t, n in held.items() if n)
    terminalreporter.write_sep(
        "-", f"{total} tests held back ({parts}) — NEOMIND_TESTS=all to run them"
    )
