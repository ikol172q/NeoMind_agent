# NeoMind Self-Test (Tester + Fixer Pattern)

NeoMind can test itself using the same fixer+tester methodology that produced the `tests/qa_archive/` archive (1,510+ test points, 70 bugs fixed).

## Quick start

From any NeoMind REPL in coding mode:

```
/skill selftest run a smoke test of slash commands
```

NeoMind will:
1. Spin up a 2-agent team via `/team create selftest`
2. Spawn a **tester** worker (read-only, drives a real tmux session)
3. Spawn a **fixer** worker (read+write source, runs pytest)
4. Pick a scenario batch from a plan in `tests/qa_archive/plans/`
5. Loop: tester runs → flags fails → fixer patches → tester re-verifies
6. Write a final report to `~/.neomind/teams/selftest/final_report.md`

## Why this exists

The `tests/qa_archive/` archive documents 70 real bugs that:
- Unit tests missed (they don't exercise the rendering layer)
- pexpect-based harnesses missed (they sanitize the output that contains the bug)
- Spot-checking missed (they're triggered by specific keystroke sequences or session-restart cycles)

The methodology that found them is now packaged as a skill so NeoMind can run it on itself — no human in the loop, no special setup beyond tmux.

## The two-agent contract

| Role | Can | Cannot |
|------|-----|--------|
| **Tester** | Run tmux, send keystrokes, capture pane, write `results/*.md` | Modify source, run pytest, edit fix log |
| **Fixer** | Read source, edit source, run pytest, write `fixes/*.md` and `FIX_LOG.md` | Run main.py, run REPL, edit test results |

The separation matters: a fix is not validated until the **tester** (a separate process) re-runs the failing scenario and reports PASS. Self-validation by the agent that wrote the fix is not trustworthy.

## What "real terminal" means here

Tmux is a real pseudo-terminal. When the tester sends:

```bash
tmux send-keys -t nm_test "yo" Enter
tmux capture-pane -t nm_test -p -S -30
```

NeoMind sees a real `tty`, prompt_toolkit renders normally, ANSI sequences are emitted, and `capture-pane -p` returns the rendered screen exactly as a user would see it (after the terminal processes the escape codes).

Compare to pexpect with `clean_ansi()`: pexpect strips ANSI before the test sees it. That's how the doubled `<tool_call>` parser bug went undetected for weeks — the error message `[agentic] Response contains <tool_call> but parser returned None` was emitted as an ANSI-styled `[red]...[/red]` line that pexpect's regex stripped before matching error patterns.

The tester in this skill never sanitizes capture output before pattern-matching for errors.

## Available test plans

| Plan | Scope | Time | When to use |
|------|-------|------|-------------|
| `tests/qa_archive/plans/2026-04-06_REAL_TERMINAL_TEST.md` | 525 short scenarios | ~6 hr | Full feature regression |
| `tests/qa_archive/plans/2026-04-07_LONG_SESSION_PLAN.md` | 10 sessions × 50-100 turns | ~6 hr | Endurance, auto-compact, long-context |
| `tests/qa_archive/plans/2026-04-08_PROJECT1_PLAN.md` | 210 boundary scenarios | ~10 hr | Real-user keystroke fidelity, edge cases |

For a smoke test, the skill picks 5-10 scenarios spanning each category — never the full plan unless explicitly asked.

## Direct invocation (without `/skill`)

If you want to run the loop programmatically (e.g., from a Cron job or CI step):

```bash
PYTHONPATH=. python3 -m bench.selftest_loop --plan smoke --max-rounds 3
```

(See `bench/selftest_loop.py` for the script — it's the same logic the skill uses, just without the team/mailbox indirection.)

## Output

After a run, you'll find:

```
~/.neomind/teams/selftest/
├── progress.md           ← live progress, updated every batch
├── results/
│   ├── batch_001.md      ← raw tmux captures + verdicts
│   ├── batch_002.md
│   └── ...
├── fixes/
│   ├── fix_001.md        ← root cause + diff + verification per bug
│   └── ...
├── FIX_LOG.md            ← consolidated fix history
└── final_report.md       ← summary, bugs found, next steps
```

The format mirrors `tests/qa_archive/` so reports can be moved into the archive without restructuring.

## Operating constraints

1. **Sleep budget**: 5-8 seconds between LLM-triggering inputs to avoid provider rate limits.
2. **One tester at a time** per LLM provider — no parallel test runs.
3. **Cleanup**: any test that creates `~/.neomind/skills/<test>/` or `~/.neomind/plugins/<test>/` MUST remove them at the end.
4. **No silent fallbacks**: if tmux is missing, prompt_toolkit can't draw, or the API is down, STOP — don't run a degraded version of the test.
5. **Re-test every fix**: a fix is not closed until the tester re-runs the original failing scenario and reports PASS.

## Limitations

The skill cannot test things that require a real human:

- Cross-platform validation (tested on macOS only — Linux/WSL/Windows need real installs)
- Multiple LLM providers (DeepSeek tested; OpenAI/Anthropic/Ollama need real keys)
- Network failure modes (no `pfctl`/`iptables` access)
- Physical keyboard ergonomics (Karabiner remaps, IME quirks, dead keys)
- Real terminal emulators (iTerm2, Alacritty, kitty differ from tmux's xterm emulation)
- Multi-day persistence (the test runs in one wall-clock window)

For these, see `tests/qa_archive/reports/2026-04-08_PROJECT1_FINAL.md` "Known Limitations" section.

## See also

- `agent/skills/shared/selftest/SKILL.md` — the skill itself, fully self-contained
- `bench/selftest_loop.py` — direct-invocation script
- `tests/qa_archive/README.md` — archive of past runs
- `tests/qa_archive/FIX_LOG.md` — chronological history of all 70 fixes
- `docs/AGENT_TEAM_TESTING_PATTERN.md` — older design doc for the pattern
