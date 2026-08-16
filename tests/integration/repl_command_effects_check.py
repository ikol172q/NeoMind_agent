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

        # 3. Session-scoped config: /permissions must still work, and the
        #    custom system prompt / mode must survive the fork.
        tester.start_recording()
        await tester.send("/permissions plan")
        await poll(tester, 6)
        screen = tester.stop_recording()
        (DUMP_DIR / "permissions.txt").write_text(screen, encoding="utf-8")
        captured["permissions"] = str(DUMP_DIR / "permissions.txt")

        # 4. Phase 6A task 2: the 279-line legacy chain is gone. These must
        #    still work — three that were shadowed by the registry and are now
        #    only defined there, and three the frontend owns and re-declared.
        for name, probe in (
            ("history", "/history"),
            ("skills", "/skills"),
            ("config", "/config"),
            ("evidence", "/evidence"),
            ("freeze", "/freeze"),
            ("expand", "/expand"),
        ):
            tester.start_recording()
            await tester.send(probe)
            await poll(tester, 5)
            screen = tester.stop_recording()
            (DUMP_DIR / f"cmd_{name}.txt").write_text(screen, encoding="utf-8")
            captured[f"cmd_{name}"] = str(DUMP_DIR / f"cmd_{name}.txt")

        # 5. Behaviour restored by the consolidation. These were lost when the
        #    registry began answering first and its copy did less than the
        #    frontend's; nothing reported it because the only tests covering
        #    them drove the unreachable copy.
        for name, probe in (
            ("perm_toggle", "/permissions"),
            ("debug_dump", "/debug dump"),
        ):
            tester.start_recording()
            await tester.send(probe)
            await poll(tester, 5)
            screen = tester.stop_recording()
            (DUMP_DIR / f"cmd_{name}.txt").write_text(screen, encoding="utf-8")
            captured[f"cmd_{name}"] = str(DUMP_DIR / f"cmd_{name}.txt")

        # 5b. The mode gate only means anything in a mode where the command
        #     is unavailable. Probing /run from coding — where it *is*
        #     available — would have proved nothing, which is what the first
        #     version of this probe did.
        tester.start_recording()
        await tester.send("/mode chat")
        await poll(tester, 6)
        await tester.send("/run echo hi")
        await poll(tester, 6)
        screen = tester.stop_recording()
        (DUMP_DIR / "cmd_mode_gate.txt").write_text(screen, encoding="utf-8")
        captured["cmd_mode_gate"] = str(DUMP_DIR / "cmd_mode_gate.txt")

        # 5c. Phase 6B task 1: the fleet's asyncio loop moved out of this
        #     class into `fleet.driver.FleetDriver`. /fleet start is the only
        #     thing that exercises it, and a broken driver looks like a hung
        #     terminal rather than an error.
        tester.start_recording()
        await tester.send("/fleet status")
        await poll(tester, 6)
        await tester.send("/fleet start coding-smoke")
        await poll(tester, 20)
        screen = tester.stop_recording()
        (DUMP_DIR / "cmd_fleet.txt").write_text(screen, encoding="utf-8")
        captured["cmd_fleet"] = str(DUMP_DIR / "cmd_fleet.txt")

        # 6. The sentinel must not be visible anywhere — if the effect were
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

        perms = Evidence("permissions", read(captured["permissions"]))
        perms.witness("/permissions plan").contains("plan")

        # Each command must produce something and must not report itself
        # unknown — "Unknown command" is what a lost declaration looks like.
        probes = []
        for name in ("history", "skills", "config", "evidence", "freeze", "expand"):
            ev = Evidence(f"cmd_{name}", read(captured[f"cmd_{name}"]))
            ev.witness(f"/{name}").absent("Unknown command", "not available", "Traceback")
            probes.append(ev)

        toggle = Evidence("perm_toggle", read(captured["cmd_perm_toggle"]))
        toggle.witness("/permissions").contains("Permission mode:")
        probes.append(toggle)

        dump = Evidence("debug_dump", read(captured["cmd_debug_dump"]))
        dump.witness("/debug dump").absent("Unknown command", "Traceback")
        probes.append(dump)

        gate = Evidence("mode_gate", read(captured["cmd_mode_gate"]))
        gate.witness("/run echo hi").contains("not available in").absent("Traceback")
        probes.append(gate)

        fleet = Evidence("fleet", read(captured["cmd_fleet"]))
        # `absent` on a phrase an *earlier* probe printed will fail: the
        # recorder accumulates every line that was ever on screen, so the
        # scrollback of previous turns is part of this capture. Only strings
        # that can mean nothing but "this step broke" belong here.
        fleet.witness("/fleet start coding-smoke").contains(
            "started with"
        ).absent("Traceback", "Command failed")
        probes.append(fleet)

        exited = Evidence("exit", read(captured["exit"]))
        exited.witness("/exit").contains("Goodbye").absent("__EXIT__")
    except AssertionError as failure:
        print(f"\n  !! {type(failure).__name__}: {failure}")
        return 1

    report = collect([mode, after, perms, *probes, exited])
    (DUMP_DIR / "index.json").write_text(
        json.dumps({"dumps": captured, "evidence": report}, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\n  dumps: {DUMP_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
