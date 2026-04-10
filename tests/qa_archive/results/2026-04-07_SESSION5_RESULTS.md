# Session 5 Results: Debugging Production Bug (75 turns)

**Date**: 2026-04-07
**Mode**: coding
**Narrative**: Developer debugs the auto-compact context-loss issue. Deep code tracing,
wrong hypotheses, frustration, backtracking.
**Method**: tmux, 8-15s between LLM calls, fresh REPL, no special env vars.
**Session duration**: ~27 min 24s (21:30 - 21:57)

## Execution Summary

| Phase | Turns | Status |
|-------|-------|--------|
| 1. Understanding the bug | 1-15 | Completed |
| 2. Tracing the code path | 16-35 | Completed (with /rewind backtrack) |
| 3. Fix attempt | 36-55 | Completed with infinite-loop issue |
| 4. Verification and wrap-up | 56-75 | Completed (with Ctrl+C recovery) |

Final session state at `/exit`:
- Conversation has 83 messages
- Final context: ~29% (38,361 / 131k tokens)

## Artifacts Produced

- `/tmp/debug_session.md` -- 207,988 chars, 1253 lines
- `/tmp/debug_session.json` -- 229,066 chars
- `/tmp/test_compact_preservation.py` -- 19,289 chars, 658 lines (syntactically
  broken, could not be executed)
- `/tmp/test_final.py` -- attempted rewrite of the test, still broken
- `/tmp/improved_facts.py` -- NEVER actually written (agent claimed to write it,
  then Read returned `File not found`)
- Checkpoints:
  - `debug-start` at 21:34:20
  - `debug-retry` at 21:38:12
  - (`before-fix` was attempted but blocked by permission prompt -- see BUG-S5-001)

## Major Findings

### BUG-S5-001: Permission-prompt input capture (same as BUG-S4-001)
Phase 2 hit the same issue: after tools like Grep/Read prompted for permission, the
user's subsequent messages were captured as prompt input and denied. Observed 10+
denied messages including:
- `搜索 compact 后 session_notes 是否被重新注入`
- `读取 agent/services/session_notes.py 前50行`
- `session_notes 有哪些section？`
- `我要修改 _extract_user_facts 来也提取文件操作记录`
- `/checkpoint before-fix`

This is the **most severe bug** -- it's reproduced across both sessions and can silently
drop a significant fraction of user input.

### BUG-S5-002: Write tool creates file but returns File-not-found on immediate Read
Turn 40: user asked "写到 /tmp/improved_facts.py". Agent's next turn tried to Read it:
```
Read ✗ File not found: /tmp/improved_facts.py
```
The file was never actually created. `ls /tmp/improved_facts.py` post-session confirms
it does not exist on disk. The agent's Write claim was phantom -- no visible error but
nothing written.

### BUG-S5-003: Agent stuck in infinite loop trying to fix indentation
Between turns 55-58, the agent attempted to write a Python test file to
`/tmp/test_compact_preservation.py`. The file was written with broken indentation
(Chinese wide spaces and no newlines between statements, e.g. `"""消息模型"""` then
`role: MessageRole` on next line). Agent then attempted to fix the indentation through
a repeated loop: Read → "确实有缩进问题。让我重新创建一个正确的版本" → Write → Bash
run → Exit code 1 → repeat. The loop ran for **several minutes** and repeated nearly
identical messages (visible in the log as `让我直接查看文件的具体内容，看看缩进到底是
什么问题：让我直接查看文件的具体内容，看看缩进到底是什么问题：让我直接查看文件的具体内容，
看看缩进到底是什么问题：` -- the exact same sentence repeated 4 times, suggesting the
LLM is being re-invoked without advancing state).

Required two Ctrl+C interruptions (`[Agent loop interrupted]` observed twice in log) to
break out. After interruption, turn count was at 75msg/conversation already, which
suggests the agent burned dozens of LLM calls inside this loop without user-visible
progress.

**Root cause (probable)**: Code generation is emitting Python with Unicode full-width
spaces / missing newlines, and each successive "fix" reproduces the same broken output
because the prompt does not include the specific failure mode, only "fix indentation".

### BUG-S5-004: Assistant message repetition (no-progress loop indicator)
Related to above but worth calling out separately. Example log lines:
```
现在运行最终的测试文件：现在运行最终的测试文件：现在运行最终的测试文件：现在运行最终的测试文件：
让我直接查看文件...：让我直接查看文件...：让我直接查看文件...：让我直接查看文件...：
```
This pattern (identical assistant text chained with no separator) appears to be a
streaming or buffering bug in the TUI, where the same token stream is printed multiple
times when the LLM retries without a clear turn boundary. It's visually confusing and
could mislead users into thinking the agent is making progress.

