#!/usr/bin/env python3
"""
Comprehensive unit tests for agent/tools.py

Tests the ToolResult class, ToolRegistry class and all tool implementations:
- Bash execution (with mocked persistent bash)
- File reading with line numbers
- File writing and creation
- File editing with string replacement
- Glob pattern matching
- Grep regex search (both ripgrep and Python fallback)
- Directory listing

File I/O is mocked to avoid actual filesystem operations.
"""

import os
import sys
import pathlib
import subprocess
from unittest.mock import Mock, MagicMock, patch, call, mock_open
import tempfile
import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.tools import ToolResult, ToolRegistry


class TestToolResultClass:
    """Test ToolResult class functionality."""

    def test_init_defaults(self):
        """Test ToolResult initialization with defaults."""
        result = ToolResult(success=True)
        assert result.success is True
        assert result.output == ""
        assert result.error == ""
        assert result.metadata == {}

    def test_init_all_params(self):
        """Test ToolResult initialization with all parameters."""
        metadata = {"key": "value"}
        result = ToolResult(
            success=False,
            output="output text",
            error="error text",
            metadata=metadata
        )
        assert result.success is False
        assert result.output == "output text"
        assert result.error == "error text"
        assert result.metadata == metadata

    def test_str_success(self):
        """Test __str__ returns output when successful."""
        result = ToolResult(success=True, output="success output")
        assert str(result) == "success output"

    def test_str_failure(self):
        """Test __str__ returns formatted error when failed."""
        result = ToolResult(success=False, error="something wrong")
        assert "Error:" in str(result)
        assert "something wrong" in str(result)

    def test_bool_success(self):
        """Test __bool__ returns True when successful."""
        result = ToolResult(success=True)
        assert bool(result) is True

    def test_bool_failure(self):
        """Test __bool__ returns False when failed."""
        result = ToolResult(success=False)
        assert bool(result) is False

    def test_repr(self):
        """Test __repr__ method."""
        result = ToolResult(success=True, output="test output")
        repr_str = repr(result)
        assert "OK" in repr_str
        assert "test output" in repr_str

        result_fail = ToolResult(success=False, error="test error")
        repr_str = repr(result_fail)
        assert "ERROR" in repr_str


class TestToolRegistryInit:
    """Test ToolRegistry initialization."""

    def test_init_default_working_dir(self):
        """Test initialization with default working directory."""
        registry = ToolRegistry()
        assert registry.working_dir == os.getcwd()
        assert registry._persistent_bash is None
        assert len(registry._tool_definitions) > 0

    def test_init_custom_working_dir(self):
        """Test initialization with custom working directory."""
        registry = ToolRegistry(working_dir="/tmp/test")
        assert registry.working_dir == "/tmp/test"

    def test_register_tools_contains_all_tools(self):
        """Test that all expected tools are registered."""
        registry = ToolRegistry()
        expected_tools = ["Bash", "Read", "Write", "Edit", "Glob", "Grep", "LS"]
        for tool_name in expected_tools:
            assert tool_name in registry._tool_definitions

    def test_get_all_tools_order(self):
        """Test that get_all_tools returns tools in correct order."""
        registry = ToolRegistry()
        tools = registry.get_all_tools()
        tool_names = [t.name for t in tools]
        expected_order = ["Bash", "Read", "Write", "Edit", "Glob", "Grep", "LS"]
        assert tool_names == expected_order


class TestToolRegistryGetTool:
    """Test tool lookup functionality."""

    def test_get_tool_exact_match(self):
        """Test exact tool name lookup."""
        registry = ToolRegistry()
        tool = registry.get_tool("Bash")
        assert tool is not None
        assert tool.name == "Bash"

    def test_get_tool_case_insensitive(self):
        """Test case-insensitive tool lookup."""
        registry = ToolRegistry()
        tool = registry.get_tool("bash")
        assert tool is not None
        assert tool.name == "Bash"

    def test_get_tool_not_found(self):
        """Test lookup of non-existent tool."""
        registry = ToolRegistry()
        tool = registry.get_tool("NonExistent")
        assert tool is None


