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
- [2026-04-19-launchd-service-stale-env-snapshot.md](2026-04-19-launchd-service-stale-env-snapshot.md) — Long-running services bake env at start; fixing .zshrc/config doesn't help. Always `ps eww <pid>` the running process, not just your shell.

## 2026-04-23 — Insight Lattice pan/zoom black-screen session

- [2026-04-23-ui-bug-ship-without-browser-test.md](2026-04-23-ui-bug-ship-without-browser-test.md) — After 3 failed iterative fixes for a UI bug, STOP editing and write a Playwright repro first. State dump + screenshot surfaces the real fault model; code reasoning alone doesn't.
- [2026-04-23-svg-viewbox-transform-voodoo.md](2026-04-23-svg-viewbox-transform-voodoo.md) — For pan/zoom, CSS transform on a wrapper `<div>` beats SVG `viewBox` + inner `<g transform>` + `getScreenCTM()`; stays in CSS pixels, no letterbox math.
- [2026-04-23-pan-clamp-on-canvas-not-content.md](2026-04-23-pan-clamp-on-canvas-not-content.md) — Pan clamp on canvas extent lets the viewport park on empty gaps between structured nodes ("black screen" despite math being correct). Compute a tight node bbox during layout and clamp on that.
- [2026-04-23-drag-listener-useeffect-race.md](2026-04-23-drag-listener-useeffect-race.md) — Don't attach document mousemove/mouseup via useEffect keyed on isPanning. The mousedown→useEffect commit gap (1–16ms) drops mouseup; next mousemove pans from stale state. Attach listeners synchronously in mousedown; teardown via ref.
- [2026-04-23-validate-then-ship-llm-pattern.md](2026-04-23-validate-then-ship-llm-pattern.md) — LLM output MUST pass a deterministic validator before anything downstream reads it. Never `reply["field"]` raw. Drop with a bounded drop_reason; fall back to deterministic output. Unlocks cheap self-check over stored output.

## 2026-04-24 — Research-tab cleanup (lattice as single focus)

- [2026-04-24-dashboard-features-that-compete-with-public-products.md](2026-04-24-dashboard-features-that-compete-with-public-products.md) — A tile that exists because "every dashboard has one" (chart / quote / heatmap / earnings calendar) competes with TradingView/Yahoo/Finviz/雪球 on their home turf and loses. Make L0 a backend tagging+snapshot pipeline (no viewing UI) and link out from each L0 node. Legacy via `?legacy=1` for reversibility.
- [2026-04-24-useeffect-ref-race-with-early-returns.md](2026-04-24-useeffect-ref-race-with-early-returns.md) — `useEffect(() => { ref.current... }, [])` never fires if the ref-bearing div lives past an early-return (loading/error skeleton). First render returns the skeleton → ref never attached → effect reads null → `[]` deps prevent re-run. Mirror the node into state via a callback ref and put that state in the dep array.

## 2026-04-24 — DeepSeek v4 migration session

- [2026-04-24-router-auto-discover-strips-deprecated-names.md](2026-04-24-router-auto-discover-strips-deprecated-names.md) — Vendor `/v1/models` drops deprecated id → router auto_discover strips it from valid set → 404 even though the direct vendor API still aliases it. Always test through the router; add a migration map for persisted refs.
- [2026-04-24-personality-model-override.md](2026-04-24-personality-model-override.md) — Per-personality `routing.primary_model:` defeats router's single-source-of-truth. Personality should own prompt + tools, NOT model selection. One `provider-state.json :: direct_model` rules them all.
- [2026-04-24-vendor-context-window-decimal-not-binary.md](2026-04-24-vendor-context-window-decimal-not-binary.md) — Vendor docs say "1M / 384K" — that's decimal (1,000,000 / 384,000), not 2^20 / 384×1024. Wrong-by-default: matches binary, overshoots actual API cap by ~5%.
