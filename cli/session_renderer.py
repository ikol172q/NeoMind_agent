"""Render a turn's runtime events for the terminal REPL.

This is the frontend half of Phase 4: `NeoMindInterface` stops owning the LLM
call and the tool loop, and instead consumes `AgentSession.run_turn()`. The
runtime decides *what happened*; this decides *how it looks*.

It lives in `cli/` rather than `agent/runtime/` deliberately —
`tests/runtime/test_import_boundary.py` forbids the runtime from importing
rich, prompt_toolkit or anything else that draws, and a renderer that the
runtime could import would make that boundary meaningless.

The visible behaviour it has to preserve, from `_stream_and_render()`:

  * a spinner runs until the first token of the answer, then stops
  * text passes through the mode's content filter (code-fence suppression in
    coding mode, syntax highlighting elsewhere)
  * an interruption prints "[Interrupted]", an error prints in red
  * tool activity is announced, and its result summarised

Thinking text is not printed as it arrives. The baseline showed a spinner
during reasoning and then a one-line "Thought for 1.2s — …" summary, and a
renderer that dumps reasoning inline would change what a user sees on every
turn of every mode.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional

from agent.runtime.events import (
    RuntimeEvent,
    StatusChanged,
    TextDelta,
    ThinkingDelta,
    ToolFinished,
    ToolProposed,
    ToolStarted,
    TurnFailed,
    TurnFinished,
)

#: Tool results are summarised, not dumped. A 5000-line grep in the scrollback
#: costs the user the rest of the turn.
TOOL_PREVIEW_CHARS = 240


@dataclass
class RenderOutcome:
    """What the REPL needs after a turn, without re-reading the events."""

    response: str = ""
    ok: bool = True
    error_code: str = ""
    error_message: str = ""
    interrupted: bool = False
    thinking_seconds: float = 0.0
    tools_run: List[str] = field(default_factory=list)
    usage: dict = field(default_factory=dict)


class SessionRenderer:
    """Turns events into terminal output.

    `write` takes already-styled text and is the only way anything reaches the
    screen, so a test can capture every byte by passing a list's append. The
    same is true of `stop_spinner`: the REPL owns the spinner thread, and the
    renderer only says when it is no longer wanted.
    """

    def __init__(
        self,
        *,
        write: Callable[[str], None],
        write_markup: Optional[Callable[[str], None]] = None,
        stop_spinner: Optional[Callable[[], None]] = None,
        content_filter: Any = None,
        show_tools: bool = True,
    ) -> None:
        self.write = write
        self.write_markup = write_markup or write
        self.stop_spinner = stop_spinner or (lambda: None)
        self.content_filter = content_filter
        self.show_tools = show_tools

    # ── filtering ─────────────────────────────────────────────────────────

    def _filtered(self, text: str) -> str:
        """Run text through the mode's filter, if one is installed.

        Filters are duck-typed the way the baseline used them: anything with a
        `filter`/`process`/`__call__` that returns a string. A filter that
        raises is bypassed rather than allowed to break the turn — losing the
        highlighting is recoverable, losing the answer is not.
        """
        f = self.content_filter
        if f is None:
            return text
        # `write` first: that is this codebase's convention.
        # `_CodeFenceFilter` and `_SyntaxHighlightFilter` are stateful stream
        # filters — stream_response() calls filter.write(chunk) and prints what
        # comes back. Checking only for `filter`/`process`/`__call__`, as the
        # first version did, meant the REPL's actual filters were skipped
        # entirely and code fences would have streamed through raw.
        for attr in ("write", "filter", "process"):
            method = getattr(f, attr, None)
            if callable(method):
                try:
                    result = method(text)
                    return text if result is None else str(result)
                except Exception:
                    return text
        if callable(f):
            try:
                result = f(text)
                return text if result is None else str(result)
            except Exception:
                return text
        return text

    def _flush_filter(self) -> None:
        """Release whatever the filter is still holding.

        `_CodeFenceFilter` and `_SyntaxHighlightFilter` buffer, because a fence
        marker can straddle a chunk boundary — write("SESSION_PATH_OK")
        returns "" and the text comes back on a later call. Without a flush at
        the end of the stream the tail is simply lost, and for an answer
        shorter than the buffer that means the whole answer: a real
        session_v1 turn printed "Thought for 0.5s" and then the prompt again,
        with the model's reply nowhere on screen.
        """
        f = self.content_filter
        if f is None:
            return
        flush = getattr(f, "flush", None)
        if not callable(flush):
            return
        try:
            remaining = flush()
        except Exception:
            return
        if remaining:
            self.write(str(remaining))

    # ── the loop ──────────────────────────────────────────────────────────

    async def render(self, events) -> RenderOutcome:
        outcome = RenderOutcome()
        first_text_seen = False
        thinking_started: Optional[float] = None
        saw_terminal = False

        async for event in events:
            if isinstance(event, ThinkingDelta):
                if thinking_started is None:
                    thinking_started = time.monotonic()
                continue

            if isinstance(event, TextDelta):
                if not first_text_seen:
                    first_text_seen = True
                    self.stop_spinner()
                    if thinking_started is not None:
                        outcome.thinking_seconds = time.monotonic() - thinking_started
                        self.write_markup(
                            f"[dim]Thought for {outcome.thinking_seconds:.1f}s[/dim]\n"
                        )
                text = self._filtered(event.text)
                if text:
                    self.write(text)
                continue

            if isinstance(event, ToolProposed):
                self.stop_spinner()
                if self.show_tools:
                    self.write_markup(
                        f"\n[dim]· {event.tool_name}({event.preview})[/dim]\n"
                    )
                continue

            if isinstance(event, ToolStarted):
                outcome.tools_run.append(event.tool_name)
                continue

            if isinstance(event, ToolFinished):
                if self.show_tools:
                    self.write_markup(self._tool_summary(event))
                continue

            if isinstance(event, StatusChanged):
                if event.text:
                    self.write_markup(f"[dim]{event.text}[/dim]\n")
                continue

            if isinstance(event, TurnFinished):
                saw_terminal = True
                self._flush_filter()
                self.stop_spinner()
                outcome.response = event.response
                outcome.usage = dict(event.usage)
                outcome.ok = True
                continue

            if isinstance(event, TurnFailed):
                saw_terminal = True
                self._flush_filter()
                self.stop_spinner()
                outcome.ok = False
                outcome.error_code = event.error_code
                outcome.error_message = event.message
                if event.error_code == "cancelled":
                    outcome.interrupted = True
                    self.write_markup("\n[dim][Interrupted][/dim]\n")
                else:
                    self.write_markup(f"\n[red]Error: {event.message}[/red]\n")
                continue

        if not saw_terminal:
            self._flush_filter()
            # The session contracts to emit one terminal event. Saying nothing
            # here would leave the REPL showing a finished-looking turn that
            # never finished.
            self.stop_spinner()
            outcome.ok = False
            outcome.error_code = "no_terminal_event"
            outcome.error_message = "the turn ended without a terminal event"
            self.write_markup("\n[red]Error: the turn ended unexpectedly[/red]\n")

        return outcome

    def _tool_summary(self, event: ToolFinished) -> str:
        if event.success:
            body = (event.preview or "").strip().splitlines()
            head = body[0][:TOOL_PREVIEW_CHARS] if body else ""
            more = f" (+{len(body) - 1} lines)" if len(body) > 1 else ""
            return f"[dim]  ✓ {event.tool_name}{(': ' + head) if head else ''}{more}[/dim]\n"
        # A refusal and a failure read differently for the same reason the
        # runtime keeps them apart: one is worth retrying, the other is not.
        reason = (event.error or "").strip()
        if reason.lower().startswith("permission denied"):
            return f"[yellow]  ⊘ {event.tool_name}: {reason}[/yellow]\n"
        return f"[red]  ✗ {event.tool_name}: {reason or 'failed'}[/red]\n"
