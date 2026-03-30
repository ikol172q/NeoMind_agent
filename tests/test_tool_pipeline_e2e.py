"""
Comprehensive end-to-end test suite for the complete tool pipeline.

Tests the full flow: parse → validate → execute → format result
This includes:
- Tool call parsing (structured and legacy formats)
- Parameter validation with unknown param stripping
- Tool execution through the registry
- Result formatting for LLM feedback
- Telegram tool_call display stripping

Architecture tested:
  agent/coding/tool_parser.py  - ToolCall.parse() and format_tool_result()
  agent/coding/tool_schema.py  - ToolDefinition.validate_params() and apply_defaults()
  agent/coding/tools.py        - ToolRegistry with all tools and _exec_* wrappers
  agent/agentic/agentic_loop.py - AgenticLoop._execute() orchestration
"""

import os
import sys
import re
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from typing import Optional

# Set up path for imports
_test_dir = os.path.dirname(os.path.abspath(__file__))
_agent_dir = os.path.dirname(_test_dir)
sys.path.insert(0, _agent_dir)

from agent.coding.tool_parser import ToolCall, ToolCallParser, format_tool_result
from agent.coding.tool_schema import (
    ToolDefinition, ToolParam, ParamType, PermissionLevel
)
from agent.coding.tools import ToolRegistry, ToolResult
from agent.agentic.agentic_loop import AgenticLoop, AgenticConfig


