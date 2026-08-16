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

    # These used to read `inspect.getsource(...)` and assert that particular
    # substrings appeared in it. That checks spelling, not behaviour: it passes
    # for a method that contains the right words and does the wrong thing, and
    # it fails for a rename that changes nothing. It also produced two false
    # failures in a full run — `inspect.getsource` resolves a code object's
    # recorded line numbers against `linecache`, so editing the file while the
    # suite is in flight hands the test a *different method's* source, and the
    # assertion message then blames the wrong thing entirely.
    #
    # They now build a real session and look at what it holds.

    def _session_for(self, interface, monkeypatch):
        """Call the real `_build_turn_session`, stubbing only what reaches out."""
        from unittest import mock

        import cli.neomind_interface as mod

        interface.chat._resolve_provider = lambda: {
            "base_url": "http://x/v1", "api_key": "k", "name": "local",
        }
        interface.chat.api_key = "k"
        interface.chat.model = "m"
        interface.chat.mode = "coding"
        interface.chat.thinking_enabled = False
        interface._session_permission_broker = lambda: None

        with mock.patch.object(mod, "ToolRegistry", create=True):
            return interface._build_turn_session()

    def test_the_session_is_seeded_from_the_current_history(self, interface, monkeypatch):
        """Built per turn, not once. A long-lived session would keep a copy
        while /compact, /clear and /load rewrite the agent's list underneath
        it, and the two would disagree silently."""
        interface.chat.conversation_history = [
            {"role": "user", "content": "the earlier question"},
        ]
        session = self._session_for(interface, monkeypatch)
        assert [m["content"] for m in session.history] == ["the earlier question"]

    def test_a_later_turn_sees_history_written_after_the_first(self, interface, monkeypatch):
        """The actual property: two sessions built at different times disagree
        only if one is holding a stale copy."""
        interface.chat.conversation_history = [{"role": "user", "content": "first"}]
        first = self._session_for(interface, monkeypatch)
        interface.chat.conversation_history.append(
            {"role": "assistant", "content": "second"}
        )
        later = self._session_for(interface, monkeypatch)
        assert len(first.history) == 1
        assert len(later.history) == 2, (
            "a session built now must see what was written since the last one"
        )

    def test_the_session_writes_through_to_the_agents_list(self, interface, monkeypatch):
        """The store half of the same property, asserted through the session
        rather than by looking for `_HistoryStore` in the source."""
        interface.chat.conversation_history = []
        session = self._session_for(interface, monkeypatch)
        session.store.append(session.session_id, {"role": "user", "content": "written"})
        assert interface.chat.conversation_history == [
            {"role": "user", "content": "written"}
        ]


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
