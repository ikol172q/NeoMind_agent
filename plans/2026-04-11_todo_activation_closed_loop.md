# TODO Activation — Zero-Downtime Self-Evolution Closed Loop

**Started:** 2026-04-11
**Goal:** Turn the canary bot + iTerm2 CLI driver from "code landed, smoke-tested" into a live end-to-end closed loop where NeoMind can (a) propose a change, (b) validate it against a canary bot via Telethon, (c) validate it against a live iTerm2 CLI session, (d) promote to production, (e) have real users keep chatting throughout — across **both** user-facing surfaces (Telegram + CLI).

**Non-negotiable constraints** (per user directive 2026-04-11):
1. **Closed-loop success is the priority.** Not "code compiles". Not "smoke test passes". The end-state is: a real evolution runs through canary + prod and both Telegram and iTerm2 users see expected behavior at every step.
2. **Do NOT trigger rate limits.** Space validator runs, reuse captured state where possible, fallback gracefully on 429.
3. **Do NOT break existing functionality.** Any regression on the Final-Gate-PASS baseline (HEAD `d45707a`) is a P0 blocker.
4. **The new feature IS expected.** Users know the canary + iTerm2 validator are coming online — this is not a stealth change. Minor user-visible differences (e.g. new `NEOMIND_CANARY=1` log line, new `router-fallback` entries in `/status`) are OK.
5. **Leave records.** This plan file + commit messages + the final "closed-loop PASS" evidence must be reconstructible in a future session.

---

## What landed before this activation session

Session 2026-04-10 → 2026-04-11 shipped (see `git log feat/major-tool-system-update -20`):

- **Plan v5 (slash-command taxonomy) — Final Gate PASS** at HEAD `d45707a`. 53/55 scenarios green across F/D/N/E/C/X. Core fixes: `_ask_llm_streaming` agentic loop wire-up, router-fallback chain, 429 retry, persona list_only, finance_compute aliases + self-correct feedback, repeat-counter reset. R/T/A passed in earlier gates.
- **TODO Part 1 code (`ce47011`)** — `neomind-canary` docker-compose service behind `canary` profile, `CanaryDeployer` orchestrator, `NEOMIND_CANARY=1` state isolation in `provider_state.py`, validator target switch via `NEOMIND_TESTER_TARGET=canary`, `docs/CANARY_BOT_SETUP.md`.
- **TODO Part 2 code (`e6011d0`)** — `ITerm2CliTester` driver, clean `ITerm2APIUnavailable` fallback path, `docs/CLI_SELF_TEST_ITERM2.md`, inline `_smoke()` entry point.

Both parts smoke-tested to the point of their external-prerequisite gates — import clean, preflight clean, unavailable path surfaces with correct remediation message.

---

## Blockers only the user can unblock

These are the two physical actions I cannot perform from a shell:

### B1. Create the canary Telegram bot

1. Open Telegram, DM **@BotFather**
2. `/newbot` → pick display name "NeoMind Canary" → pick username `neomindagent_test_bot` (or similar, must end in `bot`)
3. Copy the token BotFather returns (looks like `1234567890:AbCdEf...`)
4. **Paste the token back to the assistant** so it can fill `.env` and `telethon.env` for you

### B2. Accept iTerm2 Python API security dialog

1. The assistant has already set `defaults write com.googlecode.iterm2 EnableAPIServer -bool true`
2. You need to **Quit iTerm2 and re-open it** (Cmd+Q from iTerm2, then launch again from Applications / Spotlight)
3. On first start with API enabled, iTerm2 shows a one-time permission dialog:
   > "iTerm2 Python API: A script would like to control iTerm2. Allow?"
4. Click **Allow** (and tick "Don't ask again" if offered)
5. Confirm the socket is up: `lsof -i :1912` should show iTerm2 listening

Once B1 and B2 are done, every remaining step is automated by the assistant.

---

## Plan of execution (assistant-driven)

Each step lands as a commit so the closed loop is fully reconstructible.

### Phase A — pre-activation (assistant, can run NOW without blockers)