class TestParseValidateExecuteRead(unittest.TestCase):
    """Test the full pipeline for the Read tool:
    parse → validate params → execute on real file → format result
    """

    def setUp(self):
        """Create temp directory and registry for each test."""
        self.temp_dir = tempfile.mkdtemp()
        self.registry = ToolRegistry(working_dir=self.temp_dir)
        self.parser = ToolCallParser()

    def tearDown(self):
        """Clean up temp files."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_parse_structured_read_validate_execute(self):
        """Parse structured Read call → validate → execute on real temp file."""
        # Create a test file
        test_file = os.path.join(self.temp_dir, "test.txt")
        with open(test_file, "w") as f:
            f.write("line 1\nline 2\nline 3\n")

        # Parse structured tool call
        response = '<tool_call>{"tool": "Read", "params": {"path": "' + test_file + '"}}</tool_call>'
        tool_call = self.parser.parse(response)

        self.assertIsNotNone(tool_call)
        self.assertEqual(tool_call.tool_name, "Read")
        self.assertEqual(tool_call.params["path"], test_file)
        self.assertFalse(tool_call.is_legacy)

        # Validate params
        tool_def = self.registry.get_tool("Read")
        self.assertIsNotNone(tool_def)
        valid, error = tool_def.validate_params(tool_call.params)
        self.assertTrue(valid, f"Validation failed: {error}")

        # Apply defaults and execute
        params = tool_def.apply_defaults(tool_call.params)
        result = tool_def.execute(**params)

        self.assertTrue(result.success)
        self.assertIn("line 1", result.output)
        self.assertIn("line 2", result.output)

    def test_parse_xml_wrapped_read(self):
        """Parse XML-wrapped Read (DeepSeek format) → full pipeline."""
        test_file = os.path.join(self.temp_dir, "test.txt")
        with open(test_file, "w") as f:
            f.write("hello world\n")

        # XML-wrapped format: <tool_call><Read>{params}</Read></tool_call>
        response = (
            '<tool_call>\n'
            '<Read>\n'
            '{"path": "' + test_file + '"}\n'
            '</Read>\n'
            '</tool_call>'
        )
        tool_call = self.parser.parse(response)

        self.assertIsNotNone(tool_call)
        self.assertEqual(tool_call.tool_name, "Read")

        tool_def = self.registry.get_tool("Read")
        valid, error = tool_def.validate_params(tool_call.params)
        self.assertTrue(valid)

        params = tool_def.apply_defaults(tool_call.params)
        result = tool_def.execute(**params)
        self.assertTrue(result.success)
        self.assertIn("hello world", result.output)

    def test_parse_read_with_offset_limit(self):
        """Parse Read with offset/limit → correct lines returned."""
        test_file = os.path.join(self.temp_dir, "lines.txt")
        with open(test_file, "w") as f:
            for i in range(1, 11):
                f.write(f"line {i}\n")

        # Read lines 3-5 (offset=2, limit=3)
        response = (
            '{"tool": "Read", "params": {"path": "' + test_file + '", '
            '"offset": 2, "limit": 3}}'
        )
        # Wrap in tool_call tags
        tool_call = self.parser.parse(
            f'<tool_call>{response}</tool_call>'
        )

        self.assertIsNotNone(tool_call)
        self.assertEqual(tool_call.params["offset"], 2)
        self.assertEqual(tool_call.params["limit"], 3)

        tool_def = self.registry.get_tool("Read")
        valid, error = tool_def.validate_params(tool_call.params)
        self.assertTrue(valid)

        params = tool_def.apply_defaults(tool_call.params)
        result = tool_def.execute(**params)
        self.assertTrue(result.success)
        # Should contain lines 3-5
        self.assertIn("line 3", result.output)

    def test_parse_read_with_hallucinated_params(self):
        """Parse Read with hallucinated extra params (e.g., 'reason') → params stripped, still works."""
        test_file = os.path.join(self.temp_dir, "test.txt")
        with open(test_file, "w") as f:
            f.write("test content\n")

        # Include hallucinated "reason" parameter
        response = (
            '{"tool": "Read", "params": {"path": "' + test_file + '", '
            '"reason": "debugging purposes"}}'
        )
        tool_call = self.parser.parse(f'<tool_call>{response}</tool_call>')

        self.assertIsNotNone(tool_call)
        # Check that "reason" was parsed but will be stripped during validation
        self.assertIn("reason", tool_call.params)

        tool_def = self.registry.get_tool("Read")
        valid, error = tool_def.validate_params(tool_call.params)
        # Validation should succeed (strips unknown params)
        self.assertTrue(valid, f"Should succeed after stripping unknown params: {error}")

        # Execute should work
        params = tool_def.apply_defaults(tool_call.params)
        result = tool_def.execute(**params)
        self.assertTrue(result.success)
        self.assertIn("test content", result.output)

    def test_parse_read_nonexistent_file(self):
        """Parse Read for non-existent file → error result."""
        response = (
            '{"tool": "Read", "params": {"path": "/nonexistent/file.txt"}}'
        )
        tool_call = self.parser.parse(f'<tool_call>{response}</tool_call>')

        self.assertIsNotNone(tool_call)

        tool_def = self.registry.get_tool("Read")
        valid, error = tool_def.validate_params(tool_call.params)
        self.assertTrue(valid)  # Params are valid, but file doesn't exist

        params = tool_def.apply_defaults(tool_call.params)
        result = tool_def.execute(**params)
        self.assertFalse(result.success)
        # Error message varies, could be "No such file" or "File not found"
        self.assertTrue("not found" in result.error.lower())

    def test_format_read_result(self):
        """Format the Read result → valid <tool_result> block."""
        test_file = os.path.join(self.temp_dir, "test.txt")
        with open(test_file, "w") as f:
            f.write("test content\n")

        response = (
            '{"tool": "Read", "params": {"path": "' + test_file + '"}}'
        )
        tool_call = self.parser.parse(f'<tool_call>{response}</tool_call>')

        tool_def = self.registry.get_tool("Read")
        params = tool_def.apply_defaults(tool_call.params)
        result = tool_def.execute(**params)

        # Format result
        formatted = format_tool_result(tool_call, result)

        self.assertIn("<tool_result>", formatted)
        self.assertIn("</tool_result>", formatted)
        self.assertIn("tool: Read", formatted)
        self.assertIn("status: OK", formatted)
        self.assertIn("output: |", formatted)
        self.assertIn("test content", formatted)


class TestParseValidateExecuteWrite(unittest.TestCase):
    """Test the full pipeline for the Write tool."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.registry = ToolRegistry(working_dir=self.temp_dir)
        self.parser = ToolCallParser()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_parse_write_execute_file_created(self):
        """Parse Write tool call → execute → file actually created on disk."""
        file_path = os.path.join(self.temp_dir, "new_file.txt")
        content = "hello world"

        response = (
            '{"tool": "Write", "params": {"path": "' + file_path + '", '
            '"content": ' + json.dumps(content) + '}}'
        )
        tool_call = self.parser.parse(f'<tool_call>{response}</tool_call>')

        self.assertIsNotNone(tool_call)
        self.assertEqual(tool_call.tool_name, "Write")

        tool_def = self.registry.get_tool("Write")
        valid, error = tool_def.validate_params(tool_call.params)
        self.assertTrue(valid)

        params = tool_def.apply_defaults(tool_call.params)
        result = tool_def.execute(**params)

        self.assertTrue(result.success)
        self.assertTrue(os.path.exists(file_path))
        with open(file_path) as f:
            actual = f.read()
        self.assertEqual(actual, content)

    def test_write_verify_content_matches(self):
        """Verify written content matches exactly."""
        file_path = os.path.join(self.temp_dir, "test.py")
        content = 'def hello():\n    print("world")\n'

        response = (
            '{"tool": "Write", "params": {"path": "' + file_path + '", '
            '"content": ' + json.dumps(content) + '}}'
        )
        tool_call = self.parser.parse(f'<tool_call>{response}</tool_call>')

        tool_def = self.registry.get_tool("Write")
        params = tool_def.apply_defaults(tool_call.params)
        result = tool_def.execute(**params)

        self.assertTrue(result.success)
        with open(file_path) as f:
            actual = f.read()
        self.assertEqual(actual, content)

    def test_write_nested_directory_auto_creates(self):
        """Write to nested directory (auto-creates parents)."""
        file_path = os.path.join(self.temp_dir, "a", "b", "c", "test.txt")
        content = "nested"

        response = (
            '{"tool": "Write", "params": {"path": "' + file_path + '", '
            '"content": "' + content + '"}}'
        )
        tool_call = self.parser.parse(f'<tool_call>{response}</tool_call>')

        tool_def = self.registry.get_tool("Write")
        params = tool_def.apply_defaults(tool_call.params)
        result = tool_def.execute(**params)

        self.assertTrue(result.success)
        self.assertTrue(os.path.exists(file_path))
        with open(file_path) as f:
            self.assertEqual(f.read(), content)

    def test_write_empty_content(self):
        """Write with empty content → creates empty file."""
        file_path = os.path.join(self.temp_dir, "empty.txt")

        response = (
            '{"tool": "Write", "params": {"path": "' + file_path + '", '
            '"content": ""}}'
        )
        tool_call = self.parser.parse(f'<tool_call>{response}</tool_call>')

        tool_def = self.registry.get_tool("Write")
        params = tool_def.apply_defaults(tool_call.params)
        result = tool_def.execute(**params)

        self.assertTrue(result.success)
        self.assertTrue(os.path.exists(file_path))
        with open(file_path) as f:
            content = f.read()
        self.assertEqual(content, "")

    def test_format_write_result(self):
        """Format write result → shows 'Created'."""
        file_path = os.path.join(self.temp_dir, "new.txt")

        response = (
            '{"tool": "Write", "params": {"path": "' + file_path + '", '
            '"content": "test"}}'
        )
        tool_call = self.parser.parse(f'<tool_call>{response}</tool_call>')

        tool_def = self.registry.get_tool("Write")
        params = tool_def.apply_defaults(tool_call.params)
        result = tool_def.execute(**params)

        formatted = format_tool_result(tool_call, result)

        self.assertIn("<tool_result>", formatted)
        self.assertIn("tool: Write", formatted)
        self.assertIn("status: OK", formatted)


