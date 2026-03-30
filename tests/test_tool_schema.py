"""Tests for the formalized tool schema system (Phase 1).

Tests cover:
- ToolParam creation and repr
- ToolDefinition validation (required, types, enums, unknowns)
- ToolDefinition.apply_defaults()
- ToolDefinition.to_prompt_schema()
- generate_tool_prompt()
- PermissionLevel enum values
- ToolResult metadata enhancement
- ToolRegistry schema registration and get_tool()
- Edge cases: bool-as-int, float-as-int, empty params
"""

import os
import sys
import json
import tempfile
import unittest

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.tool_schema import (
    ToolParam, ParamType, ToolDefinition, PermissionLevel, generate_tool_prompt,
)
from agent.tools import ToolResult


# ── ToolParam Tests ───────────────────────────────────────────────────────────

class TestToolParam(unittest.TestCase):
    def test_basic_creation(self):
        p = ToolParam("path", ParamType.STRING, "File path")
        self.assertEqual(p.name, "path")
        self.assertEqual(p.param_type, ParamType.STRING)
        self.assertTrue(p.required)
        self.assertIsNone(p.default)

    def test_optional_with_default(self):
        p = ToolParam("timeout", ParamType.INTEGER, "Timeout", required=False, default=120)
        self.assertFalse(p.required)
        self.assertEqual(p.default, 120)

    def test_enum_constraint(self):
        p = ToolParam("mode", ParamType.STRING, "Output mode",
                      required=False, default="content",
                      enum=["content", "files_with_matches", "count"])
        self.assertEqual(p.enum, ["content", "files_with_matches", "count"])

    def test_repr(self):
        p = ToolParam("path", ParamType.STRING, "File path")
        self.assertIn("path", repr(p))
        self.assertIn("string", repr(p))
        self.assertIn("required", repr(p))


# ── PermissionLevel Tests ─────────────────────────────────────────────────────

class TestPermissionLevel(unittest.TestCase):
    def test_values(self):
        self.assertEqual(PermissionLevel.READ_ONLY.value, "read_only")
        self.assertEqual(PermissionLevel.WRITE.value, "write")
        self.assertEqual(PermissionLevel.EXECUTE.value, "execute")
        self.assertEqual(PermissionLevel.DESTRUCTIVE.value, "destructive")

    def test_comparison(self):
        self.assertNotEqual(PermissionLevel.READ_ONLY, PermissionLevel.EXECUTE)
        self.assertEqual(PermissionLevel.READ_ONLY, PermissionLevel.READ_ONLY)


# ── ToolDefinition Validation Tests ───────────────────────────────────────────

def _noop(**kwargs):
    return ToolResult(True, output="ok")


def _make_read_tool():
    return ToolDefinition(
        name="Read",
        description="Read a file",
        parameters=[
            ToolParam("path", ParamType.STRING, "File path"),
            ToolParam("offset", ParamType.INTEGER, "Start line", required=False, default=0),
            ToolParam("limit", ParamType.INTEGER, "Max lines", required=False, default=0),
        ],
        permission_level=PermissionLevel.READ_ONLY,
        execute=_noop,
    )


def _make_grep_tool():
    return ToolDefinition(
        name="Grep",
        description="Search files",
        parameters=[
            ToolParam("pattern", ParamType.STRING, "Regex pattern"),
            ToolParam("output_mode", ParamType.STRING, "Format",
                      required=False, default="content",
                      enum=["content", "files_with_matches", "count"]),
            ToolParam("case_insensitive", ParamType.BOOLEAN, "Case insensitive",
                      required=False, default=False),
        ],
        permission_level=PermissionLevel.READ_ONLY,
        execute=_noop,
    )


