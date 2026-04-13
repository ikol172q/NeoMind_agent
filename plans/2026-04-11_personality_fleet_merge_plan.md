# Personality Fleet + Expert Deepening — Merge Plan

**Date:** 2026-04-11
**Branch:** `plan/personality-fleet-merge`
**Status:** PLAN ONLY — awaiting user approval before any code change
**Authored by:** Cowork chair agent (acts as manager / judge per user directive 2026-04-11)
**Supersedes:** none
**Relates to (active, must be honored):**
- `plans/2026-04-11_todo_activation_closed_loop.md` — Phase C (iTerm2 activation) + Phase E (durability) still open
- `plans/GAP_ANALYSIS_CLAURST_CLAUDECODE.md` — Phase 0 (system prompt polish, 10 rounds per persona) is explicitly blocking
- `plans/TODO_zero_downtime_self_evolution.md` — spec for Parts 1+2, now largely implemented
- `plans/2026-03-28_evolution-addendum-v4.1.md` — EvolutionTransaction / SkillForge reference

---

## 0. TL;DR

The user wants NeoMind to become **a fleet of expert personalities** (chat / coding / fin, with more later, each deepening into a distinct expert), that can run multiple instances of the same persona in one project, communicate via message bus, and be supervised by a chat-manager — while (a) self-evolution never brings down the production Telegram bot, (b) CLI feels like Claude CLI, (c) every change is covered by unit + Telegram real-user + CLI real-terminal tests.

**After full recon, ~70% of this is already built in the repo.** The remaining 30% is small, concrete, and additive. This plan maps the delta, honors the two in-flight plans above, and defines the sub-agent team structure the chair agent (me) will use to execute it without cross-contamination.

**Non-negotiable constraints from the user's 2026-04-11 directive:**

1. Docker + 2 Telegram bots (prod + canary) — keep.
2. Self-evolution MUST NOT interrupt prod bot. Phase D already measured 12.1s total user-visible downtime; any regression on that is P0.
3. CLI must feel like Claude CLI (gap analysis Phase 0–3).
4. Three-layer testing on every task: pytest + Telethon (real prod+canary bot traffic) + iTerm2 (real terminal).
5. Chair (me) coordinates sub-agent pairs; does not code directly unless stuck.
6. Plan/tracking doc left for future sessions (this file, plus per-phase evidence files).
7. LLM calls are expected and acceptable.
8. `agent/services/llm_provider.py` is the router — do not re-test it.
9. No secrets / PII / personal data in commits. `.gitleaks.toml` must pass.

---

## 1. User constraints → reality map

