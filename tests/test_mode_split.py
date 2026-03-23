"""
End-to-end tests for the chat/coding mode split.

Tests config separation, command isolation, tool system, and mode-aware behavior.
"""

import os
import sys
import tempfile
import shutil
import unittest

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set a dummy API key for tests
os.environ["DEEPSEEK_API_KEY"] = "test-key-for-tests"


class TestConfigSeparation(unittest.TestCase):
    """Test that base, chat, and coding configs are properly separated."""

    def test_config_files_exist(self):
        from pathlib import Path
        config_dir = Path(__file__).parent.parent / "agent" / "config"
        self.assertTrue((config_dir / "base.yaml").exists())
        self.assertTrue((config_dir / "chat.yaml").exists())
        self.assertTrue((config_dir / "coding.yaml").exists())

    def test_base_config_has_shared_settings(self):
        import yaml
        from pathlib import Path
        config_dir = Path(__file__).parent.parent / "agent" / "config"
        base = yaml.safe_load((config_dir / "base.yaml").read_text())
        agent = base["agent"]
        self.assertEqual(agent["model"], "deepseek-chat")
        self.assertEqual(agent["context"]["max_context_tokens"], 131072)
        self.assertIn("temperature", agent)
        self.assertIn("max_tokens", agent)

    def test_chat_config_has_no_file_ops(self):
        import yaml
        from pathlib import Path
        config_dir = Path(__file__).parent.parent / "agent" / "config"
        chat = yaml.safe_load((config_dir / "chat.yaml").read_text())
        self.assertEqual(chat["mode"], "chat")
        self.assertTrue(chat["safety"]["confirm_file_operations"])
        # Chat should NOT have coding commands
        self.assertNotIn("run", chat["commands"])
        self.assertNotIn("edit", chat["commands"])
        self.assertNotIn("read", chat["commands"])
        self.assertNotIn("git", chat["commands"])

    def test_coding_config_has_tools_and_workspace(self):
        import yaml
        from pathlib import Path
        config_dir = Path(__file__).parent.parent / "agent" / "config"
        coding = yaml.safe_load((config_dir / "coding.yaml").read_text())
        self.assertEqual(coding["mode"], "coding")
        self.assertFalse(coding["safety"]["confirm_file_operations"])
        # Coding should have all tool commands
        for cmd in ("run", "edit", "read", "write", "glob", "grep", "git", "ls"):
            self.assertIn(cmd, coding["commands"])
        # Workspace config
        self.assertTrue(coding["workspace"]["auto_scan"])
        self.assertTrue(coding["workspace"]["auto_read_files"])
        # Compact config
        self.assertTrue(coding["compact"]["enabled"])


class TestAgentConfigManager(unittest.TestCase):
    """Test the rewritten AgentConfigManager with split configs."""

    def test_chat_mode_defaults(self):
        from agent_config import AgentConfigManager
        cfg = AgentConfigManager(mode="chat")
        self.assertEqual(cfg.mode, "chat")
        self.assertEqual(cfg.model, "deepseek-chat")
        self.assertTrue(cfg.safety_confirm_file_operations)
        self.assertEqual(cfg.natural_language_confidence_threshold, 0.8)
        self.assertIn("search", cfg.available_commands)
        self.assertNotIn("run", cfg.available_commands)

    def test_coding_mode_defaults(self):
        from agent_config import AgentConfigManager
        cfg = AgentConfigManager(mode="coding")
        self.assertEqual(cfg.mode, "coding")
        self.assertFalse(cfg.safety_confirm_file_operations)
        self.assertEqual(cfg.natural_language_confidence_threshold, 0.7)
        self.assertIn("run", cfg.available_commands)
        self.assertIn("edit", cfg.available_commands)
        self.assertTrue(cfg.workspace_auto_scan)
        self.assertTrue(cfg.compact_enabled)

    def test_mode_switch(self):
        from agent_config import AgentConfigManager
        cfg = AgentConfigManager(mode="chat")
        self.assertEqual(cfg.mode, "chat")
        cfg.switch_mode("coding")
        self.assertEqual(cfg.mode, "coding")
        self.assertFalse(cfg.safety_confirm_file_operations)
        self.assertIn("run", cfg.available_commands)
        cfg.switch_mode("chat")
        self.assertEqual(cfg.mode, "chat")
        self.assertTrue(cfg.safety_confirm_file_operations)
        self.assertNotIn("run", cfg.available_commands)

    def test_system_prompts_differ(self):
        from agent_config import AgentConfigManager
        chat_cfg = AgentConfigManager(mode="chat")
        code_cfg = AgentConfigManager(mode="coding")
        self.assertIn("AI assistant built on First Principles Thinking", chat_cfg.system_prompt)
        self.assertIn("expert software engineer", code_cfg.system_prompt)
        self.assertNotEqual(chat_cfg.system_prompt, code_cfg.system_prompt)

    def test_shared_base_settings(self):
        from agent_config import AgentConfigManager
        chat_cfg = AgentConfigManager(mode="chat")
        code_cfg = AgentConfigManager(mode="coding")
        # Both should have same base settings
        self.assertEqual(chat_cfg.model, code_cfg.model)
        self.assertEqual(chat_cfg.max_context_tokens, code_cfg.max_context_tokens)
        self.assertEqual(chat_cfg.temperature, code_cfg.temperature)

    def test_backward_compat_properties(self):
        from agent_config import AgentConfigManager
        cfg = AgentConfigManager(mode="chat")
        # Old property names should still work
        self.assertIsNotNone(cfg.coding_mode_system_prompt)
        self.assertFalse(cfg.coding_mode_safety_confirm_file_operations)
        self.assertTrue(cfg.coding_mode_show_status_bar)

    def test_invalid_mode_rejected(self):
        from agent_config import AgentConfigManager
        cfg = AgentConfigManager(mode="chat")
        result = cfg.switch_mode("invalid")
        self.assertFalse(result)
        self.assertEqual(cfg.mode, "chat")  # unchanged