class TestParseValidateExecuteEdit(unittest.TestCase):
    """Test the full pipeline for the Edit tool."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.registry = ToolRegistry(working_dir=self.temp_dir)
        self.parser = ToolCallParser()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_parse_edit_execute_on_real_file(self):
        """Parse Edit → execute on real file → old_string replaced."""
        file_path = os.path.join(self.temp_dir, "test.txt")
        with open(file_path, "w") as f:
            f.write("old text here\n")

        response = (
            '{"tool": "Edit", "params": {"path": "' + file_path + '", '
            '"old_string": "old text", "new_string": "new text"}}'
        )
        tool_call = self.parser.parse(f'<tool_call>{response}</tool_call>')

        tool_def = self.registry.get_tool("Edit")
        valid, error = tool_def.validate_params(tool_call.params)
        self.assertTrue(valid)

        params = tool_def.apply_defaults(tool_call.params)
        result = tool_def.execute(**params)

        self.assertTrue(result.success)
        with open(file_path) as f:
            content = f.read()
        self.assertIn("new text", content)
        self.assertNotIn("old text", content)

    def test_edit_with_replace_all_true(self):
        """Edit with replace_all=true → all occurrences replaced."""
        file_path = os.path.join(self.temp_dir, "test.txt")
        with open(file_path, "w") as f:
            f.write("foo bar foo baz foo\n")

        response = (
            '{"tool": "Edit", "params": {"path": "' + file_path + '", '
            '"old_string": "foo", "new_string": "FOO", "replace_all": true}}'
        )
        tool_call = self.parser.parse(f'<tool_call>{response}</tool_call>')

        tool_def = self.registry.get_tool("Edit")
        params = tool_def.apply_defaults(tool_call.params)
        result = tool_def.execute(**params)

        self.assertTrue(result.success)
        with open(file_path) as f:
            content = f.read()
        # All 3 occurrences should be replaced
        self.assertEqual(content.count("FOO"), 3)
        self.assertNotIn("foo", content)

    def test_edit_nonexistent_old_string(self):
        """Edit with non-existent old_string → error."""
        file_path = os.path.join(self.temp_dir, "test.txt")
        with open(file_path, "w") as f:
            f.write("hello world\n")

        response = (
            '{"tool": "Edit", "params": {"path": "' + file_path + '", '
            '"old_string": "nonexistent", "new_string": "replaced"}}'
        )
        tool_call = self.parser.parse(f'<tool_call>{response}</tool_call>')

        tool_def = self.registry.get_tool("Edit")
        params = tool_def.apply_defaults(tool_call.params)
        result = tool_def.execute(**params)

        self.assertFalse(result.success)
        self.assertIn("not found", result.error.lower())

    def test_edit_multiple_occurrences_no_replace_all(self):
        """Edit with multiple occurrences and no replace_all → error or first replacement."""
        file_path = os.path.join(self.temp_dir, "test.txt")
        with open(file_path, "w") as f:
            f.write("foo bar foo baz\n")

        response = (
            '{"tool": "Edit", "params": {"path": "' + file_path + '", '
            '"old_string": "foo", "new_string": "FOO"}}'
        )
        tool_call = self.parser.parse(f'<tool_call>{response}</tool_call>')

        tool_def = self.registry.get_tool("Edit")
        params = tool_def.apply_defaults(tool_call.params)
        result = tool_def.execute(**params)

        # Depending on implementation, either errors or replaces first occurrence
        # The key test is that it doesn't replace all when replace_all=False
        if not result.success:
            self.assertIn("occurrences", result.error.lower())
        else:
            # If it succeeds, verify it's the first occurrence
            with open(file_path) as f:
                content = f.read()
            self.assertIn("FOO bar foo baz", content)

    def test_edit_with_hallucinated_reason_param(self):
        """Edit with hallucinated 'reason' param → silently stripped, works."""
        file_path = os.path.join(self.temp_dir, "test.txt")
        with open(file_path, "w") as f:
            f.write("old\n")

        response = (
            '{"tool": "Edit", "params": {"path": "' + file_path + '", '
            '"old_string": "old", "new_string": "new", '
            '"reason": "refactoring"}}'
        )
        tool_call = self.parser.parse(f'<tool_call>{response}</tool_call>')

        # The "reason" param is in the parsed params
        self.assertIn("reason", tool_call.params)

        tool_def = self.registry.get_tool("Edit")
        valid, error = tool_def.validate_params(tool_call.params)
        # Should succeed after stripping "reason"
        self.assertTrue(valid)

        params = tool_def.apply_defaults(tool_call.params)
        result = tool_def.execute(**params)

        self.assertTrue(result.success)
        with open(file_path) as f:
            self.assertIn("new", f.read())

    def test_full_roundtrip_write_read_edit_read(self):
        """Full round-trip: Write → Read → Edit → Read again → verify change."""
        file_path = os.path.join(self.temp_dir, "roundtrip.txt")

        # Step 1: Write
        write_response = (
            '{"tool": "Write", "params": {"path": "' + file_path + '", '
            '"content": "original content\\n"}}'
        )
        write_call = self.parser.parse(f'<tool_call>{write_response}</tool_call>')
        write_def = self.registry.get_tool("Write")
        write_result = write_def.execute(**write_def.apply_defaults(write_call.params))
        self.assertTrue(write_result.success)

        # Step 2: Read
        read_response = (
            '{"tool": "Read", "params": {"path": "' + file_path + '"}}'
        )
        read_call = self.parser.parse(f'<tool_call>{read_response}</tool_call>')
        read_def = self.registry.get_tool("Read")
        read_result = read_def.execute(**read_def.apply_defaults(read_call.params))
        self.assertTrue(read_result.success)
        self.assertIn("original", read_result.output)

        # Step 3: Edit
        edit_response = (
            '{"tool": "Edit", "params": {"path": "' + file_path + '", '
            '"old_string": "original", "new_string": "modified"}}'
        )
        edit_call = self.parser.parse(f'<tool_call>{edit_response}</tool_call>')
        edit_def = self.registry.get_tool("Edit")
        edit_result = edit_def.execute(**edit_def.apply_defaults(edit_call.params))
        self.assertTrue(edit_result.success)

        # Step 4: Read again
        read_again = read_def.execute(**read_def.apply_defaults(read_call.params))
        self.assertTrue(read_again.success)
        self.assertIn("modified", read_again.output)
        self.assertNotIn("original", read_again.output)


class TestParseValidateExecuteBash(unittest.TestCase):
    """Test the full pipeline for the Bash tool."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.registry = ToolRegistry(working_dir=self.temp_dir)
        self.parser = ToolCallParser()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_parse_bash_tool_call_execute(self):
        """Parse bash tool call → execute `echo hello` → output contains 'hello'."""
        response = (
            '{"tool": "Bash", "params": {"command": "echo hello"}}'
        )
        tool_call = self.parser.parse(f'<tool_call>{response}</tool_call>')

        self.assertIsNotNone(tool_call)
        self.assertEqual(tool_call.tool_name, "Bash")

        tool_def = self.registry.get_tool("Bash")
        valid, error = tool_def.validate_params(tool_call.params)
        self.assertTrue(valid)

        params = tool_def.apply_defaults(tool_call.params)
        result = tool_def.execute(**params)

        self.assertTrue(result.success)
        self.assertIn("hello", result.output)

    def test_bash_with_timeout_param(self):
        """Bash with timeout param → works."""
        response = (
            '{"tool": "Bash", "params": {"command": "sleep 0.1", "timeout": 5}}'
        )
        tool_call = self.parser.parse(f'<tool_call>{response}</tool_call>')

        self.assertIsNotNone(tool_call)
        self.assertEqual(tool_call.params["timeout"], 5)

        tool_def = self.registry.get_tool("Bash")
        valid, error = tool_def.validate_params(tool_call.params)
        self.assertTrue(valid)

        params = tool_def.apply_defaults(tool_call.params)
        result = tool_def.execute(**params)
        # May succeed or timeout, but should parse correctly
        self.assertIsNotNone(result)

    def test_bash_legacy_format(self):
        """Bash legacy format (```bash block) → still executes through pipeline."""
        response = "```bash\necho legacy\n```"
        tool_call = self.parser.parse(response)

        self.assertIsNotNone(tool_call)
        self.assertEqual(tool_call.tool_name, "Bash")
        self.assertTrue(tool_call.is_legacy)
        self.assertIn("echo legacy", tool_call.params["command"])

        tool_def = self.registry.get_tool("Bash")
        valid, error = tool_def.validate_params(tool_call.params)
        self.assertTrue(valid)

        params = tool_def.apply_defaults(tool_call.params)
        result = tool_def.execute(**params)

        self.assertTrue(result.success)
        self.assertIn("legacy", result.output)

    def test_bash_command_failure(self):
        """Bash command failure (exit code != 0) → ToolResult.success=False."""
        response = (
            '{"tool": "Bash", "params": {"command": "false"}}'
        )
        tool_call = self.parser.parse(f'<tool_call>{response}</tool_call>')

        tool_def = self.registry.get_tool("Bash")
        params = tool_def.apply_defaults(tool_call.params)
        result = tool_def.execute(**params)

        self.assertFalse(result.success)


