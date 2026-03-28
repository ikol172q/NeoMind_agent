#!/usr/bin/env python3
"""
Comprehensive unit tests for agent/persistent_bash.py

Tests the PersistentBash class which manages a persistent subprocess.Popen
bash session with state preservation across commands.

Mocks are used to avoid spawning real shell processes.
"""

import os
import sys
import threading
import queue
import time
import subprocess
from unittest.mock import Mock, MagicMock, patch, call
import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.persistent_bash import PersistentBash
from agent.tools import ToolResult


class TestToolResult:
    """Test ToolResult class."""

    def test_tool_result_success(self):
        """Test ToolResult with success=True."""
        result = ToolResult(success=True, output="Success output")
        assert result.success is True
        assert result.output == "Success output"
        assert result.error == ""
        assert result.metadata == {}

    def test_tool_result_failure(self):
        """Test ToolResult with success=False."""
        result = ToolResult(success=False, error="Something failed")
        assert result.success is False
        assert result.error == "Something failed"
        assert result.output == ""

    def test_tool_result_with_metadata(self):
        """Test ToolResult with metadata."""
        metadata = {"key": "value", "count": 42}
        result = ToolResult(success=True, output="test", metadata=metadata)
        assert result.metadata == metadata

    def test_tool_result_str_success(self):
        """Test __str__ on successful result."""
        result = ToolResult(success=True, output="test output")
        assert str(result) == "test output"

    def test_tool_result_str_failure(self):
        """Test __str__ on failed result."""
        result = ToolResult(success=False, error="test error")
        assert "Error: test error" in str(result)

    def test_tool_result_bool_success(self):
        """Test __bool__ on successful result."""
        result = ToolResult(success=True)
        assert bool(result) is True

    def test_tool_result_bool_failure(self):
        """Test __bool__ on failed result."""
        result = ToolResult(success=False)
        assert bool(result) is False

    def test_tool_result_repr(self):
        """Test __repr__ method."""
        result = ToolResult(success=True, output="test output")
        repr_str = repr(result)
        assert "OK" in repr_str
        assert "test output" in repr_str


class TestPersistentBashInit:
    """Test PersistentBash initialization."""

    @patch("agent.persistent_bash.subprocess.Popen")
    @patch("agent.persistent_bash.threading.Thread")
    def test_init_default_params(self, mock_thread, mock_popen):
        """Test initialization with default parameters."""
        mock_proc = MagicMock()
        mock_proc.stdout = MagicMock()
        mock_proc.stderr = MagicMock()
        mock_popen.return_value = mock_proc

        bash = PersistentBash()

        assert bash.timeout == 120
        assert bash.max_output == 30000
        assert bash.proc == mock_proc

        # Verify Popen was called with correct arguments
        mock_popen.assert_called_once()
        call_args = mock_popen.call_args
        assert call_args[0][0] == ["bash", "--norc", "--noprofile"]
        assert call_args[1]["stdin"] == subprocess.PIPE
        assert call_args[1]["stdout"] == subprocess.PIPE
        assert call_args[1]["stderr"] == subprocess.PIPE
        assert call_args[1]["text"] is True

    @patch("agent.persistent_bash.subprocess.Popen")
    @patch("agent.persistent_bash.threading.Thread")
    def test_init_custom_working_dir(self, mock_thread, mock_popen):
        """Test initialization with custom working directory."""
        mock_proc = MagicMock()
        mock_proc.stdout = MagicMock()
        mock_proc.stderr = MagicMock()
        mock_popen.return_value = mock_proc

        bash = PersistentBash(working_dir="/tmp/test")

        call_args = mock_popen.call_args
        assert call_args[1]["cwd"] == "/tmp/test"

    @patch("agent.persistent_bash.subprocess.Popen")
    @patch("agent.persistent_bash.threading.Thread")
    def test_init_custom_timeout_and_max_output(self, mock_thread, mock_popen):
        """Test initialization with custom timeout and max_output."""
        mock_proc = MagicMock()
        mock_proc.stdout = MagicMock()
        mock_proc.stderr = MagicMock()
        mock_popen.return_value = mock_proc

        bash = PersistentBash(timeout=60, max_output=50000)

        assert bash.timeout == 60
        assert bash.max_output == 50000

    @patch("agent.persistent_bash.subprocess.Popen")
    @patch("agent.persistent_bash.threading.Thread")
    def test_init_sentinel_uniqueness(self, mock_thread, mock_popen):
        """Test that sentinel values are unique per instance."""
        mock_proc = MagicMock()
        mock_proc.stdout = MagicMock()
        mock_proc.stderr = MagicMock()
        mock_popen.return_value = mock_proc

        bash1 = PersistentBash()
        bash2 = PersistentBash()

        assert bash1._sentinel != bash2._sentinel
        assert bash1._exit_code_marker != bash2._exit_code_marker

    @patch("agent.persistent_bash.subprocess.Popen")
    @patch("agent.persistent_bash.threading.Thread")
    def test_init_reader_threads_started(self, mock_thread, mock_popen):
        """Test that reader threads are started."""
        mock_proc = MagicMock()
        mock_proc.stdout = MagicMock()
        mock_proc.stderr = MagicMock()
        mock_popen.return_value = mock_proc

        with patch("agent.persistent_bash.time.sleep"):
            bash = PersistentBash()

        # Should have created 2 threads (stdout and stderr)
        assert mock_thread.call_count == 2
        # Each thread should be started
        assert all(call().start() in mock_thread.mock_calls for _ in range(2))


