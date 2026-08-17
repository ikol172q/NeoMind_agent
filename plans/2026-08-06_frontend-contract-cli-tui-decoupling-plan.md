# NeoMind Frontend Contract + CLI/TUI Decoupling Plan

**Date:** 2026-08-06  
**Status:** PHASE 4 DONE (2026-08-16) — the REPL turn runs on `AgentSession` by default. **PHASE 5 (Telegram) DONE for the normal-mode turn** (2026-08-16) — `NEOMIND_TELEGRAM=session` is the compose default, signed off by a live Telethon run. Thinking mode, attachments and the private-DM dashboard route are explicitly *not* migrated; see §11. §11 is the
authoritative tracker; read it before this header. Phase 0 gates passed 2026-08-07 (containment
implemented, real-provider smokes green across DeepSeek / Kimi / local MLX, bot token rotated and
re-verified by a real Telethon run; the provider gate had been blocked by missing environment
injection rather than bad credentials — see the 2026-08-07 record in §5). Phase 1 landed frozen
events, ports, policy and a single `ToolExecutor` in commits 8133280 and 2cac93c; 66 runtime tests
pass on py3.9. Two Phase 1 items are deliberately carried into Phase 3: `AgentSession` itself, and
moving the loop's read-before-edit / PreToolUse pre-checks into executor guards. Open items are
debt, not gates: file-descriptor diagnostics, the Python 3.14 collection gap, and the GLM account
balance.  
**Audit state:** every baseline source claim in §2 was read against source (not README summaries) on
2026-08-06, and both test baselines in §2.8 were reproduced before implementation. Phase 0's current
state and evidence are recorded in §5. Line numbers are accompanied by symbol names because line
numbers drift; when they disagree, the symbol is authoritative.  
**Scope:** CLI/TUI, headless, Telegram, fleet worker turns, shared turn runtime, permissions,
commands, session state  
**Primary model today:** DeepSeek; the contract must remain provider/model agnostic  
**Decision:** establish one internal Python frontend contract before building a new Textual TUI  
**Supersedes:** no existing plan; it corrects the frontend-neutrality assumption in older fleet/CLI plans  
**Relates to:** `plans/2026-04-19_frontend_architecture_final.md` remains the browser/dashboard
decision. Textual is a terminal adapter, not a replacement for the React dashboard. Moving the
browser chat onto this runtime through an HTTP/SSE gateway is a future adapter, not part of this
plan's completion gate.

---

## 0. BLUF

NeoMind does not currently have a separable TUI. It has a capable but tightly coupled
`prompt_toolkit` + Rich REPL whose main interface class also owns pieces of agent runtime,
permissions, commands, persistence, streaming, and fleet lifecycle.

The first objective is therefore **not** to replace `prompt_toolkit` with Textual. The first
objective is to make one agent turn consumable by any frontend through a small, typed contract:

```text
Prompt REPL ──┐
Textual TUI ──┤
Telegram ─────┼── AgentSession ── TurnEngine ── LLMPort
Headless ─────┤                 ├─ ToolExecutor ── PermissionPolicy/Broker
Fleet worker ─┘                 └─ ConversationStore
```

Five live turn entry paths/surfaces exist today, not three: the Prompt REPL, headless, Telegram,
the fleet worker (`fleet/worker_turn.py`, which calls the provider directly), and the legacy
fallback interface `main.py` drops into on any exception. They do not represent five completely
independent engines — the fallback and REPL share `NeoMindAgent.stream_response()` — but every path
must have an explicit migration/freeze/deletion outcome. §2.4 inventories all five; the done
conditions are written against that count.

The current `AgenticLoop` remains the temporary internal tool-loop implementation. The current
`QueryEngine` must not become the new frontend contract as-is: it is not connected to production,
does not truly stream, and is incompatible with the real `ToolRegistry` interface.

Security is part of the contract, not a later UI feature. A write/execute operation denied by the
runtime must remain denied whether the caller is the REPL, Textual, Telegram, headless, a test,
or a buggy/malicious adapter.

---

## 1. Problem framing

### 1.1 The real problem

**Desired state:** NeoMind can evolve its CLI/TUI independently, add new Python frontends, and
switch among DeepSeek and other open-source or closed-source providers without duplicating agent
logic or weakening tool permissions.

**Current state:** each surface owns part of the turn loop, and the current terminal UI reaches
directly into mutable `NeoMindAgent` state. Adding a Textual UI today would either duplicate that
logic again or import the same internals and preserve the coupling.

**Gap to close:** one authoritative session/turn runtime with a stable event and permission
contract, plus thin surface adapters.

### 1.2 Sibling frames considered

| Frame | What it would solve | Why it is not the first move |
|---|---|---|
| Restyle the existing REPL | Better colors/layout/keybindings | Does not remove duplicated turns, history, or permission behavior |
| Replace it immediately with Textual | Long-lived widgets and richer layout | Moves current coupling into a new UI and creates a second migration problem |
| Rewrite the agent core | Could eventually produce clean boundaries | Too broad; risks finance, Telegram, memory, and provider behavior at once |
| Extract a vertical runtime contract | Makes every frontend a consumer of the same turn | Smallest change that determines all later UI work; selected approach |

### 1.3 Done condition for the overall program

The decoupling program is complete only when:

1. Prompt REPL, headless, Telegram, Textual, and fleet worker turns consume the same
   `AgentSession` event contract. `cli/interface.py` — the legacy fallback surface that `main.py`
   silently falls back to — is explicitly migrated, frozen, or deleted; it must not survive as an
   unaccounted turn path.
2. There is one tool execution path and one permission enforcement point for all surfaces,
   fleet workers included.
3. A runtime turn performs no direct terminal/Telegram rendering and calls no `print()` or
   `input()`.
4. Each surface has exactly one owner for its session history; runtime logic does not double-write
   messages or call the LLM twice.
5. A frontend cannot execute a denied tool by omitting or mutating an approval event.
6. DeepSeek remains the primary tested provider, while another provider can be selected without
   changing frontend code.
7. A new frontend can be implemented without reading or mutating private `NeoMindAgent` fields.

---

## 2. Baseline source-verified architecture (before Phase 0)

This inventory records the source state found before Phase 0 changes on 2026-08-06, not README
claims. Findings that Phase 0 has since contained or removed are explicitly tracked in §5; this
section remains the migration baseline rather than being silently rewritten as if the defects had
never existed.

### 2.1 Entrypoints and fallbacks

- `pyproject.toml` `[project.scripts]` (~line 105) installs `neomind = "main:main"`.
- `main.py` `interactive_main()` (~67-131) applies process/global configuration and launches
  `cli.neomind_interface.interactive_chat`.
- `main.py` (~118-131) catches every exception from the preferred interface and falls back to an
  older prompt/plain interface. Runtime failures can therefore be presented as interface
  availability failures.
- That fallback is a **live surface, not a stub**: `cli/interface.py` (499 lines) runs its own input
  loop and calls `chat.stream_response()` directly (~316, ~477). It has no tool loop, so it is not a
  permission hole, but a runtime exception in the migrated path will silently drop a user into an
  unmigrated turn implementation. Its disposition must be decided, not inherited (see Phase 4).
- `main.py` `headless_main()` (~145-294) implements headless mode separately, including its own tool
  parser/execution loop.

### 2.2 The current “TUI” is an enhanced REPL

`cli/neomind_interface.py` is 2,970 lines. `NeoMindInterface` owns:

- a `NeoMindAgent` object and direct access to its mutable fields;
- `PromptSession`, Rich `Console`, ANSI output, spinner threads, and keybindings;
- conversation save/load;
- new and legacy command dispatch;
- tool registry lookup and interactive permissions;
- the adapter for `AgenticLoop`;
- fleet focus, routing, background event loop, polling threads, and rendering.

`cli/neomind_interface.py:2473-2830` runs `PromptSession.prompt()` in a loop. The prompt application
exists while waiting for input, then returns before the LLM stream is rendered. The source itself
documents the consequence at `cli/neomind_interface.py:2355-2366`: the bottom toolbar disappears
during streaming because no long-lived `Application` is running.

This is a sound reason to consider Textual later, but it is not the root coupling problem.

### 2.3 The agent/LLM path still owns presentation

`NeoMindAgent.stream_response()` delegates to `agent/services/code_commands.py:1020`.
That function combines:

- input classification and command-related behavior;
- context/history mutation and compaction;
- provider/model selection;
- blocking `requests.post(..., stream=True)` and SSE parsing;
- first-token UI callbacks and content filters stored on the core object;
- direct stdout rendering at `agent/services/code_commands.py:1454-1468`;
- response persistence, usage accounting, memory/evolution hooks, and logging.

Redirecting stdout in `main.py` is currently how headless suppresses this presentation behavior.
That is evidence that streaming output is not yet a runtime event source.

### 2.4 Turn ownership is duplicated across surfaces

#### Prompt REPL

`cli/neomind_interface.py` `_run_agentic_loop()` (~2116-2300) constructs and consumes `AgenticLoop`,
supplies an LLM caller, mutates permission events, renders tool state, and passes the shared
conversation list into the loop.

It also **gates the entire tool loop on mode**: `if self.chat.mode not in ("coding", "fin"): return`
(~2131). In `chat` mode the REPL runs no tool loop and therefore exercises no permission path. Any
migration verification matrix that only tests `chat` mode proves nothing about tools or permissions.

#### Headless

`main.py` (~192) says “auto-accept reads, deny writes,” but the loop below it (~215-267) obtains any
named tool and directly calls `tool_def.execute(**params)` with no permission decision anywhere in
the function. The comment is not describing the code. It also owns a separate continuation/history
loop.

#### Telegram

`agent/integration/telegram_bot.py` separately owns provider routing, system prompt composition,
SSE/message streaming, history/storage, tool registry construction, continuation calls, and
Telegram rendering. It reuses `AgenticLoop` only for part of tool orchestration
(`_get_agentic_loop()` ~4381-4540).

#### Fleet workers — a fifth turn implementation

`fleet/worker_turn.py` `execute_task()` (~367) is a live, independent turn path reached in production
through `fleet/launch_project.py` (~249). It selects `agent_config.model` and the system prompt
itself and calls the provider through its own `requests.post` (~140); it does not use
`NeoMindAgent.stream_response()`, `AgenticLoop`, or any shared turn code.

It executes no tools **today** — `_execute_coding()` (~303-310) states in source that “full agentic
loop integration (tool calls, Edit/Bash dispatch, iterative reasoning) is deferred to a follow-up.”
That deferral is exactly why it belongs in this plan: the moment fleet workers grow tool execution,
they grow a second unaudited permission path. Older framing treated fleet as a UI-lifecycle concern;
that framing is incomplete and is corrected here.

Result: sharing `AgenticLoop` does not currently mean sharing one turn runtime. There are five live
turn entry paths (REPL, headless, Telegram, fleet worker, legacy fallback interface) backed by
multiple orchestration implementations.

#### Generic ToolRegistry/ToolDefinition dispatch sites (complete, source-verified)

