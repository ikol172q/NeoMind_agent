---
name: telegram-selftest
description: Run NeoMind's tester+fixer self-test loop against the live Telegram bot using Telethon. Mirror of selftest/ but for Telegram surface instead of tmux CLI. Tester drives a real Telegram MTProto client; Fixer reads bug reports and patches code. Repeats until clean or budget exhausted.
modes: [coding]
allowed-tools: [Bash, Read, Edit, Write, Grep, Glob, LS]
version: 1.0.0
---

# NeoMind Telegram Self-Test (Tester + Fixer Team)

You are the **coordinator** of a 2-agent self-test team for the Telegram surface. Your mission: discover and fix bugs in NeoMind by running it against itself through **real Telegram messages**, using the same tester+fixer methodology that the CLI `selftest` skill implements for tmux.

This skill is the Telegram counterpart of `agent/skills/shared/selftest/SKILL.md` (which covers CLI / tmux). Together they cover the two primary interfaces NeoMind exposes to users.

## Why a separate skill for Telegram

The user's primary interfaces are **Telegram** (for voice / quick chat / mobile) and **CLI** (for coding / batch work). Bugs in either are fatal because that's all the user has. CLI bugs are caught by the tmux-based `selftest` skill. Telegram bugs need a different driver: **Telethon** (a real MTProto client), not tmux.

Pexpect / CLI harnesses cannot test Telegram at all because they don't speak MTProto. Telethon speaks MTProto, logs in as a real user, and sends real messages to `@your_neomind_bot` — the same path a real human takes.

## The two-agent contract

| Role | Can | Cannot |
|------|-----|--------|
| **Tester** | Run Telethon, send real messages, capture replies, write `~/.neomind/teams/telegram-selftest/results/*.md` | Modify source code, run pytest, edit fix log |
| **Fixer** | Read source, edit source, run pytest, write `~/.neomind/teams/telegram-selftest/fixes/*.md` and append to `tests/qa_archive/FIX_LOG.md` | Send Telegram messages directly (only through tester), restart the live bot without coordinator permission |

The separation matters: a fix is not validated until a **fresh tester subagent** re-runs the failing scenario in a separate process and reports PASS. Self-validation by the agent that wrote the fix is not trustworthy.

## Workflow

### Phase 1 — Bootstrap the team

```
/team create telegram-selftest
```

You become the leader. Add two workers with clearly-defined roles:

- **tester** (color: cyan) — read-only access to source, full Telethon control, writes to `~/.neomind/teams/telegram-selftest/results/`
- **fixer** (color: yellow) — read+write source, runs `pytest tests/test_mode_gating.py` + related, writes to `~/.neomind/teams/telegram-selftest/fixes/` and appends to `tests/qa_archive/FIX_LOG.md`

Open both worker mailboxes via the swarm `Mailbox` API and confirm they reply to a ping before continuing.

### Phase 2 — Pick a scenario gate

Scenarios are defined in `tests/qa_archive/plans/2026-04-10_telegram_validation_v1.py` as a list of tuples grouped into SUBSETS. Each subset corresponds to a validation gate:

| Gate | Scenarios | Wall time | Use when |
|------|-----------|-----------|----------|
| `smoke` | 12 | ~5 min | Fast sanity check |
| `gate_0` | 66 | ~30 min | Retroactive validation for command-cleanup commits |
| `gate_b3` | 81 | ~40 min | After fin tools wired into agentic loop |
| `gate_b5` | 87 | ~45 min | After Tier 2 slash thin-wrapper refactor |
| `final` | 113 | ~60 min | End-of-phase comprehensive validation |

For a quick smoke run, use `smoke`. For a full release gate, use `final`.

### Phase 3 — Tester worker prompt

Send this exact briefing to the tester via mailbox:

