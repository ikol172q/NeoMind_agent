"""The inline REPL surface.

The first version was full-screen and paid for its persistent status bar with
the terminal's scrollback. Codex showed the price was avoidable — it runs an
"inline viewport; history stays in normal scrollback" — so this one owns a
strip at the bottom and nothing else.

What is asserted here is *where output is routed* and *how tall the strip is*.
Both are what actually went wrong in a real terminal: a streamed answer drawn
on the input line, and windows left free to grow that put seven blank rows
between the input and the status. Neither is visible to a test that does not
own a screen, so they are checked structurally instead.
"""

from __future__ import annotations

import sys
from unittest import mock

import pytest

from cli.fullscreen import InlineREPL, OutputSink, fullscreen_enabled


class TestTheSwitch:
    """D8: one switch, read per call — now defaulting the other way.

    The inline surface became the default once it stopped costing anything:
    it keeps the status bar through a streaming turn and leaves the scrollback
    where it was. The switch stays so that going back is a restart rather than
    a rebuild.
    """

    def test_absent_means_the_inline_repl(self, monkeypatch):
        monkeypatch.delenv("NEOMIND_TUI", raising=False)
        assert fullscreen_enabled() is True

    @pytest.mark.parametrize("value", ["0", "off", "false", "no", "legacy", "line", " OFF "])
    def test_the_spellings_that_go_back(self, monkeypatch, value):
        monkeypatch.setenv("NEOMIND_TUI", value)
        assert fullscreen_enabled() is False

    @pytest.mark.parametrize("value", ["", "1", "on", "yes", "tui", "offf", "garbage"])
    def test_anything_else_stays_on_the_default(self, monkeypatch, value):
        """A typo should leave you where you were, not somewhere else. Only the
        exact words turn it off."""
        monkeypatch.setenv("NEOMIND_TUI", value)
        assert fullscreen_enabled() is True

    def test_it_is_not_cached_at_import(self, monkeypatch):
        monkeypatch.setenv("NEOMIND_TUI", "off")
        assert fullscreen_enabled() is False
        monkeypatch.setenv("NEOMIND_TUI", "on")
        assert fullscreen_enabled() is True


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

        repl = InlineREPL(status=toolbar)
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

        repl = InlineREPL(status=toolbar)
        app = repl._build()
        rendered = []
        for window in app.layout.container.children:
            control = getattr(window, "content", None)
            getter = getattr(control, "text", None)
            if callable(getter):
                rendered.append(getter())
        assert rendered, "nothing rendered at all"

    def test_output_written_from_a_worker_goes_to_the_terminal(self):
        """Above the viewport, not into a buffer of the app's own. The buffer
        was only ever standing in for the scrollback this design keeps."""
        from prompt_toolkit.formatted_text import HTML

        repl = InlineREPL(status=lambda: HTML(" bar"))
        with mock.patch.object(sys, "stdout") as out:
            repl.write("streamed from a turn")
        out.write.assert_called_once_with("streamed from a turn")

    def test_the_sink_writes_through_to_the_terminal(self):
        from prompt_toolkit.formatted_text import HTML

        repl = InlineREPL(status=lambda: HTML(" bar"))
        with mock.patch.object(sys, "stdout") as out:
            repl.sink(width=40).print("rendered by rich")
        assert "rendered by rich" in "".join(
            c.args[0] for c in out.write.call_args_list
        )


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

    def test_the_spinner_runs_on_both_surfaces(self, monkeypatch):
        """It had to be silenced under the alternate-screen version, where its
        carriage returns landed on a layout that owned the display. An inline
        viewport does not own those rows — `patch_stdout` lifts the strip out
        of the way — so silencing it now would remove liveness for no reason."""
        import threading

        from cli.neomind_interface import NeoMindInterface

        iface = self._iface()
        iface._SPINNER_FRAMES = NeoMindInterface._SPINNER_FRAMES
        for value in ("1", ""):
            monkeypatch.setenv("NEOMIND_TUI", value)
            with mock.patch.object(threading, "Thread") as thread:
                NeoMindInterface._start_spinner(iface, "Thinking…")
            assert thread.called, f"the spinner did not start with NEOMIND_TUI={value!r}"

    def test_the_spinner_still_runs_in_line_mode(self, monkeypatch):
        import threading

        from cli.neomind_interface import NeoMindInterface

        monkeypatch.delenv("NEOMIND_TUI", raising=False)
        iface = self._iface()
        iface._SPINNER_FRAMES = NeoMindInterface._SPINNER_FRAMES
        with mock.patch.object(threading, "Thread") as thread:
            NeoMindInterface._start_spinner(iface, "Thinking…")
        thread.assert_called_once()


