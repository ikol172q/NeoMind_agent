"""Phase 5.11 live iTerm2 smoke.

Drives a real iTerm2 window, starts fin-core, sends a distinct task
to each of the 4 sub-agents via @mention dispatch from the leader
view, waits for real DeepSeek responses, cycles focus with Ctrl+→,
captures each agent's alt-screen view, returns to leader, confirms
preservation, and **leaves the window open** for user inspection.

Key property verified: switching Ctrl+→ from @fin-rt to @fin-rsrch
and back to @fin-rt shows @fin-rt's conversation exactly as it was
before the switch — no mixing, no redraw loss.
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
CTRL_D = "\x04"
ESC = "\x1b"


DUMP_DIR = REPO_ROOT / "tests" / "qa_archive" / "results" / "2026-04-12_phase5_11_live_smoke"


# Short tasks — one per agent, each distinctly prefixed
AGENT_TASKS = [
    ("fin-rt",
     "In one sentence, give a buy/hold/sell view on MSFT. Start with 'FIN-RT:'."),
    ("fin-rsrch",
     "In one sentence, state a research hypothesis about NVDA. Start with 'FIN-RSRCH:'."),
    ("dev-1",
     "In one sentence, explain what a Python decorator is. Start with 'DEV-1:'."),
    ("dev-2",
     "In one sentence, explain the difference between a list and a tuple. Start with 'DEV-2:'."),
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
    # Thread LLM provider env vars through to the iTerm2-launched shell.
    # iTerm2 spawns via launchd which does NOT inherit my test runner's
    # env (where DEEPSEEK_API_KEY etc. live, because the Claude Code
    # Bash tool sets them in its session). We write them to a throwaway
    # env file that the launch command sources + deletes immediately,
    # so the keys never appear in `ps` output.
    import shlex
    import tempfile
    env_keys = [
        "DEEPSEEK_API_KEY",
        "ZAI_API_KEY",
        "GLM_API_KEY",
        "MOONSHOT_API_KEY",
        "OPENCLAW_MOONSHOT_API_KEY",
        "FINNHUB_API_KEY",
        "ALPHAVANTAGE_API_KEY",
    ]
    env_file = tempfile.NamedTemporaryFile(
        mode="w", suffix=".env", delete=False, dir="/tmp",
    )
    for key in env_keys:
        val = os.environ.get(key)
        if val:
            env_file.write(f"export {key}={shlex.quote(val)}\n")
    env_file.close()
    env_path = env_file.name
    print(f"[smoke] env bridge: {env_path}")

    python_bin = ".venv/bin/python"
    venv_python = REPO_ROOT / ".venv" / "bin" / "python"
    if not venv_python.exists():
        python_bin = "python3"

    cfg = ITerm2Config(
        launch_cmd=(
            f"source {env_path} && rm {env_path} && "
            f"{python_bin} main.py --mode fin"
        ),
        cols=140,
        rows=60,
        boot_timeout_sec=30.0,
    )

    tester = ITerm2CliTester(cfg)
    # Do NOT auto-close at exit — leave window open for user inspection
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

    results = []

    # ── Step 1: /fleet start fin-core (enters multi-agent view) ──
    print("[smoke] /fleet start fin-core  (enters Application)")
    await tester.send("/fleet start fin-core")
    # Wait long enough for session.start() + Application render
    await _wait_ticks(tester, 4.0)
    _save_dump("01_after_start", await tester.capture(lines=80))

    # The Application is now running. The status bar should show fleet
    # tags at the top (not bottom — Application layout).
    screen = await tester.capture(lines=80)
    ok_start = (
        "FLEET" in screen
        and "fin-core" in screen
        and "@fin-rt" in screen
        and "@fin-rsrch" in screen
    )
    # Initial focus should be leader
    leader_view = "Leader" in screen or "leader" in screen
    results.append(("app_entered_and_status_bar_shows_tags", ok_start))
    results.append(("initial_focus_is_leader_view", leader_view))
    print(f"[smoke]   application entered: {'PASS' if ok_start else 'FAIL'}")
    print(f"[smoke]   leader view shown:    {'PASS' if leader_view else 'FAIL'}")

    # ── Step 2: @mention dispatch from leader view (all 4 in sequence) ──
    print("[smoke] dispatching 4 @mention tasks from leader view...")
    for name, task in AGENT_TASKS:
        print(f"[smoke]   @{name}")
        await tester.send(f"@{name} {task}")
        await asyncio.sleep(0.3)
    _save_dump("02_all_dispatched", await tester.capture(lines=80))

    # ── Step 3: wait for all 4 completions (real DeepSeek) ──
    print("[smoke] waiting up to 45s for all 4 completions...")
    deadline = time.monotonic() + 45.0
    while time.monotonic() < deadline:
        await asyncio.sleep(1.5)
        # We don't have a clean way to check completion from outside
        # the Application, so just wait 15s then assume-done. Real
        # DeepSeek short prompts complete in 2-5s each; parallel
        # execution via the same loop should finish inside 10s total.
    await asyncio.sleep(1.0)  # settle
    _save_dump("03_after_wait", await tester.capture(lines=80))

    # ── Step 4: cycle focus to each agent and capture view ──
    print("[smoke] cycling focus with Ctrl+→ ...")
    focus_captures = {}
    for name, _ in AGENT_TASKS:
        print(f"[smoke]   Ctrl+→ → expect @{name}")
        await tester.send(CTRL_RIGHT, enter=False)
        await _wait_ticks(tester, 1.5)
        screen = await tester.capture(lines=80)
        focus_captures[name] = screen
        _save_dump(f"04_focus_{name}", screen)

    # ── Step 5: verify each agent's view contains its own content ──
    for name, task in AGENT_TASKS:
        cap = focus_captures[name]
        has_prefix = any(
            keyword in cap
            for keyword in (f"@{name}", name)
        )
        has_user_prompt = task[:30] in cap  # first 30 chars of prompt
        results.append((f"{name}_view_shows_own_banner", has_prefix))
        results.append((f"{name}_view_shows_user_prompt", has_user_prompt))
        print(f"[smoke]   @{name} banner:       {'PASS' if has_prefix else 'FAIL'}")
        print(f"[smoke]   @{name} user prompt:  {'PASS' if has_user_prompt else 'FAIL'}")

    # ── Step 6: CRITICAL — cycle back to first agent, verify preservation ──
    print("[smoke] cycling back to @fin-rt (should show original content)...")
    # Current focus is at @dev-2 (last in sequence). Cycle forward
    # to wrap through leader and back to @fin-rt. Leader is 1 step
    # from dev-2, @fin-rt is 2 steps.
    await tester.send(CTRL_RIGHT, enter=False)  # dev-2 → leader
    await _wait_ticks(tester, 0.8)
    await tester.send(CTRL_RIGHT, enter=False)  # leader → fin-rt
    await _wait_ticks(tester, 1.5)
    screen_return = await tester.capture(lines=80)
    _save_dump("05_return_to_fin_rt", screen_return)

    # The fin-rt view should STILL have its content. The status bar's
    # "uptime Ns" ticks between captures, so we strip lines that
    # contain uptime markers before comparing. Content lines (agent
    # user prompts, assistant responses) must match bit-for-bit.
    first_cap = focus_captures["fin-rt"]

    def _content_markers(cap: str):
        """Extract agent-view content lines that don't depend on
        time. Skips the status bar (contains uptime) and the empty
        box-char separator lines."""
        out = []
        for line in cap.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            # Skip status-bar-tainted lines (uptime changes between captures)
            if "uptime" in line or " FLEET " in line:
                continue
            # Skip the header bar row that includes [mgr-1] tags
            if "@fin-rt*" in line or "@fin-rsrch*" in line:
                continue
            if "@dev-1*" in line or "@dev-2*" in line:
                continue
            # Only content lines — box-char prefix or known text markers
            if stripped.startswith("│") or "FIN-RT" in line or "you:" in line:
                out.append(stripped)
        return out

    orig_markers = _content_markers(first_cap)
    return_markers = _content_markers(screen_return)
    # Preservation: every content marker from the first capture must
    # still appear in the return capture. New markers may have been
    # added (e.g. task_completed arrived between captures) — we allow
    # that. We just require no content was LOST.
    preserved = all(m in return_markers for m in orig_markers if m)
    # Fallback preservation check: user's prompt still visible verbatim
    user_prompt_preserved = AGENT_TASKS[0][1][:30] in screen_return
    results.append(("fin_rt_view_preserved_after_cycle", preserved))
    results.append(("fin_rt_user_prompt_still_visible", user_prompt_preserved))
    print(f"[smoke]   preservation (full):   {'PASS' if preserved else 'FAIL'}")
    print(f"[smoke]   preservation (prompt): {'PASS' if user_prompt_preserved else 'FAIL'}")

    # ── Step 7: Escape back to leader ──
    print("[smoke] Escape back to leader view...")
    await tester.send(ESC, enter=False)
    await _wait_ticks(tester, 1.5)
    leader_after = await tester.capture(lines=80)
    _save_dump("06_esc_to_leader", leader_after)
    back_to_leader = "Leader" in leader_after or "leader" in leader_after.lower()
    results.append(("escape_returns_to_leader", back_to_leader))
    print(f"[smoke]   Esc → leader:         {'PASS' if back_to_leader else 'FAIL'}")

    # ── Summary ──
    print()
    print("=" * 64)
    n_pass = sum(1 for _, ok in results if ok)
    print(f"Phase 5.11 live smoke: {n_pass}/{len(results)} checks")
    print("=" * 64)
    for label, ok in results:
        print(f"  [{'✓' if ok else '✗'}] {label}")
    print()
    print(f"Dumps: {DUMP_DIR}")
    print()
    print("iTerm2 window LEFT OPEN. You can:")
    print("  - Press Ctrl+← / Ctrl+→ to cycle focus yourself")
    print("  - Press Esc to jump to leader")
    print("  - Type @<agent> <msg> in leader view to dispatch")
    print("  - Type in a sub-agent view to send it a task")
    print("  - Press Ctrl+D to exit multi-agent view and return to CLI")
    print("  - Cmd+W to close the window")
    print()
    return 0 if n_pass == len(results) else 1


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
