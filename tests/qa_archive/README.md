# NeoMind QA Archive

Multi-day QA test archive for NeoMind agent. All tests use **real terminal interaction via tmux**, not synthetic test harnesses.

## Final Stats

| Metric | Value |
|--------|-------|
| Test points | **1,510+** |
| Bugs found | **70** |
| Bugs fixed | **70** ✅ |
| Crashes observed | **0** |
| Unit tests | **318/318 pass** |
| Test wall time | **~30 hours** |

## Layout

```
qa_archive/
├── README.md              ← this file
├── FIX_LOG.md             ← consolidated bug fix history (70 entries)
├── plans/                 ← test plan documents (3 files)
│   ├── 2026-04-06_REAL_TERMINAL_TEST.md   — 525 short scenarios across P0-P3
│   ├── 2026-04-07_LONG_SESSION_PLAN.md    — 10 sessions × 50-100 turns each
│   └── 2026-04-08_PROJECT1_PLAN.md        — 210 real-user boundary scenarios
├── results/               ← raw test execution results (26 files)
│   ├── 2026-04-06_P*_RESULTS.md           — short scenario waves
│   ├── 2026-04-07_SESSION*_RESULTS.md     — long-session results
│   └── 2026-04-08_WAVE*_RESULTS.md        — boundary test waves
└── reports/               ← analysis & summary reports (6 files)
    ├── 2026-04-06_PROGRESS.md             — progress tracker
    ├── 2026-04-07_BENCHMARK_RESULTS.md    — performance benchmarks
    ├── 2026-04-07_FINAL_SUMMARY.md        — short scenarios final
    ├── 2026-04-07_LONG_SESSION_FINAL.md   — long sessions final
    ├── 2026-04-07_PROGRESS_FINAL.md       — overall progress snapshot
    └── 2026-04-08_PROJECT1_FINAL.md       — boundary test final
```

## Test Methodology

### Real Terminal via tmux (the only acceptable method)

Every test interacts with NeoMind through a real tmux pty session. NO env-var hacks, NO test harness wrappers, NO bypass paths. The test agent uses:

- `tmux new-session -d -s s -x 120 -y 40` — start a real terminal
- `tmux send-keys -t s "input" Enter` — send text as if a user typed it
- `tmux send-keys -t s C-c` — real Ctrl+C, not a signal to the Python process
- `tmux send-keys -t s Tab` — real Tab key for completion
- `tmux send-keys -t s BSpace` — real Backspace
- `tmux capture-pane -t s -p` — see exactly what a user would see (rendered, post-ANSI)

This was the breakthrough that exposed bugs that pexpect-based and unit-test-based approaches had missed for weeks (e.g., the doubled `<tool_call>` parser bug, the triple-Ctrl+C process kill, the user skill loader being completely silent).

### Tester + Fixer Separation

- **Tester agent**: NEVER modifies source code. Only runs tmux, captures output, records PASS/FAIL.
- **Fixer agent**: NEVER runs the REPL. Only reads test results, edits source code, runs unit tests.
- After each fixer round, the tester re-runs failed scenarios to verify the fix.

This separation ensures fixes are validated by an independent process, not the same agent that wrote them.

## Test Phases (Chronological)

### Phase 1 — Short Scenarios (525 test points)
P0–P3g cover 17 categories:
- A. Basic interaction (10)
- B. Info commands (15)
- C. Toggle commands (10)
- D. Session management (12)
- E. Team/rules (8)
- F. Dev tools (8)
- G. Misc commands (5)
- H. LLM tool calls (15)
- I. Context memory (8)
- J. Code generation (8)
- K. Security (12)
- L. 3 personality modes (9)
- M. Headless mode (4)
- N. Display quality (8)
- O. Prompt/config correctness (6)
- P. Combo scenarios (10)
- Q. Long conversations (3)

### Phase 2 — Long Sessions (775 turns)
10 narrative-driven sessions of 50-100 turns each:
1. Full-Stack Feature Development (coding, 80t)
2. Portfolio Analysis Deep Dive (fin, 70t)
3. Security Penetration Testing (coding, 60t)
4. Cross-Mode Research Project (chat+coding, 90t)
5. Debugging Production Bug (coding, 75t)
6. Finance Quant Strategy (fin, 65t)
7. Documentation Sprint (coding+chat, 85t)
8. Multi-Agent Team Task (coding, 55t)
9. Persistence Stress Test (mixed, 100t)
10. Real-World Workday (all 3 modes, 95t)

### Phase 3 — Performance Benchmarks
- Startup latency (Python floor / fast path / interactive)
- LLM round-trip latency (small/medium/large prompts)
- Tool execution latency (Read/Bash/Grep/Glob, in-process)
- Memory footprint (RSS at startup and over time)
- Bottleneck analysis

### Phase 4 — Project 1: Real-User Boundary Tests (210 scenarios)
Pushes capability limits with **100% real keystroke fidelity**:
- A. Keyboard shortcuts (25): C-c/d/l/o/e/w/u, Tab, Up/Down, Home/End, Esc
- B. Typing simulation (15): slow/fast typing, paste-buffer, Unicode
- C. Config + restart (30): Skills, Plugins, Hooks, Output Styles, Rules persistence
- D. Long conversations (10): 100-300 turns
- E. Interrupt recovery (15): Ctrl+C at various execution points
- F. File system edge cases (30): Unicode names, symlinks, permissions, sizes
- G. Anomaly injection (20): bad API keys, missing files, process kills
- H. Persistence (15): cross-session save/load/resume
- I. Terminal environment (10): 10×5 to 250×50, TERM=dumb, LANG=C
- J. Command boundaries (30): rare slash commands, argument edge cases
- K. Concurrency / race (10): multiple instances, rapid input

## Notable Bug Categories Found

1. **Tool call parser variants** (8 bugs) — DeepSeek emits multiple tool call XML formats; parser had to be hardened with normalization for `<thinking>`, `<think>`, doubled tags, pure XML, OpenAI format, `<|tool_call|>` variants
2. **User config loading** (3 bugs) — `~/.neomind/skills/`, `~/.neomind/plugins/` were silently ignored
3. **Keyboard interaction** (4 bugs) — Triple Ctrl+C kill, Esc+Enter, quoted args, /think on/off inversion
4. **Path security** (5 bugs) — tilde bypass, case bypass, `~/.docker/config.json`, broken symlinks
5. **Headless mode** (3 bugs) — tool execution missing, `--system-prompt` ignored, `--cwd` issues
6. **Session management** (4 bugs) — `/branch` orphans, `/compact` losing identity, `/stats` zeros
7. **Display quality** (5 bugs) — `</tool_call>` leakage, traceback exposure, ANSI paste crash

See `FIX_LOG.md` for the full chronological bug-fix history with root causes and verification.

## Reproducing the Tests

The fixer+tester pattern is now available as a NeoMind self-test capability — see `<workspace>/docs/SELF_TEST.md` and the `selftest` skill at `<workspace>/agent/skills/selftest/SKILL.md`.
