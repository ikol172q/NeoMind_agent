"""Phase 4 gate — the REPL running on AgentSession, in a real terminal.

Launches with NEOMIND_REPL=session_v1 so the turn goes through
AgentSession/ToolExecutor instead of stream_response() plus the CLI's own
tool loop. What has to survive is not "it answers" but how it looks: the
spinner, the code-fence filter, tool summaries, and the permission dialog.

Two launches on purpose. Permission behaviour is tested without
NEOMIND_AUTO_ACCEPT and the prompt is answered as a user would; everything
else runs with it, because an unattended run that silently bypasses the gate
is not evidence about the gate.
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
from tests.integration.repl_fidelity_check import wait_for_response  # noqa: E402

DUMP_DIR = Path(
    os.environ.get("REPL_SESSION_DUMPS")
    or (Path(tempfile.gettempdir()) / "neomind_repl_session")
)

BASE_ENV = "NEOMIND_REPL=session_v1 NEOMIND_MODE=coding"
LAUNCH_AUTO = f"{BASE_ENV} NEOMIND_AUTO_ACCEPT=1 .venv/bin/python main.py interactive --mode coding"
LAUNCH_ASK = f"{BASE_ENV} .venv/bin/python main.py interactive --mode coding"


async def run_scenarios(launch_cmd, turns, tag):
    config = ITerm2Config(
        launch_cmd=launch_cmd,
        cwd=str(REPO),
        cols=120,
        rows=60,
        visible=True,
        boot_timeout_sec=40.0,
    )
    captured = {}
    async with ITerm2CliTester(config) as tester:
        await tester.start_neomind()
        await tester.wait_for_prompt(timeout=60)
        for name, text, budget in turns:
            tester.start_recording()
            await tester.send(text)

            if tag == "ask":
                # Answer the dialog as a user would. Stopping at the prompt
                # shows only that it renders; the gate is whether an approval
                # actually reaches the executor and the command runs.
                for _ in range(int(budget / 0.5)):
                    await asyncio.sleep(0.5)
                    if "Allow?" in await tester.capture(lines=200):
                        await tester.send("y")
                        break

            if not await wait_for_response(tester, budget):
                print(f"  !! {tag}/{name}: no response within {budget}s")
            screen = tester.stop_recording()
            path = DUMP_DIR / f"{tag}_{name}.txt"
            path.write_text(screen, encoding="utf-8")
            captured[f"{tag}_{name}"] = str(path)
            print(f"  captured {tag}/{name} ({len(screen)} chars)")
        await tester.send("/quit")
        await asyncio.sleep(3)
    return captured


async def main() -> int:
    DUMP_DIR.mkdir(parents=True, exist_ok=True)
    results = {}

    results.update(await run_scenarios(LAUNCH_AUTO, [
        ("plain_text", "Reply with exactly: SESSION_PATH_OK", 90),
        ("tool_round", "Use the Read tool on pyproject.toml and quote its first line.", 150),
        ("code_fence", "Show me a hello world in Python, in a code block.", 120),
    ], "auto"))

    # No auto-accept: the dialog must appear and be answered by hand.
    results.update(await run_scenarios(LAUNCH_ASK, [
        ("permission_prompt", "Run the shell command: echo PERMISSION_PATH_OK", 150),
    ], "ask"))

    (DUMP_DIR / "index.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\n  dumps: {DUMP_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
