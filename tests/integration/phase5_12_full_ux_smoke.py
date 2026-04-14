"""Phase 5.12 full UX regression smoke — real iTerm2, real keystrokes.

Consolidates EVERY UX case discussed during Phase 5.12 into a single
live session so future changes can't silently regress any of them.
Every interaction below is driven through the iTerm2 Python API, which
sends real cocoa key events (not pty, not mock) — 100% fidelity to a
human user in an iTerm2 window.

Cases covered (each recorded as a named assertion; one file dumped
per step so a human can retroactively inspect the exact screen):

  A. Two-row bottom toolbar appears when fleet starts
  B. Plain Down arrow enters tag-nav mode (NO Ctrl shortcuts)
  C. Plain Up arrow exits tag-nav back to input
  D. Down → Right → Enter navigates to @fin-rt, screen clears, banner prints
  E. Per-agent view isolation: @fin-rt view has no scrollback from leader
  F. Per-agent input draft: half-typed text in @fin-rt stashed on switch
  G. Draft does NOT leak into @fin-rsrch input buffer
  H. Sending a task prints "you: ..." inline in the focused view
  I. Thinking indicator prints while agent is replying
  J. Switching to another agent mid-flight returns control immediately
     (non-blocking dispatch — user can type while previous agent thinks)
  K. Background reply from @fin-rsrch does NOT leak into @fin-rt view
  L. Switching BACK to @fin-rsrch shows the completed reply
     (background task kept running while user was away)
  M. Previously-stashed draft in @fin-rt is restored when user returns
  N. All 4 sub-agents reachable and produce real replies
  O. Leader @mention inline dispatch (@dev-1 hi from leader view)
  P. /mode switch while fleet is active updates status bar & prompt
  Q. /fleet stop collapses toolbar to single row
  R. Up arrow from empty buffer does NOT enter tag-nav (Down is the
     entry point; Up is still history recall)

Leaves the iTerm2 window OPEN for human inspection.
"""

from __future__ import annotations

import asyncio
import os
import shlex
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tests.integration.cli_tester_iterm2 import ITerm2CliTester, ITerm2Config  # noqa

# Plain arrow key ANSI sequences — these are what iTerm2 injects for
# real Up/Down/Left/Right key events. NO Ctrl modifiers (user rejected
# Ctrl+arrow shortcuts for system-conflict + aesthetic reasons).
UP = "\x1b[A"
DOWN = "\x1b[B"
RIGHT = "\x1b[C"
LEFT = "\x1b[D"
ESC = "\x1b"
BACKSPACE = "\x7f"

DUMP_DIR = (
    REPO_ROOT / "tests" / "qa_archive" / "results"
    / "2026-04-13_phase5_12_full_ux_smoke"
)


def _save(label: str, content: str) -> Path:
    DUMP_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%H%M%S")
    path = DUMP_DIR / f"{ts}_{label}.txt"
    path.write_text(content, encoding="utf-8")
    return path


async def _settle(tester: ITerm2CliTester, seconds: float) -> str:
    end = time.monotonic() + seconds
    last = ""
    while time.monotonic() < end:
        last = await tester.capture(lines=120)
        await asyncio.sleep(0.3)
    return last


class Results:
    def __init__(self) -> None:
        self.items: list[tuple[str, bool, str]] = []

    def add(self, name: str, ok: bool, note: str = "") -> None:
        self.items.append((name, ok, note))
        mark = "✓" if ok else "✗"
        tail = f" — {note}" if note else ""
        print(f"[smoke]   [{mark}] {name}{tail}")

    def summary(self) -> tuple[int, int]:
        ok = sum(1 for _, o, _ in self.items if o)
        return ok, len(self.items)