The generic LLM-requested `ToolDefinition`/registry execution boundary is reached from exactly four
production-code sites. This count intentionally excludes unrelated `.execute()` methods such as
database cursors, browser commands, workflows, and task objects:

| Site | Permission check | Status |
|---|---|---|
| `agent/agentic/agentic_loop.py` (~857-860) | only if the frontend sets `event.approved` | baseline finding; contained in Phase 0 |
| `main.py` headless loop (~238) | none | baseline finding; contained in Phase 0 |
| `cli/neomind_interface.py` `_execute_tool_call()` (~1986-2011) | none | baseline dead path; deleted in Phase 0 after reverse-dependency search |
| `agent/query_engine.py` `_execute_tool()` (~719) | none | dead, and broken (calls a non-existent registry method) |

`_execute_tool_call()` is an unguarded execution path kept alive only by its tests. It contradicts
D4 directly and should be deleted in Phase 0 rather than carried to Phase 8.

### 2.5 The two candidate “engines”

#### `AgenticLoop`: live and reusable, but not a full frontend contract

`agent/agentic/agentic_loop.py:241-265` accepts an initial response, a mutable messages list, and
an injected LLM caller. It yields tool/result/response/done events and is used by CLI and Telegram.

Remaining coupling:

- The loop yields a mutable `tool_start` event, then checks whether the frontend changed
  `event.approved` (`agent/agentic/agentic_loop.py:383-396`). The field is declared
  `approved: bool = True` (~117), so **silence means execute**. A frontend that ignores the event,
  crashes, or simply never learned about the handshake gets full tool execution. This single default
  is the root of every fail-open finding in §2.6; the immutable-event + `request_id` design in §4.4
  exists specifically to remove it.
- It mutates the caller's history list.
- Frontends still construct the LLM caller and own major parts of the turn.
- Some hooks/defaults are mode/model specific rather than session scoped.

Older plans described this as frontend-agnostic. The corrected conclusion is: **its parser/tool
loop is reusable, but its current permission handshake and turn ownership are not a sufficient
frontend contract.**

#### `QueryEngine`: useful design material, not a production path

`agent/core.py:381-393` initializes `QueryEngine` with both `tool_registry=None` and
`llm_caller=None`. No production caller invokes `_query_engine.run_turn()`.

**It is not, however, dead code.** `agent/services/code_commands.py` (~1600-1611) calls
`core._query_engine.budget.record_usage(...)` after every LLM response, and that budget object is
what backs the `/cost` command. The turn loop is dead; the token/cost accounting hanging off the
same object is live. Deleting the class without relocating `budget` silently breaks cost reporting —
a failure mode no current test or done gate would catch.

Additional source/runtime findings:

- `agent/query_engine.py:583-611` awaits a complete response and emits it as one stream delta.
- `agent/query_engine.py:710-724` calls `ToolRegistry.execute`, which the real registry does not
  implement; the registry exposes `get_tool()` and tool definitions instead.
- It reads `tool_result.status`, while the real `ToolResult` uses `success`, `output`, and `error`.
- Existing tests use mocks and do not exercise the real registry integration.

Direct integration result from this audit:

```text
AttributeError: 'ToolRegistry' object has no attribute 'execute'
```

Decision: harvest useful budget/compaction/event concepts later; do not wire a new TUI to this
class and do not create a third live loop around it. The live `budget` dependency must be relocated
behind the runtime (with a `/cost`-correctness gate) *before* any removal step in Phase 8.

### 2.6 Permission and tool safety findings

1. `NeoMindInterface._check_permission()` is the effective CLI policy, rather than the shared
   `PermissionManager` being the authoritative executor gate.
2. `auto_accept` and the session `_auto_approved` flag return before dynamic risk classification.
3. Choosing “always” approves later write/execute tools across the session rather than binding a
   decision to one exact tool/target/command pattern.
4. `ServiceRegistry.permission_manager` exists, and its intended matrix keeps critical operations
   interactive even in auto-accept mode, but CLI and Telegram do not inject it into their
   `AgenticConfig`.
5. Telegram builds a standard `ToolRegistry(working_dir="/app")` without a permission manager and
   does not set `event.approved` when consuming `tool_start`. The impact is bounded by the bot
   process/container and its mounts, which require a separate deployment audit, but the frontend
   contract itself is fail-open.
6. File tools call `_resolve_path()` and enforce workspace/temp roots. Bash uses a persistent shell
   and is not equivalent to a filesystem-root capability boundary.
7. The permission audit currently stores a truncated `str(params)`; future auditing must redact
   secrets and retain a safe preview/fingerprint rather than raw sensitive arguments.

### 2.7 Commands, state, persistence, and fleet

- New `CommandDispatcher`, legacy UI command handling, personality/core `command_handlers`, and
  fallback CLI behavior coexist.
- Structured command results still use magic strings such as `__EXIT__` and `__MODE_SWITCH__`.
- The UI directly changes core fields and `agent_config` state.
- `agent_config` now provides ContextVar-based task isolation for fleet tasks, which is useful, but
  ordinary frontend code still imports and mutates the global proxy rather than consuming a
  session snapshot.
- CLI persistence uses its `ConversationManager`; Telegram uses `ChatStore`; other agents/stores
  have separate histories. Different storage backends are acceptable, but turn logic must use one
  store port and one owner per session.
- Fleet has **two** distinct couplings, and conflating them was the main defect in earlier framing:
  (a) *lifecycle/rendering* — a daemon event-loop thread and polling/render threads living inside
  `NeoMindInterface`, which a fleet event port resolves; and (b) *turn ownership* — `worker_turn.py`
  calling the provider directly (§2.4). Only (a) is deferrable behind a facade. (b) is a turn
  runtime and is in scope for the program's done condition even though its migration lands late.

### 2.8 Test baseline observed during this audit

Commands run in the repository's `.venv` (Python 3.9); reproduced 2026-08-06:

```text
pytest tests/test_query_engine.py
       tests/test_agentic_loop_canonical.py
       tests/test_cli_agentic_refactor.py

Result: 90 passed, 1 failed
Failure: TestAgenticLoopIterationLimits::test_hard_limit_stops_loop —
         the repeated-response breaker fires at 2 tool_starts before the
         iteration-limit test's expected 3.
```

```text
pytest tests/test_agentic_loop.py

Result: 44 passed, 3 failed
Failures: TestExecuteToolCall::test_read_file,
          TestAgenticLoopFlow::test_max_iterations,
          TestAgenticLoopFlow::test_structured_tool_execution
          (two path-safety/root mismatches and one loop/stream contract mismatch).
```

These are not a green baseline. Phase 0 must classify and resolve the four relevant failures before
the new runtime contract is treated as proven. Two caveats on that classification:

- **One of the four is a test of dead code.** `TestExecuteToolCall::test_read_file` exercises
  `NeoMindInterface._execute_tool_call()`, which has no production callers (§2.4). Its correct
  resolution is deletion of the method and its tests, not a fix that keeps an unguarded execution
  path alive.
- **This baseline covers one environment only.** NeoMind runs on more than one interpreter
  (`.venv` = Python 3.9, plus the service venv used for pytest elsewhere). A baseline established in
  a single venv is not a baseline for the project; see §7.3 and the Phase 0 gate.

---

## 3. Architecture decisions

### D1 — Python remains the implementation language

Python is sufficient for the target TUI and runtime. Network latency, model inference, terminal
rendering, and current ownership boundaries dominate; rewriting in Rust would not solve the
architectural problem. Textual is a viable later adapter once the contract exists.

### D2 — One `AgentSession` owns each session

The session is the application boundary. It owns turn sequencing, mode/model state, conversation
state, cancellation, permission coordination, and persistence calls. Frontends receive snapshots
and events rather than mutable agent internals.

### D3 — Keep `AgenticLoop` temporarily; do not adopt `QueryEngine` as-is

The migration wraps/refactors a live path instead of replacing all behavior at once. Useful
`QueryEngine` concepts may move into the new runtime only after real integration tests exist.

### D4 — Authorization and LLM-requested tool execution are inseparable

Only `ToolExecutor` may execute an LLM-requested `ToolDefinition`. It must apply capability
filtering, validation, permission policy, approval resolution, and audit immediately before
execution. Frontends display and answer permission requests but never execute those tools. Browser,
workflow, database, and internal task `.execute()` APIs remain outside this narrowly defined rule
unless they are exposed to the LLM as `ToolDefinition`s.

### D5 — Tool visibility and tool authorization use the same capability policy

The tools included in an LLM prompt must be the tools the session is allowed to request. Execution
rechecks the same policy. Mode filtering alone is not a security boundary.

### D6 — Migrate by vertical slice, not directory rewrite

The first slice supports one ordinary turn, real deltas, one read tool, and one denied write tool.
Finance/dashboard special flows, fleet UI, and command consolidation remain on compatibility paths
until the contract is proven.

### D7 — No public/network protocol yet

The first frontend contract is an internal Python API. ACP/MCP-style remote protocols, plugin
markets, and cross-process event transport are separate future decisions.

#### D7 addendum — candidate harnesses examined 2026-08-15 (D7 unchanged)

The operator asked whether **pi** (`badlogic/pi-mono`) and the **DeepSeek Harness**
(`deepseek-ai/dsh`) could serve as references or as direct candidates. Both were read at source in a
fresh clone rather than from their READMEs. Findings, and why they do not move D7 yet:

**pi — 10 packages, 1402 files.** Its internal dependency graph is the target shape §4.1 describes,
independently arrived at:

```text
protocol → (nothing)      tui → (nothing)      telemetry → (nothing)
ai       → telemetry      agent → ai, telemetry          ← core knows no UI
coding-agent → agent, ai, client, protocol, tui          ← the only composition root
```

`tui` depends on nothing and `agent` depends on no UI; exactly one package knows both. NeoMind's
missing piece is that composition root — `cli/neomind_interface.py` is simultaneously the wiring,
the rendering, and the owner of 21 command branches (measured 2026-08-15; 7 delegate to `agent.*`
in 6–7 lines, ~9 are genuine UI concerns, 5 are agent capabilities reachable only from the CLI, and
`/evidence` alone is 162 lines — five times the next largest).

pi's protocol is bespoke: a 4-byte big-endian length prefix over CBOR, nine commands (`list`,
`create`, `attach`, `detach`, `prompt`, `steer`, `abort`, `set_model`, `set_thinking`) and seven
error codes. `attach`/`detach`/`list` imply multi-client access to a running session, and `steer`
is mid-generation intervention; NeoMind has neither today.

**DeepSeek Harness — 49 packages.** Its `@deepseek-ai/dsh-acp` package is described in its own
`package.json` as an "Automation-only Agent Client Protocol server for driving DeepSeek Harness
agents over JSON-RPC stdio" and depends on `@agentclientprotocol/sdk`. So DSH speaks **ACP**, the
open standard, rather than a private protocol. ACP has an official Python SDK
(`pip install agent-client-protocol`, Pydantic models + async base classes + JSON-RPC transport),
so the Python side of that route needs no hand-written codec.

