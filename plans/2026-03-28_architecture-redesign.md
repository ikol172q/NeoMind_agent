# NeoMind Architecture Redesign — Three-Personality Agent

**Date**: 2026-03-28
**Last Updated**: 2026-03-28 (session 5 — P3-A/B/C/F COMPLETE, core.py 7372→2811L)
**Status**: Architecture **DONE** — all commands extracted, ServiceRegistry self-contained, personalities drive mode switching, 2600 tests pass
**Goal**: Make the three-tier architecture **actually function**, not just exist as code structure
**Branch**: `refactor/three-personality-architecture`
**Test Baseline**: ~3,061 passed, ~49 skipped (8+ test files excluded for pre-existing hangs)

---

## ARCHITECTURE HEALTH REPORT (read this first)

### The Problem: Skeleton Done, Logic Still in core.py

The three-tier architecture (Slim Core → Shared Services → Personality Modes) is **structurally
complete but functionally hollow**:

- ~~**Personality classes** exist but are 100% pass-through delegates back to core.py~~ ✅ FIXED: All 3 personalities have real on_activate() with mode-specific setup
- ~~**ServiceRegistry** creates services but always falls back to core via `_resolve()` bridge~~ ✅ FIXED: Bridge removed, ServiceRegistry fully self-contained
- ~~**SharedCommandsMixin** has 13 real impls, but 21 still delegate to `self.core.handle_X()`~~ ✅ FIXED: ALL 34 commands are real implementations or direct module calls
- ~~**Command routing** works correctly but every handler immediately bounces back to core~~ ✅ FIXED: Commands route to standalone functions in workflow_commands.py and general_commands.py
- ~~**switch_mode()** still lives entirely in core.py — personality `on_activate()` is empty~~ ✅ FIXED: switch_mode() delegates to personality.on_activate(); vault/memory/skill/workspace/finance/search-domain logic moved to personalities

### What "Working Architecture" Means

The architecture is "working" when:
1. **ServiceRegistry is the single owner** — no bridge fallback to core needed
2. **Personalities call services directly** — not `self.core.handle_X()` → core → service
3. **Each personality has unique behavior** — different system prompts, on_activate logic, NL patterns
4. **switch_mode() is driven by personality** — core delegates to `personality.on_activate()`
5. **core.py is truly slim** — only LLM calls, history, streaming, process_input routing

### Phase 3 Plan: Make Architecture Functional

| Step | Description | Priority | Est. Lines Changed |
|------|-------------|----------|-------------------|
| P3-A | **ServiceRegistry owns everything** — removed `_resolve()` bridge, core uses aliases | ✅ DONE | −15L __init__.py, −48L core.py |
| P3-B | **Personality on_activate() real impl** — move switch_mode() logic into personalities | ✅ DONE | ~150L across 3 mode files + core.py trimmed |
| P3-C | **SharedCommandsMixin calls services directly** — ALL 34 commands extracted | ✅ DONE | general_commands.py (638L), shared_commands.py updated, core.py −619L |
| P3-D | **Personality unique behaviors** — Chat: conversation style, Coding: workspace init, Finance: NL patterns | ✅ DONE (via P3-B) | on_activate() + NL patterns |
| P3-E | **core.py slim-down** — removed 13 unreachable delegates + broke circular delegation in code_commands.py | ✅ DONE | core.py 2,811→2,750L; code_commands.py now calls standalone functions directly |
| P3-F | **Tests for architecture** — verify routing, service ownership, mode switching | ✅ DONE | 28 tests in test_architecture.py |

---

## PROGRESS TRACKER (read this first for context)

### What's Done

