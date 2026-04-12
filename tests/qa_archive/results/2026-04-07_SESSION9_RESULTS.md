# Session 9 Results — Session Persistence Stress Test (100 turns, coding mode)

**Date:** 2026-04-07
**Tester:** TESTER agent (tmux, 8s pacing, fresh REPL)
**Mode:** coding (deepseek-chat, think on)
**Plan:** 100 turns; recall, checkpoint/rewind, save/load, compact, mode switch
**Transcript:** /tmp/s9_full.txt (1,286 lines)

## Summary

Session executed all 100 planned turns. Many bash-based turns were blocked
behind permission prompts that sit forever waiting for `y/n/a`; the next
queued user input was consumed as the answer (yielding "Denied"), so a
substantial fraction of test turns produced no real action. Native tool
calls (Read) worked when the agent chose them; Bash always required prompts.
Phoenix-42 codeword recall worked early, then **the model hallucinated a
completely different "test codeword" set** as the conversation grew. /compact
catastrophically truncated history. /load failed.

## Pass / Fail Counts

- Slash commands attempted: ~50
- Working: `/checkpoint` x10 (all saved), `/context` x8, `/save md/json` (md
  ok, json sometimes ok), `/dream`, `/stats`, `/cost`, `/flags`, `/doctor`,
  `/permissions`, `/rules`, `/transcript`, `/skills`, `/style`, `/clear`,
  `/compact`, `/history`, `/mode chat ↔ coding`
- Broken: `/load /tmp/persistence_test.json` → "File not found" (the file
  was never created because the corresponding `/save` was overwritten by
  permission-prompt fallout); `/rewind init` → "Checkpoint 'init' not found"
  (the very first /checkpoint was queued as a permission denial answer
  instead of being executed)

## Key Findings

### F1 — Permission prompts swallow the next user input  [SEVERITY: HIGH]
Every HIGH/MEDIUM-risk Bash invocation pops a `Allow? [y]es/[n]o/[a]lways:`
prompt. The tmux send-keys script's next line is then consumed as the
answer, which is interpreted as "anything not y/n/a → Denied". This
cascades: the user's _next intended_ command is also lost (it just becomes
the denial token). Effect: roughly 30% of S9 turns produced no real work.
There is no `--yes`/`--auto-approve`/non-interactive mode visible in the
help.

### F2 — Codeword recall: early PASS, late HALLUCINATION  [SEVERITY: HIGH]
- Turn 11 ("测试代号是什么？"): correctly answered **Phoenix-42**.
- Turn 17 ("测试代号还记得吗？"): correctly answered **Phoenix-42**.
- Turn 36 (after several reads): the agent **fabricated** four totally
  unrelated codewords:
  > "Micro-compact, Full compact, Recovery message, Surface error"
  and presented them as the "test codenames" with confident specificity.
  These names actually come from `agent/agentic/error_recovery.py` which
  the model had pulled into context — it confused vault/file content with
  the user's session memory.
- Turn 40 ("新代号：Phoenix-43"): acknowledged.
- Turn 47 (after `/load`): again produced the hallucinated 4-name list
  instead of Phoenix-42 or Phoenix-43.

### F3 — `/compact` is destructive
After `/compact` near turn 69:
- `/stats` → `Turns: 0, Messages: 1, ~2,133 tokens`
- `/history` → `Conversation has 1 messages.`
The compact operation effectively wiped the conversation rather than
summarizing it. Subsequent recall questions had no context to draw on.

### F4 — `/save` survives, but `/save .json` after permission cascade left no file
`/save /tmp/persistence_test.md` (saved early, succeeded).
`/save /tmp/persistence_test.json` was queued at a moment when a permission
prompt was active and the slash command was consumed as the denial answer
— the file was never written. Later `/load /tmp/persistence_test.json`
returned `File not found`. This is a state-machine bug: slash commands
should not be eaten by permission prompts.

### F5 — `/rewind init` failed
`Checkpoint 'init' not found.` The original `/checkpoint init` (turn 2)
was eaten by the permission prompt for the LLM's `find` call. Confirms F1.

### F6 — `/clear` correctly wiped, `/checkpoint after-clear` saved
After `/clear`, `/history` showed 0 messages (correct), then a new
checkpoint saved. The agent claimed "AutoDream remembers across /clear"
which is technically true (separate store) but irrelevant to the test.

### F7 — Mode switch preserves context
`/mode chat` → `/mode coding` round-trip preserved messages
(verified by `/context` before/after).

### F8 — `/save` HTML format works
`/save /tmp/persistence_test.html` succeeded.

### F9 — `/load /tmp/persistence_test.json` failure root-caused
File simply never existed. /load reports clean error message — good UX.

### F10 — `/cost` always zero
Same as S8: token accounting not wired for deepseek provider.

### F11 — Read tool worked natively (no permission prompt)
Native `Read` tool calls succeeded for `README.md`, `agent/core.py`,
`agent/cli_command_system.py`, `pyproject.toml`, `agent/config/*.yaml`.
The model chooses Read for some files and Bash (+permission cascade)
for others; routing is inconsistent.

### F12 — XML parser failure also occurred in S9
Same `<tool_call>` parse failure pattern as S8 appeared on several turns
(LS, Read with offset/limit). Inconsistent: sometimes the model emits the
correct native call, sometimes the broken XML form.

### F13 — `/transcript`, `/skills`, `/permissions`, `/rules`, `/style` all run
- `/transcript` dumps full system prompt + history.
- `/skills` lists 25+ skills with descriptions.
- `/permissions` shows `normal`.
- `/rules` shows none defined, prints usage.
- `/style` reports no styles found.

### F14 — Status bar token counter drifts
Bottom bar shows `18% 23,406/131k` while `/context` shows `1% 2,255/128k`
after compact. Two independent token counters disagree.

### F15 — All 11 checkpoints saved successfully across the session
Checkpoint system itself is solid; failures are upstream queuing problems.

## Verdict

**Persistence subsystem is fragile under realistic stress.** Three
independent failure modes (permission-prompt-eats-input, /compact wipes,
codeword hallucination from in-context file content) compound to make
session memory untrustworthy across more than ~30 turns. Checkpoint
save/restore individually works, but the user-visible round-trip
(save → load → query) does NOT work reliably. /cost still zero.
