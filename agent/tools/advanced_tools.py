"""
Advanced Tools for NeoMind Agent.

Implements remaining Claude CLI tool parity:
- WorktreeTool: Git worktree isolation
- REPLTool: Interactive language shells
- MCPToolAdapter: Model Context Protocol tool calls
- ListMcpResourcesTool: List MCP resources
- ReadMcpResourceTool: Read MCP resources
- SkillTool: Invoke slash commands programmatically
- ConfigTool: Modify agent settings at runtime
- ToolSearchTool: Search available tools
- TaskOutputTool: Stream task output
- PowerShellTool: Windows PowerShell execution
- CronManager: Individual cron management (create/delete/list)

Created: 2026-04-02 (Phase 2 - Complete Claude CLI Parity)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class REPLLanguage(Enum):
    """Supported REPL languages."""
    PYTHON = "python"
    NODE = "node"
    RUBY = "ruby"
    BASH = "bash"


class WorktreeStatus(Enum):
    """Status of a git worktree."""
    ACTIVE = "active"
    PRUNABLE = "prunable"
    REMOVED = "removed"


class ConfigScope(Enum):
    """Scope of a configuration change."""
    SESSION = "session"
    PROJECT = "project"
    GLOBAL = "global"


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class WorktreeResult:
    """Result from a worktree operation."""
    success: bool
    message: str
    path: Optional[str] = None
    branch: Optional[str] = None
    worktrees: Optional[List[Dict[str, str]]] = None
    error: Optional[str] = None


@dataclass
class REPLResult:
    """Result from a REPL execution."""
    success: bool
    message: str
    stdout: str = ""
    stderr: str = ""
    return_code: int = 0
    session_id: Optional[str] = None
    language: Optional[str] = None
    error: Optional[str] = None


@dataclass
class MCPToolResult:
    """Result from an MCP tool adapter operation."""
    success: bool
    message: str
    content: Any = None
    servers: Optional[Dict[str, bool]] = None
    tools: Optional[List[Dict[str, Any]]] = None
    resources: Optional[List[Dict[str, Any]]] = None
    error: Optional[str] = None


@dataclass
class SkillResult:
    """Result from invoking a skill."""
    success: bool
    message: str
    skill_name: Optional[str] = None
    output: Any = None
    available_skills: Optional[List[Dict[str, str]]] = None
    error: Optional[str] = None


@dataclass
class ConfigResult:
    """Result from a config operation."""
    success: bool
    message: str
    key: Optional[str] = None
    value: Any = None
    config: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


@dataclass
class ToolSearchResult:
    """Result from searching available tools."""
    success: bool
    message: str
    matches: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class TaskOutputResult:
    """Result from reading task output."""
    success: bool
    message: str
    task_id: Optional[str] = None
    output_lines: List[str] = field(default_factory=list)
    is_running: bool = False
    error: Optional[str] = None


@dataclass
class PowerShellResult:
    """Result from a PowerShell command."""
    success: bool
    message: str
    stdout: str = ""
    stderr: str = ""
    return_code: int = 0
    error: Optional[str] = None


@dataclass
class CronResult:
    """Result from a cron management operation."""
    success: bool
    message: str
    name: Optional[str] = None
    jobs: Optional[List[Dict[str, Any]]] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# WorktreeTool
# ---------------------------------------------------------------------------

class WorktreeTool:
    """Git worktree management for isolated parallel work.

    Creates temporary git worktrees so that multiple branches can be
    worked on simultaneously without switching the main working tree.
    """

    def __init__(self, working_dir: Optional[str] = None) -> None:
        self.working_dir = working_dir or os.getcwd()
        self._active_worktrees: Dict[str, str] = {}  # name -> path

    # -- helpers -----------------------------------------------------------

    def _run_git(self, *args: str, timeout: int = 30) -> Tuple[bool, str, str]:
        """Run a git command and return (success, stdout, stderr)."""
        try:
            result = subprocess.run(
                ["git"] + list(args),
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self.working_dir,
            )
            return (
                result.returncode == 0,
                result.stdout.strip(),
                result.stderr.strip(),
            )
        except subprocess.TimeoutExpired:
            return False, "", f"Git command timed out after {timeout}s"
        except FileNotFoundError:
            return False, "", "git not found in PATH"
        except Exception as exc:
            return False, "", str(exc)

    def _is_git_repo(self) -> bool:
        """Check whether the working directory is inside a git repo."""
        ok, _, _ = self._run_git("rev-parse", "--is-inside-work-tree")
        return ok

    # -- public API --------------------------------------------------------

    def enter(
        self,
        branch: Optional[str] = None,
        name: Optional[str] = None,
    ) -> WorktreeResult:
        """Create a temporary git worktree.

        Args:
            branch: Branch to check out in the worktree.  If *None* a new
                branch is created automatically.  If the branch does not
                exist it is created with ``-b``.
            name: Human-friendly name for tracking.  Defaults to the
                branch name or an auto-generated slug.

        Returns:
            WorktreeResult with the worktree path and branch.
        """
        if not self._is_git_repo():
            return WorktreeResult(
                success=False,
                message="Not inside a git repository",
                error="not_git_repo",
            )

        # Decide on a branch name
        if branch is None:
            branch = f"worktree-{uuid.uuid4().hex[:8]}"

        wt_name = name or branch

        if wt_name in self._active_worktrees:
            return WorktreeResult(
                success=False,
                message=f"Worktree '{wt_name}' is already active",
                error="duplicate_worktree",
            )

        # Create a temp directory for the worktree
        wt_path = os.path.join(
            tempfile.gettempdir(),
            f"neomind-wt-{uuid.uuid4().hex[:8]}",
        )

        # Check whether the branch already exists
        ok, _, _ = self._run_git("rev-parse", "--verify", f"refs/heads/{branch}")
        if ok:
            git_args = ["worktree", "add", wt_path, branch]
        else:
            git_args = ["worktree", "add", "-b", branch, wt_path]

        ok, stdout, stderr = self._run_git(*git_args)
        if not ok:
            return WorktreeResult(
                success=False,
                message=f"Failed to create worktree: {stderr}",
                error="worktree_create_failed",
            )

        self._active_worktrees[wt_name] = wt_path
        logger.info("Created worktree '%s' at %s (branch %s)", wt_name, wt_path, branch)

        return WorktreeResult(
            success=True,
            message=f"Worktree '{wt_name}' created at {wt_path}",
            path=wt_path,
            branch=branch,
        )

    def exit(
        self,
        name: Optional[str] = None,
        cleanup: bool = True,
    ) -> WorktreeResult:
        """Remove a worktree.

        If the worktree has uncommitted changes and *cleanup* is True,
        the removal is forced.  Otherwise the path and branch are returned
        so the caller can decide.

        Args:
            name: Worktree name.  If *None* the most recently created
                worktree is used.
            cleanup: Whether to force-remove even if there are changes.

        Returns:
            WorktreeResult indicating success or remaining path/branch.
        """
        if not self._active_worktrees:
            return WorktreeResult(
                success=False,
                message="No active worktrees to remove",
                error="no_worktrees",
            )

        if name is None:
            # Use the last-added worktree
            name = list(self._active_worktrees.keys())[-1]

        if name not in self._active_worktrees:
            return WorktreeResult(
                success=False,
                message=f"Worktree '{name}' not found among active worktrees",
                error="not_found",
            )

        wt_path = self._active_worktrees[name]

        # Check for uncommitted changes
        try:
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                cwd=wt_path,
                timeout=10,
            )
            has_changes = bool(status.stdout.strip())
        except Exception:
            has_changes = False

        if has_changes and not cleanup:
            # Detect branch name
            try:
                br = subprocess.run(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    capture_output=True,
                    text=True,
                    cwd=wt_path,
                    timeout=10,
                )
                branch_name = br.stdout.strip()
            except Exception:
                branch_name = "unknown"

            return WorktreeResult(
                success=False,
                message=f"Worktree '{name}' has uncommitted changes",
                path=wt_path,
                branch=branch_name,
                error="has_changes",
            )

        # Remove the worktree
        force_flag = ["--force"] if cleanup else []
        ok, stdout, stderr = self._run_git("worktree", "remove", wt_path, *force_flag)
        if not ok:
            # Fallback: remove the directory manually
            if os.path.isdir(wt_path):
                shutil.rmtree(wt_path, ignore_errors=True)
            self._run_git("worktree", "prune")

        self._active_worktrees.pop(name, None)
        logger.info("Removed worktree '%s'", name)

        return WorktreeResult(
            success=True,
            message=f"Worktree '{name}' removed",
        )

    def list_worktrees(self) -> WorktreeResult:
        """List all git worktrees (both tracked and untracked).

        Returns:
            WorktreeResult with a list of worktree dicts.
        """
        if not self._is_git_repo():
            return WorktreeResult(
                success=False,
                message="Not inside a git repository",
                error="not_git_repo",
            )

        ok, stdout, stderr = self._run_git("worktree", "list", "--porcelain")
        if not ok:
            return WorktreeResult(
                success=False,
                message=f"Failed to list worktrees: {stderr}",
                error="list_failed",
            )

        worktrees: List[Dict[str, str]] = []
        current: Dict[str, str] = {}
        for line in stdout.splitlines():
            if not line.strip():
                if current:
                    worktrees.append(current)
                    current = {}
                continue
            if line.startswith("worktree "):
                current["path"] = line[len("worktree "):]
            elif line.startswith("HEAD "):
                current["head"] = line[len("HEAD "):]
            elif line.startswith("branch "):
                current["branch"] = line[len("branch "):]
            elif line.strip() == "bare":
                current["bare"] = "true"
            elif line.strip() == "detached":
                current["detached"] = "true"

        if current:
            worktrees.append(current)

        return WorktreeResult(
            success=True,
            message=f"Found {len(worktrees)} worktree(s)",
            worktrees=worktrees,
        )


# ---------------------------------------------------------------------------
# REPLTool
# ---------------------------------------------------------------------------

class REPLTool:
    """Interactive REPL for Python, Node.js, Ruby, and Bash.

    Supports both one-shot execution (``execute``) and persistent
    sessions (``create_session`` / ``close_session``).
    """

    LANGUAGE_COMMANDS: Dict[str, List[str]] = {
        "python": ["python3", "-c"],
        "node": ["node", "-e"],
        "ruby": ["ruby", "-e"],
        "bash": ["bash", "-c"],
    }

    def __init__(self) -> None:
        self._sessions: Dict[str, Dict[str, Any]] = {}

    # -- one-shot execution ------------------------------------------------

    def execute(
        self,
        code: str,
        language: str = "python",
        session_id: Optional[str] = None,
        timeout: int = 60,
        working_dir: Optional[str] = None,
    ) -> REPLResult:
        """Execute code in a one-shot subprocess.

        Args:
            code: Source code to execute.
            language: One of ``python``, ``node``, ``ruby``, ``bash``.
            session_id: If provided, append output to the named session
                history for context tracking.
            timeout: Maximum execution time in seconds.
            working_dir: Working directory for the subprocess.

        Returns:
            REPLResult with stdout, stderr, and return code.
        """
        lang_lower = language.lower()
        if lang_lower not in self.LANGUAGE_COMMANDS:
            valid = ", ".join(sorted(self.LANGUAGE_COMMANDS))
            return REPLResult(
                success=False,
                message=f"Unsupported language '{language}'. Must be one of: {valid}",
                language=lang_lower,
                error="unsupported_language",
            )

        if not code or not code.strip():
            return REPLResult(
                success=False,
                message="Code cannot be empty",
                language=lang_lower,
                error="empty_code",
            )

        cmd = list(self.LANGUAGE_COMMANDS[lang_lower]) + [code]

        # Verify the interpreter exists
        interpreter = cmd[0]
        if shutil.which(interpreter) is None:
            return REPLResult(
                success=False,
                message=f"Interpreter '{interpreter}' not found in PATH",
                language=lang_lower,
                error="interpreter_not_found",
            )

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=working_dir,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )

            repl_result = REPLResult(
                success=result.returncode == 0,
                message="Execution completed" if result.returncode == 0 else "Execution failed",
                stdout=result.stdout,
                stderr=result.stderr,
                return_code=result.returncode,
                session_id=session_id,
                language=lang_lower,
            )

            # Append to session history if tracking
            if session_id and session_id in self._sessions:
                self._sessions[session_id]["history"].append({
                    "code": code,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "return_code": result.returncode,
                    "timestamp": datetime.now().isoformat(),
                })

            return repl_result

        except subprocess.TimeoutExpired:
            return REPLResult(
                success=False,
                message=f"Execution timed out after {timeout}s",
                language=lang_lower,
                session_id=session_id,
                error="timeout",
            )
        except Exception as exc:
            return REPLResult(
                success=False,
                message=f"Execution error: {exc}",
                language=lang_lower,
                session_id=session_id,
                error=str(exc),
            )

    # -- session management ------------------------------------------------

    def create_session(
        self,
        language: str = "python",
        name: Optional[str] = None,
    ) -> REPLResult:
        """Create a named REPL session for tracking execution history.

        Args:
            language: Language for this session.
            name: Optional human-readable name.

        Returns:
            REPLResult with the new session ID.
        """
        lang_lower = language.lower()
        if lang_lower not in self.LANGUAGE_COMMANDS:
            valid = ", ".join(sorted(self.LANGUAGE_COMMANDS))
            return REPLResult(
                success=False,
                message=f"Unsupported language '{language}'. Must be one of: {valid}",
                error="unsupported_language",
            )

        session_id = f"repl-{uuid.uuid4().hex[:8]}"
        self._sessions[session_id] = {
            "language": lang_lower,
            "name": name or session_id,
            "created_at": datetime.now().isoformat(),
            "history": [],
        }

        logger.info("Created REPL session '%s' (%s)", session_id, lang_lower)
        return REPLResult(
            success=True,
            message=f"Session '{session_id}' created for {lang_lower}",
            session_id=session_id,
            language=lang_lower,
        )

    def close_session(self, session_id: str) -> REPLResult:
        """Close and discard a REPL session.

        Args:
            session_id: Session to close.

        Returns:
            REPLResult confirming closure.
        """
        if session_id not in self._sessions:
            return REPLResult(
                success=False,
                message=f"Session '{session_id}' not found",
                error="not_found",
            )

        info = self._sessions.pop(session_id)
        entry_count = len(info["history"])
        logger.info("Closed REPL session '%s' (%d entries)", session_id, entry_count)

        return REPLResult(
            success=True,
            message=f"Session '{session_id}' closed ({entry_count} history entries discarded)",
            session_id=session_id,
            language=info["language"],
        )

    def list_sessions(self) -> List[Dict[str, Any]]:
        """Return a summary of all active sessions."""
        return [
            {
                "session_id": sid,
                "language": info["language"],
                "name": info["name"],
                "created_at": info["created_at"],
                "history_count": len(info["history"]),
            }
            for sid, info in self._sessions.items()
        ]


# ---------------------------------------------------------------------------
# MCPToolAdapter  (wraps the existing MCPClient as a callable tool)
# ---------------------------------------------------------------------------

class MCPToolAdapter:
    """Execute MCP server tools through the MCP client.

    This is a thin adapter that wraps :class:`MCPClient` from
    ``agent.services.mcp_client`` to present a uniform tool interface.
    """

    def __init__(self, mcp_client: Any = None) -> None:
        self._client = mcp_client  # Lazy-initialised from agent.services.mcp_client

    def _ensure_client(self) -> Any:
        """Lazily import and initialise the MCP client."""
        if self._client is None:
            try:
                from agent.services.mcp_client import MCPClient
                self._client = MCPClient()
            except ImportError:
                raise RuntimeError(
                    "MCPClient not available -- install agent.services.mcp_client"
                )
        return self._client

    async def call(
        self,
        server_name: str,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> MCPToolResult:
        """Invoke a tool on an MCP server.

        Args:
            server_name: Name of the connected server.
            tool_name: Tool to invoke.
            arguments: Tool arguments.

        Returns:
            MCPToolResult with the tool output.
        """
        try:
            client = self._ensure_client()
        except RuntimeError as exc:
            return MCPToolResult(success=False, message=str(exc), error="no_client")

        # Verify server is connected
        servers = client.list_servers()
        if server_name not in servers:
            return MCPToolResult(
                success=False,
                message=f"Server '{server_name}' is not connected",
                error="server_not_connected",
            )

        result = await client.call_tool(tool_name, arguments)
        return MCPToolResult(
            success=result.success,
            message="Tool call succeeded" if result.success else "Tool call failed",
            content=result.content,
            error=result.error,
        )

    async def connect(
        self,
        server_name: str,
        command: Optional[str] = None,
        args: Optional[List[str]] = None,
        url: Optional[str] = None,
    ) -> MCPToolResult:
        """Connect to an MCP server.

        Provide either *command* (for stdio transport) or *url* (for HTTP
        transport).

        Args:
            server_name: Name to assign to this server connection.
            command: Executable for stdio transport.
            args: Arguments for the stdio command.
            url: URL for HTTP/SSE transport.

        Returns:
            MCPToolResult indicating connection status.
        """
        try:
            client = self._ensure_client()
        except RuntimeError as exc:
            return MCPToolResult(success=False, message=str(exc), error="no_client")

        try:
            from agent.services.mcp_client.transport import TransportConfig, TransportType
        except ImportError:
            return MCPToolResult(
                success=False,
                message="MCP transport module not available",
                error="import_error",
            )

        if command:
            config = TransportConfig(
                transport_type=TransportType.STDIO,
                command=command,
                args=args or [],
            )
        elif url:
            config = TransportConfig(
                transport_type=TransportType.HTTP,
                url=url,
            )
        else:
            return MCPToolResult(
                success=False,
                message="Either 'command' or 'url' must be provided",
                error="missing_transport",
            )

        result = await client.connect_server(server_name, config)
        if result.success:
            # Discover tools after connecting
            try:
                await client.discover_tools(server_name)
            except Exception as exc:
                logger.warning("Tool discovery after connect failed: %s", exc)

        return MCPToolResult(
            success=result.success,
            message=f"Connected to '{server_name}'" if result.success else f"Connection failed: {result.error}",
            content=result.content,
            error=result.error,
        )

    def list_servers(self) -> MCPToolResult:
        """List all connected MCP servers.

        Returns:
            MCPToolResult with server name to connection-status mapping.
        """
        try:
            client = self._ensure_client()
        except RuntimeError as exc:
            return MCPToolResult(success=False, message=str(exc), error="no_client")

        servers = client.list_servers()
        return MCPToolResult(
            success=True,
            message=f"Found {len(servers)} server(s)",
            servers=servers,
        )

    def list_tools(self) -> MCPToolResult:
        """List all discovered MCP tools across servers.

        Returns:
            MCPToolResult with tool information.
        """
        try:
            client = self._ensure_client()
        except RuntimeError as exc:
            return MCPToolResult(success=False, message=str(exc), error="no_client")

        tools = client.list_tools()
        tool_dicts = [
            {
                "name": t.name,
                "description": t.description,
                "server": t.server_name,
                "input_schema": t.input_schema,
            }
            for t in tools
        ]
        return MCPToolResult(
            success=True,
            message=f"Found {len(tool_dicts)} tool(s)",
            tools=tool_dicts,
        )


# ---------------------------------------------------------------------------
# ListMcpResourcesTool
# ---------------------------------------------------------------------------

class ListMcpResourcesTool:
    """List available MCP resources across connected servers."""

    def __init__(self, mcp_client: Any = None) -> None:
        self._client = mcp_client

    def _ensure_client(self) -> Any:
        if self._client is None:
            try:
                from agent.services.mcp_client import MCPClient
                self._client = MCPClient()
            except ImportError:
                raise RuntimeError("MCPClient not available")
        return self._client

    async def list_resources(
        self,
        server_name: Optional[str] = None,
    ) -> MCPToolResult:
        """List MCP resources, optionally filtered by server.

        Args:
            server_name: If provided, only discover resources from this
                server.  Otherwise discover from all connected servers.

        Returns:
            MCPToolResult with resource information.
        """
        try:
            client = self._ensure_client()
        except RuntimeError as exc:
            return MCPToolResult(success=False, message=str(exc), error="no_client")

        servers = client.list_servers()
        if not servers:
            return MCPToolResult(
                success=True,
                message="No MCP servers connected",
                resources=[],
            )

        target_servers = [server_name] if server_name else list(servers.keys())
        all_resources: List[Dict[str, Any]] = []

        for sname in target_servers:
            if sname not in servers:
                continue
            try:
                resources = await client.discover_resources(sname)
                for r in resources:
                    all_resources.append({
                        "uri": r.uri,
                        "name": r.name,
                        "description": r.description,
                        "mime_type": r.mime_type,
                        "server": sname,
                    })
            except Exception as exc:
                logger.warning("Resource discovery failed for '%s': %s", sname, exc)

        return MCPToolResult(
            success=True,
            message=f"Found {len(all_resources)} resource(s)",
            resources=all_resources,
        )


# ---------------------------------------------------------------------------
# ReadMcpResourceTool
# ---------------------------------------------------------------------------

class ReadMcpResourceTool:
    """Read an MCP resource by URI."""

    def __init__(self, mcp_client: Any = None) -> None:
        self._client = mcp_client

    def _ensure_client(self) -> Any:
        if self._client is None:
            try:
                from agent.services.mcp_client import MCPClient
                self._client = MCPClient()
            except ImportError:
                raise RuntimeError("MCPClient not available")
        return self._client

    async def read(self, uri: str) -> MCPToolResult:
        """Read a resource by its URI.

        Args:
            uri: The MCP resource URI (e.g. ``file:///path`` or a custom
                scheme).

        Returns:
            MCPToolResult with the resource contents.
        """
        if not uri or not uri.strip():
            return MCPToolResult(
                success=False,
                message="Resource URI cannot be empty",
                error="empty_uri",
            )

        try:
            client = self._ensure_client()
        except RuntimeError as exc:
            return MCPToolResult(success=False, message=str(exc), error="no_client")

        result = await client.read_resource(uri.strip())
        return MCPToolResult(
            success=result.success,
            message="Resource read successfully" if result.success else f"Failed to read resource: {result.error}",
            content=result.content,
            error=result.error,
        )


# ---------------------------------------------------------------------------
# SkillTool
# ---------------------------------------------------------------------------

class SkillTool:
    """Invoke slash commands / skills programmatically.

    Skills are named actions (e.g. ``commit``, ``review-pr``, ``compact``)
    that can be triggered without going through the interactive command
    parser.
    """

    # Built-in skill metadata -- actual implementations are provided by the
    # command handler or the skills subsystem.
    _BUILTIN_SKILLS: List[Dict[str, str]] = [
        {"name": "commit", "description": "Create a git commit with a generated message"},
        {"name": "review-pr", "description": "Review a GitHub pull request"},
        {"name": "compact", "description": "Compact conversation history to save tokens"},
        {"name": "simplify", "description": "Review changed code for quality and fix issues"},
        {"name": "loop", "description": "Run a prompt or command on a recurring interval"},
        {"name": "schedule", "description": "Create, list, or manage scheduled remote agents"},
        {"name": "claude-api", "description": "Help build apps with the Claude API / Anthropic SDK"},
        {"name": "update-config", "description": "Configure the Claude Code harness via settings.json"},
        {"name": "keybindings-help", "description": "Customize keyboard shortcuts and keybindings"},
    ]

    def __init__(self, command_handler: Any = None) -> None:
        self._handler = command_handler
        self._custom_skills: List[Dict[str, str]] = []

    def invoke(self, skill_name: str, args: str = "") -> SkillResult:
        """Invoke a skill by name.

        Args:
            skill_name: Skill identifier (e.g. ``"commit"``).
            args: Arguments to pass to the skill.

        Returns:
            SkillResult with the skill output.
        """
        if not skill_name or not skill_name.strip():
            return SkillResult(
                success=False,
                message="Skill name cannot be empty",
                error="empty_skill_name",
            )

        skill_name = skill_name.strip().lower()

        # Check availability
        all_skills = self._BUILTIN_SKILLS + self._custom_skills
        known_names = {s["name"] for s in all_skills}

        if skill_name not in known_names:
            return SkillResult(
                success=False,
                message=f"Unknown skill '{skill_name}'",
                skill_name=skill_name,
                available_skills=all_skills,
                error="unknown_skill",
            )

        # Delegate to command handler if available
        if self._handler is not None:
            try:
                if hasattr(self._handler, "execute_skill"):
                    output = self._handler.execute_skill(skill_name, args)
                elif hasattr(self._handler, "handle_command"):
                    output = self._handler.handle_command(f"/{skill_name} {args}".strip())
                else:
                    output = f"Skill '{skill_name}' dispatched (handler has no execute_skill method)"
            except Exception as exc:
                return SkillResult(
                    success=False,
                    message=f"Skill execution failed: {exc}",
                    skill_name=skill_name,
                    error=str(exc),
                )
        else:
            output = f"Skill '{skill_name}' recognised but no command handler configured"

        return SkillResult(
            success=True,
            message=f"Skill '{skill_name}' invoked",
            skill_name=skill_name,
            output=output,
        )

    def register_skill(self, name: str, description: str = "") -> SkillResult:
        """Register a custom skill.

        Args:
            name: Skill name.
            description: Human-readable description.

        Returns:
            SkillResult confirming registration.
        """
        if not name or not name.strip():
            return SkillResult(
                success=False,
                message="Skill name cannot be empty",
                error="empty_skill_name",
            )

        name = name.strip().lower()
        all_names = {s["name"] for s in self._BUILTIN_SKILLS + self._custom_skills}
        if name in all_names:
            return SkillResult(
                success=False,
                message=f"Skill '{name}' already exists",
                error="duplicate_skill",
            )

        self._custom_skills.append({"name": name, "description": description})
        return SkillResult(
            success=True,
            message=f"Skill '{name}' registered",
            skill_name=name,
        )

    def list_skills(self) -> SkillResult:
        """List all available skills.

        Returns:
            SkillResult with the list of skills.
        """
        all_skills = self._BUILTIN_SKILLS + self._custom_skills
        return SkillResult(
            success=True,
            message=f"Found {len(all_skills)} skill(s)",
            available_skills=all_skills,
        )


# ---------------------------------------------------------------------------
# ConfigTool
# ---------------------------------------------------------------------------

class ConfigTool:
    """Read and modify agent configuration at runtime.

    Configuration is persisted as a JSON file.  Changes made via
    ``set`` are written immediately.
    """

    _DEFAULTS: Dict[str, Any] = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 8192,
        "temperature": 0.7,
        "theme": "dark",
        "verbose": False,
        "auto_compact": True,
        "compact_threshold": 100000,
        "brief_mode": False,
        "safety_mode": "normal",
        "allowed_tools": [],
    }

    def __init__(self, config_path: Optional[str] = None) -> None:
        self.config_path = config_path or os.path.expanduser("~/.neomind/config.json")
        self._config: Dict[str, Any] = dict(self._DEFAULTS)
        self._load()

    # -- persistence -------------------------------------------------------

    def _load(self) -> None:
        """Load config from disk, merging with defaults."""
        try:
            with open(self.config_path, "r", encoding="utf-8") as fh:
                stored = json.load(fh)
            self._config.update(stored)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def _save(self) -> None:
        """Persist current config to disk."""
        config_dir = os.path.dirname(self.config_path)
        if config_dir:
            os.makedirs(config_dir, exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as fh:
            json.dump(self._config, fh, indent=2)

    # -- public API --------------------------------------------------------

    def get(self, key: Optional[str] = None) -> ConfigResult:
        """Get a configuration value or the entire config.

        Args:
            key: Config key.  If *None*, the entire config is returned.

        Returns:
            ConfigResult with the value or full config dict.
        """
        if key is None:
            return ConfigResult(
                success=True,
                message="Full configuration retrieved",
                config=dict(self._config),
            )

        if key not in self._config:
            return ConfigResult(
                success=False,
                message=f"Unknown config key '{key}'",
                key=key,
                error="unknown_key",
            )

        return ConfigResult(
            success=True,
            message=f"Config '{key}' retrieved",
            key=key,
            value=self._config[key],
        )

    def set(self, key: str, value: Any) -> ConfigResult:
        """Set a configuration value.

        The change is persisted to disk immediately.

        Args:
            key: Config key.
            value: New value.

        Returns:
            ConfigResult confirming the change.
        """
        if not key or not key.strip():
            return ConfigResult(
                success=False,
                message="Config key cannot be empty",
                error="empty_key",
            )

        key = key.strip()
        old_value = self._config.get(key)
        self._config[key] = value
        self._save()

        logger.info("Config '%s' changed: %r -> %r", key, old_value, value)
        return ConfigResult(
            success=True,
            message=f"Config '{key}' set to {value!r}",
            key=key,
            value=value,
        )

    def reset(self, key: Optional[str] = None) -> ConfigResult:
        """Reset configuration to defaults.

        Args:
            key: If provided, reset only this key.  Otherwise reset all.

        Returns:
            ConfigResult confirming the reset.
        """
        if key is not None:
            if key not in self._DEFAULTS:
                return ConfigResult(
                    success=False,
                    message=f"Unknown default config key '{key}'",
                    key=key,
                    error="unknown_key",
                )
            self._config[key] = self._DEFAULTS[key]
            self._save()
            return ConfigResult(
                success=True,
                message=f"Config '{key}' reset to default ({self._DEFAULTS[key]!r})",
                key=key,
                value=self._DEFAULTS[key],
            )

        self._config = dict(self._DEFAULTS)
        self._save()
        return ConfigResult(
            success=True,
            message="All config reset to defaults",
            config=dict(self._config),
        )


# ---------------------------------------------------------------------------
# ToolSearchTool
# ---------------------------------------------------------------------------

class ToolSearchTool:
    """Search available tools by name or description.

    Accepts a registry of tool metadata and performs fuzzy matching
    against tool names and descriptions.
    """

    def __init__(self, tool_registry: Optional[List[Dict[str, Any]]] = None) -> None:
        self._registry: List[Dict[str, Any]] = tool_registry or []

    def register(self, name: str, description: str, category: str = "") -> None:
        """Add a tool to the searchable registry.

        Args:
            name: Tool name.
            description: Tool description.
            category: Optional category tag.
        """
        self._registry.append({
            "name": name,
            "description": description,
            "category": category,
        })

    def search(
        self,
        query: str,
        max_results: int = 10,
    ) -> ToolSearchResult:
        """Search tools by name or description keywords.

        Scoring is based on:
        - Exact name match (highest)
        - Name contains query
        - Description contains query words

        Args:
            query: Search query string.
            max_results: Maximum number of results to return.

        Returns:
            ToolSearchResult with matching tools and relevance scores.
        """
        if not query or not query.strip():
            return ToolSearchResult(
                success=True,
                message=f"All {len(self._registry)} tools",
                matches=[
                    {**t, "score": 1.0}
                    for t in self._registry[:max_results]
                ],
            )

        query_lower = query.strip().lower()
        query_words = query_lower.split()

        scored: List[Tuple[float, Dict[str, Any]]] = []

        for tool in self._registry:
            name_lower = tool["name"].lower()
            desc_lower = tool.get("description", "").lower()
            cat_lower = tool.get("category", "").lower()

            score = 0.0

            # Exact name match
            if name_lower == query_lower:
                score += 10.0
            # Name starts with query
            elif name_lower.startswith(query_lower):
                score += 5.0
            # Name contains query
            elif query_lower in name_lower:
                score += 3.0

            # Word-level matching in name
            for word in query_words:
                if word in name_lower:
                    score += 2.0
                if word in desc_lower:
                    score += 1.0
                if word in cat_lower:
                    score += 0.5

            if score > 0:
                scored.append((score, {**tool, "score": round(score, 2)}))

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)
        matches = [item[1] for item in scored[:max_results]]

        return ToolSearchResult(
            success=True,
            message=f"Found {len(matches)} matching tool(s) for '{query}'",
            matches=matches,
        )


# ---------------------------------------------------------------------------
# TaskOutputTool
# ---------------------------------------------------------------------------

class TaskOutputTool:
    """Read output from a running or completed task.

    Works with the :class:`TaskManager` from ``agent.tools.task_tools``.
    """

    def __init__(self, task_manager: Any = None) -> None:
        self._manager = task_manager
        self._output_buffers: Dict[str, List[str]] = {}

    def append_output(self, task_id: str, line: str) -> None:
        """Append a line of output for a task.

        Typically called by the task execution layer.

        Args:
            task_id: Task identifier.
            line: Output line to append.
        """
        if task_id not in self._output_buffers:
            self._output_buffers[task_id] = []
        self._output_buffers[task_id].append(line)

    def read_output(
        self,
        task_id: str,
        tail: int = 50,
        offset: int = 0,
    ) -> TaskOutputResult:
        """Read output from a task.

        Args:
            task_id: Task identifier.
            tail: Number of most-recent lines to return.  Set to ``0``
                for all lines.
            offset: Skip this many lines from the end before applying
                *tail*.

        Returns:
            TaskOutputResult with the output lines.
        """
        if not task_id or not task_id.strip():
            return TaskOutputResult(
                success=False,
                message="Task ID cannot be empty",
                error="empty_task_id",
            )

        task_id = task_id.strip()

        # Check task existence via manager
        is_running = False
        if self._manager is not None:
            result = self._manager.get(task_id)
            if not result.success:
                return TaskOutputResult(
                    success=False,
                    message=f"Task '{task_id}' not found",
                    task_id=task_id,
                    error="not_found",
                )
            if result.task is not None:
                is_running = result.task.status.value == "in_progress"

        lines = self._output_buffers.get(task_id, [])

        if not lines:
            return TaskOutputResult(
                success=True,
                message=f"No output available for task '{task_id}'",
                task_id=task_id,
                output_lines=[],
                is_running=is_running,
            )

        # Apply offset and tail
        if offset > 0:
            lines = lines[:-offset] if offset < len(lines) else []
        if tail > 0 and len(lines) > tail:
            lines = lines[-tail:]

        return TaskOutputResult(
            success=True,
            message=f"Retrieved {len(lines)} line(s) of output for task '{task_id}'",
            task_id=task_id,
            output_lines=list(lines),
            is_running=is_running,
        )

    def clear_output(self, task_id: str) -> TaskOutputResult:
        """Clear buffered output for a task.

        Args:
            task_id: Task identifier.

        Returns:
            TaskOutputResult confirming the clear.
        """
        removed_count = len(self._output_buffers.pop(task_id, []))
        return TaskOutputResult(
            success=True,
            message=f"Cleared {removed_count} line(s) of output for task '{task_id}'",
            task_id=task_id,
        )


# ---------------------------------------------------------------------------
# PowerShellTool
# ---------------------------------------------------------------------------

class PowerShellTool:
    """Execute PowerShell commands (cross-platform via PowerShell Core).

    Prefers ``pwsh`` (PowerShell Core, cross-platform).  Falls back to
    ``powershell`` on Windows when ``pwsh`` is not available.
    """

    def __init__(self) -> None:
        self._executable: Optional[str] = None

    def _find_executable(self) -> Optional[str]:
        """Locate the PowerShell executable."""
        if self._executable is not None:
            return self._executable

        # Prefer pwsh (PowerShell Core -- cross-platform)
        if shutil.which("pwsh"):
            self._executable = "pwsh"
        elif platform.system() == "Windows" and shutil.which("powershell"):
            self._executable = "powershell"
        return self._executable

    def execute(
        self,
        command: str,
        timeout: int = 120,
        working_dir: Optional[str] = None,
    ) -> PowerShellResult:
        """Execute a PowerShell command.

        Args:
            command: PowerShell command string.
            timeout: Maximum execution time in seconds.
            working_dir: Working directory.

        Returns:
            PowerShellResult with stdout, stderr, and return code.
        """
        if not command or not command.strip():
            return PowerShellResult(
                success=False,
                message="Command cannot be empty",
                error="empty_command",
            )

        executable = self._find_executable()
        if executable is None:
            return PowerShellResult(
                success=False,
                message="PowerShell is not available (neither 'pwsh' nor 'powershell' found)",
                error="not_available",
            )

        cmd = [executable, "-NoProfile", "-NonInteractive", "-Command", command]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=working_dir,
            )

            return PowerShellResult(
                success=result.returncode == 0,
                message="Command completed" if result.returncode == 0 else "Command failed",
                stdout=result.stdout,
                stderr=result.stderr,
                return_code=result.returncode,
            )

        except subprocess.TimeoutExpired:
            return PowerShellResult(
                success=False,
                message=f"Command timed out after {timeout}s",
                error="timeout",
            )
        except Exception as exc:
            return PowerShellResult(
                success=False,
                message=f"Execution error: {exc}",
                error=str(exc),
            )


# ---------------------------------------------------------------------------
# CronManager  (individual cron create / delete / list tools)
# ---------------------------------------------------------------------------

class CronManager:
    """Individual cron job management tools.

    Wraps :class:`ScheduleCronTool` from ``agent.tools.collaboration_tools``
    to expose individual ``create``, ``delete``, and ``list_jobs`` methods.
    """

    def __init__(self, storage_path: Optional[str] = None) -> None:
        self._scheduler: Any = None
        self._storage_path = storage_path

    def _ensure_scheduler(self) -> Any:
        """Lazily import and initialise the scheduler."""
        if self._scheduler is None:
            try:
                from agent.tools.collaboration_tools import ScheduleCronTool
                self._scheduler = ScheduleCronTool(storage_path=self._storage_path)
            except ImportError:
                raise RuntimeError("ScheduleCronTool not available")
        return self._scheduler

    def create(
        self,
        name: str,
        cron_expr: str,
        command: str,
        description: str = "",
    ) -> CronResult:
        """Create a new cron job.

        Args:
            name: Unique job name.
            cron_expr: Cron expression (``minute hour day month weekday``).
            command: Command to execute on each trigger.
            description: Human-readable description.

        Returns:
            CronResult indicating success or failure.
        """
        try:
            scheduler = self._ensure_scheduler()
        except RuntimeError as exc:
            return CronResult(success=False, message=str(exc), error="no_scheduler")

        result = scheduler.create(name, cron_expr, command, description)
        if result.success:
            return CronResult(
                success=True,
                message=result.message,
                name=name,
            )
        return CronResult(
            success=False,
            message=result.message,
            name=name,
            error=result.error,
        )

    def delete(self, name: str) -> CronResult:
        """Delete a cron job by name.

        Args:
            name: Job name.

        Returns:
            CronResult indicating success or failure.
        """
        try:
            scheduler = self._ensure_scheduler()
        except RuntimeError as exc:
            return CronResult(success=False, message=str(exc), error="no_scheduler")

        result = scheduler.delete(name)
        if result.success:
            return CronResult(
                success=True,
                message=result.message,
                name=name,
            )
        return CronResult(
            success=False,
            message=result.message,
            name=name,
            error=result.error,
        )

    def list_jobs(self) -> CronResult:
        """List all cron jobs.

        Returns:
            CronResult with a list of job dicts.
        """
        try:
            scheduler = self._ensure_scheduler()
        except RuntimeError as exc:
            return CronResult(success=False, message=str(exc), error="no_scheduler")

        result = scheduler.list_schedules()
        jobs: List[Dict[str, Any]] = []
        for sched in (result.schedules or []):
            jobs.append({
                "name": sched.name,
                "cron_expr": sched.cron_expr,
                "command": sched.command,
                "description": sched.description,
                "enabled": sched.enabled,
                "created_at": sched.created_at.isoformat(),
            })

        return CronResult(
            success=True,
            message=result.message,
            jobs=jobs,
        )


# ---------------------------------------------------------------------------
# Module exports
# ---------------------------------------------------------------------------

__all__ = [
    # Enums
    "REPLLanguage",
    "WorktreeStatus",
    "ConfigScope",
    # Result dataclasses
    "WorktreeResult",
    "REPLResult",
    "MCPToolResult",
    "SkillResult",
    "ConfigResult",
    "ToolSearchResult",
    "TaskOutputResult",
    "PowerShellResult",
    "CronResult",
    # Tools
    "WorktreeTool",
    "REPLTool",
    "MCPToolAdapter",
    "ListMcpResourcesTool",
    "ReadMcpResourceTool",
    "SkillTool",
    "ConfigTool",
    "ToolSearchTool",
    "TaskOutputTool",
    "PowerShellTool",
    "CronManager",
]


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import asyncio as _asyncio

    print("=== Advanced Tools Smoke Test ===\n")

    # -- REPLTool --
    repl = REPLTool()
    r = repl.execute("print('hello from REPL')", language="python")
    print(f"REPL execute: success={r.success} stdout={r.stdout.strip()!r}")

    sess = repl.create_session("python", name="test-session")
    print(f"REPL session: {sess.session_id}")
    repl.close_session(sess.session_id)

    # -- ConfigTool --
    import tempfile as _tf
    with _tf.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        cfg = ConfigTool(config_path=tmp_path)
        r = cfg.get("model")
        print(f"Config get: {r.key}={r.value!r}")
        cfg.set("model", "claude-opus-4-20250514")
        r2 = cfg.get("model")
        print(f"Config after set: {r2.key}={r2.value!r}")
        cfg.reset("model")
        r3 = cfg.get("model")
        print(f"Config after reset: {r3.key}={r3.value!r}")
    finally:
        os.unlink(tmp_path)

    # -- ToolSearchTool --
    ts = ToolSearchTool()
    ts.register("Read", "Read a file from disk", "filesystem")
    ts.register("Edit", "Edit a file with string replacements", "filesystem")
    ts.register("Bash", "Execute shell commands", "execution")
    ts.register("Grep", "Search file contents with regex", "search")
    r = ts.search("file")
    print(f"Tool search 'file': {len(r.matches)} matches")
    for m in r.matches:
        print(f"  {m['name']} (score={m['score']})")

    # -- SkillTool --
    sk = SkillTool()
    r = sk.list_skills()
    print(f"\nSkills: {len(r.available_skills)} available")
    r2 = sk.invoke("commit")
    print(f"Invoke 'commit': {r2.message}")

    # -- TaskOutputTool --
    to = TaskOutputTool()
    to.append_output("task-1", "Line 1")
    to.append_output("task-1", "Line 2")
    to.append_output("task-1", "Line 3")
    r = to.read_output("task-1", tail=2)
    print(f"\nTask output: {r.output_lines}")

    # -- CronManager --
    cm = CronManager()
    r = cm.create("test-job", "*/5 * * * *", "echo hello", "Test job")
    print(f"\nCron create: {r.message}")
    r2 = cm.list_jobs()
    print(f"Cron list: {r2.message} ({len(r2.jobs or [])} jobs)")
    r3 = cm.delete("test-job")
    print(f"Cron delete: {r3.message}")

    # -- PowerShellTool --
    ps = PowerShellTool()
    exe = ps._find_executable()
    print(f"\nPowerShell executable: {exe or 'not found'}")

    print("\n=== Advanced Tools Smoke Test Complete ===")