class TestPersistentBashReader:
    """Test reader thread functionality."""

    def test_reader_reads_lines(self):
        """Test that _reader reads lines from stream."""
        q = queue.Queue()
        mock_stream = MagicMock()
        mock_stream.readline.side_effect = ["line1\n", "line2\n", "line3\n", ""]

        PersistentBash._reader(mock_stream, q)

        assert q.qsize() == 3
        assert q.get_nowait() == "line1\n"
        assert q.get_nowait() == "line2\n"
        assert q.get_nowait() == "line3\n"

    def test_reader_handles_closed_stream(self):
        """Test that _reader handles closed stream gracefully."""
        q = queue.Queue()
        mock_stream = MagicMock()
        mock_stream.readline.side_effect = ValueError("Stream closed")

        # Should not raise
        PersistentBash._reader(mock_stream, q)
        assert q.empty()

    def test_reader_handles_oserror(self):
        """Test that _reader handles OSError gracefully."""
        q = queue.Queue()
        mock_stream = MagicMock()
        mock_stream.readline.side_effect = OSError("Bad file descriptor")

        # Should not raise
        PersistentBash._reader(mock_stream, q)
        assert q.empty()

    def test_drain_queue_empty(self):
        """Test draining an empty queue."""
        q = queue.Queue()
        result = PersistentBash._drain_queue(q)
        assert result == ""

    def test_drain_queue_with_lines(self):
        """Test draining a queue with lines."""
        q = queue.Queue()
        q.put("line1\n")
        q.put("line2\n")
        q.put("line3\n")

        result = PersistentBash._drain_queue(q)
        assert result == "line1\nline2\nline3\n"
        assert q.empty()


