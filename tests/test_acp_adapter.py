"""Phase 7 — NeoMind over the Agent Client Protocol.

Every assertion here constructs a **real** ACP model. That is the point: the
adapter was written against a guessed API and seven guesses were wrong, none of
which a type checker would have caught —

    ToolCallContent           → the class is ContentToolCallContent
    ToolProposed.params       → the event carries `preview`, not params
    ACP has a "denied" status → it has four, and refusal is not one of them
    Approval(fingerprint, …)  → `request_id` is required too
    Scope.SESSION             → only ONCE and SESSION_PATTERN exist
    session_update="usage"    → the schema says "usage_update"
    PromptResponse.usage      → wants `Usage`, not `UsageUpdate`

The last one is the reason these tests exist in this shape. Pydantic drops a
field whose type does not validate rather than raising, so passing the wrong
model left `usage=None` on a response that otherwise looked perfect — a client
would have shown zero tokens spent, forever, with nothing anywhere reporting a
problem.
"""

from __future__ import annotations

import asyncio

import pytest

from acp import schema

from agent.integration.acp_server import ACP_TOOLS, SESSION_MODES, NeoMindACPAgent
from agent.integration.acp_translate import (
    describe_outcome,
    stop_reason_for,
    translate,
    translate_all,
    turn_usage,
    _tag,
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
    TurnStarted,
)


def ev(cls, seq=0, **kw):
    return cls(session_id="s", turn_id="t1", sequence=seq, **kw)


# ── translation ───────────────────────────────────────────────────────────


class TestEventMapping:

    def test_text_becomes_an_agent_message(self):
        u = translate(ev(TextDelta, text="hello"))
        assert isinstance(u, schema.AgentMessageChunk)
        assert u.content.text == "hello"

    def test_thinking_is_a_thought_not_a_message(self):
        """A client renders these differently; collapsing them would put the
        model's reasoning into the conversation."""
        u = translate(ev(ThinkingDelta, text="deliberating"))
        assert isinstance(u, schema.AgentThoughtChunk)

    def test_a_proposed_tool_starts_pending(self):
        u = translate(ev(ToolProposed, call_id="c1", tool_name="Read", preview="a.txt"))
        assert isinstance(u, schema.ToolCallStart)
        assert u.tool_call_id == "c1"
        assert u.title == "Read"
        assert u.status == "pending"

    def test_a_started_tool_is_in_progress(self):
        u = translate(ev(ToolStarted, call_id="c1", tool_name="Read"))
        assert isinstance(u, schema.ToolCallProgress)
        assert u.status == "in_progress"

    def test_a_finished_tool_is_completed(self):
        u = translate(ev(ToolFinished, call_id="c1", tool_name="Read",
                         success=True, preview="data"))
        assert u.status == "completed"

    def test_turn_lifecycle_events_have_no_counterpart(self):
        """ACP signals a turn ending by `prompt` returning, not by an update.
        Emitting something here makes a client draw a phantom message."""
        assert translate(ev(TurnStarted)) is None
        assert translate(ev(TurnFinished, response="x")) is None
        assert translate(ev(TurnFailed, error_code="e", message="m", retryable=False)) is None

    def test_a_status_message_reaches_the_user(self):
        """"Stopped after 3 tool rounds" is not decoration."""
        u = translate(ev(StatusChanged, code="rounds", text="Stopped after 3 rounds."))
        assert isinstance(u, schema.AgentMessageChunk)
        assert "Stopped after 3 rounds." in u.content.text

    def test_translate_all_drops_only_the_unmapped(self):
        events = [ev(TurnStarted), ev(TextDelta, text="a"), ev(TurnFinished, response="a")]
        assert [type(u).__name__ for u in translate_all(events)] == ["AgentMessageChunk"]


class TestDiscriminators:
    """Required, hand-typed once, and wrong once. Now derived."""

    @pytest.mark.parametrize("model,expected", [
        (schema.AgentMessageChunk, "agent_message_chunk"),
        (schema.AgentThoughtChunk, "agent_thought_chunk"),
        (schema.ToolCallStart, "tool_call"),
        (schema.ToolCallProgress, "tool_call_update"),
        (schema.UsageUpdate, "usage_update"),
    ])
    def test_the_tag_comes_from_the_schema(self, model, expected):
        assert _tag(model) == expected

    def test_a_model_without_a_literal_tag_is_rejected_loudly(self):
        class NoTag:
            model_fields = {"session_update": type("F", (), {"annotation": str})()}

        with pytest.raises(TypeError):
            _tag(NoTag)


