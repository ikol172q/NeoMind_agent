"""Phase 3 gate — `AgentSession` owns the turn.

Fakes here stand in for the provider and the registry, not for the session or
the executor: those two are the things under test, and a test that mocks them
proves only that this file's assumptions are self-consistent. The real
executor runs, with the real permission policy.
"""

from __future__ import annotations

import asyncio
import json

import pytest

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
from agent.runtime.headless import consume, render
from agent.runtime.llm_stream import (
    FinishChunk,
    LLMAuthError,
    LLMTimeout,
    TextChunk,
    ThinkingChunk,
    UsageChunk,
)
from agent.runtime.permissions import CapabilitySnapshot, PermissionPolicy
from agent.runtime.session import AgentSession
from agent.runtime.tool_executor import ToolExecutor


# ── fakes for the two edges ───────────────────────────────────────────────


class ScriptedLLM:
    """Replays a list of per-round chunk lists."""

    def __init__(self, rounds):
        self.rounds = list(rounds)
        self.calls = []

    def stream(self, messages, model, **kwargs):
        self.calls.append([dict(m) for m in messages])
        chunks = self.rounds.pop(0) if self.rounds else [FinishChunk(reason="stop")]

        async def gen():
            for c in chunks:
                await asyncio.sleep(0)
                yield c

        return gen()


class FailingLLM:
    def __init__(self, exc):
        self.exc = exc

    def stream(self, messages, model, **kwargs):
        exc = self.exc

        async def gen():
            if False:
                yield  # pragma: no cover - makes this an async generator
            raise exc

        return gen()


class FakeToolDef:
    def __init__(self, name, level, output="tool output", raises=None):
        self.name = name
        self.permission_level = level
        self._output = output
        self._raises = raises

    def apply_defaults(self, params):
        return dict(params)

    def validate(self, params):
        return True, ""

    def execute(self, **params):
        if self._raises:
            raise self._raises
        return self._output


class FakeRegistry:
    def __init__(self, tools):
        self._tools = {t.name: t for t in tools}

    def get_tool(self, name):
        return self._tools.get(name)

    def get_all_tools(self):
        return list(self._tools.values())


class FakeToolCall:
    def __init__(self, tool_name, params):
        self.tool_name = tool_name
        self.params = params


class ScriptedParser:
    """Returns a tool call for the first N assistant texts, then nothing."""

    def __init__(self, calls):
        self.calls = list(calls)

    def parse(self, text):
        if not text or not self.calls:
            return None
        return self.calls.pop(0)

    def strip_tool_call(self, text, tool_call):
        return text.replace("<tool_call>", "").replace("</tool_call>", "").strip()


def read_only_executor(registry):
    """The capability snapshot headless runs with."""
    return ToolExecutor(
        registry=registry,
        policy=PermissionPolicy(capabilities=CapabilitySnapshot.unrestricted()),
    )


def drain(session, text):
    async def go():
        return [e async for e in session.run_turn(text)]

    return asyncio.run(go())


# ── plain turn ────────────────────────────────────────────────────────────


class TestPlainTurn:

    def make(self, **kw):
        llm = ScriptedLLM([[
            ThinkingChunk(text="pondering"),
            TextChunk(text="Hello"),
            TextChunk(text=", world."),
            UsageChunk(prompt_tokens=10, completion_tokens=4, total_tokens=14),
            FinishChunk(reason="stop"),
        ]])
        return AgentSession(llm=llm, executor=None, model="m", **kw), llm

    def test_event_order(self):
        session, _ = self.make()
        events = drain(session, "hi")
        kinds = [e.type for e in events]
        assert kinds[0] == "turn_started"
        assert kinds[-1] == "turn_finished"
        assert "text_delta" in kinds and "thinking_delta" in kinds

    def test_sequence_numbers_are_monotonic(self):
        session, _ = self.make()
        seqs = [e.sequence for e in drain(session, "hi")]
        assert seqs == sorted(seqs)
        assert len(set(seqs)) == len(seqs), "sequence numbers must be unique in a turn"

    def test_all_events_share_the_turn_and_session_id(self):
        session, _ = self.make()
        events = drain(session, "hi")
        assert len({e.turn_id for e in events}) == 1
        assert {e.session_id for e in events} == {session.session_id}

    def test_final_response_is_the_assembled_text(self):
        session, _ = self.make()
        finished = [e for e in drain(session, "hi") if isinstance(e, TurnFinished)][0]
        assert finished.response == "Hello, world."

    def test_usage_is_reported_and_accumulated(self):
        session, _ = self.make()
        finished = [e for e in drain(session, "hi") if isinstance(e, TurnFinished)][0]
        assert finished.usage["total_tokens"] == 14
        assert session.snapshot().usage["prompt_tokens"] == 10

    def test_each_message_is_recorded_exactly_once(self):
        session, _ = self.make()
        drain(session, "hi")
        history = session.history
        assert [m["role"] for m in history] == ["user", "assistant"]
        assert history[0]["content"] == "hi"
        assert history[1]["content"] == "Hello, world."

    def test_history_is_a_copy(self):
        session, _ = self.make()
        drain(session, "hi")
        session.history.append({"role": "user", "content": "smuggled"})
        assert len(session.history) == 2

    def test_snapshot_tracks_turns(self):
        session, _ = self.make()
        assert session.snapshot().turn_count == 0
        drain(session, "hi")
        assert session.snapshot().turn_count == 1
        assert session.snapshot().active_turn_id is None


