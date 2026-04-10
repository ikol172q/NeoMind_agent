#!/usr/bin/env python3
"""
NeoMind self-test loop — runs the tester+fixer pattern against itself.

This is the direct-invocation form of the `selftest` skill at
`agent/skills/shared/selftest/SKILL.md`. It does not use the team/mailbox
indirection — it runs the tester and fixer phases in a single Python process,
so it's suitable for CI cron jobs and one-shot smoke tests.

Usage:
    PYTHONPATH=. python3 -m bench.selftest_loop --plan smoke
    PYTHONPATH=. python3 -m bench.selftest_loop --plan smoke --max-rounds 3
    PYTHONPATH=. python3 -m bench.selftest_loop --plan boundary --scope keyboard

Plans:
    smoke      — 8 scenarios, 1 mode, ~5 minutes
    short      — 30 scenarios from REAL_TERMINAL_TEST plan
    long       — 1 session × 50 turns from LONG_SESSION plan
    boundary   — 20 scenarios from PROJECT1 plan (real keystroke fidelity)

The script uses tmux directly, mirroring exactly what the skill's tester worker
would do — no env-var hacks, no clean_ansi, no pexpect.

Output:
    ~/.neomind/teams/selftest/results/<timestamp>/
        progress.md, results.md, fixes.md, final_report.md
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Callable, Tuple


# ── Configuration ────────────────────────────────────────────────────

WORKSPACE = Path(__file__).resolve().parent.parent
OUTPUT_ROOT = Path.home() / ".neomind" / "teams" / "selftest"
TMUX_SESSION = "nm_selftest"

LLM_SLEEP = 8        # seconds between LLM-triggering inputs
CMD_SLEEP = 5        # seconds between slash commands
STARTUP_SLEEP = 15   # seconds for prompt_toolkit to draw
RESTART_BATCH = 8    # restart REPL every N scenarios

ERROR_PATTERNS = [
    "PARSE FAILED",
    "parser returned None",
    "Traceback (most recent call last)",
    "<｜end▁of▁thinking｜>",
    "Detected simple filename",
]

SPINNER_CHARS = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


# ── Test scenarios ───────────────────────────────────────────────────

@dataclass
class Scenario:
    """One test scenario."""
    sid: str
    description: str
    setup: Optional[Callable] = None
    inputs: List[Tuple[str, str]] = field(default_factory=list)
    # inputs is a list of (kind, value) where kind is one of:
    #   "text"      — send_keys + Enter
    #   "key"       — send_keys raw (e.g. "C-c", "Tab", "BSpace")
    #   "sleep"     — sleep N seconds
    #   "expect"    — substring that must appear in capture
    #   "no_expect" — substring that must NOT appear
    sleep_after: float = LLM_SLEEP


# ── Smoke plan: minimal sanity check ──────────────────────────────────

SMOKE_PLAN: List[Scenario] = [
    Scenario(
        sid="SM01",
        description="Startup + identity",
        inputs=[
            ("text", "你是谁？"),
            ("expect", "NeoMind"),
        ],
        sleep_after=15,
    ),
    Scenario(
        sid="SM02",
        description="Slash command — /help",
        inputs=[
            ("text", "/help"),
            ("expect", "/clear"),
            ("no_expect", "Unknown command"),
        ],
        sleep_after=CMD_SLEEP,
    ),
    Scenario(
        sid="SM03",
        description="Slash command — /flags",
        inputs=[
            ("text", "/flags"),
            ("expect", "AUTO_DREAM"),
        ],
        sleep_after=CMD_SLEEP,
    ),
    Scenario(
        sid="SM04",
        description="Real Ctrl+C cancels typed input",
        inputs=[
            ("text", "draft a long story about"),
            ("key", "C-c"),
            ("sleep", 1),
            ("text", "/help"),
            ("expect", "/clear"),
        ],
        sleep_after=CMD_SLEEP,
    ),
    Scenario(
        sid="SM05",
        description="Tool call — Bash echo",
        inputs=[
            ("text", "Run: echo selftest_marker_xyz"),
            ("sleep", 12),
            ("key", "a"),  # auto-allow permission
            ("key", "Enter"),
            ("expect", "selftest_marker_xyz"),
            ("no_expect", "PARSE FAILED"),
        ],
        sleep_after=20,
    ),
    Scenario(
        sid="SM06",
        description="Read tool — read main.py",
        inputs=[
            ("text", "Read the file main.py"),
            ("expect", "import"),
            ("no_expect", "Detected simple filename"),
        ],
        sleep_after=20,
    ),
    Scenario(
        sid="SM07",
        description="Chinese input does not trigger filename detection",
        inputs=[
            ("text", "读main.py前3行"),
            ("no_expect", "Detected simple filename"),
            ("no_expect", "Fetching: https://"),
        ],
        sleep_after=20,
    ),
    Scenario(
        sid="SM08",
        description="Clean exit",
        inputs=[
            ("text", "/exit"),
        ],
        sleep_after=2,
    ),
]


# ── Tmux driver ──────────────────────────────────────────────────────

class TmuxDriver:
    """Real-terminal driver for NeoMind via tmux. NEVER sanitizes captured output."""

    def __init__(self, session: str = TMUX_SESSION, mode: str = "coding"):
        self.session = session
        self.mode = mode

    def _tmux(self, *args, check=True) -> subprocess.CompletedProcess:
        return subprocess.run(["tmux", *args], capture_output=True, text=True, check=check)

    def kill(self) -> None:
        self._tmux("kill-session", "-t", self.session, check=False)

    def start(self) -> None:
        self.kill()
        time.sleep(0.5)
        self._tmux("new-session", "-d", "-s", self.session, "-x", "120", "-y", "40")
        cmd = f"cd {WORKSPACE} && PYTHONPATH=. python3 main.py --mode {self.mode}"
        self._tmux("send-keys", "-t", self.session, cmd, "Enter")
        time.sleep(STARTUP_SLEEP)

    def send_text(self, text: str) -> None:
        # Use -l (literal) for the text, then a separate Enter
        self._tmux("send-keys", "-t", self.session, "-l", text)
        self._tmux("send-keys", "-t", self.session, "Enter")

    def send_key(self, key: str) -> None:
        # Special tmux key names: C-c, Tab, BSpace, Up, Enter, Escape, ...
        self._tmux("send-keys", "-t", self.session, key)

    def capture(self, lines: int = 50) -> str:
        """Return raw captured pane content. NO sanitization."""
        r = self._tmux("capture-pane", "-t", self.session, "-p", "-S", f"-{lines}")
        return r.stdout

    def is_alive(self) -> bool:
        r = self._tmux("has-session", "-t", self.session, check=False)
        return r.returncode == 0


# ── Test runner ──────────────────────────────────────────────────────

@dataclass
class Result:
    sid: str
    description: str
    verdict: str        # PASS / FAIL / WARN
    error_hits: List[str]
    capture_tail: str
    notes: str = ""


def check_capture(capture: str, scenario: Scenario) -> Tuple[str, List[str], str]:
    """Check capture against scenario expectations.
    Returns (verdict, error_pattern_hits, notes).
    Does NOT sanitize the capture before checking — that's the whole point."""

    # Check for any error pattern (in raw, uncleaned capture)
    error_hits = [p for p in ERROR_PATTERNS if p in capture]

    # Check for spinner residue at the very end
    last_line = capture.rstrip().split("\n")[-1] if capture.strip() else ""
    spinner_residue = any(c in last_line for c in SPINNER_CHARS)

    # Check expect / no_expect from scenario
    missing_expect = []
    leaked = []
    for kind, val in scenario.inputs:
        if kind == "expect" and val not in capture:
            missing_expect.append(val)
        elif kind == "no_expect" and val in capture:
            leaked.append(val)

    notes_parts = []
    if error_hits:
        notes_parts.append(f"errors: {error_hits}")
    if spinner_residue:
        notes_parts.append("spinner_residue")
    if missing_expect:
        notes_parts.append(f"missing: {missing_expect}")
    if leaked:
        notes_parts.append(f"leaked: {leaked}")

    if error_hits or leaked or missing_expect:
        verdict = "FAIL"
    elif spinner_residue:
        verdict = "WARN"
    else:
        verdict = "PASS"

    return verdict, error_hits, "; ".join(notes_parts) or "ok"


