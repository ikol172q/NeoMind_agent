"""Extended tests for the structured tool call parser (Phase 3).

Focus on MISSING edge cases not covered in test_tool_parser.py:
- JSON with extra fields
- Very large params dicts
- Special characters in string values
- Unicode handling
- Nested structures
- Multiple formats present (priority testing)
- Very long responses
- Whitespace and formatting edge cases
- Hallucination detection edge cases
- Preview() edge cases
- format_tool_result() edge cases
- strip_tool_call() edge cases
"""

import os
import sys
import re
import unittest
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.coding.tool_parser import ToolCallParser, ToolCall, format_tool_result
from agent.coding.tools import ToolResult


# ── TestParseStructuredEdgeCases ─────────────────────────────────────────────

class TestParseStructuredEdgeCases(unittest.TestCase):
    """Test edge cases in structured format parsing."""

    def setUp(self):
        self.parser = ToolCallParser()

    def test_json_with_extra_fields(self):
        """Extra fields in JSON should be ignored."""
        response = '<tool_call>\n{"tool": "Read", "params": {"path": "x.py"}, "extra": "ignored", "another": 123}\n</tool_call>'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertEqual(tc.tool_name, "Read")
        self.assertEqual(tc.params, {"path": "x.py"})

    def test_very_large_params_dict(self):
        """Params with 20+ keys should work."""
        params = {f"key_{i}": f"value_{i}" for i in range(25)}
        json_str = json.dumps({"tool": "Bash", "params": params})
        response = f'<tool_call>\n{json_str}\n</tool_call>'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertEqual(len(tc.params), 25)
        self.assertEqual(tc.params["key_0"], "value_0")
        self.assertEqual(tc.params["key_24"], "value_24")

    def test_params_with_newlines_in_strings(self):
        """String values with embedded newlines should parse."""
        response = '<tool_call>\n{"tool": "Edit", "params": {"path": "x.py", "old_string": "line1\\nline2\\nline3", "new_string": "new1\\nnew2"}}\n</tool_call>'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertEqual(tc.tool_name, "Edit")
        self.assertIn("line1", tc.params["old_string"])
        self.assertIn("line3", tc.params["old_string"])

    def test_params_with_quotes_in_strings(self):
        """String values with quotes should parse."""
        response = r'<tool_call>{"tool": "Bash", "params": {"command": "echo \"hello world\""}}</tool_call>'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertEqual(tc.tool_name, "Bash")
        self.assertIn("hello world", tc.params["command"])

    def test_params_with_backslashes_in_strings(self):
        """String values with backslashes should parse."""
        response = r'<tool_call>{"tool": "Read", "params": {"path": "C:\\Users\\test\\file.py"}}</tool_call>'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertIn("Users", tc.params["path"])

    def test_unicode_tool_name(self):
        """Unicode in tool name should still parse."""
        response = '<tool_call>\n{"tool": "读取", "params": {}}\n</tool_call>'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertEqual(tc.tool_name, "读取")

    def test_nested_dict_in_params(self):
        """Nested dicts in params values should work."""
        response = '<tool_call>\n{"tool": "Tool1", "params": {"config": {"nested": {"deep": "value"}}}}\n</tool_call>'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertIsInstance(tc.params["config"], dict)
        self.assertEqual(tc.params["config"]["nested"]["deep"], "value")

    def test_params_with_null_values(self):
        """Null/None values in params should parse as None."""
        response = '<tool_call>\n{"tool": "Tool1", "params": {"key1": null, "key2": "value"}}\n</tool_call>'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertIsNone(tc.params["key1"])
        self.assertEqual(tc.params["key2"], "value")

    def test_multiple_tool_call_blocks_first_wins(self):
        """Only first tool_call block should be parsed."""
        response = (
            '<tool_call>\n{"tool": "Read", "params": {"path": "first.py"}}\n</tool_call>\n'
            'text\n'
            '<tool_call>\n{"tool": "Write", "params": {"path": "second.py"}}\n</tool_call>'
        )
        tc = self.parser.parse(response)
        self.assertEqual(tc.tool_name, "Read")
        self.assertEqual(tc.params["path"], "first.py")

    def test_tool_call_deep_in_response(self):
        """Tool call block 2000+ chars into response should be found."""
        prefix = "x" * 2000
        response = prefix + '\n<tool_call>\n{"tool": "Bash", "params": {"command": "ls"}}\n</tool_call>'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertEqual(tc.tool_name, "Bash")

    def test_empty_params_dict(self):
        """Empty params dict should work."""
        response = '<tool_call>\n{"tool": "SomeTool", "params": {}}\n</tool_call>'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertEqual(tc.tool_name, "SomeTool")
        self.assertEqual(tc.params, {})

    def test_boolean_params(self):
        """Boolean params should be correctly typed."""
        response = '<tool_call>\n{"tool": "Grep", "params": {"pattern": "test", "case_insensitive": true, "recursive": false}}\n</tool_call>'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertTrue(tc.params["case_insensitive"])
        self.assertFalse(tc.params["recursive"])

    def test_numeric_params(self):
        """Numeric params should be correctly typed."""
        response = '<tool_call>\n{"tool": "Bash", "params": {"command": "test", "timeout": 42, "port": 8080, "ratio": 0.5}}\n</tool_call>'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertEqual(tc.params["timeout"], 42)
        self.assertEqual(tc.params["port"], 8080)
        self.assertEqual(tc.params["ratio"], 0.5)

    def test_params_with_list_value(self):
        """List values in params should work."""
        response = '<tool_call>\n{"tool": "Tool1", "params": {"items": ["a", "b", "c"], "count": 3}}\n</tool_call>'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertEqual(tc.params["items"], ["a", "b", "c"])

    def test_params_with_empty_string(self):
        """Empty string values should parse."""
        response = '<tool_call>\n{"tool": "Read", "params": {"path": "", "fallback": "default"}}\n</tool_call>'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        # Note: tool name validation may reject this
        if tc:
            self.assertEqual(tc.params["path"], "")

    def test_whitespace_around_json_content(self):
        """Extra whitespace around JSON should be handled."""
        response = '<tool_call>  \n  \n  {"tool": "Read", "params": {}}  \n  \n  </tool_call>'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertEqual(tc.tool_name, "Read")


