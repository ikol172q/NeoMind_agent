# Implementation Log

## 2026-04-03 — Phase 1 Gap Closure (Items 2-4)

### Item 2: Headless/Print Mode (-p flag) [DONE]

**File:** `main.py`

Added `-p/--print` argument and `--output-format` argument to `main.py`.

- `-p "prompt"` runs single-turn mode: creates NeoMindAgent, calls stream_response, prints result, exits
- `-p` without prompt reads from stdin (piped input)
- `--output-format json` outputs `{"response": "...", "tokens": N}`
- Streaming/thinking output suppressed via stdout redirect during execution
- Exit code 0 on success, 1 on error
- Fast-path in `_fast_path()` updated to pass through `-p` to argparse

**Verification:**
```
python3 main.py -p "What is 2+2?"           -> "4。"  (exit 0)
python3 main.py -p "What is 2+2?" --output-format json -> {"response":"4。","tokens":0}
```

### Item 3: Auto-compact wiring into agentic loop [VERIFIED - ALREADY DONE]

**File:** `agent/agentic/agentic_loop.py` (lines 326-368)

The ContextCollapser from `agent/services/compact/context_collapse.py` is already properly wired:
- Stage 1 (line 334): Imports ContextCollapser, builds CompactMessages from conversation, calls `should_collapse()` and `collapse()`
- Stage 2 (line 363): Falls back to full `compact_fn` if still over budget
- Token budget tracking via `record_usage()` on every iteration

No changes needed. The wiring was done correctly.

### Item 4: Tool Parser more variants [DONE]

**File:** `agent/coding/tool_parser.py`

Changes to `_LEGACY_BASH_RE`:
- Added `re.IGNORECASE` flag to handle `Bash`, `BASH`, `Shell`, `SHELL`, etc.
- Changed pattern to `r'```\s*(?:bash|shell|sh|console)\s*\n?(.*?)```'` — the `\s*` before the language tag handles ` ``` bash ` and ` ```  bash`