class TestRefusalSurvivesAProtocolThatCannotExpressIt:
    """ACP's status enum is pending | in_progress | completed | failed. There
    is no "denied", so a refusal has to arrive as `failed` *plus text* — and
    losing the distinction is exactly the bug that had every denial rendering
    as a crash on the CLI and Telegram."""

    def test_a_refusal_is_reported_as_a_refusal_in_the_text(self):
        u = translate(ev(ToolFinished, call_id="c", tool_name="Bash", success=False,
                         denied=True, error="tool not in session capability snapshot"))
        assert u.status == "failed"
        body = " ".join(c.content.text for c in (u.content or []))
        assert "Refused" in body
        assert "snapshot" in body

    def test_a_genuine_failure_does_not_claim_to_be_a_refusal(self):
        u = translate(ev(ToolFinished, call_id="c", tool_name="Read", success=False,
                         error="No such file"))
        body = " ".join(c.content.text for c in (u.content or []))
        assert "Refused" not in body
        assert "No such file" in body

    def test_describe_outcome_prefers_the_preview_on_success(self):
        assert describe_outcome(
            ev(ToolFinished, call_id="c", tool_name="Read", success=True, preview="hi")
        ) == "hi"

    def test_a_refusal_with_no_reason_still_says_it_was_refused(self):
        text = describe_outcome(
            ev(ToolFinished, call_id="c", tool_name="Bash", success=False, denied=True)
        )
        assert "Refused" in text


class TestToolOutputIsBounded:

    def test_a_huge_preview_is_clipped(self):
        u = translate(ev(ToolFinished, call_id="c", tool_name="Read",
                         success=True, preview="x" * 50_000))
        body = u.content[0].content.text
        assert len(body) < 3000
        assert "more characters" in body


class TestUsage:
    """The silent one: pydantic drops a mistyped field instead of raising."""

    def test_turn_usage_produces_the_response_type_not_the_update_type(self):
        u = turn_usage({"total_tokens": 42, "prompt_tokens": 30, "completion_tokens": 12})
        assert isinstance(u, schema.Usage)
        assert (u.total_tokens, u.input_tokens, u.output_tokens) == (42, 30, 12)

    def test_it_survives_a_prompt_response_round_trip(self):
        """The assertion that would have caught the original bug: build the
        real response and read the field back."""
        resp = schema.PromptResponse(
            stop_reason="end_turn",
            usage=turn_usage({"total_tokens": 7, "prompt_tokens": 5, "completion_tokens": 2}),
        )
        assert resp.usage is not None, "a mistyped usage is dropped, not rejected"
        assert resp.usage.total_tokens == 7

    def test_a_total_is_derived_when_only_the_halves_are_known(self):
        u = turn_usage({"prompt_tokens": 4, "completion_tokens": 6})
        assert u.total_tokens == 10

    def test_empty_usage_is_none_rather_than_zeros(self):
        assert turn_usage({}) is None
        assert turn_usage(None) is None
        assert turn_usage({"total_tokens": 0}) is None


class TestStopReason:

    def test_a_finished_turn_ends_the_turn(self):
        assert stop_reason_for(ev(TurnFinished, response="x")) == "end_turn"

    def test_a_cancelled_turn_is_cancelled_not_a_refusal(self):
        """A user's own Ctrl-C shown as a failure is a lie about what
        happened."""
        assert stop_reason_for(
            ev(TurnFailed, error_code="cancelled", message="m", retryable=True)
        ) == "cancelled"

    def test_a_provider_failure_is_not_a_refusal(self):
        """`refusal` means the agent declined. `TurnFailed` only ever means a
        technical failure, so nothing here can legitimately produce one.

        Getting this wrong was invisible until a real client read it: DSH
        reported "subagent declined the task" for a transport error and sent
        its model off to rephrase the prompt twice.
        """
        for code in ("llm_auth", "llm_timeout", "llm_transport", "unexpected"):
            reason = stop_reason_for(
                ev(TurnFailed, error_code=code, message="x", retryable=False)
            )
            assert reason == "max_turn_requests", code
            assert reason != "refusal", (
                f"{code} is a failure, not the agent choosing to decline"
            )

    def test_a_missing_terminal_event_does_not_crash_the_response(self):
        assert stop_reason_for(None) == "end_turn"


# ── the server ────────────────────────────────────────────────────────────


class FakeSession:
    def __init__(self, events):
        self.events = events
        self.cancelled = []
        self.prompt_text = None

    def run_turn(self, text):
        self.prompt_text = text

        async def gen():
            for e in self.events:
                yield e

        return gen()

    async def cancel(self, turn_id):
        self.cancelled.append(turn_id)


class FakeClient:
    def __init__(self):
        self.updates = []

    async def session_update(self, session_id, update):
        self.updates.append(update)


def agent_with(events):
    sessions = []

    def factory(session):
        s = FakeSession(events)
        sessions.append(s)
        return s

    agent = NeoMindACPAgent(session_factory=factory)
    client = FakeClient()
    agent.on_connect(client)
    return agent, client, sessions