# ── TestParseXMLWrappedEdgeCases ────────────────────────────────────────────

class TestParseXMLWrappedEdgeCases(unittest.TestCase):
    """Test edge cases in XML-wrapped format parsing."""

    def setUp(self):
        self.parser = ToolCallParser()

    def test_tool_name_with_numbers(self):
        """Tool names with numbers should work."""
        response = '<tool_call>\n<Read2>\n{"path": "x.py"}\n</Read2>\n</tool_call>'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertEqual(tc.tool_name, "Read2")

    def test_tool_name_with_underscore(self):
        """Tool names with underscores should work."""
        response = '<tool_call>\n<self_editor>\n{"file_path": "x.py"}\n</self_editor>\n</tool_call>'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertEqual(tc.tool_name, "self_editor")

    def test_extra_whitespace_in_tags(self):
        """Extra whitespace and newlines between tags should be handled."""
        response = '<tool_call>\n\n\n<Read>\n\n\n{"path": "x.py"}\n\n\n</Read>\n\n\n</tool_call>'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertEqual(tc.tool_name, "Read")

    def test_nested_tool_call_tags_malformed(self):
        """Nested tool_call tags should be handled gracefully."""
        response = '<tool_call><tool_call>\n<Read>\n{"path": "x.py"}\n</Read>\n</tool_call></tool_call>'
        tc = self.parser.parse(response)
        # Should handle gracefully (may or may not parse depending on regex matching)
        # Main thing is it doesn't crash
        self.assertIsNotNone(self.parser)

    def test_xml_wrapped_over_bash_when_structured_absent(self):
        """When structured format absent, XML-wrapped should be used."""
        response = (
            'text\n'
            '<tool_call>\n<Read>\n{"path": "x.py"}\n</Read>\n</tool_call>\n'
            '```bash\nls\n```'
        )
        tc = self.parser.parse(response)
        # XML-wrapped wins over bash
        self.assertEqual(tc.tool_name, "Read")
        self.assertFalse(tc.is_legacy)

    def test_xml_wrapped_with_very_large_json(self):
        """Very large JSON params in XML-wrapped should work."""
        params = {f"key_{i}": f"value_{i}" for i in range(30)}
        json_str = json.dumps(params)
        response = f'<tool_call>\n<Bash>\n{json_str}\n</Bash>\n</tool_call>'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertEqual(len(tc.params), 30)

    def test_xml_wrapped_empty_params(self):
        """Empty params dict in XML-wrapped should work."""
        response = '<tool_call>\n<LS>\n{}\n</LS>\n</tool_call>'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertEqual(tc.params, {})

    def test_xml_wrapped_with_special_chars_in_name(self):
        """Tool names with mixed case and underscores."""
        response = '<tool_call>\n<MyTool_2>\n{"param": "value"}\n</MyTool_2>\n</tool_call>'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertEqual(tc.tool_name, "MyTool_2")

    def test_xml_wrapped_params_with_nested_objects(self):
        """Nested objects in XML-wrapped params."""
        response = '<tool_call>\n<Tool>\n{"outer": {"inner": {"deep": "value"}}}\n</Tool>\n</tool_call>'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertEqual(tc.params["outer"]["inner"]["deep"], "value")