def run_scenario(driver: TmuxDriver, scenario: Scenario) -> Result:
    """Run one scenario against the driver."""
    if scenario.setup:
        scenario.setup()

    for kind, val in scenario.inputs:
        if kind == "text":
            driver.send_text(val)
        elif kind == "key":
            driver.send_key(val)
        elif kind == "sleep":
            time.sleep(float(val))
        # expect / no_expect are handled in check_capture, not here

    time.sleep(scenario.sleep_after)
    raw = driver.capture(lines=50)
    verdict, hits, notes = check_capture(raw, scenario)

    # Tail for the report
    tail = "\n".join(raw.rstrip().split("\n")[-15:])

    return Result(
        sid=scenario.sid,
        description=scenario.description,
        verdict=verdict,
        error_hits=hits,
        capture_tail=tail,
        notes=notes,
    )


# ── Plan loader ──────────────────────────────────────────────────────

def load_plan(name: str) -> List[Scenario]:
    if name == "smoke":
        return SMOKE_PLAN
    raise ValueError(
        f"Plan '{name}' not implemented in direct-invocation script. "
        f"Use the /skill selftest interface for the full plans documented in "
        f"tests/qa_archive/plans/."
    )


# ── Reporting ────────────────────────────────────────────────────────

def write_report(results: List[Result], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "results.md"

    pass_n = sum(1 for r in results if r.verdict == "PASS")
    fail_n = sum(1 for r in results if r.verdict == "FAIL")
    warn_n = sum(1 for r in results if r.verdict == "WARN")

    lines = [
        f"# NeoMind Self-Test Results",
        f"",
        f"- Run timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Method: tmux real-terminal driver (no sanitization)",
        f"- Total: {len(results)} scenarios",
        f"- PASS: {pass_n}",
        f"- FAIL: {fail_n}",
        f"- WARN: {warn_n}",
        f"",
        f"## Per-scenario results",
        f"",
    ]

    for r in results:
        lines += [
            f"### {r.sid}: {r.description}",
            f"- Verdict: **{r.verdict}**",
            f"- Notes: {r.notes}",
        ]
        if r.error_hits:
            lines.append(f"- Error patterns: {r.error_hits}")
        lines += [
            f"- Capture tail (last 15 lines):",
            f"```",
            r.capture_tail,
            f"```",
            f"",
        ]

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# ── Main ─────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="NeoMind self-test loop")
    ap.add_argument("--plan", default="smoke",
                    choices=["smoke", "short", "long", "boundary"],
                    help="Test plan to run (only 'smoke' implemented in direct mode)")
    ap.add_argument("--max-rounds", type=int, default=1,
                    help="Max retry rounds for failed scenarios")
    ap.add_argument("--mode", default="coding",
                    choices=["chat", "coding", "fin"],
                    help="NeoMind mode for the REPL")
    ap.add_argument("--keep-session", action="store_true",
                    help="Don't kill the tmux session at the end (for debugging)")
    args = ap.parse_args()

    # Check tmux is available
    if not shutil.which("tmux"):
        print("ERROR: tmux not found. The self-test loop requires a real terminal driver.", file=sys.stderr)
        sys.exit(2)

    plan = load_plan(args.plan)
    print(f"Loaded plan '{args.plan}': {len(plan)} scenarios")

    out_dir = OUTPUT_ROOT / time.strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output dir: {out_dir}")

    driver = TmuxDriver(mode=args.mode)
    print(f"Starting NeoMind in tmux session '{driver.session}' (mode={args.mode})...")
    driver.start()

    results: List[Result] = []
    try:
        for i, scenario in enumerate(plan, 1):
            print(f"[{i}/{len(plan)}] {scenario.sid}: {scenario.description} ... ", end="", flush=True)
            r = run_scenario(driver, scenario)
            results.append(r)
            print(r.verdict, "—", r.notes[:60])

            # Restart REPL periodically to avoid output bleed
            if i % RESTART_BATCH == 0 and i < len(plan):
                print(f"  (restarting REPL after {RESTART_BATCH} scenarios)")
                driver.start()
    finally:
        if not args.keep_session:
            driver.kill()

    report_path = write_report(results, out_dir)
    print(f"\nReport: {report_path}")

    pass_n = sum(1 for r in results if r.verdict == "PASS")
    fail_n = sum(1 for r in results if r.verdict == "FAIL")
    print(f"Summary: {pass_n} PASS, {fail_n} FAIL, {len(results) - pass_n - fail_n} WARN")
    sys.exit(0 if fail_n == 0 else 1)


if __name__ == "__main__":
    main()
