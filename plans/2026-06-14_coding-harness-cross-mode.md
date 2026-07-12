# Coding harness: deploy-safe self-edit + fin↔coding code-change handoff + model-agnostic tool layer

Status: **design (not yet implemented)** · Created 2026-06-14 · Living checklist
Companion to `plans/2026-06-14_fin-evolution-phase-c.md` — same "harness spine".

> Why keep coding personality (despite Claude CLI): NeoMind must **edit its own
> code**; a master agent or sub-agent uses the coding persona to do it. When the
> fin evolution loop needs a *code* change (not just a prompt tweak), coding is
> the safe applier. Principle throughout: **CONNECT existing, don't duplicate,
> reduce complexity, stay model-swappable.**

---

## Part A — Make self-edit deploy-safe (audit-verified gaps, 2026-06-14)

The hard requirement: *self-edit → validate → only-then ask in Telegram → a
restart that can't fail (auto-rollback)*. Audit verdict: **~80% already built,
but the live self-edit tool is wired to the WEAK path** while the strong path
sits disconnected.

- WEAK (live today): `coding/tools.py:1843` → `SelfEditor.propose_edit` → per-file git commit → `request_restart` (`self_edit.py:213`, unconditional) → `restart_intent.json` → `telegram_bot.py:609-658` **notify-only**. No post-restart verify, no auto-rollback, no confirmation.
- STRONG (built, unused): `EvolutionTransaction` (atomic + git-tag anchor + concurrency lock + `__exit__` rollback + subprocess regression + **real telegram dry-run boot gate**, `transaction.py:257/450/520/580`) → `evolution_intent.json` → `verify_pending_evolution` at startup (`post_restart_verify.py:65-136`, `telegram_bot.py:535`) → git auto-rollback + **refuses to serve broken code**.

| Gap | Fix | Kind |
|---|---|---|
| **A1** live self-edit bypasses transaction/rollback (wrong intent file: `restart_intent.json` vs `evolution_intent.json`) | route `_exec_self_editor` through `EvolutionTransaction`; write `evolution_intent.json` → `verify_pending_evolution` fires for free | CONNECT (~30 ln) |
| **A2** never asks — auto-restarts unconditionally (`self_edit.py:213`) | confirmation gate **after** `txn.smoke_test()` passes: "✅ validated, restart to load? [yes/no]" (reuse inline-keyboard `telegram_bot.py:3455`) | small BUILD |
| **A3** DESTRUCTIVE tools unconfirmed in Telegram (`permission_manager=None`→`pass`, `agentic_loop.py:812`) | pass existing `PermissionManager` (already maps SelfEditor, `permission_manager.py:336`) into the TG agentic loop | CONNECT |
| **A4** shallow validation (import-only when no test, `self_edit.py:482`) | transaction's `regression_test()` + `telegram_dry_run()` already cover this | CONNECT (same as A1) |
| **A5** in-flight TG message lost on restart (`drop_pending_updates=True`, `telegram_bot.py:591`) | persist triggering `chat_id`/pending reply in the intent file (`notify_chat_id` field already exists) + re-ack post-restart | small BUILD |

**A1+A4 are one fix** (route through the transaction). A2 is the keystone — it
makes "only ask when correct" literally true (the ask only happens *after*
validation passes).

---

## Part B — fin → coding code-change handoff

fin's evolution proposes typed changes (`fin_evolve.py` `kind`): today
`system_md_append` (prompt), `investigate`/`review` (human). **Add `kind:
"code_edit"`** `{file_path, intent, optional patch}` for changes fin can't make
to a prompt (e.g. add an indicator to the evaluator, fix a reward-verifier bug,
add a data source).

**Route by kind (one applier, no new system):**
- `system_md_append` → `fin_evolve.gated_apply` (prompt edit, reward-gated). *(existing)*
- `code_edit` → **`delegate_to_mode("coding", apply_code_edit(proposal))`** → coding's `EvolutionTransaction` path (Part A). *(new wiring)*
- `investigate` / `review` → human. *(existing)*

`delegate_to_mode` = the SAME primitive as "chat orchestrates fin+coding"
(backed by `ChatSupervisor.dispatch_task` → `worker_turn.py:432` persona
branch). **Build it once, three consumers:** chat-orchestration, fin→coding
code-edits, master→sub-agent dispatch.

**Safety convergence:** a fin-proposed `code_edit` flows → coding transaction
**validates** (syntax/AST/regression/dry-run) → Part-A confirmation gate asks in
Telegram **only because it's validated** → apply + restart with auto-rollback.
This is exactly the "only ask when correct + can't-fail restart" requirement,
reached for free by composing Part A + Part B.

---

## Part C — De-duplication / complexity reduction (the overlap map)

Two "propose → gate → apply → verify → rollback" engines exist on different
substrates. **Do NOT merge them into one mega-class** (different safety models);
**do** stop them from duplicating:

