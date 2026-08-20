"""Phase 5 — the bot's side of the session path.

The renderer and the composition root are tested on their own; this covers the
seam between them and `telegram_bot.py`, which is where the Phase 4 migration
kept producing defects that no unit test could see: a switch that read the
wrong variable, a callback that dropped the answer, history written twice.
"""

from __future__ import annotations

import asyncio
import os
from unittest import mock

import pytest

from agent.integration import telegram_bot as tb


class TestRollbackSwitch:
    """One switch per surface (D8), read per call so flipping it needs a
    container restart and not a rebuild."""

    def test_the_default_is_the_session_path(self, monkeypatch):
        """The default belongs in the code, not only in docker-compose.yml.
        With it only there, the bot ran the migrated path in its container and
        the legacy one anywhere else."""
        monkeypatch.delenv("NEOMIND_TELEGRAM", raising=False)
        assert tb._session_path_enabled() is True

    def test_session_enables_the_new_path(self, monkeypatch):
        monkeypatch.setenv("NEOMIND_TELEGRAM", "session")
        assert tb._session_path_enabled() is True

    def test_the_value_is_read_case_insensitively_and_trimmed(self, monkeypatch):
        monkeypatch.setenv("NEOMIND_TELEGRAM", "  Session  ")
        assert tb._session_path_enabled() is True

    def test_only_the_exact_word_legacy_reverts(self, monkeypatch):
        """A typo must not silently revert to the unmigrated path — the
        rollback is deliberate, so it has to be spelled."""
        monkeypatch.setenv("NEOMIND_TELEGRAM", "legcy")
        assert tb._session_path_enabled() is True
        monkeypatch.setenv("NEOMIND_TELEGRAM", "legacy")
        assert tb._session_path_enabled() is False

    def test_it_is_not_cached_at_import(self, monkeypatch):
        monkeypatch.setenv("NEOMIND_TELEGRAM", "legacy")
        assert tb._session_path_enabled() is False
        monkeypatch.setenv("NEOMIND_TELEGRAM", "session")
        assert tb._session_path_enabled() is True


class FakeMessage:
    def __init__(self):
        self.edits = []
        self.sent = []
        self.deleted = False

    async def edit_text(self, text, **kwargs):
        self.edits.append((text, kwargs))
        return self

    async def reply_text(self, text, **kwargs):
        self.sent.append((text, kwargs))
        return FakeMessage()


def _bot():
    """A bot object with only what the render callbacks touch."""
    bot = tb.NeoMindTelegramBot.__new__(tb.NeoMindTelegramBot)
    bot.config = mock.MagicMock()
    bot.config.max_message_length = 4096
    return bot


