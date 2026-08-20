"""Tests for the refactored agentic loop and permission system (Phase 3).

Tests cover:
- _check_permission: all modes × all permission levels
- _run_agentic_loop: basic flow, multi-step, max iterations
- Backward compatibility with legacy bash blocks
- Per-tool permission levels (READ_ONLY auto-approves, WRITE/EXECUTE asks)
- Plan mode (READ_ONLY ok, others blocked)
- auto_accept mode (everything runs)
- Per-turn "a" flag
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.tool_schema import PermissionLevel
from agent.tool_parser import ToolCall


def _make_interface(mode="coding", tmpdir=None):
    """Create a NeoMindInterface with a mocked chat backend."""
    from cli.neomind_interface import NeoMindInterface

    chat = MagicMock()
    chat.mode = mode
    chat.thinking_enabled = False
    chat.model = "test-model"
    chat.conversation_history = []
    chat._content_filter = None
    chat._ui_on_first_token = None

    # Mock stream_response to be a no-op
    chat.stream_response = MagicMock()

    # Mock add_to_history
    def _add(role, content):
        chat.conversation_history.append({"role": role, "content": content})
    chat.add_to_history = _add

    interface = NeoMindInterface(chat)

    # Override working directory for tool registry
    if tmpdir:
        from agent.tools import ToolRegistry
        interface._tool_registry = ToolRegistry(working_dir=tmpdir)

    return interface, chat


class TestCheckPermission(unittest.TestCase):
    """Test _check_permission for all mode × level combinations."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.interface, self.chat = _make_interface(tmpdir=self.tmpdir)

    def _make_tc(self, tool_name="Bash"):
        return ToolCall(tool_name, {"command": "ls"}, "raw")

    # ── auto_accept mode ──

    @patch("cli.neomind_interface.agent_config")
    def test_auto_accept_always_approves(self, mock_config):
        mock_config.permission_mode = "auto_accept"
        tc = self._make_tc("Bash")
        with patch("builtins.input") as mock_input:
            approved, auto = self.interface._check_permission(tc, False)
        self.assertTrue(approved)
        self.assertTrue(auto)
        mock_input.assert_not_called()

    @patch("cli.neomind_interface.agent_config")
    def test_auto_accept_write_tools(self, mock_config):
        mock_config.permission_mode = "auto_accept"
        tc = ToolCall("Write", {"path": "x", "content": "y"}, "raw")
        approved, auto = self.interface._check_permission(tc, False)
        self.assertTrue(approved)

    @patch("builtins.input", return_value="n")
    @patch("cli.neomind_interface.agent_config")
    def test_auto_accept_critical_bash_prompts_and_denies(self, mock_config, mock_input):
        mock_config.permission_mode = "auto_accept"
        tc = ToolCall("Bash", {"command": "rm -rf /tmp/neomind-critical-test"}, "raw")

        approved, auto = self.interface._check_permission(tc, False)

        self.assertFalse(approved)
        self.assertFalse(auto)
        mock_input.assert_called_once()

    @patch("builtins.input", return_value="y")
    @patch("cli.neomind_interface.agent_config")
    def test_auto_accept_critical_bash_prompts_and_allows(self, mock_config, mock_input):
        mock_config.permission_mode = "auto_accept"
        tc = ToolCall("Bash", {"command": "rm -rf /tmp/neomind-critical-test"}, "raw")

        approved, auto = self.interface._check_permission(tc, False)

        self.assertTrue(approved)
        self.assertFalse(auto)
        mock_input.assert_called_once()

    # ── plan mode ──

    @patch("cli.neomind_interface.agent_config")
    def test_plan_allows_read_only(self, mock_config):
        mock_config.permission_mode = "plan"
        tc = ToolCall("Read", {"path": "x"}, "raw")
        approved, _ = self.interface._check_permission(tc, False)
        self.assertTrue(approved)

    @patch("cli.neomind_interface.agent_config")
    def test_plan_allows_grep(self, mock_config):
        mock_config.permission_mode = "plan"
        tc = ToolCall("Grep", {"pattern": "x"}, "raw")
        approved, _ = self.interface._check_permission(tc, False)
        self.assertTrue(approved)

    @patch("cli.neomind_interface.agent_config")
    def test_plan_allows_glob(self, mock_config):
        mock_config.permission_mode = "plan"
        tc = ToolCall("Glob", {"pattern": "*.py"}, "raw")
        approved, _ = self.interface._check_permission(tc, False)
        self.assertTrue(approved)

    @patch("cli.neomind_interface.agent_config")
    def test_plan_allows_ls(self, mock_config):
        mock_config.permission_mode = "plan"
        tc = ToolCall("LS", {}, "raw")
        approved, _ = self.interface._check_permission(tc, False)
        self.assertTrue(approved)

    @patch("cli.neomind_interface.agent_config")
    def test_plan_blocks_bash(self, mock_config):
        mock_config.permission_mode = "plan"
        tc = self._make_tc("Bash")
        approved, _ = self.interface._check_permission(tc, False)
        self.assertFalse(approved)

    @patch("cli.neomind_interface.agent_config")
    def test_plan_blocks_write(self, mock_config):
        mock_config.permission_mode = "plan"
        tc = ToolCall("Write", {"path": "x", "content": "y"}, "raw")
        approved, _ = self.interface._check_permission(tc, False)
        self.assertFalse(approved)

    @patch("cli.neomind_interface.agent_config")
    def test_plan_blocks_edit(self, mock_config):
        mock_config.permission_mode = "plan"
        tc = ToolCall("Edit", {"path": "x", "old_string": "a", "new_string": "b"}, "raw")
        approved, _ = self.interface._check_permission(tc, False)
        self.assertFalse(approved)

    # ── normal mode ──

    @patch("cli.neomind_interface.agent_config")
    def test_normal_auto_approves_read(self, mock_config):
        mock_config.permission_mode = "normal"
        tc = ToolCall("Read", {"path": "x"}, "raw")
        approved, _ = self.interface._check_permission(tc, False)
        self.assertTrue(approved)

    @patch("cli.neomind_interface.agent_config")
    def test_normal_auto_approves_grep(self, mock_config):
        mock_config.permission_mode = "normal"
        tc = ToolCall("Grep", {"pattern": "x"}, "raw")
        approved, _ = self.interface._check_permission(tc, False)
        self.assertTrue(approved)

    @patch("builtins.input", return_value="y")
    @patch("cli.neomind_interface.agent_config")
    def test_normal_asks_for_bash(self, mock_config, mock_input):
        mock_config.permission_mode = "normal"
        tc = self._make_tc("Bash")
        approved, _ = self.interface._check_permission(tc, False)
        self.assertTrue(approved)
        mock_input.assert_called_once()

    @patch("builtins.input", return_value="n")
    @patch("cli.neomind_interface.agent_config")
    def test_normal_deny_bash(self, mock_config, mock_input):
        mock_config.permission_mode = "normal"
        tc = self._make_tc("Bash")
        approved, _ = self.interface._check_permission(tc, False)
        self.assertFalse(approved)

    @patch("builtins.input", return_value="a")
    @patch("cli.neomind_interface.agent_config")
    def test_normal_all_flag(self, mock_config, mock_input):
        mock_config.permission_mode = "normal"
        tc = self._make_tc("Bash")
        approved, auto = self.interface._check_permission(tc, False)
        self.assertTrue(approved)
        self.assertTrue(auto)  # auto_approved should be True now

    @patch("cli.neomind_interface.agent_config")
    def test_auto_approved_skips_prompt(self, mock_config):
        """Once auto_approved=True, no more prompts for this turn."""
        mock_config.permission_mode = "normal"
        tc = self._make_tc("Bash")
        with patch("builtins.input") as mock_input:
            approved, auto = self.interface._check_permission(tc, True)  # already auto
        self.assertTrue(approved)
        self.assertTrue(auto)
        mock_input.assert_not_called()

    @patch("builtins.input", return_value="n")
    @patch("cli.neomind_interface.agent_config")
    def test_auto_approved_critical_path_prompts_and_denies(self, mock_config, mock_input):
        mock_config.permission_mode = "normal"
        tc = ToolCall("Write", {"path": ".env", "content": "secret"}, "raw")

        approved, auto = self.interface._check_permission(tc, True)

        self.assertFalse(approved)
        self.assertTrue(auto)
        mock_input.assert_called_once()

    @patch("builtins.input", return_value="y")
    @patch("cli.neomind_interface.agent_config")
    def test_auto_approved_critical_path_prompts_and_allows(self, mock_config, mock_input):
        mock_config.permission_mode = "normal"
        tc = ToolCall("Write", {"path": ".env", "content": "secret"}, "raw")

        approved, auto = self.interface._check_permission(tc, True)

        self.assertTrue(approved)
        self.assertTrue(auto)
        mock_input.assert_called_once()

    @patch("builtins.input", side_effect=EOFError)
    @patch("cli.neomind_interface.agent_config")
    def test_critical_prompt_eof_denies(self, mock_config, mock_input):
        mock_config.permission_mode = "auto_accept"
        tc = ToolCall("Bash", {"command": "sudo true"}, "raw")

        approved, _ = self.interface._check_permission(tc, False)

        self.assertFalse(approved)
        mock_input.assert_called_once()

    @patch("builtins.input", side_effect=KeyboardInterrupt)
    @patch("cli.neomind_interface.agent_config")
    def test_critical_prompt_ctrl_c_denies(self, mock_config, mock_input):
        mock_config.permission_mode = "auto_accept"
        tc = ToolCall("Bash", {"command": "sudo true"}, "raw")

        approved, _ = self.interface._check_permission(tc, False)

        self.assertFalse(approved)
        mock_input.assert_called_once()

    @patch("builtins.input", return_value="y")
    @patch("cli.neomind_interface.agent_config")
    def test_normal_asks_for_write(self, mock_config, mock_input):
        mock_config.permission_mode = "normal"
        tc = ToolCall("Write", {"path": "x", "content": "y"}, "raw")
        approved, _ = self.interface._check_permission(tc, False)
        self.assertTrue(approved)
        mock_input.assert_called_once()

    @patch("builtins.input", return_value="y")
    @patch("cli.neomind_interface.agent_config")
    def test_normal_asks_for_edit(self, mock_config, mock_input):
        mock_config.permission_mode = "normal"
        tc = ToolCall("Edit", {"path": "x", "old_string": "a", "new_string": "b"}, "raw")
        approved, _ = self.interface._check_permission(tc, False)
        self.assertTrue(approved)
        mock_input.assert_called_once()


