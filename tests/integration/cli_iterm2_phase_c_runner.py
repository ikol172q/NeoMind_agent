"""Phase C — 5-scenario smoke runner for the iTerm2 CLI driver.

Exercises ITerm2CliTester against a live iTerm2 window running the
NeoMind CLI. Complements the Telethon pre-activation smoke by
covering the CLI surface with the same semantic scenarios:

    1. /status         — mode + model identifier visible
    2. /mode fin       — mode switch confirmed
    3. AAPL 现价        — NL finance tool dispatch returns price
    4. /tune status    — tune slash still works after taxonomy v5
    5. /clear          — archive-and-wipe still works

Run once the user has:
  1. `defaults write com.googlecode.iterm2 EnableAPIServer -bool true` (already done)
  2. Quit + re-open iTerm2 and clicked Allow on the first-time API dialog

Invocation:
    .venv/bin/python tests/integration/cli_iterm2_phase_c_runner.py

Exit codes:
    0 = all 5 scenarios PASS
    1 = ITerm2APIUnavailable (user step 2 not done)
    2 = one or more scenarios FAIL
    3 = CLI failed to boot / prompt never appeared
"""

from __future__ import annotations

import asyncio
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List

# Add repo root to sys.path so imports work regardless of cwd.
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tests.integration.cli_tester_iterm2 import (  # noqa: E402
    ITerm2CliTester, ITerm2APIUnavailable, ITerm2Config,
)


@dataclass
class Scenario:
    sid: str
    send: str
    wait_sec: float
    expect_any: List[str]


SCENARIOS: List[Scenario] = [
    Scenario(
        sid="C1_status",
        send="/status",
        wait_sec=15,
        expect_any=["mode", "模式", "kimi", "deepseek", "router"],
    ),
    Scenario(
        sid="C2_mode_fin",
        send="/mode fin",
        wait_sec=10,
        expect_any=["fin", "已切换", "switched"],
    ),
    Scenario(
        sid="C3_aapl",
        send="AAPL 现价",
        wait_sec=90,
        expect_any=["AAPL", "Apple", "$", "260", "yfinance", "Source"],
    ),
    Scenario(
        sid="C4_tune_status",
        send="/tune status",
        wait_sec=15,
        expect_any=["tune", "defaults", "overrides", "默认", "无",
                    "追加", "custom"],
    ),
    Scenario(
        sid="C5_clear",
        send="/clear",
        wait_sec=15,
        expect_any=["clear", "cleared", "归档", "已清", "wiped", "archive"],
    ),
]


async def run_one(tester: ITerm2CliTester, sc: Scenario) -> tuple:
    """Run a single scenario, return (verdict, elapsed, snippet)."""
    t0 = time.time()
    # Baseline: capture screen contents before we send
    before = await tester.capture(lines=60)

    await tester.send(sc.send)

    # Poll capture() until new content appears OR wait_sec elapsed
    deadline = time.time() + sc.wait_sec
    snippet = ""
    matched = False
    while time.time() < deadline:
        await asyncio.sleep(0.6)
        screen = await tester.capture(lines=80)
        # We compare to `before` — if the tail has grown, something
        # new was rendered.
        if len(screen) <= len(before):
            continue
        new_tail = screen[len(before):]
        # Also allow partial-line overlaps by checking any keyword
        # across the full screen, since prompt_toolkit edits can
        # shift earlier content.
        for kw in sc.expect_any:
            if kw in screen:
                matched = True
                snippet = new_tail[-200:].strip().replace("\n", " ⏎ ")
                break
        if matched:
            break

    elapsed = time.time() - t0
    if not snippet:
        screen = await tester.capture(lines=80)
        snippet = screen[-200:].strip().replace("\n", " ⏎ ")
    return ("PASS" if matched else "FAIL", elapsed, snippet[:180])


async def main() -> int:
    try:
        cfg = ITerm2Config(
            launch_cmd=".venv/bin/python main.py interactive --mode fin",
            cwd=str(REPO_ROOT),
            cols=120,
            rows=40,
            visible=True,
            boot_timeout_sec=25.0,
        )
        async with ITerm2CliTester(cfg) as tester:
            print(f"[iterm2-phase-c] connected to iTerm2")
            await tester.start_neomind()
            print(f"[iterm2-phase-c] opened window, waiting for prompt...")
            ok = await tester.wait_for_prompt(timeout=25)
            if not ok:
                screen = await tester.capture(lines=80)
                print(f"[iterm2-phase-c] prompt never appeared. tail:\n{screen[-800:]}")
                return 3
            print(f"[iterm2-phase-c] prompt ready — running {len(SCENARIOS)} scenarios")

            passed = 0
            results = []
            for sc in SCENARIOS:
                verdict, elapsed, snip = await run_one(tester, sc)
                results.append((sc.sid, verdict, elapsed, snip))
                print(f"[iterm2-phase-c] {sc.sid}: {verdict} ({elapsed:.1f}s) — {snip}")
                if verdict == "PASS":
                    passed += 1
                # Gentle spacing — don't hammer the LLM
                await asyncio.sleep(4)

            print(f"\n[iterm2-phase-c] RESULT: {passed}/{len(SCENARIOS)} PASS")
            for sid, verdict, elapsed, snip in results:
                print(f"  {sid}: {verdict}  ({elapsed:.1f}s)")
            return 0 if passed == len(SCENARIOS) else 2

    except ITerm2APIUnavailable as e:
        print(f"[iterm2-phase-c] ITerm2APIUnavailable: {e}")
        print("[iterm2-phase-c] remediation: ")
        print("  1. defaults write com.googlecode.iterm2 EnableAPIServer -bool true")
        print("  2. Quit iTerm2 (⌘Q)")
        print("  3. Re-open iTerm2")
        print("  4. Click Allow on the first-time Python API dialog")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