class TestServerTurn:

    def test_a_turn_streams_updates_and_returns_a_stop_reason(self):
        agent, client, _ = agent_with([
            ev(TextDelta, text="hello "),
            ev(TextDelta, 1, text="world"),
            ev(TurnFinished, 2, response="hello world"),
        ])

        async def go():
            s = await agent.new_session(cwd="/tmp")
            return await agent.prompt(s.session_id, [schema.TextContentBlock(type="text", text="hi")])

        resp = asyncio.run(go())
        assert resp.stop_reason == "end_turn"
        assert [type(u).__name__ for u in client.updates] == [
            "AgentMessageChunk", "AgentMessageChunk",
        ]

    def test_the_prompt_text_reaches_the_session(self):
        agent, _, sessions = agent_with([ev(TurnFinished, response="")])

        async def go():
            s = await agent.new_session(cwd="/tmp")
            await agent.prompt(s.session_id, [
                schema.TextContentBlock(type="text", text="first"),
                schema.TextContentBlock(type="text", text="second"),
            ])

        asyncio.run(go())
        assert sessions[0].prompt_text == "first\nsecond"

    def test_unsupported_content_is_named_not_dropped(self):
        """A user who attached an image should not watch it vanish with no
        explanation."""
        agent, _, sessions = agent_with([ev(TurnFinished, response="")])

        async def go():
            s = await agent.new_session(cwd="/tmp")
            await agent.prompt(s.session_id, [
                schema.ImageContentBlock(type="image", data="x", mime_type="image/png"),
            ])

        asyncio.run(go())
        assert "unsupported content" in sessions[0].prompt_text

    def test_usage_reaches_the_response(self):
        agent, _, _ = agent_with([
            ev(TurnFinished, response="x",
               usage={"total_tokens": 9, "prompt_tokens": 6, "completion_tokens": 3}),
        ])

        async def go():
            s = await agent.new_session(cwd="/tmp")
            return await agent.prompt(s.session_id, [schema.TextContentBlock(type="text", text="q")])

        resp = asyncio.run(go())
        assert resp.usage is not None and resp.usage.total_tokens == 9


class TestSessions:

    def test_each_session_gets_its_own_id(self):
        agent, _, _ = agent_with([])

        async def go():
            a = await agent.new_session(cwd="/tmp")
            b = await agent.new_session(cwd="/tmp")
            return a.session_id, b.session_id

        a, b = asyncio.run(go())
        assert a != b

    def test_an_unknown_session_is_rejected(self):
        agent, _, _ = agent_with([])

        async def go():
            await agent.prompt("nope", [schema.TextContentBlock(type="text", text="x")])

        with pytest.raises(ValueError):
            asyncio.run(go())

    def test_mode_can_be_switched_and_is_validated(self):
        agent, _, _ = agent_with([])

        async def go():
            s = await agent.new_session(cwd="/tmp")
            await agent.set_session_mode(s.session_id, "fin")
            return agent._sessions[s.session_id].mode

        assert asyncio.run(go()) == "fin"

    def test_an_unknown_mode_is_refused(self):
        agent, _, _ = agent_with([])

        async def go():
            s = await agent.new_session(cwd="/tmp")
            await agent.set_session_mode(s.session_id, "nonsense")

        with pytest.raises(ValueError):
            asyncio.run(go())

    def test_every_advertised_mode_is_accepted(self):
        agent, _, _ = agent_with([])

        async def go():
            s = await agent.new_session(cwd="/tmp")
            for mode in SESSION_MODES:
                await agent.set_session_mode(s.session_id, mode)

        asyncio.run(go())


class TestCancel:
    """ACP's cancel is a notification: it returns nothing and must not raise."""

    def test_cancelling_an_unknown_session_is_silent(self):
        agent, _, _ = agent_with([])
        asyncio.run(agent.cancel("never-existed"))

    def test_cancelling_before_a_turn_is_silent(self):
        agent, _, _ = agent_with([])

        async def go():
            s = await agent.new_session(cwd="/tmp")
            await agent.cancel(s.session_id)

        asyncio.run(go())


class TestCapabilityPolicy:
    """ACP is the first remote surface that can *ask*, which is why its
    allowlist is wider than Telegram's — but it is still an allowlist."""

    def test_the_tool_list_is_an_allowlist_not_everything(self):
        assert len(ACP_TOOLS) < 20
        for name in ("TeamDelete", "SendMessage", "CronCreate"):
            assert name not in ACP_TOOLS

    def test_the_policy_is_interactive_because_a_client_can_answer(self):
        import inspect

        from agent.integration import acp_server

        source = inspect.getsource(acp_server.NeoMindACPAgent._build_agent_session)
        assert "interactive=True" in source
        assert "auto_accept=False" in source

    def test_the_snapshot_is_scoped_rather_than_unrestricted(self):
        import inspect

        from agent.integration import acp_server

        source = inspect.getsource(acp_server.NeoMindACPAgent._build_agent_session)
        assert "CapabilitySnapshot.only(" in source
        assert "unrestricted" not in source


