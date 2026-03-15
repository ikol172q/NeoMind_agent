"""
Claude CLI-like tool system for coding mode.

Provides structured tools that mirror Claude CLI's built-in capabilities:
- Bash: Execute shell commands
- Read: Read files with line numbers
- Write: Create/overwrite files
- Edit: Targeted string replacement
- Glob: Fast file pattern matching
- Grep: Regex content search
- LS: List directory contents
"""

import os
import re
import subprocess
import pathlib
import fnmatch
from typing import Optional, List, Dict, Any, Tuple


class ToolResult:
    """Standardized result from any tool execution."""

    def __init__(self, success: bool, output: str = "", error: str = ""):
        self.success = success
        self.output = output
        self.error = error

    def __str__(self):
        if self.success:
            return self.output
        return f"Error: {self.error}"

    def __bool__(self):
        return self.success


class ToolRegistry:
    """Claude CLI-like tool system for coding mode.

    Each tool returns a ToolResult with structured output.
    """

    def __init__(self, working_dir: Optional[str] = None):
        self.working_dir = working_dir or os.getcwd()
        self._persistent_bash = None  # Lazy init

    def _resolve_path(self, path: str) -> str:
        """Resolve a path relative to working directory."""
        p = pathlib.Path(path)
        if not p.is_absolute():
            p = pathlib.Path(self.working_dir) / p
        return str(p.resolve())

    # ── Bash ─────────────────────────────────────────────────────────────

    def _get_persistent_bash(self):
        """Get or create the persistent bash session."""
        from agent.persistent_bash import PersistentBash
        if self._persistent_bash is None or not self._persistent_bash._is_alive():
            self._persistent_bash = PersistentBash(working_dir=self.working_dir)
        return self._persistent_bash

    def bash(self, command: str, timeout: int = 120) -> ToolResult:
        """Execute a shell command in a persistent bash session.

        State (cd, export, source) carries across calls.

        Args:
            command: Shell command to execute
            timeout: Timeout in seconds (default 120)
        """
        try:
            pb = self._get_persistent_bash()
            return pb.execute(command, timeout=timeout)
        except Exception as e:
            # Fallback to subprocess.run if persistent bash fails
            return self._bash_fallback(command, timeout)

    def _bash_fallback(self, command: str, timeout: int = 120) -> ToolResult:
        """Stateless bash fallback if persistent session fails."""
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self.working_dir,
            )
            output = result.stdout
            if result.stderr:
                output += f"\n{result.stderr}" if output else result.stderr
            return ToolResult(
                success=(result.returncode == 0),
                output=output.strip(),
                error=result.stderr.strip() if result.returncode != 0 else "",
            )
        except subprocess.TimeoutExpired:
            return ToolResult(False, error=f"Command timed out after {timeout}s")
        except Exception as e:
            return ToolResult(False, error=str(e))

    def close_bash(self):
        """Close the persistent bash session."""
        if self._persistent_bash is not None:
            self._persistent_bash.close()
            self._persistent_bash = None

    # ── Read ─────────────────────────────────────────────────────────────

    def read_file(self, path: str, offset: int = 0, limit: int = 0, max_chars: int = 30000) -> ToolResult:
        """Read a file with line numbers, like Claude CLI's Read tool.

        Args:
            path: File path (absolute or relative to working dir)
            offset: Starting line number (0 = from beginning)
            limit: Max lines to read (0 = all)
            max_chars: Max output characters (default 30K, middle-truncation)
        """
        resolved = self._resolve_path(path)
        if not os.path.exists(resolved):
            return ToolResult(False, error=f"File not found: {path}")
        if os.path.isdir(resolved):
            return ToolResult(False, error=f"Path is a directory: {path}. Use /ls instead.")

        # Detect binary files (files with NUL bytes)
        try:
            with open(resolved, "rb") as f:
                chunk = f.read(8192)
                if b"\x00" in chunk:
                    return ToolResult(False, error=f"Binary file: {path}. Cannot display.")
        except Exception:
            pass

        try:
            with open(resolved, "r", errors="replace") as f:
                lines = f.readlines()

            total = len(lines)
            start = max(0, offset)
            end = start + limit if limit > 0 else total

            numbered_lines = []
            for i, line in enumerate(lines[start:end], start=start + 1):
                # Truncate very long lines
                display = line.rstrip("\n")
                if len(display) > 2000:
                    display = display[:2000] + "..."
                numbered_lines.append(f"{i:>6}\t{display}")

            header = f"# {path} ({total} lines)"
            if offset > 0 or limit > 0:
                header += f" [showing lines {start + 1}-{min(end, total)}]"

            output = header + "\n" + "\n".join(numbered_lines)

            # Truncate if output exceeds max_chars
            if len(output) > max_chars:
                output = self._truncate_output(output, max_chars)

            return ToolResult(True, output=output)
        except Exception as e:
            return ToolResult(False, error=f"Failed to read {path}: {e}")

    @staticmethod
    def _truncate_output(text: str, max_chars: int = 30000) -> str:
        """Middle-truncation for large output. Preserves start + end."""
        if len(text) <= max_chars:
            return text
        keep = max_chars // 2
        removed = len(text) - max_chars
        return (
            text[:keep]
            + f"\n\n... [{removed:,} chars truncated] ...\n\n"
            + text[-keep:]
        )

    # ── Write ────────────────────────────────────────────────────────────

    def write_file(self, path: str, content: str) -> ToolResult:
        """Create or overwrite a file.

        Args:
            path: File path
            content: File content
        """
        resolved = self._resolve_path(path)
        try:
            # Create parent directories if needed
            os.makedirs(os.path.dirname(resolved), exist_ok=True)
            existed = os.path.exists(resolved)
            with open(resolved, "w") as f:
                f.write(content)
            line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
            action = "Updated" if existed else "Created"
            return ToolResult(True, output=f"{action} {path} ({line_count} lines)")
        except Exception as e:
            return ToolResult(False, error=f"Failed to write {path}: {e}")

    # ── Edit ─────────────────────────────────────────────────────────────

    def edit_file(self, path: str, old_string: str, new_string: str, replace_all: bool = False) -> ToolResult:
        """Edit a file by replacing old_string with new_string.

        Like Claude CLI's Edit tool — targeted string replacement.

        Args:
            path: File path
            old_string: Exact text to find and replace
            new_string: Replacement text
            replace_all: If True, replace all occurrences (default: first only)
        """
        resolved = self._resolve_path(path)
        if not os.path.exists(resolved):
            return ToolResult(False, error=f"File not found: {path}")

        try:
            content = open(resolved, "r").read()

            count = content.count(old_string)
            if count == 0:
                return ToolResult(False, error=f"String not found in {path}. Read the file first to get exact content.")
            if count > 1 and not replace_all:
                return ToolResult(
                    False,
                    error=f"Found {count} occurrences. Provide more context to make it unique, or use replace_all=True.",
                )

            if replace_all:
                new_content = content.replace(old_string, new_string)
                replaced_count = count
            else:
                new_content = content.replace(old_string, new_string, 1)
                replaced_count = 1

            with open(resolved, "w") as f:
                f.write(new_content)

            return ToolResult(True, output=f"Edited {path}: {replaced_count} replacement(s) made")
        except Exception as e:
            return ToolResult(False, error=f"Failed to edit {path}: {e}")

    # ── Glob ─────────────────────────────────────────────────────────────

    def glob_files(self, pattern: str, path: Optional[str] = None) -> ToolResult:
        """Find files matching a glob pattern.

        Results sorted by modification time (most recent first).

        Args:
            pattern: Glob pattern (e.g. "**/*.py", "src/**/*.ts")
            path: Base directory (default: working dir)
        """
        base = pathlib.Path(path or self.working_dir)
        try:
            matches = list(base.glob(pattern))
            # Filter out common exclusions
            excludes = {".git", "__pycache__", "node_modules", ".venv", ".mypy_cache"}
            filtered = []
            for m in matches:
                parts = m.parts
                if not any(ex in parts for ex in excludes):
                    filtered.append(m)

            if not filtered:
                return ToolResult(True, output=f"No files matching '{pattern}'")

            # Sort by mtime (most recently modified first)
            try:
                filtered.sort(key=lambda f: f.stat().st_mtime, reverse=True)
            except OSError:
                filtered.sort()  # Fallback to alphabetical

            rel_paths = [str(m.relative_to(base)) for m in filtered]
            output = f"# {len(rel_paths)} files matching '{pattern}'\n" + "\n".join(rel_paths)
            return ToolResult(True, output=output)
        except Exception as e:
            return ToolResult(False, error=f"Glob failed: {e}")

    # ── Grep ─────────────────────────────────────────────────────────────

    _ripgrep_available = None  # Class-level cache

    @classmethod
    def _has_ripgrep(cls) -> bool:
        """Check if ripgrep (rg) binary is available."""
        if cls._ripgrep_available is None:
            try:
                subprocess.run(["rg", "--version"], capture_output=True, timeout=5)
                cls._ripgrep_available = True
            except (FileNotFoundError, subprocess.TimeoutExpired):
                cls._ripgrep_available = False
        return cls._ripgrep_available

    def grep_files(
        self,
        pattern: str,
        path: Optional[str] = None,
        file_type: Optional[str] = None,
        context: int = 0,
        max_results: int = 50,
        case_insensitive: bool = False,
        output_mode: str = "content",
    ) -> ToolResult:
        """Search file contents with regex.

        Uses ripgrep if available (5-10x faster), falls back to Python.

        Args:
            pattern: Regex pattern to search for
            path: Directory to search (default: working dir)
            file_type: Filter by extension (e.g. "py", "js")
            context: Lines of context around matches
            max_results: Max number of matches to return
            case_insensitive: Case insensitive search
            output_mode: "content", "files_with_matches", or "count"
        """
        if self._has_ripgrep():
            return self._grep_ripgrep(
                pattern, path, file_type, context,
                max_results, case_insensitive, output_mode
            )
        return self._grep_python(
            pattern, path, file_type, context,
            max_results, case_insensitive
        )

    def _grep_ripgrep(
        self, pattern, path, file_type, context,
        max_results, case_insensitive, output_mode
    ) -> ToolResult:
        """Fast search using ripgrep."""
        cmd = ["rg", pattern]

        # Output mode
        if output_mode == "files_with_matches":
            cmd.append("-l")
        elif output_mode == "count":
            cmd.append("-c")

        # Flags
        if case_insensitive:
            cmd.append("-i")
        if context > 0:
            cmd.extend(["-C", str(context)])
        if file_type:
            cmd.extend(["--type", file_type])
        if max_results and output_mode == "content":
            cmd.extend(["-m", str(max_results)])

        cmd.append("-n")  # line numbers
        cmd.append("--no-heading")  # flat output
        cmd.append(str(path or self.working_dir))

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired:
            return ToolResult(False, error="Ripgrep search timed out after 30s")
        except Exception as e:
            return ToolResult(False, error=f"Ripgrep failed: {e}")

        # Exit code 2 = regex syntax error in ripgrep
        if result.returncode == 2:
            return ToolResult(False, error=f"Invalid regex: {result.stderr.strip()}")

        output = result.stdout.strip()
        if not output:
            return ToolResult(True, output=f"No matches for '{pattern}'")

        lines = output.split("\n")
        if len(lines) > max_results:
            lines = lines[:max_results]
            output = "\n".join(lines)

        header = f"# {len(lines)} match(es) for '{pattern}'"
        if len(lines) >= max_results:
            header += f" (truncated at {max_results})"
        return ToolResult(True, output=header + "\n" + output)

    def _grep_python(
        self, pattern, path, file_type, context,
        max_results, case_insensitive
    ) -> ToolResult:
        """Fallback search using Python regex."""
        search_dir = pathlib.Path(path or self.working_dir)
        excludes = {".git", "__pycache__", "node_modules", ".venv", ".mypy_cache"}

        flags = re.IGNORECASE if case_insensitive else 0
        try:
            regex = re.compile(pattern, flags)
        except re.error as e:
            return ToolResult(False, error=f"Invalid regex: {e}")

        results = []
        try:
            glob_pattern = f"**/*.{file_type}" if file_type else "**/*"
            for fp in search_dir.glob(glob_pattern):
                if not fp.is_file():
                    continue
                if any(ex in fp.parts for ex in excludes):
                    continue
                # Skip binary files
                try:
                    with open(fp, "r", errors="strict") as f:
                        lines = f.readlines()
                except (UnicodeDecodeError, PermissionError):
                    continue

                rel = str(fp.relative_to(search_dir))
                for i, line in enumerate(lines, 1):
                    if regex.search(line):
                        results.append(f"{rel}:{i}: {line.rstrip()}")
                        if len(results) >= max_results:
                            break
                if len(results) >= max_results:
                    break

            if not results:
                return ToolResult(True, output=f"No matches for '{pattern}'")

            header = f"# {len(results)} match(es) for '{pattern}'"
            if len(results) >= max_results:
                header += f" (truncated at {max_results})"
            return ToolResult(True, output=header + "\n" + "\n".join(results))
        except Exception as e:
            return ToolResult(False, error=f"Grep failed: {e}")

    # ── LS ───────────────────────────────────────────────────────────────

    def list_dir(self, path: Optional[str] = None) -> ToolResult:
        """List directory contents with metadata.

        Args:
            path: Directory path (default: working dir)
        """
        target = pathlib.Path(path or self.working_dir)
        if not target.exists():
            return ToolResult(False, error=f"Directory not found: {path}")
        if not target.is_dir():
            return ToolResult(False, error=f"Not a directory: {path}")

        try:
            entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            lines = []
            for entry in entries:
                if entry.name.startswith(".") and entry.name in (".git", ".venv", "__pycache__"):
                    continue
                if entry.is_dir():
                    lines.append(f"  {entry.name}/")
                else:
                    size = entry.stat().st_size
                    if size < 1024:
                        size_str = f"{size}B"
                    elif size < 1024 * 1024:
                        size_str = f"{size / 1024:.1f}K"
                    else:
                        size_str = f"{size / (1024 * 1024):.1f}M"
                    lines.append(f"  {entry.name:<40} {size_str:>8}")

            header = f"# {target} ({len(lines)} entries)"
            return ToolResult(True, output=header + "\n" + "\n".join(lines))
        except Exception as e:
            return ToolResult(False, error=f"LS failed: {e}")
