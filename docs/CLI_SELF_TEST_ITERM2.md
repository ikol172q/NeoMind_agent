# CLI Self-Test — iTerm2 Driver (100% fidelity)

**Status:** Driver code landed in `tests/integration/cli_tester_iterm2.py`.
Requires a one-time iTerm2 preference change to become live.

**Companion driver:** `agent/skills/shared/selftest/SKILL.md` (tmux-based, ~95% fidelity)
**Design doc:** `plans/TODO_zero_downtime_self_evolution.md` Part 2
**Telegram counterpart:** `tests/integration/telegram_tester.py`

## Why a second CLI driver

The existing tmux driver covers most of the CLI surface but cannot
reach these code paths:

| Gap | Symptom if buggy | tmux | iTerm2 |
|---|---|---|---|
| Chinese IME composition | cursor jumps mid-type | invisible | catches |
| Bracketed paste mode | multi-line paste mangled | invisible | catches |
| Real SIGWINCH on resize | status bar overflow after resize | invisible | catches |
| Terminal focus events | focus-in/out triggers stale state | invisible | catches |
| Emoji width / truecolor / ligatures | rendering glitches | tmux's own render | real iTerm2 |
| macOS keyboard shortcuts (Cmd+K etc.) | iTerm2 intercepts swallowed | invisible | catches |
| OSC 52 clipboard | paste/copy from CLI silently fails | invisible | catches |

For everything else the tmux driver is faster (~5s per scenario vs
~10-15s on iTerm2) so `selftest` still defaults to tmux. Use the
iTerm2 driver when a scenario specifically targets one of the gaps
above, and for the final-gate validator that should match real user
behavior exactly.

## One-time setup

### 1. Enable iTerm2 Python API

1. Open **iTerm2 → Preferences → General → Magic**.
2. Tick **Enable Python API**.
3. If prompted, allow access — iTerm2 opens a listener on
   `127.0.0.1:1912`.

No restart required — the API socket comes up immediately.

### 2. Verify the venv has the client library

```
cd /Users/user/Desktop/NeoMind_agent
.venv/bin/pip show iterm2 | head -3
```

Should show `iterm2 2.x`. If not:

```
.venv/bin/pip install iterm2
```

### 3. Smoke test the connection

```
cd /Users/user/Desktop/NeoMind_agent
.venv/bin/python tests/integration/cli_tester_iterm2.py
```

This opens an iTerm2 window, runs `.venv/bin/python -m agent`,
waits for the CLI prompt, sends `/status`, captures the rendered
screen, and closes.

Expected output (exit 0):

```
[iterm2-smoke] connected to iTerm2 app=<iterm2.app.App object ...>
[iterm2-smoke] capture after /status:
...
mode: fin | model: kimi-k2.5 | router: ...
```

If you see `ITerm2APIUnavailable: iTerm2 Python API socket not
reachable`, re-check step 1 — the preference is off. The port is
only opened when the pref is ticked.

## Using the driver programmatically

Minimal example (`tests/test_iterm2_smoke.py` would wrap this):

```python
import asyncio
from tests.integration.cli_tester_iterm2 import (
    ITerm2CliTester, ITerm2APIUnavailable, ITerm2Config,
)

async def main():
    cfg = ITerm2Config(cols=120, rows=40, visible=True)
    async with ITerm2CliTester(cfg) as tester:
        await tester.start_neomind()
        assert await tester.wait_for_prompt(timeout=20)

        # A normal command
        await tester.send("/mode fin")
        await tester.wait_for("fin", timeout=10)

        # Chinese IME composition (pastes precomposed text;
        # triggers the IME pipeline in prompt_toolkit)
        await tester.send("苹果今天股价多少")
        await tester.wait_for("AAPL", timeout=90)

        # Bracketed-paste multi-line Python
        code = "def hello():\n    print('hi')\nhello()\n"
        await tester.paste(code)
        await tester.send("")  # trigger prompt re-eval
        await tester.wait_for("hi", timeout=15)

        # Real resize event
        await tester.resize(cols=80, rows=24)
        await asyncio.sleep(2)
        screen = await tester.capture()
        print(screen)

        # Real ^C
        await tester.send("sleep 30", enter=True)
        await asyncio.sleep(1)
        await tester.ctrl_c()

asyncio.run(main())
```

## Fallback to tmux when API unavailable

The driver constructor raises `ITerm2APIUnavailable` with a clear
remediation message. Callers should wrap and fall back:

```python
try:
    async with ITerm2CliTester() as tester:
        await run_scenarios_iterm2(tester)
except ITerm2APIUnavailable as e:
    print(f"⚠️  iTerm2 API unavailable ({e}), falling back to tmux driver")
    await run_scenarios_tmux()
```

This way CI / unattended runs never block on a missing preference.

## Scenario library

A future commit will add
`tests/qa_archive/plans/2026-04-10_cli_iterm2_scenarios.py` holding
the 8 gap-specific scenarios listed in the table above, formatted
like the Telegram scenario file. For now the driver is the
reusable primitive — callers compose their own scenarios.

## Limitations

- **Cannot run in Docker** — the iTerm2 API socket is host-local.
  Tests that need iTerm2 fidelity must run from the host shell, not
  inside `neomind-telegram`.
- **Serial only** — iTerm2 API calls are not thread-safe across
  multiple sessions in the same Python process. For parallel CLI
  scenario runs, spawn multiple Python processes each with their
  own ITerm2CliTester.
- **Windows/Linux untested** — iTerm2 is macOS-only. On other
  platforms `from tests.integration.cli_tester_iterm2 import ...`
  will still import (no macOS API calls until `__aenter__`), but
  actual connection will fail with `ITerm2APIUnavailable`.
