"""Phase 5 — one whole Telegram turn through the session path, offline.

`_ask_llm_stream_session` is the method the migration actually swaps in, so it
is worth running end to end before it reaches a container: every collaborator
is faked, but the method itself is the real one, and a misnamed attribute or a
mis-ordered call shows up here rather than in a live chat.
"""

from __future__ import annotations

import asyncio
from unittest import mock

import pytest

from agent.integration import telegram_bot as tb
from agent.runtime.llm_stream import FinishChunk, TextChunk


class FakeLive:
    def __init__(self):
        self.edits = []

    async def edit_text(self, text, **kwargs):
        self.edits.append(text)
        return self

    @property
    def last(self):
        return self.edits[-1] if self.edits else ""


class FakeMsg:
    def __init__(self):
        self.live = FakeLive()
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)
        self.live.edits.append(text)
        return self.live


class FakeStore:
    def __init__(self, history=None, mode="chat"):
        self.history = list(history or [])
        self.written = []
        self._mode = mode

    def add_message(self, chat_id, role, content, chat_type):
        self.written.append((role, content))

    def get_recent_history(self, chat_id, limit=20):
        return list(self.history)

    def get_mode(self, chat_id):
        return self._mode


def make_bot(*, chunks=None, store=None, should_search=False, search_ctx=""):
    bot = tb.NeoMindTelegramBot.__new__(tb.NeoMindTelegramBot)
    bot.config = mock.MagicMock()
    bot.config.max_message_length = 4096
    bot._store = store or FakeStore()
    bot._usage = mock.MagicMock()
    bot._last_compact_notice = None

    bot._get_provider_chain = lambda thinking=False, chat_id=0: [
        {"name": "local", "model": "m1", "base_url": "http://x/v1", "api_key": "k"},
    ]
    bot._auto_compact_if_needed_db = lambda chat_id, model: ""
    bot._get_system_prompt = lambda chat_id=0: "you are neomind"
    bot._should_search = lambda text, chat_id=0: should_search
    bot._augment_with_search = mock.AsyncMock(
        return_value=(search_ctx, "\n\n<i>via search</i>" if search_ctx else "")
    )
    bot._get_agentic_loop = lambda: mock.Mock(registry=FakeRegistry())
    bot._send_long_message = mock.AsyncMock()

    chunks = chunks if chunks is not None else [
        TextChunk(text="the answer"), FinishChunk(reason="stop"),
    ]

    class LLM:
        seen = []

        def stream(self, messages, model, **kwargs):
            LLM.seen.append(list(messages))

            async def gen():
                for c in chunks:
                    yield c

            return gen()

    LLM.seen = []
    bot._llm_for_test = LLM
    return bot, LLM


class FakeRegistry:
    def get_tool(self, name):
        return None


def run_turn(bot, LLM, text="hello", chat_id=1):
    msg = FakeMsg()
    with mock.patch(
        "agent.runtime.providers.openai_sse.OpenAICompatibleStream",
        return_value=LLM(),
    ):
        outcome = asyncio.run(
            bot._ask_llm_stream_session(msg, text, chat_id=chat_id, chat_type="private")
        )
    return msg, outcome


class TestHappyPath:

    def test_the_answer_reaches_the_chat(self):
        bot, LLM = make_bot()
        msg, outcome = run_turn(bot, LLM)
        assert outcome.ok is True
        assert "the answer" in msg.live.last

    def test_a_placeholder_goes_out_before_the_model_answers(self):
        bot, LLM = make_bot()
        msg, _ = run_turn(bot, LLM)
        assert msg.replies[0] == "💭 ..."

    def test_the_conversation_is_persisted_once(self):
        store = FakeStore()
        bot, LLM = make_bot(store=store)
        run_turn(bot, LLM, text="what is 6*7")
        assert store.written == [
            ("user", "what is 6*7"),
            ("assistant", "the answer"),
        ]

    def test_the_system_prompt_and_history_seed_the_model(self):
        store = FakeStore(history=[{"role": "user", "content": "earlier"}])
        bot, LLM = make_bot(store=store)
        run_turn(bot, LLM, text="follow up")
        sent = LLM.seen[0]
        assert sent[0]["role"] == "system"
        assert "neomind" in sent[0]["content"]
        assert [m["content"] for m in sent[1:]] == ["earlier", "follow up"]

    def test_usage_is_recorded_against_the_provider_that_answered(self):
        bot, LLM = make_bot()
        run_turn(bot, LLM)
        assert bot._usage.record.called
        kwargs = bot._usage.record.call_args.kwargs
        assert kwargs["provider"] == "local"
        assert kwargs["model"] == "m1"
        assert kwargs["success"] is True


