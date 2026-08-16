"""Phase 4 task 5 — history stays one list, whoever writes it.

The session path builds a fresh AgentSession per turn, seeded from
`chat.conversation_history`, and writes new messages back through a store
adapter. That is only correct if everything else that rewrites history —
`/load`, `/clear`, `/compact`, `--resume` — lands in the same list, because a
session holding its own copy would prompt the model with a conversation the
user can no longer see.

These assert the wiring rather than a live turn: the store adapter and the
seeding are where a second copy would appear.
"""

from __future__ import annotations

import sys

import pytest

sys.argv = ["x"]


@pytest.fixture
def interface():
    from unittest import mock

    from cli.neomind_interface import NeoMindInterface

    obj = NeoMindInterface.__new__(NeoMindInterface)
    obj.chat = mock.MagicMock()
    obj.chat.conversation_history = []
    obj.chat.mode = "coding"
    return obj


class TestStoreAdapter:

    def test_appends_land_in_the_agent_list(self, interface):
        store = interface._HistoryStore(interface.chat)
        store.append("ses_1", {"role": "user", "content": "hi"})
        assert interface.chat.conversation_history == [{"role": "user", "content": "hi"}]

    def test_internal_flags_are_not_persisted(self, interface):
        """`_tool_result` is a marker the session uses to find its own
        messages. Writing it into the conversation would leak runtime
        bookkeeping into something the user can read back and resume from."""
        store = interface._HistoryStore(interface.chat)
        store.append("ses_1", {"role": "user", "content": "x", "_tool_result": True})
        assert interface.chat.conversation_history[0] == {"role": "user", "content": "x"}

    def test_load_reads_the_same_list(self, interface):
        interface.chat.conversation_history = [{"role": "user", "content": "earlier"}]
        store = interface._HistoryStore(interface.chat)
        assert store.load("ses_1") == [{"role": "user", "content": "earlier"}]

    def test_a_replaced_history_is_what_the_next_load_returns(self, interface):
        """`/load` and `--resume` both assign a new list. The adapter must read
        through to the attribute, not hold the list it saw at construction."""
        store = interface._HistoryStore(interface.chat)
        interface.chat.conversation_history = [{"role": "user", "content": "loaded"}]
        assert store.load("ses_1")[0]["content"] == "loaded"


class TestPerTurnSeeding:

    def test_the_session_is_seeded_from_the_current_history(self, interface, monkeypatch):
        """Built per turn, not once. A long-lived session would keep a copy
        while /compact, /clear and /load rewrite the agent's list underneath
        it, and the two would disagree silently."""
        import inspect

        from cli.neomind_interface import NeoMindInterface

        source = inspect.getsource(NeoMindInterface._build_turn_session)
        assert "history=list(self.chat.conversation_history)" in source
        assert "store=self._HistoryStore(self.chat)" in source

    def test_the_turn_path_builds_a_session_every_time(self):
        import inspect

        from cli.neomind_interface import NeoMindInterface

        source = inspect.getsource(NeoMindInterface._stream_and_render_session)
        assert source.count("self._build_turn_session()") == 1, (
            "one construction per turn; caching it would reintroduce the copy"
        )


class TestSessionWritesThroughTheStore:

    def test_agent_session_appends_to_its_store(self):
        """The session is the only writer during a turn, and it writes through
        whatever store it was given."""
        import asyncio

        from agent.runtime.llm_stream import FinishChunk, TextChunk
        from agent.runtime.session import AgentSession

        written = []

        class Store:
            def append(self, session_id, message):
                written.append(dict(message))

            def load(self, session_id):
                return []

        class LLM:
            def stream(self, messages, model, **kwargs):
                async def gen():
                    yield TextChunk(text="hello")
                    yield FinishChunk(reason="stop")

                return gen()

        session = AgentSession(llm=LLM(), executor=None, model="m", store=Store())

        async def go():
            return [e async for e in session.run_turn("hi")]

        asyncio.run(go())
        assert [m["role"] for m in written] == ["user", "assistant"]
        assert written[0]["content"] == "hi"
        assert written[1]["content"] == "hello"

    def test_a_failing_store_does_not_lose_the_turn(self):
        """In-memory history stays authoritative for the turn in progress; a
        store that raises must not take the answer down with it."""
        import asyncio

        from agent.runtime.events import TurnFinished
        from agent.runtime.llm_stream import FinishChunk, TextChunk
        from agent.runtime.session import AgentSession

        class Store:
            def append(self, session_id, message):
                raise OSError("disk full")

            def load(self, session_id):
                return []

        class LLM:
            def stream(self, messages, model, **kwargs):
                async def gen():
                    yield TextChunk(text="answer")
                    yield FinishChunk(reason="stop")

                return gen()

        session = AgentSession(llm=LLM(), executor=None, model="m", store=Store())

        async def go():
            return [e async for e in session.run_turn("hi")]

        events = asyncio.run(go())
        finished = [e for e in events if isinstance(e, TurnFinished)]
        assert finished and finished[0].response == "answer"
