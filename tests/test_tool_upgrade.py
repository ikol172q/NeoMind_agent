"""
Tests for the tool upgrade plan implementation.

Step 1: Tool→LLM Integration (command output → conversation history)
Step 2: Persistent Bash Session
Step 3: Ripgrep Integration
Step 4: Read tool truncation
Step 5: Glob mtime sorting
"""

import os
import sys
import tempfile
import shutil
import time
import unittest
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set a dummy API key for tests
os.environ["DEEPSEEK_API_KEY"] = "test-key-for-tests"


# ─── Step 1: Tool→LLM Integration ───────────────────────────────────────────


class TestTruncateMiddle(unittest.TestCase):
    """Test the _truncate_middle static method."""

    def _truncate(self, text, max_chars=30000):
        from agent.core import NeoMindAgent
        return NeoMindAgent._truncate_middle(text, max_chars=max_chars)

    def test_short_text_unchanged(self):
        text = "Hello world"
        self.assertEqual(self._truncate(text, 100), text)

    def test_exact_limit_unchanged(self):
        text = "x" * 30000
        self.assertEqual(self._truncate(text, 30000), text)

    def test_long_text_truncated(self):
        text = "A" * 10000 + "B" * 30000 + "C" * 10000  # 50K chars
        result = self._truncate(text, 30000)
        self.assertIn("chars truncated", result)
        self.assertTrue(len(result) < 50000)
        # Should preserve beginning (A's) and end (C's)
        self.assertTrue(result.startswith("A"))
        self.assertTrue(result.endswith("C"))

    def test_truncation_message_shows_removed_count(self):
        text = "x" * 50000
        result = self._truncate(text, 30000)
        # Should say 20,000 chars were truncated
        self.assertIn("20,000 chars truncated", result)

    def test_custom_limit(self):
        text = "x" * 200
        result = self._truncate(text, 100)
        self.assertIn("chars truncated", result)
        self.assertTrue(len(result) < 200)

    def test_empty_text(self):
        self.assertEqual(self._truncate("", 100), "")


class TestCommandsFeedToLLM(unittest.TestCase):
    """Test that command categorization is correct."""

    def test_tool_commands_feed_to_llm(self):
        from agent.core import NeoMindAgent
        tool_commands = {"/run", "/grep", "/find", "/read", "/write", "/edit",
                         "/git", "/code", "/diff", "/test", "/glob", "/ls"}
        for cmd in tool_commands:
            self.assertIn(cmd, NeoMindAgent.COMMANDS_FEED_TO_LLM,
                          f"{cmd} should feed to LLM")

    def test_ui_commands_dont_feed_to_llm(self):
        from agent.core import NeoMindAgent
        ui_commands = {"/help", "/clear", "/think", "/debug", "/save",
                       "/load", "/history", "/quit", "/exit", "/models",
                       "/switch", "/verbose", "/context", "/compact"}
        for cmd in ui_commands:
            self.assertNotIn(cmd, NeoMindAgent.COMMANDS_FEED_TO_LLM,
                             f"{cmd} should NOT feed to LLM")

    def test_search_and_browse_feed_to_llm(self):
        from agent.core import NeoMindAgent
        self.assertIn("/search", NeoMindAgent.COMMANDS_FEED_TO_LLM)
        self.assertIn("/browse", NeoMindAgent.COMMANDS_FEED_TO_LLM)