**Why D7 still stands.** Both are TypeScript, so "adopt directly" necessarily means a cross-process
boundary — which is what D7 defers, not what it forbids. More decisively, an ACP or pi-protocol
server is an *adapter over an event stream*, and the event stream is what Phases 2–3 create. There
is nothing to map until `LLMPort` emits real incremental chunks and `AgentSession` owns turns. Doing
the protocol first would mean designing a wire format against internals that are still moving.

**What this changes.** Nothing in the phase order. It does two things: it confirms §4.1's dependency
direction against a working system rather than an argument, and it makes ACP the specific candidate
to weigh at Phase 7 — the choice there is no longer "Textual TUI vs nothing" but "Textual TUI, or an
ACP server that any conforming client can drive, or both". Revisit at Phase 7 with the event set
frozen, and judge it then on whether the event set maps cleanly onto ACP's session model.

### D8 — One temporary rollback switch is allowed

Each surface may switch between `legacy` and `session_v1` during migration. The switch must be
removed once all affected real-surface gates pass; it must not become a permanent second runtime.

---

## 4. Target contract

### 4.1 Dependency direction

```text
surfaces/{prompt_repl,textual,telegram,headless,fleet_worker}
                         │
                         ▼
                application/session
                         │
                         ▼
 agent/runtime/{turn_engine,events,tool_executor,permissions}
                         │
                         ▼
      ports/{llm,conversation_store,tool_registry,audit,fleet}
                         ▲
                         │
 adapters/{providers,sqlite,json,existing_tools,telegram_storage}
```

Enforced rule: runtime/application modules must not import `cli`, `prompt_toolkit`, `rich`,
`telegram`, or a surface renderer.

### 4.2 Proposed session API

Names may change during implementation, but semantics must not:

```python
class AgentSession:
    async def run_turn(self, text: str) -> AsyncIterator[RuntimeEvent]: ...
    async def resolve_permission(
        self,
        request_id: str,
        decision: PermissionDecision,
    ) -> None: ...
    async def cancel(self, turn_id: str) -> None: ...
    def snapshot(self) -> SessionSnapshot: ...
```

`run_turn()` may await a permission future internally after emitting a request. The adapter answers
through `resolve_permission()`; it never mutates an event that the generator later rereads.

Every event carries at least:

```text
session_id, turn_id, sequence, timestamp, type
```

Sequence numbers are monotonically increasing within a turn so Telegram edits, terminal rendering,
record/replay tests, and future GUIs can detect missing or reordered events.

### 4.3 Runtime event set

Initial required events:

| Event | Required payload |
|---|---|
| `TurnStarted` | normalized input metadata, mode/model snapshot |
| `StatusChanged` | structured status code + safe display text |
| `ThinkingDelta` | safe/redacted reasoning display delta, when enabled |
| `TextDelta` | actual incremental response text |
| `ToolProposed` | tool name + safe preview; no unneeded raw secrets |
| `PermissionRequested` | request id, risk, explanation, allowed decision scopes |
| `ToolStarted` | call id, tool name |
| `ToolOutputDelta` | optional bounded safe output for long-running tools |
| `ToolFinished` | success/error metadata and bounded output reference/preview |
| `ContextWarning` | budget state |
| `ContextCompacted` | before/after accounting |
| `TurnFinished` | final response and usage summary |
| `TurnFailed` | typed failure, safe user message, retryability |

Events are immutable dataclasses or frozen models. Large/raw tool output may be stored by reference;
renderers receive bounded previews.

### 4.4 Permission contract and invariants

The following are non-negotiable:

1. No valid approval means no execution.
2. `ASK` with no interactive broker resolves to `DENY`.
3. “Allow once” is tied to `request_id`, tool name, normalized parameters, working directory, and
   a fingerprint of the proposed action.
4. A session rule is scoped to a declared tool/target/command pattern; there is no global
   `_auto_approved: bool`.
5. Critical/destructive actions remain interactive even under auto-accept unless an explicit,
   separately named bypass policy was selected by the user.
6. The executor compares the approved fingerprint with the actual arguments immediately before
   execution.
7. Telegram and headless start with an explicit non-interactive capability policy. Any tool not
   explicitly allowed is denied.
8. Tool prompt visibility and executor authorization derive from the same capability snapshot.
9. Audit records contain decisions and redacted previews/fingerprints, not raw credentials or
   unrestricted command arguments.
10. A frontend exception, disconnect, timeout, or cancellation while awaiting permission resolves
    to denial.

### 4.5 Ownership matrix

| Concern | Runtime/application owns | Frontend owns |
|---|---|---|
| User input meaning | normalization and turn submission | text entry, paste, keybindings |
| Model/provider | selected session state and LLM port | selector widget/command only |
| Streaming | chunk production, ordering, cancellation | rendering, throttling, folding |
| History | append/compact/persist through store port | browse/export request and display |
| Tools | visibility, validation, authorization, execution | proposal/result presentation |
| Permission | policy, request lifecycle, final enforcement | collect an authorized user's answer |
| Commands | parsing and structured application effects | UI-only commands and effect rendering |
| Fleet | worker turns run through `AgentSession`; session/event port and lifecycle | focus/layout/unread indicators |
| Diagnostics | structured events/log records | status bar and human-readable formatting |

### 4.6 Command contract

Replace magic result strings with structured effects:

```text
ExitRequested
ModeSwitchRequested(mode)
ModelSwitchRequested(model)
PromptSubmission(text)
ConversationCompactRequested
DisplayMessage(level, text)
OpenExternalRequested(target)
```

There should be one application command registry. Commands that are purely visual—theme, pane
focus, copying, expanding tool output—remain frontend-local.

---

## 5. Phased execution plan

### Phase 0 — Baseline and immediate safety containment

**Purpose:** establish trustworthy tests and close known fail-open paths before abstraction work.

Tasks:

1. Add characterization tests for CLI, headless, and Telegram tool authorization.
2. Retain and run the existing real-`ToolRegistry` integration coverage
   (`tests/test_integration_e2e.py` and `tests/test_tool_pipeline_e2e.py`); add a narrower regression
   only if those tests do not exercise the changed boundary. Registry API drift must not be hidden
   by mocks.
3. Classify and fix the four currently observed relevant test failures.
4. Make headless fail closed for write/execute/destructive tools until it uses `AgentSession`.
5. Give Telegram an explicit temporary capability policy; no interactive approval means `ASK`
   cannot execute.
6. Make the current `AgenticLoop` handshake explicitly fail closed: an unanswered permission state
   is not approval (`approved=True` as a default must go). Wire one shared `PermissionManager` into
   live loop configurations, or add a narrowly scoped compatibility guard if direct wiring changes
   behavior too broadly. Wiring the manager alone is insufficient while `ASK` can still fall
   through an implicitly approved mutable event.
7. Remove the CLI short-circuit that lets session-wide auto approval bypass critical dynamic risk.
8. Delete `NeoMindInterface._execute_tool_call()` and its tests — an unguarded
   `tool_def.execute()` path with zero production callers (§2.4). Confirm zero callers by
   reverse-dependency search before deleting, not by inspection.
9. Freeze fleet worker tool execution: `worker_turn.py` must not gain `AgenticLoop`/tool dispatch
   until it consumes `AgentSession`. Enforce this with an architecture test (for example,
   `tests/architecture/test_fleet_worker_turn_boundary.py`) that AST/import-checks for forbidden
   `ToolRegistry`/`AgenticLoop` imports, `<tool_call>` parsing, and direct `ToolDefinition.execute`
   dispatch. A source comment alone does not satisfy this task.
10. Record current CLI/Telegram/headless/fleet-worker behavior as fixtures and real-surface evidence.

Done gate:

- All relevant agentic/query/permission tests pass in both named host environments — repository
  `.venv` (Python 3.9, CLI/iTerm2) and `~/.neomind_fin_venv` (Python 3.14,
  service/pytest/full dependencies) — with the output of each run attached. Container-specific
  paths are verified in the Telegram container after restart. A pass in one environment does not
  satisfy this gate.
- A test adapter that never answers a permission request cannot execute a write. This is the direct
  regression test for `AgenticEvent.approved = True` (§2.5) and fails against the pre-Phase 0
  baseline.
- A malicious adapter that reports an approval for different parameters cannot execute.
- Headless and Telegram write/execute defaults are explicit and tested.
- No `tool_def.execute()` call site remains without a permission decision except the ones explicitly
  scheduled for replacement in Phase 1 (§2.4 table is the checklist).
- Current Prompt REPL boots in a real iTerm2 window with the user's real router and completes, in
  `coding` or `fin` mode: (a) a text-only DeepSeek turn, (b) a real `Read`, (c) a denied `Write`
  whose target remains unchanged, and (d) a denied `Bash` whose side effect does not occur. A
  `chat`-mode or text-only pass is not evidence about tools or permissions (§2.4).
- Headless and Telegram repeat the applicable read/denied-write scenarios through their real
  subprocess/client surfaces; unit or mocked adapter results are not substitutes.

#### Phase 0 execution record — 2026-08-06

Implemented containment:

- `AgenticEvent.approved` now defaults to unanswered (`None`). Only a registered `READ_ONLY` tool
  may use the configured unanswered-read compatibility path; risky, unknown, or unclassified tools
  stop without execution.
- Approval is bound to a canonical SHA-256 fingerprint of the exact tool name and nested params
  shown to the adapter. Adapter mutation or executable-call substitution fails closed. The existing
  DeepSeek joined-flag compatibility normalization now runs *before* preview/fingerprinting, never
  after approval.
- Headless executes only definitions whose permission level is exactly the `READ_ONLY` enum;
  unknown, missing, string-valued, write, execute, and destructive classifications are denied.
- CLI dynamic risk classification occurs before auto/session approval; `CRITICAL` actions still
  prompt. EOF and Ctrl-C at the permission prompt deny, and headless Ctrl-C exits 130 with valid
  text/JSON error output.
- The dead unguarded `NeoMindInterface._execute_tool_call()` and its obsolete tests were removed;
  reverse-dependency search reports zero remaining callers/member accesses.
- Fleet workers are protected by an AST architecture test that rejects imports/runtime tags/generic
  tool dispatch until their turn path consumes `AgentSession`.
- Workspace-relative path safety is resolved against `ToolRegistry.working_dir`, not process cwd,
  and is covered for traversal, symlink, tilde, temporary, and absolute paths.
- CLI and Telegram display/detection paths, plus parser/headless history cleanup, support standard
  and DeepSeek pipe/begin/end text tool protocols across streaming chunk boundaries. Headless now
  replaces the exact raw assistant reply already persisted by `stream_response()` instead of
  appending a sanitized duplicate and leaving the original payload in history. Telegram resolves
  unanswered risky-tool status as “未获批准，未执行” and removes or neutralizes pure-tool-call
  placeholders.

Verification completed:

- Both host environments passed the same relevant suite (313 tests after the final approval-binding
  regression) and the fleet suites (93 tests), run sequentially to avoid cross-environment shared
  state. Production files compile in both Python 3.9 and Python 3.14.
