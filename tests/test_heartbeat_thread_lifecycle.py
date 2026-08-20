"""Regression tests for HeartbeatWriter thread lifecycle.

Origin: a full-suite run left 115 threads named "heartbeat" alive. Every
evolution scheduler lazily builds a HeartbeatWriter, `stop()` only flipped a
flag (never joined, and the loop was parked in `time.sleep(interval)` so it
could not observe the flag for up to a full interval), and no caller invoked
`stop()` at all. See .claude/docs/troubleshooting/20260809-suite-never-finished.md.

`test_stop_recovers_thread_when_running_flag_already_cleared` covers a bug
introduced by the first attempt at the fix: an `if not self._running: return`
fast path in `stop()` looked harmless but stranded the thread whenever the flag
had been cleared by another path while the loop was still parked in `wait()`.
"""

import threading
import time

from agent.evolution.health_monitor import HeartbeatWriter, stop_all_heartbeats

# Long enough that a fix relying on the interval elapsing cannot pass by
# accident — the loop must be woken by the stop event, not by the timer.
INTERVAL = 30
SETTLE = 0.3


def _heartbeat_threads():
    return [t for t in threading.enumerate() if t.name == "heartbeat"]


def test_start_then_stop_leaves_no_thread():
    writer = HeartbeatWriter(interval=INTERVAL)
    writer.start()
    time.sleep(SETTLE)
    assert len(_heartbeat_threads()) == 1

    writer.stop()
    time.sleep(SETTLE)
    assert _heartbeat_threads() == []


def test_stop_returns_without_waiting_out_the_interval():
    writer = HeartbeatWriter(interval=INTERVAL)
    writer.start()
    time.sleep(SETTLE)

    started = time.time()
    writer.stop()
    elapsed = time.time() - started

    # The old implementation would have kept the thread parked for INTERVAL
    # seconds; a correct one wakes it through the stop event immediately.
    assert elapsed < 2.0, f"stop() took {elapsed:.1f}s — the loop was not woken"


def test_stop_recovers_thread_when_running_flag_already_cleared():
    """stop() must key off the thread, not the _running flag."""
    writer = HeartbeatWriter(interval=INTERVAL)
    writer.start()
    time.sleep(SETTLE)

    # Exactly what the original stop() did, and what any other code path that
    # clears the flag would leave behind: the thread is still parked in wait().
    writer._running = False
    time.sleep(SETTLE)
    assert len(_heartbeat_threads()) == 1, "precondition: thread still parked"

    writer.stop()
    time.sleep(SETTLE)
    assert _heartbeat_threads() == [], "stop() skipped a live thread"


def test_stop_is_idempotent_and_writer_restartable():
    writer = HeartbeatWriter(interval=INTERVAL)
    writer.start()
    time.sleep(SETTLE)

    writer.stop()
    writer.stop()  # must not raise
    time.sleep(SETTLE)
    assert _heartbeat_threads() == []

    writer.start()
    time.sleep(SETTLE)
    assert len(_heartbeat_threads()) == 1, "writer could not be restarted"

    writer.stop()
    time.sleep(SETTLE)
    assert _heartbeat_threads() == []


def test_stop_all_heartbeats_collects_writers_it_did_not_create():
    writers = [HeartbeatWriter(interval=INTERVAL) for _ in range(20)]
    for writer in writers:
        writer.start()
    time.sleep(SETTLE)
    assert len(_heartbeat_threads()) == 20

    stopped = stop_all_heartbeats()
    time.sleep(SETTLE)

    assert stopped == 20
    assert _heartbeat_threads() == []


def test_is_running_reports_the_thread_not_the_flag():
    writer = HeartbeatWriter(interval=INTERVAL)
    assert writer.is_running() is False

    writer.start()
    time.sleep(SETTLE)
    assert writer.is_running() is True

    writer._running = False
    time.sleep(SETTLE)
    assert writer.is_running() is True, "a parked thread is still a live thread"

    writer.stop()
    time.sleep(SETTLE)
    assert writer.is_running() is False