class TestToolOutputInHistory(unittest.TestCase):
    """Test that tool output is actually added to conversation history."""

    def setUp(self):
        """Create a minimal chat instance for testing."""
        from agent.core import NeoMindAgent
        self.chat = NeoMindAgent.__new__(NeoMindAgent)
        self.chat.conversation_history = []
        self.chat.mode = "coding"
        self.chat.thinking_enabled = False
        self.chat.verbose_mode = False
        self.chat.status_buffer = []
        self.chat.current_status = ""
        self.chat.last_status_update = 0

    def test_add_to_history_basic(self):
        self.chat.add_to_history("user", "hello")
        self.assertEqual(len(self.chat.conversation_history), 1)
        self.assertEqual(self.chat.conversation_history[0]["role"], "user")
        self.assertEqual(self.chat.conversation_history[0]["content"], "hello")

    def test_tool_result_format(self):
        """Verify the format of tool results in history."""
        from agent.core import NeoMindAgent
        result = "file.py:10: def main():"
        truncated = NeoMindAgent._truncate_middle(result)
        msg = f"[Tool: /grep] {truncated}"
        self.chat.add_to_history("user", msg)

        last = self.chat.conversation_history[-1]
        self.assertEqual(last["role"], "user")
        self.assertTrue(last["content"].startswith("[Tool: /grep]"))
        self.assertIn("def main()", last["content"])

    def test_truncated_tool_result_in_history(self):
        """Large tool output should be truncated before adding to history."""
        from agent.core import NeoMindAgent
        large_output = "x" * 50000
        truncated = NeoMindAgent._truncate_middle(large_output, max_chars=30000)
        self.chat.add_to_history("user", f"[Tool: /run] {truncated}")

        last = self.chat.conversation_history[-1]
        # Content should be much smaller than 50K
        self.assertTrue(len(last["content"]) < 35000)
        self.assertIn("chars truncated", last["content"])


# ─── Step 2: Persistent Bash Session ─────────────────────────────────────────


class TestPersistentBash(unittest.TestCase):
    """Test the PersistentBash session (when implemented)."""

    def test_persistent_bash_module_exists(self):
        """Check that persistent_bash.py exists."""
        from pathlib import Path
        module_path = Path(__file__).parent.parent / "agent" / "persistent_bash.py"
        # This will pass once Step 2 is implemented
        if module_path.exists():
            import importlib.util
            spec = importlib.util.spec_from_file_location("persistent_bash", module_path)
            self.assertIsNotNone(spec)

    def test_persistent_bash_state_carries(self):
        """cd in one command should persist to the next."""
        try:
            from agent.persistent_bash import PersistentBash
        except ImportError:
            self.skipTest("PersistentBash not yet implemented")

        bash = PersistentBash()
        try:
            bash.execute("cd /tmp")
            result = bash.execute("pwd")
            self.assertIn("/tmp", result.output)
        finally:
            bash.close()

    def test_persistent_bash_env_vars(self):
        """Environment variables should persist across commands."""
        try:
            from agent.persistent_bash import PersistentBash
        except ImportError:
            self.skipTest("PersistentBash not yet implemented")

        bash = PersistentBash()
        try:
            bash.execute("export TESTVAR=hello123")
            result = bash.execute("echo $TESTVAR")
            self.assertIn("hello123", result.output)
        finally:
            bash.close()

    def test_persistent_bash_timeout(self):
        """Commands should timeout after the specified duration."""
        try:
            from agent.persistent_bash import PersistentBash
        except ImportError:
            self.skipTest("PersistentBash not yet implemented")

        bash = PersistentBash(timeout=2)
        try:
            result = bash.execute("sleep 10", timeout=2)
            self.assertFalse(result.success)
            self.assertIn("timed out", result.error.lower())
        finally:
            bash.close()

    def test_persistent_bash_output_truncation(self):
        """Large output should be truncated."""
        try:
            from agent.persistent_bash import PersistentBash
        except ImportError:
            self.skipTest("PersistentBash not yet implemented")

        bash = PersistentBash(max_output=1000)
        try:
            result = bash.execute("python3 -c \"print('x' * 5000)\"")
            # Output should be truncated
            self.assertTrue(len(result.output) <= 1200)  # some overhead for truncation msg
        finally:
            bash.close()


