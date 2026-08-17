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

    def test_a_provider_failure_is_a_refusal(self):
        assert stop_reason_for(
            ev(TurnFailed, error_code="llm_auth", message="bad key", retryable=False)
        ) == "refusal"

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
