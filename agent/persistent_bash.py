"""
Persistent Bash session for coding mode.

Like Claude CLI's Bash tool — a single bash process that persists across
all /run commands. cd, export, source all carry forward.

Implementation:
- subprocess.Popen with pipes (stdin/stdout/stderr)
- Sentinel pattern to detect command completion
- Reader threads for non-blocking stdout/stderr collection
- Timeout support (default 120s)
- Output truncation (default 30K chars, middle-truncation)
"""

import os
import subprocess
import threading
import queue
import time
from typing import Optional

from agent.tools import ToolResult


class PersistentBash:
    """Persistent bash session that maintains state across commands.

    Usage:
        bash = PersistentBash(working_dir="/path/to/project")
        result = bash.execute("cd src")
        result = bash.execute("ls")          # shows src/ contents
        result = bash.execute("echo $PWD")   # shows /path/to/project/src
        bash.close()
    """

    def __init__(
        self,
        working_dir: Optional[str] = None,
        timeout: int = 120,
        max_output: int = 30000,
    ):
        self.timeout = timeout
        self.max_output = max_output
        self._sentinel = f"__IKOL_DONE_{os.getpid()}_{id(self)}__"
        self._exit_code_marker = f"__IKOL_EXIT_{os.getpid()}_{id(self)}__"

        self.proc = subprocess.Popen(
            ["bash", "--norc", "--noprofile"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=working_dir or os.getcwd(),
            bufsize=0,
            env={**os.environ, "PS1": "", "PS2": "", "PROMPT_COMMAND": ""},
        )

        # Queues for non-blocking reads
        self._stdout_q: queue.Queue = queue.Queue()
        self._stderr_q: queue.Queue = queue.Queue()

        # Reader threads
        self._stdout_thread = threading.Thread(
            target=self._reader, args=(self.proc.stdout, self._stdout_q), daemon=True
        )
        self._stderr_thread = threading.Thread(
            target=self._reader, args=(self.proc.stderr, self._stderr_q), daemon=True
        )
        self._stdout_thread.start()
        self._stderr_thread.start()

        # Drain any startup output
        time.sleep(0.05)
        self._drain_queue(self._stdout_q)
        self._drain_queue(self._stderr_q)

    @staticmethod
    def _reader(stream, q: queue.Queue):
        """Read lines from stream and put them in queue."""
        try:
            for line in iter(stream.readline, ""):
                q.put(line)
        except (ValueError, OSError):
            pass  # Stream closed

    @staticmethod
    def _drain_queue(q: queue.Queue) -> str:
        """Drain all available items from a queue."""
        lines = []
        while True:
            try:
                lines.append(q.get_nowait())
            except queue.Empty:
                break
        return "".join(lines)

    def _is_alive(self) -> bool:
        """Check if the bash process is still running."""
        return self.proc.poll() is None

    def execute(self, command: str, timeout: Optional[int] = None) -> ToolResult:
        """Run a command in the persistent bash session.

        Args:
            command: Shell command to execute
            timeout: Override default timeout (seconds)

        Returns:
            ToolResult with stdout+stderr output
        """
        if not self._is_alive():
            return ToolResult(False, error="Bash session has terminated. Restart required.")

        effective_timeout = timeout if timeout is not None else self.timeout

        # Drain any leftover output from previous commands
        self._drain_queue(self._stdout_q)
        self._drain_queue(self._stderr_q)

        # Write command + exit code capture + sentinel to stdin
        # The sentinel lets us know when the command is done
        # Note: if the command is 'exit', it will kill the session.
        # Dead-process detection handles this gracefully, and
        # _get_persistent_bash() will auto-restart on next call.
        script = (
            f"{command}\n"
            f"echo \"{self._exit_code_marker}$?\"\n"
            f"echo \"{self._sentinel}\"\n"
            f"echo \"{self._sentinel}\" >&2\n"
        )

        try:
            self.proc.stdin.write(script)
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError):
            return ToolResult(False, error="Bash session pipe broken. Restart required.")

        # Collect output until sentinel is found
        stdout_lines = []
        stderr_lines = []
        exit_code = 0
        start_time = time.time()
        stdout_done = False
        stderr_done = False

        while not (stdout_done and stderr_done):
            elapsed = time.time() - start_time
            if elapsed > effective_timeout:
                return ToolResult(
                    False,
                    output=self._format_output(stdout_lines, stderr_lines),
                    error=f"Command timed out after {effective_timeout}s",
                )

            # Check if process died
            if not self._is_alive():
                # Process died — collect remaining output and return
                stdout_lines.append(self._drain_queue(self._stdout_q))
                stderr_lines.append(self._drain_queue(self._stderr_q))
                output = self._format_output(stdout_lines, stderr_lines)
                return ToolResult(False, output=output, error="Bash session terminated unexpectedly")

            # Check stdout
            if not stdout_done:
                try:
                    line = self._stdout_q.get(timeout=0.1)
                    if self._sentinel in line:
                        stdout_done = True
                    elif self._exit_code_marker in line:
                        # Extract exit code
                        try:
                            exit_code = int(line.strip().replace(self._exit_code_marker, ""))
                        except ValueError:
                            pass
                    else:
                        stdout_lines.append(line)
                except queue.Empty:
                    pass

            # Check stderr
            if not stderr_done:
                try:
                    line = self._stderr_q.get(timeout=0.05)
                    if self._sentinel in line:
                        stderr_done = True
                    else:
                        stderr_lines.append(line)
                except queue.Empty:
                    # stderr may not have output — check if stdout is done
                    if stdout_done:
                        # Give stderr a short grace period
                        time.sleep(0.1)
                        # Try one more drain
                        while True:
                            try:
                                line = self._stderr_q.get(timeout=0.1)
                                if self._sentinel in line:
                                    stderr_done = True
                                    break
                                stderr_lines.append(line)
                            except queue.Empty:
                                stderr_done = True
                                break

        output = self._format_output(stdout_lines, stderr_lines)
        truncated = self._truncate_middle(output)

        return ToolResult(
            success=(exit_code == 0),
            output=truncated,
            error="" if exit_code == 0 else f"Exit code: {exit_code}",
        )

    def _format_output(self, stdout_lines: list, stderr_lines: list) -> str:
        """Combine stdout and stderr into a single output string."""
        parts = []
        stdout = "".join(stdout_lines).rstrip("\n")
        stderr = "".join(stderr_lines).rstrip("\n")

        if stdout:
            parts.append(stdout)
        if stderr:
            if stdout:
                parts.append(f"\nSTDERR:\n{stderr}")
            else:
                parts.append(stderr)

        return "\n".join(parts) if parts else ""

    def _truncate_middle(self, text: str) -> str:
        """Truncate output using middle-truncation strategy."""
        if len(text) <= self.max_output:
            return text
        keep = self.max_output // 2
        removed = len(text) - self.max_output
        return (
            text[:keep]
            + f"\n\n... [{removed:,} chars truncated] ...\n\n"
            + text[-keep:]
        )

    def get_cwd(self) -> str:
        """Get current working directory of the bash session."""
        result = self.execute("pwd", timeout=5)
        if result.success:
            return result.output.strip()
        return os.getcwd()

    def close(self):
        """Terminate the bash session cleanly."""
        if self._is_alive():
            try:
                self.proc.stdin.write("exit\n")
                self.proc.stdin.flush()
                self.proc.wait(timeout=5)
            except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
                self.proc.kill()
                self.proc.wait()

    def __del__(self):
        """Cleanup on garbage collection."""
        try:
            self.close()
        except Exception:
            pass