class TestAgenticLoopFlow(unittest.TestCase):
    """Test the full _run_agentic_loop flow."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    @patch("cli.neomind_interface.agent_config")
    def test_no_tool_call_exits(self, mock_config):
        """Loop exits immediately if response has no tool call."""
        mock_config.permission_mode = "auto_accept"
        interface, chat = _make_interface(tmpdir=self.tmpdir)
        chat.conversation_history = [
            {"role": "assistant", "content": "The answer is 42."}
        ]
        interface._run_agentic_loop()
        # No crash, no stream_response call
        chat.stream_response.assert_not_called()

    @patch("cli.neomind_interface.agent_config")
    def test_not_coding_mode_exits(self, mock_config):
        """Loop exits immediately in chat mode."""
        interface, chat = _make_interface(mode="chat", tmpdir=self.tmpdir)
        chat.conversation_history = [
            {"role": "assistant", "content": '<tool_call>\n{"tool": "Bash", "params": {"command": "ls"}}\n</tool_call>'}
        ]
        interface._run_agentic_loop()
        chat.stream_response.assert_not_called()

    @patch("cli.neomind_interface.agent_config")
    def test_structured_tool_execution(self, mock_config):
        """Test full flow: structured Read tool call → execute → feed back."""
        mock_config.permission_mode = "auto_accept"
        interface, chat = _make_interface(tmpdir=self.tmpdir)

        # Create test file
        with open(os.path.join(self.tmpdir, "test.py"), "w") as f:
            f.write("import os\n")

        # Simulate assistant response with structured tool call
        chat.conversation_history = [
            {"role": "assistant", "content": '<tool_call>\n{"tool": "Read", "params": {"path": "test.py"}}\n</tool_call>'}
        ]

        # After re-prompt, assistant responds without tool call (ends loop)
        def fake_stream(prompt):
            response = "The file imports os."
            chat.conversation_history.append(
                {"role": "assistant", "content": response}
            )
            return response
        chat.stream_response = fake_stream

        interface._run_agentic_loop(max_iterations=2)

        # Verify tool result was fed back
        fed_back = [m for m in chat.conversation_history if m["role"] == "user"]
        self.assertTrue(len(fed_back) >= 1)
        self.assertIn("<tool_result>", fed_back[0]["content"])
        self.assertIn("import os", fed_back[0]["content"])

    @patch("cli.neomind_interface.agent_config")
    def test_legacy_bash_still_works(self, mock_config):
        """Test backward compatibility: legacy bash blocks still execute."""
        mock_config.permission_mode = "auto_accept"
        interface, chat = _make_interface(tmpdir=self.tmpdir)

        chat.conversation_history = [
            {"role": "assistant", "content": '```bash\necho hello_legacy\n```'}
        ]

        def fake_stream(prompt):
            chat.conversation_history.append(
                {"role": "assistant", "content": "Done."}
            )
        chat.stream_response = fake_stream

        interface._run_agentic_loop(max_iterations=2)

        fed_back = [m for m in chat.conversation_history if m["role"] == "user"]
        self.assertTrue(len(fed_back) >= 1)
        self.assertIn("hello_legacy", fed_back[0]["content"])

    @patch("cli.neomind_interface.agent_config")
    def test_plan_blocks_bash_allows_read(self, mock_config):
        """In plan mode, Bash is blocked but Read executes."""
        mock_config.permission_mode = "plan"
        interface, chat = _make_interface(tmpdir=self.tmpdir)

        # Try Bash — should be blocked
        chat.conversation_history = [
            {"role": "assistant", "content": '<tool_call>\n{"tool": "Bash", "params": {"command": "rm -rf /"}}\n</tool_call>'}
        ]
        interface._run_agentic_loop()
        # No tool result fed back (blocked)
        user_msgs = [m for m in chat.conversation_history if m["role"] == "user"]
        self.assertEqual(len(user_msgs), 0)

    @patch("cli.neomind_interface.agent_config")
    def test_max_iterations(self, mock_config):
        """Loop stops after max_iterations."""
        mock_config.permission_mode = "auto_accept"
        interface, chat = _make_interface(tmpdir=self.tmpdir)

        # Every re-prompt generates another tool call (infinite loop)
        call_count = [0]
        def fake_stream(prompt):
            call_count[0] += 1
            response = (
                '<tool_call>\n'
                f'{{"tool": "Bash", "params": {{"command": "echo step_{call_count[0]}"}}}}\n'
                '</tool_call>'
            )
            chat.conversation_history.append(
                {"role": "assistant", "content": response}
            )
            return response
        chat.stream_response = fake_stream

        chat.conversation_history = [
            {"role": "assistant", "content": '<tool_call>\n{"tool": "Bash", "params": {"command": "echo start"}}\n</tool_call>'}
        ]

        interface._run_agentic_loop(max_iterations=3)
        # Should have called stream_response exactly 3 times
        self.assertEqual(call_count[0], 3)

    @patch("cli.neomind_interface.agent_config")
    def test_validation_error_feeds_back(self, mock_config):
        """Invalid tool params → error fed back, loop continues."""
        mock_config.permission_mode = "auto_accept"
        interface, chat = _make_interface(tmpdir=self.tmpdir)

        # Invalid params (path should be string, not int)
        chat.conversation_history = [
            {"role": "assistant", "content": '<tool_call>\n{"tool": "Read", "params": {"path": 42}}\n</tool_call>'}
        ]

        def fake_stream(prompt):
            chat.conversation_history.append(
                {"role": "assistant", "content": "I see the error."}
            )
        chat.stream_response = fake_stream

        interface._run_agentic_loop(max_iterations=2)

        # Verify error was fed back
        user_msgs = [m for m in chat.conversation_history if m["role"] == "user"]
        self.assertTrue(len(user_msgs) >= 1)
        self.assertIn("ERROR", user_msgs[0]["content"])


class TestPermissionLevelMatrix(unittest.TestCase):
    """Verify permission behavior for every tool × every mode."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.interface, _ = _make_interface(tmpdir=self.tmpdir)

    def _check(self, tool_name, mode, auto_approved=False, input_val="y"):
        """Helper to test permission for a tool in a given mode."""
        tc = ToolCall(tool_name, {"command": "x"} if tool_name == "Bash" else {"path": "x"} if tool_name in ("Read", "Write", "Edit", "Glob") else {"pattern": "x"} if tool_name == "Grep" else {}, "raw")

        with patch("cli.neomind_interface.agent_config") as mc:
            mc.permission_mode = mode
            if mode == "normal" and not auto_approved:
                with patch("builtins.input", return_value=input_val):
                    return self.interface._check_permission(tc, auto_approved)
            else:
                return self.interface._check_permission(tc, auto_approved)

    # READ_ONLY tools: always approve in all modes
    def test_read_normal(self):
        approved, _ = self._check("Read", "normal")
        self.assertTrue(approved)

    def test_grep_normal(self):
        approved, _ = self._check("Grep", "normal")
        self.assertTrue(approved)

    def test_glob_normal(self):
        approved, _ = self._check("Glob", "normal")
        self.assertTrue(approved)

    def test_ls_normal(self):
        approved, _ = self._check("LS", "normal")
        self.assertTrue(approved)

    def test_read_plan(self):
        approved, _ = self._check("Read", "plan")
        self.assertTrue(approved)

    def test_read_auto(self):
        approved, _ = self._check("Read", "auto_accept")
        self.assertTrue(approved)

    # WRITE tools: ask in normal, approve in auto
    def test_write_normal_approve(self):
        approved, _ = self._check("Write", "normal", input_val="y")
        self.assertTrue(approved)

    def test_write_normal_deny(self):
        approved, _ = self._check("Write", "normal", input_val="n")
        self.assertFalse(approved)

    def test_write_auto(self):
        approved, _ = self._check("Write", "auto_accept")
        self.assertTrue(approved)

    def test_write_plan(self):
        approved, _ = self._check("Write", "plan")
        self.assertFalse(approved)

    # EXECUTE tools (Bash): ask in normal, approve in auto, block in plan
    def test_bash_normal_approve(self):
        approved, _ = self._check("Bash", "normal", input_val="y")
        self.assertTrue(approved)

    def test_bash_normal_deny(self):
        approved, _ = self._check("Bash", "normal", input_val="n")
        self.assertFalse(approved)

    def test_bash_auto(self):
        approved, _ = self._check("Bash", "auto_accept")
        self.assertTrue(approved)

    def test_bash_plan(self):
        approved, _ = self._check("Bash", "plan")
        self.assertFalse(approved)


if __name__ == "__main__":
    unittest.main()
