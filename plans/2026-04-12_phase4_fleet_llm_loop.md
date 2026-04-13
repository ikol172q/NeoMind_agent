# Phase 4 Pre-flight — Fleet Per-Member LLM Loop

**Date:** 2026-04-12
**Status:** DRAFT v2 — awaiting user approval before any code change
**Supersedes:** extends `plans/2026-04-12_fin_deepening_fusion_plan.md` §4 Phase 4
**Relates to:** `contracts/persona_fleet/05_fleet_launcher.md` (original Phase 5 contract — known-incomplete `_run_member`)

### Revision history
- **v1 (2026-04-12 earlier)** proposed Options A/B/C/D, landed on **Option C** (`asyncio.Lock` + singleton monkey-patch). User rejected: "I want sub-agents that can run independently, without interfering with each other, in parallel — that's not what C does." Pointed me at `~/Desktop/nirholas` for multi-agent patterns to borrow.
- **v2 (this doc)** — after reconnaissance of nirholas, adds **Option E** (contextvars.ContextVar + transparent proxy pattern, nirholas's `AsyncLocalStorage` ported to Python). True parallelism, zero lock, zero refactor of existing callers. A/B/C/D analysis retained for traceability — they explain why naive approaches don't work and why E is the answer.

---

## 0. TL;DR

Phase 4 closes the gap flagged in commit `625a09b` (Phase 5 fleet launcher): `FleetLauncher._run_member` today is a **bare mailbox + task-queue poll loop** — it never actually invokes an LLM. Phase 4 wires real LLM turns per member, persona-correctly, with **true parallelism** (not serialized), without breaking the existing single-session CLI / Telegram prod path.

**The core insight from reconnaissance of `~/Desktop/nirholas`** (Claude Code's own multi-agent implementation): they achieve sub-agent isolation + parallelism without subprocess spawning by using JavaScript's `AsyncLocalStorage` — a per-async-task scoped store where setting a value in one task is invisible to sibling tasks. Python's `contextvars.ContextVar` has exactly the same semantics. `asyncio.create_task()` automatically captures a context snapshot at creation time, and any `ContextVar.set()` call inside the task only mutates that task's copy.

**This means**: we replace `agent_config.agent_config` (a module-level `AgentConfigManager` instance) with a **transparent proxy** that forwards every attribute access to `_current_config.get()`, a `ContextVar[AgentConfigManager]`. Each fleet worker task sets its own `AgentConfigManager(mode=member.persona)` as the current config — and from then on, every read of `agent_config.<anything>` inside that task returns the per-member view. Sibling tasks see their own views. Legacy CLI / Telegram sessions with no contextvar override see the default instance, unchanged.

**Zero lock. Zero serialization. Zero refactor of the 7 files that do `from agent_config import agent_config`. Full parallelism.** Details in §3.3.5 (Option E).

---

## 1. What Phase 4 must deliver

From `plans/2026-04-12_fin_deepening_fusion_plan.md` §4 Phase 4 + user Q2 guardrails:

1. **`FleetLauncher._run_member`** actually runs LLM turns, not just polls mailboxes.
2. **Persona correctness** — when a `fin` worker claims a task, it runs with the fin persona's system prompt + tool whitelist. Same for `coding` and `chat`. Mixing is a P0 bug.
3. **Persona-agnostic fleet code** (Q2 hard constraint) — the launcher code must contain **zero** `if persona == "fin"` branches. `fin-core` is one project among many; `coding-refactor-sprint` must use the exact same code path with no changes.
4. **`projects/fin-core/project.yaml`** as the first real project config: 1 chat leader, 2 fin workers (realtime / research), 2 coding workers (dev support).
5. **Two end-to-end tests** prove the wiring works:
   - "Analyze AAPL using data_hub + quant_engine indicators, return SignalSchema JSON" → a fin-worker claims it, runs data_hub, parses the signal, writes the analysis under `~/Desktop/Investment/fin-core/analyses/`, reports back via XML notification to the leader.
   - "Add volume-weighted RSI to quant_engine.indicators" → a coding-worker claims it, edits `agent/finance/technical_indicators.py`, reports back.
6. **Canary forward + revert leg** proves the Phase 4 code ships without touching prod Telegram bot visibility (≤12.1s downtime budget per Phase D).
7. **Regression-free** — `test_personality_differentiation` already has 10 stale failures but chat/coding/fin imports must still be clean; no new fleet-launcher test may break.

## 2. What Phase 4 will NOT do (scope guardrails)

Explicitly out of scope — each of these is a valid follow-up phase, not part of Phase 4:

- **Parallel LLM execution** — multiple fleet workers calling LLMs simultaneously. Not required for solo scale (≤5 workers / day, $15/mo cap); a single serialized execution pipeline meets the spec with 1/10th the risk. §3 Option C.
- **Refactoring `agent/core.py` to drop the `agent_config` module singleton.** That's a cross-cutting change touching ~15 files and is its own mini-phase if the user wants it later.
- **Prompt versioning + ECE calibration** — that's Phase 6 per fusion plan §4, deferred.
- **Outcome tracking (3-day-forward price labels for accuracy KPI)** — still deferred.
- **Docker-per-instance fleet** — Contract 05 already commits to "asyncio tasks in one process for solo scale".
- **Cross-persona memory writes from workers** — already built in Phase 4 of personality-fleet merge (`SharedMemory.get_cross_persona_context`); Phase 4 of the fin plan just USES it, doesn't extend it.

## 3. Architecture tension + options

### 3.1 The problem

`agent_config.py:464` has:
```python
agent_config = AgentConfigManager()  # module-level singleton
```

And the following files import the singleton object directly at module top:

| File | Line | Usage |
|---|---|---|
| `agent/core.py` | 66 | Drives `NeoMindAgent.__init__` behavior — model, prompts, safety, tools |
| `agent/base_personality.py` | 13 | Base class every persona inherits |
| `agent/modes/chat.py` | 20 | Chat persona init |
| `agent/modes/coding.py` | 21 | Coding persona init |
| `agent/modes/finance.py` | 20 | Fin persona init |
| `agent/query_engine.py` | 459 | Runtime query path |
| `agent/state_manager.py` | 167 | Runtime state |

Telegram bot already works around this in 4 places (`agent/integration/telegram_bot.py:834, 3202, 3254, 3462`) by instantiating a **new** `AgentConfigManager` directly — which means the class supports multi-instance construction, but the consumers don't. Those 4 Telegram sites are single-threaded and temporary-scope, so they don't hit the shared-state problem.

The root issue: **if two asyncio tasks in one process both want to run with different personas, they can't just each hold their own `AgentConfigManager` instance — every call into `NeoMindAgent` / the mode classes will reach through the module-level singleton and see whoever last wrote to it**.

### 3.2 Options

| Opt | Approach | Parallel? | Pros | Cons | Fit |
|---|---|---|---|---|---|
| **A** | Monkey-patch `agent_config.agent_config = member_cfg` around each worker turn | No (broken) | Zero refactor, tiny code | **Broken under asyncio** — an `await` inside the critical section yields to another coroutine which sees the wrong singleton | ❌ |
| **B** | Refactor `core.py` + `base_personality.py` + 3 mode files to accept `agent_config` as a constructor param | Yes | Architecturally correct | Cross-cutting change, 15+ files, big blast radius, high risk of breaking prod bot | ❌ for Phase 4 |
| **C** | Serialize fleet LLM turns with an `asyncio.Lock`; inside the critical section, monkey-patch the singleton | **No** — workers take turns | Small diff | Not actually parallel. User rejected: "sub-agents should run independently and in parallel, not take turns" | ❌ user rejected v1 |
| **D** | Build a standalone `WorkerRuntime` that bypasses `NeoMindAgent` entirely — reads yaml directly, calls `llm_provider`, runs a minimal tool loop | Yes | No singleton dependency | Re-implements a lot of NeoMindAgent logic; behavior drift between CLI/telegram bot and fleet workers | ❌ for Phase 4 |
| **E** | Replace the `agent_config` module global with a **`contextvars.ContextVar` + transparent proxy** (ported from nirholas's `AsyncLocalStorage` pattern) | **Yes, true parallelism** | Zero lock, zero refactor of callers, asyncio auto-propagates context copies to child tasks | Introduces a proxy object — one subtle thing to audit | ✅ **Chosen v2** |

### 3.3 Why A/B/C/D don't meet the parallelism requirement

- **A** is broken before it ships — monkey-patching a module global during an `await` lets sibling coroutines observe the wrong value. Not safe under asyncio at all.
- **B** achieves parallelism but requires touching 15+ files that currently do `from agent_config import agent_config`. Any bug in that refactor risks the prod Telegram bot. Out of Phase 4 scope.
- **C** was my v1 recommendation and is the one the user explicitly rejected. Even though it's correct under a lock, it means at any moment exactly ONE fleet worker is making an LLM call. That's "turns", not "parallel". The user wants sub-agents that "run independently without interfering with each other, in parallel" — which C does not provide.
- **D** gives parallelism but creates two divergent agent runtimes (NeoMindAgent for CLI/Telegram, WorkerRuntime for fleet). Over time they drift apart, bugs appear in one but not the other, tests are duplicated. High long-term maintenance cost for a Phase 4 tactical gain.

### 3.3.5 Option E (chosen v2): ContextVar proxy + per-task config

**Reconnaissance of `~/Desktop/nirholas`** (Claude Code's own multi-agent system, TypeScript/Bun) shows they solve exactly this problem. Key file: `src/utils/agentContext.ts:93–110`. They use JavaScript's `AsyncLocalStorage` — a per-async-execution-chain store where:

- Each async task sees only its own snapshot of the stored value
- Reading the value requires no parameter drilling — callers just ask for the "current context" and get the right one
- Child tasks spawned from a parent inherit a COPY of the parent's context at spawn time
- Sibling tasks are fully isolated — setting a value in task A does not leak into task B

**Python has the exact same primitive: `contextvars.ContextVar`.** It was added in Python 3.7, and `asyncio` was updated at the same time to automatically copy the current context into each new `Task` created by `asyncio.create_task()`. The semantics match nirholas's `AsyncLocalStorage` 1:1:

```python
from contextvars import ContextVar

_current_config: ContextVar["AgentConfigManager"] = ContextVar(
    "neomind_current_agent_config",
    default=_default_manager,
)

async def worker_a():
    cfg = AgentConfigManager(mode="fin")
    _current_config.set(cfg)       # affects worker_a only
    await do_fin_work()             # sees mode="fin"

async def worker_b():
    cfg = AgentConfigManager(mode="coding")
    _current_config.set(cfg)       # affects worker_b only
    await do_coding_work()          # sees mode="coding"

async def main():
    # Both tasks run concurrently, each in its own context copy.
    await asyncio.gather(
        asyncio.create_task(worker_a()),
        asyncio.create_task(worker_b()),
    )
```

**This just works. Python guarantees it.**

#### Transparent proxy — how existing callers stay unchanged

The 7 files that currently do `from agent_config import agent_config` and then access `agent_config.model`, `agent_config.mode`, `agent_config.system_prompt`, etc., MUST keep working. We achieve this by making `agent_config` a **proxy object** whose attribute access forwards to `_current_config.get()`:

```python
# agent_config.py (sketch — not final)

from contextvars import ContextVar
from typing import Any


class AgentConfigManager:
    # ... existing class body, unchanged ...


# Default instance the legacy callers (CLI, Telegram bot, single-session
# paths) see when no contextvar override is in effect.
_default_manager = AgentConfigManager()

# The contextvar that holds the "current" config for this async task.
# asyncio automatically copies this into each new Task's context.
_current_config: ContextVar[AgentConfigManager] = ContextVar(
    "neomind_current_agent_config",
    default=_default_manager,
)


class _AgentConfigProxy:
    """Transparent forwarder to the current-context AgentConfigManager.

    Every attribute access hits `_current_config.get()`, which returns
    whichever AgentConfigManager is bound to the caller's asyncio task.
    Legacy callers (CLI / Telegram) see the default instance. Fleet
    workers that called `set_current_config(their_cfg)` see their own.

    Instances of this class are deliberately NOT AgentConfigManager
    subclasses — the proxy is only an attribute forwarder. Nothing in
    the codebase does `isinstance(agent_config, AgentConfigManager)`
    (verified via grep 2026-04-12 during Phase 4 pre-flight) so the
    proxy is invisible to every current caller.
    """

    def __getattr__(self, name: str) -> Any:
        # Forward any attribute read to the current task's config.
        return getattr(_current_config.get(), name)

    def __setattr__(self, name: str, value: Any) -> None:
        # Forward writes too, so `agent_config.some_flag = True`
        # mutates the current task's config, not the proxy.
        setattr(_current_config.get(), name, value)

    def __repr__(self) -> str:
        return f"<AgentConfigProxy → {_current_config.get()!r}>"


# Public symbols — legacy callers keep importing `agent_config`.
agent_config = _AgentConfigProxy()


def set_current_config(cfg: AgentConfigManager):
    """Bind a specific AgentConfigManager as 'current' in this async
    task's context. Returns a Token the caller can use to reset, or
    just let the task end (context is automatically dropped then).
    """
    return _current_config.set(cfg)
```

#### The fleet launcher's worker body — dead simple

```python
# fleet/launch_project.py (sketch — not final)

import agent_config as _ac_module
from agent_config import AgentConfigManager

class FleetLauncher:
    async def _run_member(self, member):
        # This IS a Task created by asyncio.create_task() in start().
        # Python has already given us our own context copy at this point.
        # Anything we set below only affects our own task's view.
        member_cfg = AgentConfigManager(mode=member.persona)
        _ac_module.set_current_config(member_cfg)

        # From now on, `agent_config.model` / `.mode` / `.system_prompt`
        # / etc. — read from ANY file in the stack — return values from
        # THIS member's instance. Other member tasks (running concurrently
        # via asyncio.gather) see their own values. Legacy CLI/Telegram
        # running anywhere else sees the default instance. No interference.

        mailbox = self._mailboxes[member.name]
        while self._running:
            # existing mailbox/shutdown/supervisor logic stays unchanged

            if member.role == "worker":
                task = self._task_queue.try_claim_next(member.name)
                if task:
                    # await does not cross tasks; our context is preserved
                    result = await self._execute_task(member, task)
                    self._report_task_result(member, task, result)

            await asyncio.sleep(0.5)
```

**No lock. No try/finally. No singleton swap.** The worker task is born with its own context, sets its own config once, and runs to completion. Sibling tasks have sibling contexts. Python handles the isolation.

#### Scenarios walkthrough

| Scenario | What happens | Result |
|---|---|---|
| **Legacy CLI startup** (`main.py` imports `agent_config`, constructs `NeoMindAgent`) | `agent_config.model` → proxy → `_current_config.get()` → default `_default_manager` instance → returns "deepseek-reasoner" | Unchanged. Zero regression. |
| **Telegram bot single session** (existing 4 direct `AgentConfigManager()` sites in `telegram_bot.py`) | Those sites still construct their own instances and use them directly, bypassing the proxy | Unchanged. Zero regression. |
| **Fleet launches 2 fin workers + 2 coding workers simultaneously** | Each of the 4 tasks created by `asyncio.create_task(_run_member)` gets its own context copy. Each sets its own config. `asyncio.gather()` runs them concurrently. Each LLM call reads config from its own task's context | **True parallelism. Four LLM calls in flight. Zero cross-contamination.** |
| **One worker raises mid-turn** | The task's context dies with the task. No restoration needed. Sibling tasks are unaffected. | Exception safety is automatic. |
| **A fleet worker accidentally calls `agent_config.switch_mode("chat")` mid-turn** | Mutates THIS task's `AgentConfigManager` instance (via proxy → contextvar → instance). Other tasks see their own instances, unchanged. | Self-damage, no cross-contamination. Test covered. |
| **Legacy code inside a fleet worker turn** (e.g. fin persona's existing code reads `agent_config.system_prompt`) | `system_prompt` read → proxy → contextvar → member's `AgentConfigManager(mode="fin")` → correct fin system prompt | The whole existing fin persona codebase "just works" inside the fleet worker, because its module-level `from agent_config import agent_config` now returns the per-task view. |

#### Risks specific to Option E

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| E1 | A caller somewhere introspects `agent_config` with `isinstance` / `type()` / `__class__` — proxy fails that check | very low (verified by grep) | medium | Grep audit in the commit. If any are found, either rewrite the caller to use duck typing OR add a `__class__` descriptor to the proxy. None found in pre-flight. |
| E2 | A caller does `cfg = agent_config; ...later... cfg.model` — captures the proxy, not a specific instance. Later reads see whichever context is current THEN, not at capture time. | medium | low | This is the SAME semantics as today (since `agent_config` is already a singleton that can be mutated). In practice the legacy callers read the attribute once during construction (e.g. `self.model = agent_config.model` in `core.py:230`), so they capture the current value at that moment — correct behavior. |
| E3 | A caller pickles / deepcopies `agent_config` | very low | medium | Grep verified none exist. If any appear later, proxy can implement `__reduce__` / `__deepcopy__` to forward. |
| E4 | `_current_config.get()` returns the default even though a worker set its own — indicates the context isn't propagating through some async boundary | low | high | Add a Phase 4 integration test that asserts `_current_config.get() is member_cfg` from deep inside an `await`-chain inside `_execute_task`. If it fails, we catch it in CI. |
| E5 | A background thread (not an asyncio task) reads `agent_config` — contextvars work per OS thread too, so a thread not spawned from an async context sees the default | low | low | Document: fleet workers are always asyncio tasks. If any background threads need per-agent config in the future, they use `contextvars.copy_context()` explicitly. |
| E6 | Proxy's `__setattr__` silently mutates the default instance when no worker context is active | medium | low | This is the existing behavior — legacy callers can already mutate the singleton. Nothing changes for them. |

#### What Option E does NOT require

- ❌ No `asyncio.Lock`
- ❌ No monkey-patching
- ❌ No `try/finally` singleton restoration
- ❌ No refactor of `core.py`, `base_personality.py`, or the 3 mode files
- ❌ No changes to any of the 4 Telegram direct-construction sites
- ❌ No new `WorkerRuntime` duplicating NeoMindAgent logic
- ❌ No subprocess / worker_thread isolation
- ❌ No serialization of fleet LLM calls
- ❌ No change to prod bot startup

#### What Option E DOES require

- ✅ ~50 LOC change to `agent_config.py` — introduce `ContextVar`, `_default_manager`, `_AgentConfigProxy`, `set_current_config`
- ✅ ~10 LOC change to `fleet/launch_project.py::_run_member` — call `set_current_config(member_cfg)` at task entry
- ✅ ~20 LOC helper module `fleet/worker_turn.py` for the actual task execution (persona branching lives here, launcher stays agnostic)
- ✅ Unit tests that prove the context isolation holds under concurrent `asyncio.gather`
- ✅ Regression test that legacy callers (CLI-shaped test) still see the default config

## 4. What `_execute_task` actually does

The critical section in Option C does three things per worker turn:

1. **Task → prompt**: take `task["description"]` as the user-visible prompt. Optionally wrap it with a persona-aware system prompt from `member_cfg`.
2. **LLM call via `llm_provider.resolve_with_fallback`**: go through the router's existing fallback chain (DeepSeek reasoner → z.ai → Moonshot → LiteLLM). Default model is **DeepSeek reasoner** per the 2026-04-12 memory entry. No new model-selection logic in the fleet.
3. **Parse the response**:
   - If the persona is `fin` → parse via `parse_signal()` (Phase 1.1), write result via `investment_projects.write_analysis()` (Phase 0.A), return a structured summary.
   - If the persona is `coding` → interpret the response as a natural-language task description, run it through the existing agentic loop (which handles `<tool_call>` parsing + Edit/Bash dispatch). This is where the "add VWR to indicators" test lives.
   - If the persona is `chat` (a worker, not the leader) → just return the text. Chat-as-worker is edge case; main chat role is leader.

**Parking lot concern**: step 3 for coding workers requires the existing agentic loop to run inside the lock. That loop can be long (multiple tool calls, file edits, tests). The lock being held that long blocks other fleet workers from starting. At solo scale ≤5 workers this is fine, but it's the exact hot spot a future Option B refactor would fix.

## 5. Sub-task breakdown

Each sub-task ends with: (a) pytest green, (b) cross-persona regression still shows only the 15 classified-stale failures, (c) explicit sign-off before moving to the next.

### 4.A — `agent_config.py` contextvar + proxy (~30m)

The foundation. Everything else depends on this landing first.

- Introduce `_default_manager = AgentConfigManager()`
- Introduce `_current_config: ContextVar[AgentConfigManager]` with default = `_default_manager`
- Replace the module-level `agent_config = AgentConfigManager()` with `agent_config = _AgentConfigProxy()`
- Add `set_current_config(cfg)` public helper returning a `Token`
- Keep `AgentConfigManager` class unchanged
- **Unit tests are the gate for this commit** (4.D below tests the isolation property)

**Grep audit before committing**: re-run the `isinstance(.*AgentConfigManager)` and `(deepcopy|pickle).*agent_config` checks. Zero matches stays the sign the proxy is safe.

### 4.B — `fleet/worker_turn.py` helper module (~1h)

New file — extracts the "task → prompt → LLM → parse → write back" logic so `_run_member` stays thin and the logic is unit-testable without spinning up an asyncio event loop.

- `async def execute_task(member: MemberConfig, task: dict) -> dict`
- Branches on `member.persona` internally (this is the ONE place persona branching lives — fleet launcher code stays agnostic above it)
- Returns `{"status": "completed" | "failed", "result": str, "artifacts": [...]}`
- Reads `agent_config.mode` / `.system_prompt` / `.model` — these reach through the proxy to whichever config is bound in the caller's task context
- Unit tests mock `llm_provider.resolve_with_fallback` so they don't burn real LLM budget

### 4.C — `fleet/launch_project.py` hookup (~30m, now much simpler)

- Import `AgentConfigManager` and `set_current_config` from `agent_config`
- At the top of `_run_member`, before the `while` loop, construct the per-member config and bind it:
  ```python
  member_cfg = AgentConfigManager(mode=member.persona)
  set_current_config(member_cfg)
  ```
- When a task is claimed, `await self._run_worker_turn(member, task)` calls `fleet.worker_turn.execute_task(member, task)` and reports the result
- **No lock, no try/finally, no monkey-patching** — Python's asyncio context propagation handles isolation for free
- **No persona branches in `launch_project.py`** — grep audit in the commit confirms zero `"fin"` / `"chat"` / `"coding"` string literals

### 4.C — `projects/fin-core/project.yaml` (~15m)

First real project config. Persona-agnostic — the launcher treats it identically to any future `projects/coding-refactor-sprint/project.yaml`.

```yaml
project_id: fin-core
description: "Fin persona core — realtime + research + dev support"
leader: mgr-1
members:
  - { name: mgr-1,      persona: chat,   role: leader }
  - { name: fin-rt,     persona: fin,    role: worker }
  - { name: fin-rsrch,  persona: fin,    role: worker }
  - { name: dev-1,      persona: coding, role: worker }
  - { name: dev-2,      persona: coding, role: worker }
settings:
  stuck_timeout_minutes: 5
  max_concurrent_tasks: 3
```

Also: `projects/coding-smoke/project.yaml` — a tiny 1-leader + 1-coding-worker project used as the Q5 regression test to prove fleet is persona-agnostic (coding-only fleet works identically).

### 4.D — Unit tests: `tests/test_agent_config_contextvar.py` + `tests/test_worker_turn.py` (~1.5h)

**`tests/test_agent_config_contextvar.py` — Option E's isolation property** (highest priority, must land with 4.A):

- `test_default_config_returned_when_no_context` — fresh interpreter, `agent_config.mode` reads the default singleton
- `test_set_current_config_binds_in_task` — inside an `asyncio.run(...)` task, `set_current_config(fin_cfg)` makes `agent_config.mode == "fin"`
- **`test_sibling_tasks_isolated`** — the critical one. `asyncio.gather(worker_fin(), worker_coding(), worker_chat())`, each worker sets its own config and asserts its view throughout a multi-await chain. Must pass reliably with zero cross-bleed.
- `test_parent_context_preserved` — a parent task sets one config, spawns a child that sets a different one, child exits, parent still sees its original config
- `test_legacy_caller_unchanged` — import `from agent_config import agent_config`, construct `NeoMindAgent`-ish mock that captures `agent_config.model` at init, then a fleet worker spawns alongside and changes ITS context — the legacy mock still sees the default value
- `test_exception_in_worker_does_not_corrupt_siblings` — one worker raises mid-turn, other workers in the gather keep their views intact
- `test_proxy_repr_helpful_for_debugging` — `repr(agent_config)` includes the resolved config identity so logs are debuggable
- `test_grep_audit_no_isinstance_checks` — a meta-test that greps the codebase for `isinstance(.*AgentConfigManager)` and fails if any appear (regression protection)

**`tests/test_worker_turn.py`** — worker_turn.execute_task with mocked LLM:
- Fin worker receives a task, calls `resolve_with_fallback` (mocked), parses the response via `parse_signal`, writes an analysis under the tmp Investment root
- Coding worker receives a task, mocked LLM returns a `<tool_call>Edit</tool_call>`, Edit tool is invoked, task reports back
- Chat worker (edge case) returns plain text
- Invalid persona raises a clear error
- A raising LLM call produces `status=failed` with the error captured, never leaks the exception
- Asserts `agent_config.mode == member.persona` inside the task — confirms the proxy + contextvar chain is alive in the worker's execution path

### 4.E — Integration tests: `tests/test_fleet_fin_end_to_end.py` (~1.5h)

Full `FleetLauncher` lifecycle (all LLM mocked, zero budget burned):

1. Start a `fin-core`-shaped project (1 leader + 1 fin worker + 1 coding worker; smaller than the real one to keep test runtime < 10s)
2. Submit task "analyze AAPL and return signal JSON" → verify fin worker claims it, assert `~/Desktop/Investment/fin-core/analyses/*.json` exists with the expected shape
3. Submit task "write a sample file" (mocked Edit) → verify coding worker claims it, Edit mock is called, task marked completed
4. Verify the leader's `ChatSupervisor.check_mailbox()` saw both completion notifications
5. **Verify context isolation**: inside the fin worker's task body (via a spy in `execute_task`), assert `agent_config.mode == "fin"`. Inside the coding worker's task body, assert `agent_config.mode == "coding"`. Both assertions pass even though the tasks ran concurrently in `asyncio.gather` — this is the Option E proof point.
6. **Test the exception path**: dispatch a task to a worker whose `execute_task` raises, verify (a) the task is marked `failed`, (b) sibling workers in the same fleet are unaffected, (c) after the raising task exits its context dies with it so the default config is unchanged
7. **Test the Q2 regression**: same launcher, different yaml (`projects/coding-smoke/project.yaml` — 1 leader + 1 coding worker, zero fin members), same code path runs end-to-end. Proves the launcher is persona-agnostic.
8. **Test true parallelism**: start 4 workers, dispatch 4 tasks simultaneously, mock LLM with a 100ms sleep, assert the total wall-clock time is ~100ms not ~400ms (would be ~400ms under Option C's lock-based serialization)

### 4.F — `fleet/run.py` helper library + live smoke (~30m)

**NO standalone script.** User directive (2026-04-12): "我不想有个 terminal 始终运行导致我关不了 terminal". Instead, `fleet/run.py` is a **pure library helper** (not a CLI):

```python
# fleet/run.py
async def run_task(project_id: str, task_description: str,
                   project_yaml_path: Optional[str] = None,
                   timeout_s: float = 600.0) -> dict:
    """Start a fleet for the given project, submit one task, wait for
    completion, return the aggregated result, and stop the fleet cleanly.

    Lifetime bounded by the await. When this returns, all member tasks
    are stopped, all contextvar scopes have released, and the default
    agent_config is unchanged.
    """
```

Invocation from any existing session:

```bash
# From an existing CLI session (chat/coding/fin mode):
/bash python3 -c "import asyncio; from fleet.run import run_task; print(asyncio.run(run_task('fin-core', 'analyze AAPL')))"
```

Fleet's lifetime = the `await run_task(...)` call. Ctrl-C in the parent session propagates via `asyncio.CancelledError` and cleanly shuts down every worker via the existing `FleetLauncher.stop()`. **No daemon, no separate terminal, no process you forgot to kill.**

**Live smoke** (manual, ≤$0.05 one-time):
```bash
NEOMIND_FLEET_LIVE_SMOKE=1 python3 -c "
import asyncio
from fleet.run import run_task
print(asyncio.run(run_task('fin-core', 'analyze AAPL with one sentence')))
"
```
Gated on env var so automated tests never hit real LLM. User confirmed budget ok + can kill manually.

### 4.G — Canary deploy + revert rehearsal (~45m)

- Run `EvolutionTransaction.canary_deploy_and_verify` with the Phase 4 code changes
- Canary bot (`@neomind_canary_bot`) should come up on the new code without the prod bot restarting
- Run a `gate_b3` Telethon smoke against the canary — existing fin persona (NOT the fleet) must work unchanged
- Run the coding-fleet-smoke Telethon scenario (if the canary profile can spin up a fleet process)
- If green: `promote_to_prod` → confirm prod bot downtime ≤ 12.1s
- **Revert rehearsal**: apply the Phase 4 commits in reverse via git revert + canary-deploy again → confirm prod recovers to pre-Phase-4 behavior

### 4.H — 3-layer gate + commit (~30m)

- Layer 1: full pytest including test_worker_turn + test_fleet_fin_end_to_end
- Layer 2: Telethon gate_b3 against canary post-`promote_to_prod`
- Layer 3: iTerm2 coding CLI 3-scenario smoke
- Every new failure root-caused per the `gate_completion_rule` memory
- Commit in chunks: `worker_turn helper` / `launcher hookup` / `project yaml` / `tests` / `canary evidence`

**Total estimate: 5.5–6.5 hours.** Same as v1 — Option E is simpler per-component than C but the 4.A contextvar foundation + its dedicated test file is new work, so the total evens out. Canary step remains the biggest single chunk of risk.

## 5. Risk register (v2 — after Option E)

Several v1 risks are **gone** in Option E because it has no singleton swap and no lock. Remaining risks:

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| 1 | `_AgentConfigProxy` hits a subtle Python attribute-access edge case (descriptors, magic methods) that breaks a legacy caller | low | medium | 4.A grep audit for `isinstance` / `type()` / `__class__`; explicit proxy test covering `repr`, `bool`, attribute set/get, dot-chain access |
| 2 | LLM budget accidentally burned by auto-tests | low | medium ($ spend, violated user cap) | Mock LLM in all unit + integration tests; only the manual smoke (4.F) hits real LLM, gated on env var |
| 3 | Fleet runs in same process as prod Telegram bot, shared contextvar default leaks | low | high | Fleet launcher runs in a **separate process** (`scripts/fleet_run.py`). Prod bot keeps its own process + its own contextvar default. Explicit documentation in both. |
| 4 | Phase 4 code introduces persona branches in launcher — violates Q2 | low | medium (future coding project breaks) | Persona branching lives ONLY in `fleet/worker_turn.py::execute_task`; `launch_project.py` grep-audited for zero persona string literals in commit; `projects/coding-smoke/project.yaml` integration test proves the agnostic path |
| 5 | `ChatSupervisor` receives completion notifications in a format it doesn't recognize | medium | medium (tasks appear stuck) | Phase 3 of the personality-fleet merge already standardized `format_task_notification` (XML); Phase 4 worker reports via that same function, not a new shape |
| 6 | Context doesn't propagate through some async boundary we didn't anticipate | low | high | Dedicated test `test_sibling_tasks_isolated` asserts isolation holds across `asyncio.gather`, `asyncio.create_task`, nested awaits, and mocked LLM calls. If any path broke propagation, this test would fail before we ever ship. |
| 7 | Coding worker's agentic loop takes minutes during a turn → holds a Task indefinitely | medium | low | Per-worker abort via `asyncio.Task.cancel()` (triggered by supervisor stuck-detection); under Option E there's no lock to block siblings, so one slow worker only affects itself |
| 8 | A third-party library we depend on uses `threading.local` incorrectly and breaks context propagation when called from inside a worker task | very low | medium | None of the existing fin-persona dependencies (`requests`, `yfinance`, `finnhub-python`, `httpx`) use `threading.local` in a way that conflicts. Noted as a tripwire; if we hit it, document + wrap with `run_in_executor` that forwards context. |
| 9 | A legacy caller captures `agent_config.some_attr` at module-import time and then Phase 4 mutates the default | low | low | The existing codebase already does this (see `core.py:230` `self.model = agent_config.model`). Capture-at-init behavior is preserved because legacy callers always read from the default instance, not from a worker's context. Unchanged semantics. |
| 10 | Canary deploy fails mid-rollout and leaves prod in an inconsistent state | low | critical | Phase D canary infrastructure already validated at 12.1s downtime with revert leg — if any step fails, revert is tested |

## 6. Persona-agnostic compliance check (Q2) — Option E is shared fleet infra

**User concern (2026-04-12):** "why can't coding fleet use Option E? Can it be added to shared?"

**Answer: Option E IS shared. It is not a fin-specific feature. Every file Option E touches lives either at the repo root (`agent_config.py`) or under `fleet/` — nothing ships into `agent/finance/`.** A future coding-only project uses the identical code path with zero fin dependency.

### Concrete audit — where each Option E artifact lives

| File | Where | Persona-aware? | Who can use it |
|---|---|---|---|
| `agent_config.py` ContextVar + proxy | repo root | **No** — manages any `AgentConfigManager` regardless of mode | every project (fin, coding, chat, future personas) |
| `fleet/launch_project.py::_run_member` | `fleet/` shared | **No** — grep-audited for zero persona string literals | every project |
| `fleet/worker_turn.py::execute_task` | `fleet/` shared | **Yes** — dispatches on `member.persona` internally | every project; this is the ONE allowed persona-branching site |
| `fleet/run.py` (new) | `fleet/` shared | **No** — takes a project.yaml path | every project |
| `projects/fin-core/project.yaml` | project-specific | fin project | fin users |
| `projects/coding-smoke/project.yaml` | project-specific | coding project | coding users (AND the Q2 regression test) |

### Concrete example — coding-only fleet, zero fin imports

A future user can drop `projects/coding-refactor-sprint/project.yaml`:

```yaml
project_id: coding-refactor-sprint
description: "Parallel coding workers for a refactor burst"
leader: chair
members:
  - { name: chair,     persona: chat,    role: leader }
  - { name: coder-1,   persona: coding,  role: worker }
  - { name: coder-2,   persona: coding,  role: worker }
  - { name: coder-3,   persona: coding,  role: worker }
  - { name: reviewer,  persona: chat,    role: reviewer }
settings:
  stuck_timeout_minutes: 10
```

And invoke it inside any session:

```python
# From an existing CLI session: /bash python3 -c "..."
# Or from a Telegram bot handler:
from fleet.run import run_task
await run_task(
    "coding-refactor-sprint",
    "Refactor agent/modes/finance.py to drop the legacy fallback path",
)
```

What happens:
1. `run_task` loads the yaml via `fleet.project_schema.load_project_config`
2. Starts a `FleetLauncher` with 5 members (1 chat leader + 3 coding workers + 1 chat reviewer)
3. Each member's task sets its own `AgentConfigManager(mode=member.persona)` via `set_current_config` — chat leader sees chat config, each coding worker sees coding config
4. Task description gets dispatched to the 3 coding workers in parallel (real parallelism via independent contextvar copies, not serialized)
5. Each coding worker runs the existing coding persona's agentic loop — Edit / Bash / Grep tools, coding system prompt, coding safety rules
6. Workers report back to the chair via mailbox → supervisor aggregates
7. When `run_task` returns, all member tasks complete, contextvars go out of scope with their tasks, default `agent_config` is unchanged
8. **Zero fin-specific code ran.** `agent/finance/` was never imported. fin-core project.yaml was never touched.

### Gate enforcement

Phase 4 commit must pass a grep audit:
```bash
# launch_project.py must stay persona-free
grep -nE '"(fin|chat|coding)"' fleet/launch_project.py && exit 1

# fleet/run.py must stay persona-free
grep -nE '"(fin|chat|coding)"' fleet/run.py && exit 1

# agent_config.py proxy must stay persona-free (it never branches on mode)
git diff agent_config.py | grep -E '"(fin|chat|coding)"' && exit 1
```

worker_turn.py is exempt because persona dispatch is its explicit job.

## 7. Open questions (need user answer before 4.A)

1. **Approve Option E** — the `ContextVar` + transparent proxy approach ported from nirholas's `AsyncLocalStorage`? This is the one architectural decision that should be explicit. §3.3.5 has the full detail. Risks in §5.
2. **Live smoke budget OK?** ~$0.05 for one real end-to-end Finnhub + DeepSeek call in step 4.F. Can I run it once? Or keep it entirely mocked?
3. **Canary coding-fleet-smoke** — does the canary bot Docker profile have enough CPU headroom to spin up a fleet process alongside its normal duties? If not, I'll rehearse the canary rollout with a no-op Phase 4 commit (just the yaml), not the real fleet start.
4. **`scripts/fleet_run.py` launcher** — should this be a persistent daemon (start on boot, always running) or a short-lived "run one task and exit" CLI? My recommendation: **short-lived** for Phase 4, because it's easier to reason about state and fits the "ask the fleet to do X" mental model. Persistent comes later when there's a genuine always-on use case.
5. **Fail-fast from Phase 3** — should the fleet worker respect the `fail_fast` SharedMemory feedback and downgrade to rules-only? My recommendation: **yes, check on entry**, bail with `status=failed, reason="fail_fast"` if the project has an active fail_fast feedback entry less than 24h old. This is 10 lines and wires the Phase 3 work into the Phase 4 runtime.
6. **Chat-as-worker path** — do we actually need chat workers, or is chat always the leader? My recommendation: keep chat-as-worker minimally functional (return plain text), but don't use it in `fin-core/project.yaml`. It'd show up in a later "think about X" project where chat generates ideas for fin/coding workers to act on.

## 8. Files created / modified in Phase 4 (v2)

Created (new):
- `fleet/worker_turn.py` — task→LLM→parse helper, persona branching lives here
- `fleet/run.py` — **library helper** (not a script), `async def run_task(project_id, task)`, bounded lifetime
- `projects/fin-core/project.yaml` — first real project
- `projects/coding-smoke/project.yaml` — Q2 regression fixture
- `tests/test_agent_config_contextvar.py` — Option E isolation property tests (NEW in v2)
- `tests/test_worker_turn.py` — mocked unit tests
- `tests/test_fleet_fin_end_to_end.py` — integration tests
- `tests/test_fleet_run.py` — helper library tests

Dropped from v1 scope (2026-04-12 user directive):
- ~~`scripts/fleet_run.py`~~ — standalone CLI replaced by in-session `/bash python3 -c "from fleet.run import ..."` invocation pattern. No long-running terminal process.

Modified:
- **`agent_config.py`** — introduce `ContextVar` + `_AgentConfigProxy` + `set_current_config` (NEW in v2; was "not touched" in v1). ~50 LOC addition, zero behavior change for existing callers.
- `fleet/launch_project.py` — `set_current_config(AgentConfigManager(mode=member.persona))` at top of `_run_member`, wire `execute_task` into the worker branch. No lock, no try/finally.
- `plans/2026-04-12_fin_deepening_fusion_plan.md` — update §4 Phase 4 status log after completion
- `tests/qa_archive/results/2026-04-12_phase4_gate.md` — evidence file post-gate

**Still not touched** (explicit):
- `agent/core.py`
- `agent/base_personality.py`
- `agent/modes/{chat,coding,finance}.py`
- `agent/query_engine.py`
- `agent/state_manager.py`
- `agent/integration/telegram_bot.py`
- Any prod bot startup / supervisord config

The key difference from v1: `agent_config.py` is now in the "modified" list, but the modification is purely additive (new ContextVar + proxy class alongside the existing `AgentConfigManager`) and preserves the `agent_config` module symbol that the 7 callers import.

## 9. Definition of Done

- [ ] `fleet/worker_turn.py::execute_task` ships with mocked unit tests (all personas + error paths)
- [ ] `FleetLauncher._run_worker_turn` uses `asyncio.Lock` + singleton swap + `try/finally` restore
- [ ] `projects/fin-core/project.yaml` + `projects/coding-smoke/project.yaml` committed
- [ ] `scripts/fleet_run.py` can start a fleet from a yaml + gracefully stop
- [ ] `tests/test_fleet_fin_end_to_end.py` covers fin worker path, coding worker path, exception restoration, persona-agnostic via coding-smoke, supervisor aggregation, Phase 3 fail_fast respect
- [ ] `launch_project.py` grep audit: zero `"fin"` / `"chat"` / `"coding"` string literals
- [ ] pytest full regression: Phase 0-4 green + core finance + fleet + memory — every failure either fixed or documented
- [ ] Telethon gate_b3 against canary with Phase 4 code: fin persona still works (not fleet — the single-session path)
- [ ] iTerm2 coding 3-scenario smoke: coding CLI still works
- [ ] Canary → promote → revert rehearsal: prod bot ≤12.1s downtime, revert leg green
- [ ] Commit chain landed, status log updated, evidence file committed

---

## 10. User sign-off (2026-04-12)

All 6 open questions answered:

1. ✅ **Option E approved**
2. ✅ **Live smoke ok** — user can kill manually, budget not a concern
3. ✅ **Canary coding-fleet-smoke ok**, plus clarification: **Option E must be usable by coding fleets too**, not fin-specific. Addressed in §6 (persona-agnostic compliance) with a concrete `coding-refactor-sprint/project.yaml` example.
4. ✅ **Drop `scripts/fleet_run.py`** — user doesn't want a long-running terminal process. Replaced with `fleet/run.py` library helper invoked from within existing sessions via `/bash python3 -c "..."`. Fleet lifetime = function invocation lifetime. §4.F revised.
5. ✅ **Phase 3 fail_fast integration approved**
6. ✅ **Chat-as-worker minimal** — keep the path functional, use sparingly

**Starting Phase 4.A (agent_config.py contextvar + proxy foundation).** No more questions pending; implementation begins.

---

## Appendix A: Nirholas evidence (reference sources for Option E)

The contextvar-proxy design in Option E is not original — it's a direct Python port of patterns found in `~/Desktop/nirholas`, Claude Code's own multi-agent implementation (TypeScript/Bun). The key files surveyed during 2026-04-12 pre-flight:

| Nirholas file | What it teaches |
|---|---|
| `src/utils/agentContext.ts:93-110` (`agentContextStorage`, `runWithAgentContext`, `getAgentContext`) | The core pattern. JavaScript's `AsyncLocalStorage` is Python's `contextvars.ContextVar`. Per-execution-chain isolation, automatic context propagation to child tasks, no parameter drilling. |
| `src/utils/forkedAgent.ts:345-462` (`createSubagentContext`) | Clone-not-share discipline. When spawning a sub-agent, don't share references to mutable state — clone file-read caches, allocate fresh `Set` instances for tool-decision tracking, use no-op setState callbacks to cut write-through. Directly informs the §5 E1 risk mitigation. |
| `src/utils/swarm/spawnInProcess.ts:104-147` (`spawnInProcessTeammate`) | End-to-end spawn flow: construct AbortController, register task state, thread context, register cleanup. Maps to Phase 4's `FleetLauncher._run_member` pattern. |
| `src/tools/AgentTool/runAgent.ts:95-140+` | Per-agent tool scoping — each sub-agent gets its own MCP clients, skill paths, permission contexts. Confirms agents can have disjoint tool sets without global mutation. Relevant for fin's `data_hub` access vs coding's `Edit` access in the fleet. |

Full reconnaissance report saved to the Phase 4 pre-flight task log. The bottom-line finding: nirholas achieves concurrent sub-agents with per-agent identity using context threading + state cloning, all in a single process. No subprocess isolation, no worker threads, no lock-based serialization. Python's `contextvars` + asyncio's auto-propagation gives us exactly the same semantics in ~50 lines of wrapper code.
