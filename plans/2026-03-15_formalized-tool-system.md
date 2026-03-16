# Formalized Tool System — Implementation Plan

**Date:** 2026-03-15
**Status:** Implemented (Phases 1-3 complete, Phase 4 partial)
**Goal:** Transform user from prompt-only tool execution into a formalized, structured tool system with controlled I/O, guaranteed correctness, and Claude CLI-level smoothness.

> **Post-implementation note (2026-03-15):**
> The original plan proposed `<tool_call>` XML tags with JSON bodies. In practice, DeepSeek models **ignored the `<tool_call>` format entirely** — they wrote Python scripts with `open()` and `os.path.exists()` instead of using tools. Integration tests confirmed: 11/12 passed but `test_model_uses_structured_read` failed because DeepSeek produced Python code, not tool calls.
>
> **Pivot:** We switched to a **bash-centric approach** where the system prompt tells the model to use ` ```bash ` blocks for all operations (`cat`, `grep`, `python3 -m pytest`, etc.). A **python block fallback** was added for when DeepSeek outputs ` ```python ` blocks — these get wrapped in `python3 << 'PYEOF'` heredocs and executed as bash.
>
> The `<tool_call>` format is preserved in the parser as the first-priority check, in case a future model supports it, but the working system is bash-first.
>
> Additionally, the **`thinking` parameter** is now provider-gated — only sent to DeepSeek, not z.ai. See `2026-03-15_multi-provider.md` for provider details.

---

## Problem Analysis

### Current State (Prompt-Only Tools)

The current user agent relies on the LLM to produce bash code blocks, which are then extracted via regex and executed in a persistent bash session. This approach has several weaknesses:

1. **No structured tool calls.** The LLM must generate free-form bash, which is prone to hallucination, syntax errors, and unpredictable output formats.
2. **Single tool type.** Everything runs through `bash()` — Read, Write, Edit, Glob, Grep all exist in `tools.py` but are **only used by slash commands**, not by the agentic loop. The LLM has to `cat` files instead of calling `read_file()`.
3. **Output is unstructured.** Tool results are plain text dumped back into the conversation. No structured metadata (exit codes, file paths affected, bytes written).
4. **Hallucination risk.** The LLM can generate multi-block chains with fake output. Current mitigation (first-block-only) is a workaround, not a solution.
5. **No tool validation.** No input validation, no parameter typing, no schema. The system relies entirely on the LLM to get bash syntax right.

### Why Claude CLI Is Smooth

Based on research (Claude Code docs, architecture deep-dives):

1. **Structured tool calls via API.** Claude models support native `tool_use` — the model outputs structured JSON tool calls, not free-form text. The harness validates inputs, executes, and returns structured results. No regex parsing needed.
2. **Six typed core tools.** Read, Write, Edit, Bash, Glob, Grep — each with a JSON schema defining parameters and return types. The model "calls" them like function calls.
3. **Controlled I/O.** Each tool has defined input parameters and output format. The harness controls truncation, error reporting, and result formatting.
4. **Permission model per tool.** Different tools have different risk levels. Bash needs permission; Read doesn't. Granular control.
5. **Subagent isolation.** Complex tasks get delegated to subagents with their own context windows. The main conversation stays clean.

### The Gap

user uses **DeepSeek's API**, which does **not** natively support structured tool_use like Anthropic's API. This means we can't do native tool calls. BUT we can build the next best thing: a **structured tool dispatch system** that:

- Defines typed tool schemas in code
- Teaches the LLM to output tool calls in a predictable format (JSON or structured blocks)
- Parses and validates tool calls before execution
- Returns structured results
- Provides per-tool permissions

---

## Architecture Design

