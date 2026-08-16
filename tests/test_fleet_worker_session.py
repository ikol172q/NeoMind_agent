"""Phase 6B task 2 — the fleet worker turn on AgentSession.

Two things this has to get right, and neither is visible from a passing run:

  * the audit trail. Every worker call already produced a `req_id` with the
    full request and response in the audit log, and that is a zero-data-loss
    requirement. A migration that quietly dropped it would look identical from
    the outside.
  * the capability boundary. A fleet worker is the least supervised surface
    there is — unattended, on a schedule, nobody to answer a prompt — which is
    why its turn was frozen as LLM-only until it could go through the same
    ToolExecutor as everything else.
"""

from __future__ import annotations

import asyncio
from unittest import mock

import pytest

from agent.coding.tool_schema import PermissionLevel
from agent.runtime.llm_stream import FinishChunk, TextChunk, UsageChunk
from fleet.worker_session import (
    FLEET_READ_ONLY_TOOLS,
    build_worker_session,
    fleet_allowed_tools,
    session_llm_call,
)


@pytest.fixture(autouse=True)
def _never_touch_the_real_audit_log():
    """Keep tests out of `~/Desktop/Investment/_audit/`.

    `session_llm_call` writes there for real, and the first run of this file
    appended eight fabricated rows to a production audit trail — including an
    injected `llm_transport refused` — with the same endpoint and agent_id as a
    genuine fleet turn, so nothing distinguishes them after the fact. An audit
    log is only worth keeping if everything in it happened.

    Autouse rather than per-test: the class that asserts auditing patches these
    anyway, and the rest have no business writing at all.
    """
    with mock.patch.multiple(
        "agent.services.agent_audit",
        new_req_id=mock.DEFAULT,
        audit_request=mock.DEFAULT,
        audit_response=mock.DEFAULT,
        audit_error=mock.DEFAULT,
    ):
        yield


class FakeTool:
    def __init__(self, name, level):
        self.name = name
        self.permission_level = level


class FakeRegistry:
    def __init__(self, tools=()):
        self._tools = {t.name: t for t in tools}

    def get_tool(self, name):
        return self._tools.get(name)


def fake_llm(text="the answer", usage=None):
    class LLM:
        seen = []

        def stream(self, messages, model, **kwargs):
            LLM.seen.append((list(messages), model, dict(kwargs)))

            async def gen():
                yield TextChunk(text=text)
                if usage:
                    yield UsageChunk(**usage)
                yield FinishChunk(reason="stop")

            return gen()

    LLM.seen = []
    return LLM()


class TestCapabilityBoundary:

    def test_the_allowlist_excludes_filesystem_and_shell(self):
        """The shape the Phase 0 freeze existed to prevent: a scheduled job
        reading arbitrary files or running commands."""
        for name in ("Read", "Write", "Edit", "Bash", "Glob", "Grep", "LS"):
            assert name not in FLEET_READ_ONLY_TOOLS, name

    def test_only_allowlisted_read_only_tools_survive(self):
        registry = FakeRegistry([
            FakeTool("WebSearch", PermissionLevel.READ_ONLY),
            FakeTool("Bash", PermissionLevel.EXECUTE),
            FakeTool("Read", PermissionLevel.READ_ONLY),
        ])
        assert fleet_allowed_tools(registry) == ["WebSearch"]

    def test_a_tool_reclassified_later_drops_out(self):
        registry = FakeRegistry([FakeTool("WebFetch", PermissionLevel.WRITE)])
        assert fleet_allowed_tools(registry) == []

    def test_the_worker_is_not_interactive(self):
        session = build_worker_session(
            llm=fake_llm(), registry=FakeRegistry(), model="m", system_prompt="s",
        )
        assert session.executor.policy.interactive is False
        assert session.executor.policy.auto_accept is False

    def test_an_unlisted_tool_is_denied(self):
        from agent.runtime.permissions import Decision

        session = build_worker_session(
            llm=fake_llm(),
            registry=FakeRegistry([FakeTool("WebSearch", PermissionLevel.READ_ONLY)]),
            model="m",
            system_prompt="s",
        )
        decision, reason = session.executor.policy.evaluate("Bash", "read_only", {})
        assert decision is Decision.DENY
        assert "snapshot" in reason

    def test_the_tool_round_cap_is_short(self):
        """A worker turn is one question, not a loop nobody is watching."""
        session = build_worker_session(
            llm=fake_llm(), registry=FakeRegistry(), model="m", system_prompt="s",
        )
        assert session.max_tool_rounds <= 2

    def test_no_conversation_store_is_attached(self):
        """A surface with no conversation must not own conversation history;
        a second owner is how a turn gets persisted twice."""
        session = build_worker_session(
            llm=fake_llm(), registry=FakeRegistry(), model="m", system_prompt="s",
        )
        assert session.store is None