class TestParseValidateExecuteGlob(unittest.TestCase):
    """Test the full pipeline for the Glob tool."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.registry = ToolRegistry(working_dir=self.temp_dir)
        self.parser = ToolCallParser()
        # Create test files
        for name in ["file1.txt", "file2.txt", "file3.py"]:
            with open(os.path.join(self.temp_dir, name), "w") as f:
                f.write("content")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_glob_finds_matching_files(self):
        """Create temp files → Glob '*.txt' → finds them."""
        response = (
            '{"tool": "Glob", "params": {"pattern": "*.txt", '
            '"path": "' + self.temp_dir + '"}}'
        )
        tool_call = self.parser.parse(f'<tool_call>{response}</tool_call>')

        self.assertIsNotNone(tool_call)

        tool_def = self.registry.get_tool("Glob")
        valid, error = tool_def.validate_params(tool_call.params)
        self.assertTrue(valid)

        params = tool_def.apply_defaults(tool_call.params)
        result = tool_def.execute(**params)

        self.assertTrue(result.success)
        self.assertIn("file1.txt", result.output)
        self.assertIn("file2.txt", result.output)

    def test_glob_no_matches(self):
        """Glob with no matches → success but 'No files matching'."""
        response = (
            '{"tool": "Glob", "params": {"pattern": "*.nonexistent", '
            '"path": "' + self.temp_dir + '"}}'
        )
        tool_call = self.parser.parse(f'<tool_call>{response}</tool_call>')

        tool_def = self.registry.get_tool("Glob")
        params = tool_def.apply_defaults(tool_call.params)
        result = tool_def.execute(**params)

        self.assertTrue(result.success)
        self.assertIn("No files", result.output)

    def test_glob_excludes_pycache(self):
        """Glob should handle __pycache__ appropriately."""
        # Create a __pycache__ directory
        pycache_dir = os.path.join(self.temp_dir, "__pycache__")
        os.makedirs(pycache_dir, exist_ok=True)
        with open(os.path.join(pycache_dir, "test.pyc"), "w") as f:
            f.write("")

        # Glob for *.txt should not include pycache
        response = (
            '{"tool": "Glob", "params": {"pattern": "*.txt", '
            '"path": "' + self.temp_dir + '"}}'
        )
        tool_call = self.parser.parse(f'<tool_call>{response}</tool_call>')

        tool_def = self.registry.get_tool("Glob")
        params = tool_def.apply_defaults(tool_call.params)
        result = tool_def.execute(**params)

        self.assertTrue(result.success)
        self.assertNotIn("__pycache__", result.output)


class TestParseValidateExecuteGrep(unittest.TestCase):
    """Test the full pipeline for the Grep tool."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.registry = ToolRegistry(working_dir=self.temp_dir)
        self.parser = ToolCallParser()
        # Create test file with known content
        self.test_file = os.path.join(self.temp_dir, "search_test.txt")
        with open(self.test_file, "w") as f:
            f.write("def hello():\n    print('hello')\n")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_grep_finds_pattern(self):
        """Create temp file with known content → Grep for pattern → matches found."""
        response = (
            '{"tool": "Grep", "params": {"pattern": "def hello", '
            '"path": "' + self.temp_dir + '"}}'
        )
        tool_call = self.parser.parse(f'<tool_call>{response}</tool_call>')

        self.assertIsNotNone(tool_call)

        tool_def = self.registry.get_tool("Grep")
        valid, error = tool_def.validate_params(tool_call.params)
        self.assertTrue(valid)

        params = tool_def.apply_defaults(tool_call.params)
        result = tool_def.execute(**params)

        self.assertTrue(result.success)
        self.assertIn("def hello", result.output)

    def test_grep_no_matches(self):
        """Grep with no matches → 'No matches'."""
        response = (
            '{"tool": "Grep", "params": {"pattern": "nonexistent_pattern", '
            '"path": "' + self.temp_dir + '"}}'
        )
        tool_call = self.parser.parse(f'<tool_call>{response}</tool_call>')

        tool_def = self.registry.get_tool("Grep")
        params = tool_def.apply_defaults(tool_call.params)
        result = tool_def.execute(**params)

        self.assertTrue(result.success)
        self.assertIn("No matches", result.output)

    def test_grep_invalid_regex(self):
        """Grep with invalid regex → error."""
        response = (
            '{"tool": "Grep", "params": {"pattern": "[invalid(regex", '
            '"path": "' + self.temp_dir + '"}}'
        )
        tool_call = self.parser.parse(f'<tool_call>{response}</tool_call>')

        tool_def = self.registry.get_tool("Grep")
        valid, error = tool_def.validate_params(tool_call.params)
        self.assertTrue(valid)  # Validation passes (pattern is just a string)

        params = tool_def.apply_defaults(tool_call.params)
        result = tool_def.execute(**params)

        # Should fail during regex execution
        self.assertFalse(result.success)