# ── tool round ────────────────────────────────────────────────────────────


class TestToolRound:

    def make(self, tool, parser_calls, second_round_text="Done."):
        llm = ScriptedLLM([
            [TextChunk(text="<tool_call>run</tool_call>"), FinishChunk(reason="stop")],
            [TextChunk(text=second_round_text), FinishChunk(reason="stop")],
        ])
        registry = FakeRegistry([tool])
        return AgentSession(
            llm=llm,
            executor=read_only_executor(registry),
            model="m",
            tool_parser=ScriptedParser(parser_calls),
        )

    def test_read_only_tool_runs_and_reports(self):
        tool = FakeToolDef("Read", "read_only", output="file contents")
        session = self.make(tool, [FakeToolCall("Read", {"path": "a.txt"})])
        events = drain(session, "read a.txt")
        finished = [e for e in events if isinstance(e, ToolFinished)]
        assert len(finished) == 1
        assert finished[0].success is True
        assert "file contents" in finished[0].preview

    def test_tool_lifecycle_events_are_emitted_in_order(self):
        tool = FakeToolDef("Read", "read_only")
        session = self.make(tool, [FakeToolCall("Read", {"path": "a.txt"})])
        kinds = [e.type for e in drain(session, "go")]
        assert kinds.index("tool_proposed") < kinds.index("tool_started")
        assert kinds.index("tool_started") < kinds.index("tool_finished")

    def test_tool_result_is_fed_back_once(self):
        tool = FakeToolDef("Read", "read_only", output="contents")
        session = self.make(tool, [FakeToolCall("Read", {"path": "a.txt"})])
        drain(session, "go")
        tool_msgs = [m for m in session.history if m.get("_tool_result")]
        assert len(tool_msgs) == 1
        assert "contents" in tool_msgs[0]["content"]

    def test_raw_tool_payload_is_not_kept_in_history(self):
        """Replaying history must not re-arm an executable block."""
        tool = FakeToolDef("Read", "read_only")
        session = self.make(tool, [FakeToolCall("Read", {"path": "a.txt"})])
        drain(session, "go")
        assert not [m for m in session.history if "<tool_call>" in str(m.get("content"))]

    def test_history_has_no_duplicate_assistant_message(self):
        tool = FakeToolDef("Read", "read_only")
        session = self.make(tool, [FakeToolCall("Read", {"path": "a.txt"})])
        drain(session, "go")
        roles = [m["role"] for m in session.history]
        assert roles.count("assistant") == 2, roles  # one per provider round

    def test_denied_tool_is_reported_as_denial_not_error(self):
        """A refusal the model reads as an error is a refusal it retries."""
        tool = FakeToolDef("Write", "write")
        registry = FakeRegistry([tool])
        executor = ToolExecutor(
            registry=registry,
            policy=PermissionPolicy(capabilities=CapabilitySnapshot.only("Read")),
        )
        llm = ScriptedLLM([
            [TextChunk(text="<tool_call>w</tool_call>"), FinishChunk(reason="stop")],
            [TextChunk(text="Understood."), FinishChunk(reason="stop")],
        ])
        session = AgentSession(
            llm=llm,
            executor=executor,
            model="m",
            tool_parser=ScriptedParser([FakeToolCall("Write", {"path": "x"})]),
        )
        drain(session, "write x")
        fed = [m for m in session.history if m.get("_tool_result")][0]["content"]
        assert "Permission denied" in fed, fed

    def test_tool_rounds_are_bounded(self):
        tool = FakeToolDef("Read", "read_only")
        registry = FakeRegistry([tool])
        rounds = [[TextChunk(text="<tool_call>x</tool_call>"), FinishChunk(reason="stop")]] * 30
        session = AgentSession(
            llm=ScriptedLLM(rounds),
            executor=read_only_executor(registry),
            model="m",
            tool_parser=ScriptedParser([FakeToolCall("Read", {"path": "a"})] * 30),
            max_tool_rounds=3,
        )
        events = drain(session, "loop")
        assert len([e for e in events if isinstance(e, ToolStarted)]) == 3
        assert [e for e in events if isinstance(e, TurnFinished)]


