"""Unit tests for PhaseRunner — spec-kit phase execution."""

import tempfile
import shutil
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.coding.speckit.spec_manager import SpecManager, _slugify
from agent.coding.speckit.constitution import ConstitutionManager
from agent.coding.speckit.phase_runner import (
    PhaseRunner,
    PhaseResult,
    _extract_clarification_markers,
    _cross_artifact_check,
    _extract_implementation_steps,
    _is_complete,
)


class TestHelpers:
    def test_extract_clarification_markers(self):
        text = """
        Some text
        [NEEDS CLARIFICATION]: What auth provider should we use?
        More text
        [NEEDS CLARIFICATION]: How many concurrent users?
        """
        markers = _extract_clarification_markers(text)
        assert len(markers) == 2
        assert "auth provider" in markers[0]
        assert "concurrent users" in markers[1]

    def test_extract_clarification_markers_none(self):
        assert _extract_clarification_markers("No markers here") == []

    def test_cross_artifact_check_ok(self):
        spec = "### User Story 1\n### User Story 2"
        plan = "### Step 1\n### Step 2\n### Step 3"
        tasks = "- [ ] T001\n- [ ] T002\n- [x] T003"
        issues = _cross_artifact_check(spec, plan, tasks)
        assert len(issues) == 0

    def test_cross_artifact_check_empty(self):
        issues = _cross_artifact_check("", "", "")
        assert len(issues) >= 3  # No stories, no steps, no tasks

    def test_cross_artifact_check_unresolved_markers(self):
        spec = "### User Story 1\n[NEEDS CLARIFICATION]: something"
        plan = "### Step 1"
        tasks = "- [ ] T001"
        issues = _cross_artifact_check(spec, plan, tasks)
        assert any("CLARIFICATION" in i for i in issues)

    def test_extract_implementation_steps(self):
        plan = """## Implementation Steps
### Step 1: Set up project structure
details...
### Step 2: Implement core logic
details...
### Step 3: Add tests
details...
"""
        steps = _extract_implementation_steps(plan)
        assert len(steps) == 3
        assert steps[0] == "Set up project structure"
        assert steps[1] == "Implement core logic"

    def test_extract_implementation_steps_none(self):
        assert _extract_implementation_steps("No steps here") == []

    def test_extract_implementation_steps_h2_fallback(self):
        """## Step N: headers (LLM frequently produces these)."""
        plan = """
## Step 1: First thing
body
## Step 2: Second thing
body
"""
        steps = _extract_implementation_steps(plan)
        assert steps == ["First thing", "Second thing"]

    def test_extract_implementation_steps_numbered_fallback(self):
        """Numbered bullets under an Implementation Steps header."""
        plan = """
## Implementation Steps

1. Set up project structure
2. Implement core logic
3. Add tests

## Verification Plan
1. Run pytest
"""
        steps = _extract_implementation_steps(plan)
        assert steps == [
            "Set up project structure",
            "Implement core logic",
            "Add tests",
        ]

    def test_is_complete_true(self):
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write("## Actual Content\nNo placeholders here.")
            path = f.name
        try:
            assert _is_complete(Path(path)) is True
        finally:
            Path(path).unlink()

    def test_is_complete_false(self):
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write("[FEATURE_NAME] still here")
            path = f.name
        try:
            assert _is_complete(Path(path)) is False
        finally:
            Path(path).unlink()


