"""The two Phase 4 gate items the mode sweep did not cover.

**Interruption.** Ctrl+C during a long generation has to stop the turn and
leave the REPL usable — not kill the process, not wedge it, and not leave the
provider stream open. A turn that "stops" but cannot be followed by another
turn is not interrupted, it is broken, so this always sends a second prompt
afterwards and requires an answer.

**Resume.** `--resume` has to reopen a session with its history intact. The
session path builds a fresh AgentSession per turn seeded from the agent's
history, so if resume loads history into the agent, the model must be able to
recall what was said before the restart.

Run:  .venv/bin/python tests/integration/repl_interrupt_resume_check.py
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
    os.environ.get("REPL_INTERRUPT_DUMPS")
    or (Path(tempfile.gettempdir()) / "neomind_interrupt_resume")
)

LAUNCH = (
    "NEOMIND_REPL=session_v1 NEOMIND_MODE=coding NEOMIND_AUTO_ACCEPT=1 "
    ".venv/bin/python main.py interactive --mode coding"
)

MARKER = "RESUME_MARKER_KIWI_42"


def config(launch: str) -> ITerm2Config:
    return ITerm2Config(
        launch_cmd=launch,
        cwd=str(REPO),
        cols=120,
        rows=60,
        visible=True,
        boot_timeout_sec=40.0,
    )


async def interrupt_scenario(dumps):
    async with ITerm2CliTester(config(LAUNCH)) as tester:
        await tester.start_neomind()
        await tester.wait_for_prompt(timeout=60)

        tester.start_recording()
        await tester.send("Write a 900 word essay about the history of the sextant.")
        await asyncio.sleep(6)          # let it get well into the stream
        await tester.ctrl_c()
        await asyncio.sleep(4)

        # The real test of an interrupt: can the session still take work?
        await tester.send("Reply with exactly: STILL_ALIVE")
        await wait_for_response(tester, 90)
        screen = tester.stop_recording()

        path = DUMP_DIR / "interrupt.txt"
        path.write_text(screen, encoding="utf-8")
        dumps["interrupt"] = str(path)
        print(f"  captured interrupt ({len(screen)} chars)")

        await tester.send("/quit")
        await asyncio.sleep(3)


def _latest_session_id():
    """Newest id under ~/.neomind/sessions.

    Sessions are stored automatically under a timestamp id; `/save <name>`
    is a different feature that exports a markdown transcript into the
    working directory, and pairing the two — as the first version of this
    test did — reports "Session not found" for reasons that have nothing to
    do with resume.
    """
    import glob

    files = sorted(
        glob.glob(os.path.expanduser("~/.neomind/sessions/*.json")),
        key=os.path.getmtime,
    )
    return Path(files[-1]).stem if files else None


async def resume_scenario(dumps):
    async with ITerm2CliTester(config(LAUNCH)) as tester:
        await tester.start_neomind()
        await tester.wait_for_prompt(timeout=60)
        tester.start_recording()
        await tester.send(f"Remember this exact token for later: {MARKER}. Just say OK.")
        await wait_for_response(tester, 90)
        screen = tester.stop_recording()
        (DUMP_DIR / "resume_before.txt").write_text(screen, encoding="utf-8")
        dumps["resume_before"] = str(DUMP_DIR / "resume_before.txt")
        print(f"  captured resume_before ({len(screen)} chars)")
        await tester.send("/quit")
        await asyncio.sleep(3)

    session_id = _latest_session_id()
    if not session_id:
        print("  !! no session file was written; resume cannot be tested")
        return
    print(f"  resuming {session_id}")
    resumed = LAUNCH + f" --resume {session_id}"
    async with ITerm2CliTester(config(resumed)) as tester:
        await tester.start_neomind()
        await tester.wait_for_prompt(timeout=60)
        tester.start_recording()
        await tester.send("What exact token did I ask you to remember? Reply with just the token.")
        await wait_for_response(tester, 90)
        screen = tester.stop_recording()
        (DUMP_DIR / "resume_after.txt").write_text(screen, encoding="utf-8")
        dumps["resume_after"] = str(DUMP_DIR / "resume_after.txt")
        print(f"  captured resume_after ({len(screen)} chars)")
        await tester.send("/quit")
        await asyncio.sleep(3)


async def main() -> int:
    DUMP_DIR.mkdir(parents=True, exist_ok=True)
    dumps = {}
    await interrupt_scenario(dumps)
    await resume_scenario(dumps)
    (DUMP_DIR / "index.json").write_text(json.dumps(dumps, indent=2), encoding="utf-8")
    print(f"\n  dumps: {DUMP_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