# ── failure and cancellation ──────────────────────────────────────────────


class TestTerminalEvents:

    def test_provider_error_becomes_one_turn_failed(self):
        session = AgentSession(llm=FailingLLM(LLMAuthError("bad key")), executor=None, model="m")
        events = drain(session, "hi")
        failed = [e for e in events if isinstance(e, TurnFailed)]
        assert len(failed) == 1
        assert failed[0].error_code == "llm_auth"
        assert failed[0].retryable is False
        assert not [e for e in events if isinstance(e, TurnFinished)]

    def test_retryable_error_is_marked_retryable(self):
        session = AgentSession(llm=FailingLLM(LLMTimeout("slow")), executor=None, model="m")
        failed = [e for e in drain(session, "hi") if isinstance(e, TurnFailed)][0]
        assert failed.error_code == "llm_timeout"
        assert failed.retryable is True

    def test_unexpected_exception_still_terminates_the_turn(self):
        session = AgentSession(llm=FailingLLM(ValueError("boom")), executor=None, model="m")
        failed = [e for e in drain(session, "hi") if isinstance(e, TurnFailed)][0]
        assert failed.error_code == "internal_error"
        assert "boom" in failed.message

    def test_exactly_one_terminal_event_per_turn(self):
        for llm in (
            ScriptedLLM([[TextChunk(text="ok"), FinishChunk(reason="stop")]]),
            FailingLLM(LLMTimeout("slow")),
            FailingLLM(RuntimeError("x")),
        ):
            session = AgentSession(llm=llm, executor=None, model="m")
            events = drain(session, "hi")
            terminal = [e for e in events if isinstance(e, (TurnFinished, TurnFailed))]
            assert len(terminal) == 1, [e.type for e in events]

    def test_cancel_before_the_turn_starts_streaming(self):
        session = AgentSession(
            llm=ScriptedLLM([[TextChunk(text="never"), FinishChunk(reason="stop")]]),
            executor=None,
            model="m",
        )

        async def go():
            events = []
            agen = session.run_turn("hi")
            async for event in agen:
                events.append(event)
                if isinstance(event, TurnStarted):
                    await session.cancel(event.turn_id)
            return events

        events = asyncio.run(go())
        failed = [e for e in events if isinstance(e, TurnFailed)]
        assert len(failed) == 1
        assert failed[0].error_code == "cancelled"


# ── permission plumbing ───────────────────────────────────────────────────


class TestPermissionResolution:

    def test_resolving_an_unknown_request_is_ignored(self):
        session = AgentSession(llm=None, executor=None, model="m")
        asyncio.run(session.resolve_permission("req_nope", "allow"))  # must not raise

    def test_cancel_clears_pending_permission_futures(self):
        session = AgentSession(llm=None, executor=None, model="m")

        async def go():
            loop = asyncio.get_event_loop()
            session._pending_permissions["req_1"] = loop.create_future()
            await session.cancel("trn_x")
            return session._pending_permissions

        assert asyncio.run(go()) == {}


# ── headless consumer ─────────────────────────────────────────────────────


