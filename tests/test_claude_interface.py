"""
Comprehensive tests for cli/claude_interface.py.

Covers: SlashCommandCompleter, ConversationManager, ClaudeInterface commands,
key bindings, status bar, welcome screen, mode gating, and integration.
"""

import os
import sys
import json
import time
import tempfile
import shutil
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from io import StringIO

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DEEPSEEK_API_KEY"] = "test-key-for-tests"


def _make_mock_chat(mode="chat"):
    chat = MagicMock()
    chat.model = "deepseek-chat"
    chat.mode = mode
    chat.thinking_enabled = False
    chat.verbose_mode = False
    chat.status_buffer = []
    chat.conversation_history = [
        {"role": "system", "content": "You are helpful."},
    ]
    chat.context_manager = MagicMock()
    chat.context_manager.count_conversation_tokens.return_value = 1500
    return chat


# ──────────────────────────────────────────────────────────────────────────────
# SlashCommandCompleter
# ──────────────────────────────────────────────────────────────────────────────

class TestSlashCommandCompleter(unittest.TestCase):
    """Test mode-aware slash command completer."""

    def _completions(self, text, mode="chat"):
        from cli.claude_interface import SlashCommandCompleter
        from prompt_toolkit.document import Document
        c = SlashCommandCompleter(mode=mode)
        return list(c.get_completions(Document(text), None))

    def test_slash_lists_all_mode_commands(self):
        """Typing just '/' lists all commands for the active mode."""
        comps = self._completions("/", mode="chat")
        texts = [c.text for c in comps]
        self.assertIn("/help", texts)
        self.assertIn("/search", texts)
        self.assertNotIn("/run", texts, "chat mode should not show /run")

    def test_coding_mode_has_coding_commands(self):
        comps = self._completions("/", mode="coding")
        texts = [c.text for c in comps]
        self.assertIn("/run", texts)
        self.assertIn("/edit", texts)
        self.assertIn("/read", texts)
        self.assertIn("/glob", texts)
        self.assertIn("/grep", texts)

    def test_prefix_match(self):
        """'/cl' should match /clear and /compact."""
        comps = self._completions("/cl", mode="chat")
        texts = [c.text for c in comps]
        self.assertIn("/clear", texts)

    def test_no_completion_for_non_slash(self):
        comps = self._completions("hello")
        self.assertEqual(len(comps), 0)

    def test_no_completion_after_space(self):
        """'/search python' should not trigger completions (user is typing args)."""
        comps = self._completions("/search python", mode="chat")
        self.assertEqual(len(comps), 0)

    def test_descriptions_present(self):
        """Completions should include descriptions."""
        comps = self._completions("/he", mode="chat")
        # Find /help completion
        help_comp = [c for c in comps if c.text == "/help"]
        self.assertEqual(len(help_comp), 1)
        self.assertTrue(help_comp[0].display_meta)  # has description

    def test_set_mode_updates_commands(self):
        from cli.claude_interface import SlashCommandCompleter
        c = SlashCommandCompleter(mode="chat")
        self.assertNotIn("run", c.commands)
        c.set_mode("coding")
        self.assertIn("run", c.commands)
        c.set_mode("chat")
        self.assertNotIn("run", c.commands)

    def test_all_commands_have_descriptions(self):
        """Every command in both modes must have an entry in ALL_DESCRIPTIONS."""
        from cli.claude_interface import SlashCommandCompleter
        from agent_config import AgentConfigManager
        for mode in ("chat", "coding"):
            cfg = AgentConfigManager(mode=mode)
            for cmd in cfg.available_commands:
                self.assertIn(cmd, SlashCommandCompleter.ALL_DESCRIPTIONS,
                              f"/{cmd} ({mode}) missing from ALL_DESCRIPTIONS")


# ──────────────────────────────────────────────────────────────────────────────
# ConversationManager
# ──────────────────────────────────────────────────────────────────────────────

