"""ToolExecutor against the real ToolRegistry — no doubles.

This file exists because mocks hid a real defect once already: QueryEngine
called `tool_registry.execute(...)` and read `tool_result.status`, neither of
which the real objects have. Its tests passed for months because they mocked
the registry. Any port the runtime declares must be exercised against the
actual implementation at least once, or the port is a guess.
"""

import asyncio
import os
import tempfile

import pytest

from agent.runtime.permissions import CapabilitySnapshot, PermissionPolicy
from agent.runtime.tool_executor import ToolExecutor


@pytest.fixture
def workspace():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def registry(workspace):
    from agent.tools import ToolRegistry

    return ToolRegistry(working_dir=workspace)


def test_registry_really_lacks_an_execute_method(registry):
    """Pin the API the port is written against.

    If a future registry grows `.execute()`, this fails and whoever adds it
    gets to decide consciously whether the executor should use it — instead of
    a second QueryEngine quietly assuming it exists.
    """
    assert not hasattr(registry, "execute")
    assert hasattr(registry, "get_tool")
    assert hasattr(registry, "get_all_tools")


def test_real_read_tool_executes_through_the_executor(registry, workspace):
    path = os.path.join(workspace, "hello.txt")
    with open(path, "w") as fh:
        fh.write("contents from the real tool\n")

    ex = ToolExecutor(registry, PermissionPolicy(), working_dir=workspace)
    out = asyncio.run(ex.execute("Read", {"path": path}))

    assert out.executed, f"denied: {out.denied_reason}"
    assert out.success, f"failed: {out.error}"
    assert "contents from the real tool" in out.output


def test_real_write_tool_is_denied_without_a_broker(registry, workspace):
    """The headless/Telegram default: no one to ask means no write."""
    path = os.path.join(workspace, "should_not_exist.txt")

    ex = ToolExecutor(registry, PermissionPolicy(interactive=False), working_dir=workspace)
    out = asyncio.run(ex.execute("Write", {"path": path, "content": "nope"}))

    assert out.denied
    # The proof that matters is on disk, not in the return value.
    assert not os.path.exists(path), "denied write must not have touched the filesystem"


def test_real_tool_outside_capability_snapshot_is_denied(registry, workspace):
    path = os.path.join(workspace, "readable.txt")
    with open(path, "w") as fh:
        fh.write("x")

    ex = ToolExecutor(
        registry,
        PermissionPolicy(capabilities=CapabilitySnapshot.only("Glob")),
        working_dir=workspace,
    )
    out = asyncio.run(ex.execute("Read", {"path": path}))

    assert out.denied and "capability" in out.denied_reason


def test_real_tool_permission_levels_are_the_enum_the_policy_expects(registry):
    """Guard the string values the policy branches on.

    PermissionPolicy compares against 'read_only'/'write'/'execute'/
    'destructive'. If the enum's values are renamed, every classification
    silently becomes 'unclassified' — which fails closed, but would take every
    tool offline at once.
    """
    from agent.runtime.permissions import _KNOWN_LEVELS

    seen = set()
    for tool in registry.get_all_tools():
        level = getattr(tool, "permission_level", None)
        value = getattr(level, "value", level)
        if isinstance(value, str):
            seen.add(value)

    assert seen, "registry exposed no classified tools"
    unknown = seen - _KNOWN_LEVELS
    assert not unknown, f"policy does not know these permission levels: {sorted(unknown)}"