class TestPersistentBashExecute:
    """Test command execution."""

    @patch("agent.persistent_bash.subprocess.Popen")
    @patch("agent.persistent_bash.threading.Thread")
    def test_execute_simple_success(self, mock_thread, mock_popen):
        """Test executing a simple successful command."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # Process alive
        mock_proc.stdin = MagicMock()
        mock_proc.stdout = MagicMock()
        mock_proc.stderr = MagicMock()
        mock_popen.return_value = mock_proc

        with patch("agent.persistent_bash.time.sleep"):
            with patch("agent.persistent_bash.time.time") as mock_time:
                mock_time.side_effect = [0, 0.01, 0.02, 0.03, 0.04]  # Simulate time passing
                bash = PersistentBash()

                # Mock queue behavior
                with patch.object(bash, "_stdout_q") as mock_stdout_q:
                    with patch.object(bash, "_stderr_q") as mock_stderr_q:
                        # Simulate sentinel being returned
                        mock_stdout_q.get.side_effect = [
                            "output line\n",
                            f"{bash._exit_code_marker}0\n",
                            f"{bash._sentinel}\n",
                        ]
                        mock_stderr_q.get.side_effect = queue.Empty

                        result = bash.execute("echo test")

                        assert result.success is True
                        assert "output line" in result.output

    @patch("agent.persistent_bash.subprocess.Popen")
    @patch("agent.persistent_bash.threading.Thread")
    def test_execute_with_exit_code(self, mock_thread, mock_popen):
        """Test executing a command that returns non-zero exit code."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.stdin = MagicMock()
        mock_popen.return_value = mock_proc

        with patch("agent.persistent_bash.time.sleep"):
            with patch("agent.persistent_bash.time.time") as mock_time:
                mock_time.side_effect = [0] + [0.01] * 10
                bash = PersistentBash()

                with patch.object(bash, "_stdout_q") as mock_stdout_q:
                    with patch.object(bash, "_stderr_q") as mock_stderr_q:
                        mock_stdout_q.get.side_effect = [
                            f"{bash._exit_code_marker}1\n",
                            f"{bash._sentinel}\n",
                        ]
                        mock_stderr_q.get.side_effect = queue.Empty

                        result = bash.execute("false")

                        assert result.success is False
                        assert "Exit code: 1" in result.error

    @patch("agent.persistent_bash.subprocess.Popen")
    @patch("agent.persistent_bash.threading.Thread")
    def test_execute_timeout(self, mock_thread, mock_popen):
        """Test command timeout."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.stdin = MagicMock()
        mock_popen.return_value = mock_proc

        with patch("agent.persistent_bash.time.sleep"):
            with patch("agent.persistent_bash.time.time") as mock_time:
                # Time exceeds timeout
                mock_time.side_effect = [0, 10, 20, 130]
                bash = PersistentBash(timeout=120)

                with patch.object(bash, "_stdout_q") as mock_stdout_q:
                    with patch.object(bash, "_stderr_q") as mock_stderr_q:
                        mock_stdout_q.get.side_effect = queue.Empty
                        mock_stderr_q.get.side_effect = queue.Empty

                        result = bash.execute("sleep 1000")

                        assert result.success is False
                        assert "timed out" in result.error

    @patch("agent.persistent_bash.subprocess.Popen")
    @patch("agent.persistent_bash.threading.Thread")
    def test_execute_process_died(self, mock_thread, mock_popen):
        """Test when process dies unexpectedly."""
        mock_proc = MagicMock()
        mock_proc.poll.side_effect = [None, None, 1]  # Eventually returns exit code
        mock_proc.stdin = MagicMock()
        mock_popen.return_value = mock_proc

        with patch("agent.persistent_bash.time.sleep"):
            with patch("agent.persistent_bash.time.time") as mock_time:
                mock_time.side_effect = [0, 0.01, 0.02, 0.03]
                bash = PersistentBash()

                with patch.object(bash, "_stdout_q") as mock_stdout_q:
                    with patch.object(bash, "_stderr_q") as mock_stderr_q:
                        with patch.object(bash, "_drain_queue", return_value=""):
                            mock_stdout_q.get.side_effect = queue.Empty
                            mock_stderr_q.get.side_effect = queue.Empty

                            result = bash.execute("test")

                            assert result.success is False
                            assert "terminated" in result.error

    @patch("agent.persistent_bash.subprocess.Popen")
    @patch("agent.persistent_bash.threading.Thread")
    def test_execute_broken_pipe(self, mock_thread, mock_popen):
        """Test handling of broken pipe error."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.stdin = MagicMock()
        mock_proc.stdin.write.side_effect = BrokenPipeError()
        mock_popen.return_value = mock_proc

        with patch("agent.persistent_bash.time.sleep"):
            bash = PersistentBash()
            result = bash.execute("test")

            assert result.success is False
            assert "Bash session pipe broken" in result.error

    @patch("agent.persistent_bash.subprocess.Popen")
    @patch("agent.persistent_bash.threading.Thread")
    def test_execute_is_alive_check(self, mock_thread, mock_popen):
        """Test that execute checks if process is alive."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1  # Process is dead
        mock_popen.return_value = mock_proc

        with patch("agent.persistent_bash.time.sleep"):
            bash = PersistentBash()
            result = bash.execute("test")

            assert result.success is False
            assert "Bash session has terminated" in result.error

    @patch("agent.persistent_bash.subprocess.Popen")
    @patch("agent.persistent_bash.threading.Thread")
    def test_execute_custom_timeout(self, mock_thread, mock_popen):
        """Test execute with custom timeout override."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.stdin = MagicMock()
        mock_popen.return_value = mock_proc

        with patch("agent.persistent_bash.time.sleep"):
            with patch("agent.persistent_bash.time.time") as mock_time:
                mock_time.side_effect = [0, 10, 20, 65]  # Custom timeout=60
                bash = PersistentBash(timeout=120)

                with patch.object(bash, "_stdout_q") as mock_stdout_q:
                    with patch.object(bash, "_stderr_q") as mock_stderr_q:
                        mock_stdout_q.get.side_effect = queue.Empty
                        mock_stderr_q.get.side_effect = queue.Empty

                        result = bash.execute("test", timeout=60)

                        assert result.success is False
                        assert "timed out" in result.error