class TestPermissionBridge:
    """The Phase 4 broker port's second consumer. Its contract is exact and
    getting it wrong denies every tool silently — which is what happened the
    first time, in the REPL."""

    def _broker(self, answer_option):
        """`answer_option=None` means the client denied."""
        agent, _, _ = agent_with([])

        class Client:
            def __init__(self):
                self.asked = []

            async def request_permission(self, session_id, tool_call, options):
                self.asked.append((tool_call, options))
                outcome = (
                    schema.AllowedOutcome(outcome="selected", option_id=answer_option)
                    if answer_option
                    else schema.DeniedOutcome(outcome="cancelled")
                )
                return schema.RequestPermissionResponse(outcome=outcome)

        client = Client()
        agent.on_connect(client)
        session = type("S", (), {"session_id": "s1", "cwd": "/tmp"})()
        return agent._permission_broker(session), client

    def test_an_allowed_call_returns_an_approval_not_a_bool(self):
        from agent.runtime.permissions import Approval

        broker, _ = self._broker("allow")
        result = asyncio.run(broker.request(
            request_id="r1", tool_name="Read", params={"path": "a.txt"},
        ))
        assert isinstance(result, Approval), (
            "the executor refuses anything that is not an Approval; a bare "
            "True names no call, so it cannot be bound to one"
        )
        assert result.request_id == "r1"
        assert result.fingerprint

    def test_a_client_side_denial_returns_none(self):
        """The client cancelled the prompt: DeniedOutcome carries no
        option_id at all, so a bridge that reads one and compares would be
        right only by accident."""
        broker, _ = self._broker(None)
        assert asyncio.run(broker.request(
            request_id="r1", tool_name="Bash", params={"command": "rm -rf /"},
        )) is None

    def test_a_rejected_option_returns_none(self):
        broker, _ = self._broker("reject")
        assert asyncio.run(broker.request(
            request_id="r1", tool_name="Bash", params={"command": "rm -rf /"},
        )) is None

    def test_always_allow_widens_the_scope(self):
        from agent.runtime.permissions import Scope

        broker, _ = self._broker("allow_always")
        result = asyncio.run(broker.request(
            request_id="r1", tool_name="Read", params={},
        ))
        assert result.scope is Scope.SESSION_PATTERN

    def test_the_dialog_is_shown_what_it_is_approving(self):
        """A permission prompt that cannot show the arguments is the failure
        this layer exists to prevent."""
        broker, client = self._broker("allow")
        asyncio.run(broker.request(
            request_id="r1", tool_name="Bash", params={"command": "ls -la"},
        ))
        tool_call, _ = client.asked[0]
        assert tool_call.title == "Bash"
        assert tool_call.raw_input == {"command": "ls -la"}

    def test_with_no_client_attached_nothing_is_approved(self):
        agent, _, _ = agent_with([])
        agent._client = None
        session = type("S", (), {"session_id": "s", "cwd": "/tmp"})()
        broker = agent._permission_broker(session)
        assert asyncio.run(broker.request(request_id="r", tool_name="Read")) is None


