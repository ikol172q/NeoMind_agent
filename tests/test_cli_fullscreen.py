"""The full-screen REPL surface.

Three defects showed up only in a real terminal, and each one was a writer
that had not been pointed at the Application: the spinner's stderr, the twelve
other stderr writers, and the streamed tokens on stdout — which drew the
answer on top of the input line. Unit tests could not see any of them because
nothing in a unit test owns a screen.

So these assert on *where output is routed*, which is the property that was
actually wrong, rather than on how a frame looks.
"""

from __future__ import annotations

import sys
from unittest import mock

import pytest

from cli.fullscreen import (
    FullScreenREPL,
    OutputSink,
    StderrGuard,
    Transcript,
    fullscreen_enabled,
)


class TestTheSwitch:
    """D8: one switch per surface, read per call, off unless spelled."""

    def test_absent_means_the_line_based_repl(self, monkeypatch):
        monkeypatch.delenv("NEOMIND_TUI", raising=False)
        assert fullscreen_enabled() is False

    @pytest.mark.parametrize("value", ["1", "on", "true", "full", "  ON  ", "Full"])
    def test_the_spellings_that_turn_it_on(self, monkeypatch, value):
        monkeypatch.setenv("NEOMIND_TUI", value)
        assert fullscreen_enabled() is True

    @pytest.mark.parametrize("value", ["0", "off", "ful", "yes", "tui", ""])
    def test_anything_else_leaves_the_proven_path(self, monkeypatch, value):
        """A typo must land on the REPL with years of use behind it, not the
        new one."""
        monkeypatch.setenv("NEOMIND_TUI", value)
        assert fullscreen_enabled() is False

    def test_it_is_not_cached_at_import(self, monkeypatch):
        monkeypatch.setenv("NEOMIND_TUI", "1")
        assert fullscreen_enabled() is True
        monkeypatch.setenv("NEOMIND_TUI", "0")
        assert fullscreen_enabled() is False


class TestTranscriptStandsInForScrollback:
    """An alternate-screen app does not write to the terminal's scrollback, so
    this is not a convenience — it replaces a capability that was removed."""

    def test_text_accumulates_across_writes(self):
        t = Transcript()
        t.append("hello ")
        t.append("world\n")
        assert t.text == "hello world\n"

    def test_a_write_without_a_newline_continues_the_same_line(self):
        """Streamed tokens arrive mid-line; each one must not start a new one."""
        t = Transcript()
        for token in ("3", "9", "1"):
            t.append(token)
        assert t.text == "391"

    def test_it_is_bounded(self):
        t = Transcript(max_lines=5)
        for i in range(50):
            t.append(f"line {i}\n")
        assert len(t) <= 5

    def test_the_bound_drops_the_oldest(self):
        t = Transcript(max_lines=3)
        for i in range(10):
            t.append(f"line {i}\n")
        assert "line 9" in t.text
        assert "line 0" not in t.text


class TestOutputSinkRoutesRichWithoutReplacingIt:

    def test_capture_mode_keeps_ansi(self):
        """Flattened output would lose every colour, rule and table border
        before prompt_toolkit ever saw it."""
        got = []
        sink = OutputSink(capture=True, width=40, on_write=got.append)
        sink.print("[bold red]danger[/bold red]")
        assert chr(27) in "".join(got)

    def test_capture_mode_keeps_cjk(self):
        got = []
        sink = OutputSink(capture=True, width=40, on_write=got.append)
        sink.print("宽字符对齐 12.5%")
        assert "宽字符对齐" in "".join(got)

    def test_raw_writes_reach_the_same_place(self):
        got = []
        sink = OutputSink(capture=True, width=40, on_write=got.append)
        sink.write("streamed token")
        assert "streamed token" in "".join(got)

    def test_the_buffer_does_not_accumulate(self):
        """Left to grow, every token would re-render the whole session."""
        got = []
        sink = OutputSink(capture=True, width=40, on_write=got.append)
        sink.write("first")
        sink.write("second")
        assert "first" not in got[-1]

    def test_passthrough_mode_uses_the_console_it_was_given(self):
        console = mock.Mock()
        sink = OutputSink(console=console, capture=False)
        sink.print("hello")
        console.print.assert_called_once_with("hello")


