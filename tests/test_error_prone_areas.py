"""Comprehensive tests for error-prone areas in NeoMind agent.

This test file focuses on areas where exceptions can be silently swallowed,
None checks are missing, or edge cases can cause crashes:

1. AgenticLoop._execute - tool execute can raise, not caught
2. Glob/Grep metadata extraction - silent failures
3. PersistentBash initialization and cleanup
4. Binary file detection - permission errors silently ignored
5. Python heredoc escaping - "PYEOF" in code breaks heredoc
6. Hallucination detection - missing edge cases
7. Dangling intent detection - regex pattern edge cases
8. Grep exit codes - unhandled error codes
"""

import os
import sys
import tempfile
import unittest
import asyncio
from unittest.mock import MagicMock, patch, mock_open, call
import json
import subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.agentic.agentic_loop import AgenticLoop, AgenticConfig
from agent.coding.tools import ToolRegistry, ToolResult
from agent.coding.tool_parser import ToolCallParser, ToolCall, format_tool_result


class TestAgenticLoopExecuteErrors(unittest.TestCase):
    """Test AgenticLoop._execute error handling."""

    def setUp(self):
        """Set up test fixtures."""
        self.registry = MagicMock()
        self.config = AgenticConfig()
        self.loop = AgenticLoop(self.registry, self.config)

    def test_execute_tool_not_found_returns_error(self):
        """Tool execute when tool_def is None returns ToolResult error."""
        self.registry.get_tool.return_value = None
        tc = ToolCall("UnknownTool", {}, "raw")
        result = asyncio.run(self.loop._execute(tc))

        self.assertIsInstance(result, ToolResult)
        self.assertFalse(result.success)
        self.assertIn("Unknown tool", result.error)

    def test_execute_validate_params_fails_returns_error(self):
        """Tool execute when validate_params returns False returns error."""
        tool_def = MagicMock()
        tool_def.validate_params.return_value = (False, "Invalid type")
        self.registry.get_tool.return_value = tool_def

        tc = ToolCall("BadTool", {"bad_param": 123}, "raw")
        result = asyncio.run(self.loop._execute(tc))

        self.assertFalse(result.success)
        self.assertIn("Invalid params", result.error)

    def test_execute_tool_raises_runtime_error(self):
        """Tool execute raises RuntimeError - should propagate (not caught in _execute)."""
        tool_def = MagicMock()
        tool_def.validate_params.return_value = (True, "")
        tool_def.apply_defaults.return_value = {"command": "test"}
        tool_def.execute.side_effect = RuntimeError("Command failed")
        self.registry.get_tool.return_value = tool_def

        tc = ToolCall("Bash", {"command": "bad"}, "raw")
        # The exception should propagate out of _execute
        with self.assertRaises(RuntimeError):
            asyncio.run(self.loop._execute(tc))

    def test_execute_tool_raises_type_error(self):
        """Tool execute raises TypeError - should propagate."""
        tool_def = MagicMock()
        tool_def.validate_params.return_value = (True, "")
        tool_def.apply_defaults.return_value = {"command": None}
        tool_def.execute.side_effect = TypeError("Wrong type for command")
        self.registry.get_tool.return_value = tool_def

        tc = ToolCall("Bash", {"command": None}, "raw")
        with self.assertRaises(TypeError):
            asyncio.run(self.loop._execute(tc))

    def test_execute_tool_returns_none(self):
        """Tool execute returns None instead of ToolResult - no validation."""
        tool_def = MagicMock()
        tool_def.validate_params.return_value = (True, "")
        tool_def.apply_defaults.return_value = {"path": "/test"}
        tool_def.execute.return_value = None  # BUG: should return ToolResult
        self.registry.get_tool.return_value = tool_def

        tc = ToolCall("Read", {"path": "/test"}, "raw")
        result = asyncio.run(self.loop._execute(tc))
        # _execute doesn't validate return type, so None is returned
        self.assertIsNone(result)

    def test_execute_validate_params_returns_non_tuple(self):
        """validate_params returns unexpected type (not tuple)."""
        tool_def = MagicMock()
        tool_def.validate_params.return_value = "invalid"  # Should be (bool, str)
        self.registry.get_tool.return_value = tool_def

        tc = ToolCall("Test", {}, "raw")
        # This will fail with a ValueError when trying to unpack a string
        with self.assertRaises((TypeError, ValueError)):
            asyncio.run(self.loop._execute(tc))

    def test_execute_apply_defaults_returns_none(self):
        """apply_defaults returns None instead of dict."""
        tool_def = MagicMock()
        tool_def.validate_params.return_value = (True, "")
        tool_def.apply_defaults.return_value = None  # BUG
        self.registry.get_tool.return_value = tool_def

        tc = ToolCall("Test", {}, "raw")
        # This will fail when trying to **None
        with self.assertRaises(TypeError):
            asyncio.run(self.loop._execute(tc))

    def test_execute_tool_call_with_none_tool_name(self):
        """ToolCall with None tool_name."""
        self.registry.get_tool.return_value = None
        tc = ToolCall(None, {}, "raw")
        result = asyncio.run(self.loop._execute(tc))

        self.assertFalse(result.success)
        self.assertIn("Unknown tool", result.error)

    def test_execute_tool_call_with_empty_tool_name(self):
        """ToolCall with empty string tool_name."""
        self.registry.get_tool.return_value = None
        tc = ToolCall("", {}, "raw")
        result = asyncio.run(self.loop._execute(tc))

        self.assertFalse(result.success)

    def test_execute_registry_is_none(self):
        """Registry is None - AttributeError."""
        loop = AgenticLoop(None, self.config)
        tc = ToolCall("Bash", {}, "raw")
        with self.assertRaises(AttributeError):
            asyncio.run(loop._execute(tc))

    def test_execute_tool_call_params_none(self):
        """ToolCall with None params."""
        tool_def = MagicMock()
        tool_def.validate_params.side_effect = TypeError("Cannot iterate None")
        self.registry.get_tool.return_value = tool_def

        tc = ToolCall("Bash", None, "raw")
        with self.assertRaises(TypeError):
            asyncio.run(self.loop._execute(tc))