Added `_UNCLOSED_BASH_RE`:
- New regex for unclosed code blocks (LLM forgets closing ```)
- Pattern: `r'```\s*(?:bash|shell|sh|console)\s*\n?(.*)'` with `re.DOTALL | re.IGNORECASE`
- Wired into `parse()` as a fallback after closed bash blocks

**Verification (all pass):**
- `Bash`, `BASH`, `Shell` (case-insensitive) -> OK
- ` ``` bash`, ` ```  bash` (spaces) -> OK
- Unclosed ` ```bash\nls -la\n` (no closing) -> OK
- Normal ` ```bash\nls -la\n``` ` -> OK (no regression)

### Test Results

317 tests passed, 0 failed (`tests/test_new_security.py`, `test_new_memory.py`, `test_new_agentic.py`, `test_new_infra.py`).

---

## 2026-04-03 — Phase 2 Gap Closure (Items 5-7)

### Item 5: User-configurable Hooks System [DONE]

**File:** `agent/services/hooks.py` (new)

Created `HookRunner` class that reads shell hook configuration from `~/.neomind/settings.json` under the `"hooks"` key.

- **PreToolUse:** Before tool executes, runs configured shell commands with `HOOK_TOOL_NAME` and `HOOK_TOOL_INPUT` env vars
- **PostToolUse:** After tool executes, runs shell commands with `HOOK_TOOL_NAME`, `HOOK_TOOL_INPUT`, `HOOK_TOOL_OUTPUT`, `HOOK_TOOL_IS_ERROR` env vars
- **Exit codes:** 0=allow, 2=deny (blocks tool execution), other=warn (log + continue)
- Hook stdout captured and can be used in denial messages
- Tool filtering: hooks can specify `"tools": ["Bash", "Edit"]` to only trigger on specific tools
- 10-second timeout per hook to prevent hangs

**Wired into agentic loop:** `agent/agentic/agentic_loop.py`
- Added `_get_user_hook_runner()` lazy loader
- PreToolUse hook runs before `tool_def.execute()` in `_execute()` — if exit code 2, returns ToolResult with denial
- PostToolUse hook runs after execution completes, passing output and error status

**Service registry:** `agent/services/__init__.py`
- Added `hook_runner` lazy property to ServiceRegistry

### Item 6: Plugin System Basics [DONE]

**File:** `agent/services/plugin_loader.py` (new)

Created `PluginLoader` class that scans `~/.neomind/plugins/` for Python files.

- **Discovery:** Scans plugins dir for `.py` files (excluding `_`-prefixed)
- **Loading:** Uses `importlib.util.spec_from_file_location` to load each plugin module
- **Registration:** Each plugin must expose `register(tool_registry)` function
- **Reload:** `reload_all()` clears sys.modules entries and re-imports
- **Listing:** `list_plugins()` returns dicts with name/path/loaded/error
- **Formatting:** `format_plugin_list()` for human-readable display

**Service registry:** `agent/services/__init__.py`
- Added `plugin_loader` lazy property to ServiceRegistry

### Item 7: NEOMIND.md Auto-Discovery [DONE]

**File:** `agent/prompts/composer.py` (modified)

Added `inject_project_guidance()` method to `PromptComposer`:

- On startup, looks for project guidance in priority order:
  1. `{workspace}/.neomind/project.md` — project-specific
  2. `{workspace}/NEOMIND.md` — project-specific (alt location)
  3. `~/.neomind/NEOMIND.md` — global guidance
- Project-level: uses first found (project.md takes priority over NEOMIND.md)
- Global: always appended if present
- Injected as prompt section `project_guidance` with priority 45 (after tools, before context)

**Wired into ServiceRegistry:** `agent/services/__init__.py`
- `prompt_composer` property now calls `inject_project_guidance(workspace_root=os.getcwd())` on init

### Test Results (Phase 2)

317 tests passed, 0 failed (`tests/test_new_security.py`, `test_new_memory.py`, `test_new_agentic.py`, `test_new_infra.py`).

---

## 2026-04-03 — Phase 3 Gap Closure (Items 8, 11, 12)

### Item 8: Code Block Syntax Highlighting (pygments) [DONE]

**File:** `cli/neomind_interface.py`

Added pygments-based syntax highlighting for code blocks in LLM output:

- **`highlight_code_block(code, language)`** — highlights a single code block using pygments `TerminalFormatter` (ANSI colors)
- **`highlight_code_blocks_in_text(text)`** — regex-based detection of `` ```language ... ``` `` blocks, applies highlighting in-place
- **`_SyntaxHighlightFilter`** — streaming filter class for chat mode that buffers code blocks, highlights them when the closing fence arrives, and passes through non-code text immediately
- Graceful fallback: if pygments is not installed, all functions return text unchanged
- Wired into:
  - Chat mode streaming: `_SyntaxHighlightFilter` installed as `_content_filter` when `PYGMENTS_AVAILABLE` and mode is not coding
  - Fallback display path: `highlight_code_blocks_in_text()` applied to cleaned response text

### Item 11: CLI Argument Enhancement [DONE]

**File:** `main.py`, `cli/neomind_interface.py`

Added 5 new CLI arguments to `argparse`:

- **`--resume SESSION_NAME`** — resumes a previous session via the existing `/resume` command infrastructure
- **`--system-prompt TEXT`** — overrides the default system prompt
- **`--verbose`** — enables verbose/debug mode
- **`--cwd PATH`** — changes working directory before agent initialization
- **`--max-turns N`** — limits agentic loop iterations (overrides default of 15)

Updated help epilog with examples for all new flags.

### Item 12: Model Aliases [DONE]

**File:** `agent/services/llm_provider.py`, `agent/services/general_commands.py`

Added model alias system:

- **`MODEL_ALIASES`** dict: `opus`->`deepseek-reasoner`, `sonnet`->`deepseek-chat`, `haiku`->`deepseek-chat`, `reasoner`, `coder`, `chat`, `glm`, `flash`, `kimi`, `moonshot`
- **`resolve_model_alias()`** — resolves alias to actual model ID
- Wired into `set_model()`, `handle_switch_command()`, and `print_models()`

### Test Results (Phase 3)

317 tests passed, 0 failed (`tests/test_new_security.py`, `test_new_memory.py`, `test_new_agentic.py`, `test_new_infra.py`).

---

## 2026-04-03 — Phase 4 UI/UX Improvements (Items 14-16)

### Item 14: Tool Status Display Improvement [DONE]

**File:** `cli/neomind_interface.py`

Improved tool execution display in the agentic loop event handler:

- **tool_start:** Shows tool name and preview on a dedicated stderr line using `\r\033[K` to avoid mixing with LLM output: `🔧 ToolName(preview) ...`
- **tool_result:** Clears the spinner and shows completion status on its own line: `🔧 ToolName ✓` or `🔧 ToolName ✗`
- Tool preview truncated to 60 chars for clean display
- Status lines written to stderr so they don't contaminate stdout pipe output
- Detailed tool output still shown below the status line (unchanged)

### Item 15: Permission Dialog Formatting [DONE]

**File:** `cli/neomind_interface.py` (`_check_permission` method)

Enhanced the permission dialog with risk classification and explanations:

- Imports `PermissionManager` to get `classify_risk()` and `explain_permission()` results
- Shows **risk level** with color coding (LOW=green, MEDIUM=yellow, HIGH=orange, CRITICAL=red)
- Shows the **explanation string** from PermissionManager (e.g., "Permission needed to execute a shell command on your system. This executes code on your system.")
- Risk and explanation displayed before the parameter details in the Panel
- Graceful fallback: if PermissionManager import fails, falls back to permission level label

### Item 16: Git Commands Expansion [DONE]

**File:** `agent/cli_command_system.py`

Added two new git-related slash commands:

- **`/worktree`** — Manage git worktrees
  - No args or `list`: runs `git worktree list`
  - `add <path> [branch]`: runs `git worktree add`
  - `remove <path>`: runs `git worktree remove`
  - All subprocess calls wrapped in try/except with timeout
- **`/stash`** — Manage git stash
  - No args: runs `git stash list`
  - Any args passed through: `git stash <args>` (pop, push, drop, show, etc.)

Both commands registered in `_build_builtin_commands()` under coding mode with priority 33.

### Test Results (Phase 4)

317 tests passed, 0 failed (`tests/test_new_security.py`, `test_new_memory.py`, `test_new_agentic.py`, `test_new_infra.py`).
