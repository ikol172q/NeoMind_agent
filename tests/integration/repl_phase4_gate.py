"""Phase 4 done gate — the REPL on AgentSession, across modes, for real.

The plan's gate, item by item:

  * permission deny / allow-once behaviour in a real terminal, in **coding and
    fin** — a green coding run says nothing about fin, which has its own
    dispatch
  * **chat** separately shown to run no tool loop, because a green chat session
    is not evidence about tools or permissions
  * streaming, thinking toggle, model/mode switch, commands, tool results,
    interruption, and exit, seen in a real iTerm2 window

Permission scenarios launch **without** NEOMIND_AUTO_ACCEPT and answer the
prompt as a user would. Everything else launches with it, because an
unattended run that silently bypasses the gate is not evidence about the gate.

Run:  .venv/bin/python tests/integration/repl_phase4_gate.py
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
    os.environ.get("REPL_GATE_DUMPS")
    or (Path(tempfile.gettempdir()) / "neomind_phase4_gate")
)

SESSION = "NEOMIND_REPL=session_v1"


def launch(mode: str, *, auto_accept: bool) -> str:
    env = f"{SESSION} NEOMIND_MODE={mode}"
    if auto_accept:
        env += " NEOMIND_AUTO_ACCEPT=1"
    return f"{env} .venv/bin/python main.py interactive --mode {mode}"


# (name, input, seconds, answer_permission_with)
CODING_AUTO = [
    ("streaming", "Count from 1 to 5, one number per line, nothing else.", 90, None),
    ("tool_result", "Use Read on pyproject.toml and quote line 1 exactly.", 150, None),
    ("cmd_help", "/help", 45, None),
    ("thinking_toggle", "/think", 45, None),
    ("mode_switch_nl", "换成 fin", 60, None),
]

CODING_ASK = [
    ("permission_allow", "Run the shell command: echo GATE_ALLOW_OK", 150, "y"),
    ("permission_deny", "Run the shell command: echo GATE_DENY_SHOULD_NOT_RUN", 150, "n"),
]

#: fin declines shell work by persona, so asking it to `echo` proved nothing
#: about permissions — it answered in prose and no dialog appeared. Ask for
#: something fin will actually reach for a tool to do.
FIN_ASK = [
    ("fin_permission_allow",
     "Use the Bash tool to run `date +%Y` so we know the current year. Use the tool, do not guess.",
     180, "y"),
    ("fin_mode_switch", "换成 coding", 60, None),
]

CHAT_AUTO = [
    ("chat_no_tools", "What is 2+2? Answer with just the number.", 90, None),
    (
        "chat_tool_request_declined",
        "Use the Bash tool to run: echo CHAT_SHOULD_NOT_RUN_TOOLS",
        120,
        None,
    ),
]


async def run_block(mode: str, turns, tag: str, *, auto_accept: bool):
    config = ITerm2Config(
        launch_cmd=launch(mode, auto_accept=auto_accept),
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

        for name, text, budget, answer in turns:
            tester.start_recording()
            await tester.send(text)

            if answer is not None:
                for _ in range(int(budget / 0.5)):
                    await asyncio.sleep(0.5)
                    if "Allow?" in await tester.capture(lines=200):
                        await tester.send(answer)
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
    results.update(await run_block("coding", CODING_AUTO, "coding_auto", auto_accept=True))
    results.update(await run_block("coding", CODING_ASK, "coding_ask", auto_accept=False))
    results.update(await run_block("fin", FIN_ASK, "fin_ask", auto_accept=False))
    results.update(await run_block("chat", CHAT_AUTO, "chat_auto", auto_accept=True))
    (DUMP_DIR / "index.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\n  dumps: {DUMP_DIR}")
    print("  windows left open on purpose — close with ⌘W")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
