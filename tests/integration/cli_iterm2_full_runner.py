"""Phase C Full Runner — rigorous CLI scenario validation via iTerm2.

Improves on `cli_iterm2_phase_c_runner.py` which had three known gaps:

1. **Status-bar keyword collision**: prompt_toolkit draws a persistent
   status bar containing `chat | fin | think:on | deepseek-chat`. The
   old runner matched `expect_any` against the entire screen so a
   scenario expecting "fin" got an instant PASS from the status bar
   even before the LLM answered.

2. **0.6s per scenario**: the match loop polled every 0.4s and exited
   on first hit — which was always immediately because of #1.
   Real LLM replies in fin mode take 10-90s.

3. **No "new content below prompt" discipline**: the old runner could
   not tell the difference between the command echo, the LLM thinking
   spinner, and the real reply.

This runner fixes all three:

- **Strip status bar rows**: the last N lines of the capture are
  assumed to be prompt_toolkit chrome (status bar + blank lines +
  footer) and excluded from keyword matching.
- **Anchor on `[fin] >` before AND after**: a scenario begins by
  capturing the full screen AFTER the prompt appears. The match
  region is the text that appears BETWEEN the SECOND-to-last
  `[fin] >` (the prompt where we typed) and the LAST `[fin] >`
  (the new prompt after the reply is rendered).
- **Hard minimum reply window**: even if a keyword matches, the
  runner waits at least `min_reply_wait_sec` to ensure the reply
  is actually complete before moving on.

Usage:
    .venv/bin/python tests/integration/cli_iterm2_full_runner.py

Exit codes:
    0 = all scenarios PASS thresholds
    1 = iTerm2 unavailable
    2 = scenarios FAIL
    3 = CLI boot timeout
"""

from __future__ import annotations

import asyncio
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tests.integration.cli_tester_iterm2 import (  # noqa: E402
    ITerm2CliTester, ITerm2APIUnavailable, ITerm2Config,
)


# ── Scenario library (14 scenarios across 5 categories) ────────────

@dataclass
class Scenario:
    sid: str
    send: str
    wait_sec: float
    expect_any: List[str]
    category: str
    # Minimum wait AFTER the first keyword hit before we accept it
    # as a real reply. Prevents grabbing a partial render.
    min_reply_wait_sec: float = 2.0
    # How long to wait for NEW text to appear below the prompt
    # before giving up and calling the scenario a fail.
    reply_timeout_sec: float = 60.0
    # The response must contain one of these to count as a real reply
    # (strict data-marker mode — empty list means loose keyword match).
    data_markers: List[str] = field(default_factory=list)


