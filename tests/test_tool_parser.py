"""Tests for the structured tool call parser (Phase 2).

Tests cover:
- Structured format parsing (<tool_call>...</tool_call>)
- Legacy bash block parsing (```bash ... ```)
- Structured takes priority over legacy
- Malformed JSON handling
- Missing fields
- Hallucination detection
- Comment-only blocks
- ToolCall preview strings
- format_tool_result()
- Content filter suppression of <tool_call> blocks
"""

import os
import sys
import re
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.tool_parser import ToolCallParser, ToolCall, format_tool_result
from agent.tools import ToolResult


class TestToolCallParserStructured(unittest.TestCase):
    """Test parsing of <tool_call> structured format."""

    def setUp(self):
        self.parser = ToolCallParser()

    def test_basic_read(self):
        response = 'Let me read that file.\n\n<tool_call>\n{"tool": "Read", "params": {"path": "src/main.py"}}\n</tool_call>'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertEqual(tc.tool_name, "Read")
        self.assertEqual(tc.params["path"], "src/main.py")
        self.assertFalse(tc.is_legacy)

    def test_bash_command(self):
        response = '<tool_call>\n{"tool": "Bash", "params": {"command": "ls -la"}}\n</tool_call>'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertEqual(tc.tool_name, "Bash")
        self.assertEqual(tc.params["command"], "ls -la")

    def test_edit_with_multiline_strings(self):
        response = '<tool_call>\n{"tool": "Edit", "params": {"path": "x.py", "old_string": "def foo():\\n    pass", "new_string": "def foo():\\n    return 42"}}\n</tool_call>'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertEqual(tc.tool_name, "Edit")

    def test_grep_with_multiple_params(self):
        response = '<tool_call>\n{"tool": "Grep", "params": {"pattern": "TODO", "file_type": "py", "case_insensitive": true}}\n</tool_call>'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertEqual(tc.params["pattern"], "TODO")
        self.assertEqual(tc.params["file_type"], "py")
        self.assertTrue(tc.params["case_insensitive"])

    def test_missing_params_key(self):
        """Missing params defaults to empty dict."""
        response = '<tool_call>\n{"tool": "LS"}\n</tool_call>'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertEqual(tc.tool_name, "LS")
        self.assertEqual(tc.params, {})

    def test_malformed_json(self):
        response = '<tool_call>\n{not valid json}\n</tool_call>'
        tc = self.parser.parse(response)
        self.assertIsNone(tc)

    def test_missing_tool_name(self):
        response = '<tool_call>\n{"params": {"path": "x"}}\n</tool_call>'
        tc = self.parser.parse(response)
        self.assertIsNone(tc)

    def test_empty_tool_name(self):
        response = '<tool_call>\n{"tool": "", "params": {}}\n</tool_call>'
        tc = self.parser.parse(response)
        self.assertIsNone(tc)

    def test_tool_name_not_string(self):
        response = '<tool_call>\n{"tool": 42, "params": {}}\n</tool_call>'
        tc = self.parser.parse(response)
        self.assertIsNone(tc)

    def test_params_not_dict(self):
        response = '<tool_call>\n{"tool": "Bash", "params": "invalid"}\n</tool_call>'
        tc = self.parser.parse(response)
        self.assertIsNone(tc)

    def test_data_not_dict(self):
        response = '<tool_call>\n["not", "a", "dict"]\n</tool_call>'
        tc = self.parser.parse(response)
        self.assertIsNone(tc)

    def test_whitespace_tolerance(self):
        """Extra whitespace around JSON should be fine."""
        response = '<tool_call>   \n  {"tool": "Read", "params": {"path": "x"}}  \n  </tool_call>'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertEqual(tc.tool_name, "Read")

    def test_only_first_tool_call(self):
        """Should only parse the first tool call."""
        response = (
            '<tool_call>\n{"tool": "Read", "params": {"path": "a.py"}}\n</tool_call>\n'
            '<tool_call>\n{"tool": "Read", "params": {"path": "b.py"}}\n</tool_call>'
        )
        tc = self.parser.parse(response)
        self.assertEqual(tc.params["path"], "a.py")


