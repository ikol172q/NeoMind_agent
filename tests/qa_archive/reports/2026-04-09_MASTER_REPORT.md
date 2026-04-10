# NeoMind QA — Master Report
**Date range:** 2026-04-06 → 2026-04-09 (4 days)
**Method:** Real terminal interaction via tmux only — no harness wrappers, no env-var bypasses

## Headline numbers

| Metric | Value |
|--------|-------|
| **Total test points** | **1,510+** |
| **Bugs found** | **70** |
| **Bugs fixed** | **70** ✅ |
| **Fix rate** | **100%** |
| **Crashes during testing** | **0** |
| **Unit tests** | **318/318 pass** |
| **Wall clock** | **~30 hours over 4 days** |

## Test phase breakdown

| Phase | Test points | Bugs found | Method |
|-------|-------------|------------|--------|
| Phase 1 — 525 short scenarios (P0-P3g) | 525 | 28 | tmux scripted |
| Phase 2 — 10 long sessions (50-100t each) | 775 turns | 18 | tmux narrative |
| Phase 3 — Performance benchmarks | (benchmarks) | 0 | direct timing |
| Phase 4 — Project 1 (real-user boundary) | 210 | 24 | tmux real keys |
| **Total** | **1,510+** | **70** | |

## Bug severity distribution

| Severity | Found | Fixed |
|----------|-------|-------|
| P0 (critical, data loss / crash / silent fail) | 12 | 12 |
| P1 (high, major UX or feature broken) | 28 | 28 |
| P2 (medium, edge case) | 22 | 22 |
| P3 (low, cosmetic / minor) | 8 | 8 |

## Bug categories

| Category | Count | Examples |
|----------|-------|----------|
| Tool call parser variants | 9 | `<thinking>` inside `<tool_call>`, doubled tags, pure XML, OpenAI key format, `<\|tool_call\|>` |
| User config loading | 4 | `~/.neomind/skills/` ignored, `PluginLoader.load_all()` never called |
| Path security | 6 | tilde bypass, case bypass, `~/.docker/config.json`, broken symlinks |
| Keyboard interaction | 6 | Triple Ctrl+C kill, Esc+Enter, Ctrl+L, quoted args, /think on/off, ANSI paste |
| Headless mode | 4 | Tools not executed, `--system-prompt` ignored |
| Session management | 5 | `/branch` orphans, `/compact` losing identity, `/stats` zeros, `/load` empty |
| Display rendering | 6 | `</tool_call>` leakage, traceback exposure, spinner residue, content repeat |
| Slash command edge cases | 12 | `/verbose`/`/hooks`/`/arch` unregistered, `/flags toggle` parsing, `/help <cmd>` |
| Long conversation | 4 | Auto-compact identity loss, Ctrl+C during compact, recall after compact |
| LLM behavior workarounds | 8 | Chinese command space loss, retry circuit breaker, hallucinated tool names |
| Other | 6 | Various |

## What works (verified across all phases)

- ✅ All 45+ slash commands functional after fixes
- ✅ Three personality modes (coding/chat/fin) with mode switching
- ✅ Long conversations to 300 turns with auto-compact
- ✅ Session save/load/checkpoint/rewind/branch (all formats md/json/html)
- ✅ Security blocks: `/etc/passwd`, `~/.ssh/id_rsa`, `~/.docker/config.json`, `rm -rf /`, `curl|bash`, path traversal, case bypass
- ✅ User-installed skills, plugins, hooks, output styles, rules persistence
- ✅ Real keyboard interaction: C-c/d/l/o/e/w/u, Tab, Up/Down, Home/End, Esc
- ✅ Terminal environments: 10×5 to 250×50, TERM=dumb/screen/xterm, LANG=C/UTF-8
- ✅ Concurrent NeoMind instances (no data races)
- ✅ Filesystem edge cases: Unicode names, symlinks, permissions, sizes 0-100MB
- ✅ Anomaly recovery: bad API key (now errors clearly), missing files, kill -TERM, kill -9 + resume

## Performance baseline

| Metric | Value |
|--------|-------|
| Python no-op floor | 13 ms |
| `--version` (fast path) | 14 ms |
| `--help` | 30 ms |
| `--dump-system-prompt` | 53 ms |
| Interactive REPL startup (any mode) | 730–780 ms |
| LLM round-trip — small prompt | 6 s (p50) |
| LLM round-trip — medium (100 word) | 9.8 s (p50) |
| LLM round-trip — large (400 word) | 20.5 s (p50) |
| Tool execution (Read 1KB-1MB, cached) | 0.5 ms |
| Tool execution (Bash echo) | 0.08 ms (warm) |
| Memory footprint (cold start) | 177 MB |

**Bottleneck:** ~90% of user-perceived latency is the DeepSeek API call. The tool layer (sub-millisecond) is not the bottleneck.

## Methodology insights

The breakthrough that enabled this archive was abandoning pexpect/`clean_ansi`-based test harnesses and switching to tmux + raw `capture-pane`. The first 100+ scenarios run with pexpect produced clean PASS reports while the same scenarios run via tmux instantly surfaced bugs that had been there for weeks.

**Key principles** (now codified in `agent/skills/shared/selftest/SKILL.md`):

1. **Tmux is the only acceptable terminal driver.** It provides a real pty, prompt_toolkit renders normally, and `capture-pane -p` returns rendered content (post-ANSI).
2. **Never sanitize capture before checking error patterns.** The error messages that matter often live in ANSI-styled lines that `clean_ansi()` strips.
3. **Real keystrokes for real bugs.** `tmux send-keys C-c`, `Tab`, `BSpace` are real key sequences, not text strings.
4. **Tester ≠ Fixer.** A fix is unverified until a separate process re-runs the failing scenario and reports PASS.
5. **One agent, one role.** Tester never edits source. Fixer never runs the REPL.
6. **No silent fallbacks.** If something can't be tested cleanly, STOP and report — don't run a degraded version.

## Carryover and known limitations (NOT bugs)

- DeepSeek occasionally produces tool calls in formats not yet seen (the parser has 7+ format normalizers as a result)
- DeepSeek drops spaces in commands with non-ASCII args (LLM behavior, mitigated by error retry circuit breaker)
- Auto-compact threshold is high — 100 turns of trivial chat doesn't trigger it
- tmux→prompt_toolkit `BSpace` injection is unreliable (test-tool issue, not NeoMind bug)
- No env-var override for `DEEPSEEK_BASE_URL` / `DEEPSEEK_TIMEOUT` (architectural — other providers have these)
- Performance numbers are macOS-only

## Next steps

1. **NeoMind self-test capability** — packaged as `agent/skills/shared/selftest/SKILL.md` and `bench/selftest_loop.py`. Future test runs can be initiated by NeoMind itself via `/skill selftest`.
2. **Multi-LLM matrix** (Project 3) — needs human to provide OpenAI/Anthropic/Ollama credentials.
3. **Linux/Windows validation** — needs actual installs on those platforms (CI would suffice).
4. **Real terminal emulator differences** — iTerm2/Alacritty/kitty diff from tmux's xterm emulation; needs human spot-check.

## File references

- Plans: `tests/qa_archive/plans/`
- Raw results: `tests/qa_archive/results/`
- Other reports: `tests/qa_archive/reports/`
- Fix history: `tests/qa_archive/FIX_LOG.md`
- Self-test skill: `agent/skills/shared/selftest/SKILL.md`
- Self-test runner: `bench/selftest_loop.py`
- Self-test docs: `docs/SELF_TEST.md`
