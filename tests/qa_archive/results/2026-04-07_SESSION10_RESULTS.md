# Session 10 Results — Real-World Workday (95 turns, all 3 modes)

**Date:** 2026-04-07
**Tester:** TESTER agent (tmux, 8s pacing, fresh REPL)
**Modes:** chat → coding → fin → coding → fin → chat → coding → chat → coding
**Plan:** 95 turns simulating a full workday across modes
**Transcript:** /tmp/s10_full.txt (1,097 lines)

## Startup warning
On boot, two errors immediately printed before the prompt:
```
Failed to save evolution state: [Errno 2] No such file or directory:
'~/.neomind/evolution/evolution_state.tmp' ->
'~/.neomind/evolution/evolution_state.json'
```
Twice. The evolution directory is missing or the temp-then-rename
write is broken. Non-fatal, but visible to every user.

## Summary

All 95 turns executed. Mode switching works smoothly. Web search works
in chat mode. Slash commands largely work. Same systemic issues as S8/S9:
many Bash invocations blocked by permission prompts (which then ate the
following user turn), tool-parameter type validation rejected several
native tool calls (`num_results`, `extract_text`, `offset` all received
strings instead of int/bool), and several `<tool_call>` XML emissions
failed to parse. Despite all that, the agent produced very high-quality
human-facing summaries and a complete worklog.

## Pass / Fail Highlights

### Working
- Chat-mode WebSearch (`今天大盘涨跌？` returned actual hits)
- `/mode chat ↔ coding ↔ fin` switching (state preserved)
- `/draft 写一段今天的工作日志` produced a full markdown worklog
- `/save md/json/html` all three formats succeeded for `/tmp/full_workday.*`
- `/checkpoint x6` all saved
- `/doctor`, `/flags`, `/permissions`, `/rules`, `/transcript`, `/history`,
  `/stats`, `/context`, `/dream`
- Quant calculation (5y 100→200 → 14.87% CAGR) produced correctly
  **without** any tool — pure LLM math, accurate

### Broken
- `/think on` again shows `Thinking mode: OFF` (inverted, same as S8)
- `/market`, `/stock NVDA`, `/news AI`, `/stock AAPL`, `/quant CAGR 100 200 5`
  all returned `"<cmd> is not available in coding mode."` — fin-mode
  commands are gated by mode AND the test queued them after the agent had
  drifted back to coding via permission-prompt cascade, so almost the
  entire fin-mode segment was lost.
- `/btw 顺便问一下，什么是 microservices？`
  → `(Full /btw support requires quick_query method on agent)` — feature
  stub, not actually implemented.
- WebFetch tool: `'WebFetchTool' object has no attribute 'execute'` —
  hard error.
- Tool parameter validation rejected several native calls:
  `WebSearch num_results must be integer, got str`,
  `WebFetch extract_text must be boolean, got str`,
  `Read offset must be integer, got str`. The model is producing JSON
  with stringified numerics; the tool layer refuses them. (Other AI
  agents typically coerce on input.)
- After 2 identical errors the loop force-wraps: `[agentic] 2 consecutive
  identical errors for WebSearch, forcing wrap-up`. Good safety, bad UX.
- `/cost` always `$0.0000 / Tokens: 0 in / 0 out` (same as S8/S9)
- `/diff` was queued during a permission cascade and consumed as the
  denial answer — never executed
- Multiple `<tool_call>` XML payloads failed to parse (same pattern
  as S8/S9). One especially bad one: a doubly-nested
  `<tool_call><tool_call>...` from the model breaks parsing entirely.
- `/checkpoint end-of-day` command was eaten by a permission prompt
  earlier (recovered later by `/checkpoint workday-end`)

## Mode-by-mode breakdown

### Morning (chat mode → coding)
- WebSearch in chat actually worked but the model emitted `<tool_call>`
  XML that failed to parse on the first attempt; second attempt
  re-emitted the same broken XML.
- `/deep` ran but its answer is just a normal LLM response (no obvious
  multi-source research happening).
- `/doctor` healthy except `SharedMemory unavailable`.
- TODO search: `Grep` tool worked natively and returned 50 matches
  (truncated). User then asked to drill into "the first TODO" — the
  agent tried Bash, hit permission prompt, lost the next 3 user turns
  to denial cascade.

### Late morning → noon (coding/fin transitions)
- `/mode fin` is currently NOT a real switch — output line said "切换到金融
  模式" but the prompt prefix stayed `>` (coding) and slash commands
  reported "not available in coding mode". So `/mode fin` typed inside
  coding-mode-fallback rendered the user's message without actually
  changing mode. **Real `/mode fin` switching is broken in this build.**
- The test plan included `休息一下。/mode fin` as a single message —
  this was sent as one input string, not as a slash command. The agent
  saw it as plain text. Lesson: `/mode` must be on its own line, but
  this is a usability papercut not a real bug.

### Afternoon (coding)
- `/checkpoint afternoon-start`, `/checkpoint afternoon-mid` saved
  successfully.
- All Bash-based test runs (`pytest`) blocked by permission prompts.
- Native Read tool failed twice with `offset must be integer, got str`.
  The agent blames the tool layer; reasonable suspicion is the model
  emits `"offset": "0"` instead of `"offset": 0`.
- Final `/checkpoint workday-end` saved successfully.

### Evening summary turns (chat mode)
- `/draft` produced a polished work-log markdown doc (8,755 chars)
- `/save /tmp/worklog.md` succeeded
- The closing "what's the coolest feature?" turn produced an extremely
  high-quality, structured marketing-grade summary in <10 seconds.
  The conversational layer is genuinely strong; it's the tool plumbing
  that's broken.

## Cross-Session Repro Tally

| Bug | S8 | S9 | S10 |
|---|---|---|---|
| `<tool_call>` XML parse failure | YES | YES | YES |
| `/think` toggle inverted | YES | n/a | YES |
| `/cost` always $0 | YES | YES | YES |
| Permission prompt eats next input | n/a | YES | YES |
| Pre-existing leaked /team entries | YES | n/a | n/a |
| Tool param type rejection (str vs int/bool) | n/a | n/a | YES |
| Codeword hallucination after long context | n/a | YES | n/a |
| /compact wipes history | n/a | YES | n/a |

## Verdict

Conversational quality is high — summaries, drafts, and reasoning
output are excellent. Operational reliability is poor: tool execution
is gated behind two unreliable layers (an XML parser that fails on
deepseek output, and a permission system that swallows queued user
input). `/cost` reports nothing. fin-mode commands are largely
unreachable in a mixed-mode workday because mode switches are too
fragile to survive the permission-prompt UX. Evolution-state-save
error fires on every boot.