class TestCommandSeparation(unittest.TestCase):
    """Test that commands are properly isolated per mode."""

    def test_chat_completer_commands(self):
        from cli.neomind_interface import SlashCommandCompleter
        completer = SlashCommandCompleter(mode="chat")
        self.assertIn("search", completer.commands)
        self.assertIn("help", completer.commands)
        self.assertIn("think", completer.commands)
        self.assertNotIn("run", completer.commands)
        self.assertNotIn("edit", completer.commands)
        self.assertNotIn("read", completer.commands)
        self.assertNotIn("git", completer.commands)
        self.assertNotIn("glob", completer.commands)

    def test_coding_completer_commands(self):
        from cli.neomind_interface import SlashCommandCompleter
        completer = SlashCommandCompleter(mode="coding")
        self.assertIn("run", completer.commands)
        self.assertIn("edit", completer.commands)
        self.assertIn("read", completer.commands)
        self.assertIn("glob", completer.commands)
        self.assertIn("grep", completer.commands)
        self.assertIn("git", completer.commands)
        self.assertIn("ls", completer.commands)
        self.assertIn("help", completer.commands)
        self.assertIn("think", completer.commands)

    def test_completer_mode_switch(self):
        from cli.neomind_interface import SlashCommandCompleter
        completer = SlashCommandCompleter(mode="chat")
        self.assertNotIn("run", completer.commands)
        completer.set_mode("coding")
        self.assertIn("run", completer.commands)

    def test_all_descriptions_covers_all_commands(self):
        from cli.neomind_interface import SlashCommandCompleter
        from agent_config import AgentConfigManager
        # Every command in both modes should have a description
        for mode in ("chat", "coding"):
            cfg = AgentConfigManager(mode=mode)
            for cmd in cfg.available_commands:
                self.assertIn(
                    cmd,
                    SlashCommandCompleter.ALL_DESCRIPTIONS,
                    f"/{cmd} ({mode} mode) missing from ALL_DESCRIPTIONS",
                )