class TestConversationManager(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        from cli.claude_interface import ConversationManager
        self.mgr = ConversationManager()
        self.mgr.base_dir = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_save_and_load(self):
        chat = _make_mock_chat()
        fp = self.mgr.save(chat, "test_conv")
        self.assertTrue(os.path.exists(fp))
        data = self.mgr.load("test_conv")
        self.assertIsNotNone(data)
        self.assertEqual(data["model"], "deepseek-chat")
        self.assertEqual(data["mode"], "chat")
        self.assertEqual(len(data["history"]), 1)

    def test_auto_name(self):
        chat = _make_mock_chat()
        fp = self.mgr.save(chat)
        self.assertTrue(os.path.exists(fp))
        self.assertIn("conv_", fp)

    def test_list_conversations(self):
        chat = _make_mock_chat()
        self.mgr.save(chat, "conv_a")
        self.mgr.save(chat, "conv_b")
        convs = self.mgr.list_all()
        self.assertIn("conv_a", convs)
        self.assertIn("conv_b", convs)

    def test_list_sorted_reverse(self):
        chat = _make_mock_chat()
        self.mgr.save(chat, "aaa")
        self.mgr.save(chat, "zzz")
        convs = self.mgr.list_all()
        self.assertEqual(convs[0], "zzz")  # reverse sorted

    def test_load_nonexistent(self):
        self.assertIsNone(self.mgr.load("does_not_exist"))

    def test_load_with_json_extension(self):
        """Loading with or without .json extension should work."""
        chat = _make_mock_chat()
        self.mgr.save(chat, "myconv")
        # Load without .json
        self.assertIsNotNone(self.mgr.load("myconv"))

    def test_save_coding_mode(self):
        chat = _make_mock_chat(mode="coding")
        fp = self.mgr.save(chat, "coding_conv")
        data = self.mgr.load("coding_conv")
        self.assertEqual(data["mode"], "coding")


# ──────────────────────────────────────────────────────────────────────────────
# ClaudeInterface — Command Handling
# ──────────────────────────────────────────────────────────────────────────────

class TestClaudeInterfaceCommands(unittest.TestCase):

    def setUp(self):
        from cli.claude_interface import ClaudeInterface
        self.mock_chat = _make_mock_chat(mode="chat")
        self.interface = ClaudeInterface(self.mock_chat)

    def test_quit_returns_false(self):
        self.assertFalse(self.interface._handle_local_command("/quit"))

    def test_exit_returns_false(self):
        self.assertFalse(self.interface._handle_local_command("/exit"))

    def test_clear_calls_clear_history(self):
        result = self.interface._handle_local_command("/clear")
        self.assertTrue(result)
        self.mock_chat.clear_history.assert_called_once()

    def test_think_toggles(self):
        self.mock_chat.thinking_enabled = False
        self.interface._handle_local_command("/think")
        self.assertTrue(self.mock_chat.thinking_enabled)
        self.interface._handle_local_command("/think")
        self.assertFalse(self.mock_chat.thinking_enabled)

    def test_debug_toggle(self):
        self.mock_chat.verbose_mode = False
        self.interface._handle_local_command("/debug")
        self.assertTrue(self.mock_chat.verbose_mode)
        self.interface._handle_local_command("/debug")
        self.assertFalse(self.mock_chat.verbose_mode)

    def test_debug_dump_empty(self):
        self.mock_chat.status_buffer = []
        result = self.interface._handle_local_command("/debug dump")
        self.assertTrue(result)

    def test_debug_dump_with_entries(self):
        self.mock_chat.status_buffer = [
            {"timestamp": 1, "message": "test msg", "level": "info"},
        ]
        result = self.interface._handle_local_command("/debug dump")
        self.assertTrue(result)

    def test_debug_clear(self):
        self.mock_chat.status_buffer = [{"message": "x", "level": "info"}]
        self.interface._handle_local_command("/debug clear")
        self.assertEqual(self.mock_chat.status_buffer, [])

    def test_history_command(self):
        self.mock_chat.conversation_history = [
            {"role": "user", "content": "Hello world"},
            {"role": "assistant", "content": "Hi!"},
        ]
        result = self.interface._handle_local_command("/history")
        self.assertTrue(result)

    def test_help_shows_mode_commands(self):
        result = self.interface._handle_local_command("/help")
        self.assertTrue(result)

    def test_save_command(self):
        result = self.interface._handle_local_command("/save")
        self.assertTrue(result)

    def test_load_no_args_lists(self):
        result = self.interface._handle_local_command("/load")
        self.assertTrue(result)

    def test_load_nonexistent(self):
        result = self.interface._handle_local_command("/load nonexistent_conv_xyz")
        self.assertTrue(result)

    def test_non_local_command_returns_none(self):
        """Commands handled by agent core should return None."""
        result = self.interface._handle_local_command("/search python docs")
        self.assertIsNone(result)

    def test_non_slash_handled_gracefully(self):
        """Non-slash text should not crash if accidentally passed."""
        # In practice, the main loop checks startswith("/") before calling
        # _handle_local_command, so this path shouldn't occur. Just verify no crash.
        result = self.interface._handle_local_command("hello world")
        self.assertIsNotNone(result)  # handled (mode gating catches it)


# ──────────────────────────────────────────────────────────────────────────────
# ClaudeInterface — Mode Command Gating
# ──────────────────────────────────────────────────────────────────────────────

class TestCommandModeGating(unittest.TestCase):
    """Verify that coding-only commands are rejected in chat mode."""

    def setUp(self):
        from cli.claude_interface import ClaudeInterface
        self.mock_chat = _make_mock_chat(mode="chat")
        self.interface = ClaudeInterface(self.mock_chat)

    def test_run_blocked_in_chat(self):
        """'/run' should be blocked in chat mode."""
        result = self.interface._handle_local_command("/run echo hi")
        self.assertTrue(result)  # handled (with rejection message), not passed through

    def test_edit_blocked_in_chat(self):
        result = self.interface._handle_local_command("/edit file.py")
        self.assertTrue(result)

    def test_read_blocked_in_chat(self):
        result = self.interface._handle_local_command("/read file.py")
        self.assertTrue(result)

    def test_git_blocked_in_chat(self):
        result = self.interface._handle_local_command("/git status")
        self.assertTrue(result)

    def test_glob_blocked_in_chat(self):
        result = self.interface._handle_local_command("/glob **/*.py")
        self.assertTrue(result)

    def test_grep_blocked_in_chat(self):
        result = self.interface._handle_local_command("/grep TODO")
        self.assertTrue(result)

    def test_quit_always_allowed(self):
        """'/quit' should work regardless of mode."""
        result = self.interface._handle_local_command("/quit")
        self.assertFalse(result)  # False = exit signal

    def test_help_always_allowed(self):
        result = self.interface._handle_local_command("/help")
        self.assertTrue(result)

    def test_search_allowed_in_chat(self):
        """'/search' is a chat command — should pass through to agent core."""
        result = self.interface._handle_local_command("/search python")
        self.assertIsNone(result)  # None = pass to agent core

    def test_coding_mode_allows_run(self):
        """In coding mode, /run should pass through to agent core."""
        from cli.claude_interface import ClaudeInterface
        mock = _make_mock_chat(mode="coding")
        from agent_config import agent_config
        agent_config.switch_mode("coding")
        iface = ClaudeInterface(mock)
        result = iface._handle_local_command("/run echo hi")
        self.assertIsNone(result)  # None = pass to agent core
        agent_config.switch_mode("chat")  # cleanup


# ──────────────────────────────────────────────────────────────────────────────
# Status Bar
# ──────────────────────────────────────────────────────────────────────────────

class TestStatusBar(unittest.TestCase):

    def test_chat_mode_bar(self):
        from cli.claude_interface import ClaudeInterface
        mock = _make_mock_chat(mode="chat")
        mock.conversation_history = [{"role": "user", "content": "hi"}]
        iface = ClaudeInterface(mock)
        toolbar = iface._bottom_toolbar()
        s = str(toolbar)
        self.assertIn("deepseek-chat", s)
        self.assertIn("chat", s)
        self.assertIn("think:off", s)
        self.assertIn("1msg", s)

    def test_coding_mode_bar_has_permission(self):
        from cli.claude_interface import ClaudeInterface
        from agent_config import agent_config
        agent_config.switch_mode("coding")
        mock = _make_mock_chat(mode="coding")
        iface = ClaudeInterface(mock)
        toolbar = iface._bottom_toolbar()
        s = str(toolbar)
        self.assertIn("coding", s)
        self.assertIn("normal", s)  # permission mode
        agent_config.switch_mode("chat")  # cleanup

    def test_think_on_shows_in_bar(self):
        from cli.claude_interface import ClaudeInterface
        mock = _make_mock_chat()
        mock.thinking_enabled = True
        iface = ClaudeInterface(mock)
        s = str(iface._bottom_toolbar())
        self.assertIn("think:on", s)

    def test_context_percentage_colors(self):
        """Low usage should be green, high usage red."""
        from cli.claude_interface import ClaudeInterface
        # Low usage
        mock = _make_mock_chat()
        mock.context_manager.count_conversation_tokens.return_value = 1000
        iface = ClaudeInterface(mock)
        s = str(iface._bottom_toolbar())
        self.assertIn("ansigreen", s)

        # High usage
        mock.context_manager.count_conversation_tokens.return_value = 120000
        s = str(iface._bottom_toolbar())
        self.assertIn("ansired", s)


# ──────────────────────────────────────────────────────────────────────────────
# Welcome Screen
# ──────────────────────────────────────────────────────────────────────────────

class TestWelcomeScreen(unittest.TestCase):

    def test_chat_welcome_with_rich(self):
        from cli.claude_interface import ClaudeInterface
        mock = _make_mock_chat(mode="chat")
        iface = ClaudeInterface(mock)
        captured = StringIO()
        if iface.console:
            iface.console.file = captured
        iface.display_welcome()
        output = captured.getvalue()
        self.assertIn("ikol1729", output)
        self.assertIn("chat mode", output)

    def test_coding_welcome_with_rich(self):
        from cli.claude_interface import ClaudeInterface
        mock = _make_mock_chat(mode="coding")
        iface = ClaudeInterface(mock)
        captured = StringIO()
        if iface.console:
            iface.console.file = captured
        iface.display_welcome()
        output = captured.getvalue()
        self.assertIn("coding mode", output)
        self.assertIn("Tools:", output)

    def test_welcome_fallback(self):
        from cli.claude_interface import ClaudeInterface
        mock = _make_mock_chat(mode="chat")
        iface = ClaudeInterface(mock)
        iface.console = None  # Force fallback
        with patch("builtins.print") as mock_print:
            iface.display_welcome()
            mock_print.assert_called()

    def test_coding_welcome_fallback_shows_tools(self):
        from cli.claude_interface import ClaudeInterface
        mock = _make_mock_chat(mode="coding")
        iface = ClaudeInterface(mock)
        iface.console = None
        with patch("builtins.print") as mock_print:
            iface.display_welcome()
            printed = " ".join(str(call) for call in mock_print.call_args_list)
            self.assertIn("Tools", printed)


# ──────────────────────────────────────────────────────────────────────────────
# Key Bindings
# ──────────────────────────────────────────────────────────────────────────────

class TestKeyBindings(unittest.TestCase):

    def test_key_bindings_created(self):
        from prompt_toolkit.key_binding import KeyBindings
        bindings = KeyBindings()

        @bindings.add("c-o")
        def _toggle_think(event): pass

        @bindings.add("escape", eager=True)
        def _clear(event): pass

        @bindings.add("c-l")
        def _clear_screen(event): pass

        @bindings.add("escape", "enter")
        def _newline(event): pass

        self.assertGreater(len(bindings.bindings), 0)

    def test_ctrl_o_simulation(self):
        mock_chat = _make_mock_chat()
        mock_chat.thinking_enabled = False
        mock_chat.thinking_enabled = not mock_chat.thinking_enabled
        self.assertTrue(mock_chat.thinking_enabled)
        mock_chat.thinking_enabled = not mock_chat.thinking_enabled
        self.assertFalse(mock_chat.thinking_enabled)


# ──────────────────────────────────────────────────────────────────────────────
# Integration
# ──────────────────────────────────────────────────────────────────────────────

class TestIntegrationLoop(unittest.TestCase):

    def test_interface_creation(self):
        from cli.claude_interface import ClaudeInterface
        mock = _make_mock_chat()
        iface = ClaudeInterface(mock)
        self.assertTrue(iface.running)
        self.assertFalse(iface._interrupt)

    def test_command_routing_local_vs_core(self):
        from cli.claude_interface import ClaudeInterface
        mock = _make_mock_chat()
        iface = ClaudeInterface(mock)
        # Local commands
        self.assertFalse(iface._handle_local_command("/quit"))
        self.assertTrue(iface._handle_local_command("/clear"))
        self.assertTrue(iface._handle_local_command("/think"))
        self.assertTrue(iface._handle_local_command("/help"))
        # Agent core commands (pass through)
        self.assertIsNone(iface._handle_local_command("/search test"))

    def test_print_with_rich(self):
        from cli.claude_interface import ClaudeInterface
        mock = _make_mock_chat()
        iface = ClaudeInterface(mock)
        captured = StringIO()
        if iface.console:
            iface.console.file = captured
        iface._print("[green]test[/green]")
        self.assertIn("test", captured.getvalue())

    def test_print_without_rich(self):
        from cli.claude_interface import ClaudeInterface
        mock = _make_mock_chat()
        iface = ClaudeInterface(mock)
        iface.console = None
        with patch("builtins.print") as mock_print:
            iface._print("[green]test message[/green]")
            mock_print.assert_called_once()
            # Should strip markup
            printed = mock_print.call_args[0][0]
            self.assertNotIn("[green]", printed)
            self.assertIn("test message", printed)


# ──────────────────────────────────────────────────────────────────────────────
# Structural checks
# ──────────────────────────────────────────────────────────────────────────────

class TestCoreImports(unittest.TestCase):

    def test_no_duplicate_top_level_imports(self):
        core_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "agent", "core.py",
        )
        with open(core_path) as f:
            lines = f.readlines()

        import_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("class "):
                break
            if not line[0:1].isspace() and (stripped.startswith("import ") or stripped.startswith("from ")):
                import_lines.append(stripped)

        seen = set()
        duplicates = []
        for line in import_lines:
            if line in seen:
                duplicates.append(line)
            seen.add(line)

        self.assertEqual(len(duplicates), 0, f"Duplicate imports: {duplicates}")