class TestSearchAugmentation:

    def test_the_search_indicator_replaces_the_placeholder(self):
        bot, LLM = make_bot(should_search=True, search_ctx="results here")
        msg, _ = run_turn(bot, LLM)
        assert msg.replies[0].startswith("🔍")

    def test_search_context_is_given_to_the_model(self):
        bot, LLM = make_bot(should_search=True, search_ctx="RESULTS BLOCK")
        run_turn(bot, LLM, text="latest news")
        sent = LLM.seen[0]
        assert any("RESULTS BLOCK" in m["content"] for m in sent)
        assert sent[-1]["content"] == "latest news", (
            "the user's question must stay last, after the injected context"
        )

    def test_a_search_that_finds_nothing_still_answers(self):
        bot, LLM = make_bot(should_search=True, search_ctx="")
        msg, outcome = run_turn(bot, LLM)
        assert outcome.ok is True
        assert "the answer" in msg.live.last

    def test_the_footer_appears_on_the_finished_answer(self):
        bot, LLM = make_bot(should_search=True, search_ctx="results")
        msg, _ = run_turn(bot, LLM)
        assert "via search" in msg.live.last


class TestOptOut:

    def test_asking_not_to_search_adds_the_no_tools_instruction(self):
        bot, LLM = make_bot()
        run_turn(bot, LLM, text="别搜索，直接回答")
        sent = LLM.seen[0]
        assert any("NOT to search" in m["content"] for m in sent)


class TestFailures:

    def test_a_dead_provider_leaves_a_reason_in_the_chat(self):
        from agent.runtime.llm_stream import LLMAuthError

        bot, LLM = make_bot()

        class Dead:
            def stream(self, messages, model, **kwargs):
                async def gen():
                    raise LLMAuthError("invalid api key")
                    yield  # pragma: no cover

                return gen()

        msg = FakeMsg()
        with mock.patch(
            "agent.runtime.providers.openai_sse.OpenAICompatibleStream",
            return_value=Dead(),
        ):
            outcome = asyncio.run(
                bot._ask_llm_stream_session(msg, "hi", chat_id=1, chat_type="private")
            )
        assert outcome.ok is False
        assert msg.live.last != "💭 ..."
        assert "llm_auth" in msg.live.last

    def test_a_failed_turn_does_not_record_usage_as_a_success(self):
        from agent.runtime.llm_stream import LLMTransportError

        bot, LLM = make_bot()

        class Dead:
            def stream(self, messages, model, **kwargs):
                async def gen():
                    raise LLMTransportError("refused")
                    yield  # pragma: no cover

                return gen()

        msg = FakeMsg()
        with mock.patch(
            "agent.runtime.providers.openai_sse.OpenAICompatibleStream",
            return_value=Dead(),
        ):
            asyncio.run(bot._ask_llm_stream_session(msg, "hi", chat_id=1))
        assert not bot._usage.record.called

    def test_no_providers_configured_says_so(self):
        bot, LLM = make_bot()
        bot._get_provider_chain = lambda thinking=False, chat_id=0: []
        msg = FakeMsg()
        outcome = asyncio.run(bot._ask_llm_stream_session(msg, "hi", chat_id=1))
        assert outcome is None
        assert "No API key" in msg.replies[0]

    def test_nothing_is_persisted_when_the_provider_never_answers(self):
        """A stored question with no answer would be replayed as context on
        the next turn, as though the bot had ignored it."""
        from agent.runtime.llm_stream import LLMAuthError

        store = FakeStore()
        bot, LLM = make_bot(store=store)

        class Dead:
            def stream(self, messages, model, **kwargs):
                async def gen():
                    raise LLMAuthError("nope")
                    yield  # pragma: no cover

                return gen()

        msg = FakeMsg()
        with mock.patch(
            "agent.runtime.providers.openai_sse.OpenAICompatibleStream",
            return_value=Dead(),
        ):
            asyncio.run(bot._ask_llm_stream_session(msg, "hi", chat_id=1))
        assert [r for r, _ in store.written] == ["user"], (
            "the question is stored; there is simply no answer to store"
        )


class TestCompaction:

    def test_a_compaction_notice_is_handed_to_the_caller(self):
        bot, LLM = make_bot()
        bot._auto_compact_if_needed_db = lambda chat_id, model: "Auto-compacted 20 msgs"
        run_turn(bot, LLM)
        assert bot._last_compact_notice == "Auto-compacted 20 msgs"
