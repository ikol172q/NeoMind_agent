"""LLM-path tests for PhaseRunner — covers the gap where existing tests
all run with llm_fn=None.

A fake llm_fn is injected that dispatches by system-prompt to produce
deterministic markdown. We then assert that the artifacts written to
.specify/ survive ConstitutionManager structural validation and
cross-artifact checks.
"""

from __future__ import annotations

import tempfile
import shutil
from pathlib import Path
from typing import Dict, List

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.coding.speckit.spec_manager import SpecManager, _slugify
from agent.coding.speckit.constitution import ConstitutionManager
from agent.coding.speckit.phase_runner import PhaseRunner


# ── Fake LLM helpers ──────────────────────────────────────────────

# A well-formed spec body that satisfies ConstitutionManager
# structural checks (must contain: User Scenarios, Requirements,
# Success Criteria, Main Contradiction; no [NEEDS CLARIFICATION]).
WELL_FORMED_SPEC = """# Feature Specification: User Login

## User Scenarios & Testing

### User Story 1 — OAuth login (Priority: P1)
As a user I want to log in with Google.

### User Story 2 — Session refresh (Priority: P2)
As a user I want my session to persist across reloads.

## Requirements

- FR-001: System MUST support Google OAuth 2.0.
- FR-002: System MUST refresh access tokens silently.

## Main Contradiction

Convenience (single-click) vs. security (token rotation).

## Success Criteria

- SC-001: 95% of logins succeed within 2s.
- SC-002: Zero token leakage in logs.
"""

# Spec with a missing required section, to verify analyze surfaces it.
SPEC_MISSING_SECTION = """# Feature Specification: Broken

## User Scenarios & Testing

### User Story 1 — Something
As a user I want a thing.

## Requirements

- FR-001: Do the thing.

## Success Criteria

- SC-001: It works.
"""
# (No Main Contradiction → should violate.)

WELL_FORMED_PLAN = """# Implementation Plan: User Login

## Constitution Check

| Principle | Status |
| Library-First | PASS |

## Source Graph

[NEW] src/auth/oauth.py — new OAuth client

## Implementation Steps

### Step 1: Add OAuth client
- File: src/auth/oauth.py
- Change: new module
- Rollback: delete file
- Test: unit test in tests/test_oauth.py

### Step 2: Wire login route
- File: src/routes/login.py
- Change: handler calls oauth.exchange
- Rollback: revert handler
- Test: integration test

## Verification Plan

1. Unit Tests: tests/test_oauth.py
2. Integration: end-to-end login
"""

WELL_FORMED_TASKS = """# Tasks: User Login

## Phase 3: User Story 1 — OAuth login (Priority: P1)

- [ ] T001 [P] [US1] Contract test for OAuth callback
- [ ] T002 [P] [US1] Unit tests for oauth.exchange
- [ ] T003 [US1] Implement oauth.exchange in src/auth/oauth.py

## Phase 4: User Story 2 — Session refresh (Priority: P2)

- [ ] T004 [US2] Add refresh-token storage
- [ ] T005 [US2] Wire silent refresh on 401
"""