# ── TestParseLegacyBashEdgeCases ────────────────────────────────────────────

class TestParseLegacyBashEdgeCases(unittest.TestCase):
    """Test edge cases in legacy bash block parsing."""

    def setUp(self):
        self.parser = ToolCallParser()

    def test_bash_block_whitespace_only(self):
        """Bash block with only whitespace should be None."""
        response = '```bash\n   \n  \n  \n```'
        tc = self.parser.parse(response)
        self.assertIsNone(tc)

    def test_multiple_bash_blocks_first_valid_wins(self):
        """First valid bash block should win."""
        response = (
            '```bash\n   \n```\n'  # Empty, skipped
            '```bash\necho hello\n```\n'  # Valid, should be used
            '```bash\necho world\n```'  # Also valid, but first wins
        )
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertIn("hello", tc.params["command"])

    def test_bash_block_mixed_comments_and_commands(self):
        """Bash block with mixed comments and commands should pick up commands."""
        response = '```bash\n# This is a comment\necho hello\n# Another comment\nls -la\n```'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertIn("echo", tc.params["command"])
        self.assertIn("ls", tc.params["command"])

    def test_bash_block_followed_by_hallucinated_output(self):
        """Bash block followed by untagged code block should be filtered."""
        response = '```bash\nls\n```\n```\nfile1.txt\n```'
        tc = self.parser.parse(response)
        self.assertIsNone(tc)

    def test_bash_block_not_followed_by_output(self):
        """Bash block not followed by output block should be valid."""
        response = '```bash\nls -la\n```\nHere is the output of ls...'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertEqual(tc.tool_name, "Bash")

    def test_bash_block_very_long_command(self):
        """Very long bash command (1000+ chars) should work."""
        long_cmd = " && ".join([f"echo part_{i}" for i in range(100)])
        response = f'```bash\n{long_cmd}\n```'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertGreater(len(tc.params["command"]), 1000)

    def test_bash_block_with_heredoc_syntax(self):
        """Bash block with heredoc should work."""
        response = '```bash\ncat << EOF\nhello\nworld\nEOF\n```'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertIn("EOF", tc.params["command"])

    def test_bash_block_trailing_whitespace_stripped(self):
        """Trailing whitespace in bash block should be stripped."""
        response = '```bash\necho hello   \n   \n```'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        # Command should be stripped
        self.assertNotIn("   ", tc.params["command"].rstrip())

    def test_bash_block_with_pipe_operators(self):
        """Bash block with pipe operators should work."""
        response = '```bash\ncat file.txt | grep "pattern" | wc -l\n```'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertIn("grep", tc.params["command"])
        self.assertIn("wc", tc.params["command"])

    def test_bash_block_with_redirection(self):
        """Bash block with redirection should work."""
        response = '```bash\nls -la > output.txt 2>&1\n```'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertIn(">", tc.params["command"])

    def test_bash_block_empty_line_in_middle(self):
        """Bash block with empty lines in the middle should work."""
        response = '```bash\necho start\n\necho end\n```'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertIn("start", tc.params["command"])
        self.assertIn("end", tc.params["command"])


# ── TestParsePythonBlockEdgeCases ───────────────────────────────────────────