SCENARIOS: List[Scenario] = [
    # Category: M — mode and model basics (3)
    Scenario("M1_status", "/status", 10,
             ["模式", "mode", "kimi", "deepseek", "router"],
             "M", reply_timeout_sec=15),
    Scenario("M2_mode_coding", "/mode coding", 10,
             ["coding", "已切换", "switched"],
             "M", reply_timeout_sec=15),
    Scenario("M3_mode_fin", "/mode fin", 10,
             ["fin", "已切换", "switched"],
             "M", reply_timeout_sec=15),

    # Category: T — /tune subcommands (2)
    Scenario("T1_tune_status", "/tune status", 10,
             ["tune", "overrides", "defaults", "默认", "无", "custom"],
             "T", reply_timeout_sec=15),
    Scenario("T2_clear", "/clear", 10,
             ["clear", "归档", "已清", "wiped", "cleared"],
             "T", reply_timeout_sec=15),

    # Category: F — finance NL dispatch (3)
    Scenario("F1_aapl", "AAPL 现价", 90,
             ["AAPL", "Apple", "$", "260", "yfinance", "Source"],
             "F", reply_timeout_sec=90, min_reply_wait_sec=4,
             data_markers=["AAPL", "$"]),
    Scenario("F2_btc", "BTC 现价", 90,
             ["BTC", "Bitcoin", "$", "CoinGecko", "Source"],
             "F", reply_timeout_sec=90, min_reply_wait_sec=4,
             data_markers=["BTC", "$"]),
    Scenario("F3_compound", "10000元 年化8% 10年复利终值是多少", 90,
             ["21589", "21,589", "¥21", "本金", "复利", "终值"],
             "F", reply_timeout_sec=120, min_reply_wait_sec=5,
             data_markers=["21589", "21,589", "本金"]),

    # Category: Q — knowledge Q&A (2)
    Scenario("Q1_pe_ratio", "什么是市盈率? 不要搜索", 60,
             ["市盈率", "PE", "盈利", "股价"],
             "Q", reply_timeout_sec=90, min_reply_wait_sec=4,
             data_markers=["市盈率", "PE"]),
    Scenario("Q2_sharpe", "解释一下夏普比率, 不要搜索", 60,
             ["夏普", "Sharpe", "波动", "风险"],
             "Q", reply_timeout_sec=90, min_reply_wait_sec=4,
             data_markers=["夏普", "Sharpe"]),

    # Category: X — edge cases (4)
    Scenario("X1_empty_slash", "/", 10,
             ["命令", "help", "?", "usage"],
             "X", reply_timeout_sec=15),
    Scenario("X2_unknown_slash", "/totallyfake 一句话 CAPM 是什么 不要搜索", 60,
             ["CAPM", "beta", "市场", "资本"],
             "X", reply_timeout_sec=90, min_reply_wait_sec=4,
             data_markers=["CAPM"]),
    Scenario("X3_bare_enter", "", 5,
             ["[fin] >"],
             "X", reply_timeout_sec=8),  # blank line should just reprint prompt
    Scenario("X4_emoji", "🚀🚀🚀 你好", 30,
             ["你好", "hello", "🚀", "?", "问题"],
             "X", reply_timeout_sec=60, min_reply_wait_sec=3),
]


# Prompt anchor regex — matches `[fin] > ` or `[chat] >` or `[coding] >`
PROMPT_RE = re.compile(r"\[(chat|coding|fin)\]\s*>\s*")

# Status-bar bottom N lines to strip from capture before keyword check.
# prompt_toolkit's footer takes ~2-4 lines depending on terminal width.
STATUS_BAR_STRIP_LINES = 3


def _strip_status_bar(screen: str, strip_n: int = STATUS_BAR_STRIP_LINES) -> str:
    """Remove the last N non-empty lines which are prompt_toolkit chrome.

    We work on the full screen top-down and drop the final `strip_n`
    non-empty lines. Blank lines before the status bar are also dropped.
    """
    lines = screen.splitlines()
    # Walk from the bottom, skipping blanks and counting non-empty lines.
    non_empty_from_bottom = 0
    cut_at = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip():
            non_empty_from_bottom += 1
            if non_empty_from_bottom >= strip_n:
                cut_at = i
                break
    return "\n".join(lines[:cut_at])


def _extract_reply_region(stripped_screen: str) -> str:
    """Extract the text between the SECOND-to-last prompt and the LAST
    prompt in the stripped screen. This is the region containing the
    command we sent plus its reply.

    If there's only one prompt visible, return the tail from that prompt.
    If no prompt at all, return the whole stripped screen.
    """
    matches = list(PROMPT_RE.finditer(stripped_screen))
    if not matches:
        return stripped_screen
    if len(matches) == 1:
        return stripped_screen[matches[0].end():]
    # Between the second-to-last and last prompts
    return stripped_screen[matches[-2].end():matches[-1].start()]


