"""Phase 5 live conversation smoke — drives a real iTerm2 window, spawns
fin-core fleet, dispatches a REAL short task to each of the 4 sub-agents
(truly parallel via Option E contextvar + background asyncio loop), waits
for real DeepSeek responses, captures each focused view showing the
actual agent output, and **leaves the iTerm2 window OPEN** so the user
can inspect it afterward.

Unlike phase5_fleet_live_smoke.py this runner:
  - Dispatches 4 distinct tasks (one per agent, 4 different personas/roles)
  - Uses the REAL _default_llm_call (no mock)
  - Waits for task_completed events via /fleet status polling
  - Does NOT close the iTerm2 window at end — user can click around
  - Prints a "go look at window X" pointer when done

Approximate cost: 4 × (~200 input + ~100 output) DeepSeek tokens ≈ $0.005.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tests.integration.cli_tester_iterm2 import ITerm2CliTester, ITerm2Config  # noqa


CTRL_RIGHT = "\x1b[1;5C"
CTRL_LEFT = "\x1b[1;5D"


DUMP_DIR = REPO_ROOT / "tests" / "qa_archive" / "results" / "2026-04-12_phase5_live_conversation"


# Tiny tasks — one per sub-agent. Designed so each output is distinct
# and obviously tied to that agent's persona, so if the alt-screen
# isolation is broken it's immediately visually obvious.
AGENT_TASKS = [
    (
        "fin-rt",
        "In exactly one sentence, give a buy/hold/sell view on MSFT and "
        "prefix your answer with 'FIN-RT:'.",
    ),
    (
        "fin-rsrch",
        "In exactly one sentence, state a research hypothesis about NVDA "
        "earnings and prefix your answer with 'FIN-RSRCH:'.",
    ),
    (
        "dev-1",
        "In exactly one sentence, describe how a Python decorator works and "
        "prefix your answer with 'DEV-1:'.",
    ),
    (
        "dev-2",
        "In exactly one sentence, describe the difference between a list "
        "and a tuple in Python and prefix your answer with 'DEV-2:'.",
    ),
]


def _save_dump(label: str, content: str) -> Path:
    DUMP_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%H%M%S")
    path = DUMP_DIR / f"{ts}_{label}.txt"
    path.write_text(content, encoding="utf-8")
    return path


async def _wait_ticks(tester: ITerm2CliTester, seconds: float) -> str:
    end = time.monotonic() + seconds
    last = ""
    while time.monotonic() < end:
        last = await tester.capture(lines=80)
        await asyncio.sleep(0.3)
    return last


async def run() -> int:
    cfg = ITerm2Config(
        launch_cmd=".venv/bin/python main.py --mode fin",
        cols=140,
        rows=60,
        boot_timeout_sec=30.0,
    )
    venv_python = REPO_ROOT / ".venv" / "bin" / "python"
    if not venv_python.exists():
        cfg.launch_cmd = "python3 main.py --mode fin"

    tester = ITerm2CliTester(cfg)

    # Manually enter the context but NOT exit — we want the window to
    # stay open after the script finishes so the user can inspect it.
    await tester.__aenter__()
    print(f"[smoke] iTerm2 connected, launching: {cfg.launch_cmd}")
    await tester.start_neomind()

    try:
        await tester.wait_for_prompt(timeout=cfg.boot_timeout_sec)
        print("[smoke] CLI prompt detected")
    except Exception as exc:
        screen = await tester.capture(lines=200)
        _save_dump("00_boot_failure", screen)
        print(f"[smoke] ABORT: boot failed — {exc}")
        return 2

    # ── Turn 1: /fleet start fin-core ─────────────────────────
    print("[smoke] /fleet start fin-core")
    await tester.send("/fleet start fin-core")
    await _wait_ticks(tester, 4.0)
    _save_dump("01_fleet_start", await tester.capture(lines=80))

    # ── Turn 2-5: dispatch 4 tasks in sequence (all run in parallel) ──
    print("[smoke] dispatching 4 tasks (truly parallel via bg loop)...")
    for name, task in AGENT_TASKS:
        cmd = f"/fleet submit --to {name} {task}"
        print(f"[smoke]   → {name}")
        await tester.send(cmd)
        await asyncio.sleep(0.6)  # short gap so the CLI has time to print confirmation
    _save_dump("02_all_dispatched", await tester.capture(lines=80))

    # ── Wait for all 4 to complete via /fleet status polling ─────
    print("[smoke] waiting for all 4 completions (real DeepSeek)...")
    deadline = time.monotonic() + 60.0
    last_status = ""
    while time.monotonic() < deadline:
        await tester.send("/fleet status")
        await asyncio.sleep(1.5)
        last_status = await tester.capture(lines=80)
        if "completed=4" in last_status or "completed=5" in last_status:
            print("[smoke]   all 4 completed ✓")
            break
    else:
        print("[smoke]   WARN: timed out waiting for completions, continuing")
    _save_dump("03_all_completed_status", last_status)

    # ── Focus each agent in turn, capture the alt-screen view ─────
    print("[smoke] capturing each agent's isolated view...")
    for name, _ in AGENT_TASKS:
        print(f"[smoke]   focus → {name}")
        await tester.send(f"/fleet focus {name}")
        await _wait_ticks(tester, 2.0)
        screen = await tester.capture(lines=80)
        _save_dump(f"04_focus_{name}", screen)

    # ── Return to leader, capture final state ─────────────────
    print("[smoke] returning to leader view...")
    await tester.send("/fleet focus leader")
    await _wait_ticks(tester, 2.0)
    final = await tester.capture(lines=80)
    _save_dump("05_leader_final", final)

    print()
    print("=" * 64)
    print("Phase 5 live conversation smoke — DONE")
    print("=" * 64)
    print(f"Dumps: {DUMP_DIR}")
    print()
    print("iTerm2 window LEFT OPEN for user inspection.")
    print("You can now click into it, press Ctrl+← / Ctrl+→ to cycle")
    print("through each agent's alt-screen view, /fleet status to see")
    print("task counts, /fleet stop when done.")
    print()
    print("Close the window when finished with Cmd+W.")
    print()

    # IMPORTANT: do NOT call tester.__aexit__ or tester.close() — we
    # intentionally leave the iTerm2 window open for the user.
    return 0


if __name__ == "__main__":
    try:
        rc = asyncio.run(run())
    except KeyboardInterrupt:
        rc = 130
    except Exception as e:
        import traceback
        print(f"[smoke] runner crashed: {type(e).__name__}: {e}")
        traceback.print_exc()
        rc = 3
    sys.exit(rc)