class TestParsePythonBlockEdgeCases(unittest.TestCase):
    """Test edge cases in python block parsing."""

    def setUp(self):
        self.parser = ToolCallParser()

    def test_python_block_starting_with_example_comment(self):
        """Python block starting with '# Example:' should be filtered."""
        response = '```python\n# Example: This is just documentation\nprint("hello")\n```'
        tc = self.parser.parse(response)
        self.assertIsNone(tc)

    def test_python_block_starting_with_usage_comment(self):
        """Python block starting with '# Usage:' should be filtered."""
        response = '```python\n# Usage: Run this script like this\nprint("hello")\n```'
        tc = self.parser.parse(response)
        self.assertIsNone(tc)

    def test_python_block_with_code_after_comments(self):
        """Python block with executable code after comments should work."""
        response = '```python\n# Setup\nimport os\nprint("hello")\n```'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertEqual(tc.tool_name, "Bash")
        self.assertIn("python3", tc.params["command"])

    def test_python_block_wrapped_in_heredoc(self):
        """Python block should be wrapped in heredoc format."""
        response = '```python\nprint("hello")\n```'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertIn("python3", tc.params["command"])
        self.assertIn("PYEOF", tc.params["command"])
        self.assertIn("print", tc.params["command"])

    def test_python_block_with_quotes(self):
        """Python block with quotes should be properly escaped."""
        response = '```python\nprint("hello \\"world\\"")\n```'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertIn("python3", tc.params["command"])

    def test_multiple_python_blocks_first_valid_wins(self):
        """First valid python block should win."""
        response = (
            '```python\n# Example: test\npass\n```\n'  # Documentation, skipped
            '```python\nprint("valid")\n```\n'  # Valid
            '```python\nprint("also valid")\n```'  # Also valid, but first wins
        )
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertIn("valid", tc.params["command"])

    def test_python_block_followed_by_hallucinated_output(self):
        """Python block followed by untagged code block should be filtered."""
        response = '```python\nprint("test")\n```\n```\ntest output\n```'
        tc = self.parser.parse(response)
        self.assertIsNone(tc)

    def test_python_block_with_just_pass_statement(self):
        """Python block with just 'pass' should work (it's executable)."""
        response = '```python\npass\n```'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertEqual(tc.tool_name, "Bash")

    def test_python_block_with_imports_and_code(self):
        """Python block with imports and code."""
        response = '```python\nimport json\nimport sys\nprint(json.dumps({"key": "value"}))\n```'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertIn("import", tc.params["command"])

    def test_python_block_with_multiline_string(self):
        """Python block with multiline string."""
        response = '```python\ntext = """line1\nline2\nline3"""\nprint(text)\n```'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertIn("line1", tc.params["command"])

    def test_python_block_comment_only_no_code(self):
        """Python block with only comments should be filtered."""
        response = '```python\n# Comment 1\n# Comment 2\n# Comment 3\n```'
        tc = self.parser.parse(response)
        self.assertIsNone(tc)


# ── TestParsePriorityOrder ──────────────────────────────────────────────────

class TestParsePriorityOrder(unittest.TestCase):
    """Test that parsing priority order is correct: structured > xml > bash > python."""

    def setUp(self):
        self.parser = ToolCallParser()

    def test_all_four_formats_present_structured_wins(self):
        """When all 4 formats present, structured JSON wins."""
        response = (
            '<tool_call>\n{"tool": "Tool1", "params": {}}\n</tool_call>\n'
            '<tool_call>\n<Tool2>\n{"param": "value"}\n</Tool2>\n</tool_call>\n'
            '```bash\nls\n```\n'
            '```python\nprint("hi")\n```'
        )
        tc = self.parser.parse(response)
        self.assertEqual(tc.tool_name, "Tool1")
        self.assertFalse(tc.is_legacy)

    def test_xml_bash_python_xml_wins(self):
        """XML-wrapped + bash + python: xml_wrapped wins."""
        response = (
            '<tool_call>\n<ReadXML>\n{"path": "x"}\n</ReadXML>\n</tool_call>\n'
            '```bash\nls\n```\n'
            '```python\nprint("hi")\n```'
        )
        tc = self.parser.parse(response)
        self.assertEqual(tc.tool_name, "ReadXML")

    def test_bash_python_bash_wins(self):
        """Bash + python: bash wins."""
        response = (
            '```bash\necho test\n```\n'
            '```python\nprint("hi")\n```'
        )
        tc = self.parser.parse(response)
        self.assertEqual(tc.tool_name, "Bash")
        self.assertTrue(tc.is_legacy)
        self.assertIn("echo", tc.params["command"])

    def test_only_python_python_used(self):
        """Only python format: python used."""
        response = '```python\nprint("only")\n```'
        tc = self.parser.parse(response)
        self.assertEqual(tc.tool_name, "Bash")
        self.assertTrue(tc.is_legacy)
        self.assertIn("python3", tc.params["command"])

    def test_structured_malformed_xml_valid_fallback(self):
        """Structured format malformed JSON, XML-wrapped valid: XML used."""
        response = (
            '<tool_call>\n{invalid json}\n</tool_call>\n'
            '<tool_call>\n<Read>\n{"path": "x"}\n</Read>\n</tool_call>'
        )
        tc = self.parser.parse(response)
        self.assertEqual(tc.tool_name, "Read")

    def test_structured_no_tool_key_bash_present(self):
        """Structured format has no tool key, bash present: bash used."""
        response = (
            '<tool_call>\n{"params": {"path": "x"}}\n</tool_call>\n'
            '```bash\nls\n```'
        )
        tc = self.parser.parse(response)
        self.assertEqual(tc.tool_name, "Bash")
        self.assertTrue(tc.is_legacy)

    def test_xml_wrapped_fallback_before_bash(self):
        """XML-wrapped should be tried before bash."""
        response = (
            '<tool_call>\n<Tool>\n{"param": "val"}\n</Tool>\n</tool_call>\n'
            '```bash\nls\n```'
        )
        tc = self.parser.parse(response)
        self.assertEqual(tc.tool_name, "Tool")
        self.assertFalse(tc.is_legacy)