| Concern | fin (prompt) | coding (code) | Consolidation |
|---|---|---|---|
| apply + rollback skeleton | `gated_apply` snapshot→apply→reward-verify→revert | `EvolutionTransaction` snapshot→apply→smoke→revert | share the *skeleton* (snapshot/keep/revert) via a thin `ChangeProposal{kind,target,gate,verify}` shape; gates/verifiers stay substrate-specific. **No third engine.** |
| code editing | — | `SelfEditor`/`transaction` | **fin reuses it via delegate; fin builds NO code-editor** |
| trajectory store | `episode_capture` | should also use `episode_capture` | **one store** — a code-change is an episode with an outcome too (already the single store, used by both packages) |
| reward/verify | validator + PnL | syntax/test/dry-run | keep separate (different substrates), but both report keep/revert through the same skeleton |

Net: ONE code-apply-and-rollback service (the transaction), ONE inter-mode
primitive (`delegate_to_mode`), ONE trajectory store (`episode_capture`). fin
contributes proposals + reward; coding contributes safe code application.

---

## Part D — Model-agnostic harness layer (DeepSeek placeholder + fallback)

**Requirement: must survive a model swap.** Every DeepSeek-native feature is an
*opt-in branch behind a capability flag, defaulting to the old/portable path.*

`ModelCapabilities` per (provider, model): `{native_tools, reasoning_effort,
thinking, prefix_cache, json_mode, fim, prefix_completion}`. Then at each call
site:

| Feature | native branch (if capable) | fallback / placeholder (default) | anchors |
|---|---|---|---|
| tool-calling | `tool_translator` native format (currently **dormant**) | **regex `tool_parser`** (current live path) | `llm/tool_translator.py`, `coding/tool_parser.py:53` |
| reasoning_effort | send `reasoning_effort` | omit (no-op) | finance already gates this (`fin_router.py`) |
| structured output | `json_schema`/strict → `json_object` | schema-in-prompt (extractors already do this) | `extractors/base.py:47` |
| prompt cache | keep byte-stable prefixes + read `prompt_cache_hit_tokens` | keep stable prefixes anyway (helps any provider); skip hit accounting | new |
| FIM / prefix-completion | `/beta` endpoints | normal completion | new |

**Rules:**
1. No native feature is hard-coded into a call path — always `if caps.X: native else: old`.
2. Default capability set = the conservative/portable one; a model opts *in*.
3. Switching models = flip the capability flags; fallbacks carry the behavior with zero call-site rewrites.

This is the "留 placeholder（或老做法）" guarantee: the old behavior is the
floor, native is a removable upgrade.

---

## Falsifiable acceptance

- [ ] A deliberately-broken self-edit (imports fine, breaks full boot) → restart **auto-rolls-back** and the bot keeps serving old code (verifies A1).
- [ ] Self-edit Telegram flow **asks** `[yes/no]` and the ask appears **only after** validation passed (verifies A2).
- [ ] A fin `code_edit` proposal reaches coding, gets validated, and applies through the **same** transaction path (verifies B + C, no duplicate code-applier).
- [ ] Flip `native_tools=False` for the active model → coding loop still works via regex fallback, zero call-site changes (verifies D).

## Phased order (when implementing — NOT yet)

1. **D-tool-calling first** (the shared geodesic): capability flag + wire `tool_translator` native ↔ keep `tool_parser` fallback. Reliable structured tool calls underpin everything below.
2. **A1+A4** route self-edit through `EvolutionTransaction` (lights up auto-rollback).
3. **A2** confirmation gate after smoke passes; **A3** wire PermissionManager.
4. **B** `delegate_to_mode` primitive + `kind:"code_edit"` routing.
5. **A5** in-flight message preservation; **C** factor the shared skeleton if duplication is real.

## Anchors (verified file:line, 2026-06-14)

- Self-edit live (weak): `coding/tools.py:1843`, `self_edit.py:105-244/194-203/213/243/482`, `self_restart.py:38`, `telegram_bot.py:591/609-658`.
- Strong path (unused): `transaction.py:77/162/257/450/520/580`, `post_restart_verify.py:65-136/79`, `telegram_bot.py:535`, `canary_deploy.py` (no caller).
- Perms: `agentic_loop.py:75/801-814`, `permission_manager.py:336`, `telegram_bot.py:4293-4307`.
- Tool-calling: `coding/tool_parser.py:53-92`, `llm/tool_translator.py` (dormant), `telegram_bot.py:5145` (no `tools=`).
- fin proposals (typed): `fin_evolve.py:54/62/70/197/210` (`kind`), `gated_apply`.
- Orchestrator: `fleet/launch_project.py:147/381`, `fleet/session.py:451`, `worker_turn.py:432`.
- Shared store: `agent/evolution/episode_capture.py` (record_episode / iter_recent_episodes), used by finance + evolution.

> Architecture/design only — no holdings, $, or personal data (PII guard scans on commit).