class TestToolRegistryPersistentBash(unittest.TestCase):
    """Test that ToolRegistry.bash() uses persistent session."""

    def setUp(self):
        from agent.tools import ToolRegistry
        self.tmpdir = tempfile.mkdtemp()
        self.tools = ToolRegistry(working_dir=self.tmpdir)

    def tearDown(self):
        self.tools.close_bash()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_cd_persists_across_calls(self):
        """cd in one bash() call should persist to the next."""
        subdir = os.path.join(self.tmpdir, "subdir")
        os.makedirs(subdir)
        self.tools.bash(f"cd {subdir}")
        result = self.tools.bash("pwd")
        self.assertTrue(result.success)
        self.assertIn("subdir", result.output)

    def test_env_var_persists(self):
        """export in one call should be visible in the next."""
        self.tools.bash("export MY_TEST_VAR=persistent_value")
        result = self.tools.bash("echo $MY_TEST_VAR")
        self.assertTrue(result.success)
        self.assertIn("persistent_value", result.output)

    def test_bash_simple_command(self):
        result = self.tools.bash("echo hello")
        self.assertTrue(result.success)
        self.assertIn("hello", result.output)

    def test_bash_failure_returns_error(self):
        result = self.tools.bash("false")
        self.assertFalse(result.success)

    def test_close_bash(self):
        """close_bash() should terminate the session."""
        self.tools.bash("echo init")  # ensure session is created
        self.tools.close_bash()
        self.assertIsNone(self.tools._persistent_bash)


# ─── Step 3: Ripgrep Integration ─────────────────────────────────────────────


class TestRipgrepIntegration(unittest.TestCase):
    """Test ripgrep integration in grep_files."""

    def setUp(self):
        from agent.tools import ToolRegistry
        self.tmpdir = tempfile.mkdtemp()
        self.tools = ToolRegistry(working_dir=self.tmpdir)
        # Create test files
        os.makedirs(os.path.join(self.tmpdir, "src"), exist_ok=True)
        with open(os.path.join(self.tmpdir, "src", "main.py"), "w") as f:
            f.write("def main():\n    print('hello')\n\ndef helper():\n    pass\n")
        with open(os.path.join(self.tmpdir, "src", "utils.py"), "w") as f:
            f.write("import os\ndef utility():\n    return True\n")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_grep_finds_pattern(self):
        result = self.tools.grep_files("def main", path=self.tmpdir)
        self.assertTrue(result.success)
        self.assertIn("main", result.output)

    def test_grep_no_match(self):
        result = self.tools.grep_files("nonexistent_xyz_pattern", path=self.tmpdir)
        self.assertTrue(result.success)
        self.assertIn("No matches", result.output)

    def test_grep_with_file_type(self):
        result = self.tools.grep_files("def", path=self.tmpdir, file_type="py")
        self.assertTrue(result.success)
        self.assertIn("def", result.output)

    def test_grep_max_results(self):
        result = self.tools.grep_files("def", path=self.tmpdir, max_results=1)
        self.assertTrue(result.success)
        # Should have at most 1 match line (plus header)
        lines = [l for l in result.output.strip().split("\n") if not l.startswith("#")]
        self.assertLessEqual(len(lines), 1)

    def test_has_ripgrep_detection(self):
        """Test that _has_ripgrep returns a boolean."""
        if hasattr(self.tools, '_has_ripgrep'):
            result = self.tools._has_ripgrep()
            self.assertIsInstance(result, bool)


# ─── Step 4: Read Tool Truncation ────────────────────────────────────────────