class TestTurnShape:

    def test_the_system_prompt_and_question_reach_the_model(self):
        llm = fake_llm()
        result = asyncio.run(session_llm_call(
            "m", "YOU ARE A FLEET WORKER", "what is 6*7",
            registry=FakeRegistry(), llm=llm,
        ))
        messages, model, kwargs = type(llm).seen[0]
        assert messages[0] == {"role": "system", "content": "YOU ARE A FLEET WORKER"}
        assert messages[-1]["content"] == "what is 6*7"
        assert model == "m"
        assert result == "the answer"

    def test_the_token_budget_survives_the_migration(self):
        """Reasoning models bill hidden chain-of-thought against max_tokens.
        The path this replaces raised it to 8192 after replies were being
        truncated mid-sentence; a migration that reset it would reintroduce
        that silently."""
        llm = fake_llm()
        asyncio.run(session_llm_call(
            "m", "s", "q", registry=FakeRegistry(), llm=llm,
        ))
        _, _, kwargs = type(llm).seen[0]
        assert kwargs.get("max_tokens") == 8192
        assert kwargs.get("temperature") == 0.3

    def test_the_return_is_the_text_not_a_result_object(self):
        """`worker_turn`'s three persona handlers all do
        `response = await llm_call(...)` and treat it as a string."""
        out = asyncio.run(session_llm_call(
            "m", "s", "q", registry=FakeRegistry(), llm=fake_llm("plain text"),
        ))
        assert isinstance(out, str)
        assert out == "plain text"


class TestAuditIsNotLost:
    """The requirement that no test result would show if it broke."""

    def _audit(self):
        return mock.patch.multiple(
            "agent.services.agent_audit",
            new_req_id=mock.DEFAULT,
            audit_request=mock.DEFAULT,
            audit_response=mock.DEFAULT,
            audit_error=mock.DEFAULT,
        )

    def test_a_successful_call_is_audited_end_to_end(self):
        with self._audit() as patched:
            patched["new_req_id"].return_value = "req-1"
            asyncio.run(session_llm_call(
                "m", "sys", "question", registry=FakeRegistry(), llm=fake_llm("A"),
            ))

        req = patched["audit_request"].call_args.kwargs
        assert req["req_id"] == "req-1"
        assert req["model"] == "m"
        assert req["messages"][-1]["content"] == "question", (
            "the full request, not a summary of it"
        )

        resp = patched["audit_response"].call_args.kwargs
        assert resp["req_id"] == "req-1"
        assert resp["content"] == "A"
        assert patched["audit_error"].called is False

    def test_a_failed_turn_is_audited_as_an_error(self):
        from agent.runtime.llm_stream import LLMAuthError

        class Dead:
            def stream(self, messages, model, **kwargs):
                async def gen():
                    raise LLMAuthError("bad key")
                    yield  # pragma: no cover

                return gen()

        with self._audit() as patched:
            patched["new_req_id"].return_value = "req-2"
            with pytest.raises(Exception):
                asyncio.run(session_llm_call(
                    "m", "s", "q", registry=FakeRegistry(), llm=Dead(),
                ))

        assert patched["audit_error"].called
        err = patched["audit_error"].call_args.kwargs
        assert err["req_id"] == "req-2"
        assert "llm_auth" in (err["error_type"] + err["error_msg"])

    def test_a_failure_raises_so_the_launcher_marks_the_task_failed(self):
        """`execute_task` never raises — it catches and reports
        status=failed. That only works if the call raises."""
        from agent.runtime.llm_stream import LLMTransportError
        from fleet.worker_turn import WorkerTurnError

        class Dead:
            def stream(self, messages, model, **kwargs):
                async def gen():
                    raise LLMTransportError("refused")
                    yield  # pragma: no cover

                return gen()

        with pytest.raises((WorkerTurnError, LLMTransportError)):
            asyncio.run(session_llm_call(
                "m", "s", "q", registry=FakeRegistry(), llm=Dead(),
            ))

    def test_usage_reaches_the_audit_record(self):
        with self._audit() as patched:
            patched["new_req_id"].return_value = "req-3"
            asyncio.run(session_llm_call(
                "m", "s", "q",
                registry=FakeRegistry(),
                llm=fake_llm("A", usage={
                    "prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14,
                }),
            ))
        resp = patched["audit_response"].call_args.kwargs
        assert resp["usage"].get("total_tokens") == 14
