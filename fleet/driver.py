"""Own the loop a fleet runs on, so a frontend does not have to.

Phase 6B task 1. `NeoMindInterface` carried this: a class-level asyncio loop
and a daemon thread, lazily built on the first `/fleet start` and kept alive
until the interpreter exits. Two problems with it living there.

The first is duplication. A fleet is driven from a synchronous REPL, so
something has to hold a persistent loop — `get_event_loop().run_until_complete()`
only turns the loop during each call, which freezes workers between user inputs
and makes cross-call task references fail with "future belongs to a different
loop". Any second frontend needs the same machinery, and would have to rebuild
it.

The second is that the state was on the *class*. Every interface in a process
shared one loop and one thread, which is the same shape as the process-wide
config that Phase 6A moved into the session: invisible with one session, and
with two, the second silently inherits whatever the first set up.

So the loop belongs to a driver, one per fleet, and the frontend calls ordinary
synchronous methods. The driver imports no frontend and draws nothing.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Awaitable, Callable, Optional, TypeVar

T = TypeVar("T")

#: How long to wait for the background loop to come up before giving up.
#: Failing loudly beats returning a driver whose `submit` would block forever.
LOOP_START_TIMEOUT = 5.0

#: Default ceiling on a single submitted operation. Start, stop, submit and
#: status all complete in milliseconds; anything that does not has gone wrong,
#: and a frontend blocked forever on it looks like a hung terminal.
DEFAULT_CALL_TIMEOUT = 120.0


class FleetDriverError(RuntimeError):
    """The loop could not be started, or an operation outlived its timeout."""


class FleetDriver:
    """A private asyncio loop on a daemon thread, driven synchronously.

    `submit()` is the whole interface: hand it a coroutine, get its result. The
    fleet's own workers keep running on the same loop between calls, which is
    the reason the loop is persistent rather than per-call.
    """

    def __init__(self, *, name: str = "neomind-fleet-loop") -> None:
        self._name = name
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    # ── lifecycle ─────────────────────────────────────────────────────────

    @property
    def running(self) -> bool:
        return self._loop is not None and not self._loop.is_closed()

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        """Start the loop on first use. Idempotent and thread-safe."""
        with self._lock:
            if self.running:
                return self._loop  # type: ignore[return-value]

            ready = threading.Event()
            box: dict = {}

            def _run() -> None:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                box["loop"] = loop
                ready.set()
                try:
                    loop.run_forever()
                finally:
                    # Cancel what is left rather than closing under it: a
                    # worker mid-await would otherwise raise into a closed
                    # loop and the traceback would name the loop, not the
                    # worker that was actually interrupted.
                    try:
                        pending = asyncio.all_tasks(loop)
                        for task in pending:
                            task.cancel()
                        if pending:
                            loop.run_until_complete(
                                asyncio.gather(*pending, return_exceptions=True)
                            )
                    except Exception:
                        pass
                    loop.close()

            thread = threading.Thread(target=_run, name=self._name, daemon=True)
            thread.start()
            if not ready.wait(timeout=LOOP_START_TIMEOUT):
                raise FleetDriverError(
                    f"fleet background loop did not start within {LOOP_START_TIMEOUT}s"
                )
            self._loop = box.get("loop")
            self._thread = thread
            if self._loop is None:
                raise FleetDriverError("fleet background loop failed to start")
            return self._loop

    def shutdown(self, timeout: float = 5.0) -> None:
        """Stop the loop and join the thread.

        Not called on the normal REPL path — the thread is a daemon and the
        interpreter exiting is enough — but a frontend that creates and
        discards drivers (a TUI opening and closing a fleet pane) needs a way
        to not leak one per open.
        """
        with self._lock:
            loop, thread = self._loop, self._thread
            self._loop = self._thread = None
        if loop is None:
            return
        try:
            loop.call_soon_threadsafe(loop.stop)
        except RuntimeError:
            return
        if thread is not None:
            thread.join(timeout=timeout)

    # ── driving ───────────────────────────────────────────────────────────

    def submit(
        self, coro: Awaitable[T], *, timeout: Optional[float] = DEFAULT_CALL_TIMEOUT
    ) -> T:
        """Run `coro` on the fleet loop and return its result.

        Blocks the calling thread. Exceptions propagate unchanged, so a
        frontend sees the fleet's own error rather than a wrapper.
        """
        import concurrent.futures

        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        try:
            return future.result(timeout=timeout)
        # `concurrent.futures.Future.result` raises its *own* TimeoutError,
        # which is a distinct class from `asyncio.TimeoutError` on Python 3.9.
        # Catching only the asyncio one let the timeout escape as a bare
        # TimeoutError with no indication that a fleet call was involved.
        except (concurrent.futures.TimeoutError, asyncio.TimeoutError) as exc:
            future.cancel()
            raise FleetDriverError(
                f"fleet operation exceeded {timeout}s and was cancelled"
            ) from exc

    def submit_nowait(self, coro: Awaitable[Any]) -> "Any":
        """Schedule `coro` without waiting. Returns the concurrent Future.

        For work a frontend starts and then renders progress for, rather than
        blocking on — which is what an event-driven TUI will want.
        """
        return asyncio.run_coroutine_threadsafe(coro, self._ensure_loop())
