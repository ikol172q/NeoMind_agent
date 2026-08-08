"""Fail-closed permission tests for the non-interactive headless loop."""

import json
import sys
import types
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import main
from agent.coding.tool_schema import PermissionLevel


_MISSING = object()


def _tool(permission_level, result="tool output"):
    definition = SimpleNamespace(
        apply_defaults=Mock(side_effect=lambda params: params),
        execute=Mock(return_value=result),
    )
    if permission_level is not _MISSING:
        definition.permission_level = permission_level
    return definition


def _run_headless(
    monkeypatch, capsys, tool_name, tool_definition, closing_tag="call"
):
    raw_xml = (
        '<tool_call>{"tool": "' + tool_name + '", '
        '"params": {"path": "/tmp/secret-payload"}}</tool_' + closing_tag + '>'
    )
    fake_agent = SimpleNamespace(
        conversation_history=[],
        stream_response=Mock(side_effect=[
            f"Attempting tool.\n{raw_xml}",
            "Finished safely.",
        ]),
        add_to_history=Mock(),
        verbose_mode=True,
    )

    config_module = types.ModuleType("agent_config")
    config_module.agent_config = SimpleNamespace(
        mode="chat",
        system_prompt=None,
        switch_mode=Mock(),
    )
    core_module = types.ModuleType("agent.core")
    core_module.NeoMindAgent = Mock(return_value=fake_agent)

    registry = SimpleNamespace(get_tool=Mock(return_value=tool_definition))
    tools_module = types.ModuleType("agent.tools")
    tools_module.ToolRegistry = Mock(return_value=registry)

    monkeypatch.setitem(sys.modules, "agent_config", config_module)
    monkeypatch.setitem(sys.modules, "agent.core", core_module)
    monkeypatch.setitem(sys.modules, "agent.tools", tools_module)

    with pytest.raises(SystemExit) as exc_info:
        main.headless_main("test prompt")

    assert exc_info.value.code == 0
    return fake_agent, registry, capsys.readouterr().out, raw_xml


def _install_headless_agent(monkeypatch, stream_side_effect):
    fake_agent = SimpleNamespace(
        conversation_history=[],
        stream_response=Mock(side_effect=stream_side_effect),
        verbose_mode=True,
    )
    config_module = types.ModuleType("agent_config")
    config_module.agent_config = SimpleNamespace(
        mode="chat",
        system_prompt=None,
        switch_mode=Mock(),
    )
    core_module = types.ModuleType("agent.core")
    core_module.NeoMindAgent = Mock(return_value=fake_agent)
    monkeypatch.setitem(sys.modules, "agent_config", config_module)
    monkeypatch.setitem(sys.modules, "agent.core", core_module)
    return fake_agent


@pytest.mark.parametrize(
    "permission_level",
    [
        PermissionLevel.WRITE,
        PermissionLevel.EXECUTE,
        PermissionLevel.DESTRUCTIVE,
        None,
        "read_only",
        _MISSING,
    ],
    ids=["write", "execute", "destructive", "none", "string", "missing"],
)
def test_headless_denies_every_non_read_only_tool(
    monkeypatch, capsys, permission_level
):
    definition = _tool(permission_level)

    agent, _, output, raw_xml = _run_headless(
        monkeypatch, capsys, "Write", definition
    )

    definition.execute.assert_not_called()
    definition.apply_defaults.assert_not_called()
    assert agent.stream_response.call_count == 2
    history = "\n".join(call.args[1] for call in agent.add_to_history.call_args_list)
    assert "Permission denied" in history
    assert "was not executed" in history
    assert raw_xml not in history
    assert "/tmp/secret-payload" not in history
    assert "<tool_call>" not in output
    assert output.strip() == "Finished safely."


def test_headless_denies_unknown_tool_and_feeds_sanitized_result(monkeypatch, capsys):
    agent, registry, output, raw_xml = _run_headless(
        monkeypatch, capsys, "MysteryTool", None, closing_tag="report"
    )

    registry.get_tool.assert_called_once_with("MysteryTool")
    history = "\n".join(call.args[1] for call in agent.add_to_history.call_args_list)
    assert "Permission denied: unknown tools" in history
    assert raw_xml not in history
    assert "/tmp/secret-payload" not in history
    assert "<tool_call>" not in output
    assert output.strip() == "Finished safely."