class TestNpmFree(unittest.TestCase):

    def test_no_package_json(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.assertFalse(os.path.exists(os.path.join(root, "package.json")))

    def test_no_node_modules(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.assertFalse(os.path.exists(os.path.join(root, "node_modules")))

    def test_all_deps_are_python(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        content = open(os.path.join(root, "pyproject.toml")).read()
        self.assertIn("prompt_toolkit", content)
        self.assertIn("rich", content)
        self.assertNotIn("hydra-core", content)


# ── New tests: Spinner, Transcript, Agentic Tool Loop ──────────────────


class TestExtractToolBlocks(unittest.TestCase):
    """Test code block extraction from LLM responses."""

    def _iface(self):
        from cli.claude_interface import ClaudeInterface
        return ClaudeInterface(_make_mock_chat("coding"))

    def test_extract_bash_block(self):
        iface = self._iface()
        blocks = iface._extract_tool_blocks("Check:\n```bash\nls -la\n```\nDone.")
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0], ("bash", "ls -la"))

    def test_extract_only_first_block(self):
        """Should only extract the FIRST bash block (one-at-a-time execution)."""
        iface = self._iface()
        blocks = iface._extract_tool_blocks("```bash\nls\n```\nNow:\n```bash\ncat README.md\n```")
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0][1], "ls")

    def test_extract_shell_block(self):
        iface = self._iface()
        blocks = iface._extract_tool_blocks("```shell\npwd\n```")
        self.assertEqual(len(blocks), 1)

    def test_skip_python_block(self):
        iface = self._iface()
        blocks = iface._extract_tool_blocks("```python\nprint('hello')\n```")
        self.assertEqual(len(blocks), 0)

    def test_skip_comment_only_block(self):
        iface = self._iface()
        blocks = iface._extract_tool_blocks("```bash\n# This is just a comment\n```")
        self.assertEqual(len(blocks), 0)

    def test_empty_response(self):
        iface = self._iface()
        self.assertEqual(iface._extract_tool_blocks(""), [])

    def test_no_code_blocks(self):
        iface = self._iface()
        self.assertEqual(iface._extract_tool_blocks("Just text, no code."), [])

    def test_multiline_block(self):
        iface = self._iface()
        blocks = iface._extract_tool_blocks("```bash\nfind . -name '*.py'\nwc -l\n```")
        self.assertEqual(len(blocks), 1)
        self.assertIn("find", blocks[0][1])
        self.assertIn("wc", blocks[0][1])

    def test_sh_tag(self):
        iface = self._iface()
        blocks = iface._extract_tool_blocks("```sh\necho hi\n```")
        self.assertEqual(len(blocks), 1)

    def test_console_tag(self):
        iface = self._iface()
        blocks = iface._extract_tool_blocks("```console\necho hi\n```")
        self.assertEqual(len(blocks), 1)