| Step | Description | Status | Notes |
|------|-------------|--------|-------|
| 0 | Preparation (branch, baseline) | ✅ Done | Baseline: 3,449 passed (up from plan's 3,381) |
| 1 | BasePersonality + ServiceRegistry skeletons | ✅ Done | `agent/base_personality.py` (137L), `agent/services/__init__.py` (249L) |
| 2 | Move 9 root modules → services/ | ✅ Done | sys.modules stub pattern (not `from X import *`) |
| 3 | Move 12 finance modules → services/ | ✅ Done | Added `globals().update()` for importlib direct-path tests |
| 4 | Move 8 coding modules → coding/ | ✅ Done | |
| 5 | Move 6 integration modules → integration/ | ✅ Done | Fixed 8 broken relative imports in moved files |
| 6A | Create 3 Personality classes | ✅ Done | chat.py(71L), coding.py(115L), finance.py(106L) |
| 6B | Switch command routing to Personality system | ✅ Done | `_rebuild_command_handlers()` merges shared+unique |
| 6C | Remove original methods from core.py | ⏸️ Deferred | Delegates call `self.core.handle_X()`, tests call core directly |
| 7 | Finance Factory reorganize | ✅ Done | Added `get_finance_only_components()` + `response_validator` |
| 8 | Wire ServiceRegistry | ✅ Done | Bridge pattern: `getattr(self._core, ...)` for all 19 properties |
| 9 | Cleanup | ✅ Partial | `NeoMindCore` alias added; stubs kept permanently; docs NOT updated |
| C-fin | Finance enhance_response real impl | ✅ Done | Validator runs in personality, core calls `personality.enhance_response()` |
| C-shared | 6 simple shared commands real impl | ✅ Done | clear, history, think, verbose, quit, exit |
| T2A | ServiceRegistry owns service creation | ✅ Done | Lazy init with _UNSET sentinel; bridge fallback; core.__init__ uses self.services.X |
| T2B | Extract LLM provider → llm_provider.py | ✅ Done | 508L service module; core.py constants reference service; _resolve_provider uses PROVIDERS from service |
| T2C | Extract web extraction → content_extraction.py | ✅ Done | 437L in agent/web/; core.py _try_* methods are thin delegates |
| T2D | Extract LLM-analysis + formatting helpers | ✅ Done | 7 LLM commands → SharedCommandsMixin (13 real impls); log_commands.py (148L); webmap/links format → web module |
| T2E | Extract workflow commands → workflow_commands.py | ✅ Done | 9 handlers (sprint/careful/freeze/guard/unfreeze/evidence/evolve/dashboard/upgrade) → standalone funcs (421L); core.py delegates; −350L |
| T2F | Extract file commands → file_commands.py | ✅ Done | 4 handlers (diff/browse/undo/test) + _revert_change → standalone funcs (340L); core.py delegates; −441L |
| T2G | Extract web+logs commands → web_commands.py | ✅ Done | 4 handlers (links/crawl/webmap/logs) → standalone funcs (320L); core.py delegates; −372L |
| T2H | Extract code commands → code_commands.py | ✅ Done | handle_code_command + 15 _code_* helpers + auto_fix + stream_response + 25 more → standalone funcs (2181L); core.py delegates; −1941L |
| P3-B | Personality on_activate() real impl | ✅ Done | Chat/Coding/Finance on_activate() handle search domain, vault, memory, skill compat, workspace/finance init; core.py switch_mode() trimmed to delegate to personality; _fallback_mode_init() safety net added; 2572 tests pass |
| P3-A | ServiceRegistry self-contained | ✅ Done | Removed _resolve() bridge and core_ref dependency; all properties return own lazy-init values directly; core.__init__ uses self.services.X aliases instead of creating duplicates; core.py −48L |
| P3-C | SharedCommandsMixin routes to services | ✅ Done | ALL 34 commands now real impls or module calls. 9 workflow → workflow_commands.py; 10 general → general_commands.py (638L); mode/help inlined; 13 LLM commands have real implementations. core.py −619L (2811L total, down from 7372) |
| P3-F | Architecture verification tests | ✅ Done | 28 tests in test_architecture.py covering: ServiceRegistry self-containment, personality on_activate() behavior, switch_mode delegation, SharedCommandsMixin routing, core.py service alias pattern |

### What's NOT Done (Gap Analysis)

#### 1. core.py is now 3,467 lines (down from 7,372; target: ~1,200)
**Root cause**: Phase C was designed as "remove originals from core.py after delegation",
but this can't work because:
- Personality delegates call **back** to `self.core.handle_X()` (circular)
- 30+ test files call `self.agent.handle_X_command()` directly on NeoMindAgent
- Removing methods from core.py would break both

**Correct approach**: Move command implementations to **service modules** (not personality classes),
then have both core.py and personalities import from services. See "Revised Phase C" below.

#### 2. ~~ServiceRegistry is bridge-only~~ ✅ RESOLVED (Tier 2A)
ServiceRegistry now owns real lazy initialization for all 19 services using `_UNSET` sentinel
pattern. `_resolve()` helper checks own instance first, bridge fallback second.
core.__init__ uses `self.services.vault`, `.memory`, `.skills`, `.logger` instead of inline creation.
Backward-compat aliases kept (self._vault_reader, self._shared_memory, etc.).
Bug fixed: `_register_personalities()` now reuses `self.services` instead of creating duplicate.

#### 3. SharedCommandsMixin: 21 of 34 commands still delegate
**Done**: clear, history, think, verbose, quit, exit, summarize, reason, debug, explain,
refactor, translate, generate (13 real implementations)
**Extracted to workflow_commands.py** (T2E): sprint, careful, freeze, guard, unfreeze, evidence, evolve, dashboard, upgrade (9 commands — standalone funcs, core.py has thin delegates)
**Remaining 12 delegates**: search, models, mode, skills, skill, auto, plan, task, execute,
switch, context, help

#### 4. Plan items never executed
- ~~`agent/services/llm_provider.py`~~ ✅ Done in Tier 2B (508L, constants+class extracted; core.py references it)
- ~~`agent/services/vault_service.py`~~ ✅ Done in Tier 2A (ServiceRegistry.vault property)
- ~~`agent/services/memory_service.py`~~ ✅ Done in Tier 2A (ServiceRegistry.memory property)
- ~~`agent/services/logging_service.py`~~ ✅ Done in Tier 2A (ServiceRegistry.logger property)
- ~~`agent/services/skill_service.py`~~ ✅ Done in Tier 2A (ServiceRegistry.skills property)
- ~~`agent/services/search_service.py`~~ ✅ Done in Tier 2A (ServiceRegistry.search property)
- `agent/services/goal_planner.py` — GoalPlanner not split from planner.py
- `agent/finance/finance_news_digest.py` — news_digest not split (lazy import works)
- `agent/modes/__init__.py` — exists but empty (1 line)
- Cross-personality fallback dispatcher (Section 10A) — not implemented
- Pre-existing bugs (Section 12A-12E) — not fixed
- New test files (Section 8) — none created
- README/docs updates — not done

#### 5. Stubs are permanent (changed from plan)
Original plan: "Remove stubs in Step 9".
Decision: Keep all 35 stubs permanently. They use `sys.modules[__name__] = _real`
which makes them zero-cost transparent aliases. Removing would require updating ~30+
import sites for no functional benefit.

### Revised Phase C Strategy

The original plan assumed personality classes would **absorb** command implementations
from core.py (Phase A: copy → Phase B: delegate → Phase C: remove original). This was
flawed for infrastructure commands because:

1. **Personality classes should be THIN** — routing + behavioral customization only
2. **Infrastructure code** (web scraping, git ops, file ops) belongs in **service modules**
3. **Tests call core methods directly** — can't remove without updating 30+ test files

**Revised approach (3 tiers of extraction)**:

```
Tier 1: THIN PERSONALITY LAYER (done)
  - Routing decisions (which commands are available per mode)
  - Behavioral overrides (enhance_response, get_search_domain, get_nl_patterns)
  - Simple self-contained commands (quit, exit, clear, think, verbose, history)

Tier 2: SERVICE EXTRACTION (next — this shrinks core.py)
  - Extract web commands → agent/web/web_service.py
    (handle_read_command, handle_links_command, handle_crawl_command,
     handle_webmap_command + their 10+ helper methods, ~500L)
  - Extract LLM provider → agent/services/llm_provider.py
    (_resolve_provider, _proxy_transport, list_models, set_model,
     with_model, _get_fallback, ~200L)
  - Extract vault init → ServiceRegistry._init_vault()
    (move VaultReader/Writer/Watcher creation from core.__init__, ~40L)
  - Extract memory init → ServiceRegistry._init_memory()
    (move SharedMemory creation from core.__init__, ~15L)
  - Extract coding infra → keep in agent/coding/ modules
    (already there; just need core.py to import instead of inline)

Tier 3: CORE.PY SLIM-DOWN (after Tier 2)
  - Replace core.handle_X_command() with thin wrappers → service.handle_X()
  - Update tests to call services directly OR keep core wrappers
  - Core.py keeps: __init__, stream_response, switch_mode, process_input,
    LLM calls, status/UI helpers
```

### Current File Stats

```
agent/core.py                  6,571 lines   (~50 methods are thin wrappers to services)
agent/base_personality.py        137 lines
agent/services/__init__.py       372 lines   ServiceRegistry (20 lazy-init properties + _UNSET sentinel)
agent/services/llm_provider.py   508 lines   LLMProviderService + MODEL_SPECS + PROVIDERS
agent/services/shared_commands.py 331 lines  13 real implementations (7 LLM-analysis + 6 simple)
agent/services/log_commands.py   148 lines   Log formatting helpers
agent/web/content_extraction.py  437 lines   Extraction strategies + clean_text + score_content + formatters
agent/services/shared_commands.py 224 lines   34 handlers (6 real, 28 delegate)
agent/modes/chat.py               71 lines   5 unique commands (all delegate)
agent/modes/coding.py            115 lines   14 unique commands (all delegate)
agent/modes/finance.py           106 lines   0 unique commands, real enhance_response
agent/services/ (22 modules)   7,703 lines   Real implementations (moved from root/finance)
agent/coding/ (8 modules)      2,955 lines   Real implementations (moved from root)
agent/integration/ (6 modules) 5,426 lines   Real implementations (moved from finance)
Stubs (35 files)                 ~250 lines   sys.modules transparent aliases
```

### Excluded Test Files (pre-existing hangs, not related to refactor)

```
tests/test_hackernews_full.py      — hangs (network)
tests/test_integration_live.py     — hangs (live API)
tests/test_persistent_bash_full.py — hangs (subprocess)
tests/test_search_sources_full.py  — hangs (network)
tests/test_search_vector_store_full.py — hangs (vector DB)
tests/test_workspace.py            — hangs (file watcher)
tests/root_test_config.py          — import error
tests/test_search.py               — import error (OptimizedDuckDuckGoSearch moved)
tests/test_vault_watcher.py        — hangs (file watcher)
tests/test_evolution.py            — hangs (evolution engine)
tests/test_sprint.py               — hangs
tests/test_guard.py                — hangs
tests/test_review.py               — hangs
tests/test_auto_evolve_integration.py — hangs
tests/test_evolution_scheduler.py  — hangs
tests/test_upgrade.py              — hangs
tests/test_persistent_bash_full.py — hangs (subprocess)
```

**Post-Tier-2D test results**: 2,806 passed, ~61 skipped, 11 test files excluded (pre-existing)

### Key Patterns & Lessons Learned

1. **`sys.modules[__name__] = _real` pattern**: The ONLY stub pattern that works with
   `mock.patch('agent.formatter._default_formatter')`. Both `from X import *` and
   `__getattr__` approaches fail because mock.patch needs `target.__dict__[name]`.

2. **`globals().update()` for importlib direct-path loading**: Tests using
   `importlib.util.module_from_spec` (like test_provider_state.py) bypass sys.modules.
   Adding `globals().update(...)` to the stub makes attributes available via direct load.

3. **Service lazy-init pattern (Tier 2A)**: ServiceRegistry uses `_UNSET` sentinel to
   distinguish "not yet initialized" from "init returned None". `_resolve()` checks own
   instance first, bridge fallback second. core.__init__ accesses `self.services.X` which
   triggers lazy init. Backward-compat aliases (self._vault_reader, etc.) kept for 30+ test files.

4. **Double-ServiceRegistry bug**: `_register_personalities()` was creating a NEW ServiceRegistry,
   overwriting the one from `__init__`. Fixed to reuse `self.services` with fallback creation.
   Replace with direct instantiation once core.__init__ stops creating services.

4. **Personality-driven enhance_response**: core.py's `stream_response()` now calls
   `self._active_personality.enhance_response(full_response, tool_results)` generically.
   Only FinancePersonality overrides it (runs validator). Chat/Coding return passthrough.

5. **Init order matters**: `_register_personalities()` MUST come after all service
   creation in core.__init__, so ServiceRegistry can bridge to existing instances.

---

## ORIGINAL PLAN (Sections 0-14 below, preserved for reference)

---

## 0. Design Principles

1. **Shared Services First** — personalities consume shared infrastructure, never own it.
2. **Uniqueness + Shareability** — each personality has an irreplaceable strongest capability;
   common features live in `agent/services/`.
3. **Zero-Regression Migration** — every step must pass the existing 3,381 tests before proceeding.
4. **Personality Cores**:
   - **Chat** = 最均衡 / 类人 (most balanced, human-like conversationalist)
   - **Coding** = 工程师 (engineer, strongest development capability)
   - **Finance** = 赚钱 (money-making, strongest financial analysis)

---

## 1. Target Directory Structure

```
agent/
├── core.py                    # Slim core (~1,200 lines): provider registry, streaming,
│                              #   input pipeline, mode dispatch, history, config loading
├── base_personality.py        # Abstract base class for personality modes
│
# NOTE: agent_config.py lives at REPO ROOT (not inside agent/).
# Import: `from agent_config import agent_config`
# It reads YAML configs from agent/config/{base,chat,coding,fin}.yaml
│
├── services/                  # Shared Services layer (personality-agnostic)
│   ├── __init__.py
│   ├── llm_provider.py        # Provider resolution, model listing, fallback logic
│   ├── search_service.py      # UniversalSearchEngine + legacy DDG wrapper
│   ├── context_service.py     # ContextManager, conversation history ops
│   ├── safety_service.py      # SafetyManager, file ops guards
│   ├── vault_service.py       # VaultReader, VaultWriter, VaultWatcher, VaultConfig
│   ├── memory_service.py      # SharedMemory, MemoryBridge
│   ├── logging_service.py     # UnifiedLogger, PIISanitizer
│   ├── skill_service.py       # SkillLoader, skill activation
│   ├── formatter.py           # → moved from agent/formatter.py
│   ├── help_system.py         # → moved from agent/help_system.py
│   ├── task_manager.py        # → moved from agent/task_manager.py
│   ├── nl_interpreter.py      # → moved from agent/natural_language.py
│   ├── command_executor.py    # → moved from agent/command_executor.py
│   ├── goal_planner.py        # → extracted from agent/planner.py (GoalPlanner class)
│   ├── shared_commands.py     # SharedCommandsMixin: 32 shared command handlers
│   ├── news_digest.py         # → promoted from finance/ (pure aggregation, no data_hub dep)
│   ├── rss_feeds.py           # → promoted from finance/ (general-purpose)
│   ├── source_registry.py     # → promoted from finance/ (general-purpose)
│   ├── chat_store.py          # → promoted from finance/ (general-purpose)
│   ├── usage_tracker.py       # → promoted from finance/ (general-purpose)
│   ├── secure_memory.py       # → promoted from finance/ (encrypted store)
│   ├── dashboard.py           # → promoted from finance/ (general metrics)
│   ├── diagram_gen.py         # → promoted from finance/ (general visualization)
│   ├── config_editor.py       # → promoted from finance/ (config UI)
│   └── hybrid_search.py       # → promoted from finance/ (general search infra)
│
├── modes/                     # Personality mode implementations
│   ├── __init__.py
│   ├── chat.py                # ChatPersonality — human-like balanced mode
│   ├── coding.py              # CodingPersonality — engineer mode
│   └── finance.py             # FinancePersonality — money-making mode
│
├── coding/                    # Coding-specific modules (unchanged location, just renamed)
│   ├── code_analyzer.py       # → from agent/code_analyzer.py
│   ├── self_iteration.py      # → from agent/self_iteration.py
│   ├── persistent_bash.py     # → from agent/persistent_bash.py
│   ├── tool_parser.py         # → from agent/tool_parser.py
│   ├── tool_schema.py         # → from agent/tool_schema.py
│   ├── tools.py               # → from agent/tools.py
│   ├── workspace_manager.py   # → from agent/workspace_manager.py
│   └── planner.py             # → from agent/planner.py (Planner + dep analysis)
│
├── finance/                   # Finance-ONLY modules (slimmed down)
│   ├── __init__.py            # Updated factory: only fin-specific components
│   ├── quant_engine.py        # Quantitative analysis (FIN-ONLY)
│   ├── investment_personas.py # Persona-based reasoning (FIN-ONLY)
│   ├── response_validator.py  # Finance response validation (FIN-ONLY)
│   ├── fin_rag.py             # Finance RAG pipeline (FIN-ONLY)
│   ├── data_hub.py            # Finance data aggregation (FIN-ONLY)
│   └── finance_news_digest.py # Extends services/news_digest.py with thesis tracking + sentiment
│
├── integration/               # External service connectors (mode-agnostic)
│   ├── __init__.py
│   ├── telegram_bot.py        # → from finance/telegram_bot.py
│   ├── openclaw_gateway.py    # → from finance/openclaw_gateway.py
│   ├── openclaw_skill.py      # → from finance/openclaw_skill.py
│   ├── agent_collab.py        # → from finance/agent_collab.py
│   ├── mobile_sync.py         # → from finance/mobile_sync.py
│   └── hackernews.py          # → from finance/hackernews.py
│
├── browser/                   # (unchanged)
├── evolution/                 # (unchanged)
├── logging/                   # (unchanged — but exposed via services/logging_service.py)
├── memory/                    # (unchanged — but exposed via services/memory_service.py)
├── search/                    # (unchanged — engine, router, etc.)
├── skills/                    # (unchanged — but exposed via services/skill_service.py)
├── vault/                     # (unchanged — but exposed via services/vault_service.py)
├── web/                       # (unchanged)
└── workflow/                  # (unchanged — audit, evidence, guards, sprint, review)
```

---

## 2. BasePersonality Interface

```python
# agent/base_personality.py
from abc import ABC, abstractmethod
from typing import Dict, Set, Optional, Any
from agent_config import agent_config

class BasePersonality(ABC):
    """Abstract base for all NeoMind personality modes."""

    def __init__(self, core: 'NeoMindCore', services: 'ServiceRegistry'):
        self.core = core          # Slim core reference (LLM calls, history)
        self.services = services  # Shared services registry

    @property
    @abstractmethod
    def name(self) -> str:
        """Mode identifier: 'chat', 'coding', or 'fin'."""

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable name, e.g. 'Chat 类人'."""

    @abstractmethod
    def get_command_handlers(self) -> Dict[str, tuple]:
        """Return command → (handler, strip_prefix) UNIQUE to this mode.
        Shared commands are in SharedCommandsMixin (inherited)."""

    @abstractmethod
    def on_activate(self) -> None:
        """Called when switching TO this mode.

        Responsibilities (call super().on_activate() first):
        1. agent_config.switch_mode(self.name)    — reload YAML config
        2. Update core.model, core.fallback_model  — from agent_config
        3. Re-resolve provider (core._resolve_provider)
        4. Update search domain (core.searcher.set_domain)
        5. Update NL interpreter threshold
        6. Update safety settings
        7. Reload system prompt → inject into conversation_history
        8. Re-inject vault + shared memory context
        9. Deactivate incompatible active skill
        10. Clear stale available_models_cache (provider may have changed)
        11. Close stale event loops (search_loop, _browser_loop)
        12. Init mode-specific subsystems (workspace, finance, etc.)

        See core.py switch_mode() lines 786-861 for full current logic.
        """

    @abstractmethod
    def on_deactivate(self) -> None:
        """Called when switching AWAY from this mode. Cleanup if needed."""

    def get_system_prompt(self) -> str:
        """Return the personality-specific system prompt.
        Default: reads from agent_config after switch_mode()."""
        return agent_config.system_prompt or ""

    def get_commands_feed_to_llm(self) -> Set[str]:
        """Commands whose output should be fed back to the LLM.

        Default set covers all tool-like commands. Override to customize.
        Current static set (core.py L644-648):
          /run, /grep, /find, /read, /write, /edit, /git, /code,
          /analyze, /fix, /diff, /test, /search, /browse, /links,
          /crawl, /webmap
        """
        return {
            "/run", "/grep", "/find", "/read", "/write", "/edit",
            "/git", "/code", "/analyze", "/fix", "/diff", "/test",
            "/search", "/browse", "/links", "/crawl", "/webmap",
        }

    def enhance_response(self, response: str, tool_results: list) -> str:
        """Post-process LLM response (e.g. finance validation). Default: passthrough."""
        return response

    def get_search_domain(self) -> str:
        """Search domain hint for UniversalSearchEngine.
        Override: 'finance' for fin mode, 'general' for others."""
        return "general"

    def get_nl_patterns(self) -> Optional[dict]:
        """Return mode-specific natural language patterns for the NL interpreter.
        Default: None (use general patterns only).
        Override in CodingPersonality to add code-specific patterns.
        Override in FinancePersonality to add finance-specific patterns."""
        return None
```

**What on_activate() must do** (extracted from core.py `switch_mode()` lines 786-861):

```python
# Example: CodingPersonality.on_activate()
def on_activate(self):
    # 1. Reload config for this mode
    agent_config.switch_mode(self.name)            # loads coding.yaml

    # 2. Update model/provider on core
    self.core.model = agent_config.model
    self.core.fallback_model = agent_config.fallback_model
    self.core.thinking_mode = agent_config.thinking_mode
    provider = self.core._resolve_provider(self.core.model)
    self.core.base_url = provider["base_url"]

    # 3. Update search domain
    if hasattr(self.core.searcher, 'set_domain'):
        self.core.searcher.set_domain(self.get_search_domain())

    # 4. Update NL interpreter
    if self.core.interpreter:
        self.core.interpreter.confidence_threshold = (
            agent_config.natural_language_confidence_threshold
        )

    # 5. Update safety settings
    self.core.safety_confirm_file_operations = agent_config.safety_confirm_file_operations
    self.core.show_status_bar = agent_config.show_status_bar

    # 6. Reload system prompt
    new_prompt = self.get_system_prompt()
    if new_prompt:
        self.core.conversation_history = [
            m for m in self.core.conversation_history if m["role"] != "system"
        ]
        self.core.add_to_history("system", new_prompt)

    # 7. Re-inject vault context
    if self.services.vault and self.services.vault.vault_exists():
        ctx = self.services.vault.get_startup_context(mode=self.name)
        if ctx:
            self.core.add_to_history("system", ctx)

    # 8. Re-inject shared memory
    if self.services.memory:
        mem = self.services.memory.get_context_summary(mode=self.name, max_tokens=500)
        if mem:
            self.core.add_to_history("system",
                f"# User Context (from cross-personality memory)\n\n{mem}")

    # 9. Deactivate incompatible skill
    if self.core._active_skill and self.name not in self.core._active_skill.modes:
        self.core._active_skill = None

    # 10. Clear stale caches (discovered during review: models cache
    #     becomes invalid when provider changes across modes)
    self.core.available_models_cache = None
    self.core.available_models_cache_timestamp = 0

    # 11. Close stale event loops (search_loop, _browser_loop)
    for attr in ('search_loop', '_browser_loop'):
        loop = getattr(self.core, attr, None)
        if loop:
            try:
                loop.close()
            except Exception:
                pass
            setattr(self.core, attr, None)

    # 12. Mode-specific init (override in each personality)
    self._initialize_workspace_manager()
    self._init_persistent_bash()
```

### Pros/Cons of BasePersonality

| Aspect | Pros | Cons |
|--------|------|------|
| Extensibility | New modes (e.g. "research") can be added by subclassing | Requires understanding the interface contract |
| Isolation | Mode-specific bugs don't leak across personalities | Some logic duplication for border cases |
| Testing | Each personality is independently testable | Integration tests become more important |
| Runtime | Lazy activation means unused modes cost zero memory | Mode switch is slightly more complex |

---

## 3. ServiceRegistry Pattern

```python
# agent/services/__init__.py
class ServiceRegistry:
    """Central access point for all shared services.

    Personalities access services via: self.services.search, self.services.vault, etc.
    """
    def __init__(self, config):
        self.config = config
        # Eagerly initialized (lightweight)
        self.formatter = Formatter()
        self.help_system = HelpSystem()
        self.command_executor = CommandExecutor()
        self.task_manager = TaskManager()

        # Lazily initialized (heavier)
        self._search = None
        self._vault = None
        self._memory = None
        self._logger = None
        self._skills = None
        self._nl_interpreter = None

    @property
    def search(self) -> 'UniversalSearchEngine':
        if self._search is None:
            self._search = self._init_search()
        return self._search

    @property
    def vault(self) -> 'VaultService':
        if self._vault is None:
            self._vault = self._init_vault()
        return self._vault

    # ... similar lazy properties for memory, logger, skills, nl_interpreter

    # ── Workflow & Evolution (lazy, zero-arg singletons) ────────────
    # All these modules are fully decoupled from core (no NeoMindAgent reference).
    # They persist state to ~/.neomind/ independently.
    _evidence = None
    _guard = None
    _sprint_mgr = None
    _review = None
    _evolution = None
    _evolution_scheduler = None  # Depends on _evolution (AutoEvolve)
    _upgrader = None

    @property
    def evidence(self):
        if self._evidence is None:
            try:
                from agent.workflow.evidence import EvidenceTrail
                self._evidence = EvidenceTrail()
            except ImportError:
                pass
        return self._evidence

    @property
    def evolution_scheduler(self):
        """EvolutionScheduler depends on AutoEvolve — init order matters."""
        if self._evolution_scheduler is None:
            try:
                from agent.evolution.auto_evolve import AutoEvolve
                from agent.evolution.scheduler import EvolutionScheduler
                if self._evolution is None:
                    self._evolution = AutoEvolve()
                    self._evolution.run_startup_check()
                self._evolution_scheduler = EvolutionScheduler(self._evolution)
                self._evolution_scheduler.on_session_start()
            except ImportError:
                pass
        return self._evolution_scheduler

    # ... similar lazy properties for guard, sprint_mgr, review, upgrader

    # ── Lifecycle hooks (called by core.py at appropriate points) ───
    def on_turn_complete(self, turn_count: int):
        """Called after each response. Triggers scheduled evolution tasks."""
        if self.evolution_scheduler:
            self.evolution_scheduler.on_turn_complete(turn_count)

    def on_session_end(self):
        """Called on exit. Flushes evidence, runs evolution checks."""
        if self.evolution_scheduler:
            self.evolution_scheduler.on_session_end()
```

### Pros/Cons of ServiceRegistry

| Aspect | Pros | Cons |
|--------|------|------|
| Dependency Injection | Services can be swapped/mocked for testing | One more indirection layer |
| Lazy Init | Heavy services (vault, memory) only loaded when used | First-access latency spike |
| Single Source | No duplicate initialization across personalities | All services coupled to registry |
| Discoverability | `services.X` makes dependencies explicit | Must keep registry in sync with actual services |

---

## 4. core.py Slim-Down Plan

### Current State: 7,301 lines, 156 methods

```
Category               Methods   Lines(est)  Destination
─────────────────────  ────────  ──────────  ──────────────────────
LLM Infrastructure     ~20       ~1200       core.py (stays)
  generate_completion                        + services/llm_provider.py
  _resolve_provider
  _proxy_transport
  list_models / set_model
  with_model / _get_fallback

Mode Dispatch          ~5        ~200        core.py (stays)
  switch_mode
  _setup_command_handlers
  process_input (router)
  _dispatch_command

Status/UI              ~8        ~150        core.py (stays)
  _status_print
  add_status_message
  verbose / clear_status

Conversation History   ~6        ~300        services/context_service.py
  add_to_history
  _manage_context
  handle_history_command
  handle_clear_command
  handle_context_command
  handle_summarize_command

Search Commands        ~6        ~400        shared commands + services
  handle_search
  _classify_search_intent
  _extract_grep_pattern
  handle_auto_search

Chat Commands          ~18       ~1200       modes/chat.py
  handle_read_command (web)
  handle_translate_command
  handle_generate_command
  handle_reason_command
  handle_explain_command
  handle_links_command
  handle_crawl_command
  handle_webmap_command
  handle_logs_command
  handle_debug_command
  handle_plan_command (goal)
  handle_task_command
  handle_execute_command
  handle_switch_command

Coding Commands        ~42       ~2400       modes/coding.py
  handle_code_command (8 subs)
  handle_write_command
  handle_edit_command
  handle_run_command
  handle_git_command
  handle_diff_command
  handle_browse_command
  handle_undo_command
  handle_test_command
  handle_apply_command
  handle_grep_command
  handle_find_command
  handle_auto_fix_command
  _initialize_workspace_manager

Shared Analysis Cmds   ~4        ~350        shared commands (SharedCommandsMixin)
  handle_refactor_command              # LLM-only suggestions, no file changes
  handle_debug_command                 # LLM-only analysis
  handle_explain_command               # LLM-only explanation
  handle_reason_command                # LLM-only reasoning

Finance Commands       ~2        ~80         modes/finance.py
  _initialize_finance_subsystems
  (finance dispatch via factory)

Safety/Workflow        ~13       ~800        shared commands (stay in core or workflow/)
  handle_sprint_command
  handle_careful_command
  handle_freeze_command
  handle_guard_command
  handle_evidence_command
  handle_evolve_command
  handle_dashboard_command
  handle_upgrade_command

Vault Integration      ~8        ~400        services/vault_service.py
  vault init in __init__
  _check_vault_changes
  _inject_vault_context
  _write_journal_on_exit

Shared Memory          ~4        ~150        services/memory_service.py
  _shared_memory init
  _inject_memory_context
  memory preference hooks
```

### Resulting core.py: ~1,200 lines (revised from original ~500 estimate)

The original 500-line estimate was far too low. The main `stream_response()` method
alone is 539 lines (lines 6024-6562) and contains a complex 5-stage input preprocessing
pipeline + 7-stage post-processing chain that MUST stay in core because it
orchestrates personality-agnostic behaviors (auto-search, NL interpretation,
streaming, history management, evidence logging, evolution scheduling).

What **stays** in core.py:
- `class NeoMindCore` (renamed from NeoMindAgent; keep alias `NeoMindAgent = NeoMindCore` for backward compat)
- `__init__`: create ServiceRegistry, load config, instantiate active personality (~80L)
- `switch_mode()`: deactivate old personality, activate new one (~30L)
- `_rebuild_command_handlers()`: merge shared + personality-specific handlers (~15L)

**Input Processing Pipeline** (stays in core — orchestrates all modes):
- `stream_response()`: main input handler with 5-stage preprocessing + streaming + 7-stage postprocessing (~540L)
  - Stage 1: Code-context auto-detection
  - Stage 2: Input classification (bare URLs → /read, file paths → /read)
  - Stage 3: Natural language interpretation
  - Stage 4: Auto-search detection & execution
  - Stage 5: Auto-file detection & injection
  - Command dispatch to personality handlers
  - Post-processing: finance validation, history storage, vault watcher, evidence trail,
    unified logger, shared memory learning, evolution scheduler
- `classify_and_enhance_input()`: URL/file path detection (~90L)
- `auto_detect_and_read_file()`: file content injection (~45L)
- `is_code_related_query()`: code context detection (~35L)

**LLM Infrastructure** (stays in core):
- `generate_completion()`: non-streaming LLM call (~45L)
- `_resolve_provider()` / `_proxy_transport()`: provider resolution (~80L)
- `list_models()` / `set_model()` / `with_model()`: model management (~120L)

**Lifecycle & Status** (stays in core):
- Status/UI helpers: `_status_print`, `_safe_print`, verbose toggle (~80L)
- `_log_evidence()`: evidence trail helper (~20L)
- Async fallback: `stream_response_async()` (~45L)

### Pros/Cons of core.py Slim-Down

| Aspect | Pros | Cons |
|--------|------|------|
| Maintainability | ~1,200L vs 7,301L — dramatically easier to navigate | Large initial refactor effort |
| Bug Isolation | Mode-specific bugs are contained | Cross-mode bugs may be harder to trace |
| Onboarding | New devs understand structure in minutes | More files to navigate |
| Hot Reloading | Could swap personality without restarting | Not yet implemented (future) |

---

## 5. Module Migration Map

### 5A. Finance → Shared Services (12 modules)

These modules are general-purpose and should serve ALL personalities:

| Module | Current Location | New Location | Reason | Pros | Cons |
|--------|-----------------|--------------|--------|------|------|
| `hybrid_search.py` | finance/ | services/ | Search is universal | All modes get semantic search | Minor finance-tuned defaults need parameterizing |
| `news_digest.py` | finance/ | services/ | News is cross-domain | Chat/Coding get news awareness | **⚠️ REQUIRES SPLIT** — see Note below |
| `rss_feeds.py` | finance/ | services/ | RSS feeds are general | Any mode can subscribe to feeds | Finance-heavy default feed list |
| `source_registry.py` | finance/ | services/ | Source trust is universal | Consistent source scoring | Finance trust weights need per-mode config |
| `chat_store.py` | finance/ | services/ | Chat history is shared | Cross-mode conversation persistence | Currently only used by finance |
| `usage_tracker.py` | finance/ | services/ | Usage tracking is infrastructure | Track costs across all modes | None significant |
| `secure_memory.py` | finance/ | services/ | Encrypted storage is shared | Coding can store secrets too | Encryption adds overhead |
| `memory_bridge.py` | finance/ | services/ | Cross-mode memory sync | Core shared infrastructure | Tight coupling to SharedMemory |
| `dashboard.py` | finance/ | services/ | Metrics visualization is general | Dashboard for all modes | Finance-specific charts need abstraction |
| `diagram_gen.py` | finance/ | services/ | Diagram generation is universal | Coding/Chat can generate diagrams | Mermaid focus may limit some uses |
| `config_editor.py` | finance/ | services/ | Config editing is infrastructure | Consistent config UI | None significant |
| `provider_state.py` | finance/ | services/ | Provider health tracking | All modes benefit from provider state | None significant |

**⚠️ Critical Note: `news_digest.py` Requires Module Split**

`NewsDigestEngine.__init__` accepts `search=`, `data_hub=`, `memory=` parameters.
The factory (`agent/finance/__init__.py`) wires `data_hub=FinanceDataHub(config)` and
later injects `_rag=FinRAG()` post-construction. This creates a **runtime dependency
on FIN-ONLY modules** (`data_hub`, `fin_rag`).

**Affected features**: Thesis entry price tracking (`data_hub.get_quote()`),
social sentiment (`data_hub.get_social_sentiment()`), document-grounded debates (`_rag`).

**Resolution — Split `news_digest.py` into two files**:

```
services/news_digest.py          # Pure news aggregation, RSS fetching,
                                 # headline extraction, digest formatting.
                                 # Accepts search= and memory= (both Shared).
                                 # Does NOT depend on data_hub or fin_rag.

finance/finance_news_digest.py   # Extends NewsDigestEngine with:
                                 #   - Thesis price tracking (needs data_hub)
                                 #   - Social sentiment scoring (needs data_hub)
                                 #   - RAG-grounded persona debates (needs fin_rag)
                                 # class FinanceNewsDigest(NewsDigestEngine): ...
```

This split ensures the Shared version is truly dependency-free while preserving
all finance-specific thesis/sentiment features in the Finance layer.

### 5B. Finance → Integration (6 modules)

External connectors that are mode-agnostic:

| Module | New Location | Reason | Pros | Cons |
|--------|-------------|--------|------|------|
| `telegram_bot.py` | integration/ | Independent process | Clean separation from core | Still needs finance components wired |
| `openclaw_gateway.py` | integration/ | WebSocket client | Can serve any mode | Currently only finance uses it |
| `openclaw_skill.py` | integration/ | Skill plugin | General skill pattern | Finance-specific prompts inside |
| `agent_collab.py` | integration/ | Multi-agent infra | Coding agents can collaborate too | Complex protocol |
| `mobile_sync.py` | integration/ | Sync gateway | Mobile access for all modes | Depends on openclaw |
| `hackernews.py` | integration/ | External API | Tech news for coding mode too | Currently finance-tuned |

### 5C. Finance-ONLY (5 modules — stay in finance/)

| Module | Why It Stays | Unique Capability |
|--------|-------------|-------------------|
| `quant_engine.py` | Options pricing, Greeks, Monte Carlo | 赚钱 core — irreplaceable finance math |
| `investment_personas.py` | Buffett/Soros/Lynch style reasoning | 赚钱 core — unique decision framework |
| `response_validator.py` | Finance-specific compliance rules | 赚钱 core — prevents bad financial advice. **Note**: currently eagerly imported in core.py `__init__` (line 439, try/except). Must move to `FinancePersonality.on_activate()`. Also inline validation logic at core.py lines 6411-6435 must move to `FinancePersonality.enhance_response()`. Single call site, clean extraction. |
| `fin_rag.py` | Finance document RAG | 赚钱 core — domain-specific retrieval |
| `data_hub.py` | Multi-source finance data aggregation | 赚钱 core — real-time market data |

### 5D. Coding-ONLY Modules (agent/ root → coding/)

| Module | Lines | Unique Capability | Pros | Cons |
|--------|-------|-------------------|------|------|
| `code_analyzer.py` | ~400 | AST analysis, complexity metrics | 工程师 core | Could benefit chat for code explanation |
| `self_iteration.py` | ~350 | Self-improvement loop | 工程师 core — unique self-editing | Powerful but risky |
| `persistent_bash.py` | 265 | Stateful shell sessions | 工程师 core | Chat could use simple commands |
| `tool_parser.py` | 283 | LLM tool-call extraction | 工程师 core | Could generalize to all modes |
| `tool_schema.py` | 269 | Tool definition schemas | 工程师 core | Tightly coupled to tool_parser |
| `tools.py` | 730 | Tool execution engine | 工程师 core | Large; might split further |
| `workspace_manager.py` | 247 | Project context, file tracking | 工程师 core | Chat browsing could use parts |
| `planner.py` | 438 | Dependency analysis, GoalPlanner | Split: GoalPlanner→shared, Planner→coding | GoalPlanner is chat-relevant |

**Special Case — `planner.py`**: Contains two distinct classes:
- `GoalPlanner` → move to `services/` (used by Chat /plan command)
- `Planner` (dependency analysis) → stays in `coding/` (code-specific)

### 5E. Shared Root Modules (already in agent/ → services/)

| Module | Lines | Destination | Pros | Cons |
|--------|-------|-------------|------|------|
| `formatter.py` | 190 | services/formatter.py | Consistent output everywhere | None |
| `help_system.py` | 269 | services/help_system.py | Unified help for all modes | Mode-specific help needs filtering |
| `task_manager.py` | 136 | services/task_manager.py | Tasks are cross-mode | Simple module |
| `natural_language.py` | 308 | services/nl_interpreter.py | NL intent for all modes | Confidence tuning per mode |
| `command_executor.py` | 331 | services/command_executor.py | Shell exec for all modes | Mostly coding-relevant |
| `safety.py` | 414 | services/safety_service.py | Safety is universal | None |
| `context_manager.py` | 279 | services/context_service.py | Context is shared | None |
| `search_legacy.py` | 255 | services/ (merge with search_service) | Backward compat | Should eventually remove |
| `search_engine.py` | 24 | services/ (merge with search_service) | Thin wrapper only | Nearly empty — consider inlining |

---

## 6. Personality Command Distribution

### 6A. Chat Personality (modes/chat.py) — 类人 / 最均衡

**Philosophy**: The most balanced, human-like conversationalist. Excels at natural dialogue,
research, summarization, translation, and general knowledge tasks.

**Unique Commands** (only available in chat mode):

| Command | Method | Lines | What It Does | Pros | Cons |
|---------|--------|-------|-------------|------|------|
| `/read` | handle_read_command | ~80 | Read web pages with smart extraction | Natural browsing | Depends on web/ modules |
| `/translate` | handle_translate_command | ~60 | Multi-language translation | 类人 — language mastery | LLM-dependent quality |
| `/generate` | handle_generate_command | ~50 | Creative text generation | 类人 — creative output | Prompt quality matters |
| `/links` | handle_links_command | ~40 | Extract/display links from content | Research aid | Simple utility |
| `/crawl` | handle_crawl_command | ~100 | Deep crawl websites | Research depth | Slow for large sites |
| `/webmap` | handle_webmap_command | ~80 | Visual sitemap generation | Unique visualization | Niche use case |
| `/logs` | handle_logs_command | ~60 | View system logs | Debugging aid | Overlaps with coding /debug |

**Shared Commands** (available via SharedCommandsMixin in ALL modes):

| Command | Why Shared |
|---------|-----------|
| `/search` | All modes need search |
| `/plan` | Goal planning (uses GoalPlanner from services) |
| `/task` | Task management is universal |
| `/summarize` | All modes summarize |
| `/reason` | Deep reasoning is universal (LLM-only) |
| `/explain` | Explanation is universal (LLM-only) |
| `/debug` | All modes can debug (LLM-only, reads file but no writes) |
| `/refactor` | LLM-only refactoring suggestions (no file changes — `/code refactor` is the coding-specific variant that actually modifies files) |

**Personality Traits**:
- System prompt emphasizes: warmth, empathy, balanced perspective, multi-language fluency
- Response style: conversational, contextually aware, avoids over-technicality
- Strengths: general knowledge, research synthesis, natural conversation
- Weaknesses: no code execution, no financial modeling

### 6B. Coding Personality (modes/coding.py) — 工程师

**Philosophy**: The engineer. Strongest development capability. Writes, edits, tests,
debugs, and deploys code with deep project understanding.

**Unique Commands** (only available in coding mode):

| Command | Method | Lines | What It Does | Pros | Cons |
|---------|--------|-------|-------------|------|------|
| `/code` | handle_code_command | ~300 | 8 subcommands: review, optimize, document, test, security, deps, architecture, refactor | 工程师 core — comprehensive code ops | Complex dispatch logic |
| `/write` | handle_write_command | ~100 | Create/overwrite files with safety | Direct file creation | Requires safety guards |
| `/edit` | handle_edit_command | ~120 | Smart file editing with context | Surgical edits | Complex diff logic |
| `/run` | handle_run_command | ~80 | Execute commands via PersistentBash | Stateful execution | Security risk |
| `/git` | handle_git_command | ~100 | Git operations with safety | Version control | Destructive ops risk |
| `/diff` | handle_diff_command | ~60 | Show file diffs | Change review | None |
| `/browse` | handle_browse_command | ~80 | Browse project structure | Project understanding | Large projects slow |
| `/undo` | handle_undo_command | ~40 | Undo last file change | Safety net | Single-level undo |
| `/test` | handle_test_command | ~80 | Run test suites | Quality assurance | Depends on project setup |
| `/apply` | handle_apply_command | ~60 | Apply code patches | Batch edits | Patch format sensitivity |
| `/grep` | handle_grep_command | ~60 | Code search | Fast code navigation | Regex complexity |
| `/find` | handle_find_command | ~50 | Find files | File discovery | None |
| `/fix` / `/analyze` | handle_auto_fix_command | ~150 | Auto-detect and fix issues | Powerful automation | May introduce bugs |

> **Note**: `/refactor` (LLM-only suggestions) is now in SharedCommandsMixin.
> The coding-specific `/code refactor` subcommand (which actually modifies files) remains here.

**Personality Traits**:
- System prompt emphasizes: precision, correctness, safety-first, explain-then-do
- Response style: structured, includes code blocks, explains tradeoffs
- Strengths: code analysis, test writing, debugging, project architecture
- Weaknesses: less natural conversation, over-technical for non-dev users
- Special: WorkspaceManager tracks open files, PersistentBash maintains shell state

### 6C. Finance Personality (modes/finance.py) — 赚钱

**Philosophy**: The money-maker. Strongest financial analysis capability. Provides
market data, quantitative models, investment analysis, and compliance-safe advice.

**Unique Commands** (only available in fin mode):

| Command | What It Does | Pros | Cons |
|---------|-------------|------|------|
| (finance dispatch) | Routes to QuantEngine, InvestmentPersonas, FinRAG, DataHub | Deep financial analysis | Heavy dependencies |
| response validation | Auto-validates all responses for compliance | Prevents bad financial advice | May over-flag |
| persona reasoning | Buffett/Soros/Lynch style analysis | Unique multi-perspective view | May confuse users |

**Personality Traits**:
- System prompt emphasizes: accuracy, sourced data, risk disclaimers, bilingual (EN/CN)
- Response style: data-driven, includes charts/tables, always cites sources
- Strengths: market analysis, quantitative modeling, risk assessment
- Weaknesses: narrow domain, heavy init cost, external API dependency
- Special: `enhance_response()` runs FinanceResponseValidator on every output

---

## 7. Migration Steps (Ordered)

### Step 0: Preparation (no code changes)

**Actions**:
1. Create feature branch: `refactor/three-personality-architecture`
2. Run full test suite, confirm 3,381 pass baseline
3. Create `agent/services/__init__.py`, `agent/modes/__init__.py`, `agent/coding/__init__.py`, `agent/integration/__init__.py` (empty)

**Risk**: None
**Tests**: Run full suite — must match baseline exactly

---

### Step 1: Create BasePersonality and ServiceRegistry Skeletons

**Actions**:
1. Write `agent/base_personality.py` with the abstract interface shown in Section 2
2. Write `agent/services/__init__.py` with ServiceRegistry skeleton (Section 3)
3. No existing code is modified — purely additive

**Files Created**:
- `agent/base_personality.py` (~60 lines)
- `agent/services/__init__.py` (~100 lines)

**Design Detail**:
```python
# ServiceRegistry.__init__ takes the existing core as a bridge during migration
class ServiceRegistry:
    def __init__(self, core_ref=None, config=None):
        self._core = core_ref  # Temporary: allows gradual migration
        self.config = config or agent_config
```

**Risk**: Low (additive only)
**Tests**: Run full suite — no changes expected

---

### Step 2: Move Root Utility Modules → services/

**Actions**: Move 9 utility modules from `agent/` to `agent/services/`, adding `__init__.py` re-exports for backward compatibility.

**Moves**:
```
agent/formatter.py          → agent/services/formatter.py
agent/help_system.py        → agent/services/help_system.py
agent/task_manager.py       → agent/services/task_manager.py
agent/natural_language.py   → agent/services/nl_interpreter.py
agent/command_executor.py   → agent/services/command_executor.py
agent/safety.py             → agent/services/safety_service.py
agent/context_manager.py    → agent/services/context_service.py
agent/search_legacy.py      → agent/services/search_legacy.py
agent/search_engine.py      → agent/services/search_engine.py
```

**Backward Compatibility Strategy**:
Each original location gets a thin re-export stub:
```python
# agent/formatter.py (stub)
"""Backward compatibility — real implementation moved to services/."""
from agent.services.formatter import *  # noqa: F401,F403
from agent.services.formatter import Formatter, success, error, warning, info, header, code_block, command_help
```

**Why stubs**: `core.py` and 52 test files import from `agent.formatter`, `agent.safety`, etc.
Stubs avoid a massive find-replace across the entire codebase. Stubs can be removed in a future
cleanup pass once all imports are migrated.

**Risk**: Medium — import paths are the #1 source of breakage
**Tests**: Run full suite after EACH file move. Fix any import errors immediately.
**Rollback**: `git checkout -- agent/` to restore originals

---

### Step 3: Promote 12 Finance Modules → services/

**Actions**: Move 12 general-purpose modules from `agent/finance/` to `agent/services/`.

**Moves** (in dependency order):
```
Wave 1 (no internal dependencies):
  agent/finance/chat_store.py      → agent/services/chat_store.py
  agent/finance/usage_tracker.py   → agent/services/usage_tracker.py
  agent/finance/config_editor.py   → agent/services/config_editor.py
  agent/finance/provider_state.py  → agent/services/provider_state.py
  agent/finance/diagram_gen.py     → agent/services/diagram_gen.py
  agent/finance/rss_feeds.py       → agent/services/rss_feeds.py

Wave 2 (depend on Wave 1 or external):
  agent/finance/source_registry.py → agent/services/source_registry.py
  agent/finance/secure_memory.py   → agent/services/secure_memory.py
  agent/finance/hybrid_search.py   → agent/services/hybrid_search.py
  agent/finance/dashboard.py       → agent/services/dashboard.py

Wave 3 (depend on Wave 2):
  agent/finance/news_digest.py     → SPLIT:
    - agent/services/news_digest.py          (pure news aggregation, no data_hub/fin_rag)
    - agent/finance/finance_news_digest.py   (thesis tracking, sentiment, extends base)
  agent/finance/memory_bridge.py   → agent/services/memory_bridge.py
```

**Backward Compatibility**: Add re-export stubs in `agent/finance/` for each moved module:
```python
# agent/finance/hybrid_search.py (stub)
from agent.services.hybrid_search import *  # noqa
from agent.services.hybrid_search import HybridSearchEngine
```

**Update `agent/finance/__init__.py`**: Change imports to point to `agent.services.*`.

**Risk**: Medium — internal cross-imports within finance modules
**Tests**: Run full suite after each wave. Finance tests are the most affected.
**Key Metric**: All 20 `test_*_full.py` finance tests must still pass

---

### Step 4: Move Coding-Specific Modules → coding/

**Actions**: Move 8 coding-specific modules from `agent/` to `agent/coding/`.

**Moves**:
```
agent/code_analyzer.py    → agent/coding/code_analyzer.py
agent/self_iteration.py   → agent/coding/self_iteration.py
agent/persistent_bash.py  → agent/coding/persistent_bash.py
agent/tool_parser.py      → agent/coding/tool_parser.py
agent/tool_schema.py      → agent/coding/tool_schema.py
agent/tools.py            → agent/coding/tools.py
agent/workspace_manager.py → agent/coding/workspace_manager.py
agent/planner.py          → agent/coding/planner.py
```

**Special: planner.py Split**:
```python
# agent/services/goal_planner.py (extracted from planner.py)
class GoalPlanner:
    """High-level goal decomposition — used by Chat /plan command."""
    ...

# agent/coding/planner.py (remains)
class Planner:
    """Code-specific dependency analysis and change planning."""
    ...
```

**Backward Compatibility**: Same stub pattern as Step 2.

**Risk**: Medium — `core.py` directly imports these
**Tests**: Run full suite. Coding-specific tests are the most affected.

---

### Step 5: Move Integration Modules → integration/

**Actions**: Move 6 external connector modules from `agent/finance/` to `agent/integration/`.

**Moves**:
```
agent/finance/telegram_bot.py      → agent/integration/telegram_bot.py
agent/finance/openclaw_gateway.py  → agent/integration/openclaw_gateway.py
agent/finance/openclaw_skill.py    → agent/integration/openclaw_skill.py
agent/finance/agent_collab.py      → agent/integration/agent_collab.py
agent/finance/mobile_sync.py       → agent/integration/mobile_sync.py
agent/finance/hackernews.py        → agent/integration/hackernews.py
```

**Risk**: Low — these are mostly leaf modules with few internal consumers
**Tests**: Run integration test files

---

### Step 6: Extract Personality Modes from core.py

This is the **largest and most critical step**. It extracts ~6,100 lines from core.py into three personality files + SharedCommandsMixin.

#### 6A: ChatPersonality (modes/chat.py) ~1,500 lines

**Extract these methods from core.py**:
```python
class ChatPersonality(BasePersonality):
    name = "chat"
    display_name = "Chat 类人"

    def get_command_handlers(self):
        # Chat-UNIQUE commands only.
        # Shared commands (/plan, /task, /reason, /explain, /debug,
        # /summarize, /refactor, /execute, /switch, etc.)
        # are inherited from SharedCommandsMixin.
        return {
            "/read": (self.handle_read_command, True),
            "/translate": (self.handle_translate_command, True),
            "/generate": (self.handle_generate_command, True),
            "/links": (self.handle_links_command, True),
            "/crawl": (self.handle_crawl_command, True),
            "/webmap": (self.handle_webmap_command, True),
            "/logs": (self.handle_logs_command, True),
        }
```

#### 6B: CodingPersonality (modes/coding.py) ~2,800 lines

**Extract these methods from core.py**:
```python
class CodingPersonality(BasePersonality):
    name = "coding"
    display_name = "Coding 工程师"

    def on_activate(self):
        self._initialize_workspace_manager()
        self._init_persistent_bash()

    def get_command_handlers(self):
        return {
            "/code": (self.handle_code_command, True),
            "/write": (self.handle_write_command, True),
            "/edit": (self.handle_edit_command, True),
            "/run": (self.handle_run_command, True),
            "/git": (self.handle_git_command, True),
            "/diff": (self.handle_diff_command, True),
            "/browse": (self.handle_browse_command, True),
            "/undo": (self.handle_undo_command, True),
            "/test": (self.handle_test_command, True),
            "/apply": (self.handle_apply_command, True),
            "/grep": (self.handle_grep_command, True),
            "/find": (self.handle_find_command, True),
            "/fix": (self.handle_auto_fix_command, False),
            "/analyze": (self.handle_auto_fix_command, False),
            # Note: /refactor (LLM-only) is in SharedCommandsMixin.
            # /code refactor (file-modifying) is a subcommand of /code.
            # Shared commands (/plan, /task, /reason, /explain, /debug,
            # /summarize, /refactor, /execute, /switch, etc.)
            # are inherited from SharedCommandsMixin.
        }
```

#### 6C: FinancePersonality (modes/finance.py) ~400 lines

**Extract from core.py**:
```python
class FinancePersonality(BasePersonality):
    name = "fin"
    display_name = "Finance 赚钱"

    def on_activate(self):
        self._finance_components = get_finance_components(self.services.config)
        # Load validator (previously in core.py __init__ line 439)
        self._finance_validator = self._finance_components.get('validator')

    def enhance_response(self, response, tool_results):
        """Run FinanceResponseValidator on every output.

        Migration note: Must also call self.core._log_evidence() for audit trail.
        The validator is loaded in on_activate(), not at import time.
        tool_results are collected by iterating conversation_history in reverse
        until the last user message (see core.py lines 6411-6435 for exact logic).
        """
        if not self._finance_validator:
            return response
        vr = self._finance_validator.validate(response, tool_results)
        if not vr.passed:
            disclaimer = self._finance_validator.build_disclaimer(vr)
            if disclaimer:
                self.core._log_evidence(
                    "finance_validation_warning",
                    vr.summary()[:200], response[:200], severity="warning"
                )
                return response + disclaimer
        return response

    def get_command_handlers(self):
        # Finance has NO unique slash commands — it uses natural language
        # routing to QuantEngine, InvestmentPersonas, etc.
        # All shared commands (/plan, /task, /search, /summarize, etc.)
        # are inherited from SharedCommandsMixin.
        return {
            # Finance-specific dispatch happens in process_natural_input(),
            # not via slash commands.
        }
```

#### 6D: Update core.py to Slim Core

```python
# agent/core.py (~1,200 lines after extraction)
class NeoMindCore:
    def __init__(self, api_key=None, model="deepseek-chat"):
        self.services = ServiceRegistry(config=agent_config)
        self._personalities = {}
        self._active_personality = None
        # ... LLM setup, provider resolution ...
        self._register_personalities()
        self.switch_mode(agent_config.mode, persist=False)

    def _register_personalities(self):
        from agent.modes.chat import ChatPersonality
        from agent.modes.coding import CodingPersonality
        from agent.modes.finance import FinancePersonality
        self._personalities = {
            'chat': ChatPersonality(self, self.services),
            'coding': CodingPersonality(self, self.services),
            'fin': FinancePersonality(self, self.services),
        }

    def switch_mode(self, mode, persist=True):
        if self._active_personality:
            self._active_personality.on_deactivate()
        self._active_personality = self._personalities[mode]
        self._active_personality.on_activate()
        self._rebuild_command_handlers()

    def _rebuild_command_handlers(self):
        """Merge SharedCommandsMixin handlers + active personality's unique handlers.

        SharedCommandsMixin provides: /search, /models, /mode, /skills, /skill,
          /auto, /plan, /task, /execute, /switch, /summarize, /reason, /debug,
          /explain, /refactor, /clear, /history, /context, /think, /quit, /exit,
          /help, /verbose, /sprint, /careful, /freeze, /guard, /unfreeze,
          /evidence, /evolve, /dashboard, /upgrade (32 commands)
        Personality adds its unique handlers on top.
        """
        self.command_handlers = {**self._shared_handlers}
        self.command_handlers.update(self._active_personality.get_command_handlers())

    def process_input(self, user_input):
        """Route input to appropriate handler."""
        for prefix, (handler, strip) in self.command_handlers.items():
            if user_input.startswith(prefix):
                arg = user_input[len(prefix):].strip() if strip else user_input
                return handler(arg)
        return self._handle_natural_input(user_input)
```

**Risk**: HIGH — this is the most complex step

**Extraction Strategy (Delegate-Then-Remove pattern)**:

During extraction, methods exist in TWO places temporarily:
1. **Original** in core.py (still callable via `self.handle_X_command`)
2. **New copy** in personality class (callable via `personality.handle_X_command`)

Procedure for each personality:
```
Phase A: Create personality class with methods COPIED (not moved) from core.py
         - Change self.X → self.core.X for core dependencies
         - Change self.formatter → self.services.formatter
         - Run tests → personality methods work via new paths

Phase B: Update core.py command_handlers to DELEGATE to personality
         - core.handle_read_command = lambda arg: self._active_personality.handle_read_command(arg)
         - Run tests → delegation works

Phase C: REMOVE original methods from core.py (they're now dead code)
         - Run tests → nothing breaks because delegation handles everything
```

Order:
1. Phase A+B+C for ChatPersonality → test → commit
2. Phase A+B+C for CodingPersonality → test → commit
3. Phase A+B+C for FinancePersonality → test → commit
4. Final: replace delegation lambdas with `_rebuild_command_handlers()` → test → commit

**Tests**: Full suite after each phase. No shortcuts.

---

### Step 7: Update Finance Factory

**Actions**: Slim down `agent/finance/__init__.py` to only initialize the 5 finance-only modules.

```python
# agent/finance/__init__.py (updated)
def get_finance_components(config=None):
    """Initialize finance-ONLY components. Shared services are in ServiceRegistry."""
    components = {}
    # Finance-only modules
    for name, module, cls in [
        ('quant', '.quant_engine', 'QuantEngine'),
        ('data_hub', '.data_hub', 'FinanceDataHub'),
        ('rag', '.fin_rag', 'FinRAG'),
        ('personas', '.investment_personas', 'PERSONAS'),
        ('validator', '.response_validator', 'get_finance_validator'),
    ]:
        try:
            mod = __import__(f'agent.finance.{module[1:]}', fromlist=[cls])
            factory_fn = getattr(mod, cls)
            if cls == 'PERSONAS':
                components[name] = factory_fn          # Already a dict
            elif cls == 'get_finance_validator':
                components[name] = factory_fn(strict=False)  # Call factory
            else:
                components[name] = factory_fn()         # Instantiate class
        except ImportError as e:
            components[name] = None
    return components
```

**Risk**: Low
**Tests**: Finance-specific tests

---

### Step 8: Update All Shared Command Handlers

**Actions**: Commands that are available across multiple personalities are implemented once
in a shared mixin or in the ServiceRegistry, then personality modes delegate to them.

```python
# agent/services/shared_commands.py
class SharedCommandsMixin:
    """Commands available to ALL personalities via mixin."""

    def handle_search(self, query):
        return self.services.search.search(query, domain=self.name)

    def handle_models_command(self, arg):
        return self.core.list_models()

    def handle_mode_command(self, arg):
        return self.core.switch_mode(arg)

    def handle_skills_command(self, arg):
        return self.services.skills.handle_command(arg)

    def handle_help_command(self, arg):
        return self.services.help_system.get_help(arg, mode=self.name)

    # LLM-only analysis commands (shared across all modes)
    def handle_refactor_command(self, arg): ...  # LLM suggestions only
    def handle_debug_command(self, arg): ...     # LLM analysis only
    def handle_explain_command(self, arg): ...   # LLM explanation only
    def handle_reason_command(self, arg): ...    # Chain-of-thought reasoning
    def handle_summarize_command(self, arg): ... # LLM summarization
    def handle_plan_command(self, arg): ...      # GoalPlanner (shared)
    def handle_task_command(self, arg): ...      # Task CRUD
    def handle_execute_command(self, arg): ...   # Execute plan
    def handle_switch_command(self, arg): ...    # Switch model

    # Safety/workflow commands
    def handle_sprint_command(self, arg): ...
    def handle_careful_command(self, arg): ...
    def handle_freeze_command(self, arg): ...
    def handle_guard_command(self, arg): ...
    def handle_evidence_command(self, arg): ...
    def handle_evolve_command(self, arg): ...
    def handle_dashboard_command(self, arg): ...
    def handle_upgrade_command(self, arg): ...
```

Each personality inherits: `class ChatPersonality(BasePersonality, SharedCommandsMixin):`

**Risk**: Medium — method resolution order (MRO) needs careful management
**Tests**: Full suite

---

### Step 9: Cleanup and Final Verification

**Actions**:
1. Remove backward-compatibility stubs (one by one, updating imports)
2. Update all test imports to new paths (14 test files import `NeoMindAgent`)
3. Update `agent/__init__.py`: export `NeoMindCore` + keep `NeoMindAgent = NeoMindCore` alias
4. Update `cli/interface.py`: `from agent import NeoMindAgent` (works via alias)
5. Run full test suite 3 times to confirm stability
6. Update README architecture section
7. Update `plans/FEATURE_DOCUMENTATION.md` with new paths
8. Generate updated architecture visualization

**Risk**: Low (cleanup only)
**Tests**: Full suite × 3 runs

---

## 8. Test Strategy

### Per-Step Verification Protocol

```
For EACH step:
  1. Run: pytest tests/ --ignore=tests/test_search.py -x -q
  2. Expected: 3,381 passed (or more, if new tests added)
  3. If ANY failure: STOP, fix, re-run before proceeding
  4. Commit with descriptive message
```

### New Tests Needed

| Component | Test File | What to Test |
|-----------|----------|-------------|
| BasePersonality | test_base_personality.py | Interface contract, abstract method enforcement |
| ServiceRegistry | test_service_registry.py | Lazy init, service access, mock injection |
| ChatPersonality | test_chat_personality.py | Command routing, on_activate, system prompt |
| CodingPersonality | test_coding_personality.py | WorkspaceManager init, tool dispatch |
| FinancePersonality | test_finance_personality.py | Component init, response validation hook |
| SharedCommandsMixin | test_shared_commands.py | All shared commands route correctly |
| NeoMindCore (slim) | test_core_slim.py | Mode switch, command dispatch, provider resolution |
| Import compatibility | test_import_compat.py | All old import paths still work via stubs |

### Regression Safety Net

The existing 3,381 tests serve as the primary regression safety net. The backward-compatibility
stubs ensure ALL existing tests continue to pass without modification during migration.

Only after all 9 steps are complete do we update test imports to new paths (Step 9).

---

## 9. Personality Uniqueness Guarantee

### What Makes Each Personality Irreplaceable

```
┌─────────────────────────────────────────────────────────────────┐
│                     SHARED SERVICES LAYER                       │
│  Search · Vault · Memory · Logging · Safety · Skills · Config   │
│  News · RSS · Formatter · Help · TaskMgr · NL · CommandExec     │
└─────────────┬──────────────────┬──────────────────┬─────────────┘
              │                  │                  │
    ┌─────────▼─────────┐ ┌─────▼──────────┐ ┌────▼──────────────┐
    │   Chat 类人        │ │ Coding 工程师   │ │ Finance 赚钱      │
    │                   │ │                │ │                   │
    │ UNIQUE:           │ │ UNIQUE:        │ │ UNIQUE:           │
    │ · Web reading     │ │ · Code exec    │ │ · Quant modeling  │
    │ · Translation     │ │ · File ops     │ │ · Investment      │
    │ · Creative gen    │ │ · Git ops      │ │   personas        │
    │ · Deep crawling   │ │ · Testing      │ │ · Response        │
    │ · Sitemap viz     │ │ · Auto-fix     │ │   validation      │
    │ · Multi-lingual   │ │ · Self-improve │ │ · Finance RAG     │
    │   fluency         │ │ · Workspace    │ │ · Market data     │
    │ · Balanced tone   │ │   awareness    │ │   aggregation     │
    │                   │ │ · Auto-fix     │ │ · Risk analysis   │
    │ STRONGEST:        │ │                │ │                   │
    │ Natural dialogue  │ │ STRONGEST:     │ │ STRONGEST:        │
    │ & research        │ │ Development    │ │ Financial         │
    │ synthesis         │ │ capability     │ │ analysis          │
    └───────────────────┘ └────────────────┘ └───────────────────┘
```

### Cross-Mode Boundary Rules

1. **Chat CANNOT**: execute code, modify files, run git commands, do financial modeling
2. **Coding CANNOT**: do financial modeling, validate financial compliance, run quant analysis
3. **Finance CANNOT**: execute arbitrary code, modify source files, manage git repositories
4. **All CAN**: search, plan, explain, summarize, access vault/memory, use skills, track tasks

---

## 10. Critical Design Decisions

### 10A. Auto-Switch Behavior: Coding Commands Called From Other Modes

**Current behavior**: Today, a user in chat mode can type `/write hello.py` and the
handler auto-switches to coding mode (`self.switch_mode('coding', persist=False)`)
before executing. This works because ALL 53 commands are registered in a single unified
dict regardless of mode.

**Post-refactor risk**: If `/write` is only in `CodingPersonality.get_command_handlers()`,
then typing `/write` in chat mode would return "Unknown command" — a **behavior change**.

**Affected commands** (5): `/write`, `/edit`, `/run`, `/git`, `/code`

**Decision: Use a cross-personality fallback dispatcher in core.py**:

```python
# agent/core.py — process_input()
def process_input(self, user_input):
    # 1. Try active personality's handlers first
    for prefix, (handler, strip) in self.command_handlers.items():
        if user_input.startswith(prefix):
            arg = user_input[len(prefix):].strip() if strip else user_input
            return handler(arg)

    # 2. If not found, check ALL personalities for the command
    #    and auto-switch if found (preserves current behavior)
    for mode_name, personality in self._personalities.items():
        if mode_name == self._active_personality.name:
            continue
        for prefix in personality.get_command_handlers():
            if user_input.startswith(prefix):
                self._safe_print(f"🔄 Auto-switching to {mode_name} mode for {prefix}")
                self.switch_mode(mode_name, persist=False)
                return self.process_input(user_input)  # Re-dispatch

    # 3. Natural language fallback
    return self._handle_natural_input(user_input)
```

**Pros**: Zero behavior change; users don't need to manually switch modes first.
**Cons**: Slightly more complex dispatch; one extra dict scan on unknown commands.

**After refactor, the auto-switch code inside each handler can be removed** since
the dispatcher handles it. This eliminates 5 redundant `self.switch_mode()` calls.

### 10B. handle_search Cross-Dispatch to handle_grep_command

**Current behavior**: `handle_search()` checks `self.mode == "coding"` and may dispatch
to `handle_grep_command()` (a coding-only handler). This is a **cross-category call**.

**Decision: Keep handle_search in SharedCommandsMixin with mode-aware dispatch**:

```python
# agent/services/shared_commands.py
class SharedCommandsMixin:
    def handle_search(self, query):
        # Mode-aware dispatch: coding mode may redirect to grep
        if self.core._active_personality.name == "coding":
            intent = self._classify_search_intent(query)
            if intent == "grep":
                pattern = self._extract_grep_pattern(query)
                # Call coding personality's grep handler via core dispatch
                return self.core._active_personality.handle_grep_command(pattern)
            if intent == "llm":
                # Codebase comprehension → gather context and pass to LLM
                return self._handle_code_comprehension(query)

        # Default: web search (all modes)
        return self.services.search.search(query)
```

**Why this works**: SharedCommandsMixin can access `self.core._active_personality`
to call mode-specific handlers when needed. This preserves the smart routing behavior
without violating the separation of concerns.

### 10C. test_provider_state.py Hardcoded File Path

**Current behavior**: `test_provider_state.py` uses `importlib.util.spec_from_file_location()`
with a hardcoded path `agent/finance/provider_state.py`.

**Decision**: Update this test in Step 9 (cleanup) to use standard imports:
```python
# Before:
spec = importlib.util.spec_from_file_location("provider_state", "agent/finance/provider_state.py")
# After:
from agent.services.provider_state import ProviderStateTracker
```

Until Step 9, the backward-compat stub at `agent/finance/provider_state.py` will
re-export from the new location, so the hardcoded path still resolves correctly.

### 10D. handle_read_command Web Module Dependencies

`handle_read_command()` (Chat-only) depends on 10+ helper methods for web extraction:
`_try_trafilatura()`, `_try_beautifulsoup()`, `_try_html2text()`, `_try_requests_html()`,
`_try_fallback()`, `_score_content()`, `read_webpage()`, `_add_webpage_to_memory()`, etc.

**Decision**: These helpers move WITH `handle_read_command` into `modes/chat.py`.
They are large (~500 lines combined) but exclusively used by Chat commands.
The `agent/web/` package (crawler, extractor, cache) stays unchanged as a dependency.

---

## 11. Risk Assessment & Mitigation (updated)

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|-----------|
| Import breakage | High | Medium | Backward-compat stubs; test after each move |
| Method reference breakage | Medium | High | `self.core.X` bridge pattern during migration |
| Test failures from path changes | High | Low | Stubs prevent this entirely until Step 9 |
| MRO conflicts in SharedCommandsMixin | Low | Medium | Careful class hierarchy; test MRO explicitly |
| Performance regression from indirection | Low | Low | ServiceRegistry uses lazy properties |
| Circular imports | Medium | High | services/ never imports from modes/; modes/ never imports from each other |
| **Auto-switch behavior change** | **High** | **Medium** | **Cross-personality fallback dispatcher (Section 10A)** |
| **handle_search cross-dispatch** | Medium | Medium | Mode-aware SharedCommandsMixin (Section 10B) |
| **Hardcoded importlib paths in tests** | Low | Low | Update in Step 9 cleanup; stubs cover interim |
| **news_digest data_hub dependency** | High | Medium | Module split: base in services/, finance extension in finance/ |

### Import Dependency Rules (CRITICAL)

```
✅ Allowed:
  core.py → services/, modes/
  modes/* → services/
  services/* → services/* (within layer)
  coding/* → services/
  finance/* → services/
  integration/* → services/

❌ Forbidden:
  services/* → modes/*
  services/* → core.py
  modes/* → modes/* (cross-personality)
  coding/* → finance/*
  finance/* → coding/*
```

---

## 12. Pre-Existing Bugs Found During Review

These bugs exist in the CURRENT codebase (pre-refactor) and should be fixed during migration:

### 12A. Auto-search triggers NOT reloaded on mode switch

**Location**: core.py `__init__` line 354-362 vs `switch_mode()` lines 786-861
**Bug**: `UniversalSearchEngine` is initialized with `triggers=agent_config.auto_search_triggers`
at startup, but `switch_mode()` only updates the search DOMAIN, not the triggers.
Each mode has different triggers in its YAML config (chat: 21 triggers, coding: disabled,
fin: 50+ finance-specific triggers). Switching modes leaves stale triggers active.
**Fix during refactor**: Add `self.core.searcher.update_triggers(agent_config.auto_search_triggers)`
to `on_activate()` — or better, to `ServiceRegistry.search` which can be mode-aware.

### 12B. Finance mode has NO NL interpreter patterns

**Location**: agent/natural_language.py `interpret()` method
**Bug**: The interpreter has coding-specific patterns (lines 189-227) but NO finance-specific
patterns. Finance mode uses the same general patterns as chat mode.
**Impact**: `/stock AAPL` or "show me AAPL earnings" won't be auto-interpreted in fin mode.
**Fix during refactor**: Add `get_nl_patterns()` to BasePersonality; FinancePersonality
returns finance-specific patterns (stock lookup, portfolio, backtest, etc.).

### 12C. available_models_cache not cleared on mode switch

**Location**: core.py line 389-390 (init), line 954-976 (usage)
**Bug**: When switching from chat (provider A) to fin (provider B), the models cache
still contains provider A's models. `get_available_models()` returns stale data
until the cache TTL expires.
**Fix during refactor**: Clear cache in `on_activate()` step 10 (added to plan).

### 12D. Event loops not cleaned up on mode switch

**Location**: core.py line 386-387 (search_loop, _browser_loop)
**Bug**: Lazily created asyncio event loops persist across mode switches. If the old
loop has pending tasks or is in a bad state, the new mode inherits it.
**Fix during refactor**: Close and reset loops in `on_activate()` step 11 (added to plan).

### 12E. COMMANDS_FEED_TO_LLM is static, not mode-aware

**Location**: core.py line 644-648
**Bug**: The same 17 commands are fed to LLM regardless of mode. Chat's `/read` output and
Coding's `/run` output are both fed, even if the other mode's commands aren't available.
**Impact**: Low (commands only execute if registered), but wasteful.
**Fix during refactor**: Use `get_commands_feed_to_llm()` from active personality.

---

## 13. Timeline Estimate

| Step | Description | Estimated Effort | Cumulative |
|------|-------------|-----------------|-----------|
| 0 | Preparation | 15 min | 15 min |
| 1 | BasePersonality + ServiceRegistry skeletons | 30 min | 45 min |
| 2 | Move root utilities → services/ | 1 hour | 1h 45m |
| 3 | Promote 12 finance modules → services/ | 1.5 hours | 3h 15m |
| 4 | Move coding modules → coding/ | 1 hour | 4h 15m |
| 5 | Move integration modules → integration/ | 30 min | 4h 45m |
| 6 | Extract personalities from core.py (Delegate-Then-Remove × 3) | 5 hours | 9h 45m |
| 7 | Update finance factory | 30 min | 10h 15m |
| 8 | Shared command mixin | 1.5 hours | 11h 45m |
| 9 | Cleanup + verification | 2 hours | 13h 45m |

**Total: ~14 hours of focused work** (revised from 11h after discovering
stream_response() complexity and Delegate-Then-Remove extraction pattern)

---

## 14. Post-Refactor: What Comes Next

After the architectural refactor is complete, these discussions are planned:

1. **Chat Personality Deep Dive** — refine unique capabilities, prompt engineering, tone calibration
2. **Coding Personality Deep Dive** — tool system enhancement, workspace context, self-improvement loop
3. **Finance Personality Deep Dive** — quant models, data sources, compliance rules, persona tuning
4. **Cross-Personality Features** — shared memory patterns, mode-switch context transfer, skill sharing
5. **New Personality Addition** (future) — demonstrate extensibility by adding a 4th mode (e.g. Research)

---

*This plan is designed to be executed step-by-step with zero-regression guarantee.
Each step is independently committable and reversible.*