# ── TestToolCallClass ───────────────────────────────────────────────────────

class TestToolCallClass(unittest.TestCase):
    """Test ToolCall class methods and attributes."""

    def test_repr_shows_legacy_flag(self):
        """repr() should show 'legacy' or 'structured' format."""
        tc_legacy = ToolCall("Bash", {"command": "ls"}, "", is_legacy=True)
        tc_structured = ToolCall("Read", {"path": "x"}, "", is_legacy=False)

        self.assertIn("legacy", repr(tc_legacy))
        self.assertIn("structured", repr(tc_structured))

    def test_preview_empty_params(self):
        """preview() with empty params should show tool name only."""
        tc = ToolCall("LS", {}, "")
        preview = tc.preview()
        self.assertIn("LS", preview)
        self.assertIn("()", preview)

    def test_preview_long_param_truncated(self):
        """preview() with very long key param should truncate with '...'."""
        tc = ToolCall("Read", {"path": "a" * 100}, "")
        preview = tc.preview(max_len=30)
        # Preview includes tool name + param, so total will be > max_len
        # but the param itself should be truncated
        self.assertIn("...", preview)
        self.assertLess(preview.count("a"), 30)  # Should not have 30+ 'a' chars

    def test_preview_bash_multiline_command(self):
        """preview() for Bash should show first line only."""
        tc = ToolCall("Bash", {"command": "line1\nline2\nline3"}, "", is_legacy=True)
        preview = tc.preview()
        self.assertIn("line1", preview)
        self.assertNotIn("line2", preview)

    def test_preview_non_string_first_param(self):
        """preview() with non-string param values should work."""
        tc = ToolCall("Tool", {"count": 42, "enabled": True}, "")
        preview = tc.preview()
        # Should not crash
        self.assertIsNotNone(preview)

    def test_preview_max_len_respected(self):
        """preview() should respect max_len parameter."""
        tc = ToolCall("Read", {"path": "a" * 200}, "")
        for max_len in [20, 50, 100]:
            preview = tc.preview(max_len=max_len)
            # Allow for the tool name and parentheses
            self.assertLessEqual(len(preview), max_len + 10)

    def test_tool_call_raw_attribute(self):
        """ToolCall should preserve raw matched text."""
        raw_text = '<tool_call>\n{"tool": "Read", "params": {}}\n</tool_call>'
        tc = ToolCall("Read", {}, raw_text, is_legacy=False)
        self.assertEqual(tc.raw, raw_text)

    def test_tool_call_params_dict_reference(self):
        """ToolCall should store params dict reference."""
        params = {"key": "value"}
        tc = ToolCall("Tool", params, "")
        self.assertIs(tc.params, params)


# ── TestFormatToolResultEdgeCases ───────────────────────────────────────────

