"""Phase 6B task 1 — the loop a fleet runs on belongs to the fleet.

The behaviour that matters is what the class-level loop in the interface could
not do: two fleets that do not share a loop, and a driver that can be shut down
without taking the process with it.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from fleet.driver import FleetDriver, FleetDriverError


class TestSubmit:

    def test_a_coroutine_runs_and_returns_its_value(self):
        driver = FleetDriver()
        try:
            async def work():
                await asyncio.sleep(0)
                return 42

            assert driver.submit(work()) == 42
        finally:
            driver.shutdown()

    def test_exceptions_propagate_unchanged(self):
        """A frontend should see the fleet's own error, not a wrapper that
        hides which call failed."""
        driver = FleetDriver()
        try:
            async def boom():
                raise ValueError("the fleet said no")

            with pytest.raises(ValueError, match="the fleet said no"):
                driver.submit(boom())
        finally:
            driver.shutdown()

    def test_the_loop_persists_between_calls(self):
        """The reason it is a persistent loop rather than one per call: work
        started by an earlier call has to keep progressing between them."""
        driver = FleetDriver()
        try:
            progressed = []

            async def background():
                for _ in range(50):
                    await asyncio.sleep(0.005)
                    progressed.append(1)

            driver.submit_nowait(background())

            async def noop():
                return None

            driver.submit(noop())
            first = len(progressed)
            time.sleep(0.1)
            driver.submit(noop())
            assert len(progressed) > first, (
                "background work stalled between calls — the loop is not running"
            )
        finally:
            driver.shutdown()

    def test_a_task_reference_survives_across_calls(self):
        """The other half of the same problem: with a per-call loop, a future
        created in one call fails in the next with 'future belongs to a
        different loop'."""
        driver = FleetDriver()
        try:
            async def make_event():
                return asyncio.Event()

            event = driver.submit(make_event())

            async def wait_briefly():
                try:
                    await asyncio.wait_for(event.wait(), timeout=0.05)
                except asyncio.TimeoutError:
                    return "timed out on the same loop"

            assert driver.submit(wait_briefly()) == "timed out on the same loop"
        finally:
            driver.shutdown()

    def test_an_operation_that_hangs_is_cancelled_not_waited_on_forever(self):
        """A frontend blocked forever on a fleet call looks like a hung
        terminal, with nothing on screen to say why."""
        driver = FleetDriver()
        try:
            async def forever():
                await asyncio.sleep(60)

            with pytest.raises(FleetDriverError, match="exceeded"):
                driver.submit(forever(), timeout=0.2)
        finally:
            driver.shutdown()


class TestPerFleetIsolation:
    """The class-level loop in `NeoMindInterface` was shared by every
    interface in the process — the same shape as the process-wide config
    Phase 6A moved into the session."""

    def test_two_drivers_do_not_share_a_loop(self):
        a, b = FleetDriver(), FleetDriver()
        try:
            async def loop_id():
                return id(asyncio.get_event_loop())

            assert a.submit(loop_id()) != b.submit(loop_id())
        finally:
            a.shutdown()
            b.shutdown()

    def test_shutting_one_down_leaves_the_other_working(self):
        a, b = FleetDriver(), FleetDriver()
        try:
            async def ping():
                return "ok"

            a.submit(ping())
            b.submit(ping())
            a.shutdown()
            assert b.submit(ping()) == "ok"
        finally:
            b.shutdown()


class TestLifecycle:

    def test_the_loop_starts_lazily(self):
        """Constructing a driver must not cost a thread; a frontend builds one
        per session whether or not a fleet is ever started."""
        before = threading.active_count()
        driver = FleetDriver()
        assert threading.active_count() == before
        assert driver.running is False
        driver.shutdown()

    def test_the_thread_is_a_daemon(self):
        """A non-daemon thread would keep the interpreter alive after the user
        quits the REPL."""
        driver = FleetDriver()
        try:
            async def noop():
                return None

            driver.submit(noop())
            names = [t.name for t in threading.enumerate() if t.daemon]
            assert any("fleet" in n for n in names)
        finally:
            driver.shutdown()

    def test_shutdown_is_idempotent(self):
        driver = FleetDriver()

        async def noop():
            return None

        driver.submit(noop())
        driver.shutdown()
        driver.shutdown()
        assert driver.running is False

    def test_a_driver_restarts_after_shutdown(self):
        """A TUI opening and closing a fleet pane should not need a new
        object each time."""
        driver = FleetDriver()
        try:
            async def value():
                return 7

            assert driver.submit(value()) == 7
            driver.shutdown()
            assert driver.submit(value()) == 7
        finally:
            driver.shutdown()

    def test_shutdown_before_first_use_is_harmless(self):
        FleetDriver().shutdown()


class TestBoundary:

    def test_the_driver_imports_no_frontend(self):
        import ast
        import pathlib

        source = (
            pathlib.Path(__file__).resolve().parents[1] / "fleet" / "driver.py"
        ).read_text(encoding="utf-8")
        bad = []
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] in {"cli", "rich", "prompt_toolkit"}:
                    bad.append(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in {"cli", "rich", "prompt_toolkit"}:
                        bad.append(alias.name)
        assert bad == []
