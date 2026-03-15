# Plan: Split ikol1729 Agent into Chat + Coding Modes

## Overview

Split the agent into two cleanly separated modes with independent configs, commands, and behaviors. The **coding mode** should mirror Claude CLI as closely as possible.

---

## Phase 1: Config Separation

### Current (single file)
```
agent/config.yaml  ← everything mixed
```

### Target (three files)
```
agent/config/
  base.yaml        ← shared: API key, model, temperature, stream, timeout, retries
  chat.yaml        ← chat-only: system prompt, auto-search triggers, safety=strict
  coding.yaml      ← coding-only: system prompt, workspace, permissions, tools, status bar
```

### What goes where

**base.yaml** (shared)
```yaml
model: deepseek-chat
temperature: 0.7
max_tokens: 8192
stream: true
timeout: 30
max_retries: 3
thinking_enabled: true
debug: false
context:
  max_context_tokens: 131072
  warning_threshold: 0.61
  break_threshold: 0.8
  compression_strategy: truncate
  keep_system_messages: true
  keep_recent_messages: 5
```

**chat.yaml**
```yaml
system_prompt: |
  You are a helpful AI assistant. You can help with general conversation,
  answer questions, search the web, and provide information.
  Be helpful, concise, and accurate.
search_enabled: true
auto_search:
  enabled: true
  triggers: [today, news, weather, latest, current, ...]
natural_language:
  enabled: false
  confidence_threshold: 0.8
safety:
  confirm_file_operations: true
  confirm_code_changes: true
show_status_bar: true
enable_auto_complete: true
```

**coding.yaml** (Claude CLI-like)
```yaml
system_prompt: |
  You are an expert software engineer working as a CLI coding assistant.
  You have access to tools: Bash, Read, Write, Edit, Glob, Grep, LS.

  RULES:
  - Always read a file before editing it
  - Use Glob/Grep instead of bash find/grep
  - Prefer editing existing files over writing new ones
  - Ask before destructive operations (rm, git reset --hard)
  - Show diffs for file changes
  - Be concise — focus on code, not explanations
  - When a task requires multiple steps, use a todo list

  TOOL BEHAVIORS:
  - Bash: execute shell commands, persistent working directory
  - Read: read files with line numbers (supports images, PDFs, notebooks)
  - Write: create new files or full rewrites
  - Edit: targeted string replacement in existing files
  - Glob: fast file pattern matching (e.g. "**/*.py")
  - Grep: regex content search across files
  - LS: list directory contents

workspace:
  auto_scan: true
  auto_read_files: true
  auto_analyze_references: true
  exclude_patterns: [.git, __pycache__, node_modules, .venv, "*.pyc"]
permissions:
  auto_approve_reads: true
  confirm_writes: false       # like Claude CLI auto-accept mode
  confirm_deletes: true       # always ask for destructive ops
  confirm_bash: false         # auto-approve bash commands
natural_language:
  enabled: true
  confidence_threshold: 0.7
safety:
  confirm_file_operations: false
  confirm_code_changes: false
show_status_bar: true
enable_auto_complete: true
enable_mcp_support: true
compact:
  enabled: true               # auto-compact at context limit
  preserve_instructions: true  # keep system prompt on compact
```

### Files to modify
- `agent_config.py` — load base + mode-specific yaml, merge at runtime
- `agent/config.yaml` → delete, replaced by `agent/config/` directory
- `agent/core.py` — `switch_mode()` reloads mode-specific config

---

## Phase 2: Command Separation

### Chat mode commands (conversation-focused)
```
/help         Show available commands
/clear        Clear conversation history
/search       Web search
/browse       Read a webpage
/think        Toggle thinking mode
/debug        Toggle verbose output
/models       List/switch models
/history      Show conversation history
/save         Save conversation
/load         Load conversation
/compact      Compact conversation (summarize to save context)
/quit         Exit
```