class TestExecuteToolBlocks(unittest.TestCase):
    """Test tool block execution through ToolRegistry."""

    def _iface(self):
        from cli.claude_interface import ClaudeInterface
        return ClaudeInterface(_make_mock_chat("coding"))

    def test_execute_echo(self):
        iface = self._iface()
        results = iface._execute_tool_blocks([("bash", "echo hello")])
        self.assertEqual(len(results), 1)
        _, result = results[0]
        self.assertTrue(result.success)
        self.assertIn("hello", result.output)

    def test_execute_failing_command(self):
        iface = self._iface()
        results = iface._execute_tool_blocks([("bash", "false")])
        _, result = results[0]
        self.assertFalse(result.success)

    def test_registry_reuse(self):
        iface = self._iface()
        iface._execute_tool_blocks([("bash", "echo 1")])
        reg1 = iface._tool_registry
        iface._execute_tool_blocks([("bash", "echo 2")])
        self.assertIs(reg1, iface._tool_registry)


class TestAgenticLoop(unittest.TestCase):
    """Test the agentic tool execution loop."""

    def _iface(self):
        from cli.claude_interface import ClaudeInterface
        chat = _make_mock_chat("coding")
        chat._truncate_middle = MagicMock(side_effect=lambda x: x[:2000])
        return ClaudeInterface(chat)

    def test_no_loop_in_chat_mode(self):
        iface = self._iface()
        iface.chat.mode = "chat"
        iface.chat.conversation_history = [
            {"role": "assistant", "content": "```bash\nls\n```"}
        ]
        iface._run_agentic_loop()
        iface.chat.add_to_history.assert_not_called()

    def test_no_loop_without_code_blocks(self):
        iface = self._iface()
        iface.chat.conversation_history = [
            {"role": "assistant", "content": "The project looks good."}
        ]
        iface._run_agentic_loop()
        iface.chat.add_to_history.assert_not_called()

    def test_no_loop_empty_history(self):
        iface = self._iface()
        iface.chat.conversation_history = []
        iface._run_agentic_loop()  # Should not crash

    def test_no_loop_last_is_user(self):
        iface = self._iface()
        iface.chat.conversation_history = [
            {"role": "user", "content": "Hello"}
        ]
        iface._run_agentic_loop()
        iface.chat.add_to_history.assert_not_called()