class TestToolCallParserLegacy(unittest.TestCase):
    """Test parsing of legacy ```bash code blocks."""

    def setUp(self):
        self.parser = ToolCallParser()

    def test_basic_bash(self):
        response = 'Let me check:\n\n```bash\nls -la src/\n```'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertEqual(tc.tool_name, "Bash")
        self.assertEqual(tc.params["command"], "ls -la src/")
        self.assertTrue(tc.is_legacy)

    def test_shell_tag(self):
        response = '```shell\ngit status\n```'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertEqual(tc.params["command"], "git status")

    def test_sh_tag(self):
        response = '```sh\npwd\n```'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)

    def test_console_tag(self):
        response = '```console\necho hello\n```'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)

    def test_empty_block(self):
        response = '```bash\n\n```'
        tc = self.parser.parse(response)
        self.assertIsNone(tc)

    def test_comment_only_block(self):
        response = '```bash\n# This is just a comment\n```'
        tc = self.parser.parse(response)
        self.assertIsNone(tc)

    def test_hallucinated_output(self):
        """Block followed by untagged code block = hallucinated output."""
        response = '```bash\nls\n```\n```\nfile1.txt\nfile2.txt\n```'
        tc = self.parser.parse(response)
        self.assertIsNone(tc)

    def test_multiline_command(self):
        response = '```bash\ncd src\npython3 -m pytest tests/\n```'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertIn("cd src", tc.params["command"])
        self.assertIn("pytest", tc.params["command"])

    def test_python_block_parsed_as_fallback(self):
        """Python code blocks should be parsed as Bash fallback (python3 heredoc)."""
        response = '```python\nprint("hello")\n```'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertEqual(tc.tool_name, "Bash")
        self.assertIn("python3", tc.params["command"])
        self.assertIn('print("hello")', tc.params["command"])
        self.assertTrue(tc.is_legacy)

    def test_python_comment_only_block_ignored(self):
        """Python blocks with only comments should be skipped."""
        response = '```python\n# This is just a comment\n# Another comment\n```'
        tc = self.parser.parse(response)
        self.assertIsNone(tc)


class TestStructuredTakesPriority(unittest.TestCase):
    """Test that structured format takes priority over legacy."""

    def setUp(self):
        self.parser = ToolCallParser()

    def test_structured_over_legacy(self):
        """When both formats present, structured wins."""
        response = (
            '```bash\nls\n```\n\n'
            '<tool_call>\n{"tool": "Read", "params": {"path": "main.py"}}\n</tool_call>'
        )
        tc = self.parser.parse(response)
        self.assertEqual(tc.tool_name, "Read")
        self.assertFalse(tc.is_legacy)

    def test_fallback_to_legacy(self):
        """When only legacy present, use it."""
        response = '```bash\ngit log --oneline -5\n```'
        tc = self.parser.parse(response)
        self.assertEqual(tc.tool_name, "Bash")
        self.assertTrue(tc.is_legacy)

    def test_no_tool_call(self):
        """Plain text with no tool calls."""
        response = "The issue is in the authentication module. Let me explain..."
        tc = self.parser.parse(response)
        self.assertIsNone(tc)


class TestToolCallPreview(unittest.TestCase):
    def test_bash_preview(self):
        tc = ToolCall("Bash", {"command": "python3 -m pytest tests/ -v --timeout=60"}, "")
        preview = tc.preview()
        self.assertIn("pytest", preview)
        self.assertTrue(len(preview) <= 60)

    def test_read_preview(self):
        tc = ToolCall("Read", {"path": "src/main.py"}, "")
        preview = tc.preview()
        self.assertIn("Read", preview)
        self.assertIn("src/main.py", preview)

    def test_long_preview_truncated(self):
        tc = ToolCall("Bash", {"command": "a" * 100}, "")
        preview = tc.preview(max_len=30)
        self.assertTrue(len(preview) <= 30)

    def test_empty_params_preview(self):
        tc = ToolCall("LS", {}, "")
        preview = tc.preview()
        self.assertIn("LS", preview)


class TestStripToolCall(unittest.TestCase):
    def setUp(self):
        self.parser = ToolCallParser()

    def test_strip_structured(self):
        raw = '<tool_call>\n{"tool": "Read", "params": {"path": "x"}}\n</tool_call>'
        response = f"Let me read that.\n\n{raw}\n\nMore text."
        tc = self.parser.parse(response)
        stripped = self.parser.strip_tool_call(response, tc)
        self.assertNotIn("<tool_call>", stripped)
        self.assertIn("Let me read that", stripped)

    def test_strip_legacy(self):
        raw = '```bash\nls\n```'
        response = f"Checking:\n\n{raw}"
        tc = self.parser.parse(response)
        stripped = self.parser.strip_tool_call(response, tc)
        self.assertNotIn("```bash", stripped)
        self.assertIn("Checking:", stripped)