### Proposed Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   ClaudeInterface (UI)                       │
│  - Spinner, permission prompts, status bar                  │
│  - Delegates to AgenticLoop                                 │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                   AgenticLoop                                │
│  - Extracts tool calls from LLM response                    │
│  - Validates against tool schemas                            │
│  - Dispatches to ToolRegistry                                │
│  - Formats results back to LLM                               │
│  - Manages iteration (max 10 rounds)                         │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                   ToolRegistry (Enhanced)                     │
│                                                              │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │   Bash   │ │   Read   │ │  Write   │ │   Edit   │       │
│  │ schema+  │ │ schema+  │ │ schema+  │ │ schema+  │       │
│  │ validate │ │ validate │ │ validate │ │ validate │       │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘       │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │   Glob   │ │   Grep   │ │    LS    │ │  Search  │       │
│  │ schema+  │ │ schema+  │ │ schema+  │ │ schema+  │       │
│  │ validate │ │ validate │ │ validate │ │ validate │       │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘       │
│                                                              │
│  Base: ToolDefinition(name, description, parameters,         │
│        execute(), permission_level, output_format)           │
└─────────────────────────────────────────────────────────────┘
```

### Tool Call Format

Since DeepSeek doesn't support native tool_use, we teach the LLM to output structured tool calls in a parseable format:

```
<tool_call>
{"tool": "Read", "params": {"path": "src/main.py", "offset": 0, "limit": 50}}
</tool_call>
```

Or for Bash:
```
<tool_call>
{"tool": "Bash", "params": {"command": "python3 -m pytest tests/ -v", "timeout": 60}}
</tool_call>
```

**Why this format:**
- XML tags are unambiguous — no false positives from code blocks
- JSON body enables schema validation before execution
- Easy to parse with regex: `<tool_call>\s*({.*?})\s*</tool_call>`
- The model is instructed to output ONE tool_call per response, then stop

**Backward compatibility:** The existing bash code block format (```` ```bash ... ``` ````) is kept as a fallback parser. If the model outputs code blocks instead of `<tool_call>`, we still handle it (mapped to Bash tool). This makes the migration gradual.

---

## Implementation Plan — 4 Phases

### Phase 1: Tool Definition Framework (Foundation)
**Files:** `agent/tool_schema.py` (NEW), `agent/tools.py` (MODIFY)
**Estimated complexity:** Medium

#### 1.1 Create `ToolDefinition` base class

```python
# agent/tool_schema.py

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable
from enum import Enum

class PermissionLevel(Enum):
    """Tool permission categories."""
    READ_ONLY = "read_only"       # No confirmation needed
    WRITE = "write"               # Confirm in normal mode
    EXECUTE = "execute"           # Always confirm unless auto_accept
    DESTRUCTIVE = "destructive"   # Confirm even in auto_accept

class ParamType(Enum):
    STRING = "string"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    FLOAT = "float"

@dataclass
class ToolParam:
    """A single tool parameter definition."""
    name: str
    type: ParamType
    description: str
    required: bool = True
    default: Any = None
    enum: Optional[List[str]] = None  # Allowed values