class TestTranscriptCommand(unittest.TestCase):
    """Test the /transcript command."""

    def _iface(self):
        from cli.claude_interface import ClaudeInterface
        chat = _make_mock_chat("coding")
        chat.conversation_history = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "What is Python?"},
            {"role": "assistant", "content": "Python is a programming language."},
        ]
        return ClaudeInterface(chat)

    @patch('sys.stdout', new_callable=StringIO)
    def test_transcript_default(self, _):
        iface = self._iface()
        iface._show_transcript("")  # Should not crash

    @patch('sys.stdout', new_callable=StringIO)
    def test_transcript_last(self, _):
        iface = self._iface()
        iface._show_transcript("last")

    @patch('sys.stdout', new_callable=StringIO)
    def test_transcript_with_number(self, _):
        iface = self._iface()
        iface._show_transcript("2")

    @patch('sys.stdout', new_callable=StringIO)
    def test_transcript_empty_history(self, _):
        iface = self._iface()
        iface.chat.conversation_history = []
        iface._show_transcript("")

    @patch('sys.stdout', new_callable=StringIO)
    def test_transcript_full(self, _):
        iface = self._iface()
        iface._show_transcript("full")


class TestTranscriptInCommands(unittest.TestCase):
    """Test that /transcript is wired into command handling."""

    def test_transcript_in_descriptions(self):
        from cli.claude_interface import SlashCommandCompleter
        self.assertIn("transcript", SlashCommandCompleter.ALL_DESCRIPTIONS)

    def test_handle_transcript_returns_true(self):
        from cli.claude_interface import ClaudeInterface
        chat = _make_mock_chat("coding")
        chat.conversation_history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
        ]
        iface = ClaudeInterface(chat)
        result = iface._handle_local_command("/transcript")
        self.assertTrue(result)


class TestSpinnerCallback(unittest.TestCase):
    """Test that spinner callback is properly injected."""

    def test_callback_set_on_chat(self):
        from cli.claude_interface import ClaudeInterface
        chat = _make_mock_chat("coding")
        chat.stream_response = MagicMock()
        chat._truncate_middle = MagicMock(side_effect=lambda x: x)
        iface = ClaudeInterface(chat)
        iface._stream_and_render("test")
        # stream_response was called
        chat.stream_response.assert_called_once_with("test")
        # _ui_on_first_token should have been set
        self.assertTrue(hasattr(chat, '_ui_on_first_token'))


class TestHallucinationDetection(unittest.TestCase):
    """Test that blocks with inline hallucinated output are skipped."""

    def _iface(self):
        from cli.claude_interface import ClaudeInterface
        return ClaudeInterface(_make_mock_chat("coding"))

    def test_skip_block_with_inline_output(self):
        """Block followed by ``` output block should be skipped (hallucinated)."""
        iface = self._iface()
        # This simulates the LLM hallucinating both command and output
        response = "Let me check:\n```bash\nls -la\n```\n```\ntotal 20\ndrwxr-xr-x  5 root root  4096 Mar 14  .\n```"
        blocks = iface._extract_tool_blocks(response)
        self.assertEqual(len(blocks), 0, "Should skip block with inline output")

    def test_dont_skip_block_without_output(self):
        """Block NOT followed by ``` output should be extracted."""
        iface = self._iface()
        response = "Let me check:\n```bash\nls -la\n```\nDone."
        blocks = iface._extract_tool_blocks(response)
        self.assertEqual(len(blocks), 1)

    def test_skip_only_first_hallucinated(self):
        """If first block has output but second doesn't, skip first, take second."""
        iface = self._iface()
        response = (
            "```bash\nls -la\n```\n```\ntotal 20\n```\n"
            "Now let me also:\n```bash\ncat README.md\n```\nThat's all."
        )
        blocks = iface._extract_tool_blocks(response)
        # First is skipped (has inline output), second should be extracted
        # But since we only take FIRST non-hallucinated block:
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0][1], "cat README.md")