- Real headless subprocesses passed text, JSON, read-only, denied write/execute, and Ctrl-C/exit-130
  scenarios. A real local-model pipe-protocol continuation initially reported `HISTORY_DIRTY`,
  exposing `stream_response()`'s history side effect; after the source fix the same subprocess
  returned `HISTORY_CLEAN` with exit 0.
- Real iTerm2 sessions used the installed CLI, the user's router, continuous 0.3-second full-screen
  capture, a local Qwen model, real `Read`, denied `Write`/`Bash`, and a denied `CRITICAL` `.env`
  write even with auto-accept set. Dumps are under
  `~/Pictures/neomind-dogfood/2026-08/2026-08-06-phase0-cli-*.txt`; windows were intentionally left
  open for inspection.
- The Telegram container was restarted and verified healthy. A real Telethon client completed
  text/read/denied-write/denied-Bash flows and a separate split-prefix display regression, with
  model/mode restored afterward. Evidence:
  `~/Pictures/neomind-dogfood/2026-08/2026-08-06-phase0-telegram-real.json` and
  `~/Pictures/neomind-dogfood/2026-08/2026-08-06-phase0-telegram-pipe-prefix-retest.json`.
  Source verification showed ordinary private natural-language messages route through the dashboard
  agent, so the canonical coding loop was exercised through Telegram's real unknown-slash fallback
  rather than mislabeling the dashboard route as the same path.

#### Phase 0 continuation record — 2026-08-07

**Provider gate: root cause was environment injection, not credentials.**

The 401s were misdiagnosed as expired keys. `Desktop/LLM-Router/start.sh` snapshots provider keys
from the *invoking shell* into `.env.runtime`; the running router had been started on 2026-08-02
from a shell without them, so that file contained only `LLM_ROUTER_API_KEY`. The unexpanded
`${DEEPSEEK_API_KEY}` placeholder was forwarded verbatim, which upstream echoed back as
``Your api key: ****KEY} is invalid`` — the trailing `KEY}` is the tell. `scripts/repair.sh`
already documents this failure mode and sources `~/.zshrc` first; a bare `./start.sh` from a
non-login shell reproduces it silently.

Restarted via `zsh -lc './start.sh restart'`. `.env.runtime` now carries `DEEPSEEK_API_KEY`,
`ZAI_API_KEY`, `MOONSHOT_API_KEY` (mode 600); discovered models went 10 → 25. Real calls:

| Model | Result |
|---|---|
| `deepseek-v4-flash` | HTTP 200, returned `alive` — primary provider smoke |
| `deepseek-v4-pro` | HTTP 200, returned `42` with reasoning content |
| `kimi-k2.5` | HTTP 200, returned `42` — second-provider switch smoke |
| `mlx-community/Qwen3-30B-A3B-Instruct-2507-4bit` | HTTP 200, returned `42` — local |
| `glm-4.7` | HTTP 429, Z.ai code 1113 `余额不足或无可用资源包` — **billing, not auth** |

Note the earlier empty-content results for reasoning models were a `max_tokens=20` artifact, not a
provider fault. GLM is now an account-balance issue for the operator; the second-provider gate is
satisfied by Kimi, so it does not block Phase 0.

**Telegram token leak: contained at source; rotation still owed.**

Scope was larger than first reported. Measured across the docker named volume
`neomind_agent_neomind-data` (which the earlier scan of `~/.neomind` did not cover):

```text
/data/neomind/agent.log     25291 lines,  24877 with token
/data/neomind/agent.log.1   75649 lines,  74283 with token
/data/neomind/agent.log.2   75000 lines,  74809 with token
/data/neomind/agent.log.3   75196 lines,  74627 with token
TOTAL 248,596 lines — one distinct token, sha256 matching the live .env value
```

Nothing in NeoMind logged it: `httpx` logs each request line at INFO, and the Telegram polling URL
carries the token in its path. `telegram_bot.py`'s `basicConfig(level=INFO)` let it through,
supervisord captured stdout, and the ~10s poll wrote it roughly six times a minute.

Containment (`agent/logging/secret_redaction.py`, wired at the `basicConfig` call site):

1. `httpx`/`httpcore`/`urllib3`/`telegram.*` loggers drop to WARNING — removes the known source.
2. A `SecretRedactingFilter` on every root **handler** rewrites records before any handler sees
   them. Handler-level, not logger-level: a filter on a logger is not consulted for records
   propagated up from a child, which is exactly the path `httpx` records travel.

`PIISanitizer` also gained the Telegram-token shape. Its existing `api_key` pattern requires a
vendor prefix (`sk-`, `token_`, …) that a Telegram token does not have. Pattern order matters and is
now documented in-file: `ssn` matched the numeric half of `123456789:AAH…` and left the secret half
exposed as `[REDACTED_SSN]:AAH…`, which the new test caught.

Evidence: 20 tests in `tests/test_secret_redaction.py`; full logging suite 127 passed in **both**
venvs (`.venv` py3.9 and `~/.neomind_fin_venv` py3.14). After container restart, 21 new log lines
with **0** token-shaped hits and **0** `api.telegram.org/bot` hits, bot reporting LIVE. An
adversarial in-container check re-enabled `httpx` INFO after install and confirmed the filter still
redacts.

Exposure bound: the leak is local. `git grep` over the HEAD tree and the working tree (tracked and
untracked) finds zero token-shaped strings; `.env` is git-ignored, untracked, mode 600; the two
unpushed commits are clean. `~/.neomind/transcripts/{ede2f405,cdca612b}.jsonl` hold 4 further lines
(one current token, one already-superseded token), mode 600.

**Rotation completed and verified (2026-08-07).** The operator revoked the token through BotFather
and updated `.env:76`; the value's sha256 prefix moved `190379e5d6ce` → `3c7aadda9fbb` (compared by
hash, never printed). Revocation was *proved*, not assumed: the old token — recovered from
`agent.log.3`, the leak's own evidence — returns `HTTP 401 Unauthorized` from `getMe`.

One non-obvious step was required. `docker restart` does **not** re-read `env_file`; compose bakes
those values in at container-create time, so the container was still holding the now-dead token
after a plain restart. `docker compose up -d --force-recreate neomind-telegram` was needed, after
which the in-container `TELEGRAM_BOT_TOKEN` hash matched the new `.env` value.

Post-rotation verification: the bot reports its LIVE startup line, container healthy, and the real
Telethon smoke plan returned **8 PASS / 0 FAIL** (`/start`, natural language, `/status`, `/model`,
arithmetic, `/mode`, an LLM answer, `/clear`). `/status` independently confirmed the router fix from
the Telegram surface: Router 🟢 on `deepseek-v4-flash`. Across the 26 log lines written since
recreation — which include the entire Telethon run, the busiest period — token-shape hits: **0**;
`api.telegram.org/bot` hits: **0**.

The Telethon session file is schema v8 (6 columns) written by Telethon 1.43.2 in
`~/.neomind_fin_venv` (py3.14). Running the tester from `.venv` (Telethon 1.42.0) fails with
`ValueError: too many values to unpack (expected 5)`. Run the Telegram gate from the fin venv.

Old log purge remains deliberately deferred — rotation made those 35 MB inert, so no overwrite is
performed without explicit consent.

**Readiness honesty fix (`Desktop/LLM-Router/router.py`).**

`CloudPoller._fetch_provider` swallowed discovery failures and kept the prior list, so with every
key broken the router still answered `status: ok` and served its boot-time model catalog.

`/health` deliberately keeps returning 200 — `scripts/repair.sh` restarts the router when `/health`
fails, so making it fail on a bad upstream key would create a restart loop against a problem
restarting cannot fix. Instead it now reports `status: degraded`, per-provider `provider_status`
(with secret-redacted upstream errors), and `degraded_providers`. A new `/ready` returns **503**
when no cloud provider passed its last discovery.

Verified against a second router instance started on port 8010 with deliberately invalid keys:
`/health` → `status: degraded`, all three providers `ok=false` with real 401 text; `/ready` → 503.
The live router on :8000 was unaffected throughout and remains `/health` 200, `/ready` 200.

Remaining items — all debt, no open Phase 0 gate:

- **GLM/Z.ai account balance (operator action).** Auth is fixed; completions return 429 code 1113.
  Not a Phase 0 gate — the second-provider requirement is met by Kimi.

- **🔴 The full test suite has never completed — on any interpreter.** This corrects the earlier
  characterization of "intermittent pytest cleanup warnings, not a hard blocker". Investigated
  2026-08-09; details and the reproduction method are in
  `.claude/docs/troubleshooting/20260809-suite-never-finished.md`.

  - **Hang 1 at ~54% — FIXED** (`934c67b`). `tests/test_persistent_bash_full.py` mocked the queue's
    `get`, but `execute()` first calls `_drain_queue()`, which uses `get_nowait()`. An unconfigured
    MagicMock never raises `queue.Empty`, so the `while True` spun at 100% CPU. It hung before any
    assertion, so those five tests never verified anything. Confirmed pre-existing by reproducing
    at `c93e56e`. Now 40/40 in both venvs, under 4s.
  - **Hang 2 at ~71% — OPEN.** Different failure mode: 0.1% CPU, blocked in
    `select_kqueue_control_impl → kevent`, i.e. an asyncio event loop waiting indefinitely — an
    async test awaiting something that never completes, with no timeout. The specific test is not
    yet identified; naming it requires a `-v` run (a `-q` run only prints dots), which reaches the
    hang in roughly half an hour.
  - **Beyond 71% is unexplored.** Nothing has ever run past that point, so further hangs or
    failures should be expected rather than assumed absent.
  - **Consequence for every "N passed" figure in this document and its predecessors:** they are
    subset results. Treat "the suite is green" as unproven until a run terminates.
  - Suggested next step when this is picked up: add a per-test timeout (`pytest-timeout`) so a hang
    fails one test instead of blocking everyone, then work through what it reports.

- **115 leaked heartbeat threads.** `sample` showed 115 of 134 threads named `heartbeat`, from
  `agent/evolution/scheduler.py:155` → `health_monitor.py:525`. `HeartbeatWriter.stop()` only sets
  a flag — it never joins, and nothing calls it; `tests/conftest.py` has no cleanup. Each test that
  instantiates the scheduler leaks one. They sleep rather than spin, so they are not the hang, but
  each repeatedly mkdirs and writes the same file, which is a plausible source of the original
  "Too many open files" report.
- Repeated Python 3.14 runs can emit non-fatal pytest temporary-directory cleanup warnings with
  `Errno 24: Too many open files`; assertions still pass, but the warning is not evidence of
  file-descriptor hygiene and remains open diagnostic debt. Not yet reproduced on a full 3.14 run.
- The Python 3.14 environment cannot collect the whole suite (missing `hypothesis`, plus
  `agent.finance.chat_stream` / `agent.search.OptimizedDuckDuckGoSearch` import errors). The
  "313 + 93 passed" figures are a relevant subset, not a full-suite result, in that environment.
- Working tree still mixes pre-existing and Phase 0 changes and is uncommitted; splitting plus
  gitleaks and PII scans is required before any commit.