class TestTheAgentGetsItsBriefing:
    """The system prompt, and the config the mode lives in.

    This surface shipped without either. Tools were wired and the mode was
    recorded, but `history` started empty and the per-session config was bound
    in `session/new` — a different task from `session/prompt`, so it was gone
    before the turn ran. The result passed every test here because they all
    asked arithmetic: `17*23` needs no briefing. Asked what the repository it
    was running inside did, it replied asking for a link to the repository.

    So these assert on what the turn is actually handed, not on whether it
    answers.
    """

    @staticmethod
    def _session_seen_by(agent, *, run_in_separate_tasks: bool):
        """Run new_session then prompt, capturing what the factory was handed.

        `run_in_separate_tasks` reproduces the SDK: `acp/task/supervisor.py`
        wraps every request in `asyncio.create_task`, so a contextvar bound in
        one request is invisible to the next. Awaiting both in one coroutine —
        which is what every earlier test here did — hides exactly that.
        """
        seen = {}

        def factory(session):
            from agent_config import agent_config

            seen["system_prompt"] = getattr(agent_config, "system_prompt", "")
            seen["mode"] = getattr(agent_config, "mode", None)
            seen["history"] = list(getattr(session, "history", []))
            return FakeSession([ev(TurnFinished, response="")])

        agent._session_factory = factory

        async def go():
            if run_in_separate_tasks:
                s = await asyncio.create_task(agent.new_session(cwd="/tmp"))
                await asyncio.create_task(agent.prompt(s.session_id, []))
            else:
                s = await agent.new_session(cwd="/tmp")
                await agent.prompt(s.session_id, [])

        asyncio.run(go())
        return seen

    def test_the_session_config_reaches_the_turn_across_tasks(self):
        """The binding has to survive the request boundary, not just the call."""
        agent, _, _ = agent_with([])
        agent._default_mode = "coding"
        seen = self._session_seen_by(agent, run_in_separate_tasks=True)
        assert seen["mode"] == "coding", (
            "the turn read a config whose mode is not the session's; "
            "session.mode was decoration"
        )

    def test_a_mode_switch_reaches_the_config_not_only_the_record(self):
        agent, _, _ = agent_with([])
        agent._default_mode = "coding"

        async def go():
            s = await asyncio.create_task(agent.new_session(cwd="/tmp"))
            await asyncio.create_task(agent.set_session_mode(s.session_id, "chat"))
            return s.session_id

        session_id = asyncio.run(go())
        assert agent._sessions[session_id].config.mode == "chat"

    def test_the_turn_is_handed_a_system_prompt(self):
        agent, _, _ = agent_with([])
        seen = self._session_seen_by(agent, run_in_separate_tasks=True)
        roles = [m.get("role") for m in seen["history"]]
        assert roles[:1] == ["system"], (
            f"history starts {roles[:3]} — the agent has no briefing"
        )
        assert seen["history"][0]["content"].strip(), "the system message is empty"

    def test_the_seeded_prompt_is_the_one_the_config_resolves(self):
        agent, _, _ = agent_with([])
        seen = self._session_seen_by(agent, run_in_separate_tasks=True)
        assert seen["history"][0]["content"] == seen["system_prompt"]

    def test_seeding_does_not_stack_on_a_resumed_history(self):
        """A session that already carries the prompt must not gain a second."""
        from agent.integration.acp_server import _Session
        from agent_config import agent_config

        prompt = getattr(agent_config, "system_prompt", "") or "x"
        session = _Session(
            session_id="s", cwd="/tmp",
            history=[{"role": "system", "content": prompt},
                     {"role": "user", "content": "earlier"}],
        )
        from agent.integration.acp_server import NeoMindACPAgent

        seeded = NeoMindACPAgent._seeded_history(session)
        assert [m["role"] for m in seeded] == ["system", "user"]

    def test_an_empty_configured_prompt_seeds_nothing(self):
        """Absent config is not a reason to insert an empty system message."""
        from agent.integration.acp_server import NeoMindACPAgent, _Session
        from agent_config import bind_session_config, reset_current_config, agent_config

        token = bind_session_config()
        try:
            agent_config.system_prompt = ""
            seeded = NeoMindACPAgent._seeded_history(_Session(session_id="s", cwd="/tmp"))
        finally:
            reset_current_config(token)
        assert seeded == []


class TestTheSessionRemembers:
    """Cross-turn memory.

    `session.history` was read to seed every turn and never written, and no
    store was passed, so each prompt started from the same list: a client that
    asked "what did I just say" got an agent that had genuinely forgotten. The
    arithmetic probes used to check this surface are single-turn by nature and
    could not see it.
    """

    @staticmethod
    def _agent_recording_starts():
        """Drive two turns, capturing the history each turn began with."""
        starts = []

        def factory(session):
            starts.append([m.get("role") for m in session.history])
            store = NeoMindACPAgent._HistoryStore(session)

            class S:
                async def run_turn(self, text):
                    # What AgentSession._append does, minus the provider.
                    store.append(session.session_id, {"role": "user", "content": text})
                    store.append(session.session_id, {
                        "role": "assistant", "content": "ok", "_bookkeeping": "x",
                    })
                    yield ev(TurnFinished, response="ok")

                async def cancel(self, turn_id):
                    pass

            return S()

        agent = NeoMindACPAgent(session_factory=factory)
        agent.on_connect(FakeClient())

        async def go():
            s = await asyncio.create_task(agent.new_session(cwd="/tmp"))
            for text in ("the codeword is PLUMBAGO", "what was the codeword?"):
                await asyncio.create_task(agent.prompt(
                    s.session_id, [schema.TextContentBlock(type="text", text=text)],
                ))
            return s.session_id

        session_id = asyncio.run(go())
        return agent, session_id, starts

    def test_the_second_turn_starts_from_what_the_first_one_said(self):
        _, _, starts = self._agent_recording_starts()
        assert starts[0] == ["system"]
        assert starts[1] == ["system", "user", "assistant"], (
            f"turn two began with {starts[1]} — the session forgot turn one"
        )

    def test_the_earlier_message_is_there_verbatim(self):
        agent, session_id, _ = self._agent_recording_starts()
        contents = [m.get("content") for m in agent._sessions[session_id].history]
        assert "the codeword is PLUMBAGO" in contents

    def test_bookkeeping_keys_do_not_reach_the_history(self):
        """Underscored keys are the runtime's own; sending them to a provider
        is at best noise and at worst a schema rejection."""
        agent, session_id, _ = self._agent_recording_starts()
        history = agent._sessions[session_id].history
        assert not [k for m in history for k in m if k.startswith("_")]

    def test_the_system_prompt_is_not_re_seeded_each_turn(self):
        agent, session_id, _ = self._agent_recording_starts()
        history = agent._sessions[session_id].history
        assert sum(1 for m in history if m.get("role") == "system") == 1

    def test_two_sessions_do_not_share_a_history(self):
        """The store is bound to one session; a second must not see its turns."""
        from agent.integration.acp_server import _Session

        a, b = _Session(session_id="a", cwd="/tmp"), _Session(session_id="b", cwd="/tmp")
        NeoMindACPAgent._HistoryStore(a).append("a", {"role": "user", "content": "hi"})
        assert b.history == []