### Coding mode commands (Claude CLI-like)
```
# Session
/help         Show commands
/clear        Clear conversation
/compact      Compact conversation with optional preserve instructions
/think        Toggle thinking mode
/debug        Toggle verbose output
/quit         Exit

# File Operations (Claude CLI tools)
/read <path>          Read file with line numbers
/write <path>         Create/overwrite file
/edit <path>          Edit specific sections of a file
/ls [path]            List directory contents
/glob <pattern>       Find files by pattern (e.g. "**/*.py")
/grep <pattern>       Search file contents with regex

# Code Operations
/code <subcommand>    Code analysis (analyze, explain, refactor)
/fix [path]           Auto-fix code issues
/test [path]          Run tests
/run <command>        Execute shell command (bash)
/git <subcommand>     Git operations
/diff [path]          Show file diffs

# Workspace
/mode status          Show current mode info
/context              Show context window usage
/todo                 Manage task list (like Claude CLI TodoWrite)

# Model
/models               List/switch models
/save                 Save conversation
/load                 Load conversation
```

### Files to modify
- `cli/claude_interface.py` — `SlashCommandCompleter` loads different command lists per mode
- `agent/core.py` — `_setup_command_handlers()` registers mode-specific handlers
- Add `_handle_local_command()` mode branching in claude_interface.py

---

## Phase 3: Coding Mode — Claude CLI Feature Parity

### 3.1 Permission Model (like Claude CLI)

Three modes within coding mode:
1. **Normal** — ask before writes/deletes
2. **Auto-accept** — auto-approve reads + writes (toggle with `/permissions auto`)
3. **Plan mode** — read-only, no modifications (`/permissions plan`)

```python
class PermissionMode(Enum):
    NORMAL = "normal"
    AUTO_ACCEPT = "auto_accept"
    PLAN = "plan"  # read-only
```

### 3.2 Tool System (like Claude CLI built-in tools)

Map Claude CLI tools to agent capabilities:

| Claude CLI Tool | ikol1729 Implementation |
|-----------------|------------------------|
| Bash            | `/run` command → subprocess |
| Read            | `/read` → file read with line numbers |
| Write           | `/write` → create/overwrite files |
| Edit            | `/edit` → targeted string replacement |
| Glob            | `/glob` → pathlib glob matching |
| Grep            | `/grep` → regex search (already exists) |
| LS              | `/ls` → os.listdir with formatting |
| TodoWrite       | `/todo` → task tracking |
| WebSearch       | `/search` → DuckDuckGo (already exists) |
| WebFetch        | `/browse` → webpage reading (already exists) |

New file: `agent/tools.py`
```python
class ToolRegistry:
    """Claude CLI-like tool system"""

    def read_file(path, offset=None, limit=None) -> str:
        """Read with line numbers, like Claude CLI Read tool"""

    def write_file(path, content) -> bool:
        """Create/overwrite file, like Claude CLI Write tool"""

    def edit_file(path, old_string, new_string) -> bool:
        """String replacement edit, like Claude CLI Edit tool"""

    def glob_files(pattern, path=None) -> list:
        """Fast file pattern matching"""

    def grep_files(pattern, path=None, type=None) -> list:
        """Regex content search"""

    def bash(command, timeout=120) -> str:
        """Execute shell command"""

    def list_dir(path=None) -> str:
        """List directory with metadata"""
```

### 3.3 Auto-Compact (like Claude CLI)

When context hits ~95%, automatically compact:
- Preserve system prompt
- Summarize old tool outputs (file reads, grep results, bash outputs)
- Keep recent conversation turns
- Condense into structured summary

```python
# In coding mode config
compact:
  auto_trigger_threshold: 0.95  # of max_context_tokens
  preserve_system_prompt: true
  keep_recent_turns: 5
  summarize_tool_outputs: true
```

### 3.4 Status Bar Enhancement

Current: `deepseek-chat | chat | think:on | 1% 1,500/128k 3msg`

Coding mode target (Claude CLI-like):
```
deepseek-chat | coding | normal | 5% 6.5k/128k 8msg | ~/project | 3 files modified
```

Add: permission mode, working directory, git status (modified file count).

### 3.5 Conversation Compaction (`/compact`)

```
/compact                    Compact now
/compact keep API changes   Compact but preserve mentions of API changes
```

### 3.6 Todo/Task Tracking (`/todo`)

Like Claude CLI's TodoWrite:
```
/todo add "Fix auth bug"
/todo done 1
/todo list
/todo clear
```

---

## Phase 4: Chat Mode Polish

### 4.1 Chat-Specific Behaviors
- Markdown rendering for responses (already working via Rich)
- Auto-search for time-sensitive queries (already exists)
- No workspace scanning (save startup time)
- Safety confirmations always ON
- Friendlier, more conversational system prompt