### Phase 1 — Runtime contract skeleton and authoritative `ToolExecutor`

**Purpose:** create the boundary without changing terminal presentation.

Expected additions:

```text
agent/runtime/events.py
agent/runtime/session.py
agent/runtime/tool_executor.py
agent/runtime/permissions.py
agent/runtime/ports.py
tests/runtime/
```

Tasks:

1. Define frozen runtime events, session/turn/call/request IDs, and sequence behavior.
2. Define `LLMPort`, `ConversationStorePort`, `ToolRegistryPort`, `AuditPort`, and
   `PermissionBroker` protocols.
3. Implement `ToolExecutor` against the existing real `ToolRegistry`.
4. Move validation, capability filtering, permission policy, approval matching, audit, and actual
   `tool_def.execute()` behind `ToolExecutor`.
5. Adapt current `AgenticLoop` to request execution through this executor.
6. Add an import-boundary test preventing runtime → frontend imports.
7. Define interruption semantics before promising cancellation:
   - `cancellable`: the tool exposes a real cancel/terminate handle;
   - `blocking`: cancellation is recorded but the runtime waits for completion;
   - `abandon_result`: the caller stops awaiting/displaying the result while the audit explicitly
     records that the underlying side effect may continue.
   Reconcile these semantics with `ToolDefinition.interrupt_behavior`; cancelling an
   `asyncio.to_thread()` task alone is not evidence that the synchronous tool stopped.
8. Audit registered tool callbacks for direct stdout/stderr (including Telegram WebSearch). Replace
   UI-facing prints with structured `ToolOutputDelta`/tool-log events or normal logging. Do not use
   process-global stdout redirection around concurrent tools.

Done gate:

- No code outside `ToolExecutor` executes a runtime tool in the new path.
- Unit tests cover allow/ask/deny, timeout/disconnect, parameter substitution, critical risk,
  read-before-edit, async tool execution, each declared interruption behavior, and execution
  exceptions.
- Runtime tests capture empty stdout/stderr through at least one real registered tool and prove no
  `input()` call. Fake tools alone do not satisfy this gate.
- Existing UI can still use the compatibility adapter.

### Phase 2 — Extract real streaming into `LLMPort`

**Purpose:** make text/thinking/status chunks runtime data instead of terminal side effects.

Tasks:

1. Extract provider request/SSE parsing from `code_commands.stream_response()` behind an LLM port.
2. Emit true incremental chunks rather than returning a completed string as one delta.
3. Separate provider-neutral chunks from DeepSeek-specific reasoning fields in the adapter.
4. Move first-token, usage, finish reason, retryable error, cancellation, and timeout into typed
   events/results.
5. Keep a legacy renderer adapter so the existing REPL's appearance does not need to change yet.
6. Prevent double history writes while both legacy and new paths coexist.

Done gate:

- Recorded SSE fixtures reproduce the same ordered event trace deterministically.
- DeepSeek text and reasoning streams work through the port.
- A second fake/provider fixture uses the same runtime without frontend changes.
- Cancelling a turn closes the provider stream and emits one terminal event.
- Runtime itself produces no terminal output.
- **Usage/cost accounting survives the extraction.** Token counts and `/cost` output remain correct
  after streaming moves behind the port; today they are fed by
  `code_commands` → `_query_engine.budget.record_usage()` (§2.5), which the new path must replace
  rather than orphan. Assert on a real `/cost` value, not on the call existing.

### Phase 3 — Build `AgentSession` and migrate headless first

**Purpose:** prove a second surface can consume the contract without its own LLM/tool loop.

Tasks:

1. Implement `AgentSession.run_turn()` for the initial vertical slice:
   ordinary text → model stream → optional tool → result → final response.
2. Make the session the sole owner of turn history mutation and store calls.
3. Use `AgenticLoop` internally for tool-round orchestration through the new executor.
4. Implement a headless event consumer for text and JSON output.
5. Delete the manual headless parser/execution/continuation loop after parity passes.

Done gate:

- `neomind -p` uses `AgentSession` and contains no direct `ToolRegistry` execution loop.
- Text and JSON output contain one final response, correct usage, and stable error codes.
- Read-only tool works; write/execute is denied by default in non-interactive mode.
- Recorded conversation contains each user/assistant/tool message exactly once.
- Real subprocess tests cover success, provider error, tool denial, timeout, and Ctrl+C/termination.

### Phase 4 — Migrate the existing Prompt REPL

**Purpose:** preserve current usability while removing agent/runtime ownership from the UI class.

Tasks:

1. Replace `_stream_and_render()` and `_run_agentic_loop()` ownership with an event consumer.
2. Replace direct private-field reads with `SessionSnapshot` and explicit session operations.
3. Move permission answers to `resolve_permission(request_id, decision)`.
4. Keep Rich formatting, current keybindings, scrollback behavior, and prompt_toolkit fallback.
5. Move conversation save/load calls behind the session/store port.
6. Leave fleet on a compatibility facade in this phase.
7. Decide and execute the disposition of `cli/interface.py` (§2.1): migrate it to the session,
   reduce it to a diagnostic that cannot run turns, or delete it. Leaving it as an unmigrated
   fallback is not an option, because `main.py`'s broad `except Exception` routes users into it
   silently on any runtime error in the migrated path.

Done gate:

- `NeoMindInterface` never executes tools or mutates runtime history directly.
- Permission deny/once/scoped-session behavior passes in a real terminal, exercised in `coding` and
  `fin` mode. `chat` mode is separately verified to still run no tool loop — a green `chat`-mode
  session is not evidence about tools or permissions (§2.4).
- Streaming, thinking toggle, model/mode switch, commands, tool results, interruption, resume, and
  exit are verified in a real iTerm2 window.
- No observed regression is hidden by the broad fallback in `main.py`; startup/runtime exceptions
  are typed and reported correctly, and a forced runtime exception is shown to surface as an error
  rather than a silent demotion into `cli/interface.py`.

### Phase 5 — Migrate Telegram

**Purpose:** remove the largest duplicate turn implementation while retaining Telegram-specific UX.

Tasks:

1. Construct an `AgentSession` per Telegram conversation/session identity.
2. Retain Telegram message-edit throttling, HTML escaping, status messages, and attachment handling
   only in the adapter.
3. Replace Telegram-owned provider/SSE/tool continuation loops with runtime events.
4. Move Telegram's storage implementation behind `ConversationStorePort` without changing its
   database format unless a migration is explicitly justified.
5. Keep finance/dashboard routes on a documented compatibility path until each is audited; do not
   silently route special workflows through a generic chat turn.
6. Apply explicit remote-surface capability policy and authenticated permission behavior.

Done gate:

- Normal, thinking, tool-using, attachment, and error paths all consume `AgentSession` events.
- Telegram does not construct a second normal-turn LLM/tool loop.
- Real Telethon send/receive tests verify exact user-visible replies and tool denial behavior.
- Bot service is restarted and verified reboot-safe in its actual container/venv.
- CLI behavior remains unchanged after Telegram migration.

### Phase 6A — Consolidate commands, configuration, and persistence

**Purpose:** remove the remaining non-fleet control-plane coupling after all main surfaces share
turns.

Tasks:

1. Replace command magic strings with structured effects.
2. Consolidate new dispatcher, legacy UI handlers, and personality/core handlers into one registry
   with a temporary compatibility adapter.
3. Pass a session config snapshot/context instead of having frontends mutate the global
   `agent_config` proxy.
4. Define one conversation store interface with CLI JSON/file and Telegram SQLite adapters.
5. Add dependency/import tests for these surface boundaries.

Done gate:

- No magic control strings remain in application command results.
- Mode/model changes are session scoped and concurrent sessions do not leak configuration.
- One command registry defines application commands.
- Each session has exactly one conversation-store owner and compatibility adapters do not
  double-write.

### Phase 6B — Migrate fleet turn and lifecycle boundaries

**Purpose:** migrate the independent fleet worker turn without mixing it into command/store work,
then remove UI ownership of fleet lifecycle.

Tasks:

1. Extract fleet lifecycle behind `FleetSessionPort`; emit fleet events instead of letting the UI
   own daemon loops and polling/render threads.
2. Migrate `fleet/worker_turn.py` off its own `requests.post`/model-selection path onto
   `AgentSession` (§2.4). This is the fleet *turn* coupling, distinct from the lifecycle work in
   task 1, and it is what lets the Phase 0 freeze on fleet tool execution be lifted.
3. Preserve persona routing, fail-fast feedback, finance signal parsing/persistence, task queue
   completion, supervisor notification, and audit behavior through explicit adapters/events.
4. Add dependency/import and real fleet-run tests for both boundaries.

Done gate:

- Fleet can run without importing `NeoMindInterface` and the REPL only renders fleet events.
- Fleet worker turns produce runtime events and contain no direct provider call; a fleet worker that
  requests a tool is subject to the same `ToolExecutor` and permission policy as every other surface.
- Existing fin/coding/chat worker results, artifacts, fail-fast behavior, and leader notifications
  pass a real fleet run after a cold process boot.

### Phase 7 — Be drivable by an existing harness (revised 2026-08-16)

**Purpose:** stop at the boundary. Let someone else's client be the interface.

**Decision (operator, 2026-08-16).** Building NeoMind's own Textual TUI is *deferred, possibly
indefinitely*: "自己的 TUI 带来的边际效益其实有待商榷 — 除非我有非常特殊的需求且市面上没有能满足的,
否则为啥要继续自建 TUI 呢". The want is to switch freely between **pi** and the **DeepSeek Harness**
as the front end, with an own-TUI only if a need appears that neither covers.

That is the same buy-vs-build rule applied everywhere else here, and it changes what this phase
builds: not an interface, but the **adapter that makes NeoMind a server those clients can drive**.
Everything Phases 1–6B produced — frozen events, `AgentSession`, one `ToolExecutor`, session-scoped
config, typed command effects, a fleet that owns its own loop — is exactly the substrate such an
adapter needs, which is why D7 deferred it until now.

**Open question to settle first, by reading source rather than assuming:** DSH's `dsh-acp` speaks
**ACP** (open standard, JSON-RPC over stdio, official Python SDK). pi's protocol as surveyed on
2026-08-15 was **bespoke** — 4-byte big-endian length prefix over CBOR, nine commands. If that is
still true, one ACP server does not give "switch freely between pi and DSH"; it gives DSH plus every
other ACP client, and pi needs a second adapter. Check whether pi has since gained ACP support
before committing to either shape.

**Original scope, retained only as the fallback if no client fits:** conversation transcript with
incremental text; persistent input composer; model/mode/status bar; collapsible thinking/tool
panels; permission modal driven by `PermissionRequested`; cancellation and keyboard navigation;
session/history picker; optional fleet pane.

**Purpose (original):** add the richer interface only after it is a pure consumer.

Initial scope:

- conversation transcript with incremental text;
- persistent input composer;
- model/mode/status bar;
- collapsible thinking/tool panels;
- permission modal driven by `PermissionRequested`;
- cancellation and keyboard navigation;
- session/history picker;
- optional fleet pane after the fleet port is ready.