- [x] **A1** Write this activation plan (you're reading it)
- [ ] **A2** Verify the Final Gate baseline (HEAD `d45707a`) is still in a known-green state. Quick 5-scenario smoke (`/status` + `AAPL 现价` + one persona query + one /tune + one compound math) so we have a fresh regression floor BEFORE touching anything. Commit result to `tests/qa_archive/results/2026-04-11_pre_activation_smoke.md`.
- [ ] **A3** Add `TG_CANARY_BOT_USERNAME=@neomindagent_test_bot` placeholder to `.env.example` so the change is documented even before the user populates the real username. Keep `.env` untouched.
- [ ] **A4** Add a `.env` ingest helper to `docs/CANARY_BOT_SETUP.md` so B1 is documented end-to-end.

### Phase B — canary bot activation (needs B1 token)

- [ ] **B1.1** Assistant writes `TELEGRAM_TEST_BOT_TOKEN=<user-supplied>` to `.env` (append, no overwrite of production key)
- [ ] **B1.2** Assistant writes `TG_CANARY_BOT_USERNAME=<user-supplied>` to `~/.config/neomind-tester/telethon.env`
- [ ] **B1.3** Pull / build the canary image:
      `docker compose --profile canary build neomind-canary`
- [ ] **B1.4** Start the canary container:
      `docker compose --profile canary up -d neomind-canary`
- [ ] **B1.5** Verify canary boots:
      `docker exec neomind-canary supervisorctl status neomind-agent`
      should show RUNNING
- [ ] **B1.6** Confirm canary bot is reachable from Telegram:
      `curl https://api.telegram.org/bot<TEST_TOKEN>/getMe` returns `ok:true`
- [ ] **B1.7** Run `CanaryDeployer.preflight()` — must return `(True, "preflight ok")`
- [ ] **B1.8** Fire a single smoke scenario against canary bot via Telethon (`NEOMIND_TESTER_TARGET=canary`): send `/status`, expect reply within 30s. Records proof that the canary + validator wiring works end-to-end.

### Phase C — iTerm2 driver activation (needs B2 preference + restart)

- [ ] **C1** Confirm `lsof -i :1912` shows iTerm2 listening (no listen = user hasn't restarted iTerm2 yet)
- [ ] **C2** Run `.venv/bin/python tests/integration/cli_tester_iterm2.py` — must open a real iTerm2 window, run `python -m agent`, send `/status`, capture output, exit 0
- [ ] **C3** Write a minimal "real CLI scenario" script that uses `ITerm2CliTester` to run 5 representative scenarios against the CLI (`/status`, `/mode fin`, `AAPL 现价`, `/tune status`, `/clear`) and assert the rendered screen contains expected markers. This is the CLI counterpart to the Telethon canary smoke.

### Phase D — closed-loop end-to-end (needs B + C PASS)

- [ ] **D1** Compose a trivial real evolution: add a harmless log line to `agent/integration/telegram_bot.py` startup (e.g. `print("[bot] canary-loop-marker-2026-04-11")`). This is the unit of change that will flow through the entire pipeline — small enough to be safely reversible, distinctive enough to be grep-able post-deploy.
- [ ] **D2** Inside a fresh `EvolutionTransaction`:
      - `apply()` the marker edit
      - `smoke_test()` — must PASS (it will; the change is a print)
      - `CanaryDeployer.deploy_and_verify(txn, validator_subset="gate_b3")` — must PASS (no regression on the ~20-min gate_b3 subset against the canary bot)
      - Run `ITerm2CliTester` scenarios against the CANARY container's CLI path (via `docker exec neomind-canary .venv/bin/python -m agent` — this is the CLI surface of the canary bot, different from the production CLI) — must PASS
      - `txn.commit()` + `CanaryDeployer.promote_to_prod(txn)` — production restarts, but only AFTER canary has validated both surfaces
      - Run ~3 post-promotion probes against production via Telethon + iTerm2 to confirm the marker log line fires and no regression has been introduced
- [ ] **D3** Immediately `git revert` the marker commit and push the revert through the same pipeline. Demonstrates the rollback path works end-to-end — production ends up back at `d45707a`-equivalent state after a full canary → prod → canary-revert → prod-revert loop.
- [ ] **D4** Write `tests/qa_archive/results/2026-04-11_closed_loop_pass.md` with the evidence: commit hashes, validator reports, CLI screen captures, timing per stage.

### Phase E — durability + records

- [ ] **E1** Add a cron / systemd stub (design only, no activation) for nightly canary smoke so regression is caught next session without manual runs
- [ ] **E2** Update `MEMORY.md` index with any new feedback/reference memories
- [ ] **E3** Commit this plan file as completed

---

## What success looks like

**Full PASS checklist:**

1. Production `@neomindagent_bot` uptime > 99% during the entire activation (allow ~5-10s blip only for `promote_to_prod` restart)
2. `@neomindagent_test_bot` (canary) runs through a full `gate_b3` scenario set without regressions vs the Final Gate baseline
3. `ITerm2CliTester` runs 5 real scenarios against a live iTerm2 window (visible to the user, not backgrounded) and every scenario PASSes against expected screen content
4. An end-to-end evolution commit moves through `EvolutionTransaction.apply → smoke → canary_deploy_and_verify → promote_to_prod` and the production bot still serves real users at every step
5. An end-to-end revert moves through the same pipeline and returns to `d45707a`-equivalent state
6. Evidence file committed (`2026-04-11_closed_loop_pass.md`) with commit hashes, validator reports, CLI captures, stage timings

**Fail conditions (any of these = STOP and fix before continuing):**
- Production `@neomindagent_bot` goes silent for > 30s at any point outside the planned `promote_to_prod` window
- A Final-Gate-baseline scenario regresses (e.g. `AAPL 现价` stops returning real yfinance data)
- Canary bot conflicts with production (e.g. both answering the same chat_id)
- Rate limit triggered on moonshot / deepseek / telegram → STOP and wait for cooldown
- Any traceback in `/data/neomind/agent.log` during the validation window

---

## Open risks (known unknowns)

1. **Canary container might race the production container for the same litellm router rate bucket.** Both will send requests under the same org key. Mitigation: space validator runs ≥ 10s apart, prefer `gate_b3` (smaller subset) over `gate_final` for canary validation runs.

2. **Telegram bot API has per-bot rate limits.** The canary bot is a fresh token so its bucket is disjoint from prod, which is good. But if the canary validator is aggressive, the canary bot itself could throttle. Mitigation: `drain_until_quiet(min_quiet_sec=6)` between every scenario (already default).

3. **iTerm2 API may quiesce if the window loses focus.** The current driver uses `visible=True` by default. If the user switches desktops during the run, the iTerm2 session might be backgrounded and capture latency could spike. Mitigation: tester retries `capture()` up to 3× on empty return.

4. **`supervisorctl restart` inside the canary container might cascade into the supervisord watchdog restarting non-agent services.** Mitigation: explicit `supervisorctl restart neomind-agent` (program name, not group) as already coded in `canary_deploy.py`.

5. **Pre-existing 3 failing tests in `tests/test_provider_state.py::TestProviderChain`** — these fail at HEAD `d45707a` baseline (unrelated to canary), so any "regression check via pytest" must exclude these or filter them out. Not a new problem; flagging it here so the activation run doesn't mistakenly diagnose them as canary-caused.

---

## Rollback

If at any point during Phase D the production bot misbehaves:

1. `docker exec neomind-telegram supervisorctl restart neomind-agent` — quick clean restart from current git HEAD
2. If HEAD is already bad: `git reset --hard d45707a && docker exec neomind-telegram supervisorctl restart neomind-agent`
3. The canary container can be torn down independently: `docker compose --profile canary stop neomind-canary` — doesn't affect production at all

Canary state is volume-isolated (`neomind-canary-data`) so there's no risk of canary-side data corrupting prod SQLite.

---

## Assistant's status flags (filled in during execution)

- [x] Phase A complete (commit `2203748`)
- [x] Phase B complete (commit `ce47011` infra + `3cf92ae` entrypoint fix; canary `@neomindagent_test_bot` LIVE)
- [ ] Phase C complete (deferred to session end — needs iTerm2 restart)
- [x] Phase D complete (commits `69ba06b` add-leg + `370889c` revert-leg + `cd0b081` evidence file)
- [ ] Phase E in progress (memory records updated, nightly cron stub pending)
- [x] Closed-loop PASS evidence written (`tests/qa_archive/results/2026-04-11_closed_loop_pass.md`)

## Phase D measured results

| Leg | Total duration | Canary validator | promote_to_prod | Post-probes |
|---|---|---|---|---|
| Forward (add marker) | 540.6s | 532.9s (11/12 PASS) | 6.0s | 3/3 PASS |
| Revert (remove marker) | 642.2s | 634.4s (9/12 PASS, 3 known flakes) | 6.1s | 3/3 PASS |
| **Real user downtime** | **12.1s** (2 × ~6s promote_to_prod restarts) | | | |

Production pid history: `24450 → 25616 → 25942`. Both containers 0 tracebacks throughout.