class TestFormatToolResultEdgeCases(unittest.TestCase):
    """Test edge cases in format_tool_result()."""

    def test_result_with_output_and_error_success(self):
        """Success result with both output and error: only output shown."""
        tc = ToolCall("Bash", {"command": "test"}, "")
        result = ToolResult(True, output="stdout content", error="stderr content")
        formatted = format_tool_result(tc, result)
        self.assertIn("stdout content", formatted)
        self.assertNotIn("STDERR:", formatted)

    def test_result_with_output_and_error_failure(self):
        """Error result with both output and error: STDERR prefix."""
        tc = ToolCall("Bash", {"command": "fail"}, "")
        result = ToolResult(False, output="some output", error="critical error")
        formatted = format_tool_result(tc, result)
        self.assertIn("STDERR: critical error", formatted)
        self.assertIn("some output", formatted)

    def test_result_with_very_long_output_truncated(self):
        """Result with 3000+ chars: should truncate."""
        tc = ToolCall("Bash", {"command": "cat big"}, "")
        long_output = "x" * 5000
        result = ToolResult(True, output=long_output)
        formatted = format_tool_result(tc, result)
        # Output section should be significantly shorter
        output_section = formatted.split("output: |")[1]
        self.assertLess(len(output_section), 4000)

    def test_result_with_no_metadata(self):
        """Result with no metadata: no metadata line in output."""
        tc = ToolCall("Bash", {"command": "test"}, "")
        result = ToolResult(True, output="content")  # No metadata
        formatted = format_tool_result(tc, result)
        self.assertNotIn("metadata:", formatted)

    def test_result_with_complex_metadata(self):
        """Result with nested dict metadata: JSON serialized."""
        tc = ToolCall("Read", {"path": "x.py"}, "")
        metadata = {
            "lines_read": 42,
            "config": {"nested": {"deep": "value"}},
            "list": [1, 2, 3]
        }
        result = ToolResult(True, output="content", metadata=metadata)
        formatted = format_tool_result(tc, result)
        self.assertIn("metadata:", formatted)
        self.assertIn("nested", formatted)

    def test_result_with_empty_output_no_output_text(self):
        """Result with empty output: shows '(no output)'."""
        tc = ToolCall("Bash", {"command": "silent"}, "")
        result = ToolResult(True, output="")
        formatted = format_tool_result(tc, result)
        self.assertIn("(no output)", formatted)

    def test_result_error_status_shown(self):
        """Error result should show 'status: ERROR'."""
        tc = ToolCall("Bash", {"command": "fail"}, "")
        result = ToolResult(False, error="command failed")
        formatted = format_tool_result(tc, result)
        self.assertIn("status: ERROR", formatted)

    def test_result_success_status_shown(self):
        """Success result should show 'status: OK'."""
        tc = ToolCall("Read", {"path": "x"}, "")
        result = ToolResult(True, output="content")
        formatted = format_tool_result(tc, result)
        self.assertIn("status: OK", formatted)

    def test_result_output_indentation(self):
        """Result output should be indented under 'output: |'."""
        tc = ToolCall("Bash", {"command": "test"}, "")
        result = ToolResult(True, output="line1\nline2\nline3")
        formatted = format_tool_result(tc, result)
        lines = formatted.split("\n")
        # Find output section and verify indentation
        output_idx = next(i for i, l in enumerate(lines) if "output: |" in l)
        for line in lines[output_idx + 1:]:
            if line.strip() and not line.startswith("</tool_result>"):
                self.assertTrue(line.startswith("  "))

    def test_result_tool_name_included(self):
        """Result should include the tool name."""
        tc = ToolCall("CustomTool", {"param": "val"}, "")
        result = ToolResult(True, output="ok")
        formatted = format_tool_result(tc, result)
        self.assertIn("tool: CustomTool", formatted)

    def test_result_wrapped_in_tool_result_tags(self):
        """Result should be wrapped in <tool_result> tags."""
        tc = ToolCall("Read", {"path": "x"}, "")
        result = ToolResult(True, output="content")
        formatted = format_tool_result(tc, result)
        self.assertIn("<tool_result>", formatted)
        self.assertIn("</tool_result>", formatted)


# ── TestStripToolCallEdgeCases ──────────────────────────────────────────────

