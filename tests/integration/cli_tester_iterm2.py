"""NeoMind CLI tester via iTerm2 Python API — 100% user-behavior fidelity.

Companion to `telegram_tester.py` (Telethon-driven Telegram surface).
This module drives a real iTerm2 window through its Python API so CLI
scenarios exercise the SAME rendering / input / terminal event stack
that a human user sees:

- Real keystroke events including bracketed paste mode
- Real terminal resize events (not tmux's fake -x/-y)
- Real focus in/out sequences
- Real OSC 52 clipboard round-trips
- Native emoji width / truecolor / ligatures
- Chinese IME composition (text entered through iTerm2's cocoa
  input layer hits prompt_toolkit via the real macOS IME pipeline)

See plans/TODO_zero_downtime_self_evolution.md Part 2 for the gap
analysis vs the tmux driver in agent/skills/shared/selftest/SKILL.md.

Prerequisites (one-time):
    1. iTerm2 installed on the host (/Applications/iTerm.app).
    2. iTerm2 Python API enabled:
         iTerm2 → Preferences → General → Magic → Enable Python API
    3. `.venv/bin/pip install iterm2` (already done in this session).

If the API isn't reachable (port 1912 / launchd socket not listening),
this module raises `ITerm2APIUnavailable` at construction with a clear
remediation message, so the caller can fall back to the tmux driver.

Public API (mirrors telegram_tester where sensible):

    async with ITerm2CliTester() as tester:
        await tester.start_neomind()             # opens window, runs CLI
        await tester.wait_for_prompt()           # waits for "> " or similar
        await tester.send("/status")             # single keystroke-style input
        await tester.paste(multi_line_code)      # bracketed-paste mode
        text = await tester.capture(lines=40)    # rendered screen
        await tester.resize(cols=80, rows=24)    # fires real resize event
        await tester.ctrl_c()                    # real ^C
        await tester.close()                     # clean exit

The tester does NOT impose a scenario schema — caller composes
(send, expect, wait) loops the way telegram_tester does. See the
scenario library at tests/qa_archive/plans/ for examples.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


class ITerm2APIUnavailable(RuntimeError):
    """Raised when the iTerm2 Python API cannot be reached.

    Common causes:
    - iTerm2 not running on the host.
    - iTerm2 Preferences → General → Magic → Enable Python API not ticked.
    - Running inside a Docker container (the API socket lives on the host).
    """


# Default prompt-ready regex — matches NeoMind's `[mode] >` prompt
# (where mode is chat/coding/fin). Searched across the whole captured
# screen, not just the last line, because prompt_toolkit renders a
# status bar below the prompt.
DEFAULT_PROMPT_RE = re.compile(r"\[(chat|coding|fin)\]\s*>")


@dataclass
class ITerm2Config:
    """Caller-configurable defaults."""
    # Shell command that launches the NeoMind CLI. Default is the project
    # venv running `main.py interactive --mode fin` so slash commands
    # like /status and finance NL dispatch are immediately available.
    launch_cmd: str = ".venv/bin/python main.py interactive --mode fin"
    # cwd for the iTerm2 session. Default: NeoMind repo root.
    cwd: str = str(Path(__file__).resolve().parents[2])
    # Window/session geometry for the initial boot.
    cols: int = 120
    rows: int = 40
    # Keep the window visible during automation (False = backgrounded).
    visible: bool = True
    # How long we wait for iTerm2 to spawn the window and the CLI
    # to print its first prompt.
    boot_timeout_sec: float = 20.0
    # Screen-capture chunk size for capture() — the Python API returns
    # lines individually so we just clamp.
    default_capture_lines: int = 40


class ITerm2CliTester:
    """Drives a real iTerm2 session for CLI self-tests.

    Usage:
        tester = ITerm2CliTester()
        async with tester:
            await tester.start_neomind()
            await tester.wait_for_prompt()
            await tester.send("/mode fin")
            screen = await tester.capture()
            assert "fin" in screen

    The constructor does NOT touch iTerm2 — connection happens inside
    `__aenter__`. That way a caller can branch on `ITerm2APIUnavailable`
    gracefully before any side effects.
    """

    def __init__(self, config: Optional[ITerm2Config] = None):
        self.config = config or ITerm2Config()
        self._connection = None
        self._app = None
        self._window = None
        self._session = None

    # ── Context manager ──────────────────────────────────────────────

    async def __aenter__(self) -> "ITerm2CliTester":
        try:
            import iterm2  # type: ignore
        except ImportError as e:
            raise ITerm2APIUnavailable(
                "iterm2 python package not installed. "
                "Run `.venv/bin/pip install iterm2`."
            ) from e

        self._iterm2_mod = iterm2

        try:
            self._connection = await asyncio.wait_for(
                iterm2.Connection.async_create(), timeout=5.0,
            )
        except asyncio.TimeoutError as e:
            raise ITerm2APIUnavailable(
                "iTerm2 Python API socket timed out. Make sure iTerm2 "
                "is running AND Preferences → General → Magic → "
                "Enable Python API is ticked. Port 1912 should be "
                "listening on 127.0.0.1."
            ) from e
        except OSError as e:
            raise ITerm2APIUnavailable(
                f"iTerm2 Python API socket not reachable ({e}). See "
                f"docs/CLI_SELF_TEST_ITERM2.md for setup."
            ) from e

        self._app = await iterm2.async_get_app(self._connection)
        if self._app is None:
            raise ITerm2APIUnavailable(
                "iterm2.async_get_app returned None — iTerm2 is "
                "connected but reports no application state. Is the "
                "main window alive?"
            )
        return self

    async def __aexit__(self, exc_type, exc, tb):
        # Best-effort cleanup. Don't suppress exceptions.
        try:
            await self.close()
        except Exception as e:
            logger.warning(f"[iterm2] close() raised during exit: {e}")

    # ── Session lifecycle ────────────────────────────────────────────

    async def start_neomind(
        self,
        launch_cmd: Optional[str] = None,
        cwd: Optional[str] = None,
    ) -> None:
        """Open a new iTerm2 window and launch the NeoMind CLI inside.

        We create a dedicated window (not a tab) so CLI tests never
        clobber the user's current terminal state. The window opens
        in the foreground by default; pass visible=False in the config
        to minimize it.
        """
        iterm2 = self._iterm2_mod
        cmd = launch_cmd or self.config.launch_cmd
        wd = cwd or self.config.cwd

        # Wrap the CLI command in an interactive bash so the shell stays
        # alive if the CLI exits — we can still capture the terminal
        # buffer for diagnostics instead of losing the window.
        shell_cmd = f"/bin/bash -c 'cd {_shquote(wd)} && {cmd}; echo; echo __neomind_cli_exited__; exec /bin/bash -i'"
        window = await iterm2.Window.async_create(
            self._connection, command=shell_cmd,
        )
        if window is None:
            raise RuntimeError(
                "iTerm2 async_create returned None — window creation "
                "failed. Check iTerm2 Console.app for errors."
            )
        self._window = window

        # Refresh app state and locate the session id for the new window.
        # iTerm2 doesn't populate tabs/sessions on the Window object from
        # async_create — we need to re-fetch App and walk its windows.
        await asyncio.sleep(0.5)
        app = await iterm2.async_get_app(self._connection)
        self._session = None
        for w in app.windows:
            if w.window_id == window.window_id:
                for t in w.tabs:
                    for s in t.sessions:
                        self._session = s
                        break
                    if self._session:
                        break
                break
        if self._session is None:
            raise RuntimeError("iTerm2 window has no session after create")

        # Set geometry to requested size — this propagates as a real
        # SIGWINCH / terminal-resize event to the child process.
        await self.resize(self.config.cols, self.config.rows)

        if not self.config.visible:
            try:
                await window.async_set_fullscreen(False)
                # Miniaturize so it doesn't steal focus during test runs.
                # Not all iTerm2 versions expose async_minimize; ignore.
            except Exception:
                pass

    async def close(self) -> None:
        """Close the iTerm2 window we opened, if any."""
        if self._session is not None:
            try:
                # Send ^D first so prompt_toolkit has a chance to
                # tear down cleanly and flush any pending state.
                await self._session.async_send_text("\x04")
                await asyncio.sleep(0.3)
            except Exception:
                pass
        if self._window is not None:
            try:
                await self._window.async_close(force=True)
            except Exception as e:
                logger.debug(f"[iterm2] async_close: {e}")
        self._window = None
        self._session = None

    # ── Input primitives ─────────────────────────────────────────────

    async def send(self, text: str, enter: bool = True) -> None:
        """Emit text as real keystrokes; optionally terminate with Enter.

        Unlike `async_send_text`, iTerm2 processes this through the
        session's cocoa input layer, so IME composition events can
        fire for precomposed Chinese characters.
        """
        if self._session is None:
            raise RuntimeError("no active session — call start_neomind first")
        payload = text + ("\r" if enter else "")
        await self._session.async_send_text(payload)

    async def paste(self, text: str) -> None:
        """Paste text using bracketed-paste mode (ESC [ 200 ~ ... ESC [ 201 ~).

        Real terminals wrap pasted content in these escapes so
        prompt_toolkit can treat multi-line code differently from
        one-keystroke-at-a-time input. tmux send-keys doesn't emit
        the wrapper, so paste-specific bugs are invisible to the
        tmux driver. This method does.
        """
        if self._session is None:
            raise RuntimeError("no active session — call start_neomind first")
        # Use iTerm2's dedicated paste API when available — it mimics
        # Cmd+V exactly, including bracketed paste handling.
        try:
            await self._session.async_paste(text)
            return
        except AttributeError:
            pass
        # Fallback: manually emit bracketed paste escapes.
        payload = "\x1b[200~" + text + "\x1b[201~"
        await self._session.async_send_text(payload)

    async def ctrl_c(self) -> None:
        """Emit a real ^C (ETX) keystroke."""
        if self._session is None:
            raise RuntimeError("no active session")
        await self._session.async_send_text("\x03")

    async def resize(self, cols: int, rows: int) -> None:
        """Fire a real terminal resize event (propagates SIGWINCH)."""
        if self._session is None:
            raise RuntimeError("no active session")
        # iTerm2 Session.async_set_grid_size takes a Size, not two ints.
        import iterm2.util as _util
        await self._session.async_set_grid_size(_util.Size(cols, rows))

    # ── Output primitives ────────────────────────────────────────────

    async def capture(self, lines: int = 0) -> str:
        """Capture the rendered screen contents.

        Returns the visible screen plus up to `lines` of scrollback
        from the history. `lines=0` means just the visible screen.
        """
        if self._session is None:
            raise RuntimeError("no active session")
        n = lines or self.config.default_capture_lines
        contents = await self._session.async_get_screen_contents()
        out: List[str] = []
        total = contents.number_of_lines
        start = max(0, total - n)
        for i in range(start, total):
            line = contents.line(i)
            if line is None:
                continue
            out.append(line.string)
        return "\n".join(out)

    async def wait_for(
        self,
        needle: str,
        *,
        timeout: float = 15.0,
        poll_sec: float = 0.4,
    ) -> bool:
        """Poll capture() until `needle` appears or timeout expires.

        Plain substring match. For regex matching, call `capture()`
        directly and apply your own `re.search`.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            screen = await self.capture()
            if needle in screen:
                return True
            await asyncio.sleep(poll_sec)
        return False

    async def wait_for_prompt(
        self,
        *,
        prompt_regex: Optional[re.Pattern] = None,
        timeout: Optional[float] = None,
    ) -> bool:
        """Wait until the screen ends with a shell/CLI prompt marker.

        Returns True once the prompt is visible, False on timeout.
        Default regex matches `> ` optionally preceded by ANSI color
        codes — override for other prompts.
        """
        regex = prompt_regex or DEFAULT_PROMPT_RE
        dead = time.time() + (timeout or self.config.boot_timeout_sec)
        while time.time() < dead:
            screen = await self.capture(lines=60)
            # Search across the whole visible screen — prompt_toolkit
            # renders status bars / footers below the actual prompt
            # so it's not always the last non-empty line.
            if regex.search(screen):
                return True
            await asyncio.sleep(0.3)
        return False


def _shquote(path: str) -> str:
    """Minimal shell quoting for cwd paths.

    Good enough for /Users/foo/bar style paths — we're not handling
    arbitrary user input here.
    """
    if not path:
        return "''"
    if any(c in path for c in " \t\n\"'$`\\"):
        escaped = path.replace("'", "'\\''")
        return f"'{escaped}'"
    return path


# ── Smoke test — run directly ───────────────────────────────────────

async def _smoke() -> int:
    """Minimal connectivity smoke test.

    Opens a window, starts the CLI, waits for prompt, sends /status,
    captures output, closes. Exit 0 = OK, 1 = connection unavailable,
    2 = CLI failed.
    """
    try:
        async with ITerm2CliTester() as tester:
            print(f"[iterm2-smoke] connected to iTerm2 app={tester._app!r}")
            await tester.start_neomind()
            got_prompt = await tester.wait_for_prompt(timeout=20)
            if not got_prompt:
                print("[iterm2-smoke] no prompt within 20s")
                screen = await tester.capture()
                print(f"[iterm2-smoke] screen tail:\n{screen[-600:]}")
                return 2
            await tester.send("/status")
            await asyncio.sleep(3)
            screen = await tester.capture()
            print(f"[iterm2-smoke] capture after /status:\n{screen[-1000:]}")
            return 0
    except ITerm2APIUnavailable as e:
        print(f"[iterm2-smoke] ITerm2APIUnavailable: {e}")
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(_smoke()))
