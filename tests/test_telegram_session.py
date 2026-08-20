"""Phase 5 — the Telegram composition root.

The capability tests here are the point of the file. Telegram is the one
surface where the person talking to the agent is not necessarily the person
who owns the machine it runs on, and the container has the source tree
bind-mounted.
"""

from __future__ import annotations

import asyncio

import pytest

from agent.coding.tool_schema import PermissionLevel
from agent.integration.telegram_session import (
    TELEGRAM_READ_ONLY_TOOLS,
    TelegramHistoryStore,
    build_telegram_session,
    telegram_allowed_tools,
)


class FakeTool:
    def __init__(self, name, level):
        self.name = name
        self.permission_level = level


class FakeRegistry:
    def __init__(self, tools):
        self._tools = {t.name: t for t in tools}

    def get_tool(self, name):
        return self._tools.get(name)


class TestAllowlist:

    def test_only_allowlisted_tools_survive(self):
        registry = FakeRegistry([
            FakeTool("WebSearch", PermissionLevel.READ_ONLY),
            FakeTool("Bash", PermissionLevel.EXECUTE),
            FakeTool("Read", PermissionLevel.READ_ONLY),
        ])
        allowed = telegram_allowed_tools(registry)
        assert allowed == ["WebSearch"]

    def test_a_mislabelled_tool_is_still_kept_out(self):
        """The allowlist is the outer bound. A destructive tool that declares
        itself READ_ONLY does not get in just because the level check passes."""
        registry = FakeRegistry([
            FakeTool("TeamDelete", PermissionLevel.READ_ONLY),
            FakeTool("WebSearch", PermissionLevel.READ_ONLY),
        ])
        assert telegram_allowed_tools(registry) == ["WebSearch"]

    def test_a_tightened_level_drops_out_of_the_snapshot(self):
        """The level re-check is the inner bound: if WebFetch is ever
        reclassified, the allowlist alone would keep offering it."""
        registry = FakeRegistry([FakeTool("WebFetch", PermissionLevel.WRITE)])
        assert telegram_allowed_tools(registry) == []

    def test_an_unregistered_tool_is_skipped(self):
        assert telegram_allowed_tools(FakeRegistry([])) == []

    def test_filesystem_reads_are_not_offered_to_a_chat(self):
        """Headless allows Read/Glob/Grep/LS because it runs from the
        operator's own shell. A message in a group chat is not that."""
        for name in ("Read", "Glob", "Grep", "LS", "Bash", "Write", "Edit"):
            assert name not in TELEGRAM_READ_ONLY_TOOLS, name

    def test_the_allowlist_has_no_duplicates(self):
        assert len(set(TELEGRAM_READ_ONLY_TOOLS)) == len(TELEGRAM_READ_ONLY_TOOLS)


class TestPolicy:

    def _session(self, registry=None):
        registry = registry or FakeRegistry([
            FakeTool("WebSearch", PermissionLevel.READ_ONLY),
        ])

        class LLM:
            def stream(self, messages, model, **kwargs):
                async def gen():
                    if False:
                        yield None

                return gen()

        from agent.runtime.providers.fallback import ChainLink

        return build_telegram_session(
            links=[ChainLink(LLM(), "m", "local")],
            registry=registry,
            history=[],
        )

    def test_the_surface_is_not_interactive(self):
        """An ASK on Telegram either hangs the turn waiting for a prompt
        nobody will see, or gets approved by nobody. DENY is the answer."""
        session = self._session()
        assert session.executor.policy.interactive is False

    def test_auto_accept_is_off(self):
        session = self._session()
        assert session.executor.policy.auto_accept is False

    def test_a_write_is_denied_rather_than_asked(self):
        from agent.runtime.permissions import Decision

        session = self._session()
        decision, reason = session.executor.policy.evaluate(
            "WebSearch", "write", {}
        )
        assert decision is Decision.DENY

    def test_a_tool_outside_the_snapshot_is_denied_first(self):
        from agent.runtime.permissions import Decision

        session = self._session()
        decision, reason = session.executor.policy.evaluate("Bash", "read_only", {})
        assert decision is Decision.DENY
        assert "snapshot" in reason

    def test_an_allowlisted_read_is_permitted(self):
        from agent.runtime.permissions import Decision

        session = self._session()
        decision, _ = session.executor.policy.evaluate("WebSearch", "read_only", {})
        assert decision is Decision.ALLOW

    def test_the_tool_round_cap_is_short(self):
        """A chat window shows one message being edited; a long tool chain
        reads as a frozen bot."""
        assert self._session().max_tool_rounds <= 3


