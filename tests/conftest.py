"""Shared test configuration for all test modules."""

import asyncio
import os

import pytest

# Disable vault side-effects during tests (vault writes to ~/neomind-vault,
# which leaks state across test runs and breaks conversation_history assertions).
# Vault-specific tests in test_vault_*.py use their own tmp_path fixtures.
os.environ["NEOMIND_DISABLE_VAULT"] = "1"


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