class TestParseValidateExecuteLS(unittest.TestCase):
    """Test the full pipeline for the LS tool."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.registry = ToolRegistry(working_dir=self.temp_dir)
        self.parser = ToolCallParser()
        # Create test files
        with open(os.path.join(self.temp_dir, "file1.txt"), "w") as f:
            f.write("content")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_ls_lists_files_with_sizes(self):
        """Create temp files → LS → lists them with sizes."""
        response = (
            '{"tool": "LS", "params": {"path": "' + self.temp_dir + '"}}'
        )
        tool_call = self.parser.parse(f'<tool_call>{response}</tool_call>')

        self.assertIsNotNone(tool_call)

        tool_def = self.registry.get_tool("LS")
        valid, error = tool_def.validate_params(tool_call.params)
        self.assertTrue(valid)

        params = tool_def.apply_defaults(tool_call.params)
        result = tool_def.execute(**params)

        self.assertTrue(result.success)
        self.assertIn("file1.txt", result.output)

    def test_ls_nonexistent_dir(self):
        """LS on non-existent dir → error."""
        response = (
            '{"tool": "LS", "params": {"path": "/nonexistent/dir"}}'
        )
        tool_call = self.parser.parse(f'<tool_call>{response}</tool_call>')

        tool_def = self.registry.get_tool("LS")
        params = tool_def.apply_defaults(tool_call.params)
        result = tool_def.execute(**params)

        self.assertFalse(result.success)


class TestUnknownToolHandling(unittest.TestCase):
    """Test handling of unknown or invalid tools."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.registry = ToolRegistry(working_dir=self.temp_dir)
        self.parser = ToolCallParser()
        self.loop = AgenticLoop(self.registry)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_unknown_tool_name_returns_error(self):
        """Parse a tool call with unknown tool name → AgenticLoop._execute returns error."""
        response = (
            '{"tool": "UnknownTool", "params": {"param": "value"}}'
        )
        tool_call = self.parser.parse(f'<tool_call>{response}</tool_call>')

        self.assertIsNotNone(tool_call)
        self.assertEqual(tool_call.tool_name, "UnknownTool")

        # Execute through AgenticLoop
        result = self.loop._execute(tool_call)

        self.assertFalse(result.success)
        self.assertIn("Unknown tool", result.error)

    def test_tool_name_case_insensitive_lookup(self):
        """Tool name case mismatch → case-insensitive lookup finds it."""
        response = (
            '{"tool": "read", "params": {"path": "/tmp/test.txt"}}'
        )
        tool_call = self.parser.parse(f'<tool_call>{response}</tool_call>')

        self.assertIsNotNone(tool_call)
        self.assertEqual(tool_call.tool_name, "read")

        # Registry lookup should be case-insensitive
        tool_def = self.registry.get_tool("read")
        self.assertIsNotNone(tool_def)
        self.assertEqual(tool_def.name, "Read")

    def test_completely_invalid_tool_clear_error(self):
        """Completely invalid tool → clear error message."""
        response = (
            '{"tool": "InvalidToolXYZ", "params": {}}'
        )
        tool_call = self.parser.parse(f'<tool_call>{response}</tool_call>')

        tool_def = self.registry.get_tool("InvalidToolXYZ")
        self.assertIsNone(tool_def)

        result = self.loop._execute(tool_call)
        self.assertFalse(result.success)
        self.assertIn("InvalidToolXYZ", result.error)