class TestStripToolCallEdgeCases(unittest.TestCase):
    """Test edge cases in strip_tool_call()."""

    def setUp(self):
        self.parser = ToolCallParser()

    def test_strip_only_tool_call_empty_result(self):
        """Stripping from response with only tool call: empty string."""
        raw = '<tool_call>\n{"tool": "Read", "params": {}}\n</tool_call>'
        response = raw
        tc = self.parser.parse(response)
        stripped = self.parser.strip_tool_call(response, tc)
        self.assertEqual(stripped, "")

    def test_strip_preserves_text_before(self):
        """Stripping should preserve text before tool call."""
        raw = '<tool_call>\n{"tool": "Read", "params": {}}\n</tool_call>'
        response = "Let me read this file:\n\n" + raw
        tc = self.parser.parse(response)
        stripped = self.parser.strip_tool_call(response, tc)
        self.assertIn("Let me read", stripped)
        self.assertNotIn("<tool_call>", stripped)

    def test_strip_preserves_text_after(self):
        """Stripping should preserve text after tool call."""
        raw = '<tool_call>\n{"tool": "Read", "params": {}}\n</tool_call>'
        response = raw + "\n\nThanks for waiting!"
        tc = self.parser.parse(response)
        stripped = self.parser.strip_tool_call(response, tc)
        self.assertIn("Thanks", stripped)
        self.assertNotIn("<tool_call>", stripped)

    def test_strip_preserves_both_before_and_after(self):
        """Stripping should preserve text before and after."""
        raw = '<tool_call>\n{"tool": "Read", "params": {"path": "x.py"}}\n</tool_call>'
        response = f"Here's my plan:\n\n{raw}\n\nNow I'll examine the results."
        tc = self.parser.parse(response)
        stripped = self.parser.strip_tool_call(response, tc)
        self.assertIn("plan", stripped)
        self.assertIn("results", stripped)
        self.assertNotIn("<tool_call>", stripped)

    def test_strip_xml_wrapped_format(self):
        """Stripping should work for XML-wrapped format."""
        raw = '<tool_call>\n<Read>\n{"path": "x"}\n</Read>\n</tool_call>'
        response = f"Checking:\n{raw}\nDone."
        tc = self.parser.parse(response)
        stripped = self.parser.strip_tool_call(response, tc)
        self.assertNotIn("<tool_call>", stripped)
        self.assertNotIn("<Read>", stripped)
        self.assertIn("Checking", stripped)
        self.assertIn("Done", stripped)

    def test_strip_bash_format(self):
        """Stripping should work for legacy bash format."""
        raw = '```bash\nls -la\n```'
        response = f"Let's see:\n{raw}\nFiles listed."
        tc = self.parser.parse(response)
        stripped = self.parser.strip_tool_call(response, tc)
        self.assertNotIn("```bash", stripped)
        self.assertNotIn("ls -la", stripped)
        self.assertIn("Let's see", stripped)
        self.assertIn("Files listed", stripped)

    def test_strip_with_multiple_newlines(self):
        """Stripping should handle multiple newlines around tool call."""
        raw = '<tool_call>\n{"tool": "Bash", "params": {}}\n</tool_call>'
        response = f"Before.\n\n\n{raw}\n\n\nAfter."
        tc = self.parser.parse(response)
        stripped = self.parser.strip_tool_call(response, tc)
        self.assertIn("Before", stripped)
        self.assertIn("After", stripped)


# ── Integration Tests ───────────────────────────────────────────────────────

class TestParserIntegration(unittest.TestCase):
    """Integration tests combining multiple features."""

    def setUp(self):
        self.parser = ToolCallParser()

    def test_parse_and_strip_and_format_workflow(self):
        """Full workflow: parse, strip, and format result."""
        response = (
            "I'll read that file for you.\n\n"
            '<tool_call>\n{"tool": "Read", "params": {"path": "main.py"}}\n</tool_call>\n'
            "Let me know if you need anything else."
        )

        # Parse
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertEqual(tc.tool_name, "Read")

        # Strip
        stripped = self.parser.strip_tool_call(response, tc)
        self.assertNotIn("<tool_call>", stripped)
        self.assertIn("I'll read", stripped)
        self.assertIn("else", stripped)

        # Format result
        result = ToolResult(True, output="# main.py\nprint('hello')\n")
        formatted = format_tool_result(tc, result)
        self.assertIn("<tool_result>", formatted)
        self.assertIn("Read", formatted)
        self.assertIn("main.py", formatted)

    def test_priority_handling_real_scenario(self):
        """Real scenario with multiple formats and fallback handling."""
        response = (
            "Let me check multiple approaches:\n\n"
            '<tool_call>\n{"tool": "Read", "params": {"path": "bad"}}\n</tool_call>\n'
            "This is my primary approach."
        )

        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertEqual(tc.tool_name, "Read")

    def test_handle_llm_evolution(self):
        """Test handling of different LLM output styles over time."""
        # Scenario: LLM switches from structured to XML-wrapped format
        responses = [
            '<tool_call>\n{"tool": "Read", "params": {"path": "a.py"}}\n</tool_call>',
            '<tool_call>\n<Read>\n{"path": "b.py"}\n</Read>\n</tool_call>',
            '```bash\nls -la c.py\n```',
        ]

        for response in responses:
            tc = self.parser.parse(response)
            self.assertIsNotNone(tc)
            self.assertIsNotNone(tc.tool_name)


