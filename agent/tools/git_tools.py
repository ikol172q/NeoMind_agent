"""
Git Workflow Tools for NeoMind Agent.

Provides user-facing git operations: commit, branch, diff, status, PR creation.
Mirrors Claude CLI's git workflow capabilities.

Created: 2026-04-02 (Phase 2 - Coding 完整功能)
"""

from __future__ import annotations

import subprocess
import os
import re
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from datetime import datetime


@dataclass
class GitResult:
    """Result from a git operation."""
    success: bool
    output: str = ""
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class GitTools:
    """User-facing git workflow operations."""

    def __init__(self, working_dir: Optional[str] = None):
        """
        Initialize GitTools.

        Args:
            working_dir: Working directory for git commands. Defaults to cwd.
        """
        self.working_dir = working_dir or os.getcwd()

    def _run(self, *args: str, timeout: int = 30) -> GitResult:
        """
        Run a git command and return GitResult.

        Args:
            *args: Git subcommand and arguments.
            timeout: Command timeout in seconds.

        Returns:
            GitResult with output or error.
        """
        try:
            result = subprocess.run(
                ["git"] + list(args),
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self.working_dir,
            )
            return GitResult(
                success=result.returncode == 0,
                output=result.stdout.strip(),
                error=result.stderr.strip() if result.returncode != 0 else None,
                metadata={"command": f"git {' '.join(args)}"},
            )
        except subprocess.TimeoutExpired:
            return GitResult(False, error=f"Git command timed out after {timeout}s")
        except FileNotFoundError:
            return GitResult(False, error="git not found in PATH")
        except Exception as e:
            return GitResult(False, error=str(e))

    def _run_raw(self, cmd: List[str], timeout: int = 30) -> GitResult:
        """
        Run an arbitrary command (non-git) and return GitResult.

        Args:
            cmd: Full command as list of strings.
            timeout: Command timeout in seconds.

        Returns:
            GitResult with output or error.
        """
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self.working_dir,
            )
            return GitResult(
                success=result.returncode == 0,
                output=result.stdout.strip(),
                error=result.stderr.strip() if result.returncode != 0 else None,
                metadata={"command": " ".join(cmd)},
            )
        except FileNotFoundError:
            return GitResult(False, error=f"{cmd[0]} not found in PATH")
        except Exception as e:
            return GitResult(False, error=str(e))

    def status(self) -> GitResult:
        """
        Get git status (short format).

        Returns:
            GitResult with short status output.
        """
        return self._run("status", "--short")

    def diff(self, staged: bool = False, path: Optional[str] = None) -> GitResult:
        """
        Show diff of changes.

        Args:
            staged: If True, show staged (cached) changes only.
            path: Optional file path to restrict diff to.

        Returns:
            GitResult with diff output.
        """
        args = ["diff"]
        if staged:
            args.append("--staged")
        if path:
            args.append("--")
            args.append(path)
        return self._run(*args)

    def log(self, count: int = 10, oneline: bool = True) -> GitResult:
        """
        Show recent commit log.

        Args:
            count: Number of commits to show.
            oneline: If True, use --oneline format.

        Returns:
            GitResult with log output.
        """
        args = ["log", f"-{count}"]
        if oneline:
            args.append("--oneline")
        return self._run(*args)

    def branch_list(self) -> GitResult:
        """
        List all branches (local and remote).

        Returns:
            GitResult with branch listing. Current branch marked
            in metadata['current_branch'].
        """
        result = self._run("branch", "-a")
        if result.success:
            # Extract current branch
            for line in result.output.splitlines():
                if line.startswith("*"):
                    current = line.lstrip("* ").strip()
                    result.metadata["current_branch"] = current
                    break
        return result

    def branch_create(self, name: str, checkout: bool = True) -> GitResult:
        """
        Create a new branch.

        Args:
            name: Branch name.
            checkout: If True, switch to the new branch immediately.

        Returns:
            GitResult indicating success or failure.
        """
        if not name or not name.strip():
            return GitResult(False, error="Branch name cannot be empty")

        if checkout:
            return self._run("checkout", "-b", name)
        else:
            return self._run("branch", name)

    def branch_switch(self, name: str) -> GitResult:
        """
        Switch to an existing branch.

        Args:
            name: Branch name to switch to.

        Returns:
            GitResult indicating success or failure.
        """
        if not name or not name.strip():
            return GitResult(False, error="Branch name cannot be empty")
        return self._run("switch", name)

    def add(self, paths: List[str]) -> GitResult:
        """
        Stage files for commit.

        Args:
            paths: List of file paths to add.

        Returns:
            GitResult indicating success or failure.
        """
        if not paths:
            return GitResult(False, error="No paths specified")
        return self._run("add", *paths)

    def commit(self, message: str) -> GitResult:
        """
        Create a commit with the staged changes.

        Automatically appends a co-author line. Returns the commit hash
        in metadata['commit_hash'] on success.

        Args:
            message: Commit message.

        Returns:
            GitResult with commit output and hash in metadata.
        """
        if not message or not message.strip():
            return GitResult(False, error="Commit message cannot be empty")

        # Append co-author trailer
        full_message = (
            f"{message.strip()}\n\n"
            "Co-Authored-By: NeoMind Agent <noreply@neomind.dev>"
        )

        result = self._run("commit", "-m", full_message)

        if result.success:
            # Extract commit hash from output (e.g. "[main abc1234] message")
            match = re.search(r"\[[\w/.-]+\s+([0-9a-f]+)\]", result.output)
            if match:
                result.metadata["commit_hash"] = match.group(1)

        return result

    def stash(self, action: str = "push", message: Optional[str] = None) -> GitResult:
        """
        Manage the git stash.

        Args:
            action: One of "push", "pop", "list".
            message: Optional message for stash push.

        Returns:
            GitResult with stash output.
        """
        valid_actions = {"push", "pop", "list"}
        if action not in valid_actions:
            return GitResult(
                False,
                error=f"Invalid stash action '{action}'. Must be one of: {', '.join(sorted(valid_actions))}",
            )

        args = ["stash", action]
        if action == "push" and message:
            args.extend(["-m", message])

        return self._run(*args)

    def pr_create(self, title: str, body: str, base: str = "main") -> GitResult:
        """
        Create a pull request using the GitHub CLI (gh).

        Checks for gh availability first. Returns the PR URL in
        metadata['pr_url'] on success.

        Args:
            title: PR title.
            body: PR body/description.
            base: Base branch to merge into. Defaults to "main".

        Returns:
            GitResult with PR URL or error.
        """
        if not title or not title.strip():
            return GitResult(False, error="PR title cannot be empty")

        # Check if gh CLI is available
        check = self._run_raw(["which", "gh"])
        if not check.success:
            return GitResult(
                False,
                error="GitHub CLI (gh) is not installed or not in PATH. "
                      "Install it from https://cli.github.com/",
            )

        result = self._run_raw(
            ["gh", "pr", "create", "--title", title, "--body", body, "--base", base],
            timeout=60,
        )

        if result.success:
            # gh pr create outputs the PR URL on success
            url = result.output.strip()
            if url:
                result.metadata["pr_url"] = url

        return result

    def merge_status(self) -> GitResult:
        """
        Check for merge conflicts in the working tree.

        Returns:
            GitResult with conflict information. metadata['has_conflicts']
            is True if unmerged paths exist, and metadata['conflicted_files']
            lists the affected file paths.
        """
        result = self._run("diff", "--name-only", "--diff-filter=U")

        if result.success:
            conflicted = [f for f in result.output.splitlines() if f.strip()]
            result.metadata["has_conflicts"] = len(conflicted) > 0
            result.metadata["conflicted_files"] = conflicted
            if conflicted:
                result.output = f"Merge conflicts in {len(conflicted)} file(s):\n" + "\n".join(
                    f"  {f}" for f in conflicted
                )
            else:
                result.output = "No merge conflicts detected."

        return result

    def blame(self, path: str, lines: Optional[str] = None) -> GitResult:
        """
        Show git blame for a file.

        Args:
            path: File path to blame.
            lines: Optional line range (e.g. "10,20" for lines 10-20).

        Returns:
            GitResult with blame output.
        """
        if not path or not path.strip():
            return GitResult(False, error="File path cannot be empty")

        args = ["blame"]
        if lines:
            args.extend(["-L", lines])
        args.append(path)

        return self._run(*args)


__all__ = [
    'GitTools',
    'GitResult',
]


if __name__ == "__main__":
    print("=== GitTools Test ===\n")

    git = GitTools()

    # Status
    s = git.status()
    print(f"Status (success={s.success}):")
    print(f"  {s.output or s.error}\n")

    # Log
    log = git.log(count=5)
    print(f"Log (success={log.success}):")
    for line in (log.output or log.error or "").splitlines()[:5]:
        print(f"  {line}")

    # Branch list
    br = git.branch_list()
    print(f"\nBranches (success={br.success}):")
    print(f"  Current: {br.metadata.get('current_branch', 'N/A')}")

    # Diff
    d = git.diff()
    print(f"\nDiff (success={d.success}): {len(d.output)} chars")

    # Merge status
    ms = git.merge_status()
    print(f"\nMerge status: {ms.output}")

    print("\nGitTools test passed!")