class TestToolCallDisplayStripping(unittest.TestCase):
    """Test the regex patterns used in telegram_bot.py for stripping tool_call."""

    def setUp(self):
        # These are the actual patterns used in telegram_bot.py
        self.pattern_full = re.compile(r'<tool_call>.*?</tool_call>', re.DOTALL)
        self.pattern_partial = re.compile(r'</?tool_call>')

    def test_strip_single_tool_call_block_from_middle(self):
        """Strip single tool_call block from middle of text."""
        text = (
            "I will read the file.\n"
            '<tool_call>{"tool": "Read", "params": {"path": "/tmp/test.txt"}}</tool_call>\n'
            "Please wait."
        )
        result = self.pattern_full.sub('', text).strip()
        self.assertIn("I will read the file.", result)
        self.assertIn("Please wait.", result)
        self.assertNotIn("<tool_call>", result)

    def test_strip_tool_call_at_end(self):
        """Strip tool_call at end of text."""
        text = (
            "Reading file now.\n"
            '<tool_call>{"tool": "Read", "params": {"path": "/tmp/test.txt"}}</tool_call>'
        )
        result = self.pattern_full.sub('', text).strip()
        self.assertEqual(result, "Reading file now.")
        self.assertNotIn("<tool_call>", result)

    def test_strip_tool_call_at_beginning(self):
        """Strip tool_call at beginning of text."""
        text = (
            '<tool_call>{"tool": "Read", "params": {"path": "/tmp/test.txt"}}</tool_call>\n'
            "Now processing."
        )
        result = self.pattern_full.sub('', text).strip()
        self.assertEqual(result, "Now processing.")

    def test_strip_multiple_tool_call_blocks(self):
        """Strip multiple tool_call blocks."""
        text = (
            'Text before\n'
            '<tool_call>{"tool": "Read", "params": {"path": "/tmp/1.txt"}}</tool_call>\n'
            'Text between\n'
            '<tool_call>{"tool": "Write", "params": {"path": "/tmp/2.txt", "content": "hello"}}</tool_call>\n'
            'Text after'
        )
        result = self.pattern_full.sub('', text).strip()
        self.assertIn("Text before", result)
        self.assertIn("Text between", result)
        self.assertIn("Text after", result)
        self.assertEqual(result.count("<tool_call>"), 0)

    def test_strip_nested_malformed_tool_call(self):
        """Strip nested/malformed tool_call (leftover closing tag)."""
        text = (
            'Processing.\n'
            '<tool_call>{"tool": "Bash", "params": {"command": "ls"}}</tool_call>\n'
            '</tool_call>\n'
            'Done.'
        )
        # First pass: remove complete blocks
        result = self.pattern_full.sub('', text)
        # Second pass: remove partial tags
        result = self.pattern_partial.sub('', result).strip()
        self.assertNotIn("<tool_call>", result)
        self.assertNotIn("</tool_call>", result)
        self.assertIn("Processing.", result)
        self.assertIn("Done.", result)

    def test_strip_leaves_surrounding_text_intact(self):
        """Strip leaves surrounding text intact."""
        text = (
            "You asked for help.\n"
            '<tool_call>{"tool": "Read", "params": {"path": "file.txt"}}</tool_call>\n'
            "I will provide it."
        )
        result = self.pattern_full.sub('', text).strip()
        self.assertIn("You asked for help.", result)
        self.assertIn("I will provide it.", result)

    def test_strip_xml_wrapped_format_inside_tool_call(self):
        """Strip XML-wrapped format inside tool_call."""
        text = (
            "Reading now.\n"
            '<tool_call>\n'
            '<Read>\n'
            '{"path": "/tmp/test.txt"}\n'
            '</Read>\n'
            '</tool_call>\n'
            "Done."
        )
        result = self.pattern_full.sub('', text).strip()
        self.assertIn("Reading now.", result)
        self.assertIn("Done.", result)
        self.assertNotIn("<tool_call>", result)
        self.assertNotIn("<Read>", result)

    def test_no_tool_call_text_unchanged(self):
        """No tool_call → text unchanged."""
        text = "Just normal text without any tool calls."
        result = self.pattern_full.sub('', text)
        self.assertEqual(result, text)