class TestModesAreReachableFromOutside:
    """`set_session_mode` worked; nothing told a client the modes existed.

    NeoMind has had three personalities the whole time and validated switches
    against them, but `NewSessionResponse` went out carrying only a session id.
    A client with a mode picker had nothing to put in it, and one without could
    only guess the ids. The capability was implemented and unreachable — the
    same shape as the missing system prompt, one layer up.
    """

    def test_a_new_session_advertises_every_mode(self):
        agent, _, _ = agent_with([])
        resp = asyncio.run(agent.new_session(cwd="/tmp"))
        assert resp.modes is not None, "a client is told nothing about modes"
        ids = [m.id for m in resp.modes.available_modes]
        assert ids == list(SESSION_MODES)

    def test_the_advertised_ids_are_the_ones_set_mode_accepts(self):
        """A client must be able to hand back exactly what it was given."""
        agent, _, _ = agent_with([])

        async def go():
            resp = await agent.new_session(cwd="/tmp")
            for mode in resp.modes.available_modes:
                await agent.set_session_mode(resp.session_id, mode.id)
            return agent._sessions[resp.session_id].mode

        assert asyncio.run(go()) == SESSION_MODES[-1]

    def test_each_mode_carries_something_displayable(self):
        agent, _, _ = agent_with([])
        resp = asyncio.run(agent.new_session(cwd="/tmp"))
        for mode in resp.modes.available_modes:
            assert mode.name and mode.name != mode.id
            assert mode.description

    def test_the_current_mode_is_the_one_the_session_starts_in(self):
        agent, _, _ = agent_with([])
        agent._default_mode = "fin"
        resp = asyncio.run(agent.new_session(cwd="/tmp"))
        assert resp.modes.current_mode_id == "fin"

    def test_a_switch_notifies_the_client(self):
        """A second client on the same session, or the same one after a
        reconnect, has no other way to learn the mode moved."""
        agent, client, _ = agent_with([])

        async def go():
            resp = await agent.new_session(cwd="/tmp")
            await agent.set_session_mode(resp.session_id, "chat")

        asyncio.run(go())
        updates = [u for u in client.updates
                   if type(u).__name__ == "CurrentModeUpdate"]
        assert updates, "the mode changed and no client was told"
        assert updates[-1].current_mode_id == "chat"

    def test_the_notification_carries_its_discriminator(self):
        """A union member without its tag is dropped by a strict client."""
        agent, client, _ = agent_with([])

        async def go():
            resp = await agent.new_session(cwd="/tmp")
            await agent.set_session_mode(resp.session_id, "chat")

        asyncio.run(go())
        update = [u for u in client.updates
                  if type(u).__name__ == "CurrentModeUpdate"][-1]
        assert update.session_update == "current_mode_update"