class TestToolRegistryResolvePath:
    """Test path resolution."""

    def test_resolve_absolute_path(self):
        """Test that absolute paths are resolved as-is."""
        registry = ToolRegistry(working_dir="/home/user/project")
        resolved = registry._resolve_path("/tmp/file.txt")
        assert resolved == "/tmp/file.txt"

    def test_resolve_relative_path(self):
        """Test that relative paths are resolved relative to working dir."""
        registry = ToolRegistry(working_dir="/home/user/project")
        resolved = registry._resolve_path("src/main.py")
        assert "project/src/main.py" in resolved


class TestToolRegistryBash:
    """Test bash execution wrapper."""

    @patch("agent.tools.subprocess.run")
    def test_bash_uses_persistent_bash(self, mock_run):
        """Test that bash tries to use persistent bash session."""
        registry = ToolRegistry()

        with patch.object(registry, "_get_persistent_bash") as mock_get_bash:
            mock_bash = MagicMock()
            mock_bash.execute.return_value = ToolResult(success=True, output="test")
            mock_get_bash.return_value = mock_bash

            result = registry.bash("echo test")

            mock_get_bash.assert_called_once()
            mock_bash.execute.assert_called_once_with("echo test", timeout=120)
            assert result.success is True

    @patch("agent.tools.subprocess.run")
    def test_bash_fallback_on_exception(self, mock_run):
        """Test bash fallback when persistent bash fails."""
        registry = ToolRegistry()
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="fallback output",
            stderr=""
        )

        with patch.object(registry, "_get_persistent_bash") as mock_get_bash:
            mock_get_bash.side_effect = Exception("Failed")

            result = registry.bash("echo test")

            assert result.success is True
            assert "fallback output" in result.output

    def test_bash_fallback_subprocess(self):
        """Test _bash_fallback uses subprocess.run."""
        registry = ToolRegistry(working_dir="/tmp")

        with patch("agent.tools.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="output",
                stderr=""
            )

            result = registry._bash_fallback("echo test", timeout=30)

            assert result.success is True
            assert result.output == "output"
            mock_run.assert_called_once()

    def test_bash_fallback_timeout(self):
        """Test _bash_fallback handles timeout."""
        registry = ToolRegistry()

        with patch("agent.tools.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("bash", 30)

            result = registry._bash_fallback("sleep 100", timeout=30)

            assert result.success is False
            assert "timed out" in result.error

    def test_bash_fallback_exception(self):
        """Test _bash_fallback handles exceptions."""
        registry = ToolRegistry()

        with patch("agent.tools.subprocess.run") as mock_run:
            mock_run.side_effect = OSError("Command failed")

            result = registry._bash_fallback("bad command", timeout=30)

            assert result.success is False
            assert "failed" in result.error.lower()

    def test_close_bash(self):
        """Test closing bash session."""
        registry = ToolRegistry()
        mock_bash = MagicMock()
        registry._persistent_bash = mock_bash

        registry.close_bash()

        mock_bash.close.assert_called_once()
        assert registry._persistent_bash is None


class TestToolRegistryReadFile:
    """Test file reading functionality."""

    def test_read_file_not_found(self):
        """Test reading non-existent file."""
        registry = ToolRegistry()

        with patch("agent.tools.os.path.exists", return_value=False):
            result = registry.read_file("nonexistent.txt")

            assert result.success is False
            assert "not found" in result.error.lower()

    def test_read_file_is_directory(self):
        """Test that directories are rejected."""
        registry = ToolRegistry()

        with patch("agent.tools.os.path.exists", return_value=True):
            with patch("agent.tools.os.path.isdir", return_value=True):
                result = registry.read_file("directory")

                assert result.success is False
                assert "directory" in result.error.lower()

    def test_read_file_binary_file(self):
        """Test that binary files are rejected."""
        registry = ToolRegistry()

        with patch("agent.tools.os.path.exists", return_value=True):
            with patch("agent.tools.os.path.isdir", return_value=False):
                with patch("builtins.open", mock_open(read_data=b"binary\x00data")):
                    result = registry.read_file("binary.bin")

                    assert result.success is False
                    assert "binary" in result.error.lower()

    def test_read_file_success(self):
        """Test successful file read."""
        content = "line 1\nline 2\nline 3\n"
        registry = ToolRegistry()

        with patch("agent.tools.os.path.exists", return_value=True):
            with patch("agent.tools.os.path.isdir", return_value=False):
                with patch("builtins.open", mock_open(read_data=content)):
                    result = registry.read_file("test.txt")

                    assert result.success is True
                    assert "line 1" in result.output
                    assert "3 lines" in result.output

    def test_read_file_with_offset(self):
        """Test reading file with offset."""
        content = "line 1\nline 2\nline 3\nline 4\n"
        registry = ToolRegistry()

        with patch("agent.tools.os.path.exists", return_value=True):
            with patch("agent.tools.os.path.isdir", return_value=False):
                with patch("builtins.open", mock_open(read_data=content)):
                    result = registry.read_file("test.txt", offset=1, limit=2)

                    assert result.success is True
                    assert "line 2" in result.output
                    assert "line 3" in result.output
                    assert "line 1" not in result.output or "showing lines 2-3" in result.output

    def test_read_file_very_long_lines(self):
        """Test reading file with very long lines."""
        content = "x" * 3000 + "\n" + "y" * 100 + "\n"
        registry = ToolRegistry()

        with patch("agent.tools.os.path.exists", return_value=True):
            with patch("agent.tools.os.path.isdir", return_value=False):
                with patch("builtins.open", mock_open(read_data=content)):
                    result = registry.read_file("test.txt")

                    assert result.success is True
                    assert "..." in result.output  # Line truncation indicator

    def test_read_file_truncate_output(self):
        """Test output truncation when exceeds max_chars."""
        # Note: very long lines are truncated at 2000 chars first,
        # then overall output is truncated if it exceeds max_chars
        content = "x" * 50000 + "\ny" * 50000 + "\nz" * 50000 + "\n"
        registry = ToolRegistry()

        with patch("agent.tools.os.path.exists", return_value=True):
            with patch("agent.tools.os.path.isdir", return_value=False):
                with patch("builtins.open", mock_open(read_data=content)):
                    result = registry.read_file("test.txt", max_chars=30000)

                    assert result.success is True
                    assert "truncated" in result.output


class TestToolRegistryWriteFile:
    """Test file writing functionality."""

    def test_write_file_creates_file(self):
        """Test creating a new file."""
        registry = ToolRegistry()

        with patch("agent.tools.os.makedirs"):
            with patch("agent.tools.os.path.exists", return_value=False):
                with patch("builtins.open", mock_open()):
                    result = registry.write_file("new.txt", "content")

                    assert result.success is True
                    assert "Created" in result.output
                    assert "1 lines" in result.output

    def test_write_file_overwrites_existing(self):
        """Test overwriting existing file."""
        registry = ToolRegistry()

        with patch("agent.tools.os.makedirs"):
            with patch("agent.tools.os.path.exists", return_value=True):
                with patch("builtins.open", mock_open()):
                    result = registry.write_file("existing.txt", "new content")

                    assert result.success is True
                    assert "Updated" in result.output

    def test_write_file_creates_parent_dirs(self):
        """Test that parent directories are created."""
        registry = ToolRegistry()

        with patch("agent.tools.os.makedirs") as mock_makedirs:
            with patch("agent.tools.os.path.exists", return_value=False):
                with patch("builtins.open", mock_open()):
                    result = registry.write_file("dir/subdir/file.txt", "content")

                    assert result.success is True
                    mock_makedirs.assert_called_once()

    def test_write_file_multiline_content(self):
        """Test writing multiline content."""
        registry = ToolRegistry()

        with patch("agent.tools.os.makedirs"):
            with patch("agent.tools.os.path.exists", return_value=False):
                with patch("builtins.open", mock_open()):
                    result = registry.write_file("test.txt", "line1\nline2\nline3\n")

                    assert result.success is True
                    assert "3 lines" in result.output

    def test_write_file_exception(self):
        """Test handling write exceptions."""
        registry = ToolRegistry()

        with patch("agent.tools.os.makedirs"):
            with patch("agent.tools.os.path.exists", return_value=False):
                with patch("builtins.open", side_effect=IOError("Permission denied")):
                    result = registry.write_file("test.txt", "content")

                    assert result.success is False
                    assert "Failed to write" in result.error


class TestToolRegistryEditFile:
    """Test file editing functionality."""

    def test_edit_file_not_found(self):
        """Test editing non-existent file."""
        registry = ToolRegistry()

        with patch("agent.tools.os.path.exists", return_value=False):
            result = registry.edit_file("nonexistent.txt", "old", "new")

            assert result.success is False
            assert "not found" in result.error.lower()

    def test_edit_file_string_not_found(self):
        """Test editing when old_string is not found."""
        registry = ToolRegistry()

        with patch("agent.tools.os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data="content")):
                result = registry.edit_file("test.txt", "notfound", "new")

                assert result.success is False
                assert "not found" in result.error.lower()

    def test_edit_file_single_replacement(self):
        """Test replacing first occurrence with unique context."""
        registry = ToolRegistry()

        with patch("agent.tools.os.path.exists", return_value=True):
            m = mock_open(read_data="old unique old")
            with patch("builtins.open", m):
                result = registry.edit_file("test.txt", "old unique", "new unique")

                assert result.success is True
                assert "1 replacement" in result.output
                # Verify write was called
                m.assert_called()

    def test_edit_file_multiple_occurrences_without_replace_all(self):
        """Test error when multiple occurrences found without replace_all."""
        registry = ToolRegistry()

        with patch("agent.tools.os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data="old old old")):
                result = registry.edit_file("test.txt", "old", "new", replace_all=False)

                assert result.success is False
                assert "Found 3 occurrences" in result.error

    def test_edit_file_replace_all(self):
        """Test replace_all flag."""
        registry = ToolRegistry()

        with patch("agent.tools.os.path.exists", return_value=True):
            m = mock_open(read_data="old old old")
            with patch("builtins.open", m):
                result = registry.edit_file("test.txt", "old", "new", replace_all=True)

                assert result.success is True
                assert "3 replacement" in result.output
                # Verify write was called
                m.assert_called()

    def test_edit_file_exception(self):
        """Test handling edit exceptions."""
        registry = ToolRegistry()

        with patch("agent.tools.os.path.exists", return_value=True):
            with patch("builtins.open", side_effect=IOError("Failed")):
                result = registry.edit_file("test.txt", "old", "new")

                assert result.success is False
                assert "Failed to edit" in result.error


class TestToolRegistryGlobFiles:
    """Test glob pattern matching."""

    def test_glob_no_matches(self):
        """Test glob with no matches."""
        registry = ToolRegistry()

        with patch("agent.tools.pathlib.Path.glob", return_value=[]):
            result = registry.glob_files("**/*.nonexistent")

            assert result.success is True
            assert "No files matching" in result.output

    def test_glob_with_matches(self):
        """Test glob with file matches."""
        registry = ToolRegistry()

        mock_file = MagicMock()
        mock_file.parts = ("src", "main.py")
        mock_file.relative_to.return_value = pathlib.Path("src/main.py")
        mock_file.stat.return_value.st_mtime = 1000

        with patch("agent.tools.pathlib.Path.glob", return_value=[mock_file]):
            result = registry.glob_files("**/*.py")

            assert result.success is True
            assert "1 files matching" in result.output
            assert "src/main.py" in result.output

    def test_glob_excludes_common_dirs(self):
        """Test that glob excludes .git, __pycache__, etc."""
        registry = ToolRegistry()

        # Files that should be included
        good_file = MagicMock()
        good_file.parts = ("src", "main.py")
        good_file.relative_to.return_value = pathlib.Path("src/main.py")
        good_file.stat.return_value.st_mtime = 1000

        # Files that should be excluded
        bad_file = MagicMock()
        bad_file.parts = (".git", "config")
        bad_file.relative_to.return_value = pathlib.Path(".git/config")

        with patch("agent.tools.pathlib.Path.glob", return_value=[good_file, bad_file]):
            result = registry.glob_files("**/*")

            assert result.success is True
            # Only the good file should be in output
            assert "src/main.py" in result.output
            assert ".git" not in result.output

    def test_glob_sorts_by_mtime(self):
        """Test that results are sorted by modification time."""
        registry = ToolRegistry()

        file1 = MagicMock()
        file1.parts = ("newer.py",)
        file1.relative_to.return_value = pathlib.Path("newer.py")
        file1.stat.return_value.st_mtime = 2000

        file2 = MagicMock()
        file2.parts = ("older.py",)
        file2.relative_to.return_value = pathlib.Path("older.py")
        file2.stat.return_value.st_mtime = 1000

        with patch("agent.tools.pathlib.Path.glob", return_value=[file2, file1]):
            result = registry.glob_files("**/*.py")

            assert result.success is True
            # newer.py should come first (most recent)
            lines = result.output.split("\n")
            assert lines[1].strip() == "newer.py"

    def test_glob_exception(self):
        """Test glob exception handling."""
        registry = ToolRegistry()

        with patch("agent.tools.pathlib.Path.glob", side_effect=OSError("Failed")):
            result = registry.glob_files("**/*.py")

            assert result.success is False
            assert "Glob failed" in result.error


class TestToolRegistryGrepRipgrep:
    """Test grep with ripgrep."""

    def test_has_ripgrep_available(self):
        """Test ripgrep availability check."""
        with patch("agent.tools.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock()
            result = ToolRegistry._has_ripgrep()
            assert result is True

    def test_has_ripgrep_not_available(self):
        """Test when ripgrep is not available."""
        with patch("agent.tools.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()
            # Reset class cache
            ToolRegistry._ripgrep_available = None
            result = ToolRegistry._has_ripgrep()
            assert result is False

    def test_grep_ripgrep_basic_search(self):
        """Test ripgrep basic search."""
        registry = ToolRegistry()

        with patch.object(ToolRegistry, "_has_ripgrep", return_value=True):
            with patch("agent.tools.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout="file.py:1: match line\nfile.py:2: another match\n",
                    stderr=""
                )

                result = registry.grep_files("def ")

                assert result.success is True
                assert "2 match" in result.output

    def test_grep_ripgrep_no_matches(self):
        """Test ripgrep with no matches."""
        registry = ToolRegistry()

        with patch.object(ToolRegistry, "_has_ripgrep", return_value=True):
            with patch("agent.tools.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=1,
                    stdout="",
                    stderr=""
                )

                result = registry.grep_files("nonexistent")

                assert result.success is True
                assert "No matches" in result.output

    def test_grep_ripgrep_invalid_regex(self):
        """Test ripgrep with invalid regex."""
        registry = ToolRegistry()

        with patch.object(ToolRegistry, "_has_ripgrep", return_value=True):
            with patch("agent.tools.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=2,
                    stdout="",
                    stderr="regex syntax error"
                )

                result = registry.grep_files("[invalid")

                assert result.success is False
                assert "Invalid regex" in result.error

    def test_grep_ripgrep_timeout(self):
        """Test ripgrep timeout."""
        registry = ToolRegistry()

        with patch.object(ToolRegistry, "_has_ripgrep", return_value=True):
            with patch("agent.tools.subprocess.run") as mock_run:
                mock_run.side_effect = subprocess.TimeoutExpired("rg", 30)

                result = registry.grep_files("test")

                assert result.success is False
                assert "timed out" in result.error


class TestToolRegistryGrepPython:
    """Test grep with Python fallback."""

    def test_grep_python_basic_search(self):
        """Test Python grep basic search."""
        registry = ToolRegistry()

        with patch.object(ToolRegistry, "_has_ripgrep", return_value=False):
            with patch("agent.tools.pathlib.Path.glob") as mock_glob:
                mock_file = MagicMock()
                mock_file.is_file.return_value = True
                mock_file.parts = ("test.py",)
                mock_file.relative_to.return_value = pathlib.Path("test.py")

                mock_glob.return_value = [mock_file]

                with patch("builtins.open", mock_open(read_data="def test():\n    pass\n")):
                    result = registry.grep_files("def ")

                    assert result.success is True
                    assert "1 match" in result.output

    def test_grep_python_invalid_regex(self):
        """Test Python grep with invalid regex."""
        registry = ToolRegistry()

        with patch.object(ToolRegistry, "_has_ripgrep", return_value=False):
            result = registry.grep_files("[invalid")

            assert result.success is False
            assert "Invalid regex" in result.error

    def test_grep_python_case_insensitive(self):
        """Test case-insensitive search."""
        registry = ToolRegistry()

        with patch.object(ToolRegistry, "_has_ripgrep", return_value=False):
            with patch("agent.tools.pathlib.Path.glob") as mock_glob:
                mock_file = MagicMock()
                mock_file.is_file.return_value = True
                mock_file.parts = ("test.py",)
                mock_file.relative_to.return_value = pathlib.Path("test.py")

                mock_glob.return_value = [mock_file]

                with patch("builtins.open", mock_open(read_data="TEST\ntest\n")):
                    result = registry.grep_files("test", case_insensitive=True)

                    assert result.success is True

    def test_grep_python_excludes_binary(self):
        """Test that binary files are skipped."""
        registry = ToolRegistry()

        with patch.object(ToolRegistry, "_has_ripgrep", return_value=False):
            with patch("agent.tools.pathlib.Path.glob") as mock_glob:
                mock_file = MagicMock()
                mock_file.is_file.return_value = True
                mock_file.parts = ("binary.bin",)
                mock_file.relative_to.return_value = pathlib.Path("binary.bin")

                mock_glob.return_value = [mock_file]

                with patch("builtins.open", side_effect=UnicodeDecodeError("utf-8", b"", 0, 1, "invalid")):
                    result = registry.grep_files("test")

                    assert result.success is True
                    assert "No matches" in result.output


class TestToolRegistryListDir:
    """Test directory listing."""

    def test_list_dir_not_found(self):
        """Test listing non-existent directory."""
        registry = ToolRegistry()

        with patch("agent.tools.pathlib.Path.exists", return_value=False):
            result = registry.list_dir("/nonexistent")

            assert result.success is False
            assert "not found" in result.error.lower()

    def test_list_dir_is_file(self):
        """Test listing a file instead of directory."""
        registry = ToolRegistry()

        with patch("agent.tools.pathlib.Path.exists", return_value=True):
            with patch("agent.tools.pathlib.Path.is_dir", return_value=False):
                result = registry.list_dir("file.txt")

                assert result.success is False
                assert "not a directory" in result.error.lower()

    def test_list_dir_basic(self):
        """Test basic directory listing."""
        registry = ToolRegistry()

        mock_dir = MagicMock()
        mock_dir.exists.return_value = True
        mock_dir.is_dir.return_value = True

        mock_file = MagicMock()
        mock_file.name = "test.py"
        mock_file.is_dir.return_value = False
        mock_file.stat.return_value.st_size = 1024

        mock_dir.iterdir.return_value = [mock_file]

        with patch("agent.tools.pathlib.Path", return_value=mock_dir):
            result = registry.list_dir("/tmp")

            assert result.success is True
            assert "test.py" in result.output
            assert "1.0K" in result.output

    def test_list_dir_directories_first(self):
        """Test that directories are listed first."""
        registry = ToolRegistry()

        mock_dir = MagicMock()
        mock_dir.exists.return_value = True
        mock_dir.is_dir.return_value = True

        mock_subdir = MagicMock()
        mock_subdir.name = "subdir"
        mock_subdir.is_dir.return_value = True

        mock_file = MagicMock()
        mock_file.name = "file.py"
        mock_file.is_dir.return_value = False
        mock_file.stat.return_value.st_size = 100

        mock_dir.iterdir.return_value = [mock_file, mock_subdir]

        with patch("agent.tools.pathlib.Path", return_value=mock_dir):
            result = registry.list_dir("/tmp")

            assert result.success is True
            lines = result.output.split("\n")[1:]  # Skip header
            # subdir should come before file
            subdir_line = [l for l in lines if "subdir/" in l][0]
            file_line = [l for l in lines if "file.py" in l][0]
            assert lines.index(subdir_line) < lines.index(file_line)

    def test_list_dir_excludes_special_dirs(self):
        """Test that special directories are excluded."""
        registry = ToolRegistry()

        mock_dir = MagicMock()
        mock_dir.exists.return_value = True
        mock_dir.is_dir.return_value = True

        mock_git = MagicMock()
        mock_git.name = ".git"
        mock_git.is_dir.return_value = True

        mock_venv = MagicMock()
        mock_venv.name = ".venv"
        mock_venv.is_dir.return_value = True

        mock_dir.iterdir.return_value = [mock_git, mock_venv]

        with patch("agent.tools.pathlib.Path", return_value=mock_dir):
            result = registry.list_dir("/tmp")

            assert ".git" not in result.output
            assert ".venv" not in result.output

    def test_list_dir_file_sizes(self):
        """Test file size formatting."""
        registry = ToolRegistry()

        mock_dir = MagicMock()
        mock_dir.exists.return_value = True
        mock_dir.is_dir.return_value = True

        # Test different file sizes
        small_file = MagicMock()
        small_file.name = "small.txt"
        small_file.is_dir.return_value = False
        small_file.stat.return_value.st_size = 100  # 100 bytes

        med_file = MagicMock()
        med_file.name = "medium.bin"
        med_file.is_dir.return_value = False
        med_file.stat.return_value.st_size = 1024 * 100  # 100 KB

        large_file = MagicMock()
        large_file.name = "large.iso"
        large_file.is_dir.return_value = False
        large_file.stat.return_value.st_size = 1024 * 1024 * 10  # 10 MB

        mock_dir.iterdir.return_value = [small_file, med_file, large_file]

        with patch("agent.tools.pathlib.Path", return_value=mock_dir):
            result = registry.list_dir("/tmp")

            assert "100B" in result.output
            assert "100.0K" in result.output
            assert "10.0M" in result.output


class TestToolRegistryExecWrappers:
    """Test tool execution wrappers."""

    def test_exec_bash_adds_metadata(self):
        """Test that _exec_bash adds duration metadata."""
        registry = ToolRegistry()

        with patch.object(registry, "bash") as mock_bash:
            mock_bash.return_value = ToolResult(success=True, output="test")

            # Patch time module at import location
            import time as time_module
            with patch.object(time_module, "time") as mock_time:
                mock_time.side_effect = [0, 0.1]  # 100ms elapsed

                result = registry._exec_bash("echo test")

                assert "duration_ms" in result.metadata
                assert result.metadata["duration_ms"] >= 99  # Allow some tolerance

    def test_exec_read_adds_metadata(self):
        """Test that _exec_read adds file metadata."""
        registry = ToolRegistry()

        with patch.object(registry, "read_file") as mock_read:
            mock_read.return_value = ToolResult(success=True, output="# test.txt (3 lines)\n1\tline1\n2\tline2\n3\tline3")

            result = registry._exec_read("test.txt")

            assert "file_path" in result.metadata
            assert "lines_in_output" in result.metadata

    def test_exec_write_adds_metadata(self):
        """Test that _exec_write adds write metadata."""
        registry = ToolRegistry()

        with patch.object(registry, "write_file") as mock_write:
            mock_write.return_value = ToolResult(success=True, output="Created test.txt (2 lines)")

            result = registry._exec_write("test.txt", "line1\nline2")

            assert "file_path" in result.metadata
            assert "bytes_written" in result.metadata
            assert "lines_written" in result.metadata

    def test_exec_glob_adds_metadata(self):
        """Test that _exec_glob adds glob metadata."""
        registry = ToolRegistry()

        with patch.object(registry, "glob_files") as mock_glob:
            mock_glob.return_value = ToolResult(success=True, output="# 5 files matching '**/*.py'\nfile1.py\nfile2.py")

            result = registry._exec_glob("**/*.py")

            assert "pattern" in result.metadata
            assert "files_matched" in result.metadata
            assert result.metadata["files_matched"] == 5

    def test_exec_ls_adds_metadata(self):
        """Test that _exec_ls adds entry count metadata."""
        registry = ToolRegistry()

        with patch.object(registry, "list_dir") as mock_ls:
            mock_ls.return_value = ToolResult(success=True, output="# /tmp (3 entries)\n  file1\n  dir1/\n  file2")

            result = registry._exec_ls()

            assert "entry_count" in result.metadata


class TestTruncateOutput:
    """Test output truncation utility."""

    def test_truncate_output_no_truncation(self):
        """Test truncation when within limit."""
        result = ToolRegistry._truncate_output("short", max_chars=1000)
        assert result == "short"

    def test_truncate_output_middle_truncation(self):
        """Test middle truncation."""
        text = "a" * 100
        result = ToolRegistry._truncate_output(text, max_chars=60)

        assert "truncated" in result
        assert text[:30] in result
        assert text[-30:] in result
        assert len(result) <= 100


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
