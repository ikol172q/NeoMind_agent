# Plan: Agentic UX — Spinner, Thinking, Tool Loop, Display Polish

**Created:** 2026-03-15
**Status:** Done
**Priority:** High — transforms coding mode from "dump commands as text" to real agent loop

---

## Problem Statement

After the mode split and tool upgrade, coding mode had the infrastructure (persistent bash, ripgrep, tool→LLM history) but lacked the UX to feel like an agent. The LLM would output bash code blocks as text and the user had to manually copy-paste them. There was no spinner, no thinking display, no automatic tool execution loop.

| Gap | Claude CLI | ikol1729 (before) | Impact |
|-----|-----------|-------------------|--------|
| Spinner during thinking | Animated spinner with elapsed time | Nothing — blank screen while waiting | User thinks it's frozen |
| Thinking display | Brief summary, expandable | Raw thinking dumped to stdout | Clutters terminal |
| Tool execution loop | Auto-extract + execute + re-prompt | Commands printed as text | User must copy-paste commands |
| Permission model | Ask before running | N/A (no auto-execution) | No safety gate |
| Code block display | Hidden from output | Printed verbatim | Noisy, confusing |

---

## What Was Built

### 1. ANSI Spinner (stderr-based)

Writes spinner frames to `sys.stderr` to avoid Rich's stdout FileProxy recursion bug. Supports dynamic label updates via `_label_ref`.

**Key design decision:** Rich's `Status` widget replaces `sys.stdout` with a `FileProxy`. When `stream_response` calls `print()` while the proxy is still active, infinite `__getattr__` recursion → segfault. Fix: bypass Rich entirely, write spinner to stderr.

**Spinner frames:** `['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']`

### 2. Thinking Display

- Thinking content collected silently (not printed to stdout)
- Spinner updates with brief thinking summary every ~2 seconds
- After thinking completes: `Thought for 3.2s` (one line)
- Full thinking stored in `_thinking_history` for later expansion

### 3. Agentic Tool Execution Loop

When the LLM outputs a ` ```bash ` code block:
1. **Extract** the FIRST non-hallucinated bash block only
2. **Permission** prompt: `│ $ cmd_preview` + `│ Run? [y/n/a]:`
3. **Execute** under spinner (no verbose output — status folded into spinner label)
4. **Feed result** back to conversation history
5. **Re-prompt** LLM to continue (spinner stays running until first content token)
6. **Repeat** until no more code blocks or max iterations reached

**Hallucination detection:** If a bash block is followed by a ` ``` ` block (inline output), it's skipped — the LLM hallucinated both command and output.

**One-at-a-time execution:** Only the FIRST block is extracted per iteration. System prompt updated to instruct "ONE command block, then STOP."

### 4. Code Fence Filter (`_CodeFenceFilter`)

Installed on `chat._content_filter` during streaming in coding mode. Suppresses ` ```bash `, ` ```shell `, ` ```sh `, ` ```console ` fences from stdout while keeping `full_response` intact for the agentic loop. Python and other language blocks pass through.

Handles streaming character-by-character with a 15-char tail buffer for fence detection across chunk boundaries. Strips trailing newlines before a fence opening to prevent blank lines.

### 5. `/transcript` Command

View conversation history with modes: default (last 20), `full`, `N` (last N), `last` (last assistant response).

### 6. `/expand` Command

View thinking content for any turn. Modes: list turns (interactive), `last`, `N` (by number), `all`. Opens in `less -R` pager for ANSI passthrough.

---

## Files Modified

| File | Changes |
|------|---------|
| `cli/claude_interface.py` | Spinner, agentic loop, code fence filter, /transcript, /expand, Ctrl+E binding, permission UI with `│` markers |
| `agent/core.py` | Content filter support in `stream_response`, `content_was_displayed` tracking, thinking display (silent collection + spinner updates + condensed summary), `_thinking_history` storage |
| `agent/config/coding.yaml` | System prompt: ONE command block rule, STYLE (no preamble), use `cat` not `Read`, /transcript and /expand in commands list |
| `agent/config/chat.yaml` | /transcript and /expand in commands list |
| `tests/test_claude_interface.py` | 119 tests total — added: CodeFenceFilter (10), DynamicSpinnerLabel (3), AgenticLoopSpinnerDisplay (2), StreamAndRenderContentFilter (3), plus existing spinner/tool/hallucination/expand/transcript tests |

---

## Key Bugs Fixed

### Rich FileProxy Recursion (Critical)
**Symptom:** `RecursionError: maximum recursion depth exceeded` → segfault
**Cause:** Rich's `Status` replaces `sys.stdout` with `FileProxy`. When spinner thread's `Status.__exit__` hasn't restored stdout yet but `stream_response` calls `print()` → infinite `FileProxy.__getattr__` recursion.
**Fix:** Replaced Rich `Status` with lightweight ANSI spinner on `sys.stderr`.

### LLM Hallucination in Agentic Loop
**Symptom:** LLM generates 13 commands with fake outputs in one response. Loop executes all 13 against real codebase — all fail.
**Fix:** (1) Extract only FIRST block. (2) Detect hallucinated inline output. (3) System prompt: "ONE command block, then STOP."

### `Read` Interpreted as Bash Builtin
**Symptom:** LLM outputs `Read "/path"` which bash interprets as `read` builtin → error.
**Fix:** System prompt updated to use `cat "/path"` instead.

### Blank Lines Between Spinner and Permission Prompt
**Symptom:** Two blank lines between `⠸ Thinking… (3s)` and `│ $ cat ...`
**Fix:** (1) Code fence filter strips trailing newlines before fence. (2) `print()` newline only fires when visible content was displayed. (3) Removed `\n` prefix from "Thought for" line.

---

## Display Flow (Final)

```
> understand '/path/to/file.py'
⠋ Thinking… (3s)
Thought for 1.2s
  │ $ cat "/path/to/file.py"
  │ Run? [y/n/a]: y
⠴ Thinking… import os (5s)
Thought for 2.4s
Here's what the file does: ...
```

- Spinner runs on stderr with elapsed time and thinking/tool status
- "Thought for N.Ns" is one condensed line (expandable via /expand)
- Permission prompt uses `│` markers for visual continuity
- No verbose tool output — status folded into spinner
- No code block text in terminal — filter suppresses it
- No blank line gaps — newlines stripped at filter and print level