class TestFormatToolResult(unittest.TestCase):
    def test_success_result(self):
        tc = ToolCall("Read", {"path": "main.py"}, "")
        result = ToolResult(True, output="# main.py (10 lines)\n     1\timport os")
        formatted = format_tool_result(tc, result)
        self.assertIn("<tool_result>", formatted)
        self.assertIn("tool: Read", formatted)
        self.assertIn("status: OK", formatted)
        self.assertIn("import os", formatted)
        self.assertIn("</tool_result>", formatted)

    def test_error_result(self):
        tc = ToolCall("Bash", {"command": "invalid_cmd"}, "")
        result = ToolResult(False, error="command not found", output="")
        formatted = format_tool_result(tc, result)
        self.assertIn("status: ERROR", formatted)
        self.assertIn("STDERR: command not found", formatted)

    def test_metadata_included(self):
        tc = ToolCall("Read", {"path": "x.py"}, "")
        result = ToolResult(True, output="content", metadata={"lines_read": 42})
        formatted = format_tool_result(tc, result)
        self.assertIn("metadata:", formatted)
        self.assertIn("42", formatted)

    def test_no_output(self):
        tc = ToolCall("Bash", {"command": "true"}, "")
        result = ToolResult(True, output="")
        formatted = format_tool_result(tc, result)
        self.assertIn("(no output)", formatted)

    def test_output_truncated(self):
        tc = ToolCall("Bash", {"command": "cat big"}, "")
        result = ToolResult(True, output="x" * 5000)
        formatted = format_tool_result(tc, result)
        # Should be truncated at 3000 chars
        output_section = formatted.split("output: |")[1].split("</tool_result>")[0]
        self.assertTrue(len(output_section) < 4000)


# ── Content Filter Tests ──────────────────────────────────────────────────────

class TestContentFilterToolCallSuppression(unittest.TestCase):
    """Test that _CodeFenceFilter suppresses <tool_call> blocks."""

    def _make_filter(self):
        # Import the nested class
        from cli.neomind_interface import NeoMindInterface
        return NeoMindInterface._CodeFenceFilter()

    def test_suppress_tool_call(self):
        f = self._make_filter()
        text = 'Some prose.\n\n<tool_call>\n{"tool": "Read", "params": {"path": "x"}}\n</tool_call>\n'
        output = f.write(text) + f.flush()
        self.assertNotIn("<tool_call>", output)
        self.assertNotIn("Read", output)
        self.assertIn("Some prose", output)

    def test_suppress_bash_fence(self):
        """Existing bash fence suppression still works."""
        f = self._make_filter()
        text = 'Hello.\n\n```bash\nls -la\n```\n'
        output = f.write(text) + f.flush()
        self.assertNotIn("```bash", output)
        self.assertNotIn("ls -la", output)
        self.assertIn("Hello", output)

    def test_both_formats_suppressed(self):
        f = self._make_filter()
        text = (
            'Prose 1.\n\n```bash\nls\n```\n\n'
            'Prose 2.\n\n<tool_call>\n{"tool": "Read", "params": {}}\n</tool_call>\n'
        )
        output = f.write(text) + f.flush()
        self.assertNotIn("```bash", output)
        self.assertNotIn("<tool_call>", output)
        self.assertIn("Prose 1", output)
        self.assertIn("Prose 2", output)

    def test_streaming_tool_call(self):
        """Test tool_call suppression when streamed character by character."""
        f = self._make_filter()
        text = 'Hi.\n<tool_call>\n{"tool": "LS"}\n</tool_call>\nDone.'
        output = ""
        for ch in text:
            output += f.write(ch)
        output += f.flush()
        self.assertNotIn("<tool_call>", output)
        self.assertIn("Hi", output)

    def test_pass_through_normal_text(self):
        f = self._make_filter()
        text = "This is just normal text with no tool calls at all."
        output = f.write(text) + f.flush()
        self.assertEqual(output, text)

    def test_python_block_suppressed(self):
        """Python blocks are now suppressed (LLM fallback support)."""
        f = self._make_filter()
        text = 'Before\n```python\nprint("hello")\n```\nAfter'
        output = f.write(text) + f.flush()
        self.assertNotIn("print", output)
        self.assertIn("Before", output)
        self.assertIn("After", output)


if __name__ == "__main__":
    unittest.main()
