"""Phase 5 — the Telegram event consumer.

Every network call is an injected callable and the clock is injected too, so
these assert the exact sequence of edits a user would see, offline. The loop
this replaces could only be exercised against a live bot, which is why its
throttling and overflow behaviour had no tests at all.
"""

from __future__ import annotations

import asyncio

import pytest

from agent.integration.telegram_renderer import (
    EDIT_CEILING,
    TelegramRenderer,
    TelegramRenderOutcome,
)
from agent.runtime.events import (
    StatusChanged,
    TextDelta,
    ThinkingDelta,
    ToolFinished,
    ToolProposed,
    ToolStarted,
    TurnFailed,
    TurnFinished,
)


def ev(cls, seq, **kw):
    return cls(session_id="s", turn_id="t", sequence=seq, **kw)


async def stream(events):
    for e in events:
        yield e


class Chat:
    """Records what the bot would have done to the conversation."""

    def __init__(self):
        self.edits = []
        self.finals = []
        self.sends = []
        self.clock = 1000.0

    async def edit(self, text, final=False):
        self.edits.append(text)
        self.finals.append(final)

    async def send(self, text):
        self.sends.append(text)

    def tick(self, seconds):
        self.clock += seconds

    def now(self):
        return self.clock

    def renderer(self, **kw):
        return TelegramRenderer(
            edit=self.edit, send=self.send, now=self.now, **kw
        )

    @property
    def last(self):
        return self.edits[-1] if self.edits else ""


def run(renderer, events):
    return asyncio.run(renderer.render(stream(events)))


class TestEditThrottling:
    """Telegram rate-limits edits. A token-by-token loop gets the bot throttled,
    so the interval is the point, not an optimisation."""

    def test_rapid_deltas_do_not_each_cause_an_edit(self):
        chat = Chat()
        r = chat.renderer(edit_interval=2.5)
        events = [ev(TextDelta, i, text=f"{i} ") for i in range(20)]
        events.append(ev(TurnFinished, 99, response="".join(f"{i} " for i in range(20))))
        outcome = run(r, events)
        assert outcome.edits <= 2, f"{outcome.edits} edits for 20 deltas"

    def test_time_passing_releases_a_further_edit(self):
        """The throttle is a floor on the gap, not a cap on the count."""
        chat = Chat()
        renderer = chat.renderer(edit_interval=2.5)

        async def go():
            async def paced():
                yield ev(TextDelta, 0, text="one ")
                chat.tick(3.0)
                yield ev(TextDelta, 1, text="two ")
                chat.tick(3.0)
                yield ev(TextDelta, 2, text="three")
                yield ev(TurnFinished, 3, response="one two three")

            return await renderer.render(paced())

        outcome = asyncio.run(go())
        assert outcome.edits >= 3, f"only {outcome.edits} edits across 6s"
        assert "one two three" in chat.last

    def test_the_final_edit_always_happens(self):
        """Whatever the throttle did, the user must end up seeing the answer."""
        chat = Chat()
        outcome = run(chat.renderer(edit_interval=9999), [
            ev(TextDelta, 0, text="the answer"),
            ev(TurnFinished, 1, response="the answer"),
        ])
        assert "the answer" in chat.last
        assert outcome.ok is True


class TestFinalFlag:
    """The adapter renders a streaming edit and the last one differently — a
    cursor while tokens arrive, the search-source footer at the end. It can
    only do that if the renderer says which is which."""

    def test_exactly_one_edit_is_marked_final(self):
        chat = Chat()
        run(chat.renderer(edit_interval=0), [
            ev(TextDelta, 0, text="one "),
            ev(TextDelta, 1, text="two"),
            ev(TurnFinished, 2, response="one two"),
        ])
        assert chat.finals.count(True) == 1
        assert chat.finals[-1] is True

    def test_a_forced_tool_edit_is_not_final(self):
        """`force` bypasses the throttle; it does not mean the turn is over.
        Conflating them puts the closing footer on every tool announcement."""
        chat = Chat()
        run(chat.renderer(), [
            ev(ToolProposed, 0, call_id="c", tool_name="Read", preview="p"),
            ev(ToolFinished, 1, call_id="c", tool_name="Read", success=True, preview="x"),
            ev(TextDelta, 2, text="answer"),
            ev(TurnFinished, 3, response="answer"),
        ])
        assert chat.finals.count(True) == 1, chat.finals

    def test_an_error_edit_is_final(self):
        chat = Chat()
        run(chat.renderer(), [
            ev(TurnFailed, 0, error_code="llm_auth", message="bad key", retryable=False),
        ])
        assert chat.finals == [True]


class TestOverflow:
    """4096 is a hard limit on one message. Editing past it fails outright,
    which used to strand the tail of a long answer."""

    def test_a_long_answer_switches_to_new_messages(self):
        chat = Chat()
        long_text = "x" * (EDIT_CEILING + 500)
        outcome = run(chat.renderer(), [
            ev(TextDelta, 0, text=long_text),
            ev(TurnFinished, 1, response=long_text),
        ])
        assert outcome.overflowed is True
        assert chat.sends, "the tail must be sent rather than dropped"

    def test_a_short_answer_never_overflows(self):
        chat = Chat()
        outcome = run(chat.renderer(), [
            ev(TextDelta, 0, text="short"),
            ev(TurnFinished, 1, response="short"),
        ])
        assert outcome.overflowed is False
        assert not chat.sends


class TestThinkingStaysOut:

    def test_reasoning_never_reaches_the_chat(self):
        chat = Chat()
        run(chat.renderer(), [
            ev(ThinkingDelta, 0, text="internal deliberation about the prompt"),
            ev(TextDelta, 1, text="Four."),
            ev(TurnFinished, 2, response="Four."),
        ])
        joined = "".join(chat.edits) + "".join(chat.sends)
        assert "internal deliberation" not in joined
        assert "Four." in joined


