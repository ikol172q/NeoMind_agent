# Fin Harness Evolution — Phase C: a live, money-grounded, auto-promoting loop

Status: **design (not yet implemented)** · Created 2026-06-14 · Living checklist

> Thesis: NeoMind doesn't lack capability — it lacks the **harness spine** that
> connects `model ↔ tools ↔ modes ↔ reward`. Self-evolution, 3-personality
> collaboration, and DeepSeek-native features are three faces of that one
> spine. Almost every gap is "built but not wired" → **CONNECT, don't BUILD.**

---

## 1. Diagnosis — verified 2026-06-14 (file:line)

Three claims that were previously *assumed* were checked against source + the
on-disk runtime data. The picture is more precise (and more honest) than the
earlier synthesis:

| Area | Verified finding |
|---|---|
| **General evolution scheduler** | **LIVE, not dormant.** `EvolutionScheduler.on_turn_complete` is called every turn (`agent/agentic/stop_hooks.py:149`, `agent/services/code_commands.py:1646`, `agent/services/__init__.py:518`); `on_session_start/end` at `services/__init__.py:494/537`, `core.py:1449`. Each turn runs reflection + `integration_hooks.periodic_tasks` (drift/KG/distillation); every 50 turns runs the daily cycle. **BUT it evolves against a *general* substrate (learnings / reflection notes / generic drift) — NOT against a money reward.** |
| **Cross-persona orchestrator (fleet)** | **REAL but not auto-triggered.** `ChatSupervisor.dispatch_task` → per-persona worker (`fleet/session.py:451`, `fleet/launch_project.py:381`, `fleet/worker_turn.py:432`). Reachable only via the explicit CLI fleet feature (`cli/neomind_interface.py`). `fleet/run.py` has no `__main__`. **A normal chat message does NOT trigger fin/coding delegation.** |
| **Reward training data** | **STARVED.** `_evolution/outcomes/pending.jsonl` = 4 rows = **1 real decision + 3 synthetic rollout**; **no `realized.jsonl`** (backfill has produced no PnL-labeled outcomes). ~76 episodes captured under `_evolution/episodes/` but the outcome ledger is effectively empty. |

**Refined binding constraint:** not wiring — **DATA**. The loops are mostly
wired; they have ~1 real, money-grounded labeled decision to learn from. Two
sides of one hole:
- (a) general evolution runs, but optimizes *generic metrics*, not "did it make money";
- (b) the money-grounded reward loop is **data-starved** AND its promote half is **off**
  (`evolve_daily` not in `DEFAULT_JOBS`; `gated_apply` has no scheduled caller).

→ **There is no single live, money-grounded, auto-promoting evolution loop fed
by enough real data.** Building that is Phase C.

---

## 2. Design — the 5-stage loop (each tagged CONNECT vs BUILD)

**First principle:** a reward-driven loop is bottlenecked by *how much real,
money-grounded labeled data* it has. Diagnosis ③ proves today = ~1. So the
design solves **data first**, then reward, then mine/propose/promote.

### Key insight — paper trading is the untapped data pump
The trading desk already runs **paper auto-entry/exit** (`agent/finance/trading_desk.py`).
Every paper setup makes a decision (enter/exit) that real prices score with PnL
a few days later = a **money-grounded, reward-labeled decision stream that does
NOT depend on manual usage**. It is currently **not wired into the
`fin_outcome` ledger** (paper is a separate subsystem). Connecting it turns the
data rate from ~1/month into tens/week.

