"""Real-terminal check for the three REPL fidelity fixes (2026-08-15).

Verifies in an actual iTerm2 window what unit tests can only assert about
logic — a user's session is where all three defects showed up:

  1. whitespace-only stream deltas were dropped, so `ls -F a b 2>/dev/null`
     reached the model's own history as `b2>/dev/null`
  2. DeepSeek's fullwidth `<｜｜DSML｜｜tool_call>` spelling was unrecognised,
     so the raw JSON payload was printed to the user as prose
  3. `Read(file_path=...)` was rejected with "Missing required parameter:
     'path'", costing a round trip on every file read

Run:  .venv/bin/python tests/integration/repl_fidelity_check.py

One window, scenarios in sequence, and the CLI is stopped at the end. The
window itself is left for the operator to close (⌘W) — batch-closing iTerm2
windows is a known way to lose unrelated work.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tests.integration.cli_tester_iterm2 import ITerm2CliTester, ITerm2Config  # noqa: E402

#: Derived at runtime rather than written down. A hardcoded default here
#: carried the operator's username into a public repository — the pre-commit
#: PII scan caught it, which is the whole reason that scan runs.
DUMP_DIR = Path(
    os.environ.get("REPL_FIDELITY_DUMPS")
    or (Path(tempfile.gettempdir()) / "neomind_repl_fidelity")
)

#: Deliberately NOT a permission test — auto-accept is valid here and keeps the
#: run unattended. Permission behaviour has its own scenarios that must launch
#: without it.
LAUNCH = (
    "NEOMIND_AUTO_ACCEPT=1 NEOMIND_MODE=coding "
    ".venv/bin/python main.py interactive --mode coding"
)

TURNS = [
    (
        "space_in_redirect",
        "Run exactly this shell command, unchanged, and show me its raw output: "
        "ls -F agent cli nosuchdir 2>/dev/null",
        120,
    ),
    (
        "read_by_file_path",
        "Use the Read tool to read the first 5 lines of pyproject.toml.",
        120,
    ),
    (
        "list_formatting",
        "List exactly three build tools, one per line, numbered 1. 2. 3., nothing else.",
        90,
    ),
]


#: Braille frames the spinner cycles through. A line containing one of these,
#: or the words below, is progress rather than an answer — and it ends in a
#: character the prompt regex happily matches, which is how a naive wait
#: declares a turn finished before it has started.
_SPINNER = set("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏")
_PROGRESS_WORDS = ("Thinking", "Thought for")


def _settled_tail(screen: str, n: int = 50) -> str:
    lines = [
        ln for ln in screen.splitlines()
        if not (set(ln) & _SPINNER) and not any(w in ln for w in _PROGRESS_WORDS)
    ]
    return "\n".join(lines[-n:])


async def wait_for_response(tester, max_wait: float) -> bool:
    """Wait for the turn to actually finish.

    `wait_for_prompt()` alone is not enough: the prompt from the *previous*
    turn is still on screen when the next input is sent, so it returns
    immediately and the recording captures nothing. This waits for the screen
    to change first, then for it to stop changing.
    """
    before = _settled_tail(await tester.capture(lines=500))
    deadline = asyncio.get_event_loop().time() + max_wait
    changed = False
    stable_since = None

    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.3)
        tail = _settled_tail(await tester.capture(lines=500))
        if not changed:
            if tail != before:
                changed = True
                stable_since = None
            continue
        if stable_since is None or tail != stable_since[0]:
            stable_since = (tail, asyncio.get_event_loop().time())
            continue
        if asyncio.get_event_loop().time() - stable_since[1] >= 3.0:
            return True
    return changed


async def main() -> int:
    DUMP_DIR.mkdir(parents=True, exist_ok=True)
    config = ITerm2Config(
        launch_cmd=LAUNCH,
        cwd=str(REPO),
        cols=120,
        rows=60,          # 40 loses content to scroll-off, 200 breaks prompt detection
        visible=True,
        boot_timeout_sec=40.0,
    )

    results = {}
    async with ITerm2CliTester(config) as tester:
        await tester.start_neomind()
        await tester.wait_for_prompt(timeout=60)

        for name, prompt, budget in TURNS:
            tester.start_recording()
            await tester.send(prompt)
            finished = await wait_for_response(tester, budget)
            if not finished:
                print(f"  !! {name}: no response detected within {budget}s")
            screen = tester.stop_recording()
            path = DUMP_DIR / f"{name}.txt"
            path.write_text(screen, encoding="utf-8")
            results[name] = str(path)
            print(f"  captured {name} -> {path} ({len(screen)} chars)")

        # Stop the CLI rather than leaving a live agent in an unattended window.
        await tester.send("/quit")
        await asyncio.sleep(3)

    (DUMP_DIR / "index.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\n  dumps: {DUMP_DIR}")
    print("  the iTerm2 window is left open on purpose — close it with ⌘W")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
