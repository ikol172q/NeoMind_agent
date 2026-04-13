"""Phase 5 live smoke — drives a real iTerm2 window through the Phase 5
fleet CLI flow and captures forensic dumps per turn.

Run:
    python3 tests/integration/phase5_fleet_live_smoke.py

Requirements:
  - iTerm2 running
  - iTerm2 → Preferences → General → Magic → Enable Python API ticked
  - iterm2 python package installed (pip install iterm2)

Dumps land under tests/qa_archive/results/2026-04-12_phase5_live_smoke/.
The caller (Claude as manager) reads them after the run to judge UX.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

# Ensure repo root importable
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tests.integration.cli_tester_iterm2 import ITerm2CliTester, ITerm2Config  # noqa


# Control-key escape sequences — what iTerm2 injects into the pty when
# the user presses these keys in real life. Verified on iTerm2 3.x with
# default key mappings.
CTRL_RIGHT = "\x1b[1;5C"
CTRL_LEFT = "\x1b[1;5D"


DUMP_DIR = REPO_ROOT / "tests" / "qa_archive" / "results" / "2026-04-12_phase5_live_smoke"


def _save_dump(label: str, content: str) -> Path:
    DUMP_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%H%M%S")
    path = DUMP_DIR / f"{ts}_{label}.txt"
    path.write_text(content, encoding="utf-8")
    return path


async def _wait_ticks(tester: ITerm2CliTester, seconds: float) -> str:
    """Poll-capture for `seconds` seconds (accumulates into the
    recording buffer if recording is active)."""
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
    # Fallback: if .venv doesn't exist, use system python3
    venv_python = REPO_ROOT / ".venv" / "bin" / "python"
    if not venv_python.exists():
        cfg.launch_cmd = "python3 main.py --mode fin"

    tester = ITerm2CliTester(cfg)

    results = []

    async with tester:
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
        print("[smoke] Turn 1: /fleet start fin-core")
        tester.start_recording()
        await tester.send("/fleet start fin-core")
        screen = await _wait_ticks(tester, 5.0)
        turn1 = tester.stop_recording() or screen
        _save_dump("01_fleet_start", turn1)
        ok_start = (
            "Fleet fin-core started" in turn1
            and "@fin-rt" in turn1
            and "@dev-1" in turn1
        )
        tag_bar = "@fin-rt" in turn1 and "[mgr-1]" in turn1
        results.append(("fleet_start_confirmation", ok_start))
        results.append(("status_bar_tags_rendered", tag_bar))
        print(f"[smoke]   confirmation: {'PASS' if ok_start else 'FAIL'}")
        print(f"[smoke]   tag bar:      {'PASS' if tag_bar else 'FAIL'}")

        # ── Turn 2: /fleet status ─────────────────────────────────
        print("[smoke] Turn 2: /fleet status")
        tester.start_recording()
        await tester.send("/fleet status")
        screen = await _wait_ticks(tester, 3.0)
        turn2 = tester.stop_recording() or screen
        _save_dump("02_fleet_status", turn2)
        ok_status = (
            "fin-core" in turn2
            and "Focus" in turn2
            and "Members" in turn2
            and "@fin-rt" in turn2
        )
        results.append(("fleet_status_renders", ok_status))
        print(f"[smoke]   status view:  {'PASS' if ok_status else 'FAIL'}")

        # ── Turn 3: /fleet focus fin-rt (enter alt-screen isolated view) ───
        print("[smoke] Turn 3: /fleet focus fin-rt (enter alt screen)")
        tester.start_recording()
        await tester.send("/fleet focus fin-rt")
        screen = await _wait_ticks(tester, 3.0)
        turn3 = tester.stop_recording() or screen
        _save_dump("03_focus_fin_rt", turn3)
        # NEW: the alt-screen view should ONLY contain the focused
        # agent's banner + events, NOT the previous /fleet status
        # output or the /fleet start confirmation. Absence is the
        # critical assertion — presence of agent-specific content
        # alone isn't enough.
        ok_focus = "@fin-rt" in turn3 and (
            "Isolated conversation view" in turn3 or "╭─" in turn3
        )
        # Isolation check: /fleet status output should NOT be on the
        # currently-visible screen (it was printed on the primary
        # screen, and we're now in the alt screen)
        last_screen = await tester.capture(lines=80)
        _save_dump("03b_focus_fin_rt_final_screen", last_screen)
        no_leak_from_main = (
            "Fleet: fin-core  uptime" not in last_screen
            and "claimed=0  completed=" not in last_screen
        )
        results.append(("focus_banner_rendered", ok_focus))
        results.append(("alt_screen_isolates_from_main", no_leak_from_main))
        print(f"[smoke]   focus banner: {'PASS' if ok_focus else 'FAIL'}")
        print(f"[smoke]   isolated view: {'PASS' if no_leak_from_main else 'FAIL'}")

        # ── Turn 4: Ctrl+Right to cycle focus to fin-rsrch ─────────
        # After the alt-screen rewrite (2026-04-12), the focused view
        # header uses the ╭─ box-drawing prefix instead of "focus →".
        # The sub-agent header pattern we look for is "╭─ @<name>".
        print("[smoke] Turn 4: Ctrl+Right (cycle focus)")
        tester.start_recording()
        await tester.send(CTRL_RIGHT, enter=False)
        screen = await _wait_ticks(tester, 3.0)
        turn4 = tester.stop_recording() or screen
        _save_dump("04_ctrl_right", turn4)
        ok_ctrl_right = (
            "@fin-rsrch" in turn4
            and ("╭─" in turn4 or "Isolated conversation view" in turn4)
        )
        results.append(("ctrl_right_cycles_focus", ok_ctrl_right))
        print(f"[smoke]   Ctrl+Right:   {'PASS' if ok_ctrl_right else 'FAIL'}")

        # ── Turn 5: Ctrl+Left (cycle backward to fin-rt) ─────────
        print("[smoke] Turn 5: Ctrl+Left (cycle back)")
        tester.start_recording()
        await tester.send(CTRL_LEFT, enter=False)
        screen = await _wait_ticks(tester, 3.0)
        turn5 = tester.stop_recording() or screen
        _save_dump("05_ctrl_left", turn5)
        ok_ctrl_left = (
            "@fin-rt" in turn5
            and ("╭─" in turn5 or "Isolated conversation view" in turn5)
        )
        results.append(("ctrl_left_cycles_focus", ok_ctrl_left))
        print(f"[smoke]   Ctrl+Left:    {'PASS' if ok_ctrl_left else 'FAIL'}")

        # ── Turn 6: /fleet focus leader (leave alt screen) ────────
        print("[smoke] Turn 6: /fleet focus leader (leave alt screen)")
        tester.start_recording()
        await tester.send("/fleet focus leader")
        screen = await _wait_ticks(tester, 3.0)
        turn6 = tester.stop_recording() or screen
        _save_dump("06_focus_leader", turn6)
        ok_leader = "leader" in turn6 or "mgr-1" in turn6 or "back to" in turn6
        # CRITICAL regression check: after leaving the alt screen,
        # the visible terminal should have the ORIGINAL pre-alt-screen
        # content restored — that means /fleet start and /fleet status
        # lines should be back on the visible primary screen. If they
        # aren't, alt-screen restore isn't working.
        last_screen = await tester.capture(lines=80)
        _save_dump("06b_leader_final_screen", last_screen)
        restored = (
            "/fleet start fin-core" in last_screen
            or "Fleet fin-core started" in last_screen
        )
        # And the alt-screen sub-agent banner should NOT be visible
        # anymore
        no_subagent_bleed = "Isolated conversation view" not in last_screen
        results.append(("focus_leader_works", ok_leader))
        results.append(("primary_scrollback_restored", restored))
        results.append(("no_sub_agent_bleed_after_leave", no_subagent_bleed))
        print(f"[smoke]   focus leader: {'PASS' if ok_leader else 'FAIL'}")
        print(f"[smoke]   scrollback restored: {'PASS' if restored else 'FAIL'}")
        print(f"[smoke]   no sub-agent bleed: {'PASS' if no_subagent_bleed else 'FAIL'}")

        # ── Turn 7: /fleet stop ───────────────────────────────────
        print("[smoke] Turn 7: /fleet stop")
        tester.start_recording()
        await tester.send("/fleet stop")
        screen = await _wait_ticks(tester, 5.0)
        turn7 = tester.stop_recording() or screen
        _save_dump("07_fleet_stop", turn7)
        ok_stop = "Fleet stopped" in turn7
        results.append(("fleet_stop_confirms", ok_stop))
        print(f"[smoke]   fleet stop:   {'PASS' if ok_stop else 'FAIL'}")

        # ── Turn 8: status bar no longer has fleet tags ────────────
        print("[smoke] Turn 8: verify tags gone after stop")
        await asyncio.sleep(1.0)
        screen = await tester.capture(lines=80)
        _save_dump("08_post_stop", screen)
        # After stop, status bar should NOT contain "@fin-rt" in the
        # bottom toolbar (the region with "Ctrl+D exit"). We can't
        # cleanly parse just the toolbar, so we check that "fin-core"
        # is absent from the last 5 lines.
        last_lines = "\n".join(screen.splitlines()[-5:])
        ok_cleanup = "@fin-rt" not in last_lines
        results.append(("status_bar_cleared_after_stop", ok_cleanup))
        print(f"[smoke]   bar cleared:  {'PASS' if ok_cleanup else 'FAIL'}")

    # ── Summary ─────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print(f"Phase 5 live smoke: {sum(1 for _, ok in results if ok)}/{len(results)} checks passed")
    print("=" * 60)
    for label, ok in results:
        print(f"  [{'✓' if ok else '✗'}] {label}")
    print()
    print(f"Dumps saved under: {DUMP_DIR}")
    print()

    exit_code = 0 if all(ok for _, ok in results) else 1
    return exit_code


if __name__ == "__main__":
    try:
        rc = asyncio.run(run())
    except KeyboardInterrupt:
        rc = 130
    except Exception as e:
        print(f"[smoke] runner crashed: {type(e).__name__}: {e}")
        rc = 3
    sys.exit(rc)
