# Comprehensive Unit Tests for NeoMind Integration Hooks

## Overview

This test suite provides comprehensive coverage for the NeoMind evolution integration hooks system (`agent/evolution/integration_hooks.py` and `agent/evolution/self_restart.py`).

**File:** `test_integration_hooks.py`  
**Total Tests:** 67  
**Status:** All passing  
**Test Framework:** Python unittest  

## Running the Tests

```bash
cd /sessions/wonderful-relaxed-euler/mnt/NeoMind_agent
python -m unittest tests.test_integration_hooks -v
```

## Test Organization

### 1. Module Imports (2 tests)
Verifies that `integration_hooks` module and all its functions can be imported without errors.

### 2. Lazy Loading (7 tests)
Tests the lazy initialization and caching behavior of all module getters:
- `_get_degradation()`
- `_get_distillation()`
- `_get_knowledge_graph()`
- `_get_drift_detector()`
- `_get_agent_spec()`
- `_get_debate()`
- `_get_cost_optimizer()`

Each getter is verified to:
- Load the module on first call
- Return cached instance on subsequent calls
- Gracefully handle import failures

### 3. Pre-LLM Call Hook (8 tests)
Tests the `pre_llm_call()` hook which processes requests before sending to LLM:
- Returns correct structure with all expected keys
- Detects degradation tier and returns fallback responses
- Injects distillation exemplars for appropriate task types
- Adjusts output token limits per mode
- Handles exceptions gracefully

### 4. Post-Response Hook (7 tests)
Tests the `post_response()` hook which processes LLM responses:
- Records drift metrics (latency, tokens, success rate)
- Auto-degrades on failure, recovers on success
- Stores good responses as exemplars
- Records distillation attempt results
- Handles exceptions without blocking

### 5. Periodic Tasks Hook (7 tests)
Tests the `periodic_tasks()` hook called every ~50 turns:
- Performs full drift detection across all metrics
- Discovers knowledge graph clusters
- Cleans up old distillation exemplars
- Reports degradation tier
- Generates alerts for significant drift

### 6. Self-Edit Gate Hook (6 tests)
Tests the `self_edit_gate()` safety gate for code modifications:
- Approves legitimate edits
- Blocks edits to safety-critical files
- Uses AgentSpec rules for validation
- Uses debate consensus for final decision
- Detects safety files and applies higher scrutiny

### 7. Helper Functions (11 tests)
Tests utility functions used by hooks:

**`_infer_task_type()` (6 tests):**
- Detects financial analysis, sentiment analysis, market briefing
- Detects code review tasks
- Returns None for tasks too varied for distillation
- Handles different modes (fin, coding, chat)

**`_estimate_quality()` (5 tests):**
- Computes baseline quality scores
- Applies length bonuses
- Applies structure bonuses (headers, lists)
- Mode-specific signals (financial numbers, code blocks)

### 8. Graceful Degradation (3 tests)
Verifies that all hooks work correctly even when evolution modules fail to import:
- `pre_llm_call()` works without any modules
- `post_response()` works without any modules
- `periodic_tasks()` works without any modules

### 9. Self-Restart Functions (13 tests)
Tests the `self_restart.py` module:

**Supervisor Detection:**
- `is_supervisor_managed()` detects presence of supervisor socket
- Returns False when not under supervisord

**File Type Detection:**
- `needs_full_restart()` identifies files requiring full restart:
  - telegram_bot.py, __init__.py files
  - core.py, main.py, agent_config.py
  - .yaml and .yml config files
- Returns False for evolution/* modules (can use hot-reload)

**Restart Intent Operations:**
- `request_restart()` writes intent file and schedules restart
- `check_restart_intent()` reads and cleans up intent file
- Handles missing/corrupt JSON gracefully

**Restart History:**
- `get_restart_history()` reads entries from JSONL log
- Respects limit parameter
- Returns empty list when log missing

### 10. Integration Tests (2 tests)
Tests realistic workflows:
- Complete hook sequence: `pre_llm_call()` → LLM → `post_response()`
- Periodic maintenance task execution

## Mock Objects

The test suite uses comprehensive mock objects to isolate code under test:

- **MockDegradationManager**: Simulates degradation tier tracking
- **MockDistillationEngine**: Simulates exemplar storage and retrieval
- **MockKnowledgeGraph**: Simulates KG cluster discovery
- **MockDriftDetector**: Simulates metric recording and drift detection
- **MockAgentSpec**: Simulates safety rule checking
- **MockDebateConsensus**: Simulates multi-viewpoint voting
- **MockCostOptimizer**: Simulates per-mode output limit setting

## Key Features

### Comprehensive Coverage
- All public functions tested
- All error paths tested
- Integration scenarios tested
- Edge cases tested (empty logs, corrupt JSON, missing files)

### Isolation
- No external dependencies required
- No database required
- No network calls
- All mocks contained in test file

### Clarity
- Descriptive test names
- Clear docstrings
- Well-organized test classes
- Logical test ordering

### Maintainability
- setUp() methods reset state
- Mock objects are simple and clear
- Tests are independent
- Easy to add new tests

## Test Data

Tests use realistic data that mirrors actual usage:
- Financial prompts with earnings, revenue, EPS keywords
- Code review tasks
- Various response lengths and structures
- Actual degradation tier values ("live", "static", "degraded")
- Real task type names (financial_analysis, sentiment_analysis, etc.)

## Assertions

Tests verify:
- Correct return types (dict, bool, tuple, list)
- Correct structure of returned data
- Correct behavior under normal conditions
- Correct behavior under error conditions
- Correct caching behavior
- Correct event recording

## Running Individual Tests

```bash
# Run single test class
python -m unittest tests.test_integration_hooks.TestPreLLMCall -v

# Run single test
python -m unittest tests.test_integration_hooks.TestPreLLMCall.test_pre_llm_call_basic_structure -v

# Run with higher verbosity
python -m unittest tests.test_integration_hooks -vv
```

## Notes

- Tests use `unittest.mock` extensively for isolation
- No pytest required (pure unittest)
- All tests are self-contained and can run in any order
- No external files are modified during tests
- Tests clean up temporary files (uses tempfile context managers)
