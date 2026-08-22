"""The REPL as a long-lived Application that keeps the terminal's scrollback.

`neomind_interface.py` has carried the problem in a comment for a while: once
`session.prompt()` returns there is no Application to host `bottom_toolbar`, so
the status bar is absent for the whole of a streaming turn — precisely when a
user wants to know what is running and what it is costing. The fix it named
was "moving the whole REPL into a long-lived Application".

The first version of this did that with a **full-screen** Application, and
paid for the persistent status bar by losing the terminal's scrollback: an
alternate-screen application owns the display, so history had to be kept in a
buffer of its own, `| tee` stopped meaning what it meant, and the transcript
vanished on exit.

That price turned out to be avoidable. Codex — one of three terminal agents
installed on this machine — initialises its terminal with, in its own words,
an "inline viewport; history stays in normal scrollback". It owns a strip at
the bottom and nothing else. prompt_toolkit does the same thing with
`full_screen=False` plus `patch_stdout`: verified before this was rewritten,
by checking that the alternate-screen sequence is never emitted while the
status bar still redraws and printed lines still land in scrollback.

So there is no `Transcript` here any more. It existed only to stand in for a
capability that had been given away, and the terminal does that job better
than a bounded buffer ever could — search, selection and scroll all work
again because they were never taken away.

The layout follows what Codex, pi and CodeWhale independently converged on:
the input marked with a single glyph, one dim status line beneath it, parts
separated by a middle dot rather than a pipe, and no rules — whitespace does
the separating. Weight is spent on the one number that becomes a problem.
"""

from __future__ import annotations

import io
import os
import sys
from typing import Any, Callable, Optional


def fullscreen_enabled() -> bool:
    """Whether the REPL should run as a long-lived Application.

    On by default now. It kept the one thing the line-based REPL could not — a
    status bar that survives a streaming turn — without giving up anything the
    terminal already did, because an inline viewport leaves the scrollback
    alone.

    `NEOMIND_TUI=off` goes back, and the switch is read per call rather than
    cached at import, so going back is a restart and not a rebuild. Only the
    exact spellings turn it off: a typo should leave you on the default rather
    than silently somewhere else.
    """
    value = os.getenv("NEOMIND_TUI", "").strip().lower()
    return value not in ("0", "off", "false", "no", "legacy", "line")


def terminal_width(default: int = 80) -> int:
    """Columns the terminal actually has.

    Asked rather than assumed, and asked again on resize: every width baked
    into this file was wrong for every terminal but the one it was written in.
    """
    import shutil

    try:
        columns = shutil.get_terminal_size(fallback=(default, 24)).columns
    except Exception:
        return default
    return columns if columns > 20 else default


class _ForwardingFile:
    """A file Rich can write to that hands each write straight on.

    The obvious alternative — a `StringIO` plus a drain step — is what the
    first version did, and it had a hole exactly the shape of the bug it
    caused: `sink.print()` drained, `console.print()` did not. Handing the
    console out meant every `_print` in the REPL wrote into a buffer nobody
    emptied, so `/help` and every tool indicator went into it and stayed
    there while streamed tokens, which took a different route, appeared
    normally.

    Forwarding on write removes the step that could be skipped.
    """

    def __init__(self, on_write: Callable[[str], None]) -> None:
        self.on_write = on_write

    def write(self, text: str) -> int:
        if text:
            self.on_write(text)
        return len(text)

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        # Rich asks before deciding whether to emit control sequences. The
        # destination is a terminal, even though this object is not one.
        return True

    @property
    def encoding(self) -> str:
        return "utf-8"