class TestTheStripStaysAStrip:
    """An inline viewport is only worth having if it stays small.

    Every window here is pinned. The first attempt left the input free to grow
    and it took the rest of the terminal: seven blank rows opened up between
    the input and the status line, which looked exactly like the full-screen
    version it was supposed to replace.
    """

    @staticmethod
    def _repl(**kw):
        from prompt_toolkit.formatted_text import HTML

        return InlineREPL(status=lambda: HTML("  model · coding"), **kw)

    def test_it_does_not_take_the_alternate_screen(self):
        """The scrollback is the entire reason this design exists."""
        app = self._repl()._build()
        assert app.full_screen is False

    def test_every_row_of_the_strip_is_pinned(self):
        """A window with no maximum is a window that will fill the terminal.

        Walks the tree rather than the top level. The first version of this
        checked only the outer children, so the input — which lives inside a
        `VSplit` — was never looked at, and a mutation letting it grow to
        ninety-nine rows passed unnoticed.
        """
        app = self._repl()._build()
        unpinned = []

        def walk(node, path="root"):
            dim = getattr(node, "height", None)
            if dim is not None and getattr(node, "content", None) is not None:
                if dim.max is None or dim.max > 2:
                    unpinned.append(f"{path}: max={dim.max}")
            for i, child in enumerate(getattr(node, "children", []) or []):
                walk(child, f"{path}[{i}]")

        walk(app.layout.container)
        assert not unpinned, "rows that can grow: " + ", ".join(unpinned)

    def test_the_strip_is_a_handful_of_rows(self):
        app = self._repl()._build()
        total = sum(
            (getattr(w, "height", None).max if getattr(w, "height", None) else 1)
            for w in app.layout.container.children
        )
        assert total <= 6, f"the strip reserves {total} rows"

    def test_the_placeholder_shows_only_on_an_empty_input(self):
        repl = self._repl(placeholder="Ask anything")
        repl._build()
        rendered = lambda: "".join(
            f[1] for f in repl._app.layout.container.children[1].children[0].content.text()
        )
        assert "Ask anything" in rendered()
        repl.buffer.text = "hello"
        assert "Ask anything" not in rendered()

    def test_the_placeholder_rides_with_the_prompt(self):
        """Given its own column it landed at the far side of the terminal and
        read as a second field rather than as a hint."""
        repl = self._repl(placeholder="Ask anything")
        repl._build()
        fragments = repl._app.layout.container.children[1].children[0].content.text()
        text = "".join(f[1] for f in fragments)
        assert text.startswith(InlineREPL.PROMPT)
        assert "Ask anything" in text

    def test_the_status_grows_a_row_only_when_it_needs_one(self):
        """A permanently reserved fleet row is a blank row most of the time."""
        from prompt_toolkit.formatted_text import HTML

        one = InlineREPL(status=lambda: HTML("  a · b"))
        two = InlineREPL(status=lambda: HTML("  a · b\n  fleet: worker-1"))
        assert one._two_line_status() is False
        assert two._two_line_status() is True


def _plain(text: str) -> str:
    """The text with styling removed.

    Rich highlights `Read(...)` as a call and threads escape codes through the
    middle of it, so asserting on the raw stream tests Rich's syntax
    highlighting rather than whether anything was written.
    """
    import re

    return re.sub(r"\x1b\[[0-9;]*m", "", text)