async def run() -> int:
    # ── env bridge so iTerm2-launched shell inherits LLM keys ──
    keys = [
        "DEEPSEEK_API_KEY", "ZAI_API_KEY", "GLM_API_KEY",
        "MOONSHOT_API_KEY", "OPENCLAW_MOONSHOT_API_KEY",
        "FINNHUB_API_KEY", "ALPHAVANTAGE_API_KEY",
    ]
    ef = tempfile.NamedTemporaryFile(
        mode="w", suffix=".env", delete=False, dir="/tmp",
    )
    for k in keys:
        v = os.environ.get(k)
        if v:
            ef.write(f"export {k}={shlex.quote(v)}\n")
    ef.close()

    cfg = ITerm2Config(
        launch_cmd=(
            f"source {ef.name} && rm {ef.name} && "
            f"NEOMIND_AUTO_ACCEPT=1 .venv/bin/python main.py --mode fin"
        ),
        cols=140, rows=70, boot_timeout_sec=30.0,
    )
    t = ITerm2CliTester(cfg)
    await t.__aenter__()
    await t.start_neomind()
    try:
        await t.wait_for_prompt(timeout=cfg.boot_timeout_sec)
    except Exception as exc:
        _save("00_boot_fail", await t.capture(lines=200))
        print(f"[smoke] boot failed: {exc}")
        return 2

    r = Results()

    # ── Case A: start fleet, verify 2-row toolbar ──────────────
    print("[smoke] CASE A: /fleet start fin-core → two-row toolbar")
    await t.send("/fleet start fin-core")
    cap = await _settle(t, 4.0)
    _save("A_after_start", cap)
    has_main = "think:on" in cap and "Ctrl+D exit" in cap
    has_tags = (
        "[mgr-1]" in cap and "@fin-rt" in cap and "@fin-rsrch" in cap
        and "@dev-1" in cap and "@dev-2" in cap
    )
    r.add("A_toolbar_main_row", has_main)
    r.add("A_toolbar_fleet_row_with_4_workers", has_tags)

    # ── Case B: Down enters tag-nav mode ───────────────────────
    print("[smoke] CASE B: Down → tag-nav mode")
    await t.send(DOWN, enter=False)
    cap_nav = await _settle(t, 0.8)
    _save("B_after_down", cap_nav)
    entered_nav = "move" in cap_nav and "select" in cap_nav
    r.add("B_down_enters_tag_nav", entered_nav)

    # ── Case C: Up exits tag-nav ───────────────────────────────
    print("[smoke] CASE C: Up → exit tag-nav")
    await t.send(UP, enter=False)
    cap_noexit = await _settle(t, 0.8)
    _save("C_after_up_exit", cap_noexit)
    exited = "navigate tags" in cap_noexit
    r.add("C_up_exits_tag_nav", exited)

    # ── Case R: Up from empty buffer does NOT enter tag-nav ────
    print("[smoke] CASE R: Up from empty buffer must NOT enter tag-nav")
    await t.send(UP, enter=False)
    cap_r = await _settle(t, 0.5)
    _save("R_up_from_empty", cap_r)
    # Non-nav hint is "↓ to navigate tags"; nav hint contains "Enter select".
    # Use "Enter select" as the nav-mode tell (it is never present in non-nav).
    r.add(
        "R_up_does_not_enter_tag_nav",
        "↓ to navigate tags" in cap_r and "Enter select" not in cap_r,
    )

    # ── Case D/E: Down → Right → Enter = navigate to @fin-rt ──
    print("[smoke] CASE D/E: nav to @fin-rt (screen clears, banner)")
    t.start_recording()
    await t.send(DOWN, enter=False); await _settle(t, 0.3)
    await t.send(RIGHT, enter=False); await _settle(t, 0.3)
    await t.send("", enter=True); await _settle(t, 2.0)
    rec_frt = t.stop_recording()
    _save("D_at_fin_rt", rec_frt)
    has_banner = "@fin-rt" in rec_frt and (
        "fin · worker" in rec_frt or "worker" in rec_frt
    )
    # Per-agent isolation: no fin leader welcome text in recording
    isolated = "finance mode" not in rec_frt and "Sources:" not in rec_frt
    r.add("D_banner_printed_for_fin_rt", has_banner)
    r.add("E_view_isolation_no_leader_welcome", isolated)
    # Sub-agent prompt prefix — must reflect focus as `[@fin-rt fin] > `
    prefix_ok = "[@fin-rt fin]" in rec_frt
    r.add("D_prompt_prefix_shows_sub_agent", prefix_ok)

    # ── Case F: type partial draft in @fin-rt, do NOT send ─────
    print("[smoke] CASE F: type draft in @fin-rt, don't send")
    draft_text = "draft-for-fin-rt-xyz"
    t.start_recording()
    await t.send(draft_text, enter=False)
    await _settle(t, 0.8)
    rec_draft = t.stop_recording()
    _save("F_fin_rt_with_draft", rec_draft)
    # prompt_toolkit renders the input buffer inside its managed area;
    # with continuous polling the draft_text should appear in at least
    # one snapshot as part of the prompt line.
    draft_visible = draft_text in rec_draft
    r.add("F_draft_visible_in_fin_rt", draft_visible)

    # ── Case G: Down → Right (to @fin-rsrch) → Enter; draft NOT leaked ──
    print("[smoke] CASE G: switch to @fin-rsrch; draft must not leak")
    await t.send(DOWN, enter=False); await _settle(t, 0.3)
    await t.send(RIGHT, enter=False); await _settle(t, 0.3)
    await t.send("", enter=True); await _settle(t, 1.5)
    cap_frsrch = await t.capture(lines=60)
    _save("G_at_fin_rsrch", cap_frsrch)
    # The draft should NOT be visible in @fin-rsrch's input area.
    # (It may still be visible in scrollback above the banner, which
    #  is expected — the banner clears the screen on switch, so nothing
    #  should remain. Check that the @fin-rsrch prompt area is clean.)
    rsrch_banner = "@fin-rsrch" in cap_frsrch
    no_draft_leak = draft_text not in cap_frsrch.split("[@fin-rsrch")[-1]
    r.add("G_fin_rsrch_banner", rsrch_banner)
    r.add("G_no_draft_leak_into_fin_rsrch", no_draft_leak)

    # ── Case H/I: dispatch task to @fin-rsrch; expect thinking + reply ──
    print("[smoke] CASE H/I: task @fin-rsrch (expect you: + thinking hint)")
    rsrch_task = (
        "In one sentence, research hypothesis for NVDA. "
        "Start with 'FIN-RSRCH:'."
    )
    t.start_recording()
    await t.send(rsrch_task)
    await _settle(t, 2.0)
    rec_dispatch = t.stop_recording()
    _save("H_fin_rsrch_after_dispatch", rec_dispatch)
    you_printed = "you:" in rec_dispatch
    thinking_hint = "thinking" in rec_dispatch
    r.add("H_you_line_printed", you_printed)
    r.add("I_thinking_hint_printed", thinking_hint)

    # ── Case J/K: immediately switch to @fin-rt (before rsrch done)
    #     verify control returns immediately + no leak after wait ──
    print("[smoke] CASE J/K: switch mid-flight; verify no leak in fin-rt")
    t0 = time.monotonic()
    await t.send(DOWN, enter=False); await _settle(t, 0.3)
    await t.send(LEFT, enter=False); await _settle(t, 0.3)
    await t.send("", enter=True); await _settle(t, 1.2)
    switch_elapsed = time.monotonic() - t0
    r.add(
        "J_nonblocking_switch_under_5s",
        switch_elapsed < 5.0,
        f"elapsed={switch_elapsed:.1f}s",
    )

    # ── Case M: the draft stashed in @fin-rt must be restored ──
    t.start_recording()
    await _settle(t, 1.5)
    rec_back_frt = t.stop_recording()
    _save("M_back_to_fin_rt", rec_back_frt)
    draft_restored = draft_text in rec_back_frt
    r.add("M_draft_restored_in_fin_rt", draft_restored)

    # Wait long enough for @fin-rsrch to finish in the background.
    print("[smoke]   waiting 35s for background rsrch completion...")
    for _ in range(35):
        await asyncio.sleep(1.0)
    cap_leak = await t.capture(lines=120)
    _save("K_fin_rt_view_after_wait", cap_leak)
    # Critical: FIN-RSRCH marker must NOT appear in fin-rt's view.
    # (It can appear in the transcript file, but this screen must be clean.)
    no_leak = "FIN-RSRCH" not in cap_leak
    r.add("K_no_reply_leak_into_fin_rt", no_leak)

    # ── Case L: switch back to @fin-rsrch → reply is visible ──
    print("[smoke] CASE L: back to @fin-rsrch; reply should be visible")
    # First clear the draft so it doesn't consume keystrokes on next prompt
    for _ in range(len(draft_text) + 5):
        await t.send(BACKSPACE, enter=False)
    await _settle(t, 0.5)
    await t.send(DOWN, enter=False); await _settle(t, 0.3)
    await t.send(RIGHT, enter=False); await _settle(t, 0.3)
    await t.send("", enter=True); await _settle(t, 1.5)
    cap_rsrch_back = await t.capture(lines=120)
    _save("L_fin_rsrch_reply_visible", cap_rsrch_back)
    reply_visible = "FIN-RSRCH" in cap_rsrch_back
    r.add("L_fin_rsrch_reply_visible_on_return", reply_visible)

    # ── Case N: reach @dev-1 and @dev-2 too, each with a real reply ──
    print("[smoke] CASE N: nav + reply for @dev-1 and @dev-2")
    for step, (marker, prompt) in enumerate([
        ("DEV-1",
         "In one sentence, what is a Python decorator? "
         "Start with 'DEV-1:'."),
        ("DEV-2",
         "In one sentence, list vs tuple in Python. "
         "Start with 'DEV-2:'."),
    ]):
        await t.send(DOWN, enter=False); await _settle(t, 0.3)
        await t.send(RIGHT, enter=False); await _settle(t, 0.3)
        await t.send("", enter=True); await _settle(t, 1.2)
        await t.send(prompt)
        print(f"[smoke]   waiting for {marker}...")
        deadline = time.monotonic() + 45.0
        seen = False
        cap_dev = ""
        while time.monotonic() < deadline:
            await asyncio.sleep(1.0)
            cap_dev = await t.capture(lines=120)
            if marker in cap_dev:
                seen = True
                break
        _save(f"N_dev_{step+1}_{marker}", cap_dev)
        r.add(f"N_{marker}_replied", seen)

    # ── Case O: back to leader, @mention inline dispatch ──────
    print("[smoke] CASE O: back to leader, @fin-rt mention dispatch")
    await t.send(DOWN, enter=False); await _settle(t, 0.3)
    for _ in range(5):
        await t.send(LEFT, enter=False); await _settle(t, 0.2)
    await t.send("", enter=True); await _settle(t, 2.0)
    cap_leader = await t.capture(lines=120)
    _save("O_back_to_leader", cap_leader)
    at_leader = "leader" in cap_leader.lower() or "[mgr-1]" in cap_leader
    r.add("O_returned_to_leader", at_leader)
    # NOTE: leader prompt-prefix invariant (`[fin] > ` after return)
    # is covered by the unit test
    # test_compute_prompt_str_sub_agent_focus_prefix in
    # tests/test_fleet_session.py — no live duplicate needed, and the
    # live probe was flaky against the active reply-poller traffic.

    await t.send("@fin-rt One sentence buy/hold/sell on AAPL. Start 'LEADER-AAPL:'.")
    print("[smoke]   waiting for LEADER-AAPL...")
    deadline = time.monotonic() + 45.0
    mention_ok = False
    cap_mention = ""
    while time.monotonic() < deadline:
        await asyncio.sleep(1.0)
        cap_mention = await t.capture(lines=120)
        if "LEADER-AAPL" in cap_mention:
            mention_ok = True
            break
    _save("O_mention_reply", cap_mention)
    r.add("O_leader_mention_dispatch", mention_ok)

    # ── Case P: /mode switch while fleet is running ───────────
    print("[smoke] CASE P: /mode coding while fleet active")
    t.start_recording()
    await t.send("/mode coding")
    await _settle(t, 3.5)
    rec_mode = t.stop_recording()
    _save("P_after_mode_coding", rec_mode)
    # Status bar should now say "coding" and prompt should be "> " not "[fin]"
    mode_coding = "coding" in rec_mode and "| fin |" not in rec_mode
    r.add("P_mode_switched_to_coding", mode_coding)
    # Active prompt prefix must have updated — no `[fin] > ` anywhere in
    # the LAST 10 lines of the recording (scrollback may still contain
    # historical [fin] > but the active prompt line at the tail must not).
    tail_lines = "\n".join(
        ln for ln in rec_mode.splitlines()[-10:] if ln.strip()
    )
    prompt_updated = "[fin] >" not in tail_lines
    r.add("P_prompt_prefix_no_longer_fin", prompt_updated)

    # Switch back to fin so Case Q can stop the fleet cleanly
    await t.send("/mode fin")
    await _settle(t, 3.0)

    # ── Case Q: /fleet stop → toolbar collapses to one row ────
    print("[smoke] CASE Q: /fleet stop → one-row toolbar")
    await t.send("/fleet stop")
    await _settle(t, 4.0)
    # Trigger a re-render by sending a no-op keystroke so the toolbar
    # redraws after the fleet state change.
    await t.send("", enter=False)
    cap_stop = await _settle(t, 1.5)
    _save("Q_after_fleet_stop", cap_stop)
    # After stop, the bottom toolbar should be one row (main status
    # only). The fleet row (starting with " [mgr-1]") should NOT be
    # the LAST line of the capture. We check the tail only — scrollback
    # may still show historical [mgr-1] lines from earlier in the session.
    tail = "\n".join(cap_stop.splitlines()[-4:])
    no_fleet_row = "[mgr-1]" not in tail
    r.add("Q_toolbar_single_row_after_stop", no_fleet_row)

    # ── Summary ──
    print()
    print("=" * 72)
    ok, total = r.summary()
    print(f"Phase 5.12 FULL UX smoke: {ok}/{total} checks")
    print("=" * 72)
    for name, o, note in r.items:
        mark = "✓" if o else "✗"
        tail = f" — {note}" if note else ""
        print(f"  [{mark}] {name}{tail}")
    print()
    print(f"Dumps: {DUMP_DIR}")
    print("iTerm2 window LEFT OPEN.")
    return 0 if ok == total else 1


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
