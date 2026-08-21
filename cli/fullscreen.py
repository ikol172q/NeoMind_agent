"""The REPL as a long-lived full-screen Application.

`neomind_interface.py:2355` records the problem and names this as the fix:

    prompt_toolkit's bottom_toolbar disappears because session.prompt() has
    already returned and there is no running Application to host the toolbar.
    ... without moving the whole REPL into a long-lived Application (the
    expensive refactor).

It stopped being expensive. The phases that split the runtime out of the CLI
cut the seams this needs, for a different reason: the 58 commands return a
`CommandResult` and call `print` zero times, `session_renderer` writes through
an injected callable, and `progress_display` is state rather than output. What
is left coupled to the drawing is roughly 320 lines, and none of it is the
part that took years to get right.

So this reuses rather than reimplements. Rich still renders every panel,
table and Markdown block; it just renders into a buffer instead of onto the
terminal, and prompt_toolkit draws the result. `ANSI()` round-trips colour,
box drawing and CJK width intact — verified before this file was written,
because the whole design rests on it.

**The tradeoff is real and does not go away.** An alternate-screen application
does not write to the terminal's scrollback. The transcript is the app's to
keep, `| tee` no longer does what it did, and on exit the screen restores to
whatever was there before. That is the price of a status bar that survives
streaming, and it is why this ships behind a switch rather than as a
replacement.
"""

from __future__ import annotations

import io
import os
from typing import Any, Callable, List, Optional


def fullscreen_enabled() -> bool:
    """Whether the REPL should run as a full-screen Application.

    Read per call, never cached at import: flipping it is a restart, not a
    rebuild. Off unless spelled exactly, so a typo lands on the path that has
    years of use behind it rather than the new one.
    """
    return os.getenv("NEOMIND_TUI", "").strip().lower() in ("1", "on", "true", "full")


