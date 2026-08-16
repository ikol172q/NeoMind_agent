"""Render a turn's runtime events into a Telegram conversation.

The Telegram half of Phase 5, and the counterpart to `cli/session_renderer.py`.
`AgentSession` decides what happened; this decides how it looks in a chat
window — which for Telegram means editing one message in place as tokens
arrive, rather than printing a stream.

What it has to preserve, from `_ask_llm_stream_normal`:

  * a placeholder message goes out first, so the user sees the turn start
  * that message is edited on an interval, not per token — Telegram rate-limits
    edits, and a token-by-token edit loop gets the bot throttled
  * past a length threshold the edits stop and the remainder is sent as fresh
    messages, because 4096 characters is a hard limit on a single message
  * an error rewrites the placeholder rather than leaving "💭 ..." forever

It does not import telegram. Everything that touches the network is a callable
the adapter passes in, which is what lets these paths be tested without a bot
token, a chat, or a network — the old loop could only be exercised against a
live Telegram.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, List, Optional

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

#: Seconds between edits of the live message. Matches the existing loop.
DEFAULT_EDIT_INTERVAL = 2.5

#: Stop editing beyond this and switch to new messages. Telegram's hard limit
#: is 4096; the margin leaves room for the suffix the adapter may append.
EDIT_CEILING = 3900

#: What the user sees while the model is still thinking.
PLACEHOLDER = "💭 ..."


@dataclass
class TelegramRenderOutcome:
    """What the adapter needs after the turn, without replaying the events."""

    response: str = ""
    ok: bool = True
    error_code: str = ""
    error_message: str = ""
    interrupted: bool = False
    tools_run: List[str] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    edits: int = 0
    overflowed: bool = False


class TelegramRenderer:
    """Turns runtime events into edits of a single Telegram message.

    `edit` and `send` are injected so the whole render path is testable
    offline. `now` is injected for the same reason — the throttle is time-based
    and a test that has to sleep 2.5 seconds per assertion is a test nobody
    runs.
    """

    def __init__(
        self,
        *,
        edit: Callable[[str], Awaitable[Any]],
        send: Callable[[str], Awaitable[Any]],
        edit_interval: float = DEFAULT_EDIT_INTERVAL,
        show_tools: bool = True,
        now: Optional[Callable[[], float]] = None,
    ) -> None:
        self._edit = edit
        self._send = send
        self.edit_interval = edit_interval
        self.show_tools = show_tools
        self._now = now or time.monotonic

    async def render(self, events) -> TelegramRenderOutcome:
        outcome = TelegramRenderOutcome()
        buffer = ""
        tool_notes: List[str] = []
        last_edit = 0.0
        overflow_from = 0

        async def flush(force: bool = False) -> None:
            """Edit the live message, subject to the interval and the ceiling."""
            nonlocal last_edit, overflow_from
            body = self._compose(buffer, tool_notes)
            if not body:
                return
            if len(body) > EDIT_CEILING:
                # Past the ceiling the live message is frozen at whatever it
                # last showed, and the rest goes out as new messages. Editing
                # beyond the limit fails outright, which used to strand the
                # tail of a long answer.
                outcome.overflowed = True
                tail = buffer[overflow_from:]
                if force and tail.strip():
                    await self._send(tail)
                    overflow_from = len(buffer)
                return
            now = self._now()
            if not force and (now - last_edit) < self.edit_interval:
                return
            last_edit = now
            outcome.edits += 1
            await self._edit(body)

        async for event in events:
            if isinstance(event, ThinkingDelta):
                # Reasoning does not go into the chat. The placeholder already
                # says the turn is alive, and a transcript full of the model
                # talking to itself is not what a chat window is for.
                continue

            if isinstance(event, TextDelta):
                buffer += event.text
                await flush()
                continue

            if isinstance(event, ToolProposed):
                if self.show_tools:
                    tool_notes.append(f"🔧 {event.tool_name}")
                    await flush(force=True)
                continue

            if isinstance(event, ToolStarted):
                outcome.tools_run.append(event.tool_name)
                continue

            if isinstance(event, ToolFinished):
                if self.show_tools and tool_notes:
                    mark = "✓" if event.success else ("⊘" if self._denied(event) else "✗")
                    tool_notes[-1] = f"🔧 {event.tool_name} {mark}"
                    await flush(force=True)
                continue

            if isinstance(event, StatusChanged):
                if event.text:
                    tool_notes.append(f"ℹ️ {event.text}")
                    await flush(force=True)
                continue

            if isinstance(event, TurnFinished):
                outcome.response = event.response
                outcome.usage = dict(event.usage)
                outcome.ok = True
                if event.response and not buffer:
                    # A turn whose text arrived only in the final event — a
                    # tool-only round, or a provider that did not stream.
                    buffer = event.response
                await flush(force=True)
                return outcome

            if isinstance(event, TurnFailed):
                outcome.ok = False
                outcome.error_code = event.error_code
                outcome.error_message = event.message
                outcome.interrupted = event.error_code == "cancelled"
                label = (
                    "⏹ 已中断"
                    if outcome.interrupted
                    else f"⚠️ {event.error_code}: {event.message[:200]}"
                )
                await self._edit(self._compose(buffer, tool_notes, footer=label) or label)
                outcome.edits += 1
                return outcome

        # No terminal event. The session contracts to emit one, so this is a
        # broken stream rather than a quiet turn, and the user is told instead
        # of being left with "💭 ...".
        outcome.ok = False
        outcome.error_code = "no_terminal_event"
        outcome.error_message = "the turn ended without a terminal event"
        await self._edit(
            self._compose(buffer, tool_notes, footer="⚠️ 回合异常结束") or "⚠️ 回合异常结束"
        )
        outcome.edits += 1
        return outcome

    @staticmethod
    def _denied(event: ToolFinished) -> bool:
        return (event.error or "").lower().startswith("permission denied")

    @staticmethod
    def _compose(buffer: str, tool_notes: List[str], footer: str = "") -> str:
        parts = []
        if tool_notes:
            parts.append("\n".join(tool_notes))
        text = buffer.strip()
        if text:
            parts.append(text)
        if footer:
            parts.append(footer)
        return "\n\n".join(parts).strip()