class TestToolRegistryExecErrors(unittest.TestCase):
    """Test ToolRegistry execution with malformed output."""

    def setUp(self):
        """Set up test fixtures."""
        self.tmpdir = tempfile.mkdtemp()
        self.registry = ToolRegistry(working_dir=self.tmpdir)

    def tearDown(self):
        """Clean up."""
        import shutil
        if os.path.exists(self.tmpdir):
            shutil.rmtree(self.tmpdir)

    def test_exec_glob_with_empty_output(self):
        """_exec_glob with empty output - metadata extraction doesn't crash."""
        with patch.object(self.registry, 'glob_files') as mock_glob:
            mock_result = ToolResult(True, output="")
            mock_glob.return_value = mock_result

            result = self.registry._exec_glob("*.py")
            # Should not crash, metadata should be set
            self.assertTrue(result.success)
            self.assertEqual(result.metadata.get("pattern"), "*.py")

    def test_exec_glob_with_malformed_header(self):
        """_exec_glob with malformed header - metadata silently skipped."""
        with patch.object(self.registry, 'glob_files') as mock_glob:
            # Output has header but it's malformed
            output = "# Some malformed header\nfile1.py\nfile2.py"
            mock_result = ToolResult(True, output=output)
            mock_glob.return_value = mock_result

            result = self.registry._exec_glob("*.py")
            # Should not crash
            self.assertTrue(result.success)
            # files_matched should be missing from metadata (silently skipped)
            self.assertNotIn("files_matched", result.metadata)

    def test_exec_glob_with_valid_count(self):
        """_exec_glob extracts file count correctly."""
        with patch.object(self.registry, 'glob_files') as mock_glob:
            output = "# 5 files matching '*.py'\nfile1.py\nfile2.py\nfile3.py\nfile4.py\nfile5.py"
            mock_result = ToolResult(True, output=output)
            mock_glob.return_value = mock_result

            result = self.registry._exec_glob("*.py")
            self.assertEqual(result.metadata.get("files_matched"), 5)

    def test_exec_ls_with_empty_output(self):
        """_exec_ls with empty output."""
        with patch.object(self.registry, 'list_dir') as mock_ls:
            mock_result = ToolResult(True, output="")
            mock_ls.return_value = mock_result

            result = self.registry._exec_ls()
            self.assertTrue(result.success)
            self.assertNotIn("entry_count", result.metadata)

    def test_exec_ls_with_malformed_header(self):
        """_exec_ls with malformed header - metadata silently skipped."""
        with patch.object(self.registry, 'list_dir') as mock_ls:
            output = "# /some/path malformed\nfile1.txt\nfile2.txt"
            mock_result = ToolResult(True, output=output)
            mock_ls.return_value = mock_result

            result = self.registry._exec_ls()
            self.assertTrue(result.success)
            self.assertNotIn("entry_count", result.metadata)

    def test_exec_read_with_empty_file(self):
        """_exec_read with empty file works."""
        # Create an empty file
        filepath = os.path.join(self.tmpdir, "empty.txt")
        with open(filepath, "w") as f:
            f.write("")

        result = self.registry._exec_read("empty.txt")
        self.assertTrue(result.success)
        # Empty file still has header line, so lines_in_output = 1
        self.assertIn("lines_in_output", result.metadata)

    def test_exec_write_with_unicode_content(self):
        """_exec_write with unicode content works."""
        content = "Hello 世界 مرحبا мир"
        result = self.registry._exec_write("test_unicode.txt", content)

        self.assertTrue(result.success)
        # bytes_written is measured in characters, not UTF-8 bytes
        self.assertIn("bytes_written", result.metadata)
        self.assertEqual(result.metadata.get("lines_written"), 1)

    def test_edit_when_file_deleted_between_check_and_open(self):
        """_exec_edit when file deleted between exists check and open."""
        filepath = os.path.join(self.tmpdir, "temp.txt")
        with open(filepath, "w") as f:
            f.write("original content")

        # Simulate the file being deleted after the exists check
        with patch("builtins.open", side_effect=FileNotFoundError("No such file")):
            result = self.registry._exec_edit("temp.txt", "original", "new")
            # Should return error gracefully
            self.assertFalse(result.success)
            self.assertIn("Failed to edit", result.error)


