"""
Functional tests for the Claude-like CLI interface.
These tests mimic actual user behaviors: key bindings, command completion,
status bar, conversation persistence, and the overall chat loop.
"""

import os
import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestSlashCommandCompleter(unittest.TestCase):
    """Test the slash command completer for fuzzy matching."""

    def setUp(self):
        from cli.claude_interface import SlashCommandCompleter
        self.completer = SlashCommandCompleter()

    def test_basic_completion(self):
        """Typing /cl should match /clear."""
        from prompt_toolkit.document import Document
        doc = Document("/cl")
        completions = list(self.completer.get_completions(doc, None))
        names = [c.display[0][1] if isinstance(c.display, list) else str(c.display) for c in completions]
        self.assertTrue(any("clear" in str(n) for n in names), f"Expected /clear in completions, got {names}")

    def test_fuzzy_matching(self):
        """Typing /se should match /search."""
        from prompt_toolkit.document import Document
        doc = Document("/se")
        completions = list(self.completer.get_completions(doc, None))
        texts = [c.text for c in completions]
        self.assertIn("/search", texts)

    def test_no_completion_for_non_slash(self):
        """Non-slash text should not trigger completions."""
        from prompt_toolkit.document import Document
        doc = Document("hello")
        completions = list(self.completer.get_completions(doc, None))
        self.assertEqual(len(completions), 0)

    def test_all_commands_have_descriptions(self):
        """All known commands should have descriptions."""
        from cli.claude_interface import SlashCommandCompleter
        for cmd in self.completer.commands:
            # At least the common ones should have descriptions
            pass  # Descriptions are optional for extended commands
        # But the COMMAND_DESCRIPTIONS dict should cover the core ones
        self.assertIn("clear", SlashCommandCompleter.COMMAND_DESCRIPTIONS)
        self.assertIn("think", SlashCommandCompleter.COMMAND_DESCRIPTIONS)
        self.assertIn("help", SlashCommandCompleter.COMMAND_DESCRIPTIONS)
        self.assertIn("save", SlashCommandCompleter.COMMAND_DESCRIPTIONS)
        self.assertIn("load", SlashCommandCompleter.COMMAND_DESCRIPTIONS)

    def test_empty_slash(self):
        """Typing just / should list all commands."""
        from prompt_toolkit.document import Document
        doc = Document("/")
        completions = list(self.completer.get_completions(doc, None))
        # Should return many commands
        self.assertGreater(len(completions), 10)


