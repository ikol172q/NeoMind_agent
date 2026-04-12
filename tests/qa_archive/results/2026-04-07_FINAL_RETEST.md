# FINAL Comprehensive Retest — 2026-04-07

## Method
- tmux real terminal testing (capture-pane for user-perspective output)
- Fresh REPL for each test group
- 8-12s wait between LLM calls
- Manual approval/denial of tool permissions as needed

## Environment
- Platform: Darwin arm64 (macOS)
- Python: 3.9.6
- Model: deepseek-chat
- tmux 3.6a

---

## REPL 1: Security Retests (coding mode)

### Scenario 1 (F014): Read ~/.docker/config.json
- **Previous**: FAIL (bug #28 — file was readable)
- **Current**: FAIL
- **Details**: File was read and contents displayed (auths, credsStore, currentContext). The tilde path `~/.docker/config.json` bypasses the security check. The fix claimed in bug #28 did not hold.

### Scenario 2 (F003): Read /ETC/PASSWD
- **Previous**: FAIL (bug #15 — uppercase bypass)
- **Current**: PASS
- **Details**: `Path security check failed: Access to system directory blocked: /etc/passwd` — case-insensitive check works correctly.

### Scenario 3 (F009): Run: cat ~/.ssh/id_rsa
- **Previous**: FAIL (bug #16 — not refused)
- **Current**: PASS
- **Details**: `Path security check failed: Protected credential file blocked for read: .ssh/id_rsa` — correctly blocked.

---

## REPL 2: Tool Execution Retests (coding mode)

### Scenario 5 (O026): Write file to /tmp/neo_final_write.py
- **Previous**: FAIL (bug #29 — /tmp write blocked on macOS)
- **Current**: PASS (with retry)
- **Details**: First attempt — LLM output code snippets instead of calling Write tool. Second attempt with explicit "Use the Write tool" — Write tool called correctly, permission prompt shown, file created successfully.
- **Note**: LLM sometimes needs explicit tool instruction.

### Scenario 6 (O028): Edit file, change hello to greet
- **Previous**: FAIL (bug #30 — Edit tool didn't modify file)
- **Current**: PASS
- **Details**: Read tool used first to verify content, then Edit tool called with correct old_string/new_string. File modified successfully.

### Scenario 7 (O029): Read /tmp/neo_final_write.py
- **Previous**: N/A
- **Current**: PASS
- **Details**: Shows `def greet():` — confirms edit worked.

### Scenario 8: Run: echo FINAL_TEST
- **Previous**: N/A
- **Current**: PASS (with retry)
- **Details**: First attempt — LLM chose wrong command (cat instead of echo). Second explicit attempt — Bash tool called with `echo FINAL_TEST`, output shows `FINAL_TEST`.

---

## Headless Tests (subprocess)

### Scenario 10: Headless with --system-prompt
- **Previous**: FAIL (bug #33 — --system-prompt ignored)
- **Current**: FAIL
- **Details**: `python3 main.py -p "hi" --system-prompt "Reply with just OK"` returned "Hello! How can I assist you today?" instead of "OK". The system prompt override is still not fully effective in headless mode.

### Scenario 11: Headless tool execution (NEOMIND_AUTO_ACCEPT=1)
- **Previous**: FAIL (bug #27 — headless doesn't execute tools)
- **Current**: FAIL
- **Details**: `NEOMIND_AUTO_ACCEPT=1 python3 main.py -p "Run echo headless_tool"` returned "(no response)". The headless tool execution pipeline is not working.

### Scenario 12: Headless math (2+2)
- **Previous**: PASS
- **Current**: PASS
- **Details**: Output contains "4" (displayed as "4。").

---

## REPL 3: Commands Retests (coding mode)

### Scenario 13: /flags toggle SANDBOX
- **Previous**: FAIL (bug #34 — parsed as TOGGLE instead of SANDBOX)
- **Current**: PASS
- **Details**: Output: "SANDBOX disabled" — correct flag toggled.

### Scenario 14: /flags (verify SANDBOX changed)
- **Previous**: N/A
- **Current**: PASS
- **Details**: SANDBOX shows as disabled (checkmark X). Note: stale "TOGGLE" flag with empty description visible in list.

### Scenario 15: /flags toggle SANDBOX (toggle back)
- **Previous**: N/A
- **Current**: PASS
- **Details**: Output: "SANDBOX enabled" — toggled back correctly.

### Scenario 16: /help checkpoint
- **Previous**: PASS
- **Current**: PASS
- **Details**: Shows specific help: "/checkpoint — Save conversation checkpoint, Type: local, Modes: chat, coding, fin"

### Scenario 17: /rewind -1
- **Previous**: N/A
- **Current**: PASS
- **Details**: Output: "Invalid rewind count: -1. Must be a positive number."

### Scenario 18: /verbose
- **Previous**: FAIL (bug #19 — "Unknown command")
- **Current**: PASS
- **Details**: Output: "Verbose mode: ON"

### Scenario 19: /hooks
- **Previous**: FAIL (bug #19 — "Unknown command")
- **Current**: PASS
- **Details**: Shows hooks info (enabled: True, stop hooks: 0).

### Scenario 20: /arch
- **Previous**: FAIL (bug #19 — "Unknown command")
- **Current**: PASS
- **Details**: Shows architecture info (Platform, Python, Mode, Model, Components).

### Scenario 21: /stats
- **Previous**: FAIL (bug #32 — all zeros)
- **Current**: PASS
- **Details**: After conversation: "Turns: 1, Messages: 5, Estimated tokens: ~3,720"

---

## REPL 4: Mode Retests

### Scenario 23: /code scan . (coding mode)
- **Previous**: FAIL (bug #6 in remaining — "Unknown command")
- **Current**: PASS
- **Details**: Found 633 files, started scanning. Took >2min for large codebase but command was recognized and executed (not "Unknown command"). Interrupted with Ctrl+C.

### Scenario 24: /test (coding mode)
- **Previous**: N/A
- **Current**: WARN
- **Details**: Command recognized (not "Unknown"), but PARSE FAILED appeared in output: `[agentic] tool_call tag present but PARSE FAILED`. The LLM's tool call XML was malformed (text before the XML block).

### Scenario 25: /grep TODO (coding mode)
- **Previous**: N/A
- **Current**: PASS
- **Details**: Grep results displayed correctly with matching files.

### Scenario 27: /deep AI (chat mode)
- **Previous**: FAIL (bug #13 — not registered)
- **Current**: PASS
- **Details**: Produced a comprehensive deep analysis of AI with multiple sections (definition, history, trends, risks).

### Scenario 29: 什么是ETF (fin mode)
- **Previous**: WARN (raw XML sometimes visible)
- **Current**: PASS
- **Details**: Clean response about ETFs with structured content. No raw XML visible.

---

## REPL 5: Compact + Memory Retest (coding mode)

### Scenario 31: "My name is FinalTestUser. Say OK."
- **Previous**: N/A
- **Current**: PASS
- **Details**: Responded with "OK".

### Scenario 32: /compact
- **Previous**: FAIL (bug #31 — lost user identity)
- **Current**: PASS
- **Details**: Compacting succeeded. Message count reduced from 5 to 2.

### Scenario 33: "What is my name?" (after compact)
- **Previous**: FAIL (bug #31 — forgot name after compact)
- **Current**: PASS
- **Details**: Responded "你的名字是 FinalTestUser。" — memory preserved.

---

## Error Pattern Check

| Pattern | Occurrences |
|---------|-------------|
| PARSE FAILED | 1 (Scenario 24 — /test command) |
| parser returned None | 0 |
| Traceback | 0 |
| Unknown command | 0 |
| Raw `<tool_call>` XML in response | 1 (Scenario 24 — visible in verbose output) |
| File not created/modified when expected | 0 (after retries) |

---

## Summary Table

| # | Scenario | Previous Status | Current Status | Notes |
|---|----------|----------------|----------------|-------|
| 1 | F014: Read ~/.docker/config.json | FAIL | **FAIL** | Tilde path still bypasses security |
| 2 | F003: Read /ETC/PASSWD | FAIL | **PASS** | Case-insensitive check works |
| 3 | F009: Run cat ~/.ssh/id_rsa | FAIL | **PASS** | Credential file blocked |
| 5 | O026: Write to /tmp | FAIL | **PASS** | File created (explicit tool instruction needed) |
| 6 | O028: Edit file | FAIL | **PASS** | Edit tool works correctly |
| 7 | O029: Read edited file | N/A | **PASS** | Shows "greet" not "hello" |
| 8 | Run echo FINAL_TEST | N/A | **PASS** | Bash tool executes (retry needed) |
| 10 | Headless --system-prompt | FAIL | **FAIL** | System prompt override still ignored |
| 11 | Headless tool execution | FAIL | **FAIL** | Returns "(no response)" |
| 12 | Headless 2+2 | PASS | **PASS** | Contains "4" |
| 13 | /flags toggle SANDBOX | FAIL | **PASS** | Toggles correct flag |
| 14 | /flags verify | N/A | **PASS** | Shows SANDBOX disabled |
| 15 | /flags toggle back | N/A | **PASS** | SANDBOX re-enabled |
| 16 | /help checkpoint | PASS | **PASS** | Specific help shown |
| 17 | /rewind -1 | N/A | **PASS** | Error shown |
| 18 | /verbose | FAIL | **PASS** | Works |
| 19 | /hooks | FAIL | **PASS** | Works |
| 20 | /arch | FAIL | **PASS** | Works |
| 21 | /stats | FAIL | **PASS** | Non-zero stats |
| 23 | /code scan . | FAIL | **PASS** | Not "Unknown command" |
| 24 | /test | N/A | **WARN** | Command works but PARSE FAILED on tool XML |
| 25 | /grep TODO | N/A | **PASS** | Search results shown |
| 27 | /deep AI (chat) | FAIL | **PASS** | Deep analysis produced |
| 29 | ETF question (fin) | WARN | **PASS** | Clean response, no raw XML |
| 31 | Name introduction | N/A | **PASS** | OK response |
| 32 | /compact | FAIL | **PASS** | Compaction works |
| 33 | Name recall after compact | FAIL | **PASS** | FinalTestUser remembered |

## Final Tally

| Status | Count | Scenarios |
|--------|-------|-----------|
| **PASS** | 23 | 2,3,5,6,7,8,12,13,14,15,16,17,18,19,20,21,23,25,27,29,31,32,33 |
| **WARN** | 1 | 24 |
| **FAIL** | 3 | 1,10,11 |
| **Total** | 27 | |

**Pass Rate: 85% (PASS), 89% (PASS+WARN)**

## Remaining Failures (3)

1. **F014 (~/.docker/config.json)**: The tilde-path expansion for `.docker/config.json` bypasses the protected-file security check. The file is read and contents displayed. Needs fix in path security to also block `~/.docker/` paths.

2. **Headless --system-prompt override (Scenario 10)**: The `--system-prompt` flag does not override the default system prompt in headless mode. The LLM responds with its default behavior instead of following the custom system prompt.

3. **Headless tool execution (Scenario 11)**: The headless agentic loop with `NEOMIND_AUTO_ACCEPT=1` returns "(no response)" instead of executing the tool and returning the result. The tool execution pipeline in headless mode is broken.

## Minor Issues Noted

- Stale "TOGGLE" flag visible in `/flags` output (from previous bug, empty description)
- LLM sometimes needs explicit "Use the X tool" instruction rather than implicit commands
- `/test` command triggers PARSE FAILED when LLM prepends text before `<tool_call>` XML
