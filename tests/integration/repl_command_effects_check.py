"""Phase 6A gate — command effects, in a real terminal.

`/exit` and `/mode` used to signal the frontend by writing sentinel strings
into the display text (`"__EXIT__"`, `"__MODE_SWITCH__coding"`). They now
return typed effects, which means the dispatch site in `_handle_local_command`
was rewritten — and that site is pure frontend control flow, so a unit test
proving the effect exists says nothing about whether the REPL still quits.

Two things have to be true and only a terminal can show both:

  * `/mode coding` actually switches, redraws the welcome banner, and the
    status line reports the new mode — not just that a `ModeSwitchRequested`
    was returned.
  * `/exit` prints "Goodbye!" and the process ends, rather than hanging with
    the prompt still live.

Run:  .venv/bin/python tests/integration/repl_command_effects_check.py
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
from tests.integration.evidence import Evidence, collect  # noqa: E402
from tests.integration.repl_fidelity_check import wait_for_response  # noqa: E402

DUMP_DIR = Path(
    os.environ.get("REPL_EFFECTS_DUMPS")
    or (Path(tempfile.gettempdir()) / "neomind_repl_effects")
)

LAUNCH = (
    "NEOMIND_MODE=chat NEOMIND_AUTO_ACCEPT=1 "
    ".venv/bin/python main.py interactive --mode chat"
)


async def poll(tester, seconds: float, interval: float = 0.3) -> None:
    """Keep capturing while we wait.

    The recorder accumulates whatever `capture()` sees; a bare `sleep` polls
    nothing, so the dump comes back empty and every "the sentinel is not on
    screen" assertion passes vacuously. That is not a weaker test, it is a
    test of nothing.
    """
    for _ in range(int(seconds / interval)):
        await tester.capture(lines=200)
        await asyncio.sleep(interval)


def read(path) -> str:
    return Path(path).read_text(encoding="utf-8", errors="ignore")


async def main() -> int:
    DUMP_DIR.mkdir(parents=True, exist_ok=True)
    config = ITerm2Config(
        launch_cmd=LAUNCH,
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

        # 1. A mode switch has to change the session, not just return a value.
        tester.start_recording()
        await tester.send("/mode coding")
        await poll(tester, 8)
        screen = tester.stop_recording()
        (DUMP_DIR / "mode_switch.txt").write_text(screen, encoding="utf-8")
        captured["mode_switch"] = str(DUMP_DIR / "mode_switch.txt")

        # 2. And the switch has to stick: the next turn runs in the new mode.
        tester.start_recording()
        await tester.send("Reply with exactly: MODE_EFFECT_OK")
        await wait_for_response(tester, 90)
        screen = tester.stop_recording()
        (DUMP_DIR / "after_switch.txt").write_text(screen, encoding="utf-8")
        captured["after_switch"] = str(DUMP_DIR / "after_switch.txt")

        # 3. The sentinel must not be visible anywhere — if the effect were
        #    ignored, the old code path would print the raw text instead.
        tester.start_recording()
        await tester.send("/exit")
        await poll(tester, 8)
        screen = tester.stop_recording()
        (DUMP_DIR / "exit.txt").write_text(screen, encoding="utf-8")
        captured["exit"] = str(DUMP_DIR / "exit.txt")

    # Every claim below goes through Evidence, which refuses to assert
    # anything until a witness proves the capture shows the thing under test.
    # The first version of this gate reported three passes from two empty
    # dumps; that is now impossible rather than merely documented.
    try:
        mode = Evidence("mode_switch", read(captured["mode_switch"]))
        mode.witness("/mode coding").contains("coding mode").absent("__MODE_SWITCH__")

        after = Evidence("after_switch", read(captured["after_switch"]))
        after.witness("MODE_EFFECT_OK").absent("__MODE_SWITCH__", "__EXIT__")

        exited = Evidence("exit", read(captured["exit"]))
        exited.witness("/exit").contains("Goodbye").absent("__EXIT__")
    except AssertionError as failure:
        print(f"\n  !! {type(failure).__name__}: {failure}")
        return 1

    report = collect([mode, after, exited])
    (DUMP_DIR / "index.json").write_text(
        json.dumps({"dumps": captured, "evidence": report}, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\n  dumps: {DUMP_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