class TestAdvertisedCapabilitiesMatchReality:
    """A capability claim is a promise a client will act on.

    Both directions are bugs. Claiming something unimplemented invites calls
    that fail; implementing something unclaimed means nobody ever calls it —
    which is how `close_session` came to exist for a surface where every client
    leaked sessions instead.
    """

    @staticmethod
    def _caps():
        agent = NeoMindACPAgent(session_factory=lambda s: None)
        return asyncio.run(agent.initialize(protocol_version=1)).agent_capabilities

    def test_close_is_advertised_because_it_is_implemented(self):
        caps = self._caps()
        assert caps.session_capabilities is not None
        # Presence is the claim; the field holds a capability object, and a
        # bool put here is silently dropped back to None.
        assert caps.session_capabilities.close is not None

    def test_nothing_unimplemented_is_claimed(self):
        """Each of these has no handler; claiming one would break a client that
        believed it."""
        caps = self._caps()
        sc = caps.session_capabilities
        for field in ("list", "delete", "fork", "resume"):
            assert not getattr(sc, field), f"{field} advertised without a handler"
        assert caps.load_session is False

    def test_rich_content_is_not_claimed_because_the_turn_takes_text(self):
        """`_prompt_text` names non-text blocks rather than understanding them,
        so a client must not be told to send them."""
        caps = self._caps()
        pc = caps.prompt_capabilities
        assert not pc.image and not pc.audio and not pc.embedded_context

    def test_every_advertised_session_capability_has_a_handler(self):
        """Derives the claim set from the response rather than listing it, so a
        capability added later is covered without editing this test."""
        caps = self._caps()
        handlers = {
            "close": "close_session",
            "list": "list_sessions",
            "delete": "delete_session",
            "fork": "fork_session",
            "resume": "load_session",
        }
        sc = caps.session_capabilities
        for field, method in handlers.items():
            if getattr(sc, field, None):
                assert callable(getattr(NeoMindACPAgent, method, None)), (
                    f"advertised {field} with no {method}()"
                )


class TestClosingASession:

    def test_a_closed_session_is_gone(self):
        agent, _, _ = agent_with([])

        async def go():
            s = await agent.new_session(cwd="/tmp")
            await agent.close_session(s.session_id)
            return s.session_id in agent._sessions

        assert asyncio.run(go()) is False

    def test_closing_an_unknown_session_is_not_an_error(self):
        """A client that closes twice, or after a reconnect, must not be
        punished for it."""
        agent, _, _ = agent_with([])
        asyncio.run(agent.close_session("never-existed"))

    def test_a_closed_session_cannot_be_prompted(self):
        agent, _, _ = agent_with([])

        async def go():
            s = await agent.new_session(cwd="/tmp")
            await agent.close_session(s.session_id)
            await agent.prompt(s.session_id, [])

        with pytest.raises(ValueError):
            asyncio.run(go())

    def test_closing_one_session_leaves_the_other_alone(self):
        agent, _, _ = agent_with([])

        async def go():
            a = await agent.new_session(cwd="/tmp")
            b = await agent.new_session(cwd="/tmp")
            await agent.close_session(a.session_id)
            return b.session_id in agent._sessions

        assert asyncio.run(go()) is True


class TestTwoClientsDoNotShareOneConfig:
    """The property Phase 6A established, and the one this surface breaks first.

    Each ACP session forks its own config. That fork is bound around the turn
    rather than at `session/new`, because the SDK runs every request in its own
    task and a contextvar set in one is invisible to the next. These assert the
    outcome — what the turn actually read — rather than that a bind was called,
    since the earlier version called one and it had no effect by the time the
    turn ran.
    """

    @staticmethod
    def _agent_recording_config():
        seen = []

        def factory(session):
            from agent_config import agent_config

            seen.append({
                "session_id": session.session_id,
                "session_mode": session.mode,
                "config_mode": getattr(agent_config, "mode", None),
                "prompt": getattr(agent_config, "system_prompt", "") or "",
            })
            return FakeSession([ev(TurnFinished, response="")])

        agent = NeoMindACPAgent(session_factory=factory)
        agent.on_connect(FakeClient())
        return agent, seen

    @staticmethod
    def _text(t="hi"):
        return [schema.TextContentBlock(type="text", text=t)]

    def test_interleaved_turns_each_read_their_own_mode(self):
        agent, seen = self._agent_recording_config()

        async def go():
            a = await asyncio.create_task(agent.new_session(cwd="/tmp"))
            b = await asyncio.create_task(agent.new_session(cwd="/tmp"))
            await asyncio.create_task(agent.set_session_mode(a.session_id, "fin"))
            await asyncio.create_task(agent.set_session_mode(b.session_id, "chat"))
            await asyncio.gather(
                asyncio.create_task(agent.prompt(a.session_id, self._text())),
                asyncio.create_task(agent.prompt(b.session_id, self._text())),
            )

        asyncio.run(go())
        assert [s["config_mode"] for s in seen] == [s["session_mode"] for s in seen], (
            "a turn read a config whose mode was not its session's — one client "
            "changed another's"
        )
        assert {s["config_mode"] for s in seen} == {"fin", "chat"}

    def test_each_mode_brings_a_different_personality(self):
        """Otherwise the switch renames the mode without changing the agent —
        which is what it did before the config was told about it."""
        agent, seen = self._agent_recording_config()

        async def go():
            for mode in SESSION_MODES:
                s = await asyncio.create_task(agent.new_session(cwd="/tmp"))
                await asyncio.create_task(agent.set_session_mode(s.session_id, mode))
                await asyncio.create_task(agent.prompt(s.session_id, self._text()))

        asyncio.run(go())
        prompts = [s["prompt"] for s in seen]
        assert all(prompts), "a mode ran with an empty system prompt"
        assert len(set(prompts)) == len(SESSION_MODES), (
            "two modes shared a system prompt; the switch is cosmetic"
        )

    def test_the_binding_is_released_after_the_turn(self):
        """A turn must not leave its config bound behind it.

        Awaited directly rather than through `create_task`: a task gets its own
        copy of the context, so a leaked binding inside one is invisible from
        outside it and the assertion would hold no matter what. Awaiting in the
        caller's context is the case where failing to release actually shows —
        the next turn in that context would run as this session.
        """
        from agent_config import agent_config

        agent, _ = self._agent_recording_config()

        async def go():
            before = getattr(agent_config, "mode", None)
            # Any mode but the ambient one. Switching to the mode the process
            # already runs in makes before and after equal whatever happens,
            # which is how this assertion silently stopped testing anything.
            target = next(m for m in SESSION_MODES if m != before)
            s = await agent.new_session(cwd="/tmp")
            await agent.set_session_mode(s.session_id, target)
            await agent.prompt(s.session_id, self._text())
            return before, getattr(agent_config, "mode", None)

        before, after = asyncio.run(go())
        assert after == before, (
            f"the turn left its config bound: mode is {after!r}, was {before!r}"
        )