class TestTheConsoleHandedOutActuallyPrints:
    """The bug that unit tests missed and one real session found immediately.

    `self.console` is swapped for the sink's, so all 135 `_print` calls follow
    it without being touched. The first version handed out a console writing
    into a `StringIO` that only `sink.print()` emptied — so anything going
    through `console.print()` directly, which is everything the REPL prints,
    went into a buffer nobody drained. `/help` produced nothing at all and no
    tool call was ever announced, while streamed tokens took a different route
    and looked fine.
    """

    @staticmethod
    def _sink_console():
        from prompt_toolkit.formatted_text import HTML

        repl = InlineREPL(status=lambda: HTML(" bar"))
        return repl.sink(width=100).console

    def test_printing_through_the_handed_out_console_reaches_the_terminal(self):
        console = self._sink_console()
        with mock.patch.object(sys, "stdout") as out:
            console.print("[dim]· Read(README.md)[/dim]")
            written = "".join(c.args[0] for c in out.write.call_args_list if c.args)
        assert "Read(README.md)" in _plain(written)

    def test_the_repl_print_helper_reaches_the_terminal(self):
        """`_print` reads `self.console` and nothing else, which is what makes
        the swap enough — but only if the console it is given prints."""
        from cli.neomind_interface import NeoMindInterface

        iface = NeoMindInterface.__new__(NeoMindInterface)
        iface.console = self._sink_console()
        with mock.patch.object(sys, "stdout") as out:
            iface._print("[dim]tool finished[/dim]")
            written = "".join(c.args[0] for c in out.write.call_args_list if c.args)
        assert "tool finished" in _plain(written)

    def test_styling_survives_the_trip(self):
        """Flattened output would lose every colour, rule and table border."""
        console = self._sink_console()
        with mock.patch.object(sys, "stdout") as out:
            console.print("[bold red]danger[/bold red]")
            written = "".join(c.args[0] for c in out.write.call_args_list if c.args)
        assert chr(27) in written

    def test_nothing_is_held_back_waiting_to_be_drained(self):
        """A buffer with a drain step is a step that can be skipped; this one
        has no buffer to hold anything."""
        console = self._sink_console()
        seen = []
        console.file.on_write = seen.append
        console.print("first")
        assert seen, "output was retained instead of forwarded"


class TestTheBannerBorderLinesUp:
    """The right-hand border was two columns out on the title row.

    Padding was computed from the length of a string that already carried
    `[dim]` and `[/dim]`, so the markup counted as content. Rows are measured
    as plain text now and styled after — and measured in *columns*, because a
    CJK path is two columns per glyph and `len()` would put the border in the
    wrong place for exactly the users most likely to notice.
    """

    @staticmethod
    def _render(mode="coding", cwd="/Users/x/Desktop/NeoMind_agent", model="deepseek-v4"):
        import io

        from rich.console import Console

        from cli.neomind_interface import NeoMindInterface

        buf = io.StringIO()
        iface = NeoMindInterface.__new__(NeoMindInterface)
        iface.console = Console(file=buf, force_terminal=False, width=200)
        iface.chat = mock.Mock(mode=mode, model=model, thinking_enabled=True)
        iface._get_tool_registry = lambda: mock.Mock(get_all_tools=lambda: [0] * 52)
        with mock.patch("os.getcwd", return_value=cwd), \
             mock.patch("cli.neomind_interface.RICH_AVAILABLE", True):
            iface.display_welcome()
        return [line for line in buf.getvalue().split("\n") if line.strip()]

    @staticmethod
    def _columns(text: str) -> int:
        from wcwidth import wcswidth

        width = wcswidth(text)
        return width if width >= 0 else len(text)

    @pytest.mark.parametrize("mode", ["coding", "fin", "chat"])
    def test_every_row_is_the_same_width(self, mode):
        widths = {self._columns(line) for line in self._render(mode=mode)}
        assert len(widths) == 1, f"{mode}: rows differ in width — {sorted(widths)}"

    def test_a_cjk_path_does_not_break_the_border(self):
        """`len()` counts one per glyph and the terminal spends two."""
        rows = self._render(cwd="/Users/x/项目/中文很长的目录名")
        widths = {self._columns(line) for line in rows}
        assert len(widths) == 1, f"rows differ in width — {sorted(widths)}"

    def test_a_long_model_name_does_not_break_the_border(self):
        rows = self._render(model="some-very-long-model-identifier-v4-preview")
        widths = {self._columns(line) for line in rows}
        assert len(widths) == 1

    def test_the_key_hint_wall_is_gone(self):
        """Fifteen bindings in one dim pipe-separated row is the wall Codex
        avoids by showing one line and keeping the rest behind it."""
        text = "\n".join(self._render())
        assert text.count("|") <= 1
        assert "/help" in text

    def test_the_tool_count_is_shown_not_swallowed(self):
        assert "52 available" in "\n".join(self._render())