@dataclass
class ToolDefinition:
    """Complete definition of a tool."""
    name: str
    description: str
    parameters: List[ToolParam]
    permission_level: PermissionLevel
    execute: Callable  # The actual function to call
    examples: List[Dict[str, Any]] = field(default_factory=list)

    def validate_params(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Validate parameters against schema. Returns (valid, error_msg)."""
        # Check required params
        for p in self.parameters:
            if p.required and p.name not in params:
                return False, f"Missing required parameter: {p.name}"
            if p.name in params:
                # Type checking
                val = params[p.name]
                if p.type == ParamType.STRING and not isinstance(val, str):
                    return False, f"Parameter '{p.name}' must be string, got {type(val).__name__}"
                if p.type == ParamType.INTEGER and not isinstance(val, int):
                    return False, f"Parameter '{p.name}' must be integer, got {type(val).__name__}"
                if p.type == ParamType.BOOLEAN and not isinstance(val, bool):
                    return False, f"Parameter '{p.name}' must be boolean, got {type(val).__name__}"
                if p.enum and val not in p.enum:
                    return False, f"Parameter '{p.name}' must be one of {p.enum}"
        return True, ""

    def to_prompt_schema(self) -> str:
        """Generate the schema description for the system prompt."""
        params_desc = []
        for p in self.parameters:
            req = "required" if p.required else f"optional, default={p.default}"
            desc = f"    - {p.name} ({p.type.value}, {req}): {p.description}"
            if p.enum:
                desc += f" [values: {', '.join(p.enum)}]"
            params_desc.append(desc)
        return f"""**{self.name}**: {self.description}
  Parameters:
{chr(10).join(params_desc)}"""
```

#### 1.2 Register all existing tools with schemas

Wrap each existing tool method in `tools.py` with a `ToolDefinition`:

| Tool | Parameters | Permission | Notes |
|------|-----------|------------|-------|
| **Bash** | command (str, req), timeout (int, opt=120) | EXECUTE | Persistent session |
| **Read** | path (str, req), offset (int, opt=0), limit (int, opt=0) | READ_ONLY | Auto-approve |
| **Write** | path (str, req), content (str, req) | WRITE | Confirm in normal |
| **Edit** | path (str, req), old_string (str, req), new_string (str, req), replace_all (bool, opt=false) | WRITE | Must read first |
| **Glob** | pattern (str, req), path (str, opt=cwd) | READ_ONLY | Auto-approve |
| **Grep** | pattern (str, req), path (str, opt=cwd), file_type (str, opt), context (int, opt=0), case_insensitive (bool, opt=false), output_mode (str, opt="content") | READ_ONLY | Auto-approve |
| **LS** | path (str, opt=cwd) | READ_ONLY | Auto-approve |

#### 1.3 Enhanced `ToolResult` with metadata

```python
@dataclass
class ToolResult:
    success: bool
    output: str = ""
    error: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    # metadata examples: {"lines_read": 150, "file_path": "/abs/path"}
    #                    {"exit_code": 0, "duration_ms": 1234}
    #                    {"files_matched": 42, "pattern": "**/*.py"}
```

**Validation tests:**
- Each tool schema validates required params
- Type mismatches are caught
- Enum constraints enforced
- Missing params produce clear error messages

---

### Phase 2: Structured Tool Call Parser (Brain)
**Files:** `agent/tool_parser.py` (NEW), `agent/config/coding.yaml` (MODIFY)
**Estimated complexity:** Medium-High

#### 2.1 Create `ToolCallParser`

```python
# agent/tool_parser.py

import re
import json
from typing import Optional, List, Tuple

class ToolCall:
    """A parsed tool call from LLM output."""
    def __init__(self, tool_name: str, params: dict, raw: str):
        self.tool_name = tool_name
        self.params = params
        self.raw = raw  # Original text for display

class ToolCallParser:
    """Parse structured tool calls from LLM responses.

    Supports two formats:
    1. Structured: <tool_call>{"tool": "Read", "params": {...}}</tool_call>
    2. Legacy: ```bash ... ``` (mapped to Bash tool)
    """

    _STRUCTURED_RE = re.compile(
        r'<tool_call>\s*(\{.*?\})\s*</tool_call>',
        re.DOTALL
    )
    _LEGACY_BASH_RE = re.compile(
        r'```(?:bash|shell|sh|console)\s*\n(.*?)```',
        re.DOTALL
    )

    def parse(self, response: str) -> Optional[ToolCall]:
        """Parse the FIRST tool call from response. Returns None if no tool call found."""
        # Try structured format first
        m = self._STRUCTURED_RE.search(response)
        if m:
            return self._parse_structured(m)

        # Fallback to legacy bash blocks
        m = self._LEGACY_BASH_RE.search(response)
        if m:
            return self._parse_legacy_bash(m, response)

        return None

    def _parse_structured(self, match) -> Optional[ToolCall]:
        """Parse a <tool_call> JSON block."""
        try:
            data = json.loads(match.group(1))
            tool_name = data.get("tool", "")
            params = data.get("params", {})
            if not tool_name:
                return None
            return ToolCall(tool_name, params, match.group(0))
        except json.JSONDecodeError:
            return None

    def _parse_legacy_bash(self, match, full_response: str) -> Optional[ToolCall]:
        """Parse a ```bash block as a Bash tool call."""
        code = match.group(1).strip()
        if not code:
            return None
        # Skip comment-only blocks
        lines = [l for l in code.split('\n') if l.strip() and not l.strip().startswith('#')]
        if not lines:
            return None
        # Check for hallucinated output
        end_pos = match.end()
        after = full_response[end_pos:end_pos + 200].strip()
        if after.startswith('```\n') or after.startswith('```\r'):
            return None
        return ToolCall("Bash", {"command": code}, match.group(0))

    def strip_tool_call(self, response: str, tool_call: ToolCall) -> str:
        """Remove the tool call from the response text (for display)."""
        return response.replace(tool_call.raw, "").strip()
```

#### 2.2 Update system prompt for structured tool calls

The `coding.yaml` system prompt gets a new section teaching the model to use `<tool_call>` format:

```yaml
system_prompt: |
  ...existing first principles identity...

  TOOL SYSTEM:
  You have access to these tools. To use a tool, output EXACTLY ONE tool call:

  <tool_call>
  {"tool": "ToolName", "params": {"param1": "value1", ...}}
  </tool_call>

  After the tool call, STOP. The system will execute it and show you the result.
  Then you will be re-prompted to continue.

  AVAILABLE TOOLS:
  [Auto-generated from tool schemas — see Phase 1.2]

  RULES:
  - Output ONE tool call per response, then STOP
  - Do NOT guess or hallucinate tool output
  - Wait for real results before proceeding
  - Read a file before editing it
  - For complex tasks, break into steps and use one tool per step

  TOOL CALL EXAMPLES:
  [Auto-generated from tool definition examples]
```

**Key insight:** The system prompt's tool section is **auto-generated** from the registered `ToolDefinition` schemas. When a new tool is added, it automatically appears in the prompt. No manual prompt maintenance.

#### 2.3 Content filter update

Update `_CodeFenceFilter` to also suppress `<tool_call>` blocks from terminal display:

```python
# Add to existing filter:
_TOOL_CALL_OPEN_RE = re.compile(r'<tool_call>\s*')
_TOOL_CALL_CLOSE = '</tool_call>'
```

**Validation tests:**
- Parser extracts structured tool calls correctly
- Parser falls back to legacy bash blocks
- Parser handles malformed JSON gracefully
- Parser detects hallucinated output (inline results)
- System prompt auto-generates from schemas
- Content filter suppresses `<tool_call>` from display

---

### Phase 3: Agentic Loop Rewrite (Heart)
**Files:** `cli/claude_interface.py` (MODIFY), `agent/agentic_loop.py` (NEW)
**Estimated complexity:** High

#### 3.1 Extract `AgenticLoop` class

Move the agentic loop logic out of `ClaudeInterface` into its own class:

```python
# agent/agentic_loop.py

class AgenticLoop:
    """Manages the tool execution cycle between LLM responses.

    Flow:
    1. LLM generates response with tool call
    2. Parser extracts the tool call
    3. Registry validates parameters
    4. Permission check (based on tool's permission_level)
    5. Execute tool
    6. Format result as structured feedback
    7. Re-prompt LLM
    8. Repeat until no tool calls or max iterations
    """

    def __init__(self, tool_registry, tool_parser, permission_manager, ui_callbacks):
        self.registry = tool_registry
        self.parser = tool_parser
        self.permissions = permission_manager
        self.ui = ui_callbacks  # spinner_start, spinner_update, print, etc.

    def run(self, chat, max_iterations=10):
        """Run the agentic loop on the latest assistant message."""
        auto_approved = False

        for i in range(max_iterations):
            response = self._get_last_assistant_message(chat)
            if not response:
                return

            tool_call = self.parser.parse(response)
            if not tool_call:
                return  # No more tool calls

            # Resolve tool definition
            tool_def = self.registry.get_tool(tool_call.tool_name)
            if not tool_def:
                # Unknown tool — feed error back
                self._feed_error(chat, f"Unknown tool: {tool_call.tool_name}")
                continue

            # Validate parameters
            valid, error = tool_def.validate_params(tool_call.params)
            if not valid:
                self._feed_error(chat, f"Invalid params for {tool_call.tool_name}: {error}")
                continue

            # Permission check
            approved, auto_approved = self.permissions.check(
                tool_def, tool_call, auto_approved
            )
            if not approved:
                return

            # Execute with spinner
            self.ui.spinner_start(f"Thinking… {tool_call.tool_name}")
            result = tool_def.execute(**tool_call.params)

            # Feed result back
            self._feed_result(chat, tool_call, result)

            # Re-prompt LLM
            self.ui.stream_and_render_inner()

    def _feed_result(self, chat, tool_call, result):
        """Format tool result as structured feedback to the LLM."""
        feedback = f"""<tool_result>
tool: {tool_call.tool_name}
status: {"OK" if result.success else "ERROR"}
output: |
  {self._indent(result.output[:3000])}
</tool_result>"""
        # If there's metadata, include it
        if result.metadata:
            feedback += f"\nmetadata: {json.dumps(result.metadata)}"
        chat.add_to_history("user", feedback)
```

#### 3.2 Permission manager

```python
class PermissionManager:
    """Handles per-tool permission checks."""

    def check(self, tool_def, tool_call, auto_approved):
        """Returns (approved: bool, new_auto_approved: bool)"""
        mode = agent_config.permission_mode

        if mode == "plan":
            # Plan mode: only READ_ONLY tools run
            if tool_def.permission_level == PermissionLevel.READ_ONLY:
                return True, auto_approved
            self.ui.print(f"Would run: {tool_call.tool_name}({tool_call.params})")
            return False, auto_approved

        if mode == "auto_accept" or auto_approved:
            return True, auto_approved

        # Normal mode: READ_ONLY auto-approves, others ask
        if tool_def.permission_level == PermissionLevel.READ_ONLY:
            return True, auto_approved

        # Ask user
        preview = self._format_preview(tool_call)
        choice = input(f"  │ {preview}\n  │ Run? [y/n/a]: ").strip().lower()
        if choice in ("a", "all"):
            return True, True
        return choice in ("y", "yes"), auto_approved
```

**Key improvements over current system:**
- READ_ONLY tools (Read, Glob, Grep, LS) never ask permission — smoother flow
- WRITE tools (Write, Edit) ask in normal mode
- EXECUTE tools (Bash) always ask
- Plan mode allows read-only exploration without execution

#### 3.3 Structured result feedback

Instead of raw text, tool results go back to the LLM in a structured format:

```xml
<tool_result>
tool: Read
status: OK
output: |
  # src/main.py (42 lines)
       1  import os
       2  import sys
       ...
metadata: {"lines_read": 42, "file_path": "/abs/path/src/main.py"}
</tool_result>
```

This gives the LLM clear, consistent context about what happened.

**Validation tests:**
- AgenticLoop extracts and executes tool calls
- Permission manager respects tool permission levels
- READ_ONLY tools auto-approve in normal mode
- Plan mode only allows READ_ONLY
- auto_approved flag works per-turn
- Structured results are properly formatted
- Max iterations are respected
- Errors are fed back gracefully

---

### Phase 4: New Tools & Integration (Polish)
**Files:** Multiple new tool files, config updates
**Estimated complexity:** Medium

#### 4.1 Additional tools to implement

| Tool | Description | Priority |
|------|-------------|----------|
| **Search** | Web search (DuckDuckGo) | High — already exists in core |
| **Think** | Extended thinking mode trigger | Medium |
| **Git** | Structured git operations | High |
| **Test** | Run test suites with parsed output | Medium |
| **Diff** | Show file/git diffs | Low |

#### 4.2 Auto-generated system prompt

```python
def generate_tool_prompt(registry: ToolRegistry) -> str:
    """Generate the TOOL SYSTEM section of the system prompt from registered tools."""
    sections = []
    for tool in registry.get_all_tools():
        sections.append(tool.to_prompt_schema())

    return f"""TOOL SYSTEM:
You have access to these tools. To use a tool, output exactly one tool call:

<tool_call>
{{"tool": "ToolName", "params": {{"param1": "value1"}}}}
</tool_call>

After the tool call, STOP and wait for results.

AVAILABLE TOOLS:

{chr(10).join(sections)}

RULES:
- ONE tool call per response, then STOP
- Do NOT hallucinate output — wait for real results
- Read files before editing them
- Break complex tasks into steps
"""
```

#### 4.3 Comprehensive bash command cheatsheet

Create `agent/config/tool_examples.yaml` with categorized examples for the system prompt, covering:

1. File operations (read, write, edit, glob, grep)
2. Git workflows (status, diff, commit, branch, log)
3. Package management (pip, npm, cargo)
4. Testing (pytest, jest, go test)
5. Build & run (make, docker, scripts)
6. Text processing (sed, awk, jq, yq)
7. System info (ps, df, du, uname)
8. Network (curl, wget, ping)
9. Modern CLI tools (fd, bat, delta, fzf)

These examples are injected into the system prompt contextually based on the detected project type.

#### 4.4 Project type detection

```python
def detect_project_type(working_dir: str) -> List[str]:
    """Detect project type from files in working directory."""
    indicators = {
        "python": ["pyproject.toml", "setup.py", "requirements.txt", "*.py"],
        "node": ["package.json", "tsconfig.json", "*.ts", "*.js"],
        "rust": ["Cargo.toml", "*.rs"],
        "go": ["go.mod", "*.go"],
        "java": ["pom.xml", "build.gradle", "*.java"],
    }
    # Returns list of detected types
```

---

## Validation Strategy

### Unit Tests (per phase)

**Phase 1:**
- `test_tool_schema.py` — ToolDefinition creation, param validation, type checking, schema generation
- `test_tool_result.py` — ToolResult with metadata, string formatting

**Phase 2:**
- `test_tool_parser.py` — Structured parse, legacy parse, malformed JSON, hallucination detection
- `test_prompt_generation.py` — Auto-generated prompt matches expected format

**Phase 3:**
- `test_agentic_loop.py` — Full loop with mock tools, permission checks, max iterations, error handling
- `test_permission_manager.py` — All permission modes × all permission levels

**Phase 4:**
- `test_project_detection.py` — Project type detection accuracy
- `test_integration.py` — End-to-end: prompt → tool call → execution → result feedback

### Integration Tests

1. **Round-trip test:** Send a prompt that requires file reading → verify Read tool is called with correct params → verify result is fed back correctly
2. **Multi-step test:** Task requiring Read → Edit → Bash (run tests) → verify full chain executes
3. **Permission test:** Verify READ_ONLY tools don't prompt, WRITE tools do, plan mode blocks execution
4. **Backward compatibility test:** Verify bash code blocks still work as Bash tool calls
5. **Error recovery test:** Invalid tool name → error feedback → LLM corrects → success

### Manual Testing Checklist

- [ ] Start agent in coding mode
- [ ] Ask to "read main.py" → should use Read tool, no permission prompt
- [ ] Ask to "fix the bug in X" → should Read, then Edit (asks permission), then test
- [ ] `/permissions auto` → verify no prompts for any tool
- [ ] `/permissions plan` → verify only Read/Glob/Grep work
- [ ] Send ambiguous prompt → verify graceful fallback to bash
- [ ] Long-running command → verify timeout works
- [ ] Permission "a" → verify rest of turn is auto-approved

---

## Migration Path

```
Week 1: Phase 1 — ToolDefinition framework + enhanced ToolResult
         (No behavior change — foundation only)

Week 2: Phase 2 — ToolCallParser + updated system prompt
         (Model starts using <tool_call> format, bash fallback preserved)

Week 3: Phase 3 — AgenticLoop rewrite + PermissionManager
         (Full structured loop, per-tool permissions)

Week 4: Phase 4 — New tools + auto-prompt + project detection
         (Polish and integration)
```

Each phase is independently testable and deployable. The bash code block fallback ensures nothing breaks during migration.

---

## Key Design Decisions

### 1. Why `<tool_call>` tags instead of native function calling?

DeepSeek's API doesn't support Anthropic-style `tool_use`. XML tags are:
- Unambiguous (won't appear in normal code)
- Easy to parse
- Model-friendly (all LLMs understand XML tags)
- Forward-compatible (if DeepSeek adds function calling, we can switch the parser)

### 2. Why keep the bash fallback?

- Gradual migration — old sessions still work
- Some models may not follow the `<tool_call>` format perfectly
- Bash is still the right tool for ad-hoc commands
- Belt-and-suspenders reliability

### 3. Why per-tool permissions instead of global?

Claude CLI's smoothness comes partly from not asking for permission on READ_ONLY operations. Every `cat` command requiring a "y" kills the flow. With per-tool permissions:
- Read, Glob, Grep, LS → auto-approve (information gathering)
- Write, Edit → ask in normal mode (file modification)
- Bash → ask in normal mode (arbitrary execution)
- Everything auto-approves in `auto_accept` mode

### 4. Why auto-generate the system prompt from schemas?

- Single source of truth — tool definitions live in code, not duplicated in YAML
- Adding a new tool automatically updates the prompt
- Schema changes propagate without manual editing
- Testable — we can verify prompt accuracy programmatically

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| DeepSeek doesn't follow `<tool_call>` format reliably | Medium | High | Bash fallback parser, few-shot examples in prompt |
| Breaking existing agentic loop behavior | Low | High | Phase 2 keeps backward compatibility, extensive tests |
| Performance overhead from schema validation | Low | Low | Validation is simple dict/type checks |
| System prompt bloat from tool schemas | Medium | Medium | Only inject relevant tools based on project type |
| LLM outputs multiple tool calls per response | Medium | Low | Parser takes first only, just like current system |

---

## File Summary

| File | Action | Description |
|------|--------|-------------|
| `agent/tool_schema.py` | NEW | ToolDefinition, ToolParam, PermissionLevel, validation |
| `agent/tool_parser.py` | NEW | ToolCallParser, ToolCall, structured + legacy parsing |
| `agent/agentic_loop.py` | NEW | AgenticLoop class, PermissionManager |
| `agent/tools.py` | MODIFY | Register tools with schemas, enhanced ToolResult |
| `agent/config/coding.yaml` | MODIFY | Updated system prompt with tool call format |
| `agent/config/tool_examples.yaml` | NEW | Categorized tool usage examples |
| `cli/claude_interface.py` | MODIFY | Delegate to AgenticLoop, update content filter |
| `tests/test_tool_schema.py` | NEW | Schema validation tests |
| `tests/test_tool_parser.py` | NEW | Parser tests |
| `tests/test_agentic_loop.py` | NEW | Loop + permission tests |
| `tests/test_integration.py` | NEW | End-to-end tests |