def test_headless_still_executes_read_only_tool(monkeypatch, capsys):
    definition = _tool(PermissionLevel.READ_ONLY, result="file contents")

    agent, _, output, _ = _run_headless(monkeypatch, capsys, "Read", definition)

    definition.apply_defaults.assert_called_once_with({
        "path": "/tmp/secret-payload"
    })
    definition.execute.assert_called_once_with(path="/tmp/secret-payload")
    history = "\n".join(call.args[1] for call in agent.add_to_history.call_args_list)
    assert "file contents" in history
    assert "Permission denied" not in history
    assert output.strip() == "Finished safely."


def test_headless_pipe_tool_call_is_removed_from_history_and_output(
    monkeypatch, capsys
):
    definition = _tool(PermissionLevel.READ_ONLY, result="file contents")
    raw = (
        '<|tool_call|>{"tool":"Read",'
        '"params":{"path":"/tmp/pipe-secret"}}<|/tool_call|>'
    )
    fake_agent = _install_headless_agent(
        monkeypatch,
        [f"Attempting tool.\n{raw}", "Finished safely."],
    )
    # Real NeoMindAgent.stream_response() persists its assistant response
    # before returning; exercise that side effect instead of relying only on
    # the lighter mock behavior used by the other headless tests.
    fake_agent.conversation_history = [
        {"role": "assistant", "content": f"Attempting tool.\n{raw}"},
    ]
    fake_agent.add_to_history = Mock()
    registry = SimpleNamespace(get_tool=Mock(return_value=definition))
    tools_module = types.ModuleType("agent.tools")
    tools_module.ToolRegistry = Mock(return_value=registry)
    monkeypatch.setitem(sys.modules, "agent.tools", tools_module)

    with pytest.raises(SystemExit) as exc_info:
        main.headless_main("test prompt")

    assert exc_info.value.code == 0
    persisted_history = "\n".join(
        message["content"] for message in fake_agent.conversation_history
    )
    history = "\n".join(
        call.args[1] for call in fake_agent.add_to_history.call_args_list
    )
    output = capsys.readouterr().out
    assert "pipe-secret" not in persisted_history
    assert "tool_call" not in persisted_history
    assert "pipe-secret" not in history
    assert "tool_call" not in history
    assert "pipe-secret" not in output
    assert "tool_call" not in output
    assert output.strip() == "Finished safely."


@pytest.mark.parametrize("opener", ["<tool_call>", "<|tool_call_begin|>"])
def test_headless_malformed_unclosed_tool_payload_never_reaches_output(
    monkeypatch, capsys, opener
):
    _install_headless_agent(
        monkeypatch,
        [f"Safe prefix.\n{opener}not-valid-json secret-payload"],
    )

    with pytest.raises(SystemExit) as exc_info:
        main.headless_main("test prompt")

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert output.strip() == "Safe prefix."
    assert "tool_call" not in output
    assert "secret-payload" not in output


@pytest.mark.parametrize("output_format", ["text", "json"])
def test_headless_interrupt_exits_130_without_traceback(
    monkeypatch, capsys, output_format
):
    agent = _install_headless_agent(monkeypatch, KeyboardInterrupt())

    with pytest.raises(SystemExit) as exc_info:
        main.headless_main("test prompt", output_format=output_format)

    captured = capsys.readouterr()
    assert exc_info.value.code == 130
    assert captured.out == ""
    assert "Traceback" not in captured.err
    if output_format == "json":
        assert json.loads(captured.err) == {"error": "Interrupted"}
    else:
        assert captured.err == "Interrupted.\n"
    agent.stream_response.assert_called_once_with("test prompt")


def test_headless_regular_exception_keeps_error_exit(monkeypatch, capsys):
    _install_headless_agent(monkeypatch, RuntimeError("ordinary failure"))

    with pytest.raises(SystemExit) as exc_info:
        main.headless_main("test prompt")

    captured = capsys.readouterr()
    assert exc_info.value.code == 1
    assert captured.out == ""
    assert captured.err == "Error: ordinary failure\n"