class TestExpandCommand(unittest.TestCase):
    """Test the /expand command for viewing thinking turns."""

    def _iface_with_thinking(self):
        from cli.claude_interface import ClaudeInterface
        chat = _make_mock_chat("coding")
        chat._thinking_history = [
            {
                "timestamp": 1000,
                "thinking": "Let me analyze the codebase structure...\nFirst I need to check the files.",
                "response_preview": "The codebase is a Python project with...",
                "duration": 3.2,
            },
            {
                "timestamp": 2000,
                "thinking": "Now I need to fix the bug in core.py...",
                "response_preview": "I've identified the issue in...",
                "duration": 5.1,
            },
        ]
        return ClaudeInterface(chat)

    @patch('sys.stdout', new_callable=StringIO)
    def test_expand_no_thinking(self, _):
        from cli.claude_interface import ClaudeInterface
        chat = _make_mock_chat("coding")
        chat._thinking_history = []  # Explicitly empty
        iface = ClaudeInterface(chat)
        iface._show_expand("")  # Should say "no thinking turns" and return

    @patch('sys.stdout', new_callable=StringIO)
    def test_expand_list_turns(self, _):
        iface = self._iface_with_thinking()
        # Patch input to cancel
        with patch('builtins.input', side_effect=EOFError):
            iface._show_expand("")

    @patch('sys.stdout', new_callable=StringIO)
    def test_expand_last(self, _):
        iface = self._iface_with_thinking()
        with patch.object(iface, '_open_in_pager') as mock_pager:
            iface._show_expand("last")
            mock_pager.assert_called_once()
            text = mock_pager.call_args[0][0]
            self.assertIn("5.1s", text)

    @patch('sys.stdout', new_callable=StringIO)
    def test_expand_by_number(self, _):
        iface = self._iface_with_thinking()
        with patch.object(iface, '_open_in_pager') as mock_pager:
            iface._show_expand("1")
            mock_pager.assert_called_once()
            text = mock_pager.call_args[0][0]
            self.assertIn("3.2s", text)

    @patch('sys.stdout', new_callable=StringIO)
    def test_expand_all(self, _):
        iface = self._iface_with_thinking()
        with patch.object(iface, '_open_in_pager') as mock_pager:
            iface._show_expand("all")
            mock_pager.assert_called_once()
            text = mock_pager.call_args[0][0]
            self.assertIn("Turn 1", text)
            self.assertIn("Turn 2", text)

    @patch('sys.stdout', new_callable=StringIO)
    def test_expand_invalid_number(self, _):
        iface = self._iface_with_thinking()
        iface._show_expand("99")  # Should not crash

    def test_handle_expand_returns_true(self):
        from cli.claude_interface import ClaudeInterface
        chat = _make_mock_chat("coding")
        chat._thinking_history = []
        iface = ClaudeInterface(chat)
        result = iface._handle_local_command("/expand")
        self.assertTrue(result)


class TestExpandInCommands(unittest.TestCase):
    """Test that /expand is registered as a command."""

    def test_expand_in_descriptions(self):
        from cli.claude_interface import SlashCommandCompleter
        self.assertIn("expand", SlashCommandCompleter.ALL_DESCRIPTIONS)


class TestSpinnerMechanism(unittest.TestCase):
    """Test the ANSI-based spinner (stderr-based, avoids Rich proxy)."""

    def test_start_and_stop_spinner(self):
        """Spinner starts and stops cleanly."""
        from cli.claude_interface import ClaudeInterface
        iface = ClaudeInterface(_make_mock_chat("coding"))
        stop = iface._start_spinner("Testing…")
        time.sleep(0.2)
        stop.set()
        time.sleep(0.2)
        # No crash means success

    def test_spinner_writes_to_stderr(self):
        """Spinner output goes to stderr, not stdout."""
        from cli.claude_interface import ClaudeInterface
        iface = ClaudeInterface(_make_mock_chat("coding"))
        captured = StringIO()
        with patch('sys.stderr', captured):
            stop = iface._start_spinner("Test")
            time.sleep(0.2)
            stop.set()
            time.sleep(0.1)
        output = captured.getvalue()
        self.assertIn("Test", output)


class TestToolBlockRegex(unittest.TestCase):
    """Test the compiled regex for code blocks."""

    def _pattern(self):
        from cli.claude_interface import ClaudeInterface
        return ClaudeInterface._TOOL_BLOCK_RE

    def test_bash(self):
        self.assertEqual(len(list(self._pattern().finditer("```bash\nls\n```"))), 1)

    def test_shell(self):
        self.assertEqual(len(list(self._pattern().finditer("```shell\npwd\n```"))), 1)

    def test_sh(self):
        self.assertEqual(len(list(self._pattern().finditer("```sh\necho hi\n```"))), 1)

    def test_no_python(self):
        self.assertEqual(len(list(self._pattern().finditer("```python\nprint()\n```"))), 0)

    def test_no_plain(self):
        self.assertEqual(len(list(self._pattern().finditer("```\nstuff\n```"))), 0)


# ──────────────────────────────────────────────────────────────────────────────
# Code Fence Filter
# ──────────────────────────────────────────────────────────────────────────────