class TestRenderCallbacks:

    def test_a_streaming_edit_gets_a_cursor(self):
        bot, live = _bot(), FakeMessage()
        edit, _ = bot._telegram_render_callbacks(FakeMessage(), live)
        asyncio.run(edit("half an answer", False))
        assert live.edits[0][0].endswith(" ▍")

    def test_the_final_edit_has_no_cursor(self):
        """A finished answer that keeps blinking reads as still generating."""
        bot, live = _bot(), FakeMessage()
        edit, _ = bot._telegram_render_callbacks(FakeMessage(), live)
        asyncio.run(edit("the whole answer", True))
        assert not live.edits[0][0].endswith("▍")

    def test_the_search_footer_lands_only_on_the_final_edit(self):
        bot, live = _bot(), FakeMessage()
        edit, _ = bot._telegram_render_callbacks(
            FakeMessage(), live, search_footer="\n\n<i>via search</i>",
        )
        asyncio.run(edit("partial", False))
        asyncio.run(edit("complete", True))
        assert "via search" not in live.edits[0][0]
        assert "via search" in live.edits[1][0]

    def test_markdown_becomes_html(self):
        bot, live = _bot(), FakeMessage()
        edit, _ = bot._telegram_render_callbacks(FakeMessage(), live)
        asyncio.run(edit("**bold**", True))
        assert "<b>" in live.edits[0][0]

    def test_html_telegram_rejects_falls_back_to_plain_text(self):
        """Losing formatting is acceptable; losing the answer is not."""
        bot = _bot()

        class Picky(FakeMessage):
            async def edit_text(self, text, **kwargs):
                if kwargs.get("parse_mode"):
                    raise RuntimeError("Can't parse entities")
                self.edits.append((text, kwargs))
                return self

        live = Picky()
        edit, _ = bot._telegram_render_callbacks(FakeMessage(), live)
        asyncio.run(edit("the answer <unclosed", True))
        assert live.edits, "the plain-text retry must still deliver the answer"
        assert "the answer" in live.edits[0][0]

    def test_a_streaming_edit_that_fails_is_not_retried(self):
        """Retrying mid-stream stacks latency onto the next token; the final
        edit is the one that has to land."""
        bot, live = _bot(), FakeMessage()
        edit, _ = bot._telegram_render_callbacks(FakeMessage(), live)
        with mock.patch.object(
            tb.NeoMindTelegramBot, "_safe_edit", new=mock.AsyncMock(return_value=False)
        ) as safe_edit:
            asyncio.run(edit("partial", False))
        assert safe_edit.call_args.kwargs["max_retries"] == 0

    def test_overflow_goes_through_send_long_message(self):
        bot = _bot()
        sent = []
        bot._send_long_message = mock.AsyncMock(
            side_effect=lambda msg, text, **kw: sent.append(text)
        )
        _, send = bot._telegram_render_callbacks(FakeMessage(), FakeMessage())
        asyncio.run(send("the tail of a long answer"))
        assert sent == ["the tail of a long answer"]


class TestRegistryReuse:

    def test_the_registry_comes_from_the_agentic_loop(self):
        """Registered once, in one place. A second registration would drift."""
        bot = _bot()
        registry = object()
        bot._get_agentic_loop = lambda: mock.Mock(registry=registry)
        assert bot._session_registry() is registry

    def test_a_missing_loop_does_not_raise(self):
        bot = _bot()
        bot._get_agentic_loop = lambda: None
        assert bot._session_registry() is None


class TestHistoryIsNotWrittenTwice:
    """The legacy path stored the user message itself; the session does it.
    Doing both sends the question to the model twice."""

    def test_the_session_path_does_not_pre_store_the_user_message(self):
        import inspect

        source = inspect.getsource(
            tb.NeoMindTelegramBot._ask_llm_stream_session
        )
        assert 'add_message(chat_id, "user"' not in source
        assert "TelegramHistoryStore" in source

    def test_history_is_read_before_the_turn_runs(self):
        import inspect

        source = inspect.getsource(tb.NeoMindTelegramBot._ask_llm_stream_session)
        read_at = source.index("get_recent_history")
        run_at = source.index("run_turn")
        assert read_at < run_at

    def test_the_legacy_path_still_stores_it_itself(self):
        """The switch has to be able to go back."""
        import inspect

        source = inspect.getsource(tb.NeoMindTelegramBot._ask_llm_stream_normal)
        assert 'add_message(chat_id, "user"' in source


class TestProcessAndReplyDispatch:

    def _reply_source(self):
        import inspect

        return inspect.getsource(tb.NeoMindTelegramBot._process_and_reply)

    def test_both_paths_are_reachable_from_the_dispatcher(self):
        source = self._reply_source()
        assert "_ask_llm_stream_session" in source
        assert "_ask_llm_stream_normal" in source
        assert "_session_path_enabled()" in source

    def test_thinking_mode_is_untouched_by_this_migration(self):
        """`_ask_llm_streaming` is a separate surface path and is not part of
        this slice; the switch must not divert it."""
        source = self._reply_source()
        thinking_at = source.index("_ask_llm_streaming")
        switch_at = source.index("_session_path_enabled()")
        assert thinking_at < switch_at

    def test_a_failed_turn_reacts_with_the_error_marker(self):
        source = self._reply_source()
        assert '"✅" if ok else "❌"' in source
