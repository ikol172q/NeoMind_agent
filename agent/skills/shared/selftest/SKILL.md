---
name: selftest
description: Run NeoMind's tester+fixer self-test loop using a 2-agent team. Tester drives a real tmux REPL; Fixer reads bug reports and patches code. Repeats until clean or budget exhausted.
modes: [coding]
allowed-tools: [Bash, Read, Edit, Write, Grep, Glob, LS]
version: 1.0.0
---

# NeoMind Self-Test (Tester + Fixer Team)

You are the **coordinator** of a 2-agent self-test team. Your mission: discover and fix bugs in NeoMind by running it against itself in a real terminal, using the same fixer+tester pattern that produced the `tests/qa_archive/` archive.

This skill is the executable form of the methodology documented in `<workspace>/docs/SELF_TEST.md` and `tests/qa_archive/README.md`.

## Why this exists

Unit tests miss UI bugs. pexpect-based harnesses with `clean_ansi()` mask the very errors users see. The only reliable way to find user-facing bugs is to **drive a real tmux pty session** like a real user would, capture the rendered output, and never hide errors behind sanitization.

The methodology:
- **Tester** never modifies source code. Only runs tmux, captures output, records PASS/FAIL.
- **Fixer** never runs the REPL. Only reads bug reports, edits source code, runs unit tests.
- **You (the coordinator)** spawn both via the team mailbox, dispatch scenarios to the tester, route bugs to the fixer, and re-run failed scenarios after each fix.

## Workflow

### Phase 1 — Bootstrap the team

```
/team create selftest
```

You become the leader. Add two workers with clearly-defined roles:

- **tester** (color: cyan) — read-only access to source, full tmux control, writes to `~/.neomind/teams/selftest/results/`
- **fixer** (color: yellow) — read+write access to source, runs `pytest`, writes to `~/.neomind/teams/selftest/fixes/`

Open both worker mailboxes via the swarm `Mailbox` API and confirm they reply to a ping before continuing.

### Phase 2 — Pick a test plan

The plan files are stored at `<workspace>/tests/qa_archive/plans/`. Available plans:

| Plan | Scenarios | Wall time | Use when |
|------|-----------|-----------|----------|
| `2026-04-06_REAL_TERMINAL_TEST.md` | 525 short | ~6 hrs | Full feature regression |
| `2026-04-07_LONG_SESSION_PLAN.md` | 10 × 50-100 turns | ~6 hrs | Endurance / context-window |
| `2026-04-08_PROJECT1_PLAN.md` | 210 boundary | ~10 hrs | Real-user keystroke fidelity |

If the user gives a focused scope (e.g., "test all slash commands" or "test the security system"), filter the plan to just those scenario IDs.

For a smoke run, pick **5-10 scenarios** spanning each major feature category — never run the full 525 unless asked.

### Phase 3 — Tester worker prompt

Send this exact briefing to the tester via mailbox:

```
You are the TESTER. NEVER modify source code. Use ONLY tmux for terminal interaction.

REQUIRED METHOD (no exceptions):
  tmux new-session -d -s nm_test -x 120 -y 40
  tmux send-keys -t nm_test "cd <workspace> && PYTHONPATH=. python3 main.py --mode coding" Enter
  sleep 15  # let prompt_toolkit fully draw

  # For each scenario:
  tmux send-keys -t nm_test "<input>" Enter   # text input
  tmux send-keys -t nm_test C-c               # real Ctrl+C
  tmux send-keys -t nm_test Tab BSpace Up     # special keys are real keys
  sleep N                                     # 5s for slash cmds, 25s for LLM
  tmux capture-pane -t nm_test -p -S -30      # what the user actually sees

FORBIDDEN:
  - NEOMIND_DISABLE_VAULT, NEOMIND_DISABLE_MEMORY, NEOMIND_AUTO_ACCEPT
  - clean_ansi() or any sanitization of captured output
  - pexpect, expect, or any harness wrapper
  - assumptions about output — read what the pane actually shows

ERROR PATTERNS TO FLAG (search raw, uncleaned capture):
  - "PARSE FAILED"
  - "parser returned None"
  - "Traceback"
  - "<｜end▁of▁thinking｜>"
  - "Detected simple filename"  (false-positive on Chinese)
  - Content repeated 3+ times
  - Spinner chars after response: ⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏

Restart REPL every 8-10 scenarios to avoid output bleed.
8s sleep between LLM calls to avoid rate limits.

For each scenario, write:
  ID | tmux input | raw capture (last 15 lines) | error pattern hits | PASS/FAIL/WARN

When a batch finishes, send the result list to the coordinator and wait for the next batch.
```