Explicitly deferred from v1: IDE editor, arbitrary plugin marketplace, browser GUI, remote protocol,
and full finance dashboard duplication.

Done gate:

- Textual imports no private `NeoMindAgent` fields and calls no tool directly.
- The same recorded event fixtures render in Prompt REPL, headless JSON, Telegram, and Textual.
- Resize, narrow terminal, Unicode/CJK, paste, long output, cancellation, reconnect/resume, and
  permission modals pass real-terminal tests.
- Prompt REPL remains available as a lightweight/recovery frontend.

### Phase 8 — Retire compatibility paths

**Purpose:** finish the migration instead of permanently maintaining parallel runtimes.

Tasks:

1. Reverse-dependency audit for old headless loop, UI tool execution, old streaming callbacks,
   duplicate command handlers, `cli/interface.py`, `fleet/worker_turn.py`'s provider path, and
   `QueryEngine`.
2. Move only proven-useful budget/compactor pieces into runtime with real integration tests. The
   `budget` object is a live `/cost` dependency (§2.5), so this is a prerequisite for step 3, not an
   optional harvest.
3. Remove dead `QueryEngine`/legacy paths only after zero callers are demonstrated **and** `/cost`
   is verified correct against the relocated accounting.
4. Remove the temporary `legacy|session_v1` switch.
5. Update architecture and operator documentation to match source truth.

Done gate:

- One normal turn engine remains, and every one of the five live entry paths inventoried in §2.4
  has been migrated, frozen, or deleted as planned.
- One tool executor and one permission policy path remain; the §2.4 execution-site table has exactly
  one live row.
- Import/reference searches and full tests show no live caller of removed paths.
- `/cost` and token accounting produce correct values after removal.
- All user surfaces (headless, Prompt REPL, Telegram, Textual, fleet workers) pass their real-client
  gates after a cold restart.

---

## 6. First runtime-contract implementation slice (after Phase 0)

The first runtime-contract vertical-slice PR, after the Phase 0 containment PR(s) are green, should
stop after this scenario works; it should not begin Textual work:

```text
1. Headless adapter submits a user turn.
2. Fake/fixture LLM emits TextDelta and proposes Read.
3. Runtime policy allows Read and ToolExecutor executes it.
4. Tool result returns to the loop.
5. LLM emits final TextDelta and TurnFinished.
6. A second fixture proposes Write.
7. No interactive broker exists, so PermissionRequested resolves to DENY.
8. The Write callable is proven not to have run.
```

Required artifacts for that slice:

- frozen event models;
- real-registry adapter;
- permission broker/policy and tool executor;
- minimal `AgentSession` orchestration;
- headless text/JSON consumers;
- event trace fixtures and security contract tests;
- compatibility adapter for the current REPL, without UI redesign.

This slice changes the central safety/ownership decision while keeping scope small enough to review.

---

## 7. Verification gates

### 7.1 Automated contract tests

Every phase affecting runtime must test:

- event ordering and exactly one terminal event;
- no direct stdout/stderr/input from runtime;
- one history write per semantic message;
- one LLM request per intended round;
- real `ToolRegistry` integration, not mocks alone;
- permission allow/ask/deny/timeout/disconnect/argument substitution;
- cancellation before LLM, during stream, while awaiting permission, and during tool execution;
  tool-execution assertions must match its declared `cancellable`, `blocking`, or
  `abandon_result` behavior and must not mistake cancelled `asyncio.to_thread()` awaiting for a
  terminated underlying operation;
- provider error and malformed SSE behavior;
- capability filtering equivalence between prompt visibility and execution;
- concurrent session mode/model/config isolation;
- import-boundary rules.

### 7.2 Real user surfaces

Automated unit tests are insufficient for declaring a migrated phase complete:

| Surface | Required validation |
|---|---|
| Headless | real `neomind -p` subprocess, text + JSON, exit status, signals |
| Prompt REPL | real iTerm2 boot/input/stream/tool/permission/interrupt/exit, in `coding`/`fin` mode |
| Telegram | real Telethon send/receive, message edits, tool status/denial, restart |
| Fleet worker | real fleet run producing worker turns; tool requests hit the shared executor |
| Textual | real terminal launch, keys, resize, stream, modal, cancellation, resume |
| Legacy fallback (`cli/interface.py`) | until disposed of (Phase 4): boots and cannot execute tools |

`SKIP` is not `PASS`. If a dependency or environment is missing, use the correct environment or
report the phase as incomplete.

The standard real-terminal runner uses `NEOMIND_AUTO_ACCEPT=1` for non-permission regression
scenarios. Dedicated permission scenarios are an explicit exception: they must launch without that
bypass and exercise the real prompt/deny path. Otherwise the test would deliberately skip the
behavior Phase 0 is meant to prove.

### 7.3 Environment coverage

- Install and test in each affected environment: repository `.venv` (Python 3.9 CLI/iTerm2),
  `~/.neomind_fin_venv` (Python 3.14 service/pytest/full dependencies), and the independently
  provisioned Telegram container when bot code is affected. This applies to the Phase 0 baseline
  itself, not just to later phases: per-environment output is what makes “green baseline” a claim
  about the project rather than one interpreter (§2.8).
- CLI changes require a fresh process boot.
- Telegram changes require actual service/container restart and post-restart verification.
- Provider tests use configured secrets from native environment only; fixtures and evidence must
  not contain credentials.
- DeepSeek gets the primary real-provider smoke. A second configured provider gets a switch smoke
  before declaring provider-neutral behavior complete.

### 7.4 Commit/publish gate

Before every commit, push, PR, or other external upload, follow the repository/user-required
gitleaks and PII scan process and show the output. Push scans cover the entire unpushed commit range
and commit messages, not only the working tree or staged files.

---

## 8. Rollout and rollback

1. Migrate one surface at a time; do not activate new runtime paths simultaneously in CLI and
   Telegram.
2. Use recorded event traces for comparison. Do not “shadow” live tool execution or duplicate live
   LLM calls.
3. Keep one temporary per-surface `legacy|session_v1` selection until that surface's automated and
   real-client gates pass.
4. If a migrated surface fails, route only that surface back to legacy while retaining security
   containment from Phase 0.
5. Never roll back by restoring fail-open permissions.
6. Remove the temporary selection in Phase 8 so the project does not end with two permanent paths.

---

## 9. Risks and mitigations

| Risk | Consequence | Mitigation/gate |
|---|---|---|
| Double history ownership | duplicate messages, context inflation | session is sole writer; exact-count tests |
| Double provider call | cost and duplicate side effects | request-count tests; no live shadow calls |
| Mutable approval/event race | wrong tool executes | immutable events + request/fingerprint resolution |
| Frontend disconnect while asking | fail-open execution | timeout/disconnect resolves to deny |
| Tool list differs from executor policy | LLM requests unavailable/unsafe tools | one capability snapshot for prompt + execution |
| Streaming reordering | broken Telegram/Textual display | turn sequence numbers + replay tests |
| Sync blocking leaks into UI | frozen terminal/event loop | provider/tool boundaries + cancellation tests |
| Broad `main.py` fallback hides runtime bugs | misleading diagnosis | typed startup vs runtime failures |
| Global config leaks across sessions | wrong model/mode/permissions | session snapshots + concurrency tests |
| Finance special routes silently regress | incorrect dashboard behavior | explicit compatibility boundary and separate audit |
| Fleet extraction expands scope | stalled core migration | defer *lifecycle* behind facade; keep the worker *turn* in scope with a Phase 0 freeze on its tool execution |
| Fleet workers grow tools while unmigrated | a second unaudited permission path appears after the audit concluded | Phase 0 architecture-test freeze; Phase 6B migration gate |
| `QueryEngine` deleted with live `budget` attached | `/cost` and token accounting silently break | relocate accounting first; Phase 2/8 gates assert a real `/cost` value |
| Dead code “fixed” instead of deleted | unguarded `tool_def.execute()` path survives the migration it contradicts | §2.4 execution-site table is the checklist; Phase 0 deletes `_execute_tool_call()` |
| Broad `main.py` fallback demotes users into `cli/interface.py` | migrated surface appears to work while an unmigrated one is actually serving | Phase 4 disposition + forced-exception test |
| Baseline established in one venv | “green” is true for py3.9 only | per-venv Phase 0 gate with attached output |
| Legacy path never removed | two architectures forever | Phase 8 removal gate and reverse-dependency audit |

---

## 10. Explicit non-goals

This plan does not authorize or require:

- a Rust rewrite;
- an immediate full rewrite of `NeoMindAgent`;
- a provider-router rewrite;
- a finance/dashboard behavior rewrite;
- replacement of the React browser/dashboard architecture; a future HTTP/SSE runtime adapter for
  browser chat is related work, not a Phase 0–8 gate here;
- a Telegram database migration without a separate need;
- moving every existing module into new directories;
- ACP/MCP/network frontend protocol design;
- deleting `QueryEngine` or legacy paths before reverse-dependency and parity evidence;
- replacing the Prompt REPL before Textual proves itself in real terminals.

---

## 11. Status tracker