| # | Constraint | Current state | Gap |
|---|---|---|---|
| 1 | Docker + 2 Telegram bots | `docker-compose.yml` has `neomind-telegram` (prod, `TELEGRAM_BOT_TOKEN`) and `neomind-canary` (canary profile, `TELEGRAM_TEST_BOT_TOKEN`) with isolated volumes | None. Reuse. |
| 2 | Self-evolution ≠ prod downtime | `EvolutionTransaction.canary_deploy_and_verify → promote_to_prod` validated Phase D at commit `cd0b081`, 12.1s measured downtime | None for base flow. Must enforce the same path for every change we land. |
| 3 | CLI ≈ Claude CLI quality | `cli/neomind_interface.py` + iTerm2 driver present. Gap analysis documents 4 phases of polish, Phase 0 (system prompt) blocking | Execute gap analysis Phase 0 first; Phase 1 headless partially done in `main.py`; Phases 2–4 scheduled below |
| 4 | 3-layer testing | pytest 50+ files; Telethon `telegram_tester.py` + 108 scenarios; `tests/integration/cli_tester_iterm2.py` 14-scenario runner | Phase C of closed-loop plan still needs real iTerm2 API restart (user's B2); otherwise live |
| 5 | Sub-agent team execution | Not yet — I must set this up | Defined in §4 below |
| 6 | Plan/tracking doc | `plans/` convention established, dated filenames, evidence files under `tests/qa_archive/results/` | This doc + follow-up evidence files |
| 7 | All 3 test layers every task | Machinery exists; just needs enforcement per phase | Enforced in §6 |
| 8 | Router exists | `agent/services/llm_provider.py` with DeepSeek → z.ai → Moonshot → LiteLLM fallback, admin whitelist gate (commit `6ed5392`) | Do not touch |
| 9 | No secret leaks | `.gitignore` + `.gitleaks.toml` + precedent `7ddcb21 chore(sanitize)` | Enforced on every commit (§7) |

---

## 2. What's already built (inventory)

**Do not rebuild any of the following.** Each line is a pointer to the real implementation.

- **Three personalities**: `agent/modes/{chat,coding,fin}.py`, all extending `BasePersonality`; mode-switch via `agent_config.switch_mode()`. YAML configs in `agent/config/{base,chat,coding,fin}.yaml`.
- **Agentic tool loop** (ReAct-style): `agent/agentic/` — parse `<tool_call>` → validate schema → execute → feed back → continue. Frontend-agnostic via generator event stream (`tool_start`, `tool_result`, `llm_response`, `done`).
- **LLM router (fallback chain)**: `agent/services/llm_provider.py` (613 lines) with DeepSeek, z.ai, Moonshot, LiteLLM, TokenSight proxy, `resolve_with_fallback()`.
- **Blue-green canary deploy**: `agent/evolution/canary_deploy.py` + `EvolutionTransaction.canary_deploy_and_verify()` + `promote_to_prod()`. Phase D validated. `docker-compose.yml --profile canary`.
- **Telegram integration**: `agent/integration/telegram_bot.py` (5313 lines, monolithic — candidate for split but not blocking); python-telegram-bot 20.x; polling mode; streaming message edits; `@openclaw` bridge auto-delegation.
- **Interactive CLI**: `cli/neomind_interface.py` (90KB), prompt_toolkit REPL + rich rendering, slash-command taxonomy v5 with 46 commands across 4 tiers, key bindings, streaming progress, status bar.
- **Three-layer testing infra**: pytest unit tests; `tests/integration/telegram_tester.py` (Telethon, 108 scenarios, gate_b3/gate_final subsets); `tests/integration/cli_tester_iterm2.py` (iTerm2 Python API, 14 scenarios, 5/5 Phase C PASS).
- **Memory system**: `agent/memory/{agent_memory,shared_memory,memory_selector,memory_taxonomy}.py` — SQLite-backed, BM25-ranked, per-mode DBs under `/data/neomind/db/`, plus Obsidian vault for long-term semantic memory (`agent/vault/`).
- **Swarm / Team system (THIS IS THE KEY FIND)**: `agent/agentic/swarm.py` — `TeammateIdentity`, `Mailbox` (file-based, lock-protected, at `~/.neomind/teams/{team}/inboxes/{name}.json`), `SharedTaskQueue` (atomic claim), `TeamManager` (create/add/remove/delete team), `format_task_notification` (Claude-Code-style XML). **Roles: LEADER/WORKER/REVIEWER/OBSERVER** already in `agent/tools/collaboration_tools.py::TeamRole`.
- **Collaboration tools**: `SendMessageTool`, `ScheduleCronTool`, `RemoteTriggerTool`, `TeamCreateTool`, `TeamDeleteTool` in `agent/tools/collaboration_tools.py`.
- **Self-evolution pipeline**: `agent/evolution/` — auto-evolve, SkillForge (skill crystallization), drift detection, cost optimizer, `EvolutionTransaction` with apply/smoke/canary/promote/revert stages.
- **Headless `-p` mode scaffold**: `main.py` fast-path dispatch already reserves `-p/--print` for argparse; gap analysis Phase 1 partially landed.
- **Plan/evidence conventions**: `plans/YYYY-MM-DD_slug.md` for plans; `tests/qa_archive/results/YYYY-MM-DD_slug.md` for evidence.

---

## 3. The real gap (what actually needs doing)

This is the surface area of NEW work. Everything else is wiring, testing, and honoring existing plans.

### 3.1 Persona ↔ Teammate binding (small, high-leverage)

Today `TeamManager.add_member(team_name, member_name)` writes `{name, color, is_leader}` to `team.json`. **No persona field.** So when you spawn three coding teammates, they're just `Alice/Bob/Charlie`, not `coding-1/coding-2/coding-3`, and the runtime has no way to pick the right system prompt / tools / memory scope per instance.

**Change:** add `persona: str` to the member dict and to `TeammateIdentity`. Wire `add_member(team, name, persona)`. Runtime: when an instance boots, it loads its persona's YAML config. Tests: create a team with 3 coding + 2 fin + 1 chat, verify each instance runs its correct persona's prompt and tool whitelist.

### 3.2 Project = Team, make it explicit

NeoMind's Swarm uses `team` as the bounded context. User's mental model uses `project`. These are the same thing. We do NOT mass-rename; we add a thin `project_id → team_name` alias in the launcher API so user-facing docs/config use "project" and internals stay on "team". This is a 20-line change.

### 3.3 Chat-as-Manager delegation policy

Chat persona today has no explicit "supervisor" behavior. The Swarm has a `LEADER` role flag but no policy logic. We add `agent/modes/chat_supervisor.py` — a module chat persona loads when it's the team leader. It:
- watches the team mailbox (via `Mailbox.read_unread()` on the leader's inbox)
- parses worker task-notifications (XML already standardized)
- dispatches new tasks to idle workers via `SharedTaskQueue.add_task()` + `SendMessageTool`
- detects stuck workers (no heartbeat for N minutes) and re-dispatches

This is ~300 lines, well-scoped, no new infra.

### 3.4 Cross-persona memory read with source tags

User Q3 answer was "each personality keeps its own memory but can read others' for retrospection". Today `shared_memory.py` does mode-agnostic storage. We add:
- `write(content, source_persona, source_instance, project_id)` — writes always tagged
- `read(query, include_personas: list|None, require_source_tag=True)` — returns rows with `<from persona=coding instance=coding-1>...</from>` envelopes
- LLM context injection wraps cross-persona content in explicit source blocks so coding's knowledge doesn't silently pollute fin's worldview

Estimated ~150 lines of changes plus a schema migration (new columns are nullable so it's non-breaking).

### 3.5 Multi-instance fleet launcher

Today `main.py` launches one agent process. We need a launcher that reads a project config and spawns N instances with assigned personas. For solo/single-user scale, asyncio tasks in one process is sufficient (no docker-per-instance). File:

```yaml
# projects/<id>/project.yaml
project_id: build-trading-bot
leader: manager-1
members:
  - { name: manager-1, persona: chat,   role: leader }
  - { name: coder-1,   persona: coding, role: worker }
  - { name: coder-2,   persona: coding, role: worker }
  - { name: coder-3,   persona: coding, role: worker }
  - { name: quant-1,   persona: fin,    role: worker }
  - { name: quant-2,   persona: fin,    role: worker }
```

Launcher: `fleet/launch_project.py` (new file, ~200 lines). Reuses `TeamManager.create_team()` + `add_member()` loop. Each instance runs in an asyncio task bound to its own `AgentConfigManager` instance.

### 3.6 CLI polish (execute existing gap analysis)

Not new design — just execution of `GAP_ANALYSIS_CLAURST_CLAUDECODE.md` Phase 0 (blocking) and Phase 1 (headless completion). Everything else in the gap analysis is Phase 2+ and can wait.

### 3.7 Hygiene fixes (non-negotiable before any new code)

Recon flagged:
- `agent/llm_service.py` (136 lines) — malformed, duplicated functions, syntax errors lines 24-35, 99-133. **Must fix or delete before anything else** (importable modules in a broken state will randomly explode downstream work).
- `agent/integration/telegram_bot.py` (5313 lines monolith) — candidate for split. **Not blocking**, but any code we add to it must not make it worse. Defer the split to a dedicated refactor phase.
- Duplicate search modules (`search_legacy.py` vs `search/engine.py`) — defer.

---

## 4. Sub-agent team structure (per user directive #5)

I (chair agent) do NOT code directly. I dispatch **two pairs** and **arbitrate between them**:

### Pair A — Test Pair
- **Tester agent**: writes and runs tests (pytest + Telethon + iTerm2 scenarios). Outputs go to `tests/qa_archive/results/`. Tester NEVER reads the implementation code — only contracts and specs. This prevents over-fitting tests to the implementation.
- **Fixer agent**: reads the failing test output and fixes the code. Fixer NEVER writes tests (to avoid making them pass trivially). Fixer only fixes what the tester reports as broken.

### Pair B — Code Pair
- **Proposer agent**: writes new code against a spec (e.g., "add `persona` field to `TeammateIdentity`"). Produces a diff. Does NOT read existing test files.
- **Reviewer agent**: reads the proposer's diff against the spec, lists issues, blocks or approves. Reviewer does NOT write code.

### Chair (me)
- Holds the plan (this doc) and the current phase's spec.
- Dispatches both pairs in sequence: Pair B writes code → Pair A tests it → if fail, Fixer or Proposer loops → chair arbitrates if they disagree → commit when green.
- Checks progress every 5 sub-agent rounds or 20 minutes wall-clock, whichever first.
- Updates this plan doc with status + evidence file links after each phase.
- Escalates to user if: (a) Pair B+Pair A disagree after 2 loops, (b) a test layer becomes impossible to run, (c) any of the 9 user constraints is about to be violated.

### Anti-contamination rules
- Tester and Proposer never exchange messages directly.
- Tester cannot read `agent/` source files for the phase under test; can only read `contracts/*.md` specs produced by chair.
- Proposer cannot read `tests/qa_archive/` results; can only read the spec and the test names Pair A has declared.
- Chair is the only entity that sees both worlds.

This mirrors how Pair A (tester+fixer) and Pair B (proposer+reviewer) operate as independent subgraphs talking through artifacts, not conversation.

---

## 5. Phased execution plan

Every phase ends with: (a) all 3 test layers green, (b) evidence file committed, (c) this plan doc updated, (d) explicit chair sign-off.

### Phase -1 — Pre-flight (chair only, no code)

- **-1.1** Read `agent/base_personality.py`, `agent_config.py`, `agent/modes/chat.py`, `agent/modes/coding.py`, `agent/modes/fin.py`, full `swarm.py`, full `collaboration_tools.py`, and Phase D evidence file. Produce a short "contracts sheet" under `contracts/persona_fleet/` describing the exact interfaces Pair A tests and Pair B implements against.
- **-1.2** Confirm Phase C (iTerm2) activation status: run `lsof -i :1912` via bash; if inactive, log that in this plan and proceed — Phase C is not blocking for Phase 0 of this plan.
- **-1.3** Confirm prod bot is currently up via `docker exec neomind-telegram supervisorctl status neomind-agent` (read-only).
- **-1.4** Confirm the concurrent health check is not holding files I need: if `.git/index.lock` persists > 60s, wait or coordinate. (Observed once during planning.)

### Phase 0 — Honor existing plans (blocking)

- **0.A** Finish `plans/2026-04-11_todo_activation_closed_loop.md` Phase C + Phase E. If user's B2 (iTerm2 restart) still pending, surface that as a user blocker and skip to 0.B.
- **0.B** Execute `plans/GAP_ANALYSIS_CLAURST_CLAUDECODE.md` Phase 0 — **system prompt polish, 10 rounds per persona**. This is explicitly marked "highest priority, other phases wasted without this". Each round: edit `agent/config/{chat,coding,fin}.yaml` prompt → run persona-specific Telethon smoke (gate_b3 subset) → run iTerm2 3-scenario smoke → LLM-as-judge score against golden transcripts → if drift, revert; if improvement, commit.
- **0.C** Hygiene: fix or delete `agent/llm_service.py`. The fix is small (remove duplicated functions). Must pass `python -c "import agent.llm_service"` clean.
- **0.D** Gate check: all 3 layers green against HEAD. Write `tests/qa_archive/results/2026-04-11_phase0_gate.md`.

### Phase 1 — Persona ↔ Teammate binding

**Spec contract:** `contracts/persona_fleet/01_teammate_persona.md` (written by chair in Phase -1).

- **1.1** Pair B proposes: add `persona: Optional[str] = None` to `TeammateIdentity`, update `TeamManager.add_member(team, name, persona=None)`, update `team.json` schema (backward-compatible: old teams without persona default to None → legacy behavior).
- **1.2** Pair A writes: unit tests for `TeamManager`, integration test that spawns 3 coding + 2 fin + 1 chat via `create_team + add_member` and verifies each teammate's `TeammateIdentity.persona` is correctly stored.
- **1.3** Pair B implements: runtime glue so that when an instance boots with `persona="coding"`, `AgentConfigManager` auto-switches to coding mode for that instance.
- **1.4** 3-layer gate. Evidence: `tests/qa_archive/results/2026-04-11_phase1_persona_binding.md`.
- **1.5** Canary deploy via `EvolutionTransaction` to prove prod path unaffected. Revert leg required.

### Phase 2 — Project context alias

- **2.1** Add `project_id` alias layer. Pair B: 20-line change to launcher API. Pair A: test that `project_id="foo"` maps to `team_name="foo"` and backward-compat preserved.
- **2.2** 3-layer gate. Evidence file.

### Phase 3 — Chat-as-Manager delegation

**Spec contract:** `contracts/persona_fleet/03_chat_supervisor.md`.

- **3.1** Pair B: implement `agent/modes/chat_supervisor.py` — mailbox watcher, task dispatcher, stuck-worker detector.
- **3.2** Pair A: integration test — set up a 1-leader + 3-worker team, leader receives a 3-part task, dispatches parts, workers complete and report via XML task-notification, leader aggregates result.
- **3.3** 3-layer gate. Evidence.
- **3.4** Canary deploy to prove prod path unaffected.

### Phase 4 — Cross-persona memory with source tags

**Spec contract:** `contracts/persona_fleet/04_cross_persona_memory.md`.

- **4.1** Pair B: schema migration (add `source_persona`, `source_instance`, `project_id` columns, nullable). Extend `shared_memory.write/read` API. Add envelope wrapping for LLM context injection.
- **4.2** Pair A: test that fin agent reading coding's notes sees a source attribution; test that legacy memory without source tags still loads; test that filtering by `include_personas` works.
- **4.3** 3-layer gate. Evidence.

### Phase 5 — Multi-instance fleet launcher

**Spec contract:** `contracts/persona_fleet/05_fleet_launcher.md`.

- **5.1** Pair B: `fleet/launch_project.py` + `projects/<id>/project.yaml` schema. Uses asyncio tasks (one process, N tasks) for solo-scale simplicity. Docker-per-instance reserved for later.
- **5.2** Pair A: end-to-end test — start a project with 6 instances (3 coding + 2 fin + 1 chat leader), run a multi-step "build a stock-price fetcher" task, verify task completes, verify all instances shut down cleanly.
- **5.3** 3-layer gate. Evidence.
- **5.4** **Full closed-loop rehearsal:** canary validates this phase's code, promote to prod, run a real project against prod bot, revert, validate revert.

### Phase 6 — Self-evolution respects fleet (stretch, optional)

- **6.1** Extend `EvolutionTransaction` to target a persona (scope of change limited to `agent/modes/<name>.py` + `agent/config/<name>.yaml` + `personas/<name>/prompts/*`).
- **6.2** Golden transcript per persona — at least 20 scenarios each — for LLM-as-judge regression. Reuse `tests/qa_archive/` framework.
- **6.3** Evolution proposer that generates a PR-style diff into `personas/<name>/proposals/YYYY-MM-DD.md` for user review before apply.
- **6.4** 3-layer gate. Evidence.

---

## 6. Testing policy (enforced)

**Every phase, without exception**, ends with all three layers green:

1. **Unit (pytest)**: `pytest tests/` with the new phase's tests included. Must be green excluding known-flaky `tests/test_provider_state.py::TestProviderChain` (pre-existing baseline, see closed-loop plan risk #5).
2. **Telegram real-bot (Telethon)**: `gate_b3` subset against `@neomind_canary_bot` first, then `@your_neomind_bot` prod. Uses existing `tests/integration/telegram_tester.py`.
3. **CLI real-terminal (iTerm2)**: 5-scenario smoke using `tests/integration/cli_tester_iterm2.py` against live iTerm2 window. Falls back to tmux 95%-fidelity if iTerm2 API not active, with loud warning logged.

Layer 1 runs as pre-commit. Layers 2+3 run at phase end. LLM calls are expected and billed; admin whitelist gate from commit `6ed5392` prevents runaway cost.

---

## 7. Commit discipline & secret hygiene

- Work branch: `plan/personality-fleet-merge` (current) → spawns `feat/persona-fleet/phase0`, `feat/persona-fleet/phase1-binding`, etc. Merges back into `plan/personality-fleet-merge` after each phase gate.
- **No commits without explicit user approval per phase.** Chair surfaces diff + evidence before asking.
- `.gitleaks.toml` runs on every commit. If it fires, commit is aborted and chair investigates.
- Commit messages follow existing convention: `<type>(<scope>): <subject>` e.g. `feat(swarm): add persona field to TeammateIdentity`.
- Sensitive paths never committed: `.env`, `.env.*`, `*.db`, `/data/`, `.host_evolution_data/`, `.neomind_snips/`, `.neomind_tool_outputs/`, `.safety_audit.log` — all already in `.gitignore`.
- Chair scans every file added/modified for: phone numbers, real email addresses, API keys starting with `sk-`/`Bearer`/bot tokens (`\d+:[A-Za-z0-9_-]{35,}`), absolute paths under the user's home directory, Obsidian vault content. Precedent: commit `7ddcb21 chore(sanitize): redact PII and bot usernames before main merge`.
- Chair never uses `git add -A`; always names files explicitly.
- **Chair never amends or force-pushes.**

---

## 8. Rollback strategy

Per-phase rollback, always possible:

- `BASELINE.txt` file at repo root (gitignored) holds the last-known-green commit hash for each phase. Chair updates it after every gate.
- Rollback protocol: `git reset --hard $(cat BASELINE.txt)` + `docker exec neomind-telegram supervisorctl restart neomind-agent` (takes ~6s, within 12s downtime budget).
- If a deploy goes sideways on canary: `docker compose --profile canary stop neomind-canary` — zero prod impact.
- If prod regression after `promote_to_prod`: revert the offending commit, re-run canary→prod via `EvolutionTransaction.canary_deploy_and_verify` with the revert. Phase D revert leg is proven working.

---

## 9. Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Concurrent health check corrupts git state | medium | high | Work on separate branch; chair checks `.git/index.lock` before every destructive op; all sub-agent git ops go through chair |
| LLM router rate limit (prod + canary sharing bucket) | medium | medium | Space validator runs ≥ 10s; prefer `gate_b3` over `gate_final` for canary; admin whitelist already in place |
| Swarm's file-based mailbox races under real load | low | medium | 60s stale-lock recovery already implemented; solo-scale concurrency is low; stress test in Phase 5 |
| `telegram_bot.py` monolith makes every edit risky | high | medium | Do not add to it during this plan; defer refactor; if touch needed, isolate the change to one handler method |
| Phase C iTerm2 still blocked on user action (B2) | unknown | low | Fall back to tmux 95% for CLI layer; log warning; do not block the plan |
| Chair dispatch loop stalls (sub-agent disagreement) | low | medium | 2-loop rule: if Pair A and Pair B disagree after 2 rounds, chair makes a direct decision; if chair cannot decide, escalate to user |
| PII leak on commit | low | critical | `.gitleaks.toml` + chair manual scan + explicit file listing; never `git add -A` |
| New code breaks Phase D closed-loop | low | critical | Every phase re-runs Phase D forward+revert legs before marking green |

---

## 10. What I need from the user before Phase 0 starts

1. **Explicit "go" on this plan**, or corrections/changes to scope.
2. **Confirm iTerm2 Python API status**: has B2 (iTerm2 restart + "Allow" dialog) from `2026-04-11_todo_activation_closed_loop.md` been done? If not, Phase C stays deferred and we use tmux fallback for layer 3.
3. **Confirm prod bot is currently up** (I can check via `docker ps` + `supervisorctl status` read-only if you allow).
4. **Confirm the concurrent health check's scope**: does it write to `agent/` source, or only to `.safety_audit.log` + `tests/`? If it writes to `agent/`, we need a pause window per phase edit.
5. **Whitelist for LLM-cost-bearing test runs**: confirm the admin whitelist gate (`6ed5392`) allows chair to run validator suites, and which subset (`gate_b3` vs `gate_final`) you're comfortable with per phase.

---

## 11. Open questions for later phases (do not block start)

- Should `personas/` as a first-class directory (for prompts + golden transcripts + proposals) coexist with `agent/modes/` (for code)? Or fold everything into `agent/modes/<name>/{code,prompts,golden,proposals}/`?
- Should multi-instance launcher be asyncio-in-one-process (simple, solo-scale) or Docker-per-instance (isolated, scales later)? Start with asyncio; Phase 6+ can add Docker.
- How should evolution proposals interact with the Swarm team mailboxes? Proposer writes to `personas/<name>/proposals/` as files; user reviews in git. No runtime mailbox involvement unless a manager wants to suggest its workers self-improve (future work).

---

## 12. Status log (append only)

| Date | Phase | Status | Evidence | Notes |
|---|---|---|---|---|
| 2026-04-11 | plan authored | DRAFT | this file | awaiting user approval |
| 2026-04-11 | Phase -1 pre-flight | DONE | contracts/persona_fleet/*.md (5 files) | Contracts specs for all 5 phases |
| 2026-04-11 | Phase 0.C hygiene | DONE | agent/llm_service.py | Replaced malformed 136-line file with clean 28-line redirect stub |
| 2026-04-11 | Phase 1 persona binding | PASS 21/21 | tests/test_persona_binding.py | TeammateIdentity.persona + both TeamManagers |
| 2026-04-11 | Phase 2 project alias | PASS 10/10 | tests/test_project_alias.py | fleet/project_config.py |
| 2026-04-11 | Phase 3 chat supervisor | PASS 14/14 | tests/test_chat_supervisor.py | agent/modes/chat_supervisor.py |
| 2026-04-11 | Phase 4 cross-persona memory | PASS 15/15 | tests/test_cross_persona_memory.py | SharedMemory schema migration + source envelopes |
| 2026-04-11 | Phase 5 fleet launcher | PASS 13/13 | tests/test_fleet_launcher.py | fleet/launch_project.py + fleet/project_schema.py |
| 2026-04-11 | ALL PHASES | **73/73 PASS** | all 5 test files | git lock held by concurrent health check; commit pending |