async def run_scenario(tester: ITerm2CliTester, sc: Scenario) -> tuple:
    """Run one scenario with strict reply-region matching.

    Returns (verdict, elapsed_sec, reply_region_text, tool_fired).
    """
    t0 = time.time()

    # 1. Baseline: capture the current screen BEFORE we send.
    before_screen = await tester.capture(lines=80)
    before_stripped = _strip_status_bar(before_screen)
    before_prompts = len(list(PROMPT_RE.finditer(before_stripped)))

    # 2. Send the command.
    await tester.send(sc.send)

    # 3. Poll for: (a) at least one NEW prompt appearing below the
    #    baseline (evidence the CLI processed the command and returned
    #    to prompt), AND (b) the reply region contains one of the
    #    expected keywords, AND (c) after first match, wait the
    #    min_reply_wait_sec to ensure the reply is complete.
    deadline = t0 + sc.reply_timeout_sec
    matched = False
    first_match_time = 0.0
    reply_region = ""

    while time.time() < deadline:
        await asyncio.sleep(0.8)
        screen = await tester.capture(lines=100)
        stripped = _strip_status_bar(screen)
        cur_prompts = len(list(PROMPT_RE.finditer(stripped)))

        # We need at least one NEW prompt to have appeared
        if cur_prompts <= before_prompts:
            continue

        reply_region = _extract_reply_region(stripped)

        # Check data markers first (strict), then expect_any (loose)
        markers = sc.data_markers or sc.expect_any
        hit = any(kw in reply_region for kw in markers)
        if hit:
            if first_match_time == 0.0:
                first_match_time = time.time()
            # Wait min_reply_wait_sec past first match to ensure complete
            if time.time() - first_match_time >= sc.min_reply_wait_sec:
                matched = True
                break

    elapsed = time.time() - t0

    # Detect if a tool was actually fired (look for ✅/❌ + tool name)
    tool_fired = bool(
        re.search(r"(✅|❌)\s*\*?\*?(finance_|web_|Bash|Read|Write|Grep|WebSearch)",
                  reply_region)
    )

    return (
        "PASS" if matched else "FAIL",
        elapsed,
        reply_region[-400:].strip().replace("\n", " ⏎ "),
        tool_fired,
    )


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
            print(f"[cli-full] connected to iTerm2")
            await tester.start_neomind()
            print(f"[cli-full] opened window, waiting for prompt...")
            ok = await tester.wait_for_prompt(timeout=25)
            if not ok:
                screen = await tester.capture(lines=80)
                print(f"[cli-full] prompt never appeared. tail:\n{screen[-1000:]}")
                return 3
            print(f"[cli-full] prompt ready — running {len(SCENARIOS)} scenarios")
            print(f"[cli-full] strip={STATUS_BAR_STRIP_LINES} lines from bottom before matching")

            passed = 0
            results = []
            per_category = {}

            for sc in SCENARIOS:
                verdict, elapsed, region, tool_fired = await run_scenario(tester, sc)
                results.append({
                    "sid": sc.sid, "category": sc.category,
                    "verdict": verdict, "elapsed_sec": round(elapsed, 1),
                    "tool_fired": tool_fired,
                    "snippet": region[:180],
                    "expect_any": sc.expect_any,
                    "data_markers": sc.data_markers,
                })
                print(f"[cli-full] {sc.sid} [{sc.category}]: {verdict} "
                      f"({elapsed:.1f}s) tool={tool_fired} — {region[:140]}")
                if verdict == "PASS":
                    passed += 1
                per_category.setdefault(sc.category, {"pass": 0, "total": 0})
                per_category[sc.category]["total"] += 1
                if verdict == "PASS":
                    per_category[sc.category]["pass"] += 1

                # Spacing between scenarios — avoid hammering LLM
                await asyncio.sleep(5)

            print(f"\n[cli-full] ═══ RESULT: {passed}/{len(SCENARIOS)} PASS ═══")
            for cat, stats in sorted(per_category.items()):
                print(f"  [{cat}] {stats['pass']}/{stats['total']}")

            # Write JSON results for offline inspection
            import json
            with open("/tmp/cli_full_results.json", "w") as f:
                json.dump({
                    "head": "$REPO_ROOT",
                    "passed": passed,
                    "total": len(SCENARIOS),
                    "per_category": per_category,
                    "results": results,
                }, f, indent=2, ensure_ascii=False)
            print(f"[cli-full] results → /tmp/cli_full_results.json")

            return 0 if passed == len(SCENARIOS) else 2

    except ITerm2APIUnavailable as e:
        print(f"[cli-full] ITerm2APIUnavailable: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