class TestPersistentBashFormatOutput:
    """Test output formatting."""

    @patch("agent.persistent_bash.subprocess.Popen")
    @patch("agent.persistent_bash.threading.Thread")
    def test_format_output_stdout_only(self, mock_thread, mock_popen):
        """Test formatting stdout only."""
        mock_proc = MagicMock()
        mock_proc.stdout = MagicMock()
        mock_proc.stderr = MagicMock()
        mock_popen.return_value = mock_proc

        with patch("agent.persistent_bash.time.sleep"):
            bash = PersistentBash()
            result = bash._format_output(["line1\n", "line2\n"], [])
            assert result == "line1\nline2"

    @patch("agent.persistent_bash.subprocess.Popen")
    @patch("agent.persistent_bash.threading.Thread")
    def test_format_output_stderr_only(self, mock_thread, mock_popen):
        """Test formatting stderr only."""
        mock_proc = MagicMock()
        mock_proc.stdout = MagicMock()
        mock_proc.stderr = MagicMock()
        mock_popen.return_value = mock_proc

        with patch("agent.persistent_bash.time.sleep"):
            bash = PersistentBash()
            result = bash._format_output([], ["error\n"])
            assert result == "error"

    @patch("agent.persistent_bash.subprocess.Popen")
    @patch("agent.persistent_bash.threading.Thread")
    def test_format_output_both(self, mock_thread, mock_popen):
        """Test formatting both stdout and stderr."""
        mock_proc = MagicMock()
        mock_proc.stdout = MagicMock()
        mock_proc.stderr = MagicMock()
        mock_popen.return_value = mock_proc

        with patch("agent.persistent_bash.time.sleep"):
            bash = PersistentBash()
            result = bash._format_output(["output\n"], ["error\n"])
            assert "output" in result
            assert "STDERR:" in result
            assert "error" in result

    @patch("agent.persistent_bash.subprocess.Popen")
    @patch("agent.persistent_bash.threading.Thread")
    def test_format_output_empty(self, mock_thread, mock_popen):
        """Test formatting empty output."""
        mock_proc = MagicMock()
        mock_proc.stdout = MagicMock()
        mock_proc.stderr = MagicMock()
        mock_popen.return_value = mock_proc

        with patch("agent.persistent_bash.time.sleep"):
            bash = PersistentBash()
            result = bash._format_output([], [])
            assert result == ""


class TestPersistentBashTruncate:
    """Test output truncation."""

    @patch("agent.persistent_bash.subprocess.Popen")
    @patch("agent.persistent_bash.threading.Thread")
    def test_truncate_middle_no_truncation(self, mock_thread, mock_popen):
        """Test truncation when output is within limit."""
        mock_proc = MagicMock()
        mock_proc.stdout = MagicMock()
        mock_proc.stderr = MagicMock()
        mock_popen.return_value = mock_proc

        with patch("agent.persistent_bash.time.sleep"):
            bash = PersistentBash(max_output=1000)
            text = "short text"
            result = bash._truncate_middle(text)
            assert result == text

    @patch("agent.persistent_bash.subprocess.Popen")
    @patch("agent.persistent_bash.threading.Thread")
    def test_truncate_middle_with_truncation(self, mock_thread, mock_popen):
        """Test truncation when output exceeds limit."""
        mock_proc = MagicMock()
        mock_proc.stdout = MagicMock()
        mock_proc.stderr = MagicMock()
        mock_popen.return_value = mock_proc

        with patch("agent.persistent_bash.time.sleep"):
            bash = PersistentBash(max_output=100)
            text = "x" * 200
            result = bash._truncate_middle(text)

            assert len(result) <= 200  # Includes header
            assert "truncated" in result
            assert text[:50] in result  # Start preserved
            assert text[-50:] in result  # End preserved