class TestHeadlessConsumer:

    def test_text_output_is_the_final_response(self):
        session = AgentSession(
            llm=ScriptedLLM([[
                TextChunk(text="Four."),
                UsageChunk(prompt_tokens=3, completion_tokens=2, total_tokens=5),
                FinishChunk(reason="stop"),
            ]]),
            executor=None,
            model="m",
        )
        result = asyncio.run(consume(session.run_turn("2+2?")))
        assert result.ok is True
        assert render(result, "text") == "Four."

    def test_json_output_carries_usage_and_shape(self):
        session = AgentSession(
            llm=ScriptedLLM([[
                TextChunk(text="Four."),
                UsageChunk(prompt_tokens=3, completion_tokens=2, total_tokens=5),
                FinishChunk(reason="stop"),
            ]]),
            executor=None,
            model="m",
        )
        result = asyncio.run(consume(session.run_turn("2+2?")))
        payload = json.loads(render(result, "json"))
        assert payload["ok"] is True
        assert payload["response"] == "Four."
        assert payload["usage"]["total_tokens"] == 5

    def test_failure_gives_a_stable_error_code_in_json(self):
        session = AgentSession(llm=FailingLLM(LLMAuthError("bad key")), executor=None, model="m")
        result = asyncio.run(consume(session.run_turn("hi")))
        payload = json.loads(render(result, "json"))
        assert payload["ok"] is False
        assert payload["error"]["code"] == "llm_auth"
        assert payload["error"]["retryable"] is False

    def test_failure_text_output_names_the_code(self):
        session = AgentSession(llm=FailingLLM(LLMTimeout("slow")), executor=None, model="m")
        result = asyncio.run(consume(session.run_turn("hi")))
        assert "llm_timeout" in render(result, "text")

    def test_empty_response_does_not_render_as_blank(self):
        session = AgentSession(
            llm=ScriptedLLM([[FinishChunk(reason="stop")]]), executor=None, model="m"
        )
        result = asyncio.run(consume(session.run_turn("hi")))
        assert render(result, "text") == "(no response)"

    def test_tools_are_summarised_for_json_output(self):
        tool = FakeToolDef("Read", "read_only", output="data")
        registry = FakeRegistry([tool])
        session = AgentSession(
            llm=ScriptedLLM([
                [TextChunk(text="<tool_call>r</tool_call>"), FinishChunk(reason="stop")],
                [TextChunk(text="Done."), FinishChunk(reason="stop")],
            ]),
            executor=read_only_executor(registry),
            model="m",
            tool_parser=ScriptedParser([FakeToolCall("Read", {"path": "a"})]),
        )
        result = asyncio.run(consume(session.run_turn("go")))
        payload = json.loads(render(result, "json"))
        assert payload["tools"] == [{"tool": "Read", "success": True, "error": ""}]

    def test_a_stream_with_no_terminal_event_is_reported_not_hidden(self):
        async def truncated():
            from agent.runtime.events import TurnStarted as TS

            yield TS(session_id="s", turn_id="t", sequence=0)

        result = asyncio.run(consume(truncated()))
        assert result.ok is False
        assert result.error_code == "no_terminal_event"


# ── the turn must not pass off an unexecuted tool call as work done ────────


REAL_FABRICATED_EDIT = (
    "I found the file and it does contain \"WIDGET\". Now I'll replace both "
    "occurrences.\n[tool:Edit] # /tmp/acp_write_target.md"
)
"""Captured from a run that reported edits it never made.

Only the search term is changed — the real probe used a word that names a
real person's broker, and this repository is public. The shape, which is
what the test turns on, is exactly what the model emitted.

The model answered one call in the structured spelling the parser reads and
improvised `[tool:Edit]` for the next. The parser saw prose, the turn ended
`TurnFinished`, and the client was told two specific lines had been rewritten.
The file was untouched. Kept as a literal so the test breaks against what
actually happened rather than against a shape someone imagined.
"""


class NoParser:
    """Reads nothing — stands in for a spelling the real parser cannot read."""

    def parse(self, text):
        return None

    def strip_tool_call(self, text, tool_call):  # pragma: no cover - never called
        return text


def _session_over(rounds, tools=("Edit", "Read"), parser=None):
    registry = FakeRegistry([FakeToolDef(n, "READ_ONLY") for n in tools])
    return AgentSession(
        llm=ScriptedLLM(rounds),
        executor=read_only_executor(registry),
        tool_parser=parser or NoParser(),
    )


def _run(session, text="edit the file"):
    async def go():
        return [e async for e in session.run_turn(text)]

    return asyncio.run(go())


