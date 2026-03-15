# Plan: Tool Architecture Upgrade — Close the Gap with Claude CLI

**Created:** 2026-03-14
**Status:** Done
**Priority:** High — this is the core quality gap in coding mode

---

## Problem Statement

ikol1729's coding mode tools feel weak compared to Claude CLI. Root cause analysis reveals three fundamental architecture gaps plus one critical integration issue:

| Gap | Claude CLI | ikol1729 (current) | Impact |
|-----|-----------|-------------------|--------|
| Persistent Bash | `Popen` with pipes, state carries across calls | `subprocess.run()` — stateless, new process each call | `cd`, `export`, env vars lost between commands |
| Fast Search | Shells out to **ripgrep** (`rg`) — Rust-native, respects .gitignore | Pure Python `re.search()` line-by-line walk | Catastrophically slow on 1000+ file repos |
| Output Truncation | 30K char limit, middle-truncation strategy | No limit — full output dumped | Wastes context tokens, LLM chokes on huge output |
| Tool→LLM Loop | Tool results injected into conversation as `tool_result` messages | **Command output only printed, NEVER added to history** | LLM has no memory of /run, /grep, /git results |

**The #4 gap is the worst.** When a user runs `/grep TODO`, the results appear on screen but the AI has no knowledge of them. If the user then asks "fix those TODOs", the AI has no idea what they are. This makes every tool effectively disconnected from the AI reasoning loop.

---

## Architecture: How Claude CLI Actually Works

### Agent Loop (how tools integrate with LLM)

```
User Input
    ↓
┌─────────────────────────────┐
│  LLM decides: use a tool    │ ← tool_use block in response
│  e.g. Bash("grep -r TODO")  │
└─────────────┬───────────────┘
              ↓
┌─────────────────────────────┐
│  Permission Check            │ ← allow/ask/deny
│  (normal/auto-accept/plan)   │
└─────────────┬───────────────┘
              ↓
┌─────────────────────────────┐
│  Tool Execution              │
│  → persistent bash session   │
│  → ripgrep for search        │
│  → output truncated to 30K   │
└─────────────┬───────────────┘
              ↓
┌─────────────────────────────┐
│  Result → conversation       │ ← tool_result block
│  (truncated, formatted)      │
└─────────────┬───────────────┘
              ↓
┌─────────────────────────────┐
│  LLM processes result        │
│  → decides next action       │
│  → may call another tool     │
│  → or respond to user        │
└─────────────────────────────┘
```

**Key insight:** In Claude CLI, the LLM *decides* when to use tools. In ikol1729, the *user* manually types `/grep`. Both approaches are valid, but the tool output MUST flow back into the conversation either way.

### Claude CLI Bash: Persistent Session

```
Implementation: subprocess.Popen(["bash"], stdin=PIPE, stdout=PIPE, stderr=PIPE)
- Single process, reused across all /run calls
- cd, export, source all persist
- Reader threads on stdout/stderr queues
- Sentinel pattern to detect command completion
- Timeout: 120s default, configurable
- Output: 30K char cap, middle-truncation
```

### Claude CLI Grep: Ripgrep Wrapper

```
Implementation: subprocess.run(["rg", pattern, ...flags])
- Respects .gitignore automatically
- Binary file detection built-in
- Output modes: content, files_with_matches, count
- Context lines: -A, -B, -C flags
- File type filter: --type py, --type js
- Case insensitive: -i flag
- 5-10x faster than Python regex walk
```

---

## Implementation Plan

### Step 1: Tool→LLM Integration (CRITICAL, do first)

**Problem:** Command output is printed but never added to conversation history.

**Current flow (broken):**
```python
# core.py line ~4100
response = handler(arg)       # handler runs /grep, /run, etc.
self._safe_print(response)    # printed to screen
return None                   # ← LLM never sees it
```

**Target flow:**
```python
response = handler(arg)
self._safe_print(response)
# NEW: Add tool result to conversation so LLM can reason about it
truncated = self._truncate_output(response, max_chars=30000)
self.add_to_history("user", f"[Tool: /{cmd}] {truncated}")
# Don't return None — let the LLM process the result
```