### 4.2 Chat Commands
- Keep it simple — only conversation-relevant commands
- No file operation commands (no /read, /write, /edit, /run, /git)
- Focus: /search, /browse, /help, /think, /save, /load

---

## Phase 5: Entry Point and Mode Selection

### CLI Arguments
```bash
# Explicit mode selection
python main.py --mode chat
python main.py --mode coding

# Or shorthand aliases (in .zshrc)
alias ikol-chat="cd ~/Desktop/ikol1729_agent && source .venv/bin/activate && python3 main.py --mode chat"
alias ikol-code="cd ~/Desktop/ikol1729_agent && source .venv/bin/activate && python3 main.py --mode coding"
```

### Welcome Screen (mode-specific)

**Chat mode:**
```
╭─────────────────────────────────────────╮
│  ikol1729 — Chat Mode                   │
│  Model: deepseek-chat                   │
│  Type /help for commands, /quit to exit │
╰─────────────────────────────────────────╯
```

**Coding mode (Claude CLI-like):**
```
╭─────────────────────────────────────────╮
│  ikol1729 — Coding Mode                 │
│  Model: deepseek-chat                   │
│  Workspace: ~/Desktop/my-project        │
│  Tools: Bash, Read, Write, Edit,        │
│         Glob, Grep, LS                  │
│  /help for commands · Ctrl+D to exit    │
╰─────────────────────────────────────────╯
```

### No Cross-Mode Switching at Runtime

Remove `/mode chat` and `/mode coding` switching during a session. Pick your mode at startup. This keeps configs clean and avoids state confusion.

---

## Phase 6: Testing

### Functional Tests (not unit tests)

1. **Config loading** — verify base + mode configs merge correctly
2. **Chat mode smoke test** — launch, send message, get response, /search works, /read does NOT work
3. **Coding mode smoke test** — launch, /read a file, /edit it, /run a command, check status bar
4. **Permission model** — normal mode asks for confirm, auto-accept doesn't, plan mode blocks writes
5. **Auto-compact** — fill context to 95%, verify compaction triggers
6. **Command isolation** — chat mode rejects /run, coding mode accepts it
7. **Status bar** — verify mode-specific content (working dir in coding, not in chat)

---

## Implementation Order

| Step | Task | Files | Priority |
|------|------|-------|----------|
| 1 | Create `agent/config/` with base.yaml, chat.yaml, coding.yaml | new files | HIGH |
| 2 | Rewrite `agent_config.py` to load split configs | agent_config.py | HIGH |
| 3 | Separate command registries per mode | agent/core.py | HIGH |
| 4 | Split `SlashCommandCompleter` per mode | cli/claude_interface.py | HIGH |
| 5 | Create `agent/tools.py` (Claude CLI tool system) | new file | HIGH |
| 6 | Implement permission model | agent/core.py, new file | MEDIUM |
| 7 | Implement `/compact` command | agent/core.py | MEDIUM |
| 8 | Implement `/todo` command | agent/core.py | MEDIUM |
| 9 | Mode-specific welcome screens | cli/claude_interface.py | LOW |
| 10 | Remove runtime mode switching | agent/core.py, claude_interface.py | LOW |
| 11 | Add coding mode status bar extras (git status, cwd) | cli/claude_interface.py | LOW |
| 12 | Functional tests | tests/ | HIGH |

---

## Summary of Key Differences After Split

| Aspect | Chat Mode | Coding Mode |
|--------|-----------|-------------|
| System prompt | Conversational assistant | Claude CLI-like coding assistant |
| Available commands | 12 (conversation-focused) | 20+ (file ops, code, git, tools) |
| File operations | None | Full (read/write/edit/glob/grep) |
| Bash execution | No | Yes (/run) |
| Workspace scanning | Off | On |
| Permission model | N/A | Normal / Auto-accept / Plan |
| Safety confirmations | Always on | Configurable per permission mode |
| Status bar | Simple (model, think, context) | Rich (model, perms, context, cwd, git) |
| Auto-compact | No | Yes (at 95% context) |
| Todo tracking | No | Yes (/todo) |
| NL confidence | 0.8 | 0.7 |
| Config file | chat.yaml | coding.yaml |