class TestFullConversationRoundTrip(unittest.TestCase):
    """Test full conversation turn with tool execution."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.registry = ToolRegistry(working_dir=self.temp_dir)
        self.parser = ToolCallParser()
        # Create a test file
        self.test_file = os.path.join(self.temp_dir, "test.txt")
        with open(self.test_file, "w") as f:
            f.write("test content\n")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_llm_output_parse_strip_execute_format(self):
        """LLM outputs response with tool_call → parse → strip → execute → format result."""
        # Simulate LLM output with Chinese text and tool call
        llm_output = (
            "让我读一下文件。\n"
            '<tool_call>{"tool": "Read", "params": {"path": "' + self.test_file + '"}}</tool_call>'
        )

        # Parse tool call
        tool_call = self.parser.parse(llm_output)
        self.assertIsNotNone(tool_call)

        # Strip tool_call from display
        display_text = llm_output.replace(tool_call.raw, "").strip()
        self.assertIn("让我读一下文件", display_text)
        self.assertNotIn("<tool_call>", display_text)

        # Execute tool
        tool_def = self.registry.get_tool(tool_call.tool_name)
        params = tool_def.apply_defaults(tool_call.params)
        result = tool_def.execute(**params)

        self.assertTrue(result.success)
        self.assertIn("test content", result.output)

        # Format result
        formatted = format_tool_result(tool_call, result)
        self.assertIn("<tool_result>", formatted)
        self.assertIn("</tool_result>", formatted)
        self.assertIn("tool: Read", formatted)
        self.assertIn("status: OK", formatted)

    def test_full_roundtrip_with_multiple_steps(self):
        """Simulate multi-step conversation: Read → Edit → Read again."""
        # Step 1: LLM says "I'll read the file"
        llm_output_1 = (
            "让我先读一下文件内容。\n"
            '<tool_call>{"tool": "Read", "params": {"path": "' + self.test_file + '"}}</tool_call>'
        )
        tool_call_1 = self.parser.parse(llm_output_1)
        self.assertIsNotNone(tool_call_1)

        tool_def_1 = self.registry.get_tool(tool_call_1.tool_name)
        result_1 = tool_def_1.execute(**tool_def_1.apply_defaults(tool_call_1.params))
        self.assertTrue(result_1.success)
        formatted_1 = format_tool_result(tool_call_1, result_1)

        # Step 2: LLM says "I'll edit the file"
        llm_output_2 = (
            "现在我来修改文件。\n"
            '<tool_call>{"tool": "Edit", "params": {"path": "' + self.test_file + '", '
            '"old_string": "test content", "new_string": "modified content"}}</tool_call>'
        )
        tool_call_2 = self.parser.parse(llm_output_2)
        self.assertIsNotNone(tool_call_2)

        tool_def_2 = self.registry.get_tool(tool_call_2.tool_name)
        result_2 = tool_def_2.execute(**tool_def_2.apply_defaults(tool_call_2.params))
        self.assertTrue(result_2.success)
        formatted_2 = format_tool_result(tool_call_2, result_2)

        # Step 3: LLM verifies the change by reading again
        llm_output_3 = (
            "让我验证修改是否成功。\n"
            '<tool_call>{"tool": "Read", "params": {"path": "' + self.test_file + '"}}</tool_call>'
        )
        tool_call_3 = self.parser.parse(llm_output_3)
        self.assertIsNotNone(tool_call_3)

        tool_def_3 = self.registry.get_tool(tool_call_3.tool_name)
        result_3 = tool_def_3.execute(**tool_def_3.apply_defaults(tool_call_3.params))
        self.assertTrue(result_3.success)
        self.assertIn("modified content", result_3.output)


if __name__ == "__main__":
    unittest.main()
