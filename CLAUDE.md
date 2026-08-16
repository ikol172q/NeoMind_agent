# NeoMind — Claude Code project guide

NeoMind is a multi-modal agent (chat / coding / fin) with a CLI and a
Telegram bot surface. This file is auto-loaded into every Claude Code
session started in this project. It is an **index only** — the actual
content lives in the files it points to.

## Key conventions

- **Python venv**: `.venv/bin/python` (never system python)
- **LLM router**: `http://127.0.0.1:8000/v1` (local litellm proxy)
- **Modes**: `coding` / `chat` / `fin` — each with its own config in `agent/config/`
- **API keys**: inherit from `~/.zshrc` via `docker-compose.yml` `environment:`, not `.env`
- **Permission bypass (tests only)**: `NEOMIND_AUTO_ACCEPT=1`

## Where things live

### Methodology (how to do things right)
`.claude/skills/<name>/SKILL.md` (project) and `~/.claude/skills/<name>/SKILL.md`
(user-level, applies to all projects) — invoked when description matches.
- `tester-fixer-judge` — multi-agent test+fix orchestration
- `real-terminal-fidelity-testing` — 100% user-behavior terminal testing
- `session-reflection` (user-level) — auto-trigger self-review every ~30 min in
  long sessions, externalize new learnings, dedup against existing docs
- `anti-hallucination` — **MUST READ** before any task that fills fact-heavy
  structured data (yaml/json), researches sources, or asks an LLM to "compress
  training knowledge into facts". Phase 3 subagent fabricated 108 source URLs
  + dozens of numeric claims in `docs/strategies/strategies.yaml` because this
  rule did not exist. Hard rules: URLs must be `raw://<sha256>` or `[]`;
  numeric claims must be qualitative or `*_source`-cited; empty is honest,
  invented number is trust violation.

### 🪞 Periodic self-reflection (mandatory)
At session start for long/complex work, schedule a wakeup (~25 min) to invoke
the `session-reflection` skill. At every natural phase boundary (merged PR,
finished scenario, major fix, incident), also invoke it. Externalize new
learnings into skill / hook / troubleshooting — don't wait for user reminder.

### Troubleshooting (anti-patterns to avoid)
`.claude/docs/troubleshooting/INDEX.md` — one-line index of every anti-pattern.  
`.claude/docs/troubleshooting/<YYYYMMDD-slug>.md` — one file per anti-pattern with
the concrete WRONG code/command, the RIGHT alternative, and WHY.

**Before any complex engineering task, read `INDEX.md` and open any relevant
entries. Every session is expected to add at least one new entry when a
mistake is made or a subtle gotcha is discovered.**

### Active hooks
`.claude/settings.json` — Claude Code hook config.
- PreToolUse:Bash → `tools/hooks/iterm2_safety_hook.py` (blocks iTerm2 window close patterns)
- PreToolUse:Bash → `tools/hooks/leak_scan_hook.py` (gitleaks before `git commit`/`push`,
  author-metadata check, blocks force-push to main; bypass with `NEOMIND_ALLOW_LEAKS=1`)

`.git/hooks/pre-commit` → `tools/hooks/pre-commit`  
(installed via `./tools/hooks/install.sh`; runs
`tests/integration/cross_mode_boot_smoke.py` when shared paths change)

### 🔺 Truth-first prompt design (mine and NeoMind's)
`plans/references/` — the design philosophy I use when authoring or
auditing any prompt in this repo, and the operating manual for my own
behavior in Claude Code sessions.
- `karpathy-skills-2026.md` — Karpathy's 4 principles (Think Before /
  Simplicity / Surgical / Goal-Driven), all converging on falsifiability.
- `first-principles.md` — when to drop pattern-matching and query the
  substrate (state / context / live data / "I think I know" signals).
- `karpathy-2025-12-tweet.md` — "LLMs make wrong assumptions on your
  behalf and just run along with them without checking." The single
  most-actionable LLM failure-mode diagnosis.
- `prompt-design-philosophy.md` — synthesis: pyramid template
  (pinnacle → 5 failure modes → assumption surfacing → first-principles →
  pre-response gate → style/tools/persona), shared across NeoMind's
  chat / coding / fin personalities.
- The personal version of these as MY operating rules lives in
  user-level memory `feedback_pyramid_truth_first.md`.

### User-level memory
`~/.claude/projects/-Users-localuser-Desktop/memory/` — user-level persistent
memories (loaded for any session under `/Users/user/Desktop/`). Contains
the hard rule file `feedback_never_close_iterm2_windows.md`.

## Running the tests

The suite is ~6100 tests. Running all of them takes about six minutes, but the
time is not evenly spread: the 25 slowest account for roughly 240 of those 360
seconds, and every one of them is slow for the same reason — it leaves the
process to call a provider, spawn a subprocess, or wait out a real timeout.

So the default run holds those back and everything else finishes in about a
minute and a half.

```bash
.venv/bin/python -m pytest tests/ -q          # fast tier — the inner loop
NEOMIND_TESTS=all .venv/bin/python -m pytest tests/ -q   # everything
.venv/bin/python -m pytest tests/ -q -m llm   # one tier: llm | proc | slow
```

Every default run prints what it held back:

```
- 160 tests held back (70 llm, 86 proc, 4 slow) — NEOMIND_TESTS=all to run them -
```

That line is not decoration. A suite that quietly stops running things starts
lying about what is covered, and this repository has already been bitten by
tests that skipped themselves and read as green.

**Run the full tier before pushing, and after touching anything shared.** The
fast tier does not exercise the provider, the CLI as a process, or timeout
behaviour, so it cannot tell you the agent still boots.

Tiers are assigned by path in `tests/conftest.py::_TIER_PATHS`, not by
decorating each test, so a new file under `tests/llm/` is tiered the moment it
exists. Add a path there rather than marking tests one by one.

Killing pytest does not reap the Playwright chromium the web tests spawn per
file. After an interrupted run: `tools/reap_test_processes.sh`.

## How to extend

When a session produces new learnings:

1. **Methodology** → new `.claude/skills/<name>/SKILL.md` (one skill per concept)
2. **Anti-pattern** → new file at `.claude/docs/troubleshooting/YYYYMMDD-slug.md`
   AND append a one-line entry to `INDEX.md`
3. **Never** stuff content directly into this file. This file is a map, not a
   library.