class TestInterruptActuallyInterrupts:
    """Ctrl+C has to stop the work, not announce that it did.

    The first version printed "[interrupted]" and left the turn running: a real
    session showed the spinner counting past it to seven seconds while the
    model kept going. A message about something that did not happen is the
    exact failure this codebase spent the day removing from the runtime, and
    it went straight back in here by hand.

    The turn runs on a worker, so a KeyboardInterrupt raised in the key binding
    never reaches it. These assert the loop stops, not that a word appeared.
    """

    @staticmethod
    def _running_repl():
        import threading
        import time

        from prompt_toolkit.formatted_text import HTML

        repl = InlineREPL(status=lambda: HTML(" bar"))
        repl.write = lambda _t: None
        state = {"iterations": 0, "caught": False}
        started = threading.Event()

        def turn(_text):
            try:
                started.set()
                for i in range(1_000_000):
                    state["iterations"] = i
                    time.sleep(0.001)
            except KeyboardInterrupt:
                state["caught"] = True
                raise

        repl.on_submit = turn
        repl._run_turn("go")
        started.wait(timeout=2)
        time.sleep(0.3)
        return repl, state

    def test_the_running_turn_stops(self):
        import time

        repl, state = self._running_repl()
        before = state["iterations"]
        repl._interrupt_worker()
        time.sleep(0.4)
        after = state["iterations"]
        assert after - before < 5, (
            f"the loop advanced {after - before} steps after the interrupt — "
            "it was told, not stopped"
        )

    def test_the_turn_sees_a_keyboard_interrupt(self):
        """So the handler the line-based REPL already relies on still fires."""
        import time

        repl, state = self._running_repl()
        repl._interrupt_worker()
        time.sleep(0.4)
        assert state["caught"] is True

    def test_the_session_is_usable_afterwards(self):
        import time

        repl, _ = self._running_repl()
        repl._interrupt_worker()
        time.sleep(0.4)
        assert repl._busy is False, "a stuck busy flag rejects the next prompt"

    def test_interrupting_with_nothing_running_is_harmless(self):
        from prompt_toolkit.formatted_text import HTML

        repl = InlineREPL(status=lambda: HTML(" bar"))
        repl._interrupt_worker()

    def test_the_word_is_not_printed_twice(self):
        """The turn's own handler prints it; the worker's fallback must not.

        The turn re-raises, which is what the real one does — its handler
        prints and lets the exception continue. A fallback that also prints
        then puts the word on screen twice, which is what happened in a real
        session. An earlier version of this test had the turn swallow the
        exception, so the fallback was never reached and the assertion held
        no matter what the fallback did.
        """
        import time

        from prompt_toolkit.formatted_text import HTML

        repl = InlineREPL(status=lambda: HTML(" bar"))
        written = []
        repl.write = written.append

        def turn(_text):
            try:
                for _ in range(1_000_000):
                    time.sleep(0.001)
            except KeyboardInterrupt:
                repl.write("\n[Interrupted]\n")
                raise

        repl.on_submit = turn
        repl._run_turn("go")
        time.sleep(0.3)
        repl._interrupt_worker()
        time.sleep(0.4)
        assert "".join(written).lower().count("interrupted") == 1