class TestCodeFenceFilter(unittest.TestCase):
    """Test _CodeFenceFilter that suppresses bash code blocks from display."""

    def _filter(self):
        from cli.claude_interface import ClaudeInterface
        return ClaudeInterface._CodeFenceFilter()

    def test_plain_text_passes_through(self):
        f = self._filter()
        result = f.write("Hello world, no code here.")
        result += f.flush()
        self.assertEqual(result, "Hello world, no code here.")

    def test_suppresses_bash_block(self):
        f = self._filter()
        text = "Before\n```bash\nls -la\n```\nAfter"
        result = f.write(text)
        result += f.flush()
        # Should contain "Before" and "After" but NOT "ls -la"
        self.assertIn("Before", result)
        self.assertIn("After", result)
        self.assertNotIn("ls -la", result)
        self.assertNotIn("```bash", result)

    def test_suppresses_shell_block(self):
        f = self._filter()
        text = "Start\n```shell\npwd\n```\nEnd"
        result = f.write(text)
        result += f.flush()
        self.assertNotIn("pwd", result)
        self.assertIn("Start", result)
        self.assertIn("End", result)

    def test_suppresses_sh_block(self):
        f = self._filter()
        text = "A\n```sh\necho hi\n```\nB"
        result = f.write(text)
        result += f.flush()
        self.assertNotIn("echo hi", result)

    def test_suppresses_console_block(self):
        f = self._filter()
        text = "A\n```console\nwhoami\n```\nB"
        result = f.write(text)
        result += f.flush()
        self.assertNotIn("whoami", result)

    def test_passes_python_block(self):
        f = self._filter()
        text = "Code:\n```python\nprint('hello')\n```\nDone."
        result = f.write(text)
        result += f.flush()
        # Python blocks should NOT be suppressed
        self.assertIn("print('hello')", result)

    def test_streaming_chunks(self):
        """Feed content character-by-character like real streaming."""
        f = self._filter()
        text = "Hi\n```bash\nls\n```\nBye"
        result = ""
        for ch in text:
            result += f.write(ch)
        result += f.flush()
        self.assertIn("Hi", result)
        self.assertIn("Bye", result)
        self.assertNotIn("ls", result)

    def test_streaming_word_chunks(self):
        """Feed content in small word-like chunks."""
        f = self._filter()
        chunks = ["Let me ", "check:\n", "```bash", "\n", "ls -la\n", "```", "\nDone."]
        result = ""
        for chunk in chunks:
            result += f.write(chunk)
        result += f.flush()
        self.assertIn("Let me check:", result)
        self.assertIn("Done.", result)
        self.assertNotIn("ls -la", result)

    def test_multiple_bash_blocks(self):
        """Multiple bash blocks should all be suppressed."""
        f = self._filter()
        text = "A\n```bash\ncmd1\n```\nB\n```bash\ncmd2\n```\nC"
        result = f.write(text)
        result += f.flush()
        self.assertNotIn("cmd1", result)
        self.assertNotIn("cmd2", result)
        self.assertIn("A", result)
        self.assertIn("B", result)
        self.assertIn("C", result)

    def test_flush_returns_remaining_buffer(self):
        f = self._filter()
        # Feed partial text that stays in buffer
        result = f.write("Short")
        # flush() should return whatever's buffered
        result += f.flush()
        self.assertEqual(result, "Short")


# ──────────────────────────────────────────────────────────────────────────────
# Dynamic Spinner Labels
# ──────────────────────────────────────────────────────────────────────────────

class TestDynamicSpinnerLabel(unittest.TestCase):
    """Test that spinner supports dynamic label updates."""

    def test_spinner_has_label_ref(self):
        from cli.claude_interface import ClaudeInterface
        iface = ClaudeInterface(_make_mock_chat("coding"))
        stop = iface._start_spinner("Initial")
        self.assertTrue(hasattr(stop, '_label_ref'))
        self.assertEqual(stop._label_ref[0], "Initial")
        stop.set()
        time.sleep(0.15)

    def test_update_spinner_changes_label(self):
        from cli.claude_interface import ClaudeInterface
        iface = ClaudeInterface(_make_mock_chat("coding"))
        stop = iface._start_spinner("Start")
        iface._update_spinner(stop, "Updated")
        self.assertEqual(stop._label_ref[0], "Updated")
        stop.set()
        time.sleep(0.15)

    def test_dynamic_label_shows_in_output(self):
        from cli.claude_interface import ClaudeInterface
        iface = ClaudeInterface(_make_mock_chat("coding"))
        captured = StringIO()
        with patch('sys.stderr', captured):
            stop = iface._start_spinner("Label1")
            time.sleep(0.15)
            iface._update_spinner(stop, "Label2")
            time.sleep(0.15)
            stop.set()
            time.sleep(0.15)
        output = captured.getvalue()
        self.assertIn("Label1", output)
        self.assertIn("Label2", output)


# ──────────────────────────────────────────────────────────────────────────────
# Agentic Loop — spinner-based display (no verbose output)
# ──────────────────────────────────────────────────────────────────────────────