class FakeLLM:
    """Dispatch by system-prompt prefix to fixed return values.

    Records every call so tests can assert which prompts were sent.
    """

    def __init__(self, responses: Dict[str, str]):
        # Map: substring-of-system-prompt -> response markdown.
        self.responses = responses
        self.calls: List[tuple] = []

    async def __call__(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        for key, value in self.responses.items():
            if key in system_prompt:
                return value
        return ""  # default: empty


# ── Tests ─────────────────────────────────────────────────────────


class TestPhaseRunnerLLMPath:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.tmpdir = tempfile.mkdtemp()
        self.spec_mgr = SpecManager(self.tmpdir)
        yield
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _runner(self, llm: FakeLLM) -> PhaseRunner:
        return PhaseRunner(spec_manager=self.spec_mgr, llm_fn=llm)

    # ── specify ──

    @pytest.mark.asyncio
    async def test_specify_with_llm_enriches_spec(self):
        llm = FakeLLM({"product engineer": WELL_FORMED_SPEC})
        runner = self._runner(llm)

        result = await runner.run_specify("User Login", "Add OAuth login flow")

        assert result.success
        assert len(llm.calls) == 1
        slug = _slugify("User Login")
        on_disk = self.spec_mgr.load_spec(slug)
        assert on_disk == WELL_FORMED_SPEC  # template was overwritten

    @pytest.mark.asyncio
    async def test_specify_no_description_skips_llm(self):
        """Existing behavior at phase_runner.py:104 — LLM only fires
        when description is non-empty. Locks in current contract."""
        llm = FakeLLM({"product engineer": WELL_FORMED_SPEC})
        runner = self._runner(llm)

        result = await runner.run_specify("User Login", "")

        assert result.success
        assert len(llm.calls) == 0  # no description → no LLM call

    # ── specify + analyze: well-formed LLM output passes structural check ──

    @pytest.mark.asyncio
    async def test_llm_specify_passes_constitution_validation(self):
        """The well-formed LLM spec must survive
        ConstitutionManager.validate_spec_against_constitution.
        Regression guard for spec-template / validator section drift."""
        llm = FakeLLM({"product engineer": WELL_FORMED_SPEC})
        runner = self._runner(llm)

        await runner.run_constitution("Test Project")
        await runner.run_specify("User Login", "Add OAuth login flow")

        const_mgr = ConstitutionManager(self.spec_mgr)
        slug = _slugify("User Login")
        violations = const_mgr.validate_spec_against_constitution(slug)

        assert violations == [], f"Unexpected violations: {violations}"

    # ── specify: malformed LLM output is caught by analyze ──

    @pytest.mark.asyncio
    async def test_llm_specify_missing_section_caught_by_analyze(self):
        """If the LLM omits 'Main Contradiction', /speckit.analyze must
        report a violation. This protects against silent overwrite of
        the template (phase_runner.py:108) with structurally invalid
        content."""
        llm = FakeLLM({
            "product engineer": SPEC_MISSING_SECTION,
            "senior software architect": WELL_FORMED_PLAN,
            "technical project manager": WELL_FORMED_TASKS,
        })
        runner = self._runner(llm)

        await runner.run_constitution("Test Project")
        await runner.run_specify("Broken Feature", "Test description")
        slug = _slugify("Broken Feature")
        await runner.run_plan(slug)
        await runner.run_tasks(slug)

        result = await runner.run_analyze(slug)

        assert not result.success
        assert result.data["gate"] == "FAIL"
        assert any("Main Contradiction" in v for v in result.data["violations"]), \
            f"Expected Main Contradiction violation, got: {result.data['violations']}"

    # ── plan ──

    @pytest.mark.asyncio
    async def test_plan_with_llm_overwrites_template(self):
        llm = FakeLLM({
            "product engineer": WELL_FORMED_SPEC,
            "senior software architect": WELL_FORMED_PLAN,
        })
        runner = self._runner(llm)

        await runner.run_specify("User Login", "Add OAuth login flow")
        slug = _slugify("User Login")
        result = await runner.run_plan(slug)

        assert result.success
        on_disk = self.spec_mgr.load_plan(slug)
        assert on_disk == WELL_FORMED_PLAN

    @pytest.mark.asyncio
    async def test_llm_plan_passes_constitution_validation(self):
        llm = FakeLLM({
            "product engineer": WELL_FORMED_SPEC,
            "senior software architect": WELL_FORMED_PLAN,
        })
        runner = self._runner(llm)

        await runner.run_constitution("Test Project")
        await runner.run_specify("User Login", "Add OAuth login flow")
        slug = _slugify("User Login")
        await runner.run_plan(slug)

        const_mgr = ConstitutionManager(self.spec_mgr)
        violations = const_mgr.validate_plan_against_constitution(slug)

        assert violations == [], f"Unexpected violations: {violations}"

    # ── tasks ──

    @pytest.mark.asyncio
    async def test_tasks_with_llm_overwrites_and_parses(self):
        """End-to-end: LLM-generated tasks.md must round-trip through
        parse_tasks. Protects against parse_tasks regex
        (spec_manager.py:248) drifting away from realistic LLM output."""
        llm = FakeLLM({
            "product engineer": WELL_FORMED_SPEC,
            "senior software architect": WELL_FORMED_PLAN,
            "technical project manager": WELL_FORMED_TASKS,
        })
        runner = self._runner(llm)

        await runner.run_specify("User Login", "Add OAuth login flow")
        slug = _slugify("User Login")
        await runner.run_plan(slug)
        result = await runner.run_tasks(slug)

        assert result.success
        parsed = self.spec_mgr.parse_tasks(slug)
        assert len(parsed) == 5, f"Expected 5 tasks, got {len(parsed)}: {parsed}"
        # First task is parallel + has US tag
        assert parsed[0]["id"] == "T001"
        assert parsed[0]["parallel"] is True
        assert parsed[0]["user_story"] == "US1"

    # ── full happy path: gate PASSes ──

    @pytest.mark.asyncio
    async def test_full_llm_pipeline_passes_analyze_gate(self):
        """constitution → specify → plan → tasks → analyze, all with
        LLM enrichment, gate should PASS."""
        llm = FakeLLM({
            "product engineer": WELL_FORMED_SPEC,
            "senior software architect": WELL_FORMED_PLAN,
            "technical project manager": WELL_FORMED_TASKS,
        })
        runner = self._runner(llm)

        await runner.run_constitution("Test Project")
        await runner.run_specify("User Login", "Add OAuth login flow")
        slug = _slugify("User Login")
        await runner.run_plan(slug)
        await runner.run_tasks(slug)
        result = await runner.run_analyze(slug)

        assert result.data["gate"] == "PASS", \
            f"Gate failed with violations: {result.data['violations']}"
        # All four LLM phases fired
        assert len(llm.calls) == 3  # specify + plan + tasks

    # ── clarify LLM suggestions ──

    @pytest.mark.asyncio
    async def test_clarify_calls_llm_once_per_marker(self):
        """LLM is invoked once per marker in markers[:5]
        (phase_runner.py:421). Asserts on llm.calls, not on the
        suggestions dict — see the dedup test below for why."""
        llm = FakeLLM({"technical analyst": "Use OAuth 2.0 with PKCE."})
        runner = self._runner(llm)

        await runner.run_specify("Test Feature", "")
        slug = _slugify("Test Feature")
        result = await runner.run_clarify(slug)

        assert result.success
        n = result.data["n_markers"]
        assert n >= 2
        # llm.calls counts raw invocations, before any dedup
        assert len(llm.calls) == min(n, 5)

    @pytest.mark.asyncio
    async def test_clarify_marker_text_differentiated(self):
        """Regression guard for the spec-template.md duplicate-marker
        bug. The default template ships with TWO distinct placeholder
        markers; if a future template edit accidentally makes them
        identical again, suggestions dict will collapse to one entry
        because phase_runner.py:420 keys by marker text."""
        llm = FakeLLM({"technical analyst": "Use OAuth 2.0 with PKCE."})
        runner = self._runner(llm)

        await runner.run_specify("Test Feature", "")
        slug = _slugify("Test Feature")
        result = await runner.run_clarify(slug)

        suggestions = result.data["suggestions"]
        # One suggestion per distinct marker (currently 2)
        assert len(suggestions) == result.data["n_markers"], \
            f"Suggestions collapsed: {len(suggestions)} != {result.data['n_markers']}"
        for v in suggestions.values():
            assert "OAuth 2.0 with PKCE" in v

    # ── implement falls back when no coordinator ──

    @pytest.mark.asyncio
    async def test_implement_extracts_steps_from_llm_plan(self):
        """LLM plan has '### Step 1:' / '### Step 2:' headers — the
        _extract_implementation_steps regex (phase_runner.py:561)
        should pick them up, not fall back to the single-task default."""
        llm = FakeLLM({
            "product engineer": WELL_FORMED_SPEC,
            "senior software architect": WELL_FORMED_PLAN,
        })
        runner = self._runner(llm)

        await runner.run_specify("User Login", "Add OAuth login flow")
        slug = _slugify("User Login")
        await runner.run_plan(slug)
        result = await runner.run_implement(slug)

        assert result.success
        impl_tasks = result.data["implementation_tasks"]
        # WELL_FORMED_PLAN has 2 steps; if regex misses, we'd get the
        # single fallback "Implement {slug} per plan.md"
        assert len(impl_tasks) == 2, \
            f"Expected 2 extracted steps, got {len(impl_tasks)}: {impl_tasks}"
        assert "Add OAuth client" in impl_tasks[0]