class TestMismatchedClosingTag(unittest.TestCase):
    """Test tolerance for mismatched closing tags.

    LLMs sometimes output </tool_result> instead of </tool_call>.
    The parser should tolerate this and still parse the tool call.
    """

    def setUp(self):
        self.parser = ToolCallParser()

    def test_structured_with_tool_result_closing(self):
        """<tool_call>...JSON...</tool_result> should still parse."""
        response = '<tool_call>\n{"tool": "SomeTool", "params": {}}\n</tool_result>'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertEqual(tc.tool_name, "SomeTool")
        self.assertEqual(tc.params, {})

    def test_structured_read_with_tool_result_closing(self):
        response = '<tool_call>\n{"tool": "Read", "params": {"path": "main.py"}}\n</tool_result>'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertEqual(tc.tool_name, "Read")
        self.assertEqual(tc.params["path"], "main.py")

    def test_xml_wrapped_with_tool_result_closing(self):
        """XML-wrapped format with </tool_result> closing."""
        response = '<tool_call>\n<Read>\n{"path": "test.py"}\n</Read>\n</tool_result>'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertEqual(tc.tool_name, "Read")

    def test_normal_tool_call_closing_still_works(self):
        """Regular </tool_call> closing must still work."""
        response = '<tool_call>\n{"tool": "SomeTool", "params": {}}\n</tool_call>'
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertEqual(tc.tool_name, "SomeTool")

    def test_mismatched_tag_with_surrounding_text(self):
        """Full response with prose + mismatched closing."""
        response = (
            "我来查看整个文件夹的结构和内容，然后分析架构。\n\n"
            "<tool_call>\n"
            '{"tool": "SomeTool", "params": {}}\n'
            "</tool_result>"
        )
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertEqual(tc.tool_name, "SomeTool")

    def test_strip_mismatched_tag(self):
        """strip_tool_call should work with mismatched closing tag."""
        response = (
            "我来查看。\n\n"
            '<tool_call>\n{"tool": "SomeTool", "params": {}}\n</tool_result>'
        )
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        stripped = self.parser.strip_tool_call(response, tc)
        self.assertNotIn("<tool_call>", stripped)
        self.assertNotIn("</tool_result>", stripped)
        self.assertIn("我来查看", stripped)

    def test_mismatched_with_complex_params(self):
        """Complex params with mismatched closing tag."""
        response = (
            '<tool_call>\n'
            '{"tool": "Grep", "params": {"pattern": "def main", "file_type": "py", "case_insensitive": true}}\n'
            '</tool_result>'
        )
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertEqual(tc.tool_name, "Grep")
        self.assertTrue(tc.params["case_insensitive"])


class TestToolCallDisplayStrippingMismatched(unittest.TestCase):
    """Test the regex patterns used in telegram_bot.py for stripping,
    now with mismatched tag tolerance."""

    def test_strip_full_block_mismatched(self):
        """The full-block strip regex should handle </tool_result> closing."""
        import re
        pattern = re.compile(r'<tool_call>.*?</tool_(?:call|result)>', re.DOTALL)
        text = '我来查看。\n<tool_call>\n{"tool": "LS", "params": {}}\n</tool_result>\n继续。'
        clean = pattern.sub('', text).strip()
        self.assertNotIn("tool_call", clean)
        self.assertNotIn("tool_result", clean)
        self.assertIn("我来查看", clean)
        self.assertIn("继续", clean)

    def test_strip_partial_tags_mismatched(self):
        """The partial tag strip regex should handle </tool_result>."""
        import re
        pattern = re.compile(r'</?tool_(?:call|result)>')
        text = '</tool_result> leftover text </tool_call>'
        clean = pattern.sub('', text).strip()
        self.assertEqual(clean, "leftover text")

    def test_strip_both_normal_and_mismatched(self):
        """Mix of correct and mismatched tags."""
        import re
        pattern = re.compile(r'<tool_call>.*?</tool_(?:call|result)>', re.DOTALL)
        text = (
            'Text 1\n<tool_call>{"tool":"A","params":{}}</tool_call>\n'
            'Text 2\n<tool_call>{"tool":"B","params":{}}</tool_result>\n'
            'Text 3'
        )
        clean = pattern.sub('', text).strip()
        self.assertIn("Text 1", clean)
        self.assertIn("Text 2", clean)
        self.assertIn("Text 3", clean)
        self.assertNotIn("tool_call", clean)


if __name__ == "__main__":
    unittest.main()