class TestStderrIsTakenNotAskedNicely:
    """Thirteen places write ANSI to stderr. Patching each is one missed edit
    away from a shredded layout, and the next one added would not know to ask."""

    def test_the_stream_is_restored_afterwards(self):
        before = sys.stderr
        with StderrGuard(lambda t: None):
            assert sys.stderr is not before
        assert sys.stderr is before

    def test_it_is_restored_even_when_the_body_raises(self):
        before = sys.stderr
        with pytest.raises(RuntimeError):
            with StderrGuard(lambda t: None):
                raise RuntimeError("boom")
        assert sys.stderr is before

    def test_carriage_returns_and_erase_codes_are_dropped(self):
        """They mean "redraw this line in place", which a scrolling transcript
        cannot honour and would render as gibberish."""
        got = []
        with StderrGuard(got.append):
            sys.stderr.write("\r\x1b[K")
        assert got == []

    def test_real_text_survives(self):
        got = []
        with StderrGuard(got.append):
            sys.stderr.write("something went wrong\n")
        assert "something went wrong" in "".join(got)

    def test_a_spinner_collapses_to_one_line(self):
        """The bug this exists for: each frame is a *different* braille glyph,
        so comparing the raw text finds every frame distinct and collapses
        nothing — which is what the first version did."""
        got = []
        with StderrGuard(got.append):
            for frame in "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏⠋⠙":
                sys.stderr.write(f"\r\x1b[K\x1b[36m{frame}\x1b[0m Thinking…")
        assert len(got) == 1, f"twelve spinner frames became {len(got)} lines"

    def test_a_changed_label_is_not_collapsed(self):
        """Dedup must not swallow progress that actually changed."""
        got = []
        with StderrGuard(got.append):
            sys.stderr.write("\r\x1b[K⠋ Thinking…")
            sys.stderr.write("\r\x1b[K⠙ Thinking… (3s)")
        assert len(got) == 2

    def test_distinct_tool_lines_both_appear(self):
        got = []
        with StderrGuard(got.append):
            sys.stderr.write("🔧 Read(core.py) ✓\n")
            sys.stderr.write("🔧 Grep(def stream) ✓\n")
        assert len(got) == 2

    def test_it_does_not_claim_to_be_a_terminal(self):
        """A library asking is deciding whether to emit cursor control, and the
        honest answer for a transcript is no."""
        with StderrGuard(lambda t: None):
            assert sys.stderr.isatty() is False


class TestTheStatusBarSurvivesStreaming:
    """The whole reason this surface exists. `neomind_interface.py` records the
    old behaviour: once `session.prompt()` returned there was no Application to
    host the toolbar, so during streaming it was simply gone."""

    def test_the_toolbar_is_part_of_the_layout(self):
        from prompt_toolkit.formatted_text import HTML

        calls = []

        def toolbar():
            calls.append(1)
            return HTML(" <b>model</b> | coding")

        repl = FullScreenREPL(toolbar=toolbar)
        app = repl._build()
        for window in app.layout.container.children:
            control = getattr(window, "content", None)
            getter = getattr(control, "text", None)
            if callable(getter):
                try:
                    getter()
                except Exception:
                    pass
        assert calls, "the status bar is not rendered by a redraw"

    def test_a_broken_toolbar_does_not_take_the_repl_down(self):
        """It is decoration around a working REPL."""
        def toolbar():
            raise ValueError("context manager exploded")

        repl = FullScreenREPL(toolbar=toolbar)
        app = repl._build()
        rendered = []
        for window in app.layout.container.children:
            control = getattr(window, "content", None)
            getter = getattr(control, "text", None)
            if callable(getter):
                rendered.append(getter())
        assert rendered, "nothing rendered at all"

    def test_output_written_from_a_worker_reaches_the_transcript(self):
        from prompt_toolkit.formatted_text import HTML

        repl = FullScreenREPL(toolbar=lambda: HTML(" bar"))
        repl.write("streamed from a turn")
        assert "streamed from a turn" in repl.transcript.text

    def test_the_sink_feeds_the_transcript(self):
        from prompt_toolkit.formatted_text import HTML

        repl = FullScreenREPL(toolbar=lambda: HTML(" bar"))
        repl.sink(width=40).print("rendered by rich")
        assert "rendered by rich" in repl.transcript.text