class TestPersistentBashGetCwd:
    """Test get_cwd method."""

    @patch("agent.persistent_bash.subprocess.Popen")
    @patch("agent.persistent_bash.threading.Thread")
    def test_get_cwd_success(self, mock_thread, mock_popen):
        """Test get_cwd when pwd succeeds."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.stdin = MagicMock()
        mock_popen.return_value = mock_proc

        with patch("agent.persistent_bash.time.sleep"):
            bash = PersistentBash()

            with patch.object(bash, "execute") as mock_execute:
                mock_execute.return_value = ToolResult(success=True, output="/tmp/test")
                result = bash.get_cwd()

                assert result == "/tmp/test"
                mock_execute.assert_called_once_with("pwd", timeout=5)

    @patch("agent.persistent_bash.subprocess.Popen")
    @patch("agent.persistent_bash.threading.Thread")
    def test_get_cwd_fallback(self, mock_thread, mock_popen):
        """Test get_cwd fallback when pwd fails."""
        mock_proc = MagicMock()
        mock_proc.stdout = MagicMock()
        mock_proc.stderr = MagicMock()
        mock_popen.return_value = mock_proc

        with patch("agent.persistent_bash.time.sleep"):
            bash = PersistentBash()

            with patch.object(bash, "execute") as mock_execute:
                mock_execute.return_value = ToolResult(success=False, error="Failed")
                with patch("agent.persistent_bash.os.getcwd", return_value="/home/user"):
                    result = bash.get_cwd()

                    assert result == "/home/user"


class TestPersistentBashClose:
    """Test close and cleanup."""

    @patch("agent.persistent_bash.subprocess.Popen")
    @patch("agent.persistent_bash.threading.Thread")
    def test_close_success(self, mock_thread, mock_popen):
        """Test closing the bash session."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.stdin = MagicMock()
        mock_popen.return_value = mock_proc

        with patch("agent.persistent_bash.time.sleep"):
            bash = PersistentBash()
            bash.close()

            mock_proc.stdin.write.assert_called_with("exit\n")
            mock_proc.stdin.flush.assert_called()
            mock_proc.wait.assert_called()

    @patch("agent.persistent_bash.subprocess.Popen")
    @patch("agent.persistent_bash.threading.Thread")
    def test_close_timeout_kills_process(self, mock_thread, mock_popen):
        """Test that close kills process on timeout."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.stdin = MagicMock()
        # First wait with timeout raises, second wait (after kill) succeeds
        mock_proc.wait.side_effect = [subprocess.TimeoutExpired("bash", 5), None]
        mock_popen.return_value = mock_proc

        with patch("agent.persistent_bash.time.sleep"):
            bash = PersistentBash()
            bash.close()

            mock_proc.kill.assert_called()

    @patch("agent.persistent_bash.subprocess.Popen")
    @patch("agent.persistent_bash.threading.Thread")
    def test_close_broken_pipe(self, mock_thread, mock_popen):
        """Test close handles broken pipe."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.stdin = MagicMock()
        mock_proc.stdin.write.side_effect = BrokenPipeError()
        mock_popen.return_value = mock_proc

        with patch("agent.persistent_bash.time.sleep"):
            bash = PersistentBash()
            bash.close()  # Should not raise

            mock_proc.kill.assert_called()

    @patch("agent.persistent_bash.subprocess.Popen")
    @patch("agent.persistent_bash.threading.Thread")
    def test_close_already_dead(self, mock_thread, mock_popen):
        """Test close when process is already dead."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1  # Dead
        mock_popen.return_value = mock_proc

        with patch("agent.persistent_bash.time.sleep"):
            bash = PersistentBash()
            bash.close()

            # Should not attempt to write to stdin
            mock_proc.stdin.write.assert_not_called()

    @patch("agent.persistent_bash.subprocess.Popen")
    @patch("agent.persistent_bash.threading.Thread")
    def test_del_calls_close(self, mock_thread, mock_popen):
        """Test that __del__ calls close."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.stdin = MagicMock()
        mock_popen.return_value = mock_proc

        with patch("agent.persistent_bash.time.sleep"):
            bash = PersistentBash()

            with patch.object(bash, "close") as mock_close:
                bash.__del__()
                mock_close.assert_called_once()


class TestPersistentBashIsAlive:
    """Test is_alive check."""

    @patch("agent.persistent_bash.subprocess.Popen")
    @patch("agent.persistent_bash.threading.Thread")
    def test_is_alive_true(self, mock_thread, mock_popen):
        """Test _is_alive when process is running."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        with patch("agent.persistent_bash.time.sleep"):
            bash = PersistentBash()
            assert bash._is_alive() is True

    @patch("agent.persistent_bash.subprocess.Popen")
    @patch("agent.persistent_bash.threading.Thread")
    def test_is_alive_false(self, mock_thread, mock_popen):
        """Test _is_alive when process is dead."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1  # Exited with code 1
        mock_popen.return_value = mock_proc

        with patch("agent.persistent_bash.time.sleep"):
            bash = PersistentBash()
            assert bash._is_alive() is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