class TestToolDefinitionValidation(unittest.TestCase):
    """Test parameter validation logic."""

    def test_valid_required_only(self):
        tool = _make_read_tool()
        ok, err = tool.validate_params({"path": "src/main.py"})
        self.assertTrue(ok)
        self.assertEqual(err, "")

    def test_valid_all_params(self):
        tool = _make_read_tool()
        ok, err = tool.validate_params({"path": "src/main.py", "offset": 10, "limit": 50})
        self.assertTrue(ok)

    def test_missing_required(self):
        tool = _make_read_tool()
        ok, err = tool.validate_params({})
        self.assertFalse(ok)
        self.assertIn("path", err)
        self.assertIn("Missing required", err)

    def test_unknown_parameter_silently_stripped(self):
        """Unknown params should be silently stripped, not rejected.

        LLMs sometimes hallucinate extra params (e.g. 'reason') —
        rejecting them wastes a round-trip. We just ignore them.
        """
        tool = _make_read_tool()
        params = {"path": "x", "nonexistent": 42}
        ok, err = tool.validate_params(params)
        self.assertTrue(ok)
        self.assertEqual(err, "")
        # The unknown key should have been removed
        self.assertNotIn("nonexistent", params)

    def test_wrong_type_string(self):
        tool = _make_read_tool()
        ok, err = tool.validate_params({"path": 42})  # Should be string
        self.assertFalse(ok)
        self.assertIn("must be string", err)

    def test_wrong_type_integer(self):
        tool = _make_read_tool()
        ok, err = tool.validate_params({"path": "x", "offset": "not_int"})
        self.assertFalse(ok)
        self.assertIn("must be integer", err)

    def test_bool_not_accepted_as_integer(self):
        """Python's bool is a subclass of int — we must reject it for INTEGER params."""
        tool = _make_read_tool()
        ok, err = tool.validate_params({"path": "x", "offset": True})
        self.assertFalse(ok)
        self.assertIn("must be integer", err)

    def test_wrong_type_boolean(self):
        tool = _make_grep_tool()
        ok, err = tool.validate_params({"pattern": "test", "case_insensitive": "yes"})
        self.assertFalse(ok)
        self.assertIn("must be boolean", err)

    def test_enum_valid(self):
        tool = _make_grep_tool()
        ok, err = tool.validate_params({"pattern": "test", "output_mode": "count"})
        self.assertTrue(ok)

    def test_enum_invalid(self):
        tool = _make_grep_tool()
        ok, err = tool.validate_params({"pattern": "test", "output_mode": "invalid"})
        self.assertFalse(ok)
        self.assertIn("must be one of", err)
        self.assertIn("invalid", err)

    def test_empty_params_with_no_required(self):
        """Tool with no required params should validate with empty dict."""
        tool = ToolDefinition(
            name="LS",
            description="List dir",
            parameters=[
                ToolParam("path", ParamType.STRING, "Dir", required=False, default=None),
            ],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        ok, err = tool.validate_params({})
        self.assertTrue(ok)

    def test_float_accepts_int(self):
        """FLOAT params should accept int values (int is valid as float)."""
        tool = ToolDefinition(
            name="Test",
            description="Test",
            parameters=[
                ToolParam("value", ParamType.FLOAT, "A number"),
            ],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        ok, err = tool.validate_params({"value": 42})
        self.assertTrue(ok)
        ok, err = tool.validate_params({"value": 3.14})
        self.assertTrue(ok)
        ok, err = tool.validate_params({"value": "not_num"})
        self.assertFalse(ok)


# ── apply_defaults Tests ──────────────────────────────────────────────────────

class TestApplyDefaults(unittest.TestCase):
    def test_fills_missing_optional(self):
        tool = _make_read_tool()
        params = tool.apply_defaults({"path": "x"})
        self.assertEqual(params["offset"], 0)
        self.assertEqual(params["limit"], 0)

    def test_does_not_override_provided(self):
        tool = _make_read_tool()
        params = tool.apply_defaults({"path": "x", "offset": 50})
        self.assertEqual(params["offset"], 50)

    def test_does_not_modify_input(self):
        tool = _make_read_tool()
        original = {"path": "x"}
        result = tool.apply_defaults(original)
        self.assertNotIn("offset", original)  # Original unchanged
        self.assertIn("offset", result)


# ── to_prompt_schema Tests ────────────────────────────────────────────────────

class TestPromptSchema(unittest.TestCase):
    def test_basic_schema(self):
        tool = _make_read_tool()
        schema = tool.to_prompt_schema()
        self.assertIn("**Read**", schema)
        self.assertIn("Read a file", schema)
        self.assertIn("path (string, required)", schema)
        self.assertIn("offset (integer, optional", schema)

    def test_enum_in_schema(self):
        tool = _make_grep_tool()
        schema = tool.to_prompt_schema()
        self.assertIn("[values: content, files_with_matches, count]", schema)

    def test_examples_in_schema(self):
        tool = ToolDefinition(
            name="Bash",
            description="Run command",
            parameters=[ToolParam("command", ParamType.STRING, "Cmd")],
            permission_level=PermissionLevel.EXECUTE,
            execute=_noop,
            examples=[{"command": "ls"}],
        )
        schema = tool.to_prompt_schema()
        self.assertIn("Examples:", schema)
        self.assertIn('"command": "ls"', schema)

    def test_no_params_tool(self):
        tool = ToolDefinition(
            name="NoArgs",
            description="No args tool",
            parameters=[],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        schema = tool.to_prompt_schema()
        self.assertIn("Parameters: none", schema)


# ── generate_tool_prompt Tests ────────────────────────────────────────────────

class TestGenerateToolPrompt(unittest.TestCase):
    def test_contains_all_tools(self):
        tools = [_make_read_tool(), _make_grep_tool()]
        prompt = generate_tool_prompt(tools)
        self.assertIn("**Read**", prompt)
        self.assertIn("**Grep**", prompt)

    def test_contains_format_instructions(self):
        prompt = generate_tool_prompt([_make_read_tool()])
        self.assertIn("<tool_call>", prompt)
        self.assertIn("</tool_call>", prompt)
        self.assertIn("<tool_result>", prompt)
        self.assertIn("RULES:", prompt)

    def test_contains_rules(self):
        prompt = generate_tool_prompt([_make_read_tool()])
        self.assertIn("ONE tool call per response", prompt)
        self.assertIn("Do NOT guess or hallucinate", prompt)
        self.assertIn("Read a file before editing", prompt)


# ── ToolResult Metadata Tests ─────────────────────────────────────────────────

class TestToolResultMetadata(unittest.TestCase):
    def test_default_empty_metadata(self):
        r = ToolResult(True, output="ok")
        self.assertEqual(r.metadata, {})

    def test_metadata_provided(self):
        r = ToolResult(True, output="ok", metadata={"lines_read": 42})
        self.assertEqual(r.metadata["lines_read"], 42)

    def test_metadata_mutable(self):
        r = ToolResult(True, output="ok")
        r.metadata["duration_ms"] = 150
        self.assertEqual(r.metadata["duration_ms"], 150)

    def test_backward_compatible_str(self):
        r = ToolResult(True, output="hello")
        self.assertEqual(str(r), "hello")

    def test_backward_compatible_bool(self):
        self.assertTrue(bool(ToolResult(True)))
        self.assertFalse(bool(ToolResult(False)))

    def test_repr(self):
        r = ToolResult(True, output="some output")
        self.assertIn("OK", repr(r))
        r2 = ToolResult(False, error="bad thing")
        self.assertIn("ERROR", repr(r2))

    def test_metadata_not_shared_between_instances(self):
        """Ensure default metadata is not shared (mutable default arg trap)."""
        r1 = ToolResult(True)
        r2 = ToolResult(True)
        r1.metadata["x"] = 1
        self.assertNotIn("x", r2.metadata)


# ── ToolRegistry Schema Registration Tests ────────────────────────────────────

class TestToolRegistrySchemas(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _make_registry(self):
        from agent.tools import ToolRegistry
        return ToolRegistry(working_dir=self.tmpdir)

    def test_all_tools_registered(self):
        reg = self._make_registry()
        expected = {"Bash", "Read", "Write", "Edit", "Glob", "Grep", "LS", "SelfEditor"}
        self.assertEqual(set(reg._tool_definitions.keys()), expected)

    def test_get_tool_exact(self):
        reg = self._make_registry()
        tool = reg.get_tool("Read")
        self.assertIsNotNone(tool)
        self.assertEqual(tool.name, "Read")

    def test_get_tool_case_insensitive(self):
        reg = self._make_registry()
        tool = reg.get_tool("read")
        self.assertIsNotNone(tool)
        self.assertEqual(tool.name, "Read")

    def test_get_tool_unknown(self):
        reg = self._make_registry()
        self.assertIsNone(reg.get_tool("NonExistent"))

    def test_get_all_tools_order(self):
        reg = self._make_registry()
        tools = reg.get_all_tools()
        names = [t.name for t in tools]
        self.assertEqual(names, ["Bash", "Read", "Write", "Edit", "Glob", "Grep", "LS", "SelfEditor"])

    def test_bash_tool_is_execute(self):
        reg = self._make_registry()
        tool = reg.get_tool("Bash")
        self.assertEqual(tool.permission_level, PermissionLevel.EXECUTE)

    def test_read_tool_is_read_only(self):
        reg = self._make_registry()
        tool = reg.get_tool("Read")
        self.assertEqual(tool.permission_level, PermissionLevel.READ_ONLY)

    def test_write_tool_is_write(self):
        reg = self._make_registry()
        tool = reg.get_tool("Write")
        self.assertEqual(tool.permission_level, PermissionLevel.WRITE)

    def test_edit_tool_is_write(self):
        reg = self._make_registry()
        tool = reg.get_tool("Edit")
        self.assertEqual(tool.permission_level, PermissionLevel.WRITE)

    def test_glob_tool_is_read_only(self):
        reg = self._make_registry()
        tool = reg.get_tool("Glob")
        self.assertEqual(tool.permission_level, PermissionLevel.READ_ONLY)

    def test_grep_tool_is_read_only(self):
        reg = self._make_registry()
        tool = reg.get_tool("Grep")
        self.assertEqual(tool.permission_level, PermissionLevel.READ_ONLY)

    def test_ls_tool_is_read_only(self):
        reg = self._make_registry()
        tool = reg.get_tool("LS")
        self.assertEqual(tool.permission_level, PermissionLevel.READ_ONLY)

    def test_bash_tool_validates_params(self):
        reg = self._make_registry()
        tool = reg.get_tool("Bash")
        ok, _ = tool.validate_params({"command": "ls"})
        self.assertTrue(ok)
        ok, err = tool.validate_params({})
        self.assertFalse(ok)
        self.assertIn("command", err)

    def test_read_tool_validates_params(self):
        reg = self._make_registry()
        tool = reg.get_tool("Read")
        ok, _ = tool.validate_params({"path": "test.py"})
        self.assertTrue(ok)
        ok, _ = tool.validate_params({"path": "test.py", "offset": 10, "limit": 20})
        self.assertTrue(ok)

    def test_grep_enum_validation(self):
        reg = self._make_registry()
        tool = reg.get_tool("Grep")
        ok, _ = tool.validate_params({"pattern": "x", "output_mode": "count"})
        self.assertTrue(ok)
        ok, err = tool.validate_params({"pattern": "x", "output_mode": "bad"})
        self.assertFalse(ok)
        self.assertIn("must be one of", err)

    def test_tool_execution_via_schema(self):
        """Test that _exec_read actually works through the schema."""
        reg = self._make_registry()
        # Create a test file
        test_file = os.path.join(self.tmpdir, "test.txt")
        with open(test_file, "w") as f:
            f.write("line 1\nline 2\nline 3\n")

        tool = reg.get_tool("Read")
        result = tool.execute(path="test.txt")
        self.assertTrue(result.success)
        self.assertIn("line 1", result.output)
        self.assertIn("file_path", result.metadata)

    def test_exec_write_metadata(self):
        reg = self._make_registry()
        tool = reg.get_tool("Write")
        result = tool.execute(path=os.path.join(self.tmpdir, "out.txt"),
                              content="hello\nworld\n")
        self.assertTrue(result.success)
        self.assertEqual(result.metadata["bytes_written"], 12)
        self.assertEqual(result.metadata["lines_written"], 2)

    def test_exec_glob_metadata(self):
        reg = self._make_registry()
        # Create some files
        for name in ["a.py", "b.py", "c.txt"]:
            with open(os.path.join(self.tmpdir, name), "w") as f:
                f.write("x")
        tool = reg.get_tool("Glob")
        result = tool.execute(pattern="*.py")
        self.assertTrue(result.success)
        self.assertIn("pattern", result.metadata)

    def test_exec_ls_metadata(self):
        reg = self._make_registry()
        for name in ["a.txt", "b.txt"]:
            with open(os.path.join(self.tmpdir, name), "w") as f:
                f.write("x")
        tool = reg.get_tool("LS")
        result = tool.execute()
        self.assertTrue(result.success)
        self.assertIn("entry_count", result.metadata)


# ── Coding Scenario Coverage Tests ────────────────────────────────────────────

class TestCodingScenarios(unittest.TestCase):
    """Verify tool schemas cover all common coding scenarios."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        from agent.tools import ToolRegistry
        self.reg = ToolRegistry(working_dir=self.tmpdir)

    def test_scenario_read_file(self):
        """Scenario: User asks 'read main.py' → Read tool."""
        tool = self.reg.get_tool("Read")
        self.assertIsNotNone(tool)
        ok, _ = tool.validate_params({"path": "src/main.py"})
        self.assertTrue(ok)

    def test_scenario_read_file_range(self):
        """Scenario: User asks 'show me lines 50-100 of core.py' → Read with offset/limit."""
        tool = self.reg.get_tool("Read")
        ok, _ = tool.validate_params({"path": "core.py", "offset": 50, "limit": 50})
        self.assertTrue(ok)

    def test_scenario_edit_file(self):
        """Scenario: User asks 'rename function foo to bar' → Edit tool."""
        tool = self.reg.get_tool("Edit")
        ok, _ = tool.validate_params({
            "path": "src/main.py",
            "old_string": "def foo(",
            "new_string": "def bar(",
        })
        self.assertTrue(ok)

    def test_scenario_edit_replace_all(self):
        """Scenario: 'rename all occurrences of old_var to new_var' → Edit with replace_all."""
        tool = self.reg.get_tool("Edit")
        ok, _ = tool.validate_params({
            "path": "src/main.py",
            "old_string": "old_var",
            "new_string": "new_var",
            "replace_all": True,
        })
        self.assertTrue(ok)

    def test_scenario_create_file(self):
        """Scenario: User asks 'create a new file utils.py' → Write tool."""
        tool = self.reg.get_tool("Write")
        ok, _ = tool.validate_params({
            "path": "src/utils.py",
            "content": "def helper():\n    pass\n",
        })
        self.assertTrue(ok)

    def test_scenario_run_tests(self):
        """Scenario: User asks 'run the tests' → Bash tool."""
        tool = self.reg.get_tool("Bash")
        ok, _ = tool.validate_params({"command": "python3 -m pytest tests/ -v"})
        self.assertTrue(ok)

    def test_scenario_run_with_timeout(self):
        """Scenario: Long-running build → Bash with custom timeout."""
        tool = self.reg.get_tool("Bash")
        ok, _ = tool.validate_params({"command": "make build", "timeout": 300})
        self.assertTrue(ok)

    def test_scenario_find_files(self):
        """Scenario: 'find all Python files in src/' → Glob tool."""
        tool = self.reg.get_tool("Glob")
        ok, _ = tool.validate_params({"pattern": "**/*.py", "path": "src/"})
        self.assertTrue(ok)

    def test_scenario_search_code(self):
        """Scenario: 'search for TODO comments' → Grep tool."""
        tool = self.reg.get_tool("Grep")
        ok, _ = tool.validate_params({
            "pattern": "TODO|FIXME",
            "case_insensitive": True,
            "file_type": "py",
        })
        self.assertTrue(ok)

    def test_scenario_search_files_only(self):
        """Scenario: 'which files import requests?' → Grep with files_with_matches."""
        tool = self.reg.get_tool("Grep")
        ok, _ = tool.validate_params({
            "pattern": "import requests",
            "output_mode": "files_with_matches",
        })
        self.assertTrue(ok)

    def test_scenario_list_directory(self):
        """Scenario: 'what's in the src folder?' → LS tool."""
        tool = self.reg.get_tool("LS")
        ok, _ = tool.validate_params({"path": "src/"})
        self.assertTrue(ok)

    def test_scenario_git_operations(self):
        """Scenario: 'commit my changes' → Bash tool with git command."""
        tool = self.reg.get_tool("Bash")
        ok, _ = tool.validate_params({"command": "git add -A && git commit -m 'fix: bug'"})
        self.assertTrue(ok)

    def test_scenario_install_package(self):
        """Scenario: 'install numpy' → Bash tool with pip."""
        tool = self.reg.get_tool("Bash")
        ok, _ = tool.validate_params({
            "command": "pip install numpy --break-system-packages"
        })
        self.assertTrue(ok)

    def test_scenario_docker_build(self):
        """Scenario: 'build the docker image' → Bash tool."""
        tool = self.reg.get_tool("Bash")
        ok, _ = tool.validate_params({"command": "docker build -t myapp .", "timeout": 300})
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
