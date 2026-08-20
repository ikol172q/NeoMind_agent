"""AgenticLoop routed through the runtime executor (the session_v1 bridge).

Two things must hold at once during migration: with the switch off nothing
changes for the live CLI and Telegram surfaces, and with it on the tool is
dispatched by ToolExecutor rather than by the loop. Both are asserted here by
watching where execution actually happens, not by trusting configuration.
"""

import asyncio
import tempfile

import pytest

from agent.agentic.agentic_loop import AgenticConfig, AgenticLoop
from agent.runtime.permissions import CapabilitySnapshot, PermissionPolicy
from agent.runtime.tool_executor import ToolExecutor

READ_CALL = '<tool_call>{"tool": "Read", "params": {"path": "%s"}}</tool_call>'


@pytest.fixture
def workspace():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def sample_file(workspace):
    import os

    path = os.path.join(workspace, "note.txt")
    with open(path, "w") as fh:
        fh.write("bridged content\n")
    return path


def _registry(workspace):
    from agent.tools import ToolRegistry

    return ToolRegistry(working_dir=workspace)


def _drive(loop, llm_response, approve=True):
    """Run the loop, answering the permission handshake like a frontend."""

    async def _run():
        events = []

        async def llm_caller(messages):
            return "done"

        async for event in loop.run(llm_response, [], llm_caller):
            events.append(event)
            if event.type == "tool_start":
                event.approved = approve
        return events

    return asyncio.run(_run())


def test_switch_off_keeps_legacy_dispatch(workspace, sample_file):
    """Default config must not touch the runtime at all."""
    registry = _registry(workspace)
    loop = AgenticLoop(registry, AgenticConfig(max_iterations=1))

    assert loop.config.tool_executor is None

    events = _drive(loop, READ_CALL % sample_file)
    results = [e for e in events if e.type == "tool_result"]

    assert results and results[0].result_success
    assert "bridged content" in (results[0].result_output or "")


def test_switch_on_dispatches_through_the_executor(workspace, sample_file):
    registry = _registry(workspace)
    executor = ToolExecutor(registry, PermissionPolicy(), working_dir=workspace)

    seen = []
    original = executor.execute

    async def spy(tool_name, params, **kw):
        seen.append((tool_name, dict(params)))
        return await original(tool_name, params, **kw)

    executor.execute = spy
    loop = AgenticLoop(registry, AgenticConfig(max_iterations=1, tool_executor=executor))

    events = _drive(loop, READ_CALL % sample_file)
    results = [e for e in events if e.type == "tool_result"]

    # Params arrive with the tool's defaults already applied (the loop applies
    # them before handing over), so assert on identity rather than exact shape.
    assert len(seen) == 1, f"executor was not used exactly once: {seen}"
    assert seen[0][0] == "Read"
    assert seen[0][1]["path"] == sample_file
    assert results and results[0].result_success
    assert "bridged content" in (results[0].result_output or "")


def test_executor_denial_becomes_a_tool_result_not_an_exception(workspace, sample_file):
    """A blocked call is information the model can act on.

    Raising here would abort the turn; the model instead needs to see that the
    tool was refused so it can choose another route.
    """
    registry = _registry(workspace)
    executor = ToolExecutor(
        registry,
        PermissionPolicy(capabilities=CapabilitySnapshot.only("Glob")),
        working_dir=workspace,
    )
    loop = AgenticLoop(registry, AgenticConfig(max_iterations=1, tool_executor=executor))

    events = _drive(loop, READ_CALL % sample_file)
    results = [e for e in events if e.type == "tool_result"]

    assert results, "a denial must still produce a tool_result"
    assert results[0].result_success is False
    assert "Blocked" in (results[0].result_error or "")


def test_bridge_still_fails_closed_when_the_frontend_denies(workspace, sample_file):
    """The switch must not weaken the handshake it bridges."""
    registry = _registry(workspace)
    executor = ToolExecutor(registry, PermissionPolicy(), working_dir=workspace)

    seen = []
    original = executor.execute

    async def spy(tool_name, params, **kw):
        seen.append(tool_name)
        return await original(tool_name, params, **kw)

    executor.execute = spy

    # A write, so the loop's own handshake governs it rather than the
    # read-only auto-approval path.
    import os

    target = os.path.join(workspace, "denied.txt")
    call = '<tool_call>{"tool": "Write", "params": {"path": "%s", "content": "x"}}</tool_call>' % target

    loop = AgenticLoop(registry, AgenticConfig(max_iterations=1, tool_executor=executor))
    _drive(loop, call, approve=False)

    assert seen == [], "a denied call must never reach the executor"
    assert not os.path.exists(target), "denied write touched the filesystem"


def test_bridge_preserves_tool_result_shape(workspace, sample_file):
    """Downstream code reads success/output/error/metadata off a ToolResult."""
    registry = _registry(workspace)
    executor = ToolExecutor(registry, PermissionPolicy(), working_dir=workspace)
    loop = AgenticLoop(registry, AgenticConfig(max_iterations=1, tool_executor=executor))

    events = _drive(loop, READ_CALL % sample_file)
    result_events = [e for e in events if e.type == "tool_result"]

    assert result_events
    assert isinstance(result_events[0].result_output, str)
    assert result_events[0].result_error in (None, "")