class TestToolSystem(unittest.TestCase):
    """Test the NeoMind tool system."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        from agent.tools import ToolRegistry
        self.tools = ToolRegistry(working_dir=self.tmpdir)

    def tearDown(self):
        self.tools.close_bash()
        shutil.rmtree(self.tmpdir)

    def test_write_and_read(self):
        result = self.tools.write_file("test.py", "print('hello')\n")
        self.assertTrue(result.success)
        self.assertIn("Created", result.output)

        result = self.tools.read_file("test.py")
        self.assertTrue(result.success)
        self.assertIn("print('hello')", result.output)
        self.assertIn("1\t", result.output)  # line numbers

    def test_edit(self):
        self.tools.write_file("test.py", "x = 1\ny = 2\n")
        result = self.tools.edit_file("test.py", "x = 1", "x = 42")
        self.assertTrue(result.success)
        content = open(os.path.join(self.tmpdir, "test.py")).read()
        self.assertIn("x = 42", content)

    def test_edit_not_found(self):
        self.tools.write_file("test.py", "x = 1\n")
        result = self.tools.edit_file("test.py", "nonexistent", "x")
        self.assertFalse(result.success)

    def test_edit_ambiguous(self):
        self.tools.write_file("test.py", "x = 1\nx = 1\n")
        result = self.tools.edit_file("test.py", "x = 1", "x = 2")
        self.assertFalse(result.success)
        self.assertIn("2 occurrences", result.error)

    def test_bash(self):
        result = self.tools.bash("echo hello")
        self.assertTrue(result.success)
        self.assertEqual(result.output, "hello")

    def test_bash_timeout(self):
        result = self.tools.bash("sleep 10", timeout=1)
        self.assertFalse(result.success)
        self.assertIn("timed out", result.error)

    def test_glob(self):
        self.tools.write_file("a.py", "")
        self.tools.write_file("b.py", "")
        self.tools.write_file("c.txt", "")
        result = self.tools.glob_files("*.py")
        self.assertTrue(result.success)
        self.assertIn("a.py", result.output)
        self.assertIn("b.py", result.output)
        self.assertNotIn("c.txt", result.output)

    def test_grep(self):
        self.tools.write_file("a.py", "def hello():\n    pass\n")
        self.tools.write_file("b.py", "x = 1\n")
        result = self.tools.grep_files("def hello")
        self.assertTrue(result.success)
        self.assertIn("a.py", result.output)
        self.assertNotIn("b.py", result.output)

    def test_ls(self):
        self.tools.write_file("file.txt", "hello")
        os.makedirs(os.path.join(self.tmpdir, "subdir"))
        result = self.tools.list_dir()
        self.assertTrue(result.success)
        self.assertIn("subdir/", result.output)
        self.assertIn("file.txt", result.output)

    def test_read_nonexistent(self):
        result = self.tools.read_file("nonexistent.py")
        self.assertFalse(result.success)

    def test_read_with_offset_limit(self):
        self.tools.write_file("big.txt", "\n".join(f"line {i}" for i in range(100)))
        result = self.tools.read_file("big.txt", offset=10, limit=5)
        self.assertTrue(result.success)
        self.assertIn("showing lines 11-15", result.output)


class TestCoreIntegration(unittest.TestCase):
    """Test that core.py works correctly with the new config system."""

    def test_chat_mode_system_prompt(self):
        from agent_config import agent_config
        agent_config.switch_mode("chat")
        from agent.core import NeoMindAgent
        chat = NeoMindAgent(api_key="test")
        sys_msgs = [m for m in chat.conversation_history if m["role"] == "system"]
        self.assertEqual(len(sys_msgs), 1)
        self.assertIn("AI assistant built on First Principles Thinking", sys_msgs[0]["content"])

    def test_coding_mode_system_prompt(self):
        from agent_config import agent_config
        agent_config.switch_mode("coding")
        from agent.core import NeoMindAgent
        chat = NeoMindAgent(api_key="test")
        sys_msgs = [m for m in chat.conversation_history if m["role"] == "system"]
        self.assertEqual(len(sys_msgs), 1)
        self.assertIn("expert software engineer", sys_msgs[0]["content"])

    def test_switch_mode_updates_prompt(self):
        from agent_config import agent_config
        agent_config.switch_mode("chat")
        from agent.core import NeoMindAgent
        chat = NeoMindAgent(api_key="test")
        # Switch to coding
        chat.switch_mode("coding")
        sys_msgs = [m for m in chat.conversation_history if m["role"] == "system"]
        self.assertIn("expert software engineer", sys_msgs[0]["content"])
        # Switch back to chat
        chat.switch_mode("chat")
        sys_msgs = [m for m in chat.conversation_history if m["role"] == "system"]
        self.assertIn("AI assistant built on First Principles Thinking", sys_msgs[0]["content"])


class TestAgentConfigEdgeCases(unittest.TestCase):
    """Test edge cases and less common paths in AgentConfigManager."""

    def test_env_override_model(self):
        os.environ["DEEPSEEK_MODEL"] = "deepseek-reasoner"
        from agent_config import AgentConfigManager
        cfg = AgentConfigManager(mode="chat")
        self.assertEqual(cfg.model, "deepseek-reasoner")
        del os.environ["DEEPSEEK_MODEL"]

    def test_env_override_temperature(self):
        os.environ["DEEPSEEK_TEMPERATURE"] = "0.3"
        from agent_config import AgentConfigManager
        cfg = AgentConfigManager(mode="chat")
        self.assertEqual(cfg.temperature, 0.3)
        del os.environ["DEEPSEEK_TEMPERATURE"]

    def test_env_override_debug(self):
        os.environ["DEEPSEEK_DEBUG"] = "true"
        from agent_config import AgentConfigManager
        cfg = AgentConfigManager(mode="chat")
        self.assertTrue(cfg.debug)
        del os.environ["DEEPSEEK_DEBUG"]

    def test_env_override_invalid_temp_ignored(self):
        os.environ["DEEPSEEK_TEMPERATURE"] = "not_a_number"
        from agent_config import AgentConfigManager
        cfg = AgentConfigManager(mode="chat")
        self.assertEqual(cfg.temperature, 0.7)  # default
        del os.environ["DEEPSEEK_TEMPERATURE"]

    def test_neomind_mode_env_var(self):
        os.environ["IKOL_MODE"] = "coding"
        from agent_config import AgentConfigManager
        cfg = AgentConfigManager()  # no explicit mode
        self.assertEqual(cfg.mode, "coding")
        del os.environ["IKOL_MODE"]

    def test_invalid_neomind_mode_defaults_to_chat(self):
        os.environ["IKOL_MODE"] = "invalid_mode"
        from agent_config import AgentConfigManager
        cfg = AgentConfigManager()
        self.assertEqual(cfg.mode, "chat")
        del os.environ["IKOL_MODE"]

    def test_get_with_agent_prefix(self):
        from agent_config import AgentConfigManager
        cfg = AgentConfigManager(mode="chat")
        # Legacy agent. prefix should be stripped
        val = cfg.get("agent.context.max_context_tokens")
        self.assertEqual(val, 131072)

    def test_get_nonexistent_key_returns_default(self):
        from agent_config import AgentConfigManager
        cfg = AgentConfigManager(mode="chat")
        val = cfg.get("nonexistent.deeply.nested.key", "fallback")
        self.assertEqual(val, "fallback")

    def test_get_mode_config_unknown_mode(self):
        from agent_config import AgentConfigManager
        cfg = AgentConfigManager(mode="chat")
        result = cfg.get_mode_config("unknown")
        self.assertEqual(result, {})

    def test_mode_config_property(self):
        from agent_config import AgentConfigManager
        cfg = AgentConfigManager(mode="coding")
        mc = cfg.mode_config
        self.assertIn("system_prompt", mc)
        self.assertIn("commands", mc)

    def test_update_value_agent_key(self):
        from agent_config import AgentConfigManager
        cfg = AgentConfigManager(mode="chat")
        cfg.update_value("agent.model", "gpt-4")
        self.assertEqual(cfg.model, "gpt-4")

    def test_update_value_mode_key(self):
        from agent_config import AgentConfigManager
        cfg = AgentConfigManager(mode="chat")
        cfg.update_value("show_status_bar", False)
        self.assertFalse(cfg.show_status_bar)

    def test_context_properties(self):
        from agent_config import AgentConfigManager
        cfg = AgentConfigManager(mode="chat")
        self.assertEqual(cfg.max_context_tokens, 131072)
        self.assertAlmostEqual(cfg.context_warning_threshold, 0.61)
        self.assertAlmostEqual(cfg.context_break_threshold, 0.8)
        self.assertEqual(cfg.compression_strategy, "truncate")
        self.assertTrue(cfg.keep_system_messages)
        self.assertEqual(cfg.keep_recent_messages, 5)

    def test_base_properties(self):
        from agent_config import AgentConfigManager
        cfg = AgentConfigManager(mode="chat")
        self.assertTrue(cfg.stream)
        self.assertEqual(cfg.timeout, 30)
        self.assertEqual(cfg.max_retries, 3)
        self.assertEqual(cfg.max_tokens, 8192)

    def test_coding_specific_properties_from_chat_mode(self):
        """Coding-only properties should return defaults when in chat mode."""
        from agent_config import AgentConfigManager
        cfg = AgentConfigManager(mode="chat")
        self.assertFalse(cfg.workspace_auto_scan)
        self.assertFalse(cfg.workspace_auto_read_files)
        self.assertFalse(cfg.compact_enabled)
        self.assertEqual(cfg.permission_mode, "normal")

    def test_coding_specific_properties_from_coding_mode(self):
        from agent_config import AgentConfigManager
        cfg = AgentConfigManager(mode="coding")
        self.assertTrue(cfg.workspace_auto_scan)
        self.assertTrue(cfg.workspace_auto_read_files)
        self.assertTrue(cfg.workspace_auto_analyze_references)
        self.assertTrue(cfg.compact_enabled)
        self.assertAlmostEqual(cfg.compact_auto_trigger_threshold, 0.95)
        self.assertEqual(cfg.permission_mode, "normal")
        self.assertTrue(cfg.enable_mcp_support)

    def test_auto_search_triggers_chat(self):
        from agent_config import AgentConfigManager
        cfg = AgentConfigManager(mode="chat")
        triggers = cfg.auto_search_triggers
        self.assertIn("today", triggers)
        self.assertIn("news", triggers)
        self.assertTrue(cfg.auto_search_enabled)

    def test_auto_search_triggers_coding(self):
        from agent_config import AgentConfigManager
        cfg = AgentConfigManager(mode="coding")
        self.assertFalse(cfg.auto_search_enabled)
        self.assertEqual(cfg.auto_search_triggers, [])


class TestToolResultClass(unittest.TestCase):
    """Test the ToolResult class behavior."""

    def test_bool_success(self):
        from agent.tools import ToolResult
        r = ToolResult(True, output="ok")
        self.assertTrue(bool(r))

    def test_bool_failure(self):
        from agent.tools import ToolResult
        r = ToolResult(False, error="bad")
        self.assertFalse(bool(r))

    def test_str_success(self):
        from agent.tools import ToolResult
        r = ToolResult(True, output="hello")
        self.assertEqual(str(r), "hello")

    def test_str_failure(self):
        from agent.tools import ToolResult
        r = ToolResult(False, error="something broke")
        self.assertEqual(str(r), "Error: something broke")


class TestToolEdgeCases(unittest.TestCase):
    """Test edge cases in ToolRegistry."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        from agent.tools import ToolRegistry
        self.tools = ToolRegistry(working_dir=self.tmpdir)

    def tearDown(self):
        self.tools.close_bash()
        shutil.rmtree(self.tmpdir)

    def test_read_directory_error(self):
        os.makedirs(os.path.join(self.tmpdir, "mydir"))
        result = self.tools.read_file("mydir")
        self.assertFalse(result.success)
        self.assertIn("directory", result.error.lower())

    def test_read_long_lines_truncated(self):
        long_line = "x" * 3000 + "\n"
        self.tools.write_file("long.txt", long_line)
        result = self.tools.read_file("long.txt")
        self.assertTrue(result.success)
        self.assertIn("...", result.output)  # truncation marker

    def test_write_creates_parent_dirs(self):
        result = self.tools.write_file("sub/deep/file.txt", "content")
        self.assertTrue(result.success)
        self.assertTrue(os.path.exists(os.path.join(self.tmpdir, "sub", "deep", "file.txt")))

    def test_write_reports_updated_on_overwrite(self):
        self.tools.write_file("f.txt", "v1")
        result = self.tools.write_file("f.txt", "v2")
        self.assertTrue(result.success)
        self.assertIn("Updated", result.output)

    def test_edit_replace_all(self):
        self.tools.write_file("f.txt", "aaa\naaa\naaa\n")
        result = self.tools.edit_file("f.txt", "aaa", "bbb", replace_all=True)
        self.assertTrue(result.success)
        self.assertIn("3 replacement", result.output)
        content = open(os.path.join(self.tmpdir, "f.txt")).read()
        self.assertEqual(content.count("bbb"), 3)
        self.assertEqual(content.count("aaa"), 0)

    def test_edit_nonexistent_file(self):
        result = self.tools.edit_file("nope.txt", "a", "b")
        self.assertFalse(result.success)

    def test_glob_no_matches(self):
        result = self.tools.glob_files("*.xyz")
        self.assertTrue(result.success)  # success, just empty
        self.assertIn("No files matching", result.output)

    def test_glob_excludes_venv(self):
        venv_dir = os.path.join(self.tmpdir, ".venv", "lib")
        os.makedirs(venv_dir)
        self.tools.write_file(".venv/lib/site.py", "x")
        self.tools.write_file("main.py", "y")
        result = self.tools.glob_files("**/*.py")
        self.assertIn("main.py", result.output)
        self.assertNotIn(".venv", result.output)

    def test_grep_invalid_regex(self):
        result = self.tools.grep_files("[invalid")
        self.assertFalse(result.success)
        self.assertIn("Invalid regex", result.error)

    def test_grep_no_matches(self):
        self.tools.write_file("a.txt", "hello world\n")
        result = self.tools.grep_files("xyzzy_nomatch")
        self.assertTrue(result.success)
        self.assertIn("No matches", result.output)

    def test_grep_with_file_type(self):
        self.tools.write_file("a.py", "def foo(): pass\n")
        self.tools.write_file("b.js", "function foo() {}\n")
        result = self.tools.grep_files("foo", file_type="py")
        self.assertIn("a.py", result.output)
        self.assertNotIn("b.js", result.output)

    def test_grep_max_results(self):
        lines = "\n".join(f"match_{i}" for i in range(100))
        self.tools.write_file("many.txt", lines)
        result = self.tools.grep_files("match_", max_results=5)
        self.assertTrue(result.success)
        self.assertIn("truncated at 5", result.output)

    def test_grep_skips_binary_files(self):
        binary_path = os.path.join(self.tmpdir, "binary.bin")
        with open(binary_path, "wb") as f:
            f.write(b"\x00\x01\x02 match_this \x03\x04")
        result = self.tools.grep_files("match_this")
        # Should not crash, binary should be skipped
        self.assertTrue(result.success)

    def test_ls_nonexistent(self):
        result = self.tools.list_dir("/nonexistent_path_xyz")
        self.assertFalse(result.success)

    def test_ls_not_a_directory(self):
        self.tools.write_file("file.txt", "hi")
        result = self.tools.list_dir(os.path.join(self.tmpdir, "file.txt"))
        self.assertFalse(result.success)
        self.assertIn("Not a directory", result.error)

    def test_ls_size_formatting(self):
        # Small file
        self.tools.write_file("small.txt", "x")
        # Larger file
        self.tools.write_file("bigger.txt", "x" * 2000)
        result = self.tools.list_dir()
        self.assertTrue(result.success)
        self.assertIn("B", result.output)  # bytes
        self.assertIn("K", result.output)  # kilobytes

    def test_bash_failure_return_code(self):
        result = self.tools.bash("exit 1")
        self.assertFalse(result.success)

    def test_bash_stderr(self):
        result = self.tools.bash("echo err >&2")
        # stderr should appear in output
        self.assertIn("err", result.output)

    def test_resolve_absolute_path(self):
        abs_path = os.path.join(self.tmpdir, "abs.txt")
        self.tools.write_file(abs_path, "content")
        result = self.tools.read_file(abs_path)
        self.assertTrue(result.success)

    def test_resolve_relative_path(self):
        self.tools.write_file("rel.txt", "content")
        result = self.tools.read_file("rel.txt")
        self.assertTrue(result.success)


class TestNoDependencyOnHydra(unittest.TestCase):
    """Verify we no longer depend on Hydra/OmegaConf."""

    def test_agent_config_no_hydra_import(self):
        import importlib
        spec = importlib.util.find_spec("agent_config")
        source = open(spec.origin).read()
        # Check actual import statements, not comments
        self.assertNotIn("import hydra", source)
        self.assertNotIn("from hydra", source)
        self.assertNotIn("import omegaconf", source)
        self.assertNotIn("from omegaconf", source)

    def test_pyproject_no_hydra(self):
        from pathlib import Path
        toml = (Path(__file__).parent.parent / "pyproject.toml").read_text()
        self.assertNotIn("hydra-core", toml)


class TestNoPythonNpmDeps(unittest.TestCase):
    """Verify no npm dependencies exist."""

    def test_no_package_json(self):
        from pathlib import Path
        root = Path(__file__).parent.parent
        self.assertFalse((root / "package.json").exists())

    def test_no_node_modules(self):
        from pathlib import Path
        root = Path(__file__).parent.parent
        self.assertFalse((root / "node_modules").exists())


if __name__ == "__main__":
    unittest.main()