class TestReadToolTruncation(unittest.TestCase):
    """Test read_file output truncation."""

    def setUp(self):
        from agent.tools import ToolRegistry
        self.tmpdir = tempfile.mkdtemp()
        self.tools = ToolRegistry(working_dir=self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_small_file_not_truncated(self):
        path = os.path.join(self.tmpdir, "small.py")
        with open(path, "w") as f:
            f.write("print('hello')\n")
        result = self.tools.read_file("small.py")
        self.assertTrue(result.success)
        self.assertNotIn("chars truncated", result.output)

    def test_large_file_truncated(self):
        """Files over 30K chars should be truncated."""
        path = os.path.join(self.tmpdir, "big.py")
        with open(path, "w") as f:
            for i in range(5000):
                f.write(f"line_{i} = 'x' * 100  # padding to make this line longer\n")
        result = self.tools.read_file("big.py")
        self.assertTrue(result.success)
        # Output should be truncated to ~30K
        self.assertTrue(len(result.output) < 35000)
        self.assertIn("chars truncated", result.output)

    def test_binary_file_rejected(self):
        """Binary files should return an error."""
        path = os.path.join(self.tmpdir, "binary.dat")
        with open(path, "wb") as f:
            f.write(b"\x00\x01\x02\xff" * 100)
        result = self.tools.read_file("binary.dat")
        self.assertFalse(result.success)
        self.assertIn("Binary file", result.error)

    def test_read_with_offset_and_limit(self):
        path = os.path.join(self.tmpdir, "lines.txt")
        with open(path, "w") as f:
            for i in range(100):
                f.write(f"Line {i}\n")
        result = self.tools.read_file("lines.txt", offset=10, limit=5)
        self.assertTrue(result.success)
        self.assertIn("showing lines 11-15", result.output)


# ─── Step 5: Glob mtime Sorting ──────────────────────────────────────────────


class TestGlobMtimeSorting(unittest.TestCase):
    """Test that glob results are sorted by modification time."""

    def setUp(self):
        from agent.tools import ToolRegistry
        self.tmpdir = tempfile.mkdtemp()
        self.tools = ToolRegistry(working_dir=self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_glob_finds_files(self):
        # Create test files
        for name in ["a.py", "b.py", "c.py"]:
            with open(os.path.join(self.tmpdir, name), "w") as f:
                f.write(f"# {name}\n")
        result = self.tools.glob_files("*.py")
        self.assertTrue(result.success)
        self.assertIn("3 files", result.output)

    def test_glob_mtime_order(self):
        """Most recently modified files should appear first."""
        # Create files with distinct mtimes
        for i, name in enumerate(["old.py", "mid.py", "new.py"]):
            path = os.path.join(self.tmpdir, name)
            with open(path, "w") as f:
                f.write(f"# {name}\n")
            # Set increasing mtime: old=oldest, new=newest
            mtime = time.time() - (2 - i) * 100
            os.utime(path, (mtime, mtime))

        result = self.tools.glob_files("*.py")
        self.assertTrue(result.success)
        lines = [l for l in result.output.strip().split("\n") if not l.startswith("#")]
        # new.py should be first (most recent mtime)
        self.assertEqual(lines[0], "new.py")
        self.assertEqual(lines[1], "mid.py")
        self.assertEqual(lines[2], "old.py")


# ─── Integration Tests ───────────────────────────────────────────────────────


class TestToolUpgradeIntegration(unittest.TestCase):
    """Integration tests across multiple steps."""

    def test_truncate_middle_is_static(self):
        """_truncate_middle should be callable without an instance."""
        from agent.core import NeoMindAgent
        result = NeoMindAgent._truncate_middle("short text")
        self.assertEqual(result, "short text")

    def test_commands_feed_to_llm_is_class_attr(self):
        """COMMANDS_FEED_TO_LLM should be a class attribute."""
        from agent.core import NeoMindAgent
        self.assertIsInstance(NeoMindAgent.COMMANDS_FEED_TO_LLM, set)
        self.assertTrue(len(NeoMindAgent.COMMANDS_FEED_TO_LLM) > 0)

    def test_tool_result_str_format(self):
        """ToolResult.__str__ should work correctly for history injection."""
        from agent.tools import ToolResult
        success = ToolResult(True, output="found 5 matches")
        self.assertEqual(str(success), "found 5 matches")

        failure = ToolResult(False, error="file not found")
        self.assertEqual(str(failure), "Error: file not found")


# ─── Additional Coverage: agent_config.py ─────────────────────────────────────


class TestAgentConfigSaveLoad(unittest.TestCase):
    """Test config save_config() and update_value()."""

    def test_update_value_agent_key(self):
        from agent_config import AgentConfigManager
        cfg = AgentConfigManager(mode="coding")
        result = cfg.update_value("agent.model", "test-model")
        self.assertTrue(result)
        self.assertEqual(cfg.model, "test-model")

    def test_update_value_nested_agent_key(self):
        from agent_config import AgentConfigManager
        cfg = AgentConfigManager(mode="coding")
        result = cfg.update_value("agent.context.max_context_tokens", 99999)
        self.assertTrue(result)
        self.assertEqual(cfg.max_context_tokens, 99999)

    def test_update_value_mode_key(self):
        from agent_config import AgentConfigManager
        cfg = AgentConfigManager(mode="chat")
        result = cfg.update_value("search_enabled", False)
        self.assertTrue(result)
        self.assertFalse(cfg.search_enabled)

    def test_save_config_round_trip(self):
        """save_config() should write YAML that can be reloaded."""
        from agent_config import AgentConfigManager
        import yaml

        cfg = AgentConfigManager(mode="coding")
        # Save to a temp dir
        original_dir = cfg.config_dir
        tmpdir = tempfile.mkdtemp()
        try:
            # Copy configs to temp
            for name in ["base.yaml", "chat.yaml", "coding.yaml"]:
                src = original_dir / name
                dst = os.path.join(tmpdir, name)
                with open(dst, "w") as f:
                    f.write(src.read_text())

            cfg.config_dir = Path(tmpdir)
            result = cfg.save_config()
            self.assertTrue(result)

            # Verify files written
            base_data = yaml.safe_load(open(os.path.join(tmpdir, "base.yaml")).read())
            self.assertIn("agent", base_data)
            self.assertIn("model", base_data["agent"])
        finally:
            shutil.rmtree(tmpdir)
            cfg.config_dir = original_dir

    def test_dot_get_empty_dict(self):
        from agent_config import AgentConfigManager
        cfg = AgentConfigManager(mode="chat")
        result = cfg._dot_get({}, "some.nested.key")
        self.assertIsNone(result)

    def test_dot_get_single_level(self):
        from agent_config import AgentConfigManager
        cfg = AgentConfigManager(mode="chat")
        result = cfg._dot_get({"key": "value"}, "key")
        self.assertEqual(result, "value")

    def test_get_with_legacy_prefix(self):
        from agent_config import AgentConfigManager
        cfg = AgentConfigManager(mode="coding")
        # agent.model should strip prefix and find model
        result = cfg.get("agent.model")
        self.assertIsNotNone(result)

    def test_get_unknown_key_returns_default(self):
        from agent_config import AgentConfigManager
        cfg = AgentConfigManager(mode="chat")
        result = cfg.get("nonexistent.key", "default_val")
        self.assertEqual(result, "default_val")

    def test_invalid_mode_defaults_to_chat(self):
        from agent_config import AgentConfigManager
        cfg = AgentConfigManager(mode="invalid_mode")
        self.assertEqual(cfg.mode, "chat")

    def test_get_mode_config_invalid_returns_empty(self):
        from agent_config import AgentConfigManager
        cfg = AgentConfigManager(mode="chat")
        result = cfg.get_mode_config("nonexistent")
        self.assertEqual(result, {})

    def test_backward_compat_properties(self):
        """Test backward-compatible property mappings."""
        from agent_config import AgentConfigManager
        cfg = AgentConfigManager(mode="coding")
        # These should all return reasonable values without errors
        self.assertIsInstance(cfg.auto_features_enabled, bool)
        self.assertIsInstance(cfg.coding_mode_auto_file_operations, bool)
        self.assertIsInstance(cfg.coding_mode_workspace_scan, bool)
        self.assertIsInstance(cfg.coding_mode_auto_read_files, bool)
        self.assertIsInstance(cfg.coding_mode_auto_analyze_references, bool)
        self.assertIsInstance(cfg.coding_mode_enable_auto_complete, bool)
        self.assertIsInstance(cfg.coding_mode_enable_mcp_support, bool)
        self.assertIsInstance(cfg.coding_mode_natural_language_confidence_threshold, float)

    def test_context_properties(self):
        """Test all context-related properties."""
        from agent_config import AgentConfigManager
        cfg = AgentConfigManager(mode="coding")
        self.assertIsInstance(cfg.max_context_tokens, int)
        self.assertIsInstance(cfg.context_warning_threshold, float)
        self.assertIsInstance(cfg.context_break_threshold, float)
        self.assertIsInstance(cfg.compression_strategy, str)
        self.assertIsInstance(cfg.keep_system_messages, bool)
        self.assertIsInstance(cfg.keep_recent_messages, int)


# ─── Additional Coverage: persistent_bash.py ──────────────────────────────────


class TestPersistentBashRobustness(unittest.TestCase):
    """Additional robustness tests for PersistentBash."""

    def test_format_output_empty(self):
        from agent.persistent_bash import PersistentBash
        bash = PersistentBash()
        try:
            result = bash._format_output([], [])
            self.assertEqual(result, "")
        finally:
            bash.close()

    def test_format_output_stdout_only(self):
        from agent.persistent_bash import PersistentBash
        bash = PersistentBash()
        try:
            result = bash._format_output(["line1\n", "line2\n"], [])
            self.assertIn("line1", result)
            self.assertIn("line2", result)
        finally:
            bash.close()

    def test_format_output_stderr_only(self):
        from agent.persistent_bash import PersistentBash
        bash = PersistentBash()
        try:
            result = bash._format_output([], ["error\n"])
            self.assertIn("error", result)
        finally:
            bash.close()

    def test_format_output_both(self):
        from agent.persistent_bash import PersistentBash
        bash = PersistentBash()
        try:
            result = bash._format_output(["out\n"], ["err\n"])
            self.assertIn("out", result)
            self.assertIn("STDERR", result)
            self.assertIn("err", result)
        finally:
            bash.close()

    def test_truncate_middle(self):
        from agent.persistent_bash import PersistentBash
        bash = PersistentBash(max_output=100)
        try:
            result = bash._truncate_middle("x" * 200)
            self.assertIn("chars truncated", result)
            self.assertTrue(len(result) < 200)
        finally:
            bash.close()

    def test_is_alive(self):
        from agent.persistent_bash import PersistentBash
        bash = PersistentBash()
        try:
            self.assertTrue(bash._is_alive())
        finally:
            bash.close()

    def test_not_alive_after_close(self):
        from agent.persistent_bash import PersistentBash
        bash = PersistentBash()
        bash.close()
        self.assertFalse(bash._is_alive())

    def test_execute_after_close_returns_error(self):
        from agent.persistent_bash import PersistentBash
        bash = PersistentBash()
        bash.close()
        result = bash.execute("echo test")
        self.assertFalse(result.success)
        self.assertIn("terminated", result.error)

    def test_get_cwd(self):
        from agent.persistent_bash import PersistentBash
        bash = PersistentBash(working_dir="/tmp")
        try:
            cwd = bash.get_cwd()
            self.assertIn("/tmp", cwd)
        finally:
            bash.close()

    def test_drain_queue_empty(self):
        import queue
        from agent.persistent_bash import PersistentBash
        q = queue.Queue()
        result = PersistentBash._drain_queue(q)
        self.assertEqual(result, "")

    def test_drain_queue_with_items(self):
        import queue
        from agent.persistent_bash import PersistentBash
        q = queue.Queue()
        q.put("line1\n")
        q.put("line2\n")
        result = PersistentBash._drain_queue(q)
        self.assertEqual(result, "line1\nline2\n")

    def test_exit_code_propagation(self):
        """Non-zero exit codes should be captured."""
        from agent.persistent_bash import PersistentBash
        bash = PersistentBash()
        try:
            result = bash.execute("(exit 42)")
            self.assertFalse(result.success)
            self.assertIn("42", result.error)
        finally:
            bash.close()

    def test_multiline_output(self):
        from agent.persistent_bash import PersistentBash
        bash = PersistentBash()
        try:
            result = bash.execute("echo line1; echo line2; echo line3")
            self.assertTrue(result.success)
            self.assertIn("line1", result.output)
            self.assertIn("line2", result.output)
            self.assertIn("line3", result.output)
        finally:
            bash.close()


# ─── Additional Coverage: tools.py ────────────────────────────────────────────


class TestToolRegistryAdditional(unittest.TestCase):
    """Additional tests for ToolRegistry coverage gaps."""

    def setUp(self):
        from agent.tools import ToolRegistry
        self.tmpdir = tempfile.mkdtemp()
        self.tools = ToolRegistry(working_dir=self.tmpdir)

    def tearDown(self):
        self.tools.close_bash()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_truncate_output_static(self):
        """_truncate_output should work as a static method."""
        from agent.tools import ToolRegistry
        result = ToolRegistry._truncate_output("short", max_chars=100)
        self.assertEqual(result, "short")

    def test_truncate_output_long(self):
        from agent.tools import ToolRegistry
        text = "x" * 500
        result = ToolRegistry._truncate_output(text, max_chars=100)
        self.assertIn("chars truncated", result)

    def test_read_file_line_truncation(self):
        """Lines over 2000 chars should be truncated."""
        path = os.path.join(self.tmpdir, "longline.txt")
        with open(path, "w") as f:
            f.write("x" * 3000 + "\n")
        result = self.tools.read_file("longline.txt", max_chars=100000)
        self.assertTrue(result.success)
        # Should contain truncation indicator
        self.assertIn("...", result.output)

    def test_write_file_creates_parent_dirs(self):
        result = self.tools.write_file("deep/nested/dir/file.py", "content")
        self.assertTrue(result.success)
        self.assertIn("Created", result.output)
        self.assertTrue(os.path.exists(os.path.join(self.tmpdir, "deep/nested/dir/file.py")))

    def test_write_file_reports_updated(self):
        self.tools.write_file("existing.py", "v1")
        result = self.tools.write_file("existing.py", "v2")
        self.assertTrue(result.success)
        self.assertIn("Updated", result.output)

    def test_edit_file_replace_all(self):
        self.tools.write_file("multi.py", "x = 1\ny = 1\nz = 1\n")
        result = self.tools.edit_file("multi.py", "1", "2", replace_all=True)
        self.assertTrue(result.success)
        self.assertIn("3 replacement", result.output)
        content = open(os.path.join(self.tmpdir, "multi.py")).read()
        self.assertNotIn("1", content)

    def test_glob_no_matches(self):
        result = self.tools.glob_files("*.xyz")
        self.assertTrue(result.success)
        self.assertIn("No files matching", result.output)

    def test_glob_excludes_git(self):
        """Files in .git should be excluded."""
        os.makedirs(os.path.join(self.tmpdir, ".git"))
        with open(os.path.join(self.tmpdir, ".git", "test.py"), "w") as f:
            f.write("")
        with open(os.path.join(self.tmpdir, "real.py"), "w") as f:
            f.write("")
        result = self.tools.glob_files("**/*.py")
        self.assertTrue(result.success)
        self.assertNotIn(".git", result.output)
        self.assertIn("real.py", result.output)

    def test_grep_case_insensitive(self):
        with open(os.path.join(self.tmpdir, "test.py"), "w") as f:
            f.write("Hello World\nhello world\n")
        result = self.tools.grep_files("HELLO", path=self.tmpdir, case_insensitive=True)
        self.assertTrue(result.success)
        # Should find both lines
        self.assertIn("2 match", result.output)

    def test_list_dir_excludes_hidden(self):
        """ls should exclude .git, .venv, __pycache__."""
        os.makedirs(os.path.join(self.tmpdir, ".git"))
        os.makedirs(os.path.join(self.tmpdir, ".venv"))
        os.makedirs(os.path.join(self.tmpdir, "src"))
        with open(os.path.join(self.tmpdir, "file.py"), "w") as f:
            f.write("x")
        result = self.tools.list_dir()
        self.assertTrue(result.success)
        self.assertNotIn(".git", result.output)
        self.assertNotIn(".venv", result.output)
        self.assertIn("src", result.output)

    def test_list_dir_size_formatting(self):
        """Size should show B, K, M units."""
        with open(os.path.join(self.tmpdir, "tiny.txt"), "w") as f:
            f.write("x")  # 1 byte
        with open(os.path.join(self.tmpdir, "medium.txt"), "w") as f:
            f.write("x" * 2048)  # ~2K
        result = self.tools.list_dir()
        self.assertTrue(result.success)
        self.assertIn("B", result.output)
        self.assertIn("K", result.output)

    def test_list_dir_nonexistent(self):
        result = self.tools.list_dir("/nonexistent_dir_12345")
        self.assertFalse(result.success)

    def test_list_dir_file_not_dir(self):
        path = os.path.join(self.tmpdir, "file.txt")
        with open(path, "w") as f:
            f.write("x")
        result = self.tools.list_dir(path)
        self.assertFalse(result.success)
        self.assertIn("Not a directory", result.error)

    def test_bash_fallback(self):
        """_bash_fallback should work as stateless subprocess."""
        result = self.tools._bash_fallback("echo fallback_test")
        self.assertTrue(result.success)
        self.assertIn("fallback_test", result.output)

    def test_bash_fallback_timeout(self):
        result = self.tools._bash_fallback("sleep 10", timeout=1)
        self.assertFalse(result.success)
        self.assertIn("timed out", result.error)


# ─── Additional Coverage: ConversationManager ─────────────────────────────────


class TestConversationManagerAdditional(unittest.TestCase):
    """Additional tests for ConversationManager."""

    def test_init_creates_directory(self):
        from cli.neomind_interface import ConversationManager
        mgr = ConversationManager()
        self.assertTrue(mgr.base_dir.exists())

    def test_save_json_structure(self):
        """Saved file should have proper JSON structure."""
        import json
        from cli.neomind_interface import ConversationManager
        from unittest.mock import MagicMock

        mgr = ConversationManager()
        chat = MagicMock()
        chat.model = "test-model"
        chat.mode = "chat"
        chat.thinking_enabled = False
        chat.conversation_history = [{"role": "user", "content": "hello"}]

        name = f"_test_json_struct_{int(time.time())}"
        try:
            fp = mgr.save(chat, name)
            data = json.loads(open(fp).read())
            self.assertIn("timestamp", data)
            self.assertIn("model", data)
            self.assertIn("mode", data)
            self.assertIn("history", data)
            self.assertEqual(data["model"], "test-model")
        finally:
            try:
                os.remove(fp)
            except OSError:
                pass

    def test_load_with_json_extension(self):
        from cli.neomind_interface import ConversationManager
        mgr = ConversationManager()
        result = mgr.load("nonexistent_conv.json")
        self.assertIsNone(result)


# ─── Additional Coverage: SlashCommandCompleter ──────────────────────────────


class TestSlashCommandCompleterAdditional(unittest.TestCase):
    """Additional edge case tests for SlashCommandCompleter."""

    def test_fallback_when_no_commands_in_config(self):
        """When config has empty commands, should fall back to ALL_DESCRIPTIONS."""
        from cli.neomind_interface import SlashCommandCompleter
        from unittest.mock import patch, MagicMock

        # Mock config to return empty commands
        mock_config = MagicMock()
        mock_config.get_mode_config.return_value = {"commands": []}

        with patch("cli.neomind_interface.agent_config", mock_config):
            completer = SlashCommandCompleter(mode="chat")
            # Should fall back to all descriptions
            self.assertEqual(set(completer.commands), set(SlashCommandCompleter.ALL_DESCRIPTIONS.keys()))

    def test_completion_yields_sorted(self):
        """Completions should be yielded in sorted order."""
        from cli.neomind_interface import SlashCommandCompleter
        from unittest.mock import MagicMock

        completer = SlashCommandCompleter.__new__(SlashCommandCompleter)
        completer.commands = ["quit", "help", "clear", "debug"]
        completer.mode = "chat"
        completer.help_system = None

        doc = MagicMock()
        doc.text_before_cursor = "/"
        completions = list(completer.get_completions(doc, None))
        texts = [c.text for c in completions]
        self.assertEqual(texts, sorted(texts))


if __name__ == "__main__":
    unittest.main()