**Design decisions:**
- Add as "user" role (same as how /read already works)
- Prefix with `[Tool: /command]` so LLM knows it's tool output, not user text
- Truncate to 30K chars using middle-truncation (matches Claude CLI)
- Make this opt-in per command (some like /help, /clear shouldn't feed to LLM)

**Commands that SHOULD feed results to LLM:**
- /run, /grep, /find, /read, /git, /code, /analyze, /diff, /test, /glob, /ls

**Commands that should NOT:**
- /help, /clear, /think, /debug, /save, /load, /history, /quit, /exit, /models

**Files to modify:**
- `agent/core.py` — command dispatch loop, add `_truncate_output()` method
- Tag each handler in `command_handlers` dict with `feed_to_llm=True/False`

**Validation:**
1. Run `/grep def main` → verify output appears in `conversation_history`
2. Then type "what did you find?" → LLM should reference grep results
3. Run `/run echo hello` → type "what was the output?" → LLM should say "hello"
4. Run `/help` → verify it does NOT appear in history

---

### Step 2: Persistent Bash Session

**Problem:** Each `/run` spawns a fresh subprocess. `cd /tmp` then `/run ls` shows original dir.

**Implementation: `PersistentBash` class**

```python
# agent/persistent_bash.py (NEW file)

class PersistentBash:
    """Persistent bash session like Claude CLI's Bash tool."""

    def __init__(self, working_dir=None, timeout=120, max_output=30000):
        self.proc = subprocess.Popen(
            ["bash", "--norc", "--noprofile"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=working_dir,
            bufsize=0,
        )
        self.timeout = timeout
        self.max_output = max_output
        self._sentinel = "__IKOL_CMD_DONE__"
        # Start reader threads for stdout/stderr

    def execute(self, command: str, timeout: int = None) -> ToolResult:
        """Run command in persistent session. State carries forward."""
        # Write command + sentinel echo to stdin
        # Read stdout/stderr until sentinel detected
        # Apply timeout
        # Truncate output if > max_output (middle-truncation)
        # Return ToolResult

    def get_cwd(self) -> str:
        """Get current working directory of the session."""
        result = self.execute("pwd")
        return result.output.strip()

    def close(self):
        """Terminate the bash session."""
        self.proc.terminate()
```

**Middle-truncation strategy (matching Claude CLI):**
```python
def _truncate_middle(self, text: str, max_chars: int = 30000) -> str:
    if len(text) <= max_chars:
        return text
    keep = max_chars // 2
    return (
        text[:keep]
        + f"\n\n... [{len(text) - max_chars} chars truncated] ...\n\n"
        + text[-keep:]
    )
```

**Integration:**
- `ToolRegistry.bash()` uses `PersistentBash` instead of `subprocess.run()`
- Session created when coding mode starts, destroyed on exit
- `/run` handler delegates to `PersistentBash.execute()`
- Status bar shows current working dir from `PersistentBash.get_cwd()`

**Validation:**
1. `/run cd /tmp` → `/run pwd` → should show `/tmp`
2. `/run export FOO=bar` → `/run echo $FOO` → should show `bar`
3. `/run sleep 200` → should timeout after 120s
4. `/run cat /dev/urandom | head -c 100000 | base64` → output should be truncated to 30K

**Files:**
- `agent/persistent_bash.py` (NEW)
- `agent/tools.py` — update `bash()` to use persistent session
- `agent/core.py` — create session on coding mode init, cleanup on exit

---

### Step 3: Ripgrep Integration

**Problem:** Pure Python grep is too slow for real codebases.

**Strategy:** Shell out to `rg` if available, fall back to Python.

```python
# In agent/tools.py — updated grep_files()

def grep_files(self, pattern, path=None, file_type=None, context=0,
               max_results=50, case_insensitive=False, output_mode="content"):
    """Search files with ripgrep (fast) or Python fallback."""

    if self._has_ripgrep():
        return self._grep_ripgrep(pattern, path, file_type, context,
                                   max_results, case_insensitive, output_mode)
    else:
        return self._grep_python(pattern, path, file_type, context,
                                  max_results, case_insensitive)

def _has_ripgrep(self):
    """Check if rg binary is available."""
    try:
        subprocess.run(["rg", "--version"], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False

def _grep_ripgrep(self, pattern, path, file_type, context,
                   max_results, case_insensitive, output_mode):
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
    if max_results:
        cmd.extend(["-m", str(max_results)])

    cmd.append("-n")  # line numbers
    cmd.append("--no-heading")  # flat output
    cmd.append(str(path or self.working_dir))

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    # ... format and return ToolResult
```

**Installation:**
- macOS: `brew install ripgrep`
- Linux: `apt install ripgrep` or `cargo install ripgrep`
- Add to TROUBLESHOOTING.md: "For fast search, install ripgrep: brew install ripgrep"

**Validation:**
1. With `rg` installed: `/grep "def main" --type py` → fast results, respects .gitignore
2. Without `rg`: same command → Python fallback, slower but works
3. Large repo test: clone a 10K-file repo, time `/grep import` → should complete in <1s with rg

**Files:**
- `agent/tools.py` — rewrite `grep_files()` with rg integration + Python fallback

---

### Step 4: Read Tool Enhancement

**Problem:** No token/character limit, no pagination awareness.

**Changes:**
- Add 30K character limit to file reads (consistent with bash truncation)
- Improve offset/limit UX — show total lines and remaining
- Add binary file detection (skip files with NUL bytes)

```python
def read_file(self, path, offset=0, limit=0, max_chars=30000):
    # ... existing logic ...
    output = header + "\n" + "\n".join(numbered_lines)

    # Truncate if too long
    if len(output) > max_chars:
        output = self._truncate_middle(output, max_chars)

    return ToolResult(True, output=output)
```

**Validation:**
1. Read a 10K-line file → output should be truncated with middle-truncation message
2. Read with offset=500, limit=50 → should show lines 501-550

**Files:**
- `agent/tools.py` — update `read_file()`

---

### Step 5: Glob Enhancement

**Changes:**
- Sort results by mtime (most recently modified first)
- Respect .gitignore if git repo detected

```python
def glob_files(self, pattern, path=None):
    # ... existing logic ...

    # Sort by mtime (most recent first)
    filtered.sort(key=lambda f: (base / f).stat().st_mtime, reverse=True)
```

**Files:**
- `agent/tools.py` — update `glob_files()`

---

## Implementation Order & Timeline

| Step | Task | Effort | Dependencies |
|------|------|--------|-------------|
| **1** | Tool→LLM integration (command output → conversation history) | 2-3 hours | None |
| **2** | Persistent Bash session | 3-4 hours | Step 1 (for LLM to see results) |
| **3** | Ripgrep integration | 1-2 hours | Step 1 |
| **4** | Read tool truncation | 30 min | None |
| **5** | Glob mtime sorting | 30 min | None |

**Step 1 is the highest priority.** Without it, steps 2-5 improve tool quality but the LLM still can't reason about results.

---

## Validation Strategy

### Per-step validation (during implementation)
Each step has specific test cases listed above.

### End-to-end validation (after all steps)

**Test 1: Tool chain reasoning**
```
> /grep "TODO" --type py
(results shown + added to history)
> can you fix those TODOs?
(LLM should reference the actual grep results and propose fixes)
```

**Test 2: Persistent state**
```
> /run cd /tmp && mkdir test_dir
> /run ls test_dir
(should work — same session, dir persists)
> /run pwd
(should show /tmp)
```

**Test 3: Large output handling**
```
> /run find / -name "*.py" 2>/dev/null
(output should be truncated to 30K, not flood the terminal/context)
```

**Test 4: Search speed**
```
> /grep "import" (in a large repo)
(should complete in <2s with ripgrep, not 30s+ with Python)
```

**Test 5: Full coding workflow**
```
> /read main.py
> there's a bug on line 42, fix it
> /edit main.py "old code" "new code"
> /run python main.py
> did it work?
(LLM should be able to follow the entire chain because all results are in history)
```

---

## Risk Assessment

| Risk | Mitigation |
|------|-----------|
| Persistent bash process leaks | `close()` in `__del__`, `atexit` handler, timeout per command |
| ripgrep not installed | Python fallback — always works, just slower |
| Output truncation loses important info | Middle-truncation preserves start + end, configurable limit |
| Tool output floods context window | 30K char cap per tool result, auto-compact at 95% |
| Breaking existing command handlers | Step 1 is additive — existing print behavior unchanged, we ADD history |

---

## Files Summary

| File | Action | What |
|------|--------|------|
| `agent/persistent_bash.py` | NEW | Persistent bash session with Popen |
| `agent/tools.py` | MODIFY | Add rg integration, truncation, mtime sort |
| `agent/core.py` | MODIFY | Tool→LLM loop (add output to history), session lifecycle |
| `TROUBLESHOOTING.md` | MODIFY | Add ripgrep install instructions, new known issues |
| `tests/test_tool_upgrade.py` | NEW | Functional tests for all 5 steps |
| `plans/2026-03-14_tool-upgrade.md` | THIS FILE | |
