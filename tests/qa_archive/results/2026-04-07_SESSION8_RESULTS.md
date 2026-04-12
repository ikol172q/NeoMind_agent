# Session 8 Results — Multi-Agent Team Task (55 turns, coding mode)

**Date:** 2026-04-07
**Tester:** TESTER agent (tmux, 8s pacing, fresh REPL)
**Mode:** coding (deepseek-chat, think on)
**Plan:** 55 turns; Multi-agent team workflow (search subsystem refactor)
**Transcript:** /tmp/s8_full.txt (698 lines captured)

## Summary

Session executed all 55 planned turns to completion. Most slash commands worked,
but the LLM's tool-calling pipeline is fundamentally broken with deepseek for
this scenario: the model emits XML `<tool_call>...</tool_call>` tags but the
parser fails on every single one of them, so almost no real tool calls were
issued. The agent then "answers from imagination," producing fabricated content.

## Pass / Fail Counts

- Slash commands attempted: 24
- Slash commands working as expected: 19 (`/help`, `/flags`, `/team create|list|info|delete`, `/checkpoint x6`, `/save md/json`, `/dream`, `/stats`, `/cost`, `/context x2`, `/doctor`, `/history`)
- Slash commands BROKEN/INVERTED: 2 (`/think on` showed "Thinking mode: OFF", `/think off` showed "Thinking mode: ON")
- Tool-call attempts (Bash/Read/Grep/LS via XML): ~20 — **all failed to parse**
- Conversational turns (free text → fabricated answers): ~28

## Key Findings

### F1 — Tool-call parser fails 100% for deepseek XML output  [SEVERITY: BLOCKER]
deepseek-chat consistently emits the documented format:
```
<tool_call>
<tool>Bash</tool>
<params>{"command": "..."}</params>
</tool_call>
```
Every single one was rejected with `[agentic] PARSE FAILED full output (...)`
followed by `tool_call tag present but PARSE FAILED`. None of the file reads,
greps, or finds requested by the user were ever executed in S8. The agent then
either produced "(Agent executed tools but produced no visible summary)" or
returned fabricated WebSearch results that had nothing to do with the question
(e.g., "list agent/search/" returned California State Workers info).

### F2 — `/think on` and `/think off` are inverted
- After `/think on` the status line shows `Thinking mode: OFF`.
- After `/think off` the status line shows `Thinking mode: ON`.
- Status bar at bottom still showed `think:on` throughout.

### F3 — `/team` is essentially a name registry
`/team create`, `list`, `info`, `delete` succeed at storing/listing names but
there is no observable orchestration happening. No worker agents, no message
passing, no scratchpad output. `/team info search_refactor` only shows
"Members: neomind (blue)" — i.e. only the leader. After enabling
`COORDINATOR_MODE` and creating a team, behavior was identical to single-agent.

### F4 — Pre-existing leaked teams from prior sessions
`/team list` showed stale entries from previous test sessions:
`dup-test`, `"Research`, `duplicate-test`, `devteam`. The malformed
`"Research` entry (literal leading double-quote) suggests prior input was not
sanitized when stored.

### F5 — `/cost` always reports zero
`/cost` reported `Session cost: $0.0000 / Tokens: 0 in / 0 out / Context usage: 0%`
even after 19+ LLM-driven turns. Token accounting is not wired up for
deepseek provider.

### F6 — `/stats` and `/context` disagree
- `/stats`: "Turns: 19, Messages: 47, ~6,413 tokens"
- `/context`: same numbers but at end of session bottom bar shows `11% 14,806/131k`
- The 14k/131k is likely the accurate inflight count; the 6.4k underreports.

### F7 — Search fallback masquerades as Bash output
When Bash tool calls fail to parse, the agent appears to fall back to a web
search tool that returns generic Chinese SEO content (e.g., for `find agent/
-name "*search*"` it returned only `1. agent/ -name "*search*" -type f` —
literally echoing the command as a search hit). This is misleading: the user
sees "results" but they are unrelated.

### F8 — `/save` works for md and json
Both `/save /tmp/migration_plan.md` (5,993 chars) and
`/save /tmp/team_session.json` (10,518 chars) succeeded.

### F9 — `/checkpoint` works reliably
All 4 checkpoints saved successfully under `~/.neomind/checkpoints/`.

### F10 — `/doctor` healthy
All services up, 11/15 flags enabled, sandbox available, vault present.
One warning: `SharedMemory unavailable`.

### F11 — `/help team` lacks detail
Only shows the one-line `/team — Manage agent teams (swarm)`; no usage info.

## Verdict

**Coding-mode tool execution path is broken end-to-end for deepseek.**
Slash commands work; conversational answers happen; but the agentic loop
cannot run a single tool. This makes the "multi-agent team" feature
indistinguishable from solo chat with no file access. /think toggle is
inverted. /cost is zero. /team has no orchestration. Otherwise stable —
no crashes, no hangs, all 55 turns processed.