class OutputSink:
    """Where everything the REPL prints ends up.

    One object because two writers to one screen is how a layout gets shredded.
    In line mode it forwards to the console it was given and behaves exactly as
    before; under the Application it hands Rich a console whose file writes
    through to whoever is printing above the viewport.

    Rich is not replaced. It is pointed somewhere else.
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
        if capture:
            from rich.console import Console

            # `force_terminal` is what makes Rich emit ANSI at all when its
            # file is not a tty; without it every colour, rule and table border
            # is flattened away before it reaches the terminal.
            self.console = Console(
                file=_ForwardingFile(on_write or (lambda _t: None)),
                force_terminal=True,
                color_system="truecolor",
                width=width,
                soft_wrap=False,
            )
        else:
            self.console = console

    def print(self, *args: Any, **kwargs: Any) -> None:
        """Rich-flavoured output: markup, Markdown, tables, panels."""
        if self.console is not None:
            self.console.print(*args, **kwargs)
        else:
            print(*args, **kwargs)

    def write(self, text: str) -> None:
        """Raw text, as the streaming renderer produces it."""
        if self.capture:
            if self.on_write is not None:
                self.on_write(text)
        else:
            import sys

            sys.stdout.write(text)
            sys.stdout.flush()

    def resize(self, width: int) -> None:
        if self.capture and self.console is not None:
            self.console.width = max(20, width)


class InlineREPL:
    """A long-lived Application that owns the bottom strip and nothing else.

    The status bar is a `Window` in the layout, so it is drawn on every frame —
    including the frames produced while a turn streams, which is exactly when
    `bottom_toolbar` was absent before. Everything the turn prints goes to
    stdout under `patch_stdout`, which lifts the viewport, writes above it, and
    puts it back: the terminal keeps the history, and search, selection and
    scrolling keep working because they were never taken away.

    A turn runs on a worker thread. Running it inline would block the event
    loop, nothing would redraw, and the status bar would freeze for the length
    of the turn — the same symptom this exists to remove, reached from the
    other side.
    """

    #: Marks the input. A single glyph rather than a box: Codex, pi and
    #: CodeWhale all frame their input with one, and a full border in a strip
    #: this short reads as heavier than what it contains.
    PROMPT = "› "

    #: How long the output proxy batches writes before painting. Every write
    #: lifts the strip out of the way and puts it back, so one repaint per
    #: token is one flicker per token. Long enough to coalesce a burst of
    #: tokens, short enough that a reply still appears to stream.
    #: Overridable so the interval can be measured rather than assumed.
    WRITE_INTERVAL = float(os.getenv("NEOMIND_TUI_INTERVAL", "0.1"))

    def __init__(
        self,
        *,
        status: Callable[[], Any],
        completer: Any = None,
        key_bindings: Any = None,
        style: Any = None,
        on_submit: Optional[Callable[[str], None]] = None,
        placeholder: str = "",
    ) -> None:
        self.status = status
        self.on_submit = on_submit
        self.placeholder = placeholder
        self._busy = False
        self._app: Any = None
        self._completer = completer
        self._extra_bindings = key_bindings
        self._style = style
        self._patch: Any = None
        self._worker: Any = None
        self._at_line_start = True

    # ── output ────────────────────────────────────────────────────────────

    def write(self, text: str) -> None:
        """Print above the viewport, from whichever thread produced it."""
        if not text:
            return
        import sys

        # Remembered so `_end_line` knows whether the cursor is mid-line.
        # A streamed answer usually ends without a newline, which leaves the
        # cursor parked on that row — and `patch_stdout` lifts the strip by
        # whole lines, so the next turn's redraw erased the row the answer was
        # still sitting on. That is the answer disappearing when you ask the
        # next question, and the flicker: the same partial row was repainted
        # on every write.
        self._at_line_start = text.endswith("\n")
        sys.stdout.write(text)
        # Deliberately not flushed per token. `StdoutProxy` batches writes and
        # emits them on its own cadence; flushing each one defeated that and
        # made the strip lift and settle once per token — which is the flicker.
        # A turn ends with `_end_line`, and the proxy drains on exit, so
        # nothing is left unwritten.

    def _end_line(self) -> None:
        """Close the current line, if anything is on it."""
        if not getattr(self, "_at_line_start", True):
            self.write("\n")

    def invalidate(self) -> None:
        if self._app is not None:
            try:
                self._app.invalidate()
            except Exception:
                # A redraw request arriving after the app has gone is not
                # worth taking a turn down for.
                pass

    def sink(self, width: Optional[int] = None) -> OutputSink:
        """A sink sized to the terminal, and resized when the terminal is.

        The first version hardcoded 100 columns. Rich then wrapped at 100 in an
        80-column window and the terminal re-wrapped what was left, which is
        how a paragraph came out ragged with pieces missing. A width that is
        not the terminal's is wrong at every width except one.
        """
        self._sink = OutputSink(
            capture=True, width=width or terminal_width(), on_write=self.write,
        )
        return self._sink

    def _resync_width(self) -> None:
        """Follow the terminal across a resize."""
        sink = getattr(self, "_sink", None)
        if sink is not None:
            sink.resize(terminal_width())

    def _two_line_status(self) -> bool:
        """Whether the status needs a second row this frame.

        Asked per frame rather than fixed, because the fleet line only exists
        while a fleet is running; a permanently reserved row would be a blank
        one most of the time.
        """
        try:
            from prompt_toolkit.formatted_text import to_formatted_text

            text = "".join(f[1] for f in to_formatted_text(self.status()))
            return "\n" in text
        except Exception:
            return False

    # ── layout ────────────────────────────────────────────────────────────

    def _build(self) -> Any:
        from prompt_toolkit.application import Application
        from prompt_toolkit.buffer import Buffer
        from prompt_toolkit.formatted_text import HTML, to_formatted_text
        from prompt_toolkit.key_binding import merge_key_bindings
        from prompt_toolkit.layout import Layout
        from prompt_toolkit.layout.containers import HSplit, VSplit, Window
        from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
        from prompt_toolkit.layout.dimension import Dimension

        self.buffer = Buffer(
            completer=self._completer,
            complete_while_typing=True,
            multiline=False,
            accept_handler=self._accept,
        )

        def status_fragments():
            try:
                return to_formatted_text(self.status())
            except Exception as exc:  # noqa: BLE001 — decoration around a
                # working REPL; a broken bar must not end the session.
                return to_formatted_text(
                    HTML(f"  <ansired>status unavailable: {exc}</ansired>")
                )

        def prompt_fragments():
            """The marker, plus the hint when there is nothing typed yet.

            Drawn as part of the prompt rather than as its own window: a
            separate column put the hint at the far side of the terminal, which
            read as a second field instead of as a placeholder.
            """
            marker = [("class:prompt", self.PROMPT)]
            if self.buffer.text or self._busy or not self.placeholder:
                return marker
            return marker + [("class:placeholder", self.placeholder)]

        # Every window in the strip is pinned to its exact height. A window
        # left free to grow takes the rest of the terminal with it — the first
        # attempt put seven blank rows between the input and the status line,
        # because the input was allowed to expand and did.
        input_row = VSplit([
            Window(
                content=FormattedTextControl(prompt_fragments),
                width=Dimension.exact(len(self.PROMPT)),
            ),
            Window(
                content=BufferControl(buffer=self.buffer),
                height=Dimension.exact(1),
                # The hint is drawn *behind* the buffer rather than beside it,
                # so it occupies the space the text will, the way a form
                # placeholder does. Beside it, it read as a second column.
                get_line_prefix=None,
            ),
        ])

        root = HSplit([
            # One blank row above. Codex spends its budget on space rather than
            # rules, and that is most of why its strip reads as calm.
            Window(height=Dimension.exact(1), char=" "),
            input_row,
            Window(height=Dimension.exact(1), char=" "),
            Window(
                content=FormattedTextControl(status_fragments, focusable=False),
                height=Dimension.exact(1 + (1 if self._two_line_status() else 0)),
            ),
        ])

        bindings = self._own_bindings()
        if self._extra_bindings is not None:
            bindings = merge_key_bindings([self._extra_bindings, bindings])

        self._app = Application(
            layout=Layout(root, focused_element=input_row),
            key_bindings=bindings,
            # The whole point. An alternate screen would take the scrollback
            # with it, which is the cost this design exists to avoid.
            full_screen=False,
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
            # Interrupt the work, not the session — the same meaning it has in
            # the line-based REPL.
            #
            # The first version only printed "[interrupted]" and left the turn
            # running. A real run showed the spinner counting past it to seven
            # seconds: the message was a claim about something that had not
            # happened, which is the failure this whole surface has been
            # chasing elsewhere.
            #
            # The turn runs on a worker, so a KeyboardInterrupt raised here
            # never reaches it. `_stream_and_render_session` already catches
            # one — the line-based REPL depends on it — so the interrupt is
            # delivered *into that thread* rather than reinvented.
            if self._busy:
                self._interrupt_worker()
            else:
                self.buffer.reset()

        return kb

    # ── input ─────────────────────────────────────────────────────────────

    def _accept(self, buff: Any) -> bool:
        text = buff.text
        buff.reset()
        if not text.strip() or self._busy:
            return False
        self._end_line()
        self.write(f"\n{self.PROMPT}{text}\n")
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
            except KeyboardInterrupt:
                # Delivered by `_interrupt_worker`. Silent on purpose: the
                # turn's own handler catches this first and prints
                # "[Interrupted]" itself, and saying so again put the word on
                # screen twice. Reaching here at all only means the interrupt
                # landed between statements rather than inside the turn.
                pass
            except Exception as exc:  # noqa: BLE001
                self.write(f"\n[error] {exc}\n")
            finally:
                # Land on a fresh row before the strip is drawn again.
                self._end_line()
                self._busy = False
                self._worker = None
                self.invalidate()

        self._worker = threading.Thread(target=work, daemon=True)
        self._worker.start()

    def _interrupt_worker(self) -> None:
        """Raise KeyboardInterrupt inside the thread running the turn.

        `PyThreadState_SetAsyncExc` is the only way to interrupt a thread that
        is not looking for it, which a streaming turn is not. It lands at the
        next bytecode boundary — near-instant for a loop pumping tokens, and
        the thread is a daemon either way, so a turn blocked in a syscall does
        not outlive the session.
        """
        import ctypes
        import threading

        worker = getattr(self, "_worker", None)
        if worker is None or not worker.is_alive():
            return
        ident = worker.ident
        if ident is None:
            return
        raised = ctypes.pythonapi.PyThreadState_SetAsyncExc(
            ctypes.c_ulong(ident), ctypes.py_object(KeyboardInterrupt)
        )
        if raised > 1:
            # Undo an over-broad set, as CPython's own documentation requires.
            ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(ident), None)

    # ── lifecycle ─────────────────────────────────────────────────────────

    def run(self) -> None:
        """Run until Ctrl+D.

        `patch_stdout` is what makes a print from a worker thread land *above*
        the viewport instead of through it. Without it the two writers fight
        over the same rows and the strip is redrawn on top of the output.
        """
        from prompt_toolkit.patch_stdout import StdoutProxy

        app = self._build()
        # `StdoutProxy` directly rather than `patch_stdout`, which hardcodes
        # its cadence. Batching writes is what stops the viewport being lifted
        # and replaced on every token; the interval is short enough that
        # streaming still reads as streaming.
        with StdoutProxy(raw=True, sleep_between_writes=self.WRITE_INTERVAL) as proxy:
            saved_out, saved_err = sys.stdout, sys.stderr
            sys.stdout = proxy
            sys.stderr = proxy
            try:
                app.run()
            finally:
                sys.stdout, sys.stderr = saved_out, saved_err