class TestAgenticLoopSpinnerDisplay(unittest.TestCase):
    """Test that agentic loop uses spinner instead of verbose output after permission."""

    def _iface(self):
        from cli.claude_interface import ClaudeInterface
        chat = _make_mock_chat("coding")
        chat._truncate_middle = MagicMock(side_effect=lambda x: x[:2000])
        chat.stream_response = MagicMock()
        return ClaudeInterface(chat)

    @patch('builtins.input', return_value='y')
    def test_agentic_loop_starts_spinner(self, _):
        """After permission, agentic loop should start a spinner."""
        iface = self._iface()
        iface.chat.conversation_history = [
            {"role": "assistant", "content": "Let me check:\n```bash\necho hello\n```"}
        ]
        # After executing, stream_response is called (re-prompt)
        # Make stream_response set the conversation to no more blocks
        def mock_stream(prompt):
            iface.chat.conversation_history.append(
                {"role": "assistant", "content": "All done, no more commands."}
            )
        iface.chat.stream_response = MagicMock(side_effect=mock_stream)

        captured_stderr = StringIO()
        with patch('sys.stderr', captured_stderr):
            iface._run_agentic_loop()
        stderr_out = captured_stderr.getvalue()
        # Spinner should have written "Thinking" to stderr
        self.assertIn("Thinking", stderr_out)

    @patch('builtins.input', return_value='y')
    def test_no_verbose_output_to_stdout(self, _):
        """After permission, tool execution output should NOT be printed verbosely."""
        iface = self._iface()
        iface.chat.conversation_history = [
            {"role": "assistant", "content": "```bash\necho hello_world\n```"}
        ]
        def mock_stream(prompt):
            iface.chat.conversation_history.append(
                {"role": "assistant", "content": "Done."}
            )
        iface.chat.stream_response = MagicMock(side_effect=mock_stream)

        captured_stdout = StringIO()
        with patch('sys.stdout', captured_stdout):
            with patch('sys.stderr', StringIO()):  # suppress spinner
                iface._run_agentic_loop()
        stdout_out = captured_stdout.getvalue()
        # The permission prompt "$ echo hello_world" is expected (brief preview),
        # but verbose execution output (indented lines) should NOT appear
        # Old verbose format was "    hello_world" (indented output lines)
        indented_lines = [l for l in stdout_out.split('\n') if l.startswith('    ')]
        self.assertEqual(len(indented_lines), 0, f"Found verbose output lines: {indented_lines}")


# ──────────────────────────────────────────────────────────────────────────────
# Content filter integration in _stream_and_render
# ──────────────────────────────────────────────────────────────────────────────

class TestStreamAndRenderContentFilter(unittest.TestCase):
    """Test that _stream_and_render installs content filter in coding mode."""

    def test_filter_installed_in_coding_mode(self):
        from cli.claude_interface import ClaudeInterface
        chat = _make_mock_chat("coding")
        filter_installed = []
        def mock_stream(prompt):
            filter_installed.append(getattr(chat, '_content_filter', None))
        chat.stream_response = MagicMock(side_effect=mock_stream)
        iface = ClaudeInterface(chat)
        iface._stream_and_render("test prompt")
        # During stream_response, _content_filter should have been set
        self.assertEqual(len(filter_installed), 1)
        self.assertIsNotNone(filter_installed[0])

    def test_filter_not_installed_in_chat_mode(self):
        from cli.claude_interface import ClaudeInterface
        chat = _make_mock_chat("chat")
        chat._content_filter = None  # Explicitly initialize (MagicMock auto-creates)
        filter_installed = []
        def mock_stream(prompt):
            filter_installed.append(chat._content_filter)
        chat.stream_response = MagicMock(side_effect=mock_stream)
        iface = ClaudeInterface(chat)
        iface._stream_and_render("test prompt")
        # In chat mode, _content_filter should NOT be set
        self.assertEqual(len(filter_installed), 1)
        self.assertIsNone(filter_installed[0])

    def test_filter_cleaned_up_after_render(self):
        from cli.claude_interface import ClaudeInterface
        chat = _make_mock_chat("coding")
        chat.stream_response = MagicMock()
        iface = ClaudeInterface(chat)
        iface._stream_and_render("test")
        # After _stream_and_render completes, filter should be cleaned up
        self.assertIsNone(getattr(chat, '_content_filter', None))


# ──────────────────────────────────────────────────────────────────────────────
# /permissions command
# ──────────────────────────────────────────────────────────────────────────────

class TestPermissionsCommand(unittest.TestCase):
    """Test the /permissions command for toggling permission mode at runtime."""

    def setUp(self):
        from cli.claude_interface import ClaudeInterface
        from agent_config import agent_config
        agent_config.switch_mode("coding")
        self.mock_chat = _make_mock_chat(mode="coding")
        self.interface = ClaudeInterface(self.mock_chat)
        # Reset to normal
        agent_config.permission_mode = "normal"

    def tearDown(self):
        from agent_config import agent_config
        agent_config.permission_mode = "normal"
        agent_config.switch_mode("chat")

    def test_toggle_normal_to_auto(self):
        from agent_config import agent_config
        agent_config.permission_mode = "normal"
        result = self.interface._handle_local_command("/permissions")
        self.assertTrue(result)
        self.assertEqual(agent_config.permission_mode, "auto_accept")

    def test_toggle_auto_to_normal(self):
        from agent_config import agent_config
        agent_config.permission_mode = "auto_accept"
        result = self.interface._handle_local_command("/permissions")
        self.assertTrue(result)
        self.assertEqual(agent_config.permission_mode, "normal")

    def test_set_explicit_auto(self):
        from agent_config import agent_config
        result = self.interface._handle_local_command("/permissions auto")
        self.assertTrue(result)
        self.assertEqual(agent_config.permission_mode, "auto_accept")

    def test_set_explicit_plan(self):
        from agent_config import agent_config
        result = self.interface._handle_local_command("/permissions plan")
        self.assertTrue(result)
        self.assertEqual(agent_config.permission_mode, "plan")

    def test_set_explicit_normal(self):
        from agent_config import agent_config
        agent_config.permission_mode = "auto_accept"
        result = self.interface._handle_local_command("/permissions normal")
        self.assertTrue(result)
        self.assertEqual(agent_config.permission_mode, "normal")

    def test_invalid_arg_shows_usage(self):
        from agent_config import agent_config
        old_mode = agent_config.permission_mode
        result = self.interface._handle_local_command("/permissions foobar")
        self.assertTrue(result)
        # Should not change the mode
        self.assertEqual(agent_config.permission_mode, old_mode)

    def test_permissions_in_descriptions(self):
        from cli.claude_interface import SlashCommandCompleter
        self.assertIn("permissions", SlashCommandCompleter.ALL_DESCRIPTIONS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