class TestHistoryStore:

    class FakeStore:
        def __init__(self, history=None):
            self.written = []
            self._history = history or []

        def add_message(self, chat_id, role, content, chat_type):
            self.written.append((chat_id, role, content, chat_type))

        def get_recent_history(self, chat_id, limit=20):
            return list(self._history)

    def test_messages_land_in_the_chat_store(self):
        store = self.FakeStore()
        adapter = TelegramHistoryStore(store, 42, "private")
        adapter.append("s", {"role": "user", "content": "hi"})
        adapter.append("s", {"role": "assistant", "content": "hello"})
        assert store.written == [
            (42, "user", "hi", "private"),
            (42, "assistant", "hello", "private"),
        ]

    def test_tool_results_are_not_persisted(self):
        """Transcript, not conversation. Replaying yesterday's search results
        into today's prompt spends context on stale data."""
        store = self.FakeStore()
        adapter = TelegramHistoryStore(store, 42)
        adapter.append("s", {
            "role": "user",
            "content": "[tool:WebSearch] ...",
            "_tool_result": True,
        })
        assert store.written == []

    def test_an_empty_message_is_not_written(self):
        store = self.FakeStore()
        adapter = TelegramHistoryStore(store, 42)
        adapter.append("s", {"role": "assistant", "content": ""})
        assert store.written == []

    def test_load_reads_through_to_the_store(self):
        store = self.FakeStore([{"role": "user", "content": "earlier"}])
        adapter = TelegramHistoryStore(store, 42)
        assert adapter.load("s")[0]["content"] == "earlier"

    def test_the_chat_type_is_carried(self):
        """Group and private are stored separately; losing it merges two
        conversations that belong to different people."""
        store = self.FakeStore()
        TelegramHistoryStore(store, 7, "group").append("s", {"role": "user", "content": "x"})
        assert store.written[0][3] == "group"


class TestEndToEnd:
    """One turn, no telegram and no network."""

    def test_a_turn_streams_and_persists(self):
        from agent.runtime.events import TextDelta, TurnFinished
        from agent.runtime.llm_stream import FinishChunk, TextChunk
        from agent.runtime.providers.fallback import ChainLink

        class LLM:
            def stream(self, messages, model, **kwargs):
                async def gen():
                    yield TextChunk(text="42")
                    yield FinishChunk(reason="stop")

                return gen()

        store = TestHistoryStore.FakeStore()
        session = build_telegram_session(
            links=[ChainLink(LLM(), "m", "local")],
            registry=FakeRegistry([]),
            history=[],
            store=TelegramHistoryStore(store, 1),
        )

        async def go():
            return [e async for e in session.run_turn("what is 6*7")]

        events = asyncio.run(go())
        assert any(isinstance(e, TextDelta) and e.text == "42" for e in events)
        assert isinstance(events[-1], TurnFinished)
        assert [w[1] for w in store.written] == ["user", "assistant"]

    def test_a_failing_provider_chain_ends_as_one_terminal_event(self):
        from agent.runtime.events import TurnFailed
        from agent.runtime.llm_stream import LLMAuthError
        from agent.runtime.providers.fallback import ChainLink

        class Dead:
            def stream(self, messages, model, **kwargs):
                async def gen():
                    raise LLMAuthError("bad key")
                    yield  # pragma: no cover

                return gen()

        session = build_telegram_session(
            links=[ChainLink(Dead(), "m", "local")],
            registry=FakeRegistry([]),
            history=[],
        )

        async def go():
            return [e async for e in session.run_turn("hi")]

        events = asyncio.run(go())
        terminal = [e for e in events if isinstance(e, TurnFailed)]
        assert len(terminal) == 1
        assert terminal[0].error_code == "llm_auth"

    def test_history_seeds_the_prompt(self):
        from agent.runtime.llm_stream import FinishChunk, TextChunk
        from agent.runtime.providers.fallback import ChainLink

        seen = []

        class LLM:
            def stream(self, messages, model, **kwargs):
                seen.append(messages)

                async def gen():
                    yield TextChunk(text="ok")
                    yield FinishChunk(reason="stop")

                return gen()

        session = build_telegram_session(
            links=[ChainLink(LLM(), "m", "local")],
            registry=FakeRegistry([]),
            history=[
                {"role": "system", "content": "you are a bot"},
                {"role": "user", "content": "earlier question"},
            ],
        )

        async def go():
            return [e async for e in session.run_turn("follow up")]

        asyncio.run(go())
        roles = [m["role"] for m in seen[0]]
        assert roles == ["system", "user", "user"]
        assert seen[0][-1]["content"] == "follow up"


