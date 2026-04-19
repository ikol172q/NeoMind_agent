# Troubleshooting index

One-line index of every known anti-pattern. Each entry points at a file
in this directory with full context (WRONG, RIGHT, WHY).

**How to read**: before starting any complex engineering task, scan this
index for categories that match your task (terminal capture, docker
recreate, feature gating, etc.). Open the specific entries and apply.

**How to add**: when a session produces a new failure mode, create a file
`YYYYMMDD-slug.md` with full context and add one line here.

---

## 2026-04-12 — coding-cli comprehensive test session

- [2026-04-12-arbitrary-terminal-line-limits.md](2026-04-12-arbitrary-terminal-line-limits.md) — Never use `capture(lines=N)` for full-terminal reads; use `start_recording`/`stop_recording` for absolute-scrollback accumulation
- [2026-04-12-fidelity-shortcut-hunting.md](2026-04-12-fidelity-shortcut-hunting.md) — When user says "100% fidelity", don't substitute tmux/expect/small window/slow polling
- [2026-04-12-stale-wakeup-pids.md](2026-04-12-stale-wakeup-pids.md) — Wakeup prompts contain stale pids; always `pgrep -f <runner>` first
- [2026-04-12-llm-judges-dont-work-here.md](2026-04-12-llm-judges-dont-work-here.md) — kimi/glm/deepseek-chat all fail as judges for NeoMind tests; Claude reads dumps directly
- [2026-04-12-feature-gate-single-fix-site.md](2026-04-12-feature-gate-single-fix-site.md) — auto_search hijack existed in 4 separate code paths; grep for ALL call sites before declaring fixed
- [2026-04-12-trusting-fixer-reports.md](2026-04-12-trusting-fixer-reports.md) — Verify fixer edits via grep/Read BEFORE running the test
- [2026-04-12-api-key-leak-in-bash-output.md](2026-04-12-api-key-leak-in-bash-output.md) — Never `echo $API_KEY` or `env | grep API_KEY`; use presence+length pattern
- [2026-04-12-docker-recreate-without-env-check.md](2026-04-12-docker-recreate-without-env-check.md) — Before docker recreate, diff live container env vs disk .env to prevent production breakage
- [2026-04-12-iterm2-batch-close.md](2026-04-12-iterm2-batch-close.md) — Never iterate `app.windows` and call `async_close`; killed Claude Code's own session
- [2026-04-12-iteration-spiral.md](2026-04-12-iteration-spiral.md) — After 3 failed fix attempts, dispatch a diagnostic agent (not another fix); stop patch-spraying
- [2026-04-12-subagent-prompt-sizing.md](2026-04-12-subagent-prompt-sizing.md) — Fixer prompts must be self-contained, surgical, <200 word report target
- [2026-04-12-cross-mode-smoke-skipped.md](2026-04-12-cross-mode-smoke-skipped.md) — Changes to shared paths require cross-mode boot smoke (automated via pre-commit hook)

## 2026-04-19 — fin dashboard fusion session

- [2026-04-19-headless-browser-memory-leak.md](2026-04-19-headless-browser-memory-leak.md) — Always `trap`/`finally` to kill spawned Chrome + rm user-data-dir; check `memory_pressure` before spawning; one background poll at a time
- [2026-04-19-openbb-workspace-schema-gotchas.md](2026-04-19-openbb-workspace-schema-gotchas.md) — apps.json is an ARRAY; agents.json endpoints.query is RELATIVE; SSE must emit `event: copilotMessageChunk` + `{"delta": …}` — Workspace drops anything else silently