class TestCancellingWhileADialogIsOpen:
    """Escape has to end the wait, not start a five-minute one.

    The broker awaited `client.request_permission` with nothing watching for
    cancellation. ACP says a client that cancels answers the outstanding
    request with `cancelled`, but one that simply closes its dialog — or drops
    — sends nothing, and the executor's 300s permission timeout was then the
    only thing that ended the turn.
    """

    @staticmethod
    def _broker_and_session(*, answer_after: float):
        asked = asyncio.Event()

        class SlowClient:
            async def session_update(self, session_id, update):
                pass

            async def request_permission(self, session_id, tool_call, options, **kw):
                asked.set()
                await asyncio.sleep(answer_after)
                return None

        agent = NeoMindACPAgent(session_factory=lambda s: None)
        agent.on_connect(SlowClient())
        return agent, asked

    def test_a_cancel_ends_the_wait_promptly(self):
        agent, asked = self._broker_and_session(answer_after=300)

        async def go():
            session = await agent.new_session(cwd="/tmp")
            record = agent._sessions[session.session_id]
            broker = agent._permission_broker(record)
            task = asyncio.create_task(
                broker.request(request_id="r1", tool_name="Edit", params={"path": "x"})
            )
            await asyncio.wait_for(asked.wait(), timeout=5)
            record.cancelled = True
            # Far below the 300s the client would take and the 300s executor
            # ceiling, so passing means cancellation ended it, not a timeout.
            return await asyncio.wait_for(task, timeout=5)

        assert asyncio.run(go()) is None, "a cancelled request must not approve"

    def test_an_answer_still_arrives_when_nothing_cancels(self):
        """The watcher must not swallow a normal reply."""
        approved = {}

        class Client:
            async def session_update(self, session_id, update):
                pass

            async def request_permission(self, session_id, tool_call, options, **kw):
                approved["asked"] = tool_call.title
                return schema.RequestPermissionResponse(
                    outcome=schema.AllowedOutcome(outcome="selected", option_id="allow"),
                )

        agent = NeoMindACPAgent(session_factory=lambda s: None)
        agent.on_connect(Client())

        async def go():
            session = await agent.new_session(cwd="/tmp")
            broker = agent._permission_broker(agent._sessions[session.session_id])
            return await broker.request(
                request_id="r1", tool_name="Edit", params={"path": "x"},
            )

        result = asyncio.run(go())
        assert approved["asked"] == "Edit"
        assert result is not None, "an allowed call came back denied"
        assert result.request_id == "r1"

    def test_the_outstanding_request_is_not_left_running(self):
        """A reply delivered after the turn ended would land nowhere, or worse,
        into the next one."""
        finished = []

        class Client:
            async def session_update(self, session_id, update):
                pass

            async def request_permission(self, session_id, tool_call, options, **kw):
                try:
                    await asyncio.sleep(300)
                except asyncio.CancelledError:
                    finished.append("cancelled")
                    raise
                return None

        agent = NeoMindACPAgent(session_factory=lambda s: None)
        agent.on_connect(Client())

        async def go():
            session = await agent.new_session(cwd="/tmp")
            record = agent._sessions[session.session_id]
            broker = agent._permission_broker(record)
            task = asyncio.create_task(
                broker.request(request_id="r1", tool_name="Edit", params={"path": "x"})
            )
            await asyncio.sleep(0.2)
            record.cancelled = True
            await asyncio.wait_for(task, timeout=5)

        asyncio.run(go())
        assert finished == ["cancelled"], "the client call was left in flight"