```
You are the TESTER. NEVER modify source code. Use ONLY Telethon through
tests/integration/telegram_tester.py to interact with @your_neomind_bot.

REQUIRED METHOD (no exceptions):
  1. Import SUBSETS from
     tests/qa_archive/plans/2026-04-10_telegram_validation_v1.py
  2. Use tests.integration.telegram_tester.TelegramBotTester
  3. For each scenario tuple (sid, send, wait, expect_any, category):
       a. Call drain_until_quiet(6.0, 120.0) to avoid cross-step leak
       b. Send the text via the tester
       c. Wait up to `wait` seconds for the reply (with in-place edit detection)
       d. Record PASS if any keyword in expect_any appears in the combined reply
       e. Record FAIL with the first 300 chars of the actual reply
  4. Write a structured report to
     ~/.neomind/teams/telegram-selftest/results/<date>_<gate>.md

HEALTH CHECK EVERY 2-3 MIN:
  - docker exec neomind-telegram supervisorctl status neomind-agent must be RUNNING
  - tail of /data/neomind/agent.log must show fresh timestamps
  - If the log is silent >3 min while tester is active, ABORT and report the hang

NEVER:
  - Edit any source file
  - Run destructive git commands
  - Run pytest
  - Install pip packages
  - Restart the bot (only the coordinator or fixer can do that)

REPORT FORMAT (markdown):
  ## Gate: <name>
  ## Head: <git rev>
  ## Wall time: <s>
  ## Totals: <pass>/<total>
  ## By category: R:X/30 · F:X/10 · D:X/6 · T:X/8 · A:X/12 ...
  ## Regressions vs previous run: [list of SIDs]
  ## Failures:
    - SID: reason + first 300 chars of reply
  ## Verdict: PASS / FAIL
```

### Phase 4 — Fixer worker prompt

Send this exact briefing to the fixer via mailbox:

```
You are the FIXER. NEVER run Telethon or send any Telegram messages.
Your job is to read the tester's report, diagnose failures, patch code,
commit, and notify the coordinator when ready for re-test.

REQUIRED METHOD:
  1. Poll ~/.neomind/teams/telegram-selftest/results/ for new reports
  2. For each FAIL entry: read the bot's agent.log around the time of
     the failure, grep relevant source, form a hypothesis, apply a
     minimal patch
  3. Validate the patch with the relevant pytest target (e.g.
     tests/test_mode_gating.py) BEFORE committing
  4. git commit with a message linking the failing SID(s)
  5. Append an entry to tests/qa_archive/FIX_LOG.md with date, symptom,
     root cause, fix, commit hash, validation status (pending tester)
  6. Send a mailbox message to the coordinator: "fix ready for re-test"

NEVER:
  - Run Telethon / send Telegram messages
  - Validate your own fix (tester must do it in a separate process)
  - Delete commits (only revert, and only with coordinator permission)
  - Skip the pytest validation step
```

### Phase 5 — Loop until clean

```
while there are FAIL scenarios and budget > 0:
    tester runs the failing SIDs against the new commit
    if all pass:
        break
    else:
        fixer reads new report, makes next fix
```

### Phase 6 — Final report

Once all scenarios in the gate pass (within threshold), write a final report to `~/.neomind/teams/telegram-selftest/final_report.md` with:
- gate name + git HEAD at end
- total scenarios, final pass rate, by category
- list of all FIX_LOG entries this session added
- any open issues deferred to next session

## Dependencies

This skill depends on:
- `tests/integration/telegram_tester.py` — the Telethon driver
- `tests/qa_archive/plans/2026-04-10_telegram_validation_v1.py` — the scenario library
- `agent/agentic/swarm.py` — Mailbox, TaskQueue, TeamManager
- `~/.config/neomind-tester/telethon.env` — TG_API_ID, TG_API_HASH, TG_PHONE, TG_BOT_USERNAME (user's Telegram account)
- The live `@your_neomind_bot` running in Docker

## Limitations (NOT covered by this skill)

- **Group chat dynamics** — tester runs against a 1-on-1 chat with the bot
- **Multi-user race conditions** — requires multiple Telethon clients
- **Mobile-specific UX** — Telegram renders slightly differently on iOS / Android / Desktop
- **Voice messages** — tester sends text only (MTProto supports voice but test infra doesn't)
- **Image uploads** — not yet supported by this suite
- **Long-running sessions** (>1 hour, context window overflow) — covered separately by `tests/qa_archive/plans/2026-04-07_LONG_SESSION_PLAN.md`

## Related

- `agent/skills/shared/selftest/SKILL.md` — CLI / tmux version
- `docs/SELF_TEST.md` — CLI methodology
- `docs/TELEGRAM_SELF_TEST.md` — Telegram methodology (this skill's manual)
- `plans/TODO_zero_downtime_self_evolution.md` — the future of canary-deployment self-evolution that this skill will eventually power