class TestPersistentBashErrors(unittest.TestCase):
    """Test PersistentBash error handling."""

    def setUp(self):
        """Set up test fixtures."""
        self.tmpdir = tempfile.mkdtemp()
        self.registry = ToolRegistry(working_dir=self.tmpdir)

    def tearDown(self):
        """Clean up."""
        try:
            self.registry.close_bash()
        except Exception:
            # In test_close_bash_when_close_raises_os_error, close already raised
            pass
        import shutil
        if os.path.exists(self.tmpdir):
            shutil.rmtree(self.tmpdir)

    def test_get_persistent_bash_when_import_fails(self):
        """_get_persistent_bash when PersistentBash import fails (simulated)."""
        # Since PersistentBash is imported dynamically inside the method,
        # we can test the behavior by mocking __import__ properly
        import builtins
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if "persistent_bash" in name:
                raise ImportError("No module named persistent_bash")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            with self.assertRaises(ImportError):
                self.registry._get_persistent_bash()

    def test_get_persistent_bash_when_is_alive_raises(self):
        """_get_persistent_bash when _is_alive() raises."""
        mock_instance = MagicMock()
        mock_instance._is_alive.side_effect = RuntimeError("Check failed")

        self.registry._persistent_bash = mock_instance
        with self.assertRaises(RuntimeError):
            self.registry._get_persistent_bash()

    def test_close_bash_when_close_raises_os_error(self):
        """close_bash when close() raises OSError."""
        mock_instance = MagicMock()
        mock_instance.close.side_effect = OSError("Broken pipe")
        self.registry._persistent_bash = mock_instance

        # Should propagate the OSError
        with self.assertRaises(OSError):
            self.registry.close_bash()

    def test_close_bash_when_persistent_bash_is_none(self):
        """close_bash when _persistent_bash is None - no-op."""
        self.registry._persistent_bash = None
        # Should not raise
        self.registry.close_bash()
        self.assertIsNone(self.registry._persistent_bash)

    def test_bash_fallback_when_persistent_fails(self):
        """bash() when persistent fails, fallback works."""
        mock_instance = MagicMock()
        mock_instance._is_alive.return_value = True
        mock_instance.execute.side_effect = RuntimeError("Session dead")
        self.registry._persistent_bash = mock_instance

        # Should catch exception and fallback
        result = self.registry.bash("echo test")
        # Fallback uses subprocess.run, which should succeed for echo
        self.assertTrue(result.success)
        self.assertIn("test", result.output)


