"""
NeoMind tool system for coding mode.

Provides structured tools with built-in capabilities:
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
    """Standardized result from any tool execution.

    Attributes:
        success: Whether the tool executed successfully
        output: The tool's stdout/primary output
        error: Error message if failed
        metadata: Structured metadata about the execution (e.g. lines_read,
                  exit_code, files_matched, duration_ms, file_path)
    """

    def __init__(self, success: bool, output: str = "", error: str = "",
                 metadata: Optional[Dict[str, Any]] = None):
        self.success = success
        self.output = output
        self.error = error
        self.metadata = metadata or {}

    def __str__(self):
        if self.success:
            return self.output
        return f"Error: {self.error}"

    def __bool__(self):
        return self.success

    def __repr__(self):
        status = "OK" if self.success else "ERROR"
        preview = (self.output or self.error)[:60]
        return f"ToolResult({status}, {preview!r})"


class ToolRegistry:
    """NeoMind tool system for coding mode.

    Each tool returns a ToolResult with structured output.
    Tools are registered with typed schemas (ToolDefinition) for:
    - Parameter validation before execution
    - Per-tool permission levels
    - Auto-generated system prompt sections
    """

    # Max result sizes per tool — results exceeding this are persisted to disk
    TOOL_MAX_RESULT_CHARS = {
        'Grep': 50000,
        'Glob': 30000,
        'Bash': 50000,
        'WebFetch': 40000,
        'WebSearch': 30000,
    }

    def __init__(self, working_dir: Optional[str] = None, deny_rules: Optional[List[str]] = None):
        self.working_dir = working_dir or os.getcwd()
        self._persistent_bash = None  # Lazy init
        self._tool_definitions: Dict[str, Any] = {}  # name → ToolDefinition
        self._files_read: set = set()   # Track files read in this session (for read-before-edit)
        self._files_mtime: Dict[str, float] = {}  # path → mtime at read time (staleness detection)
        self._files_read_ranges: Dict[str, List[Tuple[int, int]]] = {}  # path → [(offset, limit), ...] (dedup)
        self._tool_call_cache: Dict[str, 'ToolResult'] = {}  # dedup cache for read-only tools
        self._plan_mode: bool = False   # When True, block write/execute tools
        self._task_manager = None
        # Deny rules: patterns that remove tools from the prompt BEFORE the LLM sees them.
        # Format: "ToolName" or "ToolName(pattern)" — e.g. "Bash(git push:*)", "Write(*.env)".
        # This is a security boundary — tools matching deny rules are invisible to the LLM.
        self._deny_rules: List[str] = deny_rules or []
        self._deferred_tool_threshold: int = 20  # When tool count exceeds this, defer non-essential tools
        self._deferred_tools_enabled: bool = True
        self._register_tools()

    def _persist_large_result(self, tool_name: str, result: 'ToolResult') -> 'ToolResult':
        """If result exceeds tool's max size, save to disk and return a reference."""
        max_chars = self.TOOL_MAX_RESULT_CHARS.get(tool_name, 0)
        if max_chars <= 0 or len(result.output) <= max_chars:
            return result
        # Persist to disk
        import time as _t
        output_dir = os.path.join(self.working_dir, '.neomind_tool_outputs')
        os.makedirs(output_dir, exist_ok=True)
        timestamp = _t.strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{tool_name}.txt"
        filepath = os.path.join(output_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(result.output)
        truncated = result.output[:max_chars // 2] + f"\n\n... [{len(result.output):,} chars total — full output saved to: {filepath}]\nUse the Read tool to inspect relevant sections.\n"
        return ToolResult(
            success=result.success,
            output=truncated,
            error=result.error,
            metadata={**result.metadata, 'persisted_to': filepath, 'original_chars': len(result.output)},
        )

    def _register_tools(self):
        """Register all built-in tools with their schemas."""
        from agent.tool_schema import ToolDefinition, ToolParam, ParamType, PermissionLevel

        self._tool_definitions = {}

        # ── Bash ──
        self._tool_definitions["Bash"] = ToolDefinition(
            name="Bash",
            description="Execute shell commands in a persistent bash session (cd/export carry across calls)",
            parameters=[
                ToolParam("command", ParamType.STRING, "Shell command to execute"),
                ToolParam("timeout", ParamType.INTEGER,
                          "Timeout in seconds", required=False, default=120),
            ],
            permission_level=PermissionLevel.EXECUTE,
            execute=self._exec_bash,
            examples=[
                {"command": "ls -la src/"},
                {"command": "python3 -m pytest tests/ -v", "timeout": 60},
                {"command": "git status"},
                {"command": "pip install requests --break-system-packages"},
            ],
        )

        # ── Read ──
        self._tool_definitions["Read"] = ToolDefinition(
            name="Read",
            description="Read a file with line numbers (auto-truncated at 30K chars)",
            parameters=[
                ToolParam("path", ParamType.STRING, "File path (absolute or relative to workspace)"),
                ToolParam("offset", ParamType.INTEGER,
                          "Starting line number (0 = from beginning)", required=False, default=0),
                ToolParam("limit", ParamType.INTEGER,
                          "Max lines to read (0 = all)", required=False, default=0),
            ],
            permission_level=PermissionLevel.READ_ONLY,
            execute=self._exec_read,
            examples=[
                {"path": "src/main.py"},
                {"path": "src/main.py", "offset": 50, "limit": 20},
            ],
        )

        # ── Write ──
        self._tool_definitions["Write"] = ToolDefinition(
            name="Write",
            description="Create a new file or overwrite an existing file",
            parameters=[
                ToolParam("path", ParamType.STRING, "File path"),
                ToolParam("content", ParamType.STRING, "File content to write"),
            ],
            permission_level=PermissionLevel.WRITE,
            execute=self._exec_write,
            examples=[
                {"path": "src/hello.py", "content": "print('Hello, world!')\\n"},
            ],
            interrupt_behavior='block',  # Don't corrupt files mid-write
        )

        # ── Edit ──
        self._tool_definitions["Edit"] = ToolDefinition(
            name="Edit",
            description="Edit a file by replacing exact string matches (read file first to get exact content)",
            parameters=[
                ToolParam("path", ParamType.STRING, "File path"),
                ToolParam("old_string", ParamType.STRING, "Exact text to find and replace"),
                ToolParam("new_string", ParamType.STRING, "Replacement text"),
                ToolParam("replace_all", ParamType.BOOLEAN,
                          "Replace all occurrences (default: first only)", required=False, default=False),
            ],
            permission_level=PermissionLevel.WRITE,
            execute=self._exec_edit,
            examples=[
                {"path": "src/main.py", "old_string": "def old_name(", "new_string": "def new_name("},
            ],
        )

        # ── Glob ──
        self._tool_definitions["Glob"] = ToolDefinition(
            name="Glob",
            description="Find files matching a glob pattern (sorted by modification time, most recent first)",
            parameters=[
                ToolParam("pattern", ParamType.STRING, "Glob pattern (e.g. '**/*.py', 'src/**/*.ts')"),
                ToolParam("path", ParamType.STRING,
                          "Base directory (default: workspace)", required=False, default=None),
            ],
            permission_level=PermissionLevel.READ_ONLY,
            execute=self._exec_glob,
            examples=[
                {"pattern": "**/*.py"},
                {"pattern": "src/**/*.ts", "path": "/project"},
            ],
        )

        # ── Grep ──
        self._tool_definitions["Grep"] = ToolDefinition(
            name="Grep",
            description="Search file contents with regex (uses ripgrep when available for 5-10x speed)",
            parameters=[
                ToolParam("pattern", ParamType.STRING, "Regex pattern to search for"),
                ToolParam("path", ParamType.STRING,
                          "Directory to search (default: workspace)", required=False, default=None),
                ToolParam("file_type", ParamType.STRING,
                          "Filter by extension (e.g. 'py', 'js')", required=False, default=None),
                ToolParam("context", ParamType.INTEGER,
                          "Lines of context around matches", required=False, default=0),
                ToolParam("case_insensitive", ParamType.BOOLEAN,
                          "Case insensitive search", required=False, default=False),
                ToolParam("output_mode", ParamType.STRING,
                          "Output format", required=False, default="content",
                          enum=["content", "files_with_matches", "count"]),
            ],
            permission_level=PermissionLevel.READ_ONLY,
            execute=self._exec_grep,
            examples=[
                {"pattern": "def main\\("},
                {"pattern": "TODO|FIXME", "file_type": "py", "case_insensitive": True},
                {"pattern": "import", "output_mode": "files_with_matches"},
            ],
        )

        # ── LS ──
        self._tool_definitions["LS"] = ToolDefinition(
            name="LS",
            description="List directory contents with file sizes",
            parameters=[
                ToolParam("path", ParamType.STRING,
                          "Directory path (default: workspace)", required=False, default=None),
            ],
            permission_level=PermissionLevel.READ_ONLY,
            execute=self._exec_ls,
            examples=[
                {},
                {"path": "src/"},
            ],
        )

        # ── SelfEditor (self-modification with safety gates) ──
        self._tool_definitions["SelfEditor"] = ToolDefinition(
            name="SelfEditor",
            description=(
                "Modify NeoMind's own Python source code. Every edit goes through "
                "8 safety gates (syntax, AST, constitutional review, etc.) and is "
                "git-committed. After editing, the system auto-chooses hot-reload "
                "or process restart. Use this to fix bugs, improve prompts, or "
                "add features to yourself."
            ),
            parameters=[
                ToolParam("file_path", ParamType.STRING,
                          "Path relative to /app (e.g. 'agent/config/chat.yaml')"),
                ToolParam("new_content", ParamType.STRING,
                          "Complete new file content (replaces entire file)"),
                ToolParam("reason", ParamType.STRING,
                          "Why this change improves NeoMind (for audit trail)"),
            ],
            permission_level=PermissionLevel.DESTRUCTIVE,
            execute=self._exec_self_editor,
            examples=[
                {
                    "file_path": "agent/evolution/example.py",
                    "new_content": "# improved version\\ndef better():\\n    pass\\n",
                    "reason": "Refactored for clarity",
                },
            ],
        )

        # ── TaskManager ──
        self._task_manager = None  # Lazy init
        self._tool_definitions["TaskCreate"] = ToolDefinition(
            name="TaskCreate",
            description="Create a task to track progress on complex work",
            parameters=[
                ToolParam("subject", ParamType.STRING, "Brief task title"),
                ToolParam("description", ParamType.STRING, "What needs to be done"),
            ],
            permission_level=PermissionLevel.READ_ONLY,
            execute=self._exec_task_create,
            examples=[
                {"subject": "Fix auth bug", "description": "Login returns 500 on empty password"},
            ],
        )

        self._tool_definitions["TaskGet"] = ToolDefinition(
            name="TaskGet",
            description="Get a task by its ID",
            parameters=[
                ToolParam("task_id", ParamType.STRING, "Task ID (e.g. 'task-1')"),
            ],
            permission_level=PermissionLevel.READ_ONLY,
            execute=self._exec_task_get,
        )

        self._tool_definitions["TaskList"] = ToolDefinition(
            name="TaskList",
            description="List all tasks, optionally filtered by status",
            parameters=[
                ToolParam("status", ParamType.STRING, "Filter by status",
                          required=False, default=None,
                          enum=["pending", "in_progress", "completed", "cancelled"]),
            ],
            permission_level=PermissionLevel.READ_ONLY,
            execute=self._exec_task_list,
        )

        self._tool_definitions["TaskUpdate"] = ToolDefinition(
            name="TaskUpdate",
            description="Update a task's status, subject, or description",
            parameters=[
                ToolParam("task_id", ParamType.STRING, "Task ID"),
                ToolParam("status", ParamType.STRING, "New status",
                          required=False, default=None,
                          enum=["pending", "in_progress", "completed", "cancelled"]),
                ToolParam("subject", ParamType.STRING, "New subject",
                          required=False, default=None),
                ToolParam("description", ParamType.STRING, "New description",
                          required=False, default=None),
            ],
            permission_level=PermissionLevel.READ_ONLY,
            execute=self._exec_task_update,
        )

        self._tool_definitions["TaskStop"] = ToolDefinition(
            name="TaskStop",
            description="Cancel/stop a task",
            parameters=[
                ToolParam("task_id", ParamType.STRING, "Task ID to cancel"),
            ],
            permission_level=PermissionLevel.READ_ONLY,
            execute=self._exec_task_stop,
        )

        # ── Utility Tools ──
        self._web_fetch_tool = None    # Lazy init
        self._web_search_tool = None   # Lazy init
        self._notebook_edit_tool = None  # Lazy init
        self._todo_write_tool = None   # Lazy init
        self._ask_user_tool = None     # Lazy init
        self._sleep_tool = None        # Lazy init
        self._brief_tool = None        # Lazy init

        self._tool_definitions["WebFetch"] = ToolDefinition(
            name="WebFetch",
            description="Fetch a web page and extract its content",
            parameters=[
                ToolParam("url", ParamType.STRING, "URL to fetch"),
                ToolParam("extract_text", ParamType.BOOLEAN,
                          "Extract text content only (default: True)", required=False, default=True),
                ToolParam("timeout", ParamType.FLOAT,
                          "Request timeout in seconds", required=False, default=30),
            ],
            permission_level=PermissionLevel.READ_ONLY,
            execute=self._exec_web_fetch,
            is_open_world=True,
        )

        self._tool_definitions["WebSearch"] = ToolDefinition(
            name="WebSearch",
            description="Search the web and return results",
            parameters=[
                ToolParam("query", ParamType.STRING, "Search query"),
                ToolParam("num_results", ParamType.INTEGER,
                          "Number of results to return", required=False, default=5),
            ],
            permission_level=PermissionLevel.READ_ONLY,
            execute=self._exec_web_search,
            is_open_world=True,
        )

        self._tool_definitions["NotebookEdit"] = ToolDefinition(
            name="NotebookEdit",
            description="Read, edit, add, or delete Jupyter notebook cells",
            parameters=[
                ToolParam("path", ParamType.STRING, "Path to .ipynb notebook file"),
                ToolParam("action", ParamType.STRING, "Action to perform",
                          enum=["read", "edit", "add", "delete"]),
                ToolParam("cell_index", ParamType.INTEGER,
                          "Cell index (0-based)", required=False, default=None),
                ToolParam("cell_type", ParamType.STRING,
                          "Cell type for add/edit", required=False, default=None,
                          enum=["code", "markdown"]),
                ToolParam("source", ParamType.STRING,
                          "Cell source content", required=False, default=None),
            ],
            permission_level=PermissionLevel.WRITE,
            execute=self._exec_notebook_edit,
        )

        self._tool_definitions["TodoWrite"] = ToolDefinition(
            name="TodoWrite",
            description="Manage a personal todo list (add, complete, remove, list)",
            parameters=[
                ToolParam("action", ParamType.STRING, "Action to perform",
                          enum=["add", "complete", "remove", "list"]),
                ToolParam("text", ParamType.STRING,
                          "Todo item text (for add)", required=False, default=None),
                ToolParam("todo_id", ParamType.STRING,
                          "Todo item ID (for complete/remove)", required=False, default=None),
                ToolParam("priority", ParamType.STRING,
                          "Priority level", required=False, default=None,
                          enum=["high", "medium", "low"]),
            ],
            permission_level=PermissionLevel.READ_ONLY,
            execute=self._exec_todo_write,
        )

        self._tool_definitions["AskUser"] = ToolDefinition(
            name="AskUser",
            description="Ask the user a question and wait for their response",
            parameters=[
                ToolParam("question", ParamType.STRING, "Question to ask the user"),
                ToolParam("options", ParamType.STRING,
                          "Comma-separated options for the user to choose from",
                          required=False, default=None),
            ],
            permission_level=PermissionLevel.READ_ONLY,
            execute=self._exec_ask_user,
        )

        self._tool_definitions["Sleep"] = ToolDefinition(
            name="Sleep",
            description="Pause execution for a specified duration",
            parameters=[
                ToolParam("seconds", ParamType.FLOAT, "Number of seconds to sleep"),
                ToolParam("reason", ParamType.STRING,
                          "Reason for sleeping (logged)", required=False, default=None),
            ],
            permission_level=PermissionLevel.READ_ONLY,
            execute=self._exec_sleep,
        )

        self._tool_definitions["Brief"] = ToolDefinition(
            name="Brief",
            description="Toggle brief/verbose output mode",
            parameters=[
                ToolParam("enabled", ParamType.BOOLEAN,
                          "Enable brief mode (default: True)", required=False, default=True),
            ],
            permission_level=PermissionLevel.READ_ONLY,
            execute=self._exec_brief,
        )

        # ── Git Tools ──
        self._git_tools = None  # Lazy init

        self._tool_definitions["GitStatus"] = ToolDefinition(
            name="GitStatus",
            description="Show git working tree status",
            parameters=[],
            permission_level=PermissionLevel.READ_ONLY,
            execute=self._exec_git_status,
        )

        self._tool_definitions["GitDiff"] = ToolDefinition(
            name="GitDiff",
            description="Show git diff (staged and unstaged changes)",
            parameters=[],
            permission_level=PermissionLevel.READ_ONLY,
            execute=self._exec_git_diff,
        )

        self._tool_definitions["GitLog"] = ToolDefinition(
            name="GitLog",
            description="Show recent git commit log",
            parameters=[],
            permission_level=PermissionLevel.READ_ONLY,
            execute=self._exec_git_log,
        )

        self._tool_definitions["GitCommit"] = ToolDefinition(
            name="GitCommit",
            description="Stage and commit changes with a message",
            parameters=[],
            permission_level=PermissionLevel.WRITE,
            execute=self._exec_git_commit,
        )

        self._tool_definitions["GitBranch"] = ToolDefinition(
            name="GitBranch",
            description="List, create, or switch git branches",
            parameters=[],
            permission_level=PermissionLevel.WRITE,
            execute=self._exec_git_branch,
        )

        self._tool_definitions["GitPR"] = ToolDefinition(
            name="GitPR",
            description="Create or manage pull requests",
            parameters=[],
            permission_level=PermissionLevel.EXECUTE,
            execute=self._exec_git_pr,
        )

        # ── Plan Mode Tools ──
        self._plan_mode_manager = None  # Lazy init

        self._tool_definitions["EnterPlanMode"] = ToolDefinition(
            name="EnterPlanMode",
            description="Enter plan mode — disables write/execute tools for safe planning",
            parameters=[],
            permission_level=PermissionLevel.READ_ONLY,
            execute=self._exec_enter_plan_mode,
        )

        self._tool_definitions["ExitPlanMode"] = ToolDefinition(
            name="ExitPlanMode",
            description="Exit plan mode — re-enables all tools",
            parameters=[],
            permission_level=PermissionLevel.READ_ONLY,
            execute=self._exec_exit_plan_mode,
        )

        # ── Collaboration Tools ──
        self._send_message_tool = None   # Lazy init
        self._schedule_cron_tool = None  # Lazy init
        self._team_manager = None        # Lazy init

        self._tool_definitions["SendMessage"] = ToolDefinition(
            name="SendMessage",
            description="Send a message to another agent or user",
            parameters=[
                ToolParam("to", ParamType.STRING, "Recipient identifier"),
                ToolParam("content", ParamType.STRING, "Message content"),
            ],
            permission_level=PermissionLevel.READ_ONLY,
            execute=self._exec_send_message,
        )

        self._tool_definitions["ScheduleCron"] = ToolDefinition(
            name="ScheduleCron",
            description="Create, delete, or list scheduled cron jobs",
            parameters=[
                ToolParam("action", ParamType.STRING, "Action to perform",
                          enum=["create", "delete", "list"]),
                ToolParam("name", ParamType.STRING,
                          "Cron job name", required=False, default=None),
                ToolParam("cron_expr", ParamType.STRING,
                          "Cron expression (e.g. '*/5 * * * *')", required=False, default=None),
                ToolParam("command", ParamType.STRING,
                          "Command to execute on schedule", required=False, default=None),
            ],
            permission_level=PermissionLevel.EXECUTE,
            execute=self._exec_schedule_cron,
        )

        self._tool_definitions["TeamCreate"] = ToolDefinition(
            name="TeamCreate",
            description="Create a new team",
            parameters=[
                ToolParam("name", ParamType.STRING, "Team name"),
                ToolParam("description", ParamType.STRING,
                          "Team description", required=False, default=None),
            ],
            permission_level=PermissionLevel.READ_ONLY,
            execute=self._exec_team_create,
        )

        self._tool_definitions["TeamDelete"] = ToolDefinition(
            name="TeamDelete",
            description="Delete an existing team",
            parameters=[
                ToolParam("name", ParamType.STRING, "Team name to delete"),
            ],
            permission_level=PermissionLevel.READ_ONLY,
            execute=self._exec_team_delete,
        )

        # ── Advanced Tools ──
        self._worktree_tool = None       # Lazy init
        self._repl_tool = None           # Lazy init
        self._mcp_adapter = None         # Lazy init
        self._list_mcp_resources_tool = None  # Lazy init
        self._read_mcp_resource_tool = None   # Lazy init
        self._skill_tool = None          # Lazy init
        self._config_tool = None         # Lazy init
        self._tool_search_tool = None    # Lazy init
        self._task_output_tool = None    # Lazy init
        self._powershell_tool = None     # Lazy init
        self._cron_manager = None        # Lazy init

        self._tool_definitions["EnterWorktree"] = ToolDefinition(
            name="EnterWorktree",
            description="Create a temporary git worktree for isolated changes",
            parameters=[
                ToolParam("branch", ParamType.STRING,
                          "Branch to check out (auto-created if omitted)",
                          required=False, default=None),
            ],
            permission_level=PermissionLevel.EXECUTE,
            execute=self._exec_enter_worktree,
        )

        self._tool_definitions["ExitWorktree"] = ToolDefinition(
            name="ExitWorktree",
            description="Remove a git worktree and optionally clean up its directory",
            parameters=[
                ToolParam("name", ParamType.STRING,
                          "Worktree name to remove", required=False, default=None),
                ToolParam("cleanup", ParamType.BOOLEAN,
                          "Whether to force-remove the directory",
                          required=False, default=True),
            ],
            permission_level=PermissionLevel.EXECUTE,
            execute=self._exec_exit_worktree,
        )

        self._tool_definitions["REPL"] = ToolDefinition(
            name="REPL",
            description="Execute code in a one-shot subprocess (Python, Node, Ruby, or Bash)",
            parameters=[
                ToolParam("code", ParamType.STRING, "Code to execute"),
                ToolParam("language", ParamType.STRING,
                          "Language runtime to use", required=False, default="python",
                          enum=["python", "node", "ruby", "bash"]),
            ],
            permission_level=PermissionLevel.EXECUTE,
            execute=self._exec_repl,
        )

        self._tool_definitions["MCPCall"] = ToolDefinition(
            name="MCPCall",
            description="Call a tool on an MCP server",
            parameters=[
                ToolParam("server_name", ParamType.STRING, "MCP server name"),
                ToolParam("tool_name", ParamType.STRING, "Tool name on that server"),
                ToolParam("arguments", ParamType.STRING,
                          "JSON string of arguments", required=False, default=None),
            ],
            permission_level=PermissionLevel.EXECUTE,
            execute=self._exec_mcp_call,
        )

        self._tool_definitions["ListMcpResources"] = ToolDefinition(
            name="ListMcpResources",
            description="List resources exposed by MCP servers",
            parameters=[
                ToolParam("server_name", ParamType.STRING,
                          "Filter by server name", required=False, default=None),
            ],
            permission_level=PermissionLevel.READ_ONLY,
            execute=self._exec_list_mcp_resources,
        )

        self._tool_definitions["ReadMcpResource"] = ToolDefinition(
            name="ReadMcpResource",
            description="Read an MCP resource by its URI",
            parameters=[
                ToolParam("uri", ParamType.STRING, "MCP resource URI"),
            ],
            permission_level=PermissionLevel.READ_ONLY,
            execute=self._exec_read_mcp_resource,
        )

        self._tool_definitions["Skill"] = ToolDefinition(
            name="Skill",
            description="Invoke a registered skill (slash command) by name",
            parameters=[
                ToolParam("name", ParamType.STRING, "Skill name to invoke"),
                ToolParam("args", ParamType.STRING,
                          "Arguments to pass to the skill",
                          required=False, default=None),
            ],
            permission_level=PermissionLevel.READ_ONLY,
            execute=self._exec_skill,
        )

        self._tool_definitions["Config"] = ToolDefinition(
            name="Config",
            description="Get, set, or reset agent configuration values",
            parameters=[
                ToolParam("action", ParamType.STRING, "Action to perform",
                          enum=["get", "set", "reset"]),
                ToolParam("key", ParamType.STRING, "Config key",
                          required=False, default=None),
                ToolParam("value", ParamType.STRING, "Config value (for set)",
                          required=False, default=None),
            ],
            permission_level=PermissionLevel.WRITE,
            execute=self._exec_config,
        )

        self._tool_definitions["ToolSearch"] = ToolDefinition(
            name="ToolSearch",
            description="Search available tools by name or description",
            parameters=[
                ToolParam("query", ParamType.STRING, "Search query"),
            ],
            permission_level=PermissionLevel.READ_ONLY,
            execute=self._exec_tool_search,
        )

        self._tool_definitions["TaskOutput"] = ToolDefinition(
            name="TaskOutput",
            description="Read the output log of a running or completed task",
            parameters=[
                ToolParam("task_id", ParamType.STRING, "Task ID to read output from"),
                ToolParam("tail", ParamType.INTEGER,
                          "Number of trailing lines to return",
                          required=False, default=50),
            ],
            permission_level=PermissionLevel.READ_ONLY,
            execute=self._exec_task_output,
        )

        self._tool_definitions["PowerShell"] = ToolDefinition(
            name="PowerShell",
            description="Execute a PowerShell command (pwsh or powershell)",
            parameters=[
                ToolParam("command", ParamType.STRING, "PowerShell command to execute"),
                ToolParam("timeout", ParamType.INTEGER,
                          "Timeout in seconds", required=False, default=120),
            ],
            permission_level=PermissionLevel.EXECUTE,
            execute=self._exec_powershell,
        )

        self._tool_definitions["CronCreate"] = ToolDefinition(
            name="CronCreate",
            description="Create a new cron job",
            parameters=[
                ToolParam("name", ParamType.STRING, "Unique job name"),
                ToolParam("cron_expr", ParamType.STRING,
                          "Cron expression (e.g. '*/5 * * * *')"),
                ToolParam("command", ParamType.STRING, "Command to execute on schedule"),
                ToolParam("description", ParamType.STRING,
                          "Human-readable description", required=False, default=None),
            ],
            permission_level=PermissionLevel.EXECUTE,
            execute=self._exec_cron_create,
        )

        self._tool_definitions["CronDelete"] = ToolDefinition(
            name="CronDelete",
            description="Delete a cron job by name",
            parameters=[
                ToolParam("name", ParamType.STRING, "Cron job name to delete"),
            ],
            permission_level=PermissionLevel.EXECUTE,
            execute=self._exec_cron_delete,
        )

        self._tool_definitions["CronList"] = ToolDefinition(
            name="CronList",
            description="List all registered cron jobs",
            parameters=[],
            permission_level=PermissionLevel.READ_ONLY,
            execute=self._exec_cron_list,
        )

        # ── RemoteTrigger ──
        self._tool_definitions["RemoteTrigger"] = ToolDefinition(
            name="RemoteTrigger",
            description="Fire a webhook/API trigger by name",
            parameters=[
                ToolParam("name", ParamType.STRING, "Trigger name to fire"),
                ToolParam("payload", ParamType.STRING,
                          "JSON payload string", required=False, default=None),
            ],
            permission_level=PermissionLevel.EXECUTE,
            execute=self._exec_remote_trigger,
        )

        # ── SyntheticOutput ──
        self._tool_definitions["SyntheticOutput"] = ToolDefinition(
            name="SyntheticOutput",
            description="Produce structured JSON output matching a given schema. "
                        "Use when you need to return data in a specific format.",
            parameters=[
                ToolParam("schema_name", ParamType.STRING,
                          "Name/identifier for the output schema"),
                ToolParam("data", ParamType.STRING,
                          "JSON string of the structured data to output"),
            ],
            permission_level=PermissionLevel.READ_ONLY,
            execute=self._exec_synthetic_output,
        )

        # ── Snip ──
        self._tool_definitions["Snip"] = ToolDefinition(
            name="Snip",
            description="Extract and save a snippet from conversation history. "
                        "Useful for saving important context for later reference.",
            parameters=[
                ToolParam("label", ParamType.STRING,
                          "Short label for the snippet"),
                ToolParam("content", ParamType.STRING,
                          "The content to save as a snippet"),
                ToolParam("category", ParamType.STRING,
                          "Category: code, insight, reference, error",
                          required=False, default="reference"),
            ],
            permission_level=PermissionLevel.WRITE,
            execute=self._exec_snip,
        )

        # ── VerifyPlanExecution ──
        self._tool_definitions["VerifyPlanExecution"] = ToolDefinition(
            name="VerifyPlanExecution",
            description="Verify that a plan's steps have been properly executed "
                        "by checking expected outcomes.",
            parameters=[
                ToolParam("plan_summary", ParamType.STRING,
                          "Summary of the plan that was executed"),
                ToolParam("expected_outcomes", ParamType.STRING,
                          "JSON array of expected outcomes to verify"),
            ],
            permission_level=PermissionLevel.READ_ONLY,
            execute=self._exec_verify_plan,
        )

        # ── Workflow ──
        self._tool_definitions["Workflow"] = ToolDefinition(
            name="Workflow",
            description="Execute a workflow script from the project's workflow directory. "
                        "Workflows are shell scripts or Python scripts in .neomind/workflows/.",
            parameters=[
                ToolParam("name", ParamType.STRING,
                          "Workflow script name (without path)"),
                ToolParam("args", ParamType.STRING,
                          "Arguments to pass to the workflow",
                          required=False, default=""),
            ],
            permission_level=PermissionLevel.EXECUTE,
            execute=self._exec_workflow,
        )

        # ── Brief ──
        self._tool_definitions["Brief"] = ToolDefinition(
            name="Brief",
            description="Toggle brief output mode. In brief mode, responses are "
                        "concise summaries instead of full explanations.",
            parameters=[
                ToolParam("enabled", ParamType.BOOLEAN,
                          "True to enable brief mode, False to disable",
                          required=False, default=True),
            ],
            permission_level=PermissionLevel.READ_ONLY,
            execute=self._exec_brief,
        )

        # ── CtxInspect ──
        self._tool_definitions["CtxInspect"] = ToolDefinition(
            name="CtxInspect",
            description="Inspect the current context window usage. Shows token counts, "
                        "message counts, and capacity info.",
            parameters=[],
            permission_level=PermissionLevel.READ_ONLY,
            execute=self._exec_ctx_inspect,
        )

    # ── Tool execution wrappers (bridge schema → existing methods) ─────────

    def _get_task_manager(self):
        """Get or create the session TaskManager."""
        if self._task_manager is None:
            from agent.tools.task_tools import TaskManager
            self._task_manager = TaskManager()
        return self._task_manager

    def _exec_task_create(self, subject: str, description: str) -> ToolResult:
        result = self._get_task_manager().create(subject, description)
        if result.success:
            return ToolResult(True, output=result.message,
                              metadata={"task_id": result.task.id if result.task else None})
        return ToolResult(False, error=result.error or result.message)

    def _exec_task_get(self, task_id: str) -> ToolResult:
        result = self._get_task_manager().get(task_id)
        if result.success and result.task:
            t = result.task
            return ToolResult(True, output=f"[{t.id}] {t.status.value} — {t.subject}\n{t.description}")
        return ToolResult(False, error=result.error or result.message)

    def _exec_task_list(self, status: str = None) -> ToolResult:
        result = self._get_task_manager().list(status_filter=status)
        if result.success:
            if not result.tasks:
                return ToolResult(True, output="No tasks found.")
            lines = [f"[{t.id}] {t.status.value} — {t.subject}" for t in result.tasks]
            return ToolResult(True, output="\n".join(lines),
                              metadata={"count": len(result.tasks)})
        return ToolResult(False, error=result.error or result.message)

    def _exec_task_update(self, task_id: str, status: str = None,
                          subject: str = None, description: str = None) -> ToolResult:
        result = self._get_task_manager().update(task_id, status=status,
                                                  subject=subject, description=description)
        if result.success:
            return ToolResult(True, output=result.message)
        return ToolResult(False, error=result.error or result.message)

    def _exec_task_stop(self, task_id: str) -> ToolResult:
        result = self._get_task_manager().stop(task_id)
        if result.success:
            return ToolResult(True, output=result.message)
        return ToolResult(False, error=result.error or result.message)

    # ── Utility tool lazy getters & wrappers ────────────────────────────

    def _get_web_fetch_tool(self):
        if self._web_fetch_tool is None:
            from agent.tools.utility_tools import WebFetchTool
            self._web_fetch_tool = WebFetchTool()
        return self._web_fetch_tool

    def _get_web_search_tool(self):
        if self._web_search_tool is None:
            from agent.tools.utility_tools import WebSearchTool
            self._web_search_tool = WebSearchTool()
        return self._web_search_tool

    def _get_notebook_edit_tool(self):
        if self._notebook_edit_tool is None:
            from agent.tools.utility_tools import NotebookEditTool
            self._notebook_edit_tool = NotebookEditTool()
        return self._notebook_edit_tool

    def _get_todo_write_tool(self):
        if self._todo_write_tool is None:
            from agent.tools.utility_tools import TodoWriteTool
            self._todo_write_tool = TodoWriteTool()
        return self._todo_write_tool

    def _get_ask_user_tool(self):
        if self._ask_user_tool is None:
            from agent.tools.utility_tools import AskUserQuestionTool
            self._ask_user_tool = AskUserQuestionTool()
        return self._ask_user_tool

    def _get_sleep_tool(self):
        if self._sleep_tool is None:
            from agent.tools.utility_tools import SleepTool
            self._sleep_tool = SleepTool()
        return self._sleep_tool

    def _get_brief_tool(self):
        if self._brief_tool is None:
            from agent.tools.utility_tools import BriefTool
            self._brief_tool = BriefTool()
        return self._brief_tool

    def _exec_web_fetch(self, url: str, extract_text: bool = True,
                        timeout: float = 30) -> ToolResult:
        try:
            result = self._get_web_fetch_tool().execute(
                url=url, extract_text=extract_text, timeout=timeout)
            return ToolResult(True, output=result)
        except Exception as e:
            return ToolResult(False, error=f"WebFetch error: {e}")

    def _exec_web_search(self, query: str, num_results: int = 5) -> ToolResult:
        # Bug #2 fix: WebSearchTool exposes async ``search()``, not ``execute()``.
        # Drive it via asyncio and format the WebSearchResult into plain text.
        try:
            num_results = int(num_results) if num_results is not None else 5
        except (TypeError, ValueError):
            num_results = 5
        try:
            import asyncio as _asyncio
            tool = self._get_web_search_tool()

            async def _run():
                return await tool.search(query=query, num_results=num_results)

            try:
                # If we're already inside a running loop, run on a fresh loop
                # in a worker thread to avoid "loop already running" errors.
                _asyncio.get_running_loop()
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                    fut = ex.submit(lambda: _asyncio.new_event_loop().run_until_complete(_run()))
                    search_result = fut.result()
            except RuntimeError:
                # No running loop — safe to use asyncio.run
                search_result = _asyncio.run(_run())

            if not getattr(search_result, "success", False):
                return ToolResult(
                    False,
                    error=f"WebSearch error: {getattr(search_result, 'error', 'unknown error')}",
                )

            hits = getattr(search_result, "results", []) or []
            if not hits:
                return ToolResult(True, output=f"No results for: {query}")

            lines = [f"# WebSearch results for: {query}", ""]
            for i, hit in enumerate(hits, 1):
                title = getattr(hit, "title", "") or ""
                url = getattr(hit, "url", "") or ""
                snippet = getattr(hit, "snippet", "") or ""
                lines.append(f"{i}. {title}")
                if url:
                    lines.append(f"   {url}")
                if snippet:
                    lines.append(f"   {snippet}")
                lines.append("")
            return ToolResult(True, output="\n".join(lines).rstrip())
        except Exception as e:
            return ToolResult(False, error=f"WebSearch error: {e}")

    def _exec_notebook_edit(self, path: str, action: str,
                            cell_index: int = None, cell_type: str = None,
                            source: str = None) -> ToolResult:
        if self._plan_mode and action != "read":
            return ToolResult(False, error="Plan mode active — notebook edits are disabled.")
        try:
            result = self._get_notebook_edit_tool().execute(
                path=path, action=action, cell_index=cell_index,
                cell_type=cell_type, source=source)
            return ToolResult(True, output=result)
        except Exception as e:
            return ToolResult(False, error=f"NotebookEdit error: {e}")

    def _exec_todo_write(self, action: str, text: str = None,
                         todo_id: str = None, priority: str = None) -> ToolResult:
        try:
            result = self._get_todo_write_tool().execute(
                action=action, text=text, todo_id=todo_id, priority=priority)
            return ToolResult(True, output=result)
        except Exception as e:
            return ToolResult(False, error=f"TodoWrite error: {e}")

    def _exec_ask_user(self, question: str, options: str = None) -> ToolResult:
        try:
            result = self._get_ask_user_tool().execute(
                question=question, options=options)
            return ToolResult(True, output=result)
        except Exception as e:
            return ToolResult(False, error=f"AskUser error: {e}")

    def _exec_sleep(self, seconds: float, reason: str = None) -> ToolResult:
        try:
            result = self._get_sleep_tool().execute(seconds=seconds, reason=reason)
            return ToolResult(True, output=result,
                              metadata={"seconds": seconds, "reason": reason})
        except Exception as e:
            return ToolResult(False, error=f"Sleep error: {e}")

    def _exec_brief(self, enabled: bool = True) -> ToolResult:
        try:
            result = self._get_brief_tool().execute(enabled=enabled)
            return ToolResult(True, output=result)
        except Exception as e:
            return ToolResult(False, error=f"Brief error: {e}")

    # ── Git tool lazy getters & wrappers ──────────────────────────────

    def _get_git_tools(self):
        if self._git_tools is None:
            from agent.tools.git_tools import GitTools
            self._git_tools = GitTools(working_dir=self.working_dir)
        return self._git_tools

    def _exec_git_status(self) -> ToolResult:
        try:
            result = self._get_git_tools().status()
            return ToolResult(True, output=result)
        except Exception as e:
            return ToolResult(False, error=f"GitStatus error: {e}")

    def _exec_git_diff(self) -> ToolResult:
        try:
            result = self._get_git_tools().diff()
            return ToolResult(True, output=result)
        except Exception as e:
            return ToolResult(False, error=f"GitDiff error: {e}")

    def _exec_git_log(self) -> ToolResult:
        try:
            result = self._get_git_tools().log()
            return ToolResult(True, output=result)
        except Exception as e:
            return ToolResult(False, error=f"GitLog error: {e}")

    def _exec_git_commit(self) -> ToolResult:
        if self._plan_mode:
            return ToolResult(False, error="Plan mode active — git commits are disabled.")
        try:
            result = self._get_git_tools().commit()
            return ToolResult(True, output=result)
        except Exception as e:
            return ToolResult(False, error=f"GitCommit error: {e}")

    def _exec_git_branch(self) -> ToolResult:
        if self._plan_mode:
            return ToolResult(False, error="Plan mode active — branch operations are disabled.")
        try:
            result = self._get_git_tools().branch()
            return ToolResult(True, output=result)
        except Exception as e:
            return ToolResult(False, error=f"GitBranch error: {e}")

    def _exec_git_pr(self) -> ToolResult:
        if self._plan_mode:
            return ToolResult(False, error="Plan mode active — PR operations are disabled.")
        try:
            result = self._get_git_tools().pr()
            return ToolResult(True, output=result)
        except Exception as e:
            return ToolResult(False, error=f"GitPR error: {e}")

    # ── Plan mode tool wrappers ───────────────────────────────────────

    def _get_plan_mode_manager(self):
        if self._plan_mode_manager is None:
            from agent.tools.plan_mode import PlanModeManager
            self._plan_mode_manager = PlanModeManager(self)
        return self._plan_mode_manager

    def _exec_enter_plan_mode(self) -> ToolResult:
        try:
            self._get_plan_mode_manager().enter()
            self.enter_plan_mode()
            return ToolResult(True, output="Entered plan mode. Write/execute tools are now disabled.")
        except Exception as e:
            return ToolResult(False, error=f"EnterPlanMode error: {e}")

    def _exec_exit_plan_mode(self) -> ToolResult:
        try:
            self._get_plan_mode_manager().exit()
            self.exit_plan_mode()
            return ToolResult(True, output="Exited plan mode. All tools are now enabled.")
        except Exception as e:
            return ToolResult(False, error=f"ExitPlanMode error: {e}")

    # ── Collaboration tool lazy getters & wrappers ────────────────────

    def _get_send_message_tool(self):
        if self._send_message_tool is None:
            from agent.tools.collaboration_tools import SendMessageTool
            self._send_message_tool = SendMessageTool()
        return self._send_message_tool

    def _get_schedule_cron_tool(self):
        if self._schedule_cron_tool is None:
            from agent.tools.collaboration_tools import ScheduleCronTool
            self._schedule_cron_tool = ScheduleCronTool()
        return self._schedule_cron_tool

    def _get_team_manager(self):
        if self._team_manager is None:
            from agent.tools.collaboration_tools import TeamManager
            self._team_manager = TeamManager()
        return self._team_manager

    def _exec_send_message(self, to: str, content: str) -> ToolResult:
        try:
            result = self._get_send_message_tool().execute(to=to, content=content)
            return ToolResult(True, output=result)
        except Exception as e:
            return ToolResult(False, error=f"SendMessage error: {e}")

    def _exec_schedule_cron(self, action: str, name: str = None,
                            cron_expr: str = None, command: str = None) -> ToolResult:
        if self._plan_mode and action != "list":
            return ToolResult(False, error="Plan mode active — cron modifications are disabled.")
        try:
            result = self._get_schedule_cron_tool().execute(
                action=action, name=name, cron_expr=cron_expr, command=command)
            return ToolResult(True, output=result)
        except Exception as e:
            return ToolResult(False, error=f"ScheduleCron error: {e}")

    def _exec_team_create(self, name: str, description: str = None) -> ToolResult:
        try:
            result = self._get_team_manager().create(name=name, description=description)
            return ToolResult(True, output=result)
        except Exception as e:
            return ToolResult(False, error=f"TeamCreate error: {e}")

    def _exec_team_delete(self, name: str) -> ToolResult:
        try:
            result = self._get_team_manager().delete(name=name)
            return ToolResult(True, output=result)
        except Exception as e:
            return ToolResult(False, error=f"TeamDelete error: {e}")

    # ── Advanced tool lazy getters & wrappers ────────────────────────────

    def _get_worktree_tool(self):
        if self._worktree_tool is None:
            from agent.tools.advanced_tools import WorktreeTool
            self._worktree_tool = WorktreeTool(working_dir=self.working_dir)
        return self._worktree_tool

    def _get_repl_tool(self):
        if self._repl_tool is None:
            from agent.tools.advanced_tools import REPLTool
            self._repl_tool = REPLTool()
        return self._repl_tool

    def _get_mcp_adapter(self):
        if self._mcp_adapter is None:
            from agent.tools.advanced_tools import MCPToolAdapter
            self._mcp_adapter = MCPToolAdapter()
        return self._mcp_adapter

    def _get_list_mcp_resources_tool(self):
        if self._list_mcp_resources_tool is None:
            from agent.tools.advanced_tools import ListMcpResourcesTool
            self._list_mcp_resources_tool = ListMcpResourcesTool()
        return self._list_mcp_resources_tool

    def _get_read_mcp_resource_tool(self):
        if self._read_mcp_resource_tool is None:
            from agent.tools.advanced_tools import ReadMcpResourceTool
            self._read_mcp_resource_tool = ReadMcpResourceTool()
        return self._read_mcp_resource_tool

    def _get_skill_tool(self):
        if self._skill_tool is None:
            from agent.tools.advanced_tools import SkillTool
            self._skill_tool = SkillTool()
        return self._skill_tool

    def _get_config_tool(self):
        if self._config_tool is None:
            from agent.tools.advanced_tools import ConfigTool
            self._config_tool = ConfigTool()
        return self._config_tool

    def _get_tool_search_tool(self):
        if self._tool_search_tool is None:
            from agent.tools.advanced_tools import ToolSearchTool
            self._tool_search_tool = ToolSearchTool()
        return self._tool_search_tool

    def _get_task_output_tool(self):
        if self._task_output_tool is None:
            from agent.tools.advanced_tools import TaskOutputTool
            self._task_output_tool = TaskOutputTool()
        return self._task_output_tool

    def _get_powershell_tool(self):
        if self._powershell_tool is None:
            from agent.tools.advanced_tools import PowerShellTool
            self._powershell_tool = PowerShellTool()
        return self._powershell_tool

    def _get_cron_manager(self):
        if self._cron_manager is None:
            from agent.tools.advanced_tools import CronManager
            self._cron_manager = CronManager()
        return self._cron_manager

    def _exec_enter_worktree(self, branch: str = None) -> ToolResult:
        if self._plan_mode:
            return ToolResult(False, error="Plan mode active — worktree operations are disabled.")
        try:
            result = self._get_worktree_tool().enter(branch=branch)
            if result.success:
                return ToolResult(True, output=result.message,
                                  metadata={"path": result.path, "branch": result.branch})
            return ToolResult(False, error=result.error or result.message)
        except Exception as e:
            return ToolResult(False, error=f"EnterWorktree error: {e}")

    def _exec_exit_worktree(self, name: str = None, cleanup: bool = True) -> ToolResult:
        if self._plan_mode:
            return ToolResult(False, error="Plan mode active — worktree operations are disabled.")
        try:
            result = self._get_worktree_tool().exit(name=name, cleanup=cleanup)
            if result.success:
                return ToolResult(True, output=result.message)
            return ToolResult(False, error=result.error or result.message)
        except Exception as e:
            return ToolResult(False, error=f"ExitWorktree error: {e}")

    def _exec_repl(self, code: str, language: str = "python") -> ToolResult:
        if self._plan_mode:
            return ToolResult(False, error="Plan mode active — REPL execution is disabled.")
        try:
            result = self._get_repl_tool().execute(code=code, language=language)
            if result.success:
                output = result.stdout or result.message
                if result.stderr:
                    output += f"\n[stderr]\n{result.stderr}"
                return ToolResult(True, output=output,
                                  metadata={"language": result.language,
                                            "return_code": result.return_code})
            return ToolResult(False, error=result.error or result.message)
        except Exception as e:
            return ToolResult(False, error=f"REPL error: {e}")

    def _exec_mcp_call(self, server_name: str, tool_name: str,
                       arguments: str = None) -> ToolResult:
        if self._plan_mode:
            return ToolResult(False, error="Plan mode active — MCP tool calls are disabled.")
        try:
            import asyncio
            import json as _json
            parsed_args = _json.loads(arguments) if arguments else None
            adapter = self._get_mcp_adapter()
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run, adapter.call(server_name, tool_name, parsed_args)
                    ).result()
            else:
                result = asyncio.run(adapter.call(server_name, tool_name, parsed_args))
            if result.success:
                content = result.content
                if not isinstance(content, str):
                    content = _json.dumps(content, indent=2, default=str)
                return ToolResult(True, output=content)
            return ToolResult(False, error=result.error or result.message)
        except Exception as e:
            return ToolResult(False, error=f"MCPCall error: {e}")

    def _exec_list_mcp_resources(self, server_name: str = None) -> ToolResult:
        try:
            import asyncio
            import json as _json
            tool = self._get_list_mcp_resources_tool()
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run, tool.list_resources(server_name=server_name)
                    ).result()
            else:
                result = asyncio.run(tool.list_resources(server_name=server_name))
            if result.success:
                content = result.content
                if not isinstance(content, str):
                    content = _json.dumps(content, indent=2, default=str)
                return ToolResult(True, output=content)
            return ToolResult(False, error=result.error or result.message)
        except Exception as e:
            return ToolResult(False, error=f"ListMcpResources error: {e}")

    def _exec_read_mcp_resource(self, uri: str) -> ToolResult:
        try:
            import asyncio
            import json as _json
            tool = self._get_read_mcp_resource_tool()
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run, tool.read(uri=uri)
                    ).result()
            else:
                result = asyncio.run(tool.read(uri=uri))
            if result.success:
                content = result.content
                if not isinstance(content, str):
                    content = _json.dumps(content, indent=2, default=str)
                return ToolResult(True, output=content)
            return ToolResult(False, error=result.error or result.message)
        except Exception as e:
            return ToolResult(False, error=f"ReadMcpResource error: {e}")

    def _exec_skill(self, name: str, args: str = None) -> ToolResult:
        try:
            result = self._get_skill_tool().invoke(
                skill_name=name, args=args or "")
            if result.success:
                return ToolResult(True, output=result.message,
                                  metadata={"skill": result.skill_name})
            return ToolResult(False, error=result.error or result.message)
        except Exception as e:
            return ToolResult(False, error=f"Skill error: {e}")

    def _exec_config(self, action: str, key: str = None,
                     value: str = None) -> ToolResult:
        if self._plan_mode and action != "get":
            return ToolResult(False, error="Plan mode active — config modifications are disabled.")
        try:
            tool = self._get_config_tool()
            if action == "get":
                result = tool.get(key=key)
            elif action == "set":
                if not key:
                    return ToolResult(False, error="Config set requires a key.")
                result = tool.set(key=key, value=value)
            elif action == "reset":
                result = tool.reset(key=key)
            else:
                return ToolResult(False, error=f"Unknown config action: {action}")
            if result.success:
                import json as _json
                val = result.value
                if isinstance(val, dict):
                    val = _json.dumps(val, indent=2)
                return ToolResult(True, output=result.message + (f"\n{val}" if val else ""))
            return ToolResult(False, error=result.error or result.message)
        except Exception as e:
            return ToolResult(False, error=f"Config error: {e}")

    def _exec_tool_search(self, query: str) -> ToolResult:
        try:
            result = self._get_tool_search_tool().search(query=query)
            if result.success:
                return ToolResult(True, output=result.message,
                                  metadata={"matches": result.matches})
            return ToolResult(False, error=result.error or result.message)
        except Exception as e:
            return ToolResult(False, error=f"ToolSearch error: {e}")

    def _exec_task_output(self, task_id: str, tail: int = 50) -> ToolResult:
        try:
            result = self._get_task_output_tool().read_output(
                task_id=task_id, tail=tail)
            if result.success:
                return ToolResult(True, output=result.message,
                                  metadata={"task_id": result.task_id,
                                            "line_count": result.line_count})
            return ToolResult(False, error=result.error or result.message)
        except Exception as e:
            return ToolResult(False, error=f"TaskOutput error: {e}")

    def _exec_powershell(self, command: str, timeout: int = 120) -> ToolResult:
        if self._plan_mode:
            return ToolResult(False, error="Plan mode active — PowerShell execution is disabled.")
        try:
            result = self._get_powershell_tool().execute(
                command=command, timeout=timeout)
            if result.success:
                output = result.stdout or result.message
                if result.stderr:
                    output += f"\n[stderr]\n{result.stderr}"
                return ToolResult(True, output=output,
                                  metadata={"return_code": result.return_code})
            return ToolResult(False, error=result.error or result.message)
        except Exception as e:
            return ToolResult(False, error=f"PowerShell error: {e}")

    def _exec_cron_create(self, name: str, cron_expr: str,
                          command: str, description: str = None) -> ToolResult:
        if self._plan_mode:
            return ToolResult(False, error="Plan mode active — cron creation is disabled.")
        try:
            result = self._get_cron_manager().create(
                name=name, cron_expr=cron_expr, command=command,
                description=description or "")
            if result.success:
                return ToolResult(True, output=result.message)
            return ToolResult(False, error=result.error or result.message)
        except Exception as e:
            return ToolResult(False, error=f"CronCreate error: {e}")

    def _exec_cron_delete(self, name: str) -> ToolResult:
        if self._plan_mode:
            return ToolResult(False, error="Plan mode active — cron deletion is disabled.")
        try:
            result = self._get_cron_manager().delete(name=name)
            if result.success:
                return ToolResult(True, output=result.message)
            return ToolResult(False, error=result.error or result.message)
        except Exception as e:
            return ToolResult(False, error=f"CronDelete error: {e}")

    def _exec_cron_list(self) -> ToolResult:
        try:
            result = self._get_cron_manager().list_jobs()
            if result.success:
                return ToolResult(True, output=result.message,
                                  metadata={"jobs": result.jobs})
            return ToolResult(False, error=result.error or result.message)
        except Exception as e:
            return ToolResult(False, error=f"CronList error: {e}")

    def _exec_remote_trigger(self, name: str, payload: str = None) -> ToolResult:
        if self._plan_mode:
            return ToolResult(False, error="Plan mode active — remote triggers disabled.")
        try:
            from agent.tools.collaboration_tools import RemoteTriggerTool
            if not hasattr(self, '_remote_trigger_tool') or self._remote_trigger_tool is None:
                self._remote_trigger_tool = RemoteTriggerTool()
            import json
            payload_dict = json.loads(payload) if payload else None
            import asyncio
            result = asyncio.run(self._remote_trigger_tool.fire(name, payload_dict))
            if result.success:
                return ToolResult(True, output=result.message)
            return ToolResult(False, error=result.error or result.message)
        except Exception as e:
            return ToolResult(False, error=str(e))

    def _exec_synthetic_output(self, schema_name: str, data: str) -> ToolResult:
        """Produce structured JSON output matching a schema."""
        try:
            import json as _json
            parsed = _json.loads(data)
            formatted = _json.dumps(parsed, indent=2, ensure_ascii=False)
            return ToolResult(
                True,
                output=formatted,
                metadata={"schema_name": schema_name, "keys": list(parsed.keys()) if isinstance(parsed, dict) else "array"},
            )
        except _json.JSONDecodeError as e:
            return ToolResult(False, error=f"Invalid JSON data: {e}")
        except Exception as e:
            return ToolResult(False, error=str(e))

    def _exec_snip(self, label: str, content: str, category: str = "reference") -> ToolResult:
        """Save a snippet from conversation history."""
        import time as _time
        import json as _json

        snip_dir = os.path.join(self.working_dir, '.neomind_snips')
        os.makedirs(snip_dir, exist_ok=True)

        timestamp = _time.strftime("%Y%m%d_%H%M%S")
        safe_label = re.sub(r'[^a-zA-Z0-9_-]', '_', label)[:50]
        filename = f"{timestamp}_{safe_label}.md"
        filepath = os.path.join(snip_dir, filename)

        snip_content = f"---\nlabel: {label}\ncategory: {category}\ntimestamp: {timestamp}\n---\n\n{content}\n"

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(snip_content)
            return ToolResult(
                True,
                output=f"Snippet saved: {filename}",
                metadata={"file_path": filepath, "label": label, "category": category},
            )
        except Exception as e:
            return ToolResult(False, error=f"Failed to save snippet: {e}")

    def _exec_verify_plan(self, plan_summary: str, expected_outcomes: str) -> ToolResult:
        """Verify plan execution by checking expected outcomes."""
        import json as _json

        try:
            outcomes = _json.loads(expected_outcomes)
        except _json.JSONDecodeError:
            outcomes = [expected_outcomes]

        results = []
        all_pass = True

        for i, outcome in enumerate(outcomes):
            if isinstance(outcome, dict):
                check_type = outcome.get('type', 'file_exists')
                target = outcome.get('target', '')

                if check_type == 'file_exists':
                    try:
                        resolved = self._resolve_path(target)
                        exists = os.path.exists(resolved)
                        results.append(f"{'✓' if exists else '✗'} File exists: {target}")
                        if not exists:
                            all_pass = False
                    except Exception:
                        results.append(f"✗ Cannot resolve path: {target}")
                        all_pass = False

                elif check_type == 'file_contains':
                    pattern = outcome.get('pattern', '')
                    try:
                        resolved = self._resolve_path(target)
                        with open(resolved, 'r') as f:
                            content = f.read()
                        found = pattern in content
                        results.append(f"{'✓' if found else '✗'} File contains '{pattern}': {target}")
                        if not found:
                            all_pass = False
                    except Exception as e:
                        results.append(f"✗ Check failed: {e}")
                        all_pass = False

                else:
                    results.append(f"? Unknown check type: {check_type}")
            else:
                results.append(f"? Unstructured outcome: {outcome}")

        summary = f"Plan: {plan_summary}\n\nVerification Results:\n" + "\n".join(results)
        summary += f"\n\nOverall: {'ALL PASSED' if all_pass else 'SOME FAILED'}"

        return ToolResult(all_pass, output=summary)

    def _exec_workflow(self, name: str, args: str = "") -> ToolResult:
        """Execute a workflow script from .neomind/workflows/."""
        if self._plan_mode:
            return ToolResult(False, error="Plan mode active — workflow execution disabled.")
        workflow_dir = os.path.join(self.working_dir, '.neomind', 'workflows')
        if not os.path.exists(workflow_dir):
            return ToolResult(False, error=f"No workflows directory: {workflow_dir}")

        safe_name = re.sub(r'[^a-zA-Z0-9_.-]', '', name)
        candidates = [
            os.path.join(workflow_dir, safe_name),
            os.path.join(workflow_dir, safe_name + '.sh'),
            os.path.join(workflow_dir, safe_name + '.py'),
        ]
        script = None
        for c in candidates:
            if os.path.isfile(c):
                script = c
                break
        if not script:
            available = [f for f in os.listdir(workflow_dir) if not f.startswith('.')]
            return ToolResult(False, error=f"Workflow '{name}' not found. Available: {', '.join(available) or 'none'}")

        import subprocess as _sp
        try:
            if script.endswith('.py'):
                cmd = ['python3', script] + (args.split() if args else [])
            else:
                cmd = ['bash', script] + (args.split() if args else [])
            result = _sp.run(cmd, capture_output=True, text=True, timeout=120, cwd=self.working_dir)
            output = result.stdout + (('\n' + result.stderr) if result.stderr else '')
            return ToolResult(result.returncode == 0, output=output.strip(),
                              error=result.stderr.strip() if result.returncode != 0 else '',
                              metadata={'script': script, 'exit_code': result.returncode})
        except _sp.TimeoutExpired:
            return ToolResult(False, error=f"Workflow '{name}' timed out after 120s")
        except Exception as e:
            return ToolResult(False, error=str(e))

    def _exec_brief(self, enabled: bool = True) -> ToolResult:
        """Toggle brief output mode."""
        if not hasattr(self, '_brief_mode'):
            self._brief_mode = False
        self._brief_mode = enabled
        return ToolResult(True, output=f"Brief mode {'enabled' if enabled else 'disabled'}.",
                          metadata={'brief_mode': enabled})

    def _exec_ctx_inspect(self) -> ToolResult:
        """Inspect context window usage."""
        import sys
        history = getattr(self, '_conversation_history', None)
        if history is None:
            # Try to estimate from instance state
            tools_count = len(self._tool_definitions)
            files_read = len(getattr(self, '_files_read', set()))
            return ToolResult(True, output=(
                f"Context Inspection:\n"
                f"  Registered tools: {tools_count}\n"
                f"  Files read this session: {files_read}\n"
                f"  Plan mode: {self._plan_mode}\n"
                f"  Brief mode: {getattr(self, '_brief_mode', False)}\n"
                f"  Working directory: {self.working_dir}\n"
            ))
        msg_count = len(history)
        user_msgs = sum(1 for m in history if m.get('role') == 'user')
        asst_msgs = sum(1 for m in history if m.get('role') == 'assistant')
        total_chars = sum(len(str(m.get('content', ''))) for m in history)
        est_tokens = total_chars // 4  # rough estimate
        return ToolResult(True, output=(
            f"Context Window Inspection:\n"
            f"  Total messages: {msg_count}\n"
            f"  User messages: {user_msgs}\n"
            f"  Assistant messages: {asst_msgs}\n"
            f"  Estimated tokens: ~{est_tokens:,}\n"
            f"  Total characters: {total_chars:,}\n"
        ))

    def _exec_bash(self, command: str, timeout: int = 120) -> ToolResult:
        """Execute via persistent bash session."""
        if self._plan_mode:
            return ToolResult(False, error="Plan mode active — command execution is disabled. Exit plan mode first.")
        import time
        start = time.time()
        result = self.bash(command, timeout=timeout)
        elapsed_ms = int((time.time() - start) * 1000)
        result.metadata["duration_ms"] = elapsed_ms
        result.metadata["command"] = command
        return result

    def _exec_read(self, path: str, offset: int = 0, limit: int = 0) -> ToolResult:
        """Execute file read with metadata, staleness tracking, and deduplication."""
        # Bug #1 fix: LLMs sometimes pass offset/limit as strings ("0") instead
        # of ints. Coerce defensively so the tool does not crash.
        try:
            offset = int(offset) if offset is not None else 0
        except (TypeError, ValueError):
            offset = 0
        try:
            limit = int(limit) if limit is not None else 0
        except (TypeError, ValueError):
            limit = 0

        resolved = self._resolve_path(path)

        # Deduplication: if exact same range was already read, return abbreviated
        range_key = (offset, limit)
        if resolved in self._files_read_ranges:
            if range_key in self._files_read_ranges[resolved]:
                return ToolResult(
                    True,
                    output=f"[File already read in this session: {path} (offset={offset}, limit={limit}). Content unchanged.]",
                    metadata={"file_path": resolved, "deduplicated": True},
                )

        result = self.read_file(path, offset=offset, limit=limit)
        result.metadata["file_path"] = resolved
        if result.success:
            self._files_read.add(resolved)
            # Track mtime for staleness detection
            try:
                self._files_mtime[resolved] = os.path.getmtime(resolved)
            except OSError:
                pass
            # Track read ranges for deduplication
            self._files_read_ranges.setdefault(resolved, []).append(range_key)
            # Count lines in output
            lines = result.output.split("\n")
            result.metadata["lines_in_output"] = len(lines) - 1  # subtract header
        return result

    def _exec_write(self, path: str, content: str) -> ToolResult:
        """Execute file write with metadata."""
        if self._plan_mode:
            return ToolResult(False, error="Plan mode active — file writes are disabled. Exit plan mode first.")
        result = self.write_file(path, content)
        resolved = self._resolve_path(path)
        result.metadata["file_path"] = resolved
        if result.success:
            # Bug #4 fix: phantom Write — write_file reported success but
            # nothing landed on disk. Verify the file actually exists and
            # has the expected size before reporting success to the LLM.
            try:
                expected_bytes = len(content.encode("utf-8"))
            except Exception:
                expected_bytes = len(content)
            try:
                if not os.path.exists(resolved):
                    return ToolResult(
                        False,
                        error=(
                            f"Write verification failed: file does not exist "
                            f"after write: {resolved}"
                        ),
                        metadata={"file_path": resolved},
                    )
                actual_bytes = os.path.getsize(resolved)
                if actual_bytes != expected_bytes:
                    return ToolResult(
                        False,
                        error=(
                            f"Write verification failed: expected {expected_bytes} "
                            f"bytes on disk, found {actual_bytes} bytes at {resolved}"
                        ),
                        metadata={
                            "file_path": resolved,
                            "expected_bytes": expected_bytes,
                            "actual_bytes": actual_bytes,
                        },
                    )
            except OSError as e:
                return ToolResult(
                    False,
                    error=f"Write verification failed: {e}",
                    metadata={"file_path": resolved},
                )
            result.metadata["bytes_written"] = len(content)
            result.metadata["lines_written"] = content.count("\n") + (
                1 if content and not content.endswith("\n") else 0
            )
            result.metadata["verified_bytes"] = expected_bytes
        return result

    def _exec_edit(self, path: str, old_string: str, new_string: str,
                   replace_all: bool = False) -> ToolResult:
        """Execute file edit with metadata and staleness detection."""
        if self._plan_mode:
            return ToolResult(False, error="Plan mode active — file edits are disabled. Exit plan mode first.")
        resolved = self._resolve_path(path, operation='write')
        if resolved not in self._files_read:
            return ToolResult(False, error=f"Must Read '{path}' before editing. Use the Read tool first to see current content.")

        # Staleness detection: check if file was modified since we last read it
        if resolved in self._files_mtime:
            try:
                current_mtime = os.path.getmtime(resolved)
                if current_mtime > self._files_mtime[resolved]:
                    return ToolResult(
                        False,
                        error=f"File '{path}' was modified since last read (stale). "
                              f"Read it again to get the current content before editing."
                    )
            except OSError:
                pass

        result = self.edit_file(path, old_string, new_string, replace_all=replace_all)
        result.metadata["file_path"] = resolved

        # Update mtime after successful edit
        if result.success:
            try:
                self._files_mtime[resolved] = os.path.getmtime(resolved)
                # Invalidate read dedup cache for this file
                self._files_read_ranges.pop(resolved, None)
            except OSError:
                pass

        return result

    def _exec_glob(self, pattern: str, path: Optional[str] = None) -> ToolResult:
        """Execute glob search with metadata."""
        result = self.glob_files(pattern, path=path)
        if result.success and not result.output.startswith("No files"):
            # Extract count from header: "# N files matching ..."
            try:
                count = int(result.output.split("\n")[0].split()[1])
                result.metadata["files_matched"] = count
            except (IndexError, ValueError):
                pass
        result.metadata["pattern"] = pattern
        return result

    def _exec_grep(self, pattern: str, path: Optional[str] = None,
                   file_type: Optional[str] = None, context: int = 0,
                   case_insensitive: bool = False,
                   output_mode: str = "content") -> ToolResult:
        """Execute grep search with metadata and large result persistence."""
        result = self.grep_files(
            pattern, path=path, file_type=file_type, context=context,
            case_insensitive=case_insensitive, output_mode=output_mode,
        )
        result.metadata["pattern"] = pattern
        return self._persist_large_result('Grep', result)

    def _exec_self_editor(self, file_path: str, new_content: str,
                          reason: str) -> ToolResult:
        """Execute a self-edit through the safety pipeline."""
        if self._plan_mode:
            return ToolResult(False, error="Plan mode active — self-editing is disabled. Exit plan mode first.")
        try:
            from agent.evolution.self_edit import SelfEditor
            editor = SelfEditor()
            success, message = editor.propose_edit(file_path, reason, new_content)
            if success:
                return ToolResult(True, output=message)
            else:
                return ToolResult(False, error=message)
        except Exception as e:
            return ToolResult(False, error=f"SelfEditor error: {e}")

    def _exec_ls(self, path: Optional[str] = None) -> ToolResult:
        """Execute directory listing with metadata."""
        result = self.list_dir(path=path)
        if result.success:
            # Extract count from header: "# /path (N entries)"
            try:
                header = result.output.split("\n")[0]
                count = int(header.split("(")[1].split()[0])
                result.metadata["entry_count"] = count
            except (IndexError, ValueError):
                pass
        return result

    # ── Tool registry access ───────────────────────────────────────────────

    # Common aliases LLMs use for tool names
    _TOOL_ALIASES = {
        "search": "WebSearch",
        "web_search": "WebSearch",
        "websearch": "WebSearch",
        "internet_search": "WebSearch",
        "google": "WebSearch",
        "browse": "WebSearch",
        "shell": "Bash",
        "terminal": "Bash",
        "exec": "Bash",
        "readfile": "Read",
        "read_file": "Read",
        "writefile": "Write",
        "write_file": "Write",
        "editfile": "Edit",
        "edit_file": "Edit",
        "find": "Glob",
        "list": "LS",
        "ls": "LS",
    }

    # ── Deny-rule filtering ─────────────────────────────────────────

    def set_deny_rules(self, rules: List[str]):
        """Set deny rules that filter tools from the prompt before the LLM sees them.

        Deny rules are a security boundary — matching tools are invisible to the LLM.
        Format per rule: "ToolName" or "ToolName(pattern)".
        Examples: "Bash(git push:*)", "Write(*.env)", "SelfEditor".
        """
        self._deny_rules = list(rules)

    def _tool_matches_deny_rule(self, tool_name: str, rule: str) -> bool:
        """Check if a tool name matches a deny rule pattern."""
        # Simple tool-level deny: "Bash", "SelfEditor"
        if '(' not in rule:
            return tool_name.lower() == rule.lower()
        # Command/file-pattern deny: "Bash(git:*)", "Write(*.env)"
        tool_part, rest = rule.split('(', 1)
        if tool_part.lower() != tool_name.lower():
            return False
        pattern = rest.rstrip(')')
        # The pattern is informational at visibility level — if the tool
        # is denied with any pattern, the whole tool is hidden from the prompt.
        # Per-command enforcement happens at execution time via is_destructive().
        return True

    def _apply_deny_rules(self, tools: List[Any]) -> List[Any]:
        """Filter out tools that match any deny rule.

        Called before assembling the system prompt so the LLM never sees
        denied tools in its available tool list.
        """
        if not self._deny_rules:
            return tools
        filtered = []
        for tool_def in tools:
            denied = False
            for rule in self._deny_rules:
                if self._tool_matches_deny_rule(tool_def.name, rule):
                    denied = True
                    break
            if not denied:
                filtered.append(tool_def)
        return filtered

    # ── Deferred tool loading ───────────────────────────────────────

    def set_deferred_tool_threshold(self, threshold: int):
        """Set the tool count threshold for deferred tool loading.

        When get_all_tools() returns more than `threshold` tools, non-always_load
        tools are deferred (removed from the prompt). A ToolSearch mechanism allows
        the LLM to discover them at runtime.
        """
        self._deferred_tool_threshold = threshold

    def _apply_deferred_loading(self, tools: List[Any]) -> List[Any]:
        """Defer non-essential tools when the tool pool exceeds the threshold.

        Tools with always_load=True are always included. Tools with
        requires_user_interaction() are always deferred (shown on demand).
        """
        if not self._deferred_tools_enabled:
            return tools
        essential = [t for t in tools if getattr(t, 'always_load', True)]
        if len(tools) <= self._deferred_tool_threshold:
            return tools
        # Keep essential + add a notice about deferred tools
        deferred_count = len(tools) - len(essential)
        if deferred_count > 0:
            # Add a marker so the prompt mentions deferred tools are available
            pass  # ToolSearch tool would be injected here
        return essential

    # ── Tool getters ────────────────────────────────────────────────

    def get_tool(self, name: str) -> Optional[Any]:
        """Get a tool definition by name (case-insensitive + alias lookup)."""
        # Exact match first
        if name in self._tool_definitions:
            return self._tool_definitions[name]
        # Case-insensitive fallback
        name_lower = name.lower()
        for key, tool_def in self._tool_definitions.items():
            if key.lower() == name_lower:
                return tool_def
        # Alias fallback — LLMs often use short/variant names
        canonical = self._TOOL_ALIASES.get(name_lower)
        if canonical and canonical in self._tool_definitions:
            return self._tool_definitions[canonical]
        return None

    def set_denial_tracker(self, tracker):
        """Attach a DenialTracker for circuit-breaker integration.

        When set, get_all_tools() automatically filters out tools whose
        circuit is broken (consecutive denials exceeded threshold).
        """
        self._denial_tracker = tracker

    def get_all_tools(self, mode: Optional[str] = None,
                      apply_deny_rules: bool = True,
                      apply_deferred: bool = True) -> List[Any]:
        """Get all registered tool definitions in display order.

        If `mode` is provided, tools are filtered by their `allowed_modes`
        attribute: only tools whose allowed_modes is None (shared) or
        contains `mode` are returned. This is the mode-gating mechanism
        that lets fin-mode LLMs see `finance_*` tools, coding-mode LLMs
        see `code_*` tools, etc., without cross-mode leakage.

        When `mode` is None, all tools are returned (legacy behaviour).

        Deny rules (apply_deny_rules) filter tools BEFORE the LLM sees them.
        Deferred loading (apply_deferred) reduces the prompt tool list when
        the tool pool exceeds the threshold.
        Denial tracker filters circuit-broken tools (Phase 2).
        """
        # Display order: Bash, Read, Write, Edit, Glob, Grep, LS
        order = ["Bash", "Read", "Write", "Edit", "Glob", "Grep", "LS"]
        result = []
        for name in order:
            if name in self._tool_definitions:
                tool_def = self._tool_definitions[name]
                if tool_def.is_available_in_mode(mode):
                    result.append(tool_def)
        # Append any tools not in the default order
        for name, tool_def in self._tool_definitions.items():
            if name not in order and tool_def.is_available_in_mode(mode):
                result.append(tool_def)

        # Phase 2: deny-rule filtering (before LLM sees the list)
        if apply_deny_rules:
            result = self._apply_deny_rules(result)

        # Phase 2: denial tracker circuit-breaker filtering
        tracker = getattr(self, '_denial_tracker', None)
        if tracker is not None:
            broken = set(t.lower() for t in tracker.get_broken_tools())
            if broken:
                result = [t for t in result if t.name.lower() not in broken]

        # Phase 2: deferred tool loading (large tool pools)
        if apply_deferred and self._deferred_tools_enabled:
            result = self._apply_deferred_loading(result)

        return result

    def enter_plan_mode(self):
        """Enter plan mode — disable write/execute/destructive tools."""
        self._plan_mode = True

    def exit_plan_mode(self):
        """Exit plan mode — re-enable all tools."""
        self._plan_mode = False

    @property
    def is_plan_mode(self) -> bool:
        return self._plan_mode

    def _resolve_path(self, path: str, operation: str = 'read') -> str:
        """Resolve a path relative to working directory.

        Security: ensures resolved path stays within the workspace and
        passes all path traversal prevention checks.
        """
        # Expand ~ to actual home directory FIRST (before any checks)
        if path.startswith('~'):
            path = os.path.expanduser(path)

        # Run full safety check (includes protected files, path traversal, etc.)
        try:
            from agent.services.safety_service import SafetyManager
            sm = SafetyManager(workspace_root=self.working_dir)
            # Check is_path_safe (covers protected files, system dirs, etc.)
            ok, reason = sm.is_path_safe(path, operation)
            if not ok:
                raise ValueError(f"Path security check failed: {reason}")
            # Also check path traversal specifically
            ok, reason = sm.validate_path_traversal(path, operation)
            if not ok:
                raise ValueError(f"Path security check failed: {reason}")
        except ImportError:
            pass

        p = pathlib.Path(path)
        if not p.is_absolute():
            p = pathlib.Path(self.working_dir) / p
        resolved = str(p.resolve())
        workspace_abs = str(pathlib.Path(self.working_dir).resolve())
        # Allow workspace paths, /tmp/, and macOS temp dirs (/var/folders/)
        # macOS: /tmp is a symlink to /private/tmp, so include both
        _SAFE_EXTERNAL_PREFIXES = ("/tmp/", "/private/tmp/", "/var/folders/")
        if not resolved.startswith(workspace_abs) and not any(
            resolved.startswith(prefix) for prefix in _SAFE_EXTERNAL_PREFIXES
        ):
            raise ValueError(f"Path '{path}' resolves outside workspace")
        return resolved

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
        # Guard: reject raw Python source mistakenly passed as a shell command.
        # Reasoner models sometimes feed their own markdown code blocks to Bash.
        _py_reject_msg = (
            "ERROR: This looks like raw Python source, not a shell command.\n"
            "Use `python3 -c '<code>'` to run Python inline, OR write code to a "
            "file first then `python3 file.py`.\n"
            "Do NOT pass raw Python source as Bash commands."
        )
        _stripped = command.lstrip()
        if (
            _stripped.startswith(("def ", "class ", "from ", "return ", "@"))
            or re.match(r"^import\s+[A-Za-z_][\w\.]*\s*$", _stripped)
            or "```" in command
            or re.search(r"\bdef\s+\w+\s*\([^)]*\)\s*:?\s*def\s+\w+", command)
            or re.search(r"\breturn\s+\w+def\s+\w+", command)
            or re.search(r"^@\w+def\s+\w+", _stripped)
            or re.search(r"^import\s+\w+\w+\.\w+", _stripped)
        ):
            return ToolResult(False, error=_py_reject_msg)
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
        """Read a file with line numbers.

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

        Targeted string replacement in files.

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
                # DR05 fix: use lstat() so broken symlinks don't raise FileNotFoundError.
                # Also guard with try/except for any other stat() failure (permissions, etc.)
                try:
                    is_symlink = entry.is_symlink()
                    st = entry.lstat()
                    import stat as _stat_mod
                    is_dir = _stat_mod.S_ISDIR(st.st_mode)
                except OSError:
                    lines.append(f"  {entry.name:<40} {'<stat err>':>8}")
                    continue

                if is_symlink:
                    # Distinguish broken vs valid symlinks without crashing
                    try:
                        target_exists = entry.exists()
                    except OSError:
                        target_exists = False
                    if not target_exists:
                        lines.append(f"  {entry.name:<40} {'<broken link>':>8}")
                    else:
                        try:
                            target = os.readlink(str(entry))
                        except OSError:
                            target = "?"
                        lines.append(f"  {entry.name} -> {target}")
                    continue

                if is_dir:
                    lines.append(f"  {entry.name}/")
                else:
                    size = st.st_size
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