class TestEveryWriterIsPointedAtTheApp:
    """Where the three real-terminal defects actually lived.

    Each was a writer still aimed at the terminal while an Application owned
    the screen. The layout looked right in isolation every time; the failure
    only appeared when something else wrote.
    """

    @staticmethod
    def _iface():
        from cli.neomind_interface import NeoMindInterface

        iface = NeoMindInterface.__new__(NeoMindInterface)
        return iface

    def test_streamed_tokens_go_to_stdout_in_line_mode(self):
        iface = self._iface()
        writer = iface._stream_writer()
        with mock.patch.object(sys, "stdout") as out:
            writer("token")
        out.write.assert_called_once_with("token")

    def test_streamed_tokens_go_to_the_app_in_full_screen_mode(self):
        """The defect: the answer was drawn on the input line, because the
        renderer was wired straight to stdout no matter who owned the screen."""
        iface = self._iface()
        got = []
        iface._fullscreen_write = got.append
        writer = iface._stream_writer()
        with mock.patch.object(sys, "stdout") as out:
            writer("391")
        assert got == ["391"]
        out.write.assert_not_called()

    def test_the_renderer_takes_the_writer_rather_than_owning_one(self):
        """Asserted on the parsed call, not on a substring: a comment naming
        `_stream_writer` would satisfy a grep.

        The construction site is found rather than named. Hard-coding the
        method it lives in already produced a green-looking failure here once,
        when the guess (`_stream_and_render`) was not the real name
        (`_stream_and_render_session`) — a test that cannot find its target
        proves nothing about it.
        """
        import ast
        import pathlib

        tree = ast.parse(pathlib.Path("cli/neomind_interface.py").read_text())
        sites = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "SessionRenderer"
        ]
        assert sites, "SessionRenderer is never constructed"
        for site in sites:
            write = next((k for k in site.keywords if k.arg == "write"), None)
            assert write is not None, "SessionRenderer got no writer"
            assert isinstance(write.value, ast.Call) and \
                getattr(write.value.func, "attr", None) == "_stream_writer", (
                    f"line {site.lineno}: the writer is fixed, not chosen per "
                    f"surface — this is how the answer got drawn on the input line"
                )

    def test_the_spinner_is_silent_under_the_application(self, monkeypatch):
        """It writes carriage returns straight to stderr. Under an Application
        those land on the layout; the status bar already shows liveness."""
        import threading

        from cli.neomind_interface import NeoMindInterface

        monkeypatch.setenv("NEOMIND_TUI", "1")
        iface = self._iface()
        with mock.patch.object(threading, "Thread") as thread:
            event = NeoMindInterface._start_spinner(iface, "Thinking…")
        thread.assert_not_called()
        assert isinstance(event, threading.Event)

    def test_the_spinner_still_runs_in_line_mode(self, monkeypatch):
        import threading

        from cli.neomind_interface import NeoMindInterface

        monkeypatch.delenv("NEOMIND_TUI", raising=False)
        iface = self._iface()
        iface._SPINNER_FRAMES = NeoMindInterface._SPINNER_FRAMES
        with mock.patch.object(threading, "Thread") as thread:
            NeoMindInterface._start_spinner(iface, "Thinking…")
        thread.assert_called_once()