### BUG-S5-005: `/rewind debug-start` restored 24 turns back
Expected behavior but worth logging. User backtracked hypothesis after the
"etc, I've gone the wrong direction" turn. `/rewind debug-start` reported:
```
✓ Restored checkpoint: debug-start (24 turns)
```
The subsequent checkpoint `debug-retry` was saved cleanly, and the agent correctly
resumed from the new line of investigation.

### BUG-S5-006: Python vs python3 mismatch in agent Bash tool
Agent tried to run `python test_compact_preservation.py` which failed with exit code
127 ("python not found"). Agent self-corrected on next attempt with `python3`. This
is a minor issue but worth noting the agent doesn't default to `python3` on macOS.

### BUG-S5-007: HIGH-risk Bash always requires confirmation even for /tmp
`cd /tmp && python test_compact_preservation.py` was flagged HIGH risk and required
`[y]es/[n]o/[a]lways` confirmation. For a /tmp script on an already-sandboxed path,
this seems over-eager.

## Debug Narrative Reconstruction

Despite the bugs above, the agent did produce a substantive debug narrative:

1. **Phase 1 hypothesis**: compact loses file modification history via
   `_extract_user_facts` only extracting name/preferences.
2. **Phase 2 backtrack**: user realized the problem isn't in session_notes but in
   conversation_history truncation. `/rewind debug-start` to reset.
3. **Phase 2 retrace**: traced `/compact` command flow: `_cmd_compact` →
   `CommandResult(compact=True)` → `compact_now()` → `micro_compact()` in
   `context_collapse.py`. Correctly identified that compact collapses to summary
   message, dropping tool_result content.
4. **Phase 3 design**: proposed a 4-layer preservation policy (MUST_KEEP / PREFER_KEEP
   / COMPRESSIBLE / DISCARDABLE) and importance scoring with recency bonus.
5. **Phase 3 implementation**: attempted to write test file, fell into the loop from
   BUG-S5-003.
6. **Phase 4 recovery**: after Ctrl+C, user got summary, `/doctor`, `/flags`, `/stats`,
   and PR description. All ran cleanly.

## Working Features (Verified)

- `/checkpoint` with multiple labels worked (debug-start, debug-retry)
- `/rewind <label>` correctly restored 24-turn-earlier state
- `/think on`/`off` toggled
- `/brief on`/`off` toggled (though `/brief` commands also got consumed by the
  permission prompt glitch)
- `/compact` executed cleanly and the agent's post-compact recall was correct
  ("记得！" -- it did remember the bug being debugged)
- `/save /tmp/debug_session.md` saved 183,041 chars successfully
- `/save /tmp/debug_session.json` saved 202,669 chars successfully
- `/history` reported `Conversation has 83 messages`
- `/doctor`, `/flags`, `/stats`, `/cost`, `/context` all returned clean output
- `/dream` triggered without error

## Context Management

- Starting context: 5% (6,338 tokens)
- Pre-compact (turn 47): ~29% (38,361 tokens)
- Post-compact recall: confirmed working ("compact后还记得我在debug什么bug吗？" →
  "记得！")
- Final context at /exit: 29% -- conversation did not hit auto-compact threshold

## Recommendations (Ranked)

1. **Fix the permission-prompt input capture** (shared with Session 4) -- P0.
2. **Guard against no-progress loops** -- detect repeated nearly-identical assistant
   outputs and break the loop with a user prompt (BUG-S5-003/004). P0.
3. **Phantom Write detection** -- post-write, verify file exists and has expected
   byte count; raise loud error if not (BUG-S5-002). P1.
4. **Better code generation prompting** -- the Python code generation is outputting
   broken Unicode/indentation. Needs a code-aware formatter pass or a retry budget
   cap. P1.
5. **Default to `python3`** on macOS (BUG-S5-006). P2.
6. **Risk assessment tuning** -- /tmp path Bash commands don't need HIGH (BUG-S5-007). P2.
7. **Streaming de-dup in TUI** (BUG-S5-004). P2.

## Summary

The bug-narrative portion of the session completed successfully -- the agent correctly
diagnosed the compact context-loss issue and proposed a preservation-policy fix. However,
the **debugging session itself exposed more bugs than it fixed**:
- 1 critical input-routing bug (permission prompt consumption)
- 1 critical infinite-loop bug in code generation
- 1 phantom-write bug
- 4 minor UX/ergonomics bugs

The irony is strong: a debug-agent-debugging-agent session found that the agent has a
context-loss bug (the intended target) AND that the agent also has file-write,
permission-dialog, and infinite-loop bugs that weren't on the radar at session start.