| # | Stage | Move | CONNECT / BUILD |
|---|---|---|---|
| 1 | **Data pump** (top priority — kills starvation) | wire `paper_trading` setup entry/exit → `fin_outcome.record_decisions`; one-time backfill of real decisions from the ~76 episodes; let existing `fin_outcome.backfill` PnL-label them | CONNECT (+ 1 one-off script) |
| 2 | **Reward credibility** (verify the verifier FIRST) | fix `response_validator` Rule 3 false positives (extracts fake prices from threshold/example $ amounts) + unit test. `fin_reward.score_episode` already = 0.6 validator + 0.4 PnL outcome — it just has no data | fix 2 sites + test |
| 3 | **mine → propose** | `fin_evolve.mine` (outcome-aware) clusters low-reward / money-losing decisions → `propose` drafts prompt/router/rubric edits | ALREADY BUILT |
| 4 | **gated auto-promote** | `fin_evolve.gated_apply`: baseline → apply → verify → auto-revert if not better; golden-regression + PSI-drift safety gates dominate. Risky/ambiguous edits stay **proposal-only for human review** (honors the "改动给建议" decision) | ALREADY BUILT |
| 5 | **trigger** | add `evolve_daily` to `DEFAULT_JOBS` → daily backfill → mine → draft runs unattended | ONE LINE |

### Grounding the general evolution (diagnosis ① hole)
Don't tear out `agent/evolution/` (it runs, it has value). Instead feed the
fin-mode `EvolutionScheduler` the **fin reward signal**, so reflection/drift
reflect on "did it make money" rather than generic metrics. Also CONNECT.

---

## 3. Falsifiable success metrics (the real checklist)

- [ ] **Data:** outcomes ledger ≥ **30 real PnL-labeled decisions / week** (from ~1/month).
- [ ] **Verifier:** Rule 3 false-positive rate = **0** on a held-out reply set; verifier validated *before* any auto-apply.
- [ ] **Loop runs:** `evolve_daily` runs daily; ≥1 gated proposal/week.
- [ ] **Promotion is honest:** `gated_apply` auto-keeps only edits with paired Δreward ≥ 0.05 AND win-rate ≥ 0.6 over ≥ n_min paired queries; everything else auto-reverts.
- [ ] **End-to-end:** measurable reward lift on a frozen held-out decision set after N weeks — i.e. the agent demonstrably got better at the task without a human editing the prompt.

---

## 4. Phased build order (when implementing — NOT yet)

- **C0 — verifier first.** Fix Rule 3 + test. (Never optimize a metric whose verifier has a bug.)
- **C1 — data pump.** paper→outcome wiring + one-off episode backfill. Watch the ledger fill.
- **C2 — turn on the loop.** `evolve_daily` → `DEFAULT_JOBS`, draft-only at first; inspect proposal quality on real data.
- **C3 — enable gated auto-promote** for low-risk edit classes only; keep risky classes proposal-only.
- **C4 — ground general evolution** in fin reward for fin mode.

---

## 5. Open / unverified (carry forward)

- Does `paper_trading` expose setup entry/exit events in a shape `fin_outcome.record_decisions` can consume? (verify at C1 start)
- Do the general engines (reflection/prompt_tuner/skill_forge) produce anything *used* downstream, or only logged? (impacts whether C4 is worth it)
- Rollout decisions (`session_id` prefix `rollout-`) must be filtered out of the *real-PnL* ledger to avoid polluting the money signal.

---

## 6. Anchors (verified file:line, 2026-06-14)

- Loop: `agent/finance/fin_outcome.py` (record_decisions / backfill / load_realized_index), `fin_reward.py:score_episode`, `fin_evolve.py` (mine / propose / gated_apply), `scheduler/jobs/evolve_daily.py` (NOT in `DEFAULT_JOBS`, see `scheduler/core.py`).
- Verifier: `agent/finance/response_validator.py` (Rule 3 price regex + source patterns).
- Data pump source: `agent/finance/trading_desk.py` (paper setups).
- Live capture: `dashboard_agent/agent.py:_finalize_turn` → `episode_capture.record_episode` + `fin_outcome.record_decisions`.
- General scheduler (live): `agent/evolution/scheduler.py`, called from `services/__init__.py:494/518/537`, `stop_hooks.py:149`, `code_commands.py:1646`, `core.py:1449`.
- Runtime data: `_evolution/outcomes/pending.jsonl` (1 real), `_evolution/episodes/*.jsonl` (~76).

> Note: this doc is architecture/design only — **no holdings, $ amounts, or
> personal data** (the PII guard scans it on commit). Keep it that way.