| Phase | Status | Evidence |
|---|---|---|
| 0 — baseline + safety containment | Gates passed 2026-08-07 (commit pending) | containment implemented; dual-env automated suites and real headless/iTerm2 flows pass; router env repaired → DeepSeek `alive`, Kimi `42`, local MLX `42` (GLM 429 balance, non-gating); bot token rotated, old token proved dead via `getMe` 401, Telethon smoke 8 PASS / 0 FAIL; log leak contained with 0 token hits post-fix |
| 1 — runtime contract + ToolExecutor | Substantially done (8133280, 2cac93c) | frozen events + ports + policy + single ToolExecutor; real-registry integration (caught a wrong param-name assumption on write); AST + subprocess import boundary; AgenticLoop dispatch switchable through the executor with the switch asserted from both sides; 66 runtime tests py3.9, 209 incl. regression suites py3.14; cross-mode boot smoke green. Open: AgentSession itself, and moving the loop's read-before-edit / PreToolUse pre-checks into executor guards (Phase 3). |
| 2 — LLM streaming port | Substantially done (2026-08-15) | `agent/runtime/llm_stream.py` (frozen chunks + typed retryable errors), `agent/runtime/providers/openai_sse.py` (httpx async, pure `parse_sse_frame`), `agent/runtime/usage_accounting.py`; 118 runtime tests. Gates: fixtures replay to an identical ordered trace twice; a real DeepSeek call yields 7 text + 5 thinking chunks, usage (96/13/109) and finish_reason (proved to hit the network — a bogus key fails it with the provider's own 401); a second provider fixture runs through the same parser unchanged; early exit + `aclose()` closes the response; stdout and stderr are empty across a full stream; real provider usage drives the real `/cost` to `Tokens: 86 in / 18 out` and `$1.3700` on a priced fixture. Open: the loop still runs on `code_commands.stream_response()` — cutting it over, the legacy renderer adapter and double-history-write prevention move with `AgentSession` in Phase 3; "one terminal event" is a session-layer assertion and is deferred with it. |
| 3 — AgentSession + headless | Substantially done (2026-08-15) | `agent/runtime/session.py` (AgentSession: sole history writer, one terminal event per turn, permission answered by request_id not by mutation), `agent/runtime/headless.py` (event consumer), composition root + D8 switch in `main.py`. 162 runtime tests, 11 of them real subprocess runs. Gates: `-p` runs through AgentSession with no local ToolRegistry loop; text and JSON carry one final response, real provider usage and stable error codes (`llm_auth` on stderr, exit non-zero); a read tool runs and a write tool cannot; SIGINT exits 130 with no traceback; an unreachable provider fails instead of hanging; each user/assistant/tool message is recorded exactly once and no raw `<tool_call>` payload survives in history. **Found and fixed en route:** the headless capability set was derived from `permission_level is READ_ONLY`, and TeamDelete ("Delete an existing team"), TeamCreate, SendMessage, TodoWrite, TaskCreate and TaskStop all declare READ_ONLY — so unattended runs could delete teams and message other agents. Headless now names its 19 tools explicitly and re-checks the level. The mislabelling itself is untouched and remains a defect for every other surface. Open: the legacy loop stays behind `NEOMIND_HEADLESS=legacy` (D8) rather than being deleted the same day the new path went live; `tests/test_headless_permissions.py` is pinned to it and both go together. |
| 4 — Prompt REPL migration | Done (2026-08-16) | Task 1 landed behind `NEOMIND_REPL=session_v1` (D8) and proven in a real iTerm2 window: a plain turn, a tool round, a code-fence turn, and the permission dialog answered by hand with the command actually running (`Allow? [y]es… y` → `✓ Bash: PERMISSION_PATH_OK`). `_stream_and_render_session()` builds a per-turn AgentSession seeded from the agent's history and writing back through a store adapter, so `/history`, `/compact` and token accounting keep reading one authoritative list. **Four wiring defects the terminal found and the suite could not:** the renderer never flushed the content filter, which buffers, so short answers vanished entirely; `PermissionPolicy.interactive` defaults to False, turning every ASK into DENY ("no interactive broker") even with a broker attached; the broker returned a `Decision` where the executor requires an `Approval` bound by fingerprint, so every tool was silently refused; and the session treated the executor's *notification* callback as the ask and blocked on a future nothing would resolve. The broker port gained `params` — a dialog that cannot show what it is approving is the failure this layer exists to prevent. **Default flipped 2026-08-16** after the gate ran in real iTerm2 windows: streaming, tool results, /help, /think, NL mode switching, permission allow *and* deny in coding and fin, chat shown to run no tool loop, Ctrl+C leaving the session able to take the next turn, and --resume recalling a token from before a restart. `NEOMIND_REPL=legacy` remains until Phase 8. Tasks 5 and 6 closed the same day. History is one list: the store adapter writes through to `chat.conversation_history`, `/load` and `--resume` replace it, and the next turn's session seeds from whatever is there — asserted, including that the session's `_tool_result` marker never reaches the saved conversation and that a store raising OSError does not take the answer down. Fleet stays on the compatibility facade as the phase specifies and was checked against the new default rather than assumed: 80 passed in the full tier. Task 7 done and verified. Renderer: `cli/session_renderer.py` consumes `run_turn()` events and preserves the visible contract of `_stream_and_render()` — spinner stops on the first token, reasoning stays out of the transcript behind a one-line "Thought for Xs", content filters still apply (a raising filter loses styling, not the answer), tool results are summarised rather than dumped, and a refusal renders differently from a crash. 19 tests assert the exact bytes written. It sits in `cli/` because the runtime may not import anything that draws. **Not yet wired**: `NeoMindInterface` still calls `_stream_and_render()`/`_run_agentic_loop()`; flipping it needs the real-terminal gate, and the plan forbids calling a phase done on tests alone. Task 7 detail: `main.py` no longer wraps the whole interactive session in `except Exception`. Only an ImportError now means "interface unavailable", and it routes to `cli.interface.explain_unavailable_interface()`, a diagnostic that runs no turns — a runtime fault mid-session used to print one Note and silently demote the user into a second, unmigrated REPL with their session gone. Proved with an injected fault: exit 1, the real error surfaced, no "falling back" message. cli/interface.py's turn-running entry points are now unreachable from main.py and are left for Phase 8 rather than deleted mid-migration; `dev_test.py` and two test modules still import them. **Not yet started:** tasks 1-6 — the event consumer in `NeoMindInterface`, SessionSnapshot instead of private-field reads, `resolve_permission`, save/load behind the store port, and the fleet facade. The real-terminal gate (iTerm2, coding + fin, with chat separately shown to run no tool loop) has not been run. |
| 5 — Telegram migration | Done for the normal-mode turn (2026-08-16) | Baseline first: the live bot was driven with the version-locked Telethon client before anything changed — 8 PASS / 0 FAIL — and a dashboard 403 found en route was fixed in `.env` only and re-verified by a real round-trip returning real portfolio data. Then the surface was rebuilt in pieces, each one testable without a bot: `agent/integration/telegram_renderer.py` (17 tests) edits one message on an interval rather than per token, because Telegram rate-limits edits and a token-by-token loop gets the bot throttled; past 3900 chars it stops editing and sends the remainder, because editing past 4096 fails outright and used to strand the tail of a long answer; an error rewrites the placeholder instead of leaving "💭 ..." forever, and partial text survives a failure. `agent/runtime/providers/fallback.py` (25 tests) lifts the provider chain out of the 436-line method with the rule that makes it safe in front of a live UI — **failover is only legal before the first chunk**, since restarting on another provider would replay an answer the user has already read; 429 retries the *same* provider honouring `Retry-After` (which the typed error now carries) before advancing, which matters when the chain has one entry and advancing means having nowhere to go. `agent/integration/telegram_session.py` (20 tests) is the composition root and applies the remote-surface policy task 6 asks for: an explicit allowlist ∩ still-`READ_ONLY`, deliberately narrower than headless (no Read/Glob/Grep/LS — headless runs from the operator's own shell; a group-chat message is not that), `interactive=False` so an unanswerable ASK is DENY, tool results not persisted. That is what the bot already did, but by construction: today the agentic loop simply never sets `event.approved`, so a non-read tool silently ends the turn with no reply and no reason — now it is refused explicitly and rendered ⊘. Wired into `_ask_llm_stream_session` behind `NEOMIND_TELEGRAM=session` (D8, also declared in `docker-compose.yml`, default `legacy`), with 35 more tests covering the seam: the switch (a typo falls back to legacy, not silently forward), the render callbacks (cursor while streaming, footer only on the final edit, HTML rejection falls back to plain text rather than losing the answer), and a whole turn end-to-end offline. **Gate run against the live bot.** First the legacy path with this code loaded: 8 PASS / 0 FAIL, so the slice is a no-op until the switch moves. Then `NEOMIND_TELEGRAM=session`: 5 PASS / 0 FAIL, including a real refusal rendering as `🔧 Read ⊘` with the model explaining it was denied rather than inventing the file's contents. Container recreated from compose, healthy, `restart: unless-stopped`; a bare `docker compose up -d neomind-telegram` with no env var resolves to `session` and reports no change needed, so the running config is reproducible from the repo. Default flipped the same day.

**The first Telethon run was green and meaningless, which is the finding worth keeping.** `_handle_message` routes every plain private-DM message to `_handle_dashboard_agent` and returns — so a DM never reaches `_process_and_reply` at all, and the plan's "verification" was exercising a path this phase never touched. The container log gave it away: `fin route: intent=lookup` on every step, and neither the new `[session]` nor the old `[llm-stream]` marker anywhere. The reachable route from a DM is the unknown-slash fallthrough in `_handle_unknown_command`, which strips the `/` and forwards to `_process_and_reply`; the plan now uses that and says why, so nobody 'tidies' it back into plain messages.

**Three defects the real client found and 6300 tests could not.** (1) `ToolFinished` had no `denied` field, so both renderers recovered the refusal by testing whether `error` started with "permission denied" — while the session sets `error` to the policy's own wording, "tool not in session capability snapshot". The check never matched, and **every denial on every surface has been drawing as a red ✗ crash since Phase 4**. The fixtures passed because they fed a string the runtime does not produce; the regression test now derives the event from the real executor and asserts both renderers, and pins that the wording does *not* start with those words. (2) Past the edit ceiling `flush` stopped editing entirely, so the last edit that landed was a streaming one and the live message kept the "still arriving" cursor forever on a finished turn — seen on a real 1500-word answer. (3) Tool-call markup reached the chat: the session strips it from history, but the deltas carrying it have already streamed, so the user watched a raw `<tool_call>{"tool": "Read", ...}` payload appear.

**Open, deliberately.** Thinking mode (`_ask_llm_streaming`, 211 lines) and the attachment path are untouched and still on the legacy loop. The private-DM dashboard route stays where it is — task 5 of this phase says finance/dashboard routes keep a documented compatibility path rather than being folded into a generic chat turn — but it means the surface the operator uses most is still a second turn implementation, and Phase 8 cannot retire `_ask_llm_stream_normal` until that is faced. Tavily was at ~90% of quota on 2026-08-16, so the Telethon plan is pinned search-free (verified: 0 searches spent per run). |
| 6A — commands/config/store boundaries | Done (2026-08-16) | **Task 1 — command magic strings → typed effects.** `/exit` and `/mode` signalled the frontend by writing sentinels into `CommandResult.text`, the same field that holds the display text: `text="__EXIT__"`, `text=f"__MODE_SWITCH__{target}"`, matched on the other side with `result.text == "__EXIT__"` and `.replace("__MODE_SWITCH__", "")`. One field, two channels — a command whose ordinary output equalled a sentinel would quit the application, and the TUI this migration exists to enable could not be written without knowing every sentinel's spelling and how to slice its argument back out. Now frozen `Effect` objects carrying arguments as fields, with `CommandResult.effect(kind)` so a frontend asks rather than isinstances through a tuple. Verified in a real iTerm2 window because this is pure frontend control flow: `/mode coding` switches and redraws (52 tools, workspace banner), the next turn answers in the new mode, `/exit` prints Goodbye and the process returns to the shell, and no sentinel is on screen in any dump. **The gate's first run was itself wrong** — two of three dumps came back empty because `start_recording()` accumulates what `capture()` polls and a bare `sleep()` polls nothing, so "no sentinel on screen" passed vacuously; it now polls while waiting and treats an empty dump as failure. Two guard tests scan for the pattern returning. **Task 3 — session-scoped configuration.** The contextvar mechanism already existed for fleet workers and no interactive surface used it, so every frontend write landed on the process-wide default; `agent_config.py`'s own comment says reads "fall back to a process-wide default when no worker has called set_current_config()". Connected rather than rebuilt: `fork_current_config()` + `bind_session_config()`, called once from `NeoMindInterface.run()`. Forked rather than freshly constructed because YAML settings are deterministic given the mode but mutated state is not — `main.py` writes `agent_config.system_prompt`, whose setter lands in `_active`, and a fresh manager would silently run the agent with the file's default prompt; overrides copy by `_*_override` suffix so a later property is not forgotten. Bound in `run()` because main.py configures mode and prompt before calling it. Proven by mutation: drop `_active` and the system-prompt test fails; make the bind a no-op and all three isolation tests fail. Real terminal: `/permissions plan` → "Permission mode: plan", mode switch still redraws, a turn after the fork answers normally. Unmigrated surfaces unaffected — binding is optional and an unbound context still reads the process config.

**Verification harness (2026-08-16), prompted by two vacuous passes in one day.** `tests/integration/evidence.py` enforces: prove the observation happened and observed the thing under test, before asserting anything about it. An empty capture raises at construction; a witness must be established before any assertion; `absent()` is refused without one, because absence is exactly what an empty capture looks like; `require_path_marker()` asserts the new code ran and the legacy path did not run alongside it, since a run exercising both proves neither. Wired into the effects gate (which now reports which witness earned each pass) and the Telethon runner (which voids the whole run if `[session]` never appeared) — verified both directions against the live container. Self-tested in `tests/test_evidence_harness.py` using the two real failures as cases.

**Task 2 — one command registry.** Commands reached the user through three places: the registry, a 21-branch `if cmd == ...` chain in `_handle_local_command`, and personality handlers on `agent.core`. Measured before touching anything: **14 of the 21 branches were already unreachable** — the dispatcher answers first and returns — so editing the legacy `/clear` changed nothing while looking like the place to do it. They were reachable only when `create_default_registry()` raised, and silently serving a *different* implementation of every command is worse than saying the registry is broken, so that now reports and the 279-line chain is deleted. The seven genuinely frontend-owned commands (`fleet`, `expand`, `freeze`, `unfreeze`, `guard`, `sprint`, `evidence`) are declared into the same registry by `cli/ui_commands.py` — 58 → 65 commands — because "what commands exist" has to have one answer or autocomplete, `/help` and the mode-availability check each learn a different list. It registers into `NeoMindAgent`'s per-instance registry, so nothing leaks into Telegram's.

**What the deletion exposed.** 27 tests failed, and the reason is the finding: `_make_mock_chat` gave the interface a MagicMock dispatcher, so `dispatch()` returned a mock that failed on await, the interface swallowed it, and **every command test had been driving the dead legacy copy rather than the command system**. Fixing the fixture to build a real registry dropped it to 9, and each remaining one was a genuine behavioural difference — two of them lost long ago rather than by this change: bare `/permissions` stopped toggling and `/debug dump`/`/debug clear` stopped existing when the registry's thinner copy began answering first. Nothing reported either, because the only tests covering them were aimed at the unreachable copy. Consolidation means one implementation that does what both did, so the registry versions gained the toggle and the two subcommands. The third — mode gating, which told the user `/run` is coding-only — this change did remove, and it is restored on the single dispatch path. A fourth, `_handle_local_command` returning None on a dispatcher exception, was silently handing `/permissions` to the model as prose; it now reports the failure.

**Task 4 — one conversation store owner.** `ConversationStorePort` already existed; both `NeoMindInterface._HistoryStore` and `TelegramHistoryStore` implement it, `AgentSession._append` is the single write path during a turn, and the Telegram migration already removed the pre-store that would have double-written the user's question. Asserted rather than assumed in `tests/test_surface_boundaries.py`.

**Task 5 — boundary tests.** `tests/test_surface_boundaries.py`: no second command chain, every declared UI command has its method, registration never overrides an existing command, a missing registry is reported not worked around, no control signal travels in `CommandResult.text` anywhere in the tree, the REPL binds its own config, both store adapters satisfy the port with one writer, and the Phase 5/6A modules import no frontend (parsed, not grepped — the renderer's own docstring contains the words "does not import telegram", which a text search cannot tell from an import).

**Real terminal, 30 assertions across 13 observations**, each with a witness: mode switch redraws, a turn answers in the new mode, `/permissions plan` sets it, six commands that lost their legacy copy still work (`/history`, `/skills`, `/config`, `/evidence`, `/freeze`, `/expand`), bare `/permissions` toggles, `/debug dump` prints the log again, and `/run` in chat mode says it is coding-only. The mode-gate probe was initially run from *coding* mode, where `/run` is available — it proved nothing and was re-run from chat. |
| 6B — fleet turn/lifecycle boundaries | Done (2026-08-16) | **Task 2 — the worker turn.** `worker_turn.py` reached the provider itself, which made fleet the last surface with its own turn implementation and the reason `test_fleet_worker_turn_boundary.py` froze it as LLM-only. It migrates at one seam: `worker_turn` already injects its LLM call as `(model, system_prompt, user_prompt) -> str` and all three persona handlers use it, so replacing the default moved fin, coding and chat at once with no change to persona logic. A fleet worker is the least supervised surface there is — unattended, scheduled, nobody to answer a prompt — so `fleet/worker_session.py` gives it the strictest policy: `interactive=False` and an allowlist ∩ still-READ_ONLY that excludes Read/Glob/Grep/Bash outright. The audit trail is preserved exactly, including recording a failed turn as an error before raising, which is what lets `execute_task` report `status=failed` without propagating.

**Task 1 — the lifecycle.** `NeoMindInterface` carried the fleet's asyncio loop and daemon thread as *class* attributes. A persistent loop is genuinely necessary (a synchronous REPL using `run_until_complete()` only turns the loop during each call, so workers freeze between inputs and cross-call task references fail with "future belongs to a different loop") but on the class it meant every interface in a process shared one — the same shape Phase 6A moved out of the config — and any second frontend would have had to rebuild it. `fleet/driver.py` owns it now, one per interface, and gains what class attributes could not have: `shutdown()` so a TUI opening and closing a fleet pane does not leak a thread per open, restart-after-shutdown, and a timeout, since a frontend blocked forever on a fleet call looks like a hung terminal with nothing on screen to explain it. Found en route: `concurrent.futures.Future.result` raises its *own* TimeoutError, a different class from `asyncio.TimeoutError` on 3.9, so catching only the latter let it escape bare.

**Tasks 3 and 4 — behaviour preserved, asserted end to end.** `tests/test_fleet_session_path_e2e.py` runs the fleet with only the *provider* faked: launcher, task queue, persona routing, AgentSession, ToolExecutor, signal parsing, the analysis write and the leader mailbox are all real. Covers fin signal → `write_analysis` → queue completion, one provider call per task, the persona system prompt reaching the model, the leader's XML `task_notification`, a coding task, and a provider failure. Plus a guard that the legacy default is never called, because a suite that silently tests the old path is the failure this phase already hit once.

**Freeze lifted, not deleted.** The old assertion (worker_turn executes no tools) stays — it is persona dispatch and should not execute anything itself. Four new ones say fleet may now use tools *only* through the shared path: no registry dispatch of its own, `interactive=False` and `auto_accept=False` present explicitly rather than by default, `CapabilitySnapshot.only(...)` rather than `unrestricted()`, and the live allowlist checked for filesystem/shell names so renaming the constant cannot widen it.

**Two defects found by doing it.** The launcher called `complete_task()` unconditionally while `complete_task` hardcoded `status='completed'` — so a failed worker turn was recorded in the queue as completed with the error text where the summary belongs, and anything asking the queue "did this work?" got the wrong answer, while the leader notification built two lines later correctly said failed. Pre-existing; fixed by threading the status the launcher already had. And flipping the default **silently broke every test that mocks `_default_llm_call`**: `_resolve_llm_call()` stopped returning it, so those mocks were bypassed and the tests began making real provider calls and writing the user's production audit log. Two conftest guards now: `NEOMIND_INVESTMENT_ROOT` points at a temp dir for the whole session (the mechanism existed, with "(tests)" in its docstring, and nothing used it), and `NEOMIND_FLEET` defaults to legacy unless a test opts in.

Default flipped to `session` after a real fleet run on coding-smoke with no env var set, verified by audit marker rather than by the answer: `fleet.worker.session_llm_call` present, `fleet.worker._default_llm_call` absent. `NEOMIND_FLEET=legacy` reverts. |
| 7 — be drivable by an existing harness | Done (2026-08-16) | **Scope changed by operator decision.** Building a TUI of our own is deferred, possibly permanently: "自己的 TUI 带来的边际效益其实有待商榷". Both adapters were built instead, and Python was moved to 3.14 first because the ACP SDK requires ≥3.10.

**What the survey got wrong, corrected by reading source.** The plan recorded DeepSeek Harness as `deepseek-ai/dsh`; the repo is `deepseek-ai/DeepSeek-Harness`. Its ACP package is *automation-only* by its own README — "not a presentation or human-interaction layer" — and its human interface is a **web GUI**, not a TUI. And pi still does not speak ACP: a fresh clone contains zero references to it. So "switch freely between pi and DSH" needs **two** adapters, and of the two only pi has a terminal UI.

**ACP** (`agent/integration/acp_*.py`, 47 tests). A pure translation plus a composition root, exactly the shape D7 predicted once an event stream existed. It is the **first remote surface that can ask**: Telegram and fleet are `interactive=False` because nobody is there, an ACP client implements `request_permission`, so the Phase 4 broker port finally has a second consumer. Eight guesses about the SDK were wrong, none catchable by a type checker, all found by constructing real models — the worst being `PromptResponse.usage`, which wants `Usage` and not `UsageUpdate`: pydantic drops a mistyped field rather than raising, so the response looked perfect and reported zero tokens forever. Discriminators are now derived from each model's `Literal` after one of five hand-typed values was wrong, and a boundary test fails if a literal reappears.

**pi** (`agent/integration/pi_*.py`, 54 tests). Nine commands over length-prefixed CBOR. The framing encoder is verified byte-for-byte against pi's TypeScript. pi implements CBOR itself, so whether it is a dialect was checked by parsing its output with a decoder written only from RFC 8949 — 104 bytes, every one consumed, CJK and nested containers intact. Kept fully separate from ACP because pi's `server` package calls itself "Experimental… may change or be removed without notice".

**`tools/protocol/` is the finding.** Our tests assert what we believe the protocol requires; that script asserts what pi requires, using pi's own TypeBox schemas. They disagreed on five points and every one would have reached a client: metadata and snapshot are different shapes, a tool is a transcript item rather than `{type,name,status}`, `queuedSteer`/`queuedSteerCount` are required (without them a client cannot attach at all), `model` is `{provider,id}`, and `phase: "busy"` is not a legal value — which only appears *after* a prompt, so the session would have looked healthy until the user spoke. Passing our own tests and passing the other side's validator are different claims; here they differed by four message shapes.

`steer` is answered `not_implemented` rather than approximated. Refusals travel in tool content on both protocols, since neither has a refused status — `ToolFinished.denied`, added the same day to stop denials rendering as crashes on the CLI and Telegram, is what makes that reliable in both. |
| 8 — compatibility retirement | Pending | — |

No phase may be marked complete based only on code review, imports, mocks, curl, or skipped tests.