class OutputSink:
    """Where everything the REPL prints ends up.

    One object because a full-screen app cannot tolerate a second writer: a
    single stray `print` lands in the middle of a redraw and corrupts the
    frame. In line mode it forwards to the console it was given and behaves
    exactly as before; in full-screen mode it captures Rich's own output and
    hands the text to whoever is drawing.

    Rich is not replaced. It is pointed at a buffer.
    """

    def __init__(
        self,
        *,
        console: Any = None,
        capture: bool = False,
        width: int = 100,
        on_write: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.capture = capture
        self.on_write = on_write
        self._buffer = io.StringIO()
        if capture:
            from rich.console import Console

            # `force_terminal` is what makes Rich emit ANSI into a plain
            # buffer; without it the markup is flattened and every colour,
            # rule and table border is lost before prompt_toolkit ever sees it.
            self.console = Console(
                file=self._buffer,
                force_terminal=True,
                color_system="truecolor",
                width=width,
                soft_wrap=False,
            )
        else:
            self.console = console

    # ── the two ways the REPL emits ───────────────────────────────────────

    def print(self, *args: Any, **kwargs: Any) -> None:
        """Rich-flavoured output: markup, Markdown, tables, panels."""
        if self.console is not None:
            self.console.print(*args, **kwargs)
        else:
            print(*args, **kwargs)
        self._drain()

    def write(self, text: str) -> None:
        """Raw text, as the streaming renderer produces it."""
        if self.capture:
            self._buffer.write(text)
            self._drain()
        else:
            import sys

            sys.stdout.write(text)
            sys.stdout.flush()

    # ── capture plumbing ──────────────────────────────────────────────────

    def _drain(self) -> None:
        """Hand off whatever Rich just wrote, and reset the buffer.

        Draining rather than accumulating: the buffer is a transport, not the
        transcript. Letting it grow would mean re-rendering the whole session
        on every token.
        """
        if not self.capture:
            return
        text = self._buffer.getvalue()
        if not text:
            return
        self._buffer.seek(0)
        self._buffer.truncate(0)
        if self.on_write is not None:
            self.on_write(text)

    def resize(self, width: int) -> None:
        if self.capture and self.console is not None:
            self.console.width = max(20, width)


class Transcript:
    """What the terminal's scrollback used to hold.

    In line mode the terminal keeps everything and the app need not. A
    full-screen app owns its own history or it has none, so this is not a
    convenience — it is the thing standing in for a capability that was
    removed.

    Bounded, because a session that runs all day would otherwise grow without
    limit. The bound is in lines rather than bytes so the number means
    something to whoever tunes it.
    """

    def __init__(self, max_lines: int = 5000) -> None:
        self.max_lines = max_lines
        self._lines: List[str] = [""]

    def append(self, text: str) -> None:
        if not text:
            return
        parts = text.split("\n")
        self._lines[-1] += parts[0]
        self._lines.extend(parts[1:])
        if len(self._lines) > self.max_lines:
            # Drop from the front: the recent end is the part being read.
            del self._lines[: len(self._lines) - self.max_lines]

    def clear(self) -> None:
        self._lines = [""]

    @property
    def text(self) -> str:
        return "\n".join(self._lines)

    def __len__(self) -> int:
        return len(self._lines)


class FullScreenREPL:
    """The Application the REPL runs inside.

    The layout is the whole point. The status bar is a `Window` in it, so it is
    drawn on every frame — including the frames produced while a turn is
    streaming, which is exactly when the old `bottom_toolbar` was absent and a
    header line had to be printed into the scrollback to compensate.

    A turn runs on a worker thread. Running it inline would block the event
    loop, nothing would redraw, and the status bar would freeze for the length
    of the turn — the same symptom this exists to remove, arrived at from the
    other direction.
    """

    def __init__(
        self,
        *,
        toolbar: Callable[[], Any],
        completer: Any = None,
        key_bindings: Any = None,
        style: Any = None,
        on_submit: Optional[Callable[[str], None]] = None,
        prompt: str = "> ",
        max_transcript_lines: int = 5000,
    ) -> None:
        self.transcript = Transcript(max_lines=max_transcript_lines)
        self.toolbar = toolbar
        self.on_submit = on_submit
        self.prompt = prompt
        self._busy = False
        self._app: Any = None
        self._follow = True          # stick to the bottom until the user scrolls
        self._scroll = 0             # lines up from the bottom
        self._completer = completer
        self._extra_bindings = key_bindings
        self._style = style

    # ── output ────────────────────────────────────────────────────────────

    def write(self, text: str) -> None:
        """Called from the worker thread as output is produced."""
        self.transcript.append(text)
        if self._follow:
            self._scroll = 0
        self.invalidate()

    def invalidate(self) -> None:
        if self._app is not None:
            try:
                self._app.invalidate()
            except Exception:
                # A redraw request that arrives after the app has gone is not
                # worth taking a turn down for.
                pass

    def sink(self, width: int = 100) -> OutputSink:
        return OutputSink(capture=True, width=width, on_write=self.write)

    # ── layout ────────────────────────────────────────────────────────────

    def _build(self) -> Any:
        from prompt_toolkit.application import Application
        from prompt_toolkit.buffer import Buffer
        from prompt_toolkit.formatted_text import ANSI, HTML, to_formatted_text
        from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
        from prompt_toolkit.layout import Layout
        from prompt_toolkit.layout.containers import HSplit, Window
        from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
        from prompt_toolkit.layout.dimension import Dimension

        def transcript_fragments():
            text = self.transcript.text
            if self._scroll:
                lines = text.split("\n")
                end = max(1, len(lines) - self._scroll)
                text = "\n".join(lines[:end])
            return to_formatted_text(ANSI(text))

        output_window = Window(
            content=FormattedTextControl(transcript_fragments, focusable=False),
            wrap_lines=True,
            # Bottom-anchored: a REPL reads from the newest line, and a window
            # that grows downward from the top leaves the newest output off
            # screen until it happens to fill.
            dont_extend_height=False,
        )

        def toolbar_fragments():
            try:
                value = self.toolbar()
            except Exception as exc:  # noqa: BLE001 — a broken bar must not
                # take down the app; it is decoration around a working REPL.
                return to_formatted_text(HTML(f" <ansired>status unavailable: {exc}</ansired>"))
            return to_formatted_text(value)

        status_window = Window(
            content=FormattedTextControl(toolbar_fragments, focusable=False),
            height=Dimension(min=1, max=2),
            style="class:bottom-toolbar",
        )

        self.buffer = Buffer(
            completer=self._completer,
            complete_while_typing=True,
            multiline=False,
            accept_handler=self._accept,
        )
        input_window = Window(
            content=BufferControl(buffer=self.buffer),
            height=Dimension(min=1, max=6),
        )

        prompt_window = Window(
            content=FormattedTextControl(lambda: [("class:prompt", self.prompt)]),
            width=len(self.prompt),
            dont_extend_width=True,
        )

        from prompt_toolkit.layout.containers import VSplit

        root = HSplit([
            output_window,
            Window(height=1, char="─", style="class:separator"),
            status_window,
            VSplit([prompt_window, input_window]),
        ])

        bindings = self._own_bindings()
        if self._extra_bindings is not None:
            bindings = merge_key_bindings([self._extra_bindings, bindings])

        self._app = Application(
            layout=Layout(root, focused_element=input_window),
            key_bindings=bindings,
            full_screen=True,
            style=self._style,
            mouse_support=False,
            refresh_interval=0.2,
        )
        return self._app

    def _own_bindings(self) -> Any:
        from prompt_toolkit.key_binding import KeyBindings

        kb = KeyBindings()

        @kb.add("c-d")
        def _exit(event):
            event.app.exit()

        @kb.add("c-c")
        def _interrupt(event):
            # Same meaning as in the line-based REPL: interrupt the work, not
            # the session. Exiting on Ctrl+C would lose a transcript the
            # terminal is no longer keeping a copy of.
            if self._busy:
                self.write("\n[interrupted]\n")
            else:
                self.buffer.reset()

        @kb.add("pageup")
        def _up(event):
            self._follow = False
            self._scroll = min(self._scroll + 10, max(0, len(self.transcript) - 1))

        @kb.add("pagedown")
        def _down(event):
            self._scroll = max(0, self._scroll - 10)
            if self._scroll == 0:
                self._follow = True

        @kb.add("end")
        def _bottom(event):
            self._scroll = 0
            self._follow = True

        return kb

    # ── input ─────────────────────────────────────────────────────────────

    def _accept(self, buff: Any) -> bool:
        text = buff.text
        buff.reset()
        if not text.strip() or self._busy:
            return False
        self.write(f"\n{self.prompt}{text}\n")
        self._run_turn(text)
        return False

    def _run_turn(self, text: str) -> None:
        """Hand the turn to a worker so the frame keeps updating."""
        import threading

        if self.on_submit is None:
            return

        def work():
            self._busy = True
            self.invalidate()
            try:
                self.on_submit(text)
            except Exception as exc:  # noqa: BLE001
                self.write(f"\n[error] {exc}\n")
            finally:
                self._busy = False
                self.invalidate()

        threading.Thread(target=work, daemon=True).start()

    # ── lifecycle ─────────────────────────────────────────────────────────

    def run(self) -> None:
        self._build().run()


class StderrGuard:
    """Route stderr into the transcript for as long as the app owns the screen.

    Thirteen places write ANSI to stderr — spinners, tool-progress lines, and
    the erase-line codes that clear them. Every one is a second writer to a
    screen the Application believes it owns, and in a real run they landed on
    top of the layout and shredded it.

    Teaching each call site about full-screen mode would be thirteen edits and
    one missed edit away from the same corruption, and the next one added would
    not know to ask. Taking the stream instead covers all of them, including
    the ones written later.

    Carriage returns and erase-line sequences are dropped rather than
    forwarded: they mean "redraw this line in place", which a scrolling
    transcript cannot honour and would render as gibberish. What remains is the
    text a human wanted to see.
    """

    #: `\r`, and the CSI sequences a spinner uses to erase what it just wrote.
    _CONTROL = None

    def __init__(self, write: Callable[[str], None]) -> None:
        self._write = write
        self._saved: Any = None
        self._pending = ""

    def __enter__(self) -> "StderrGuard":
        import re
        import sys

        if StderrGuard._CONTROL is None:
            StderrGuard._CONTROL = re.compile(r"\r|\x1b\[[0-9;]*[KGJ]")
        self._saved = sys.stderr
        sys.stderr = self  # type: ignore[assignment]
        return self

    def __exit__(self, *exc: Any) -> None:
        import sys

        if self._saved is not None:
            sys.stderr = self._saved
            self._saved = None

    # ── file-like surface ────────────────────────────────────────────────

    def write(self, text: str) -> int:
        if not text:
            return 0
        cleaned = StderrGuard._CONTROL.sub("", text)
        if not cleaned.strip():
            return len(text)
        # A spinner redraws the same line ten times a second. Stripped of the
        # carriage return that made it animate, that is ten lines a second in a
        # transcript. Collapse consecutive repeats rather than short-circuiting
        # each spinner by hand: the next one added will not know to ask.
        #
        # Compared with the braille glyphs removed. They are what makes a
        # spinner a spinner — each frame is a *different* character — so
        # comparing the raw text finds every frame distinct and collapses
        # nothing, which is what the first version of this did.
        stamp = self._despin(cleaned)
        if stamp == self._pending:
            return len(text)
        self._pending = stamp
        self._write(cleaned if cleaned.endswith("\n") else cleaned + "\n")
        return len(text)

    @staticmethod
    def _despin(text: str) -> str:
        """The line with its animation frame removed, for comparison only.

        U+2800–U+28FF is the braille block, which is where every spinner in
        this codebase draws its frames from.
        """
        return "".join(c for c in text if not (0x2800 <= ord(c) <= 0x28FF)).strip()

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        # False, deliberately. A library that asks is deciding whether to emit
        # cursor control, and the honest answer for a transcript is no.
        return False

    @property
    def encoding(self) -> str:
        return "utf-8"