class TestTools:

    def test_a_tool_is_announced_and_then_marked(self):
        chat = Chat()
        run(chat.renderer(), [
            ev(ToolProposed, 0, call_id="c", tool_name="Read", preview="p"),
            ev(ToolStarted, 1, call_id="c", tool_name="Read"),
            ev(ToolFinished, 2, call_id="c", tool_name="Read", success=True, preview="data"),
            ev(TurnFinished, 3, response="done"),
        ])
        assert "🔧 Read" in chat.last
        assert "✓" in chat.last

    def test_a_denial_is_marked_differently_from_a_failure(self):
        chat = Chat()
        run(chat.renderer(), [
            ev(ToolProposed, 0, call_id="c", tool_name="Write", preview="p"),
            ev(ToolFinished, 1, call_id="c", tool_name="Write", success=False,
               denied=True, error="tool not in session capability snapshot"),
            ev(TurnFinished, 2, response=""),
        ])
        assert "⊘" in chat.last, "a refusal should not look like a crash"

        chat2 = Chat()
        run(chat2.renderer(), [
            ev(ToolProposed, 0, call_id="c", tool_name="Read", preview="p"),
            ev(ToolFinished, 1, call_id="c", tool_name="Read", success=False,
               error="No such file"),
            ev(TurnFinished, 2, response=""),
        ])
        assert "✗" in chat2.last

    def test_tool_output_is_not_pasted_into_the_chat(self):
        chat = Chat()
        run(chat.renderer(), [
            ev(ToolProposed, 0, call_id="c", tool_name="Read", preview="p"),
            ev(ToolFinished, 1, call_id="c", tool_name="Read", success=True,
               preview="y" * 9000),
            ev(TurnFinished, 2, response="summary"),
        ])
        assert "y" * 100 not in "".join(chat.edits)


class TestOverflowSealsTheLiveMessage:
    """Found by a real 1500-word answer on the live bot.

    Once the composed body passes the ceiling, `flush` stops editing — so the
    last edit that landed was a streaming one, and the live message kept the
    "still arriving" cursor forever on a turn that had already finished.
    """

    def test_the_live_message_gets_a_final_edit_before_the_tail_is_sent(self):
        chat = Chat()
        long_text = "x" * (EDIT_CEILING + 800)
        outcome = run(chat.renderer(edit_interval=0), [
            ev(TextDelta, 0, text=long_text),
            ev(TurnFinished, 1, response=long_text),
        ])
        assert outcome.overflowed is True
        assert chat.finals.count(True) == 1, (
            "an overflowing turn still needs exactly one closing edit"
        )

    def test_the_seal_happens_only_once(self):
        chat = Chat()
        big = "y" * (EDIT_CEILING + 100)
        run(chat.renderer(edit_interval=0), [
            ev(TextDelta, 0, text=big),
            ev(ToolProposed, 1, call_id="c", tool_name="Read", preview="p"),
            ev(ToolFinished, 2, call_id="c", tool_name="Read", success=True, preview="x"),
            ev(TurnFinished, 3, response=big),
        ])
        assert chat.finals.count(True) <= 1

    def test_the_sealed_body_still_fits_telegrams_limit(self):
        chat = Chat()
        big = "z" * (EDIT_CEILING + 5000)
        run(chat.renderer(edit_interval=0), [
            ev(TextDelta, 0, text=big),
            ev(TurnFinished, 1, response=big),
        ])
        assert all(len(e) <= EDIT_CEILING for e in chat.edits), (
            "editing past the limit fails outright"
        )

    def test_a_turn_that_never_overflows_is_unaffected(self):
        chat = Chat()
        run(chat.renderer(edit_interval=0), [
            ev(TextDelta, 0, text="short"),
            ev(TurnFinished, 1, response="short"),
        ])
        assert chat.finals.count(True) == 1


class TestTerminalEvents:

    def test_a_provider_error_replaces_the_placeholder(self):
        chat = Chat()
        outcome = run(chat.renderer(), [
            ev(TurnFailed, 0, error_code="llm_auth", message="bad key", retryable=False),
        ])
        assert outcome.ok is False
        assert "llm_auth" in chat.last
        assert chat.last != "💭 ..."

    def test_cancellation_reads_as_stopped_not_failed(self):
        chat = Chat()
        outcome = run(chat.renderer(), [
            ev(TurnFailed, 0, error_code="cancelled", message="Turn cancelled.", retryable=True),
        ])
        assert outcome.interrupted is True
        assert "⏹" in chat.last

    def test_partial_text_survives_a_failure(self):
        """Whatever the model managed to say is still worth showing."""
        chat = Chat()
        run(chat.renderer(), [
            ev(TextDelta, 0, text="I was saying something"),
            ev(TurnFailed, 1, error_code="llm_timeout", message="slow", retryable=True),
        ])
        assert "I was saying something" in chat.last

    def test_a_stream_with_no_terminal_event_is_reported(self):
        chat = Chat()
        outcome = run(chat.renderer(), [ev(TextDelta, 0, text="half")])
        assert outcome.ok is False
        assert outcome.error_code == "no_terminal_event"
        assert "异常" in chat.last

    def test_a_tool_only_turn_still_shows_its_answer(self):
        """When the text arrives only in the terminal event — a provider that
        did not stream, or a round that was all tool work."""
        chat = Chat()
        run(chat.renderer(), [
            ev(ToolStarted, 0, call_id="c", tool_name="Read"),
            ev(TurnFinished, 1, response="the final answer"),
        ])
        assert "the final answer" in chat.last