### Phase 4 — Fixer worker prompt

Send this exact briefing to the fixer via mailbox:

```
You are the FIXER. NEVER run the NeoMind REPL. Only read test results, edit source, and run pytest.

WORKFLOW:
  1. Wait for bug reports from coordinator
  2. For each bug:
     a. Read the failing scenario's raw capture
     b. Locate the source code path (use Grep)
     c. Read enough surrounding code to understand
     d. Determine root cause (NOT just the symptom)
     e. Apply minimal fix (don't refactor surrounding code)
     f. Run unit tests:
          cd <workspace> && python3 -m pytest \
            tests/test_new_security.py tests/test_new_memory.py \
            tests/test_new_agentic.py tests/test_new_infra.py \
            -x -q 2>&1 | tail -10
     g. Append to fix log:
          ## Bug #N: <title>
          - Root cause: ...
          - Fix: ...
          - File: <path>:<line>
          - Verification: <unit test result>
     h. Report fix complete to coordinator

NEVER:
  - Run main.py or any REPL
  - Modify test result files
  - Skip the unit test step
  - Apply a fix without identifying the root cause
  - Refactor unrelated code
  - Make yaml prompts much longer (over-detailed prompts hurt LLM IQ)

KEY SOURCE FILES:
  agent/coding/tool_parser.py       - LLM tool call parsing (most bug-prone)
  agent/agentic/agentic_loop.py     - tool execution loop, error retries
  agent/services/safety_service.py  - file/path security
  agent/workflow/guards.py          - bash command security
  cli/neomind_interface.py          - REPL UI, prompt_toolkit, key bindings
  agent/cli_command_system.py       - slash command registry
  agent/services/code_commands.py   - stream_response, classification
```

### Phase 5 — The dispatch loop

```
while scenarios_remaining and budget_ok:
    batch = pick_next_batch(8-10 scenarios)
    send batch to tester
    wait for tester results
    fails = [r for r in results if r.verdict == FAIL]
    if fails:
        send fails to fixer
        wait for fixer to confirm fixes complete
        # Critical: re-test the fixed scenarios
        send fails to tester for re-verification
        wait for re-test results
        promote any still-failing to next round (max 3 retries per scenario)
    record progress to ~/.neomind/teams/selftest/progress.md
```

After every 5 batches, snapshot:
- Total scenarios run / passed / failed / fixed
- Bugs found and their root cause categories
- Estimated time to completion

### Phase 6 — Final report

When the plan is exhausted (or the user stops you), produce a final report at:

  `~/.neomind/teams/selftest/final_report.md`

Format mirroring `tests/qa_archive/reports/2026-04-08_PROJECT1_FINAL.md`:
- Total scenarios / pass / fail / warn
- Per-category breakdown
- Bugs found with severity and fix status
- Carry-over issues that need human attention
- Recommended next test plan (if any)

## Rules of engagement

1. **Tmux is the only acceptable terminal driver.** Never fall back to pexpect or subprocess+stdin — the bugs that matter live in the rendering layer.

2. **Capture-pane shows what the user sees.** If a bug appears in raw capture but not in the LLM's text response, it's still a bug worth fixing. Conversely, never mask raw capture before checking error patterns.

3. **Real keystrokes for real bugs.** Use `C-c`, `Tab`, `BSpace`, `Up`, `Esc`, `Enter` as real key sequences via tmux. Do not type "Ctrl+C" as a literal string.

4. **One agent, one role.** The tester does not edit code. The fixer does not run the REPL. This separation is what makes fix verification trustworthy.

5. **Re-test every fix.** A fixer's claim of "fixed" is unverified until the tester re-runs the failing scenario and reports PASS. Do not mark a bug closed before that.

6. **Rate limits.** Sleep 5-8s between LLM-triggering inputs. Sleep 15s between REPL restarts. Run at most one tester at a time per LLM provider.

7. **Cleanup.** At the end of any session that touched `~/.neomind/skills/`, `~/.neomind/plugins/`, or `~/.neomind/hooks/`, restore them to their pre-test state. Never leave test fixtures in the user's actual config.

8. **No silent fallbacks.** If tmux is unavailable, prompt_toolkit refuses to draw, or the LLM API is down — STOP and report. Do not "work around" the failure with a degraded test.

## Calling convention

The user invokes this skill with `/skill selftest` and a scope description, e.g.:

- `/skill selftest run a smoke test of all 3 personality modes`
- `/skill selftest test the slash command system end-to-end`
- `/skill selftest run the boundary plan against the file system tools`

Acknowledge the scope, confirm the test plan you'll use, give an ETA, then execute the workflow above.
