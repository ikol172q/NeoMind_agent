# Session 4 Results: Cross-Mode Research (90 turns target, 80 executed)

**Date**: 2026-04-07
**Mode**: chat + coding (mixed)
**Narrative**: Researcher compares NeoMind with Claude Code leaked source, brainstorming in chat then switching to coding for code analysis.
**Method**: tmux, 8-12s between LLM calls, fresh REPL, no special env vars.
**Session duration**: ~19 min 50s (21:10 - 21:30)

## Execution Summary

| Phase | Turns | Status |
|-------|-------|--------|
| 1. Brainstorming in chat mode | 1-15 | Completed |
| 2. Claude Code comparison | 16-35 | Completed with issues (see below) |
| 3. Deep analysis | 36-60 | Completed |
| 4. Report generation | 61-80 | Completed with issues (rewind behavior) |
| 5. Bonus | 81-90 | Skipped (task description allowed skip) |

Final session state at `/exit`:
- Turns: 8 (after `/rewind`)
- Messages: 20 (user: 8, assistant: 7, tool: 0)
- Tokens: ~3,387 (2% of 128k context)

## Artifacts Produced

- `/tmp/research_report.md` -- 44,110 chars, 473 lines
- `/tmp/research_report.html` -- 47,441 chars
- Multiple checkpoints saved to `~/.neomind/checkpoints/`
  - `研究计划制定` at 21:16:16
  - `工具系统对比` at 21:17:33

## Major Findings

### BUG-S4-001: Permission-prompt input capture blocks subsequent commands (CRITICAL UX)
During Phase 2, after user issued `/compact`, a permission confirmation dialog appeared
(`Allow? [y]es / [n]o / [a]lways:`). Every subsequent line the user typed -- including
natural-language queries and other slash commands -- was interpreted as input to the
permission prompt, rather than as a new message. Those messages were all silently denied
(`⊘ Denied`). Observed 9+ consecutive user messages denied this way:

```
Allow? [y]es / [n]o / [a]lways: /compact                  ⊘ Denied
Allow? [y]es / [n]o / [a]lways: compact之后还记得我在研究什么吗？  ⊘ Denied
Allow? [y]es / [n]o / [a]lways: 继续。现在看session管理       ⊘ Denied
Allow? [y]es / [n]o / [a]lways: 搜索NeoMind里所有跟session...  ⊘ Denied
...
```
This means a significant portion of Phase 2 (turns 26-35) didn't reach the LLM at all.
Only once a new tool invocation was triggered (by a turn that happened to bypass the
stuck state) did the UI recover. The user has no way to know the prompt is still active
(status bar is hidden during confirmation).

**Repro**: `/compact` or any HIGH-risk tool. User types subsequent messages. All denied.
**Impact**: Silent data loss of user intent; session effectively stalls.
**Recommended fix**: Permission dialog should consume exactly one input line, not linger;
or the prompt should be visually reinforced and any non-{y,n,a} input should be treated
as a new chat message.

### BUG-S4-002: Read tool fails on offset=str parameter
```
Read ✗ Invalid params: Parameter 'offset' must be integer, got str
```
Triggered at turns requesting "前50行" -- LLM attempted to pass `offset="0"` (string).
Occurred twice. The tool parser needs lenient int-coercion or the schema docstring
should be more explicit.

### BUG-S4-003: WebSearchTool missing execute method
```
WebSearch ✗ WebSearch error: 'WebSearchTool' object has no attribute 'execute'
```
WebSearch tool invocation crashed. The tool class appears not to implement the standard
execute interface. This blocked Phase 2 comparison turns that tried to find Claude Code
public docs via search.

### BUG-S4-004: Agentic tool_call parse failure (non-fatal)
```
[agentic] tool_call tag present but PARSE FAILED. Snippet: <tool_call>
<tool>Bash</tool>
<params>
{"command": "wc -l /tmp/research_report.md", "timeout":10}
</params>
</tool_call>
(Agent executed tools but produced no visible summary)
```
The XML-style tool call format was emitted by the LLM but not parsed by the agentic
parser. Occurred during turn 72. The fallback "no visible summary" message is
user-confusing.

### BUG-S4-005: `/rewind` with label rewinds too aggressively
User issued `/rewind 所有维度对比完成` at turn 74 expecting to return to that
checkpoint. System responded `Restored checkpoint: 所有维度对比完成 (7 turns)` --
collapsing a 60+ turn conversation back to 7 turns. While this may be intended behavior,
it's surprising given that the checkpoint was created *late* in the session (turn 59),
not early. Suggests the checkpoint's turn count is counted relative to the new
conversation-history length after pruning, not total turns.

Post-rewind `/stats` showed Turns: 8, Messages: 20. The user's final "总结今天的研究工作"
summary was generated from only these 8 turns, losing the bulk of the research context.

### BUG-S4-006: Queued commands leak into next message input
After `/rewind`, the user's next several commands (`/stats`, `/cost`, `总结今天的研究工作`,
`/exit`) were queued but visible as literal text inside a still-processing message:
```
> rewind之后还记得什么？
⠋ Thinking…/stats
/cost
总结今天的研究工作
/exit
```
They did eventually get processed, but their ordering is not deterministic and they
appeared to be part of the previous message.

## Working Features (Verified)

- Mode switching (`/mode chat`, `/mode coding`) worked correctly each time
- `/brainstorm`, `/deep`, `/compare`, `/draft` all produced rich, coherent outputs
- `/checkpoint` with Chinese labels saved successfully
- `/think on`/`/think off` toggled correctly; think time visible as `Thought for X.Ys`
- `/context`, `/stats`, `/cost` returned formatted output
- `/flags` listed feature flags cleanly (SESSION_CHECKPOINT, VOICE_INPUT, etc.)
- `/save /tmp/research_report.md` and `.html` both succeeded (~44K and ~47K chars)
- `/compact` executed (size dropped to 1 msg in Phase 3)
- `/dream` returned (trigger gates observed: >30min, >3 mentions, idle)
- Chinese input processed correctly throughout
- Coding-mode tool listing showed 52 tools on startup
- Grep, Read, Glob operated normally on NeoMind's own source when offset/limit were int

## Not-Found / Expected Empty Results

- `<reference_repos>/` did **not** exist on the
  machine. This was handled gracefully by NeoMind -- search tools simply returned no
  results, and the LLM pivoted to "推测" (speculative) analysis rather than crashing.
  The resulting comparison report is thus based on NeoMind source + LLM prior knowledge
  of Claude Code, not side-by-side code reading.

## Context Management Observations

- First `/compact` (turn 26, after ~25 turns of heavy reads) went through the permission
  prompt path (see BUG-S4-001).
- Second `/compact` (turn 50) succeeded and reduced msg count. Post-compact the agent
  correctly recalled "NeoMind vs Claude Code architecture research" when asked.
- Auto-compact threshold was not visibly triggered during this session (max observed
  context: 29% @ ~38k tokens, below the 80% threshold).

## Recommendations

1. **Fix BUG-S4-001 (permission prompt)** -- this is the single biggest UX issue. It
   caused silent loss of ~9 user turns and likely corrupts many real user sessions.
2. Fix Read parameter coercion (BUG-S4-002).
3. Implement or remove WebSearchTool.execute (BUG-S4-003).
4. Tighten XML tool_call parser or switch to JSON-only (BUG-S4-004).
5. Clarify `/rewind` semantics -- show a confirmation with "rewinding N turns, you
   will lose X messages" (BUG-S4-005).
6. Fix command queuing during thinking animation (BUG-S4-006).
