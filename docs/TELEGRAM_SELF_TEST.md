# NeoMind Telegram Self-Test (Tester + Fixer Pattern)

NeoMind can test its Telegram surface using the same tester+fixer methodology that `docs/SELF_TEST.md` documents for the CLI surface. The two documents together cover the two primary interfaces NeoMind exposes to users: **CLI** (tmux pseudo-terminal) and **Telegram** (Telethon MTProto client).

## Quick start

From any NeoMind REPL in coding mode:

```
/skill telegram-selftest run the gate_0 suite
```

NeoMind will:
1. Spin up a 2-agent team via `/team create telegram-selftest`
2. Spawn a **tester** worker that uses Telethon to send real messages to `@neomindagent_bot`
3. Spawn a **fixer** worker that reads bug reports and patches source
4. Run the scenario gate from `tests/qa_archive/plans/2026-04-10_telegram_validation_v1.py`
5. Loop: tester runs → flags fails → fixer patches → tester re-verifies
6. Write a final report to `~/.neomind/teams/telegram-selftest/final_report.md`

## Why this exists

The CLI self-test (tmux) cannot test Telegram at all because it doesn't speak MTProto. Telegram is a completely different surface — different message flow, different rendering (inline keyboards, markdown parsing, ReactionTypeEmoji, streaming edits), different failure modes (polling lag, rate limits, connection drops). Bugs in the Telegram surface are fatal because most of the user's daily interaction with NeoMind happens there.

This skill closes the gap by giving NeoMind the same level of self-test capability for Telegram that it already has for CLI.

## The two-agent contract

| Role | Can | Cannot |
|------|-----|--------|
| **Tester** | Run Telethon, send messages, capture replies, write `results/*.md` | Modify source, run pytest, edit fix log |
| **Fixer** | Read source, edit source, run pytest, write `fixes/*.md` and append to `tests/qa_archive/FIX_LOG.md` | Run Telethon, send Telegram messages, restart the live bot without coordinator permission |

The separation matters: a fix is not validated until the **tester** (a separate subagent process) re-runs the failing scenario and reports PASS. Self-validation by the agent that wrote the fix is not trustworthy — a pattern we burned on repeatedly in the 2026-04-10 session when "I ran 3 manual probes" was treated as validation.

## What "real Telegram" means here

The tester uses Telethon, which is a real MTProto client. When the tester calls:

```python
await client.send_message(bot, "/status")
```

the bot sees an incoming update from Telegram's servers, routed through `getUpdates` polling exactly the same way a real user's message would be. Telegram's servers, rate limits, message-edit flow, reaction delivery, markdown parser — all of it is in the loop. There is no mock, no test harness, no bypass. The only difference from a human user is that the tester reads replies via API instead of with eyes.

Compare to pexpect / tmux: those approaches can't test Telegram at all because they don't speak MTProto. You'd have to install a Telegram Desktop client and drive it via screen capture, which is way more fragile than Telethon.

## Fidelity of Telethon

**Near 100% equivalent to a real user** for all text-based interactions:
- Real MTProto round-trip (same servers, same rate limits, same auth)
- Real message-edit stream (Telethon sees `editMessageText` events just like the Telegram UI)
- Real typing indicators, reactions, mentions
- Real replies-to, inline keyboards (with minor API vs UI differences)
- Real group-chat context (when the test is run in a group)

**Not equivalent:**
- **Voice messages in** — user speaks into the phone, Telegram converts to voice file → bot receives audio. The tester currently sends text only. Voice ingestion path is not tested by this skill.
- **Image / document uploads in** — user sends a photo → bot receives a file. Not yet tested.
- **Mobile-specific rendering** — different Telegram clients render the same message slightly differently. Telethon's API view is closer to Desktop than to iOS/Android. Minor UX quirks on mobile can slip through.
- **Push notification behavior** — how the user's phone notifies them when the bot replies. Entirely client-side, not testable from the bot's perspective.

These gaps are acceptable because the core failure mode we want to catch is **the bot not replying correctly to a text message**, which Telethon covers 100%.

## Scenario library layout

Scenarios live in `tests/qa_archive/plans/2026-04-10_telegram_validation_v1.py` as a list of tuples:

```python
(sid, send_text, wait_seconds, expect_any_substrings, category)
```

Categories:
- **R** — Regression baseline (30 scenarios)
- **F** — Graceful slash fallthrough (10)
- **D** — Deletion graceful handling (6)
- **T** — `/tune` sub-command coverage (8)
- **A** — Tier 4 admin command coverage (12)
- **N** — Fin-mode natural-language tool triggering (15, Phase B.3+)
- **E** — Dual-entry slash/tool equivalence (6, Phase B.5+)
- **C** — Context / multi-turn (8)
- **X** — Edge cases (10)
- **G** — Group chat (8, optional)

Total: **113 scenarios**. Runtime for the full suite: ~60 minutes.

Gate subsets are defined in the same file's `SUBSETS` dict:
- `gate_0` (66 scenarios, ~30 min) — retroactive for cleanup commits
- `gate_b3` (81 scenarios, ~40 min) — after fin tools wired
- `gate_b5` (87 scenarios, ~45 min) — after thin wrapper refactor
- `final` (113 scenarios, ~60 min) — end of phase

## How the fixer uses the audit trail

Every fix committed by a fixer during a selftest loop must append an entry to `tests/qa_archive/FIX_LOG.md`:

```markdown
## 2026-04-10 Session

| # | Date | Bug | Root cause | Fix commit | Validated by |
|---|---|---|---|---|---|
| 79 | 2026-04-10 | /status shows ... | ... | abc1234 | R_U01 PASS at gate_0 |
```

The "validated by" column must reference a specific SID from the scenario library that re-ran after the fix. A commit without a validated SID is not a fix.

## Coordinator checklist

Before each run, verify:
1. `@neomindagent_bot` is RUNNING: `docker exec neomind-telegram supervisorctl status neomind-agent`
2. `git status --short` is clean (no uncommitted WIP that could be lost)
3. `~/.config/neomind-tester/telethon.env` exists with valid credentials
4. `tests/integration/telegram_tester.py` exists and imports cleanly
5. `tests/qa_archive/plans/2026-04-10_telegram_validation_v1.py` exists
6. `agent/agentic/swarm.py` mailbox infrastructure is importable

After each run:
1. Verify `~/.neomind/teams/telegram-selftest/final_report.md` exists
2. Copy the final report into `tests/qa_archive/results/<date>_telegram_<gate>.md` for version control
3. Append any new entries to `tests/qa_archive/FIX_LOG.md`
4. Commit the results + fix log updates

## Related

- `docs/SELF_TEST.md` — CLI / tmux version
- `agent/skills/shared/selftest/SKILL.md` — CLI selftest skill
- `agent/skills/shared/telegram-selftest/SKILL.md` — this skill's implementation
- `plans/2026-04-10_slash-command-taxonomy-v5-with-validation.md` — the taxonomy + validation framework this skill enforces
- `plans/TODO_zero_downtime_self_evolution.md` — canary deployment architecture that will let NeoMind self-modify Telegram code without taking the production bot offline