class TestPhaseRunner:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.tmpdir = tempfile.mkdtemp()
        self.spec_mgr = SpecManager(self.tmpdir)
        self.runner = PhaseRunner(spec_manager=self.spec_mgr)
        yield
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ── run_constitution ──

    @pytest.mark.asyncio
    async def test_run_constitution(self):
        result = await self.runner.run_constitution("Test Project")
        assert result.success
        assert result.artifact_path is not None
        assert Path(result.artifact_path).exists()

    # ── run_specify ──

    @pytest.mark.asyncio
    async def test_run_specify(self):
        result = await self.runner.run_specify("User Login", "Add OAuth login flow")
        assert result.success
        assert result.artifact_path is not None
        assert result.data["feature_slug"] == "user-login"

    @pytest.mark.asyncio
    async def test_run_specify_no_description(self):
        result = await self.runner.run_specify("User Login", "")
        assert result.success
        spec_path = Path(result.artifact_path)
        assert spec_path.exists()

    # ── run_clarify ──

    @pytest.mark.asyncio
    async def test_run_clarify_no_markers(self):
        await self.runner.run_specify("Test Feature", "")
        slug = _slugify("Test Feature")
        # Default template has [NEEDS CLARIFICATION] markers
        result = await self.runner.run_clarify(slug)
        assert result.success
        # Template has 2 [NEEDS CLARIFICATION] markers by default
        assert result.data["n_markers"] >= 2

    @pytest.mark.asyncio
    async def test_run_clarify_missing_spec(self):
        result = await self.runner.run_clarify("nonexistent")
        assert not result.success

    # ── run_plan ──

    @pytest.mark.asyncio
    async def test_run_plan_no_llm(self):
        await self.runner.run_specify("Test Feature", "")
        slug = _slugify("Test Feature")
        result = await self.runner.run_plan(slug)
        assert result.success
        assert result.artifact_path is not None

    @pytest.mark.asyncio
    async def test_run_plan_missing_spec(self):
        result = await self.runner.run_plan("nonexistent")
        assert not result.success

    # ── run_tasks ──

    @pytest.mark.asyncio
    async def test_run_tasks(self):
        await self.runner.run_specify("Test Feature", "")
        slug = _slugify("Test Feature")
        await self.runner.run_plan(slug)
        result = await self.runner.run_tasks(slug)
        assert result.success
        assert result.artifact_path is not None

    @pytest.mark.asyncio
    async def test_run_tasks_missing_plan(self):
        result = await self.runner.run_tasks("nonexistent")
        assert not result.success

    # ── run_analyze ──

    @pytest.mark.asyncio
    async def test_run_analyze_no_constitution(self):
        await self.runner.run_specify("Test Feature", "")
        slug = _slugify("Test Feature")
        result = await self.runner.run_analyze(slug)
        # Should fail gate because no constitution
        assert not result.success
        assert result.data["gate"] == "FAIL"
        assert any("No constitution" in v for v in result.data["violations"])

    @pytest.mark.asyncio
    async def test_run_analyze_with_constitution(self):
        await self.runner.run_constitution("Test Project")
        await self.runner.run_specify("Test Feature", "")
        slug = _slugify("Test Feature")
        # Fill spec to pass structural checks
        spec_path = self.spec_mgr.specs_dir / slug / "spec.md"
        spec_path.write_text("""# Feature Spec
## User Scenarios
### User Story 1
## Requirements
## Main Contradiction
The key thing.
## Success Criteria
- SC-001: It works
""")
        await self.runner.run_plan(slug)
        # Write a complete plan (template has placeholders that trigger violations)
        plan_path = self.spec_mgr.specs_dir / slug / "plan.md"
        plan_path.write_text("""# Implementation Plan
## Constitution Check
| Principle | Status |
| Library-First | PASS |
| Test-First | PASS |
## Source Graph
[MODIFIED] src/test.py
### Step 1: Set up structure
### Step 2: Implement core logic
## Verification Plan
1. Run tests
""")
        # Also write proper tasks to pass cross-artifact checks
        tasks_path = self.spec_mgr.specs_dir / slug / "tasks.md"
        tasks_path.write_text("""# Tasks
- [ ] T001 Set up structure
- [ ] T002 Implement core logic
""")
        result = await self.runner.run_analyze(slug)
        # Gate should pass with complete artifacts
        assert result.data["gate"] == "PASS"

    # ── run_implement ──

    @pytest.mark.asyncio
    async def test_run_implement_missing_plan(self):
        result = await self.runner.run_implement("nonexistent")
        assert not result.success

    @pytest.mark.asyncio
    async def test_run_implement_no_coordinator(self):
        await self.runner.run_specify("Test Feature", "")
        slug = _slugify("Test Feature")
        await self.runner.run_plan(slug)
        result = await self.runner.run_implement(slug)
        # Without coordinator, should succeed but list tasks for manual execution
        assert result.success
        assert result.data.get("implementation_tasks") is not None

    # ── run_checklist ──

    @pytest.mark.asyncio
    async def test_run_checklist(self):
        await self.runner.run_specify("Test Feature", "")
        slug = _slugify("Test Feature")
        result = await self.runner.run_checklist(slug)
        assert result.success
        assert result.artifact_path is not None

    # ── run_status ──

    @pytest.mark.asyncio
    async def test_run_status_empty(self):
        result = await self.runner.run_status()
        assert result.success
        assert "No feature specs" in result.message or "0 feature spec" in result.message.lower()

    @pytest.mark.asyncio
    async def test_run_status_with_specs(self):
        await self.runner.run_specify("Feature A", "")
        await self.runner.run_specify("Feature B", "")
        result = await self.runner.run_status()
        assert result.success
        assert len(result.data["specs"]) == 2

    @pytest.mark.asyncio
    async def test_run_status_specific(self):
        await self.runner.run_specify("Feature A", "")
        slug = _slugify("Feature A")
        result = await self.runner.run_status(slug)
        assert result.success
        assert "Feature A" in result.message or slug in result.message

    @pytest.mark.asyncio
    async def test_run_status_nonexistent(self):
        result = await self.runner.run_status("nonexistent")
        # _feature_status creates dirs so it can show artifacts; it always succeeds
        # Check that it shows a feature status with the slug
        assert result.success
        assert "nonexistent" in result.message
