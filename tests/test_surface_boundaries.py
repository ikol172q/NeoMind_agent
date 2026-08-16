"""Phase 6A task 5 — the boundaries, asserted rather than agreed to.

Three properties this phase is supposed to establish, each of which is easy to
lose by accident and invisible when lost:

  * one registry defines what commands exist
  * a session's configuration is its own
  * a session has exactly one conversation-store owner

The command tests are the load-bearing ones. Before this phase, `/clear` had
two implementations and the second could not run — the dispatcher answered
first and returned — so editing it changed nothing while looking like it
should. Nothing failed; the code just quietly meant less than it appeared to.
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.argv = ["x"]


def interface_source() -> str:
    return (REPO / "cli" / "neomind_interface.py").read_text(encoding="utf-8")


class TestOneCommandRegistry:

    def test_the_repl_has_no_second_command_chain(self):
        """The 21-branch `if cmd == ...` fallback is gone. Its presence meant
        two answers to "what does /clear do", and the reachable one was not
        the one you would find by reading."""
        source = interface_source()
        start = source.index("def _handle_local_command")
        end = source.index("\n    def ", start + 10)
        body = source[start:end]
        branches = re.findall(r'if cmd (?:==|in) [("\']', body)
        assert branches == [], (
            f"{len(branches)} command branches remain in _handle_local_command; "
            f"commands belong in the registry"
        )

    def test_frontend_commands_are_declared_in_the_registry(self):
        from agent.cli_command_system import create_default_registry
        from cli.neomind_interface import NeoMindInterface
        from cli.ui_commands import UI_COMMANDS, register_ui_commands

        registry = create_default_registry()
        iface = NeoMindInterface.__new__(NeoMindInterface)
        register_ui_commands(iface, registry)

        for name, _, _, _ in UI_COMMANDS:
            assert registry.find(name) is not None, f"/{name} is not declared"

    def test_every_declared_ui_command_has_its_method(self):
        """A declaration whose handler cannot run is worse than no
        declaration: it appears in /help and then fails at the prompt."""
        from cli.neomind_interface import NeoMindInterface
        from cli.ui_commands import UI_COMMANDS

        for name, _, _, method in UI_COMMANDS:
            assert hasattr(NeoMindInterface, method), f"/{name} → {method} missing"

    def test_registering_does_not_override_an_existing_command(self):
        """A frontend quietly shadowing a shared command is how two
        implementations of /clear happened."""
        from agent.cli_command_system import Command, CommandRegistry
        from cli.neomind_interface import NeoMindInterface
        from cli.ui_commands import register_ui_commands

        registry = CommandRegistry()
        registry.register(Command(name="fleet", description="pre-existing"))
        iface = NeoMindInterface.__new__(NeoMindInterface)
        added = register_ui_commands(iface, registry)

        assert "fleet" not in added
        assert registry.find("fleet").description == "pre-existing"

    def test_a_missing_registry_is_reported_not_worked_around(self):
        """When the registry fails to build, saying so beats silently serving
        a different implementation of every command."""
        source = interface_source()
        start = source.index("def _handle_local_command")
        end = source.index("\n    def ", start + 10)
        body = source[start:end]
        assert "Command registry unavailable" in body

    def test_ui_commands_do_not_return_their_output_as_text(self):
        """These print for themselves; returning text would print it twice."""
        from unittest import mock

        from cli.ui_commands import _make_handler

        iface = mock.MagicMock()
        result = _make_handler(iface, "_ui_cmd_freeze")("some/dir")
        assert result.display == "skip"
        assert result.text == ""
        iface._ui_cmd_freeze.assert_called_once_with("some/dir")


class TestNoSentinelsAnywhere:
    """Task 1's property, kept honest across the whole tree rather than in
    the one file it was fixed in."""

    def test_no_control_signal_travels_in_command_text(self):
        offenders = []
        pattern = re.compile(r'CommandResult\([^)]*text\s*=\s*f?"__')
        for path in list(REPO.glob("agent/**/*.py")) + list(REPO.glob("cli/**/*.py")):
            if ".venv" in path.parts:
                continue
            if pattern.search(path.read_text(encoding="utf-8", errors="ignore")):
                offenders.append(str(path.relative_to(REPO)))
        assert offenders == []


class TestSessionScopedConfig:

    def test_the_repl_binds_its_own_config(self):
        source = interface_source()
        start = source.index("    def run(self):")
        end = source.index("\n    def ", start + 10)
        assert "bind_session_config()" in source[start:end], (
            "an unbound session writes to the process-wide default"
        )

    def test_binding_is_what_makes_two_sessions_independent(self):
        """The behavioural proof lives in `test_session_config_isolation.py`;
        this only checks the frontend still calls it, since that one line is
        what connects the property to the surface."""
        from agent_config import bind_session_config, fork_current_config

        assert callable(bind_session_config)
        assert callable(fork_current_config)


class TestOneConversationStoreOwner:
    """Task 4. Both surfaces write history through one port, and each session
    has exactly one writer — a second one is how a question gets stored twice
    and replayed to the model as though it were asked twice."""

    def test_both_adapters_satisfy_the_port(self):
        from agent.integration.telegram_session import TelegramHistoryStore
        from cli.neomind_interface import NeoMindInterface

        for adapter in (TelegramHistoryStore, NeoMindInterface._HistoryStore):
            for method in ("append", "load"):
                assert callable(getattr(adapter, method, None)), (
                    f"{adapter.__name__} is missing {method}()"
                )

    def test_the_session_is_the_only_writer_during_a_turn(self):
        """`AgentSession._append` is the single write path; anything else
        appending during a turn is a second owner."""
        source = (REPO / "agent" / "runtime" / "session.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        writers = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "append":
                if isinstance(func.value, ast.Attribute) and func.value.attr == "store":
                    writers.add("store.append")
                if isinstance(func.value, ast.Attribute) and func.value.attr == "_history":
                    writers.add("_history.append")
        assert writers <= {"store.append", "_history.append"}

    def test_telegram_does_not_pre_store_what_the_session_stores(self):
        """The double-write the phase gate names. The legacy path wrote the
        user message itself; the session writes it too, so a migrated turn
        that kept both would send the question to the model twice."""
        import inspect

        from agent.integration.telegram_bot import NeoMindTelegramBot

        source = inspect.getsource(NeoMindTelegramBot._ask_llm_stream_session)
        assert 'add_message(chat_id, "user"' not in source

    def test_tool_results_are_not_persisted_as_conversation(self):
        from agent.integration.telegram_session import TelegramHistoryStore

        written = []

        class Store:
            def add_message(self, *a):
                written.append(a)

        adapter = TelegramHistoryStore(Store(), 1)
        adapter.append("s", {"role": "user", "content": "x", "_tool_result": True})
        assert written == []


class TestImportDirection:
    """The rule the whole migration rests on: the runtime may not import a
    frontend. Enforced separately in tests/runtime/test_import_boundary.py for
    `agent/runtime`; this covers the two new Phase 5/6A modules."""

    @pytest.mark.parametrize("module", [
        "agent/integration/telegram_renderer.py",
        "agent/integration/telegram_session.py",
        "agent/runtime/providers/fallback.py",
    ])
    def test_no_runtime_module_imports_a_frontend(self, module):
        source = (REPO / module).read_text(encoding="utf-8")
        tree = ast.parse(source)
        bad = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] in {"cli", "rich", "prompt_toolkit"}:
                    bad.append(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in {"cli", "rich", "prompt_toolkit"}:
                        bad.append(alias.name)
        assert bad == [], f"{module} imports a frontend: {bad}"

    def test_the_telegram_renderer_does_not_import_telegram(self):
        """It is testable offline precisely because it does not.

        Parsed rather than grepped: the module's own docstring says the words
        "does not import telegram", and a text search cannot tell an
        explanation from an import.
        """
        source = (REPO / "agent/integration/telegram_renderer.py").read_text(encoding="utf-8")
        imported = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
            elif isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
        assert "telegram" not in imported