class TestUnexecutedToolCallIsNotAnAnswer:

    def test_the_real_fabrication_is_caught(self):
        """The captured output, run through the real turn loop."""
        session = _session_over([
            [TextChunk(text=REAL_FABRICATED_EDIT), FinishChunk(reason="stop")],
            [TextChunk(text="Sorry — I did not edit anything."),
             FinishChunk(reason="stop")],
        ])
        events = _run(session)
        codes = [e.code for e in events if isinstance(e, StatusChanged)]
        assert "tool_call_unparsed" in codes, (
            "a turn that names a real tool in an unreadable spelling reported "
            "success; nothing distinguished it from work actually done"
        )

    def test_the_model_is_told_and_gets_one_retry(self):
        session = _session_over([
            [TextChunk(text=REAL_FABRICATED_EDIT), FinishChunk(reason="stop")],
            [TextChunk(text="Nothing was changed."), FinishChunk(reason="stop")],
        ])
        _run(session)
        # Two provider calls: the original, then the reissue request.
        assert len(session.llm.calls) == 2
        correction = session.llm.calls[1][-1]
        assert correction["role"] == "user"
        assert "nothing ran" in correction["content"].lower()
        assert "Edit" in correction["content"]

    def test_a_second_failure_is_reported_not_swallowed(self):
        """One retry, then say plainly that the described action did not happen."""
        session = _session_over([
            [TextChunk(text=REAL_FABRICATED_EDIT), FinishChunk(reason="stop")],
            [TextChunk(text=REAL_FABRICATED_EDIT), FinishChunk(reason="stop")],
        ])
        events = _run(session)
        codes = [e.code for e in events if isinstance(e, StatusChanged)]
        assert codes.count("tool_call_unparsed") == 1, "retried more than once"
        assert "tool_call_unparsed_final" in codes
        final = [e for e in events if isinstance(e, StatusChanged)][-1]
        assert "did not happen" in final.text

    def test_the_turn_still_ends_with_exactly_one_terminal_event(self):
        """The contract holds through the new branch."""
        session = _session_over([
            [TextChunk(text=REAL_FABRICATED_EDIT), FinishChunk(reason="stop")],
            [TextChunk(text=REAL_FABRICATED_EDIT), FinishChunk(reason="stop")],
        ])
        events = _run(session)
        terminal = [e for e in events if isinstance(e, (TurnFinished, TurnFailed))]
        assert len(terminal) == 1

    def test_prose_about_a_tool_is_not_treated_as_a_failed_call(self):
        """The check must not fire on an answer that merely mentions a tool."""
        session = _session_over([
            [TextChunk(text="You can use the Edit tool to change files."),
             FinishChunk(reason="stop")],
        ])
        events = _run(session)
        assert not [e for e in events if isinstance(e, StatusChanged)]
        assert len(session.llm.calls) == 1, "a plain answer was needlessly retried"

    def test_an_unknown_tool_name_does_not_fire(self):
        session = _session_over([
            [TextChunk(text="[tool:Frobnicate] do the thing"),
             FinishChunk(reason="stop")],
        ])
        events = _run(session)
        assert not [e for e in events if isinstance(e, StatusChanged)]

    def test_the_names_come_from_the_registry_the_executor_actually_has(self):
        """A lookup the real registry does not answer leaves the check inert —
        which is how this guard would ship as decoration."""
        from agent.tools import ToolRegistry

        session = AgentSession(
            llm=ScriptedLLM([]),
            executor=read_only_executor(ToolRegistry(working_dir=".")),
        )
        names = session._known_tool_names()
        assert names, "the real registry yielded no tool names"
        assert "Edit" in names

    def test_the_guard_holds_on_the_production_path(self):
        """Real registry, real executor, real ACP-shaped policy.

        The fakes above prove the branch; this proves it survives the wiring an
        ACP client actually gets — where `Edit` resolves, its level is `write`,
        and the policy would have asked. The point of the guard is that the
        turn never reached that question.
        """
        from agent.integration.acp_server import NeoMindACPAgent
        from agent.runtime.permissions import CapabilitySnapshot, PermissionPolicy
        from agent.tools import ToolRegistry

        registry = ToolRegistry(working_dir=".")
        policy = PermissionPolicy(
            capabilities=CapabilitySnapshot.only(
                *NeoMindACPAgent._allowed_tools(registry)
            ),
            interactive=True,
            auto_accept=False,
        )
        session = AgentSession(
            llm=ScriptedLLM([
                [TextChunk(text=REAL_FABRICATED_EDIT), FinishChunk(reason="stop")],
                [TextChunk(text=REAL_FABRICATED_EDIT), FinishChunk(reason="stop")],
            ]),
            executor=ToolExecutor(registry=registry, policy=policy, working_dir="."),
            tool_parser=NoParser(),
        )
        events = _run(session)
        codes = [e.code for e in events if isinstance(e, StatusChanged)]
        assert "tool_call_unparsed" in codes
        assert "tool_call_unparsed_final" in codes
        assert len([e for e in events if isinstance(e, (TurnFinished, TurnFailed))]) == 1