class TestBinaryFileDetection(unittest.TestCase):
    """Test binary file detection in read_file."""

    def setUp(self):
        """Set up test fixtures."""
        self.tmpdir = tempfile.mkdtemp()
        self.registry = ToolRegistry(working_dir=self.tmpdir)

    def tearDown(self):
        """Clean up."""
        import shutil
        if os.path.exists(self.tmpdir):
            shutil.rmtree(self.tmpdir)

    def test_binary_file_with_nul_bytes(self):
        """Binary file with NUL bytes detected."""
        filepath = os.path.join(self.tmpdir, "binary.bin")
        with open(filepath, "wb") as f:
            f.write(b"Binary\x00Data")

        result = self.registry.read_file("binary.bin")
        self.assertFalse(result.success)
        self.assertIn("Binary file", result.error)

    def test_text_file_reads_successfully(self):
        """Text file reads successfully."""
        filepath = os.path.join(self.tmpdir, "text.txt")
        with open(filepath, "w") as f:
            f.write("Hello\nWorld")

        result = self.registry.read_file("text.txt")
        self.assertTrue(result.success)
        self.assertIn("Hello", result.output)
        self.assertIn("World", result.output)

    def test_permission_error_during_binary_check_continues(self):
        """Permission error during binary check - silent pass, continues to read."""
        filepath = os.path.join(self.tmpdir, "noaccess.txt")
        with open(filepath, "w") as f:
            f.write("Secret content")

        # Mock open to raise PermissionError on first call (binary check)
        original_open = open
        call_count = [0]

        def mock_open_func(path, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1 and "rb" in str(args):
                raise PermissionError("Access denied")
            return original_open(path, *args, **kwargs)

        with patch("builtins.open", side_effect=mock_open_func):
            result = self.registry.read_file("noaccess.txt")
            # Should continue despite permission error
            self.assertTrue(result.success)

    def test_file_with_nul_in_first_chunk_detected(self):
        """File with NUL only in first 8192 bytes is detected."""
        filepath = os.path.join(self.tmpdir, "sparse_binary.bin")
        with open(filepath, "wb") as f:
            # NUL byte in first chunk
            f.write(b"Start" + b"\x00" + b"Rest")

        result = self.registry.read_file("sparse_binary.bin")
        self.assertFalse(result.success)
        self.assertIn("Binary file", result.error)


class TestPythonHeredocEscaping(unittest.TestCase):
    """Test Python heredoc escaping in tool_parser."""

    def setUp(self):
        """Set up test fixtures."""
        self.parser = ToolCallParser()

    def test_normal_python_code_heredoc_format(self):
        """Normal Python code produces correct heredoc."""
        response = """```python
print("hello")
```"""
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertEqual(tc.tool_name, "Bash")
        self.assertIn("python3 << 'PYEOF'", tc.params["command"])
        self.assertIn("print(\"hello\")", tc.params["command"])
        self.assertIn("PYEOF", tc.params["command"])

    def test_python_code_containing_pyeof_string(self):
        """Python code containing 'PYEOF' string breaks heredoc."""
        response = """```python
content = "PYEOF"
print(content)
```"""
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        # The heredoc will be broken because PYEOF appears in the code
        # This is a known bug - the delimiter is hardcoded
        command = tc.params["command"]
        # The heredoc will incorrectly terminate when it encounters "PYEOF"
        self.assertIn("PYEOF", command)
        # This would fail at runtime, but the parser doesn't detect it

    def test_python_code_with_quotes(self):
        """Python code with quotes handled by heredoc."""
        response = """```python
msg = 'single' + "double"
```"""
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        command = tc.params["command"]
        self.assertIn("'single'", command)
        self.assertIn('"double"', command)

    def test_python_code_with_backslashes(self):
        """Python code with backslashes handled by heredoc."""
        response = r"""```python
path = "C:\\Users\\test"
```"""
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        command = tc.params["command"]
        self.assertIn("C:\\\\Users\\\\test", command)

    def test_python_code_with_newlines(self):
        """Python code with multiple newlines."""
        response = """```python
def func():
    return 42

print(func())
```"""
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        command = tc.params["command"]
        self.assertIn("def func():", command)
        self.assertIn("return 42", command)


class TestHallucinationDetection(unittest.TestCase):
    """Test hallucination detection in tool_parser."""

    def setUp(self):
        """Set up test fixtures."""
        self.parser = ToolCallParser()

    def test_bash_followed_by_triple_backtick_newline_detected(self):
        """Bash followed by ```\\n - hallucination detected."""
        response = """```bash
echo "test"
```
```
output: test
```"""
        tc = self.parser.parse(response)
        # Should detect hallucination and return None
        self.assertIsNone(tc)

    def test_bash_followed_by_triple_backtick_carriage_return_detected(self):
        """Bash followed by ```\\r - hallucination detected."""
        response = "```bash\necho test\n```\n```\r\noutput"
        tc = self.parser.parse(response)
        # Should detect hallucination
        self.assertIsNone(tc)

    def test_bash_followed_by_triple_backtick_crlf_not_detected_currently(self):
        """Bash followed by ```\\r\\n - NOT currently detected (bug)."""
        response = "```bash\necho test\n```\n```\r\noutput"
        tc = self.parser.parse(response)
        # Currently doesn't check for \r\n together
        # This is a bug that could allow hallucinations through
        # The check only looks for "\n" or "\r" separately

    def test_bash_followed_by_regular_text_not_hallucination(self):
        """Bash followed by regular text - not hallucination."""
        response = """```bash
echo "test"
```
This is regular text, not a code block."""
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertEqual(tc.tool_name, "Bash")
        self.assertIn("echo", tc.params["command"])

    def test_bash_at_end_of_response_not_hallucination(self):
        """Bash at end of response - not hallucination."""
        response = """Let me run this command:
```bash
ls -la
```"""
        tc = self.parser.parse(response)
        self.assertIsNotNone(tc)
        self.assertEqual(tc.tool_name, "Bash")
        self.assertIn("ls", tc.params["command"])

    def test_python_with_hallucinated_output(self):
        """Python code followed by hallucinated output."""
        response = """```python
print("hello")
```
```
hello
```"""
        tc = self.parser.parse(response)
        # Should detect hallucination and skip this bash block
        self.assertIsNone(tc)


class TestDanglingIntentDetection(unittest.TestCase):
    """Test dangling intent detection pattern."""

    def _is_dangling(self, text: str) -> bool:
        """Helper to test dangling intent detection."""
        stripped = text.strip()
        return stripped.endswith(('：', ':', '…', '...')) and any(
            kw in stripped for kw in ('让我', '我来', '检查', '查看', '创建', '执行', '读取')
        )

    def test_dangling_with_chinese_colon_and_keyword(self):
        """'让我检查一下：' - dangling (True)."""
        self.assertTrue(self._is_dangling("让我检查一下："))

    def test_dangling_with_english_colon_and_keyword(self):
        """'我来创建文件...' - dangling (True)."""
        self.assertTrue(self._is_dangling("我来创建文件..."))

    def test_not_dangling_with_period(self):
        """'完成了。' - not dangling (False)."""
        self.assertFalse(self._is_dangling("完成了。"))

    def test_dangling_with_multiple_ellipsis(self):
        """'让我检查一下…' - dangling (True)."""
        self.assertTrue(self._is_dangling("让我检查一下…"))

    def test_dangling_with_keyword_in_middle(self):
        """'文件已读取。结果如下：' - dangling if ends with colon (True)."""
        self.assertTrue(self._is_dangling("文件已读取。结果如下："))

    def test_not_dangling_english_text(self):
        """'The file was created.' - not dangling (False)."""
        self.assertFalse(self._is_dangling("The file was created."))

    def test_not_dangling_keyword_alone(self):
        """'我来' alone without ending punctuation - False."""
        self.assertFalse(self._is_dangling("我来"))

    def test_not_dangling_keyword_with_period(self):
        """'让我检查。' - keyword but ends with period, not colon (False)."""
        self.assertFalse(self._is_dangling("让我检查。"))

    def test_dangling_empty_string(self):
        """Empty string - False."""
        self.assertFalse(self._is_dangling(""))

    def test_dangling_only_punctuation(self):
        """Just '：' - False (no keyword)."""
        self.assertFalse(self._is_dangling("："))

    def test_dangling_keyword_ending_with_punctuation(self):
        """'我来执行命令：' - True (keyword + colon)."""
        self.assertTrue(self._is_dangling("我来执行命令："))

    def test_dangling_multiple_keywords(self):
        """'让我检查并读取文件...' - True (multiple keywords + ellipsis)."""
        self.assertTrue(self._is_dangling("让我检查并读取文件..."))


class TestGrepExitCodes(unittest.TestCase):
    """Test grep/ripgrep exit code handling."""

    def setUp(self):
        """Set up test fixtures."""
        self.tmpdir = tempfile.mkdtemp()
        self.registry = ToolRegistry(working_dir=self.tmpdir)

    def tearDown(self):
        """Clean up."""
        import shutil
        if os.path.exists(self.tmpdir):
            shutil.rmtree(self.tmpdir)

    @patch("subprocess.run")
    @patch.object(ToolRegistry, "_has_ripgrep")
    def test_ripgrep_exit_0_success_with_output(self, mock_has_rg, mock_run):
        """Ripgrep exit 0 - success with output."""
        mock_has_rg.return_value = True
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "file.py:10: found_pattern"
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        result = self.registry.grep_files("found_pattern", path=self.tmpdir)
        self.assertTrue(result.success)
        self.assertIn("found_pattern", result.output)

    @patch("subprocess.run")
    @patch.object(ToolRegistry, "_has_ripgrep")
    def test_ripgrep_exit_1_no_matches(self, mock_has_rg, mock_run):
        """Ripgrep exit 1 - no matches."""
        mock_has_rg.return_value = True
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        result = self.registry.grep_files("nonexistent", path=self.tmpdir)
        self.assertTrue(result.success)
        self.assertIn("No matches", result.output)

    @patch("subprocess.run")
    @patch.object(ToolRegistry, "_has_ripgrep")
    def test_ripgrep_exit_2_invalid_regex(self, mock_has_rg, mock_run):
        """Ripgrep exit 2 - invalid regex."""
        mock_has_rg.return_value = True
        mock_result = MagicMock()
        mock_result.returncode = 2
        mock_result.stdout = ""
        mock_result.stderr = "regex parse error"
        mock_run.return_value = mock_result

        result = self.registry.grep_files("[invalid(regex", path=self.tmpdir)
        self.assertFalse(result.success)
        self.assertIn("Invalid regex", result.error)

    @patch("subprocess.run")
    @patch.object(ToolRegistry, "_has_ripgrep")
    def test_ripgrep_exit_139_sigsegv_unhandled(self, mock_has_rg, mock_run):
        """Ripgrep exit 139 (SIGSEGV) - currently unhandled."""
        mock_has_rg.return_value = True
        mock_result = MagicMock()
        mock_result.returncode = 139  # SIGSEGV
        mock_result.stdout = ""
        mock_result.stderr = "Segmentation fault"
        mock_run.return_value = mock_result

        result = self.registry.grep_files(".*", path=self.tmpdir)
        # Currently returns success for non-0, non-1, non-2 exit codes
        # This is a bug - should handle signal-based exits
        self.assertTrue(result.success)
        # No error reported for SIGSEGV


class TestToolResultFormattingEdgeCases(unittest.TestCase):
    """Test format_tool_result edge cases."""

    def test_format_result_with_none_output(self):
        """format_tool_result with None output."""
        tc = ToolCall("Read", {"path": "/test"}, "raw")
        result = ToolResult(True, output=None)

        formatted = format_tool_result(tc, result)
        self.assertIn("<tool_result>", formatted)
        self.assertIn("status: OK", formatted)
        # None output should be handled
        self.assertIsNotNone(formatted)

    def test_format_result_with_empty_error_but_failed(self):
        """format_tool_result with failed status but empty error."""
        tc = ToolCall("Bash", {"command": "false"}, "raw")
        result = ToolResult(False, output="", error="")

        formatted = format_tool_result(tc, result)
        self.assertIn("status: ERROR", formatted)
        self.assertIn("<tool_result>", formatted)

    def test_format_result_with_long_output_truncated(self):
        """format_tool_result truncates long output to 3000 chars."""
        tc = ToolCall("Read", {"path": "/test"}, "raw")
        long_output = "x" * 5000
        result = ToolResult(True, output=long_output)

        formatted = format_tool_result(tc, result)
        # Output should be truncated
        self.assertLess(len(formatted), len(long_output) + 200)

    def test_format_result_with_metadata(self):
        """format_tool_result includes metadata."""
        tc = ToolCall("Bash", {"command": "ls"}, "raw")
        result = ToolResult(True, output="file1\nfile2", metadata={"duration_ms": 100})

        formatted = format_tool_result(tc, result)
        self.assertIn("metadata:", formatted)
        self.assertIn("100", formatted)


class TestValidateParamsEdgeCases(unittest.TestCase):
    """Test ToolDefinition validate_params edge cases."""

    def test_validate_params_with_no_params_defined(self):
        """Validate params when tool has no parameters defined."""
        from agent.tool_schema import ToolDefinition

        tool_def = ToolDefinition(
            name="NoParams",
            description="Tool with no params",
            parameters=[],
            permission_level=0,
            execute=lambda: ToolResult(True),
        )

        # Should accept empty params dict
        valid, error = tool_def.validate_params({})
        self.assertTrue(valid)

    def test_validate_params_with_required_param_missing(self):
        """Validate params when required param is missing."""
        from agent.tool_schema import ToolDefinition, ToolParam, ParamType

        tool_def = ToolDefinition(
            name="RequiredParam",
            description="Test",
            parameters=[
                ToolParam("required_field", ParamType.STRING, "Required", required=True)
            ],
            permission_level=0,
            execute=lambda **kwargs: ToolResult(True),
        )

        # Missing required param should fail
        valid, error = tool_def.validate_params({})
        self.assertFalse(valid)


if __name__ == "__main__":
    unittest.main()