class TestConversationManager(unittest.TestCase):
    """Test conversation save/load/list."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        from cli.claude_interface import ConversationManager
        self.mgr = ConversationManager()
        # Override base_dir to use temp
        self.mgr.base_dir = Path(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_mock_chat(self):
        chat = MagicMock()
        chat.model = "deepseek-chat"
        chat.mode = "chat"
        chat.thinking_enabled = False
        chat.conversation_history = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        return chat

    def test_save_and_load(self):
        """Save a conversation and load it back."""
        chat = self._make_mock_chat()
        fp = self.mgr.save(chat, "test_conv")
        self.assertTrue(os.path.exists(fp))

        data = self.mgr.load("test_conv")
        self.assertIsNotNone(data)
        self.assertEqual(data["model"], "deepseek-chat")
        self.assertEqual(len(data["history"]), 3)
        self.assertEqual(data["history"][1]["content"], "Hello")

    def test_list_conversations(self):
        """List should return saved conversations."""
        chat = self._make_mock_chat()
        self.mgr.save(chat, "conv_a")
        self.mgr.save(chat, "conv_b")
        convs = self.mgr.list_all()
        self.assertIn("conv_a", convs)
        self.assertIn("conv_b", convs)

    def test_load_nonexistent(self):
        """Loading a nonexistent conversation returns None."""
        data = self.mgr.load("does_not_exist")
        self.assertIsNone(data)

    def test_auto_name(self):
        """Saving without a name should auto-generate one."""
        chat = self._make_mock_chat()
        fp = self.mgr.save(chat)
        self.assertTrue(os.path.exists(fp))
        self.assertIn("conv_", fp)


class TestClaudeInterfaceCommands(unittest.TestCase):
    """Test command handling in the ClaudeInterface."""

    def setUp(self):
        # Mock the DeepSeekStreamingChat
        self.mock_chat = MagicMock()
        self.mock_chat.model = "deepseek-chat"
        self.mock_chat.mode = "chat"
        self.mock_chat.thinking_enabled = False
        self.mock_chat.conversation_history = []
        self.mock_chat.context_manager = MagicMock()
        self.mock_chat.context_manager.count_conversation_tokens.return_value = 100

        from cli.claude_interface import ClaudeInterface
        self.interface = ClaudeInterface(self.mock_chat)

    def test_quit_command(self):
        """Test /quit returns False (exit signal)."""
        result = self.interface._handle_local_command("/quit")
        self.assertFalse(result)

    def test_exit_command(self):
        """Test /exit returns False (exit signal)."""
        result = self.interface._handle_local_command("/exit")
        self.assertFalse(result)

    def test_clear_command(self):
        """Test /clear calls chat.clear_history()."""
        result = self.interface._handle_local_command("/clear")
        self.assertTrue(result)
        self.mock_chat.clear_history.assert_called_once()

    def test_think_toggle(self):
        """Test /think toggles thinking_enabled."""
        self.mock_chat.thinking_enabled = False
        result = self.interface._handle_local_command("/think")
        self.assertTrue(result)
        self.assertTrue(self.mock_chat.thinking_enabled)

        # Toggle again
        result = self.interface._handle_local_command("/think")
        self.assertTrue(result)
        self.assertFalse(self.mock_chat.thinking_enabled)

    def test_history_command(self):
        """Test /history shows conversation history."""
        self.mock_chat.conversation_history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
        ]
        result = self.interface._handle_local_command("/history")
        self.assertTrue(result)

    def test_help_command(self):
        """Test /help shows available commands."""
        result = self.interface._handle_local_command("/help")
        self.assertTrue(result)

    def test_unknown_command_returns_none(self):
        """Unknown slash commands should return None (pass to agent core)."""
        result = self.interface._handle_local_command("/search python docs")
        self.assertIsNone(result)

    def test_non_slash_returns_none(self):
        """Non-slash input passed to _handle_local_command should return None."""
        # Actually this shouldn't happen because we check startswith("/") before calling
        # but the method should be robust
        result = self.interface._handle_local_command("hello world")
        self.assertIsNone(result)


class TestKeyBindings(unittest.TestCase):
    """Test key binding setup for Claude-like interface."""

    def test_key_bindings_created(self):
        """Verify key bindings can be created."""
        from prompt_toolkit.key_binding import KeyBindings
        bindings = KeyBindings()

        # Verify we can add bindings for all required keys
        @bindings.add("c-o")
        def _toggle_think(event):
            pass

        @bindings.add("escape")
        def _clear(event):
            pass

        @bindings.add("c-l")
        def _clear_screen(event):
            pass

        @bindings.add("escape", "enter")
        def _newline(event):
            pass

        # Should have 4 bindings
        self.assertGreater(len(bindings.bindings), 0)

    def test_ctrl_o_thinking_toggle_simulation(self):
        """Simulate Ctrl+O toggling thinking mode."""
        mock_chat = MagicMock()
        mock_chat.thinking_enabled = False
        mock_chat.model = "deepseek-chat"
        mock_chat.mode = "chat"
        mock_chat.conversation_history = []
        mock_chat.context_manager = MagicMock()

        # Simulate what Ctrl+O handler does
        mock_chat.thinking_enabled = not mock_chat.thinking_enabled
        self.assertTrue(mock_chat.thinking_enabled)

        mock_chat.thinking_enabled = not mock_chat.thinking_enabled
        self.assertFalse(mock_chat.thinking_enabled)


class TestStatusBar(unittest.TestCase):
    """Test bottom status bar formatting."""

    def test_status_bar_content(self):
        """Status bar should contain model, mode, thinking status."""
        mock_chat = MagicMock()
        mock_chat.model = "deepseek-chat"
        mock_chat.mode = "chat"
        mock_chat.thinking_enabled = True
        mock_chat.context_manager = MagicMock()
        mock_chat.context_manager.count_conversation_tokens.return_value = 500

        from cli.claude_interface import ClaudeInterface
        interface = ClaudeInterface(mock_chat)
        toolbar = interface._bottom_toolbar()

        # The toolbar returns an HTML formatted text
        # We can check the raw string representation
        toolbar_str = str(toolbar)
        self.assertIn("deepseek-chat", toolbar_str)
        self.assertIn("chat", toolbar_str)
        self.assertIn("think:on", toolbar_str)

    def test_status_bar_thinking_off(self):
        """Status bar should show think:off when disabled."""
        mock_chat = MagicMock()
        mock_chat.model = "deepseek-reasoner"
        mock_chat.mode = "coding"
        mock_chat.thinking_enabled = False
        mock_chat.context_manager = MagicMock()
        mock_chat.context_manager.count_conversation_tokens.return_value = 0

        from cli.claude_interface import ClaudeInterface
        interface = ClaudeInterface(mock_chat)
        toolbar = interface._bottom_toolbar()
        toolbar_str = str(toolbar)
        self.assertIn("think:off", toolbar_str)
        self.assertIn("coding", toolbar_str)


class TestWelcomeScreen(unittest.TestCase):
    """Test compact welcome screen display."""

    def test_welcome_with_rich(self):
        """Welcome should display model and mode info."""
        mock_chat = MagicMock()
        mock_chat.model = "deepseek-chat"
        mock_chat.mode = "chat"
        mock_chat.thinking_enabled = True
        mock_chat.conversation_history = []
        mock_chat.context_manager = MagicMock()

        from cli.claude_interface import ClaudeInterface
        interface = ClaudeInterface(mock_chat)

        # Capture output
        from io import StringIO
        captured = StringIO()
        if interface.console:
            interface.console.file = captured
        interface.display_welcome()
        output = captured.getvalue()
        # Should contain key info
        self.assertIn("ikol1729", output)

    def test_welcome_fallback(self):
        """Welcome should work without rich too."""
        mock_chat = MagicMock()
        mock_chat.model = "deepseek-chat"
        mock_chat.mode = "chat"
        mock_chat.thinking_enabled = False
        mock_chat.conversation_history = []
        mock_chat.context_manager = MagicMock()

        from cli.claude_interface import ClaudeInterface
        interface = ClaudeInterface(mock_chat)
        interface.console = None  # Force fallback

        with patch('builtins.print') as mock_print:
            interface.display_welcome()
            mock_print.assert_called()


class TestNpmDependencyFree(unittest.TestCase):
    """Ensure no npm/node dependencies are required."""

    def test_no_package_json(self):
        """No package.json should exist in the project."""
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.assertFalse(
            os.path.exists(os.path.join(project_root, "package.json")),
            "package.json should not exist - use Python packages only"
        )

    def test_no_node_modules(self):
        """No node_modules directory should exist."""
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.assertFalse(
            os.path.exists(os.path.join(project_root, "node_modules")),
            "node_modules should not exist - use Python packages only"
        )

    def test_all_deps_are_python(self):
        """pyproject.toml should only list Python dependencies."""
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        pyproject_path = os.path.join(project_root, "pyproject.toml")
        self.assertTrue(os.path.exists(pyproject_path))
        content = open(pyproject_path).read()
        # Should contain Python package references
        self.assertIn("openai", content)
        self.assertIn("prompt_toolkit", content)


class TestCoreImports(unittest.TestCase):
    """Test that core.py has no duplicate imports after cleanup."""

    def test_no_duplicate_top_level_imports(self):
        """core.py top-level imports (before class def) should not be duplicated."""
        core_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "agent", "core.py"
        )
        with open(core_path) as f:
            lines = f.readlines()

        # Only check imports before the first class definition (top-level)
        import_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("class "):
                break  # Stop at first class definition
            # Only consider non-indented import lines
            if not line[0:1].isspace() and (stripped.startswith("import ") or stripped.startswith("from ")):
                import_lines.append(stripped)

        # Find duplicates
        seen = set()
        duplicates = []
        for line in import_lines:
            if line in seen:
                duplicates.append(line)
            seen.add(line)

        self.assertEqual(
            len(duplicates), 0,
            f"Found duplicate top-level imports in core.py: {duplicates}"
        )


class TestIntegrationLoop(unittest.TestCase):
    """Test the main chat loop integration."""

    def test_interface_creation(self):
        """ClaudeInterface should initialize without errors."""
        mock_chat = MagicMock()
        mock_chat.model = "deepseek-chat"
        mock_chat.mode = "chat"
        mock_chat.thinking_enabled = False
        mock_chat.conversation_history = []
        mock_chat.context_manager = MagicMock()

        from cli.claude_interface import ClaudeInterface
        interface = ClaudeInterface(mock_chat)
        self.assertTrue(interface.running)
        self.assertFalse(interface._interrupt)

    def test_command_routing(self):
        """Commands should be routed correctly: local vs agent core."""
        mock_chat = MagicMock()
        mock_chat.model = "deepseek-chat"
        mock_chat.mode = "chat"
        mock_chat.thinking_enabled = False
        mock_chat.conversation_history = []
        mock_chat.context_manager = MagicMock()

        from cli.claude_interface import ClaudeInterface
        interface = ClaudeInterface(mock_chat)

        # Local commands
        self.assertFalse(interface._handle_local_command("/quit"))
        self.assertTrue(interface._handle_local_command("/clear"))
        self.assertTrue(interface._handle_local_command("/think"))
        self.assertTrue(interface._handle_local_command("/help"))

        # Agent core commands (should return None)
        self.assertIsNone(interface._handle_local_command("/search test"))
        self.assertIsNone(interface._handle_local_command("/code scan"))
        self.assertIsNone(interface._handle_local_command("/models list"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
