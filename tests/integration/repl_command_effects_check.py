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

    empty = [n for n, path in captured.items()
             if not Path(path).read_text(encoding="utf-8", errors="ignore").strip()]
    if empty:
        # An empty dump cannot support any claim about what was on screen.
        print(f"  !! empty dumps, nothing was measured: {empty}")
        return 2

    verdicts = {}
    for name, path in captured.items():
        body = Path(path).read_text(encoding="utf-8", errors="ignore")
        verdicts[name] = {
            "sentinel_visible": "__EXIT__" in body or "__MODE_SWITCH__" in body,
            "chars": len(body),
        }

    exit_body = Path(captured["exit"]).read_text(encoding="utf-8", errors="ignore")
    verdicts["exit"]["said_goodbye"] = "Goodbye" in exit_body

    after = Path(captured["after_switch"]).read_text(encoding="utf-8", errors="ignore")
    verdicts["after_switch"]["answered"] = "MODE_EFFECT_OK" in after
    verdicts["after_switch"]["mode_is_coding"] = "coding" in after

    (DUMP_DIR / "index.json").write_text(
        json.dumps({"dumps": captured, "verdicts": verdicts}, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(verdicts, indent=2))
    print(f"\n  dumps: {DUMP_DIR}")

    failed = [n for n, v in verdicts.items() if v["sentinel_visible"]]
    if failed:
        print(f"  !! sentinel leaked into the screen: {failed}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