class TestDenialIsCarriedByTheEventNotTheProse:
    """The bug this class exists for.

    Both renderers used to decide "was this refused?" by checking whether
    `error` started with "permission denied". The session sets `error` to the
    policy's `denied_reason` — "tool not in session capability snapshot" —
    so the check never matched and every denial on every surface drew as a
    red ✗ crash. The renderer tests passed because they fed a string the
    runtime does not produce.

    These drive the real executor and the real policy, so the fixture cannot
    encode the assumption again.
    """

    def _denial_event(self):
        import asyncio

        from agent.coding.tool_schema import PermissionLevel
        from agent.runtime.events import ToolFinished
        from agent.runtime.llm_stream import FinishChunk, TextChunk
        from agent.runtime.providers.fallback import ChainLink

        class Parser:
            def parse(self, text):
                if "CALL" not in text:
                    return None
                return type("Call", (), {"tool_name": "Bash", "params": {"command": "ls"}})()

            def strip_tool_call(self, text, call):
                return text.replace("CALL", "").strip()

        class LLM:
            def __init__(self):
                self.calls = 0

            def stream(self, messages, model, **kwargs):
                self.calls += 1
                first = self.calls == 1

                async def gen():
                    yield TextChunk(text="CALL" if first else "I could not run that.")
                    yield FinishChunk(reason="stop")

                return gen()

        session = build_telegram_session(
            links=[ChainLink(LLM(), "m", "local")],
            registry=FakeRegistry([
                FakeTool("Bash", PermissionLevel.EXECUTE),
                FakeTool("WebSearch", PermissionLevel.READ_ONLY),
            ]),
            history=[],
            tool_parser=Parser(),
        )

        async def go():
            return [e async for e in session.run_turn("run ls")]

        events = asyncio.run(go())
        finished = [e for e in events if isinstance(e, ToolFinished)]
        assert finished, "the tool call must have been attempted"
        return finished[0]

    def test_a_refused_tool_sets_denied(self):
        event = self._denial_event()
        assert event.success is False
        assert event.denied is True

    def test_the_reason_does_not_start_with_the_words_renderers_used_to_match(self):
        """Pinning the actual wording. If a future change makes `error` begin
        with "Permission denied", the string check would start working again
        and hide that the field is the real contract."""
        event = self._denial_event()
        assert not event.error.lower().startswith("permission denied")
        assert event.error, "a refusal still has to say why"

    def test_the_telegram_renderer_marks_it_as_a_refusal(self):
        import asyncio

        from agent.integration.telegram_renderer import TelegramRenderer
        from agent.runtime.events import ToolProposed, TurnFinished

        event = self._denial_event()
        edits = []

        async def edit(text, final=False):
            edits.append(text)

        async def send(text):
            pass

        async def stream():
            yield ToolProposed(
                session_id="s", turn_id="t", sequence=0,
                call_id=event.call_id, tool_name=event.tool_name, preview="p",
            )
            yield event
            yield TurnFinished(session_id="s", turn_id="t", sequence=2, response="")

        renderer = TelegramRenderer(edit=edit, send=send, now=lambda: 0.0)
        asyncio.run(renderer.render(stream()))
        assert "⊘" in edits[-1], f"a refusal drew as a crash: {edits[-1]!r}"

    def test_the_cli_renderer_marks_it_as_a_refusal(self):
        """Same defect, other surface. Phase 4 shipped with it."""
        from cli.session_renderer import SessionRenderer

        event = self._denial_event()
        out = []
        renderer = SessionRenderer(
            write=out.append, write_markup=out.append, stop_spinner=lambda: None,
        )
        line = renderer._tool_summary(event)
        assert "⊘" in line and "yellow" in line, line
