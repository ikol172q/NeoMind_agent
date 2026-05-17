"""Unit tests for ConstitutionManager."""

import tempfile
import shutil
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.coding.speckit.spec_manager import SpecManager
from agent.coding.speckit.constitution import ConstitutionManager


class TestConstitutionManager:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.tmpdir = tempfile.mkdtemp()
        self.spec_mgr = SpecManager(self.tmpdir)
        self.const_mgr = ConstitutionManager(self.spec_mgr)
        yield
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_init_creates_constitution(self):
        path = self.const_mgr.init("My Project")
        assert Path(path).exists()
        assert self.const_mgr.is_initialized()

    def test_is_initialized_false(self):
        assert not self.const_mgr.is_initialized()

    def test_load_returns_content(self):
        self.const_mgr.init("My Project")
        content = self.const_mgr.load()
        assert content is not None
        assert "My Project" in content

    def test_load_returns_none_when_missing(self):
        assert self.const_mgr.load() is None

    def test_get_system_prompt_section(self):
        self.const_mgr.init("My Project")
        section = self.const_mgr.get_system_prompt_section()
        assert section is not None
        assert "Project Constitution" in section
        assert "ALL implementation decisions" in section

    def test_get_system_prompt_section_empty(self):
        assert self.const_mgr.get_system_prompt_section() is None

    def test_validate_spec_no_constitution(self):
        violations = self.const_mgr.validate_spec_against_constitution("test")
        assert len(violations) == 1
        assert "No constitution" in violations[0]

    def test_validate_spec_no_spec(self):
        self.const_mgr.init("My Project")
        violations = self.const_mgr.validate_spec_against_constitution("nonexistent")
        assert len(violations) >= 1

    def test_validate_spec_structural(self):
        self.const_mgr.init("My Project")
        self.spec_mgr.create_spec("Test Feature", "")
        slug = "test-feature"
        spec_path = self.spec_mgr.specs_dir / slug / "spec.md"
        # Write a complete spec
        spec_path.write_text("""# Feature Spec
## User Scenarios
## Requirements
## Main Contradiction
## Success Criteria
""")
        violations = self.const_mgr.validate_spec_against_constitution(slug)
        # Should pass structural checks — no NEEDS CLARIFICATION markers
        assert len(violations) == 0

    def test_validate_spec_with_clarification_markers(self):
        self.const_mgr.init("My Project")
        self.spec_mgr.create_spec("Test Feature", "")
        slug = "test-feature"
        spec_path = self.spec_mgr.specs_dir / slug / "spec.md"
        spec_path.write_text("""# Feature Spec
## User Scenarios
## Requirements
## Main Contradiction
## Success Criteria
[NEEDS CLARIFICATION]: Something unclear
""")
        violations = self.const_mgr.validate_spec_against_constitution(slug)
        assert any("[NEEDS CLARIFICATION]" in v for v in violations)

    def test_validate_plan_no_constitution(self):
        violations = self.const_mgr.validate_plan_against_constitution("test")
        assert len(violations) == 1
        assert "No constitution" in violations[0]

    def test_validate_plan_no_plan(self):
        self.const_mgr.init("My Project")
        self.spec_mgr.create_spec("Test Feature", "")
        slug = "test-feature"
        violations = self.const_mgr.validate_plan_against_constitution(slug)
        assert any("not found" in v for v in violations)

    def test_validate_plan_complete(self):
        self.const_mgr.init("My Project")
        self.spec_mgr.create_spec("Test Feature", "")
        slug = "test-feature"
        self.spec_mgr.create_plan(slug)
        plan_path = self.spec_mgr.specs_dir / slug / "plan.md"
        plan_path.write_text("""# Plan
## Constitution Check
## Source Graph
## Verification Plan
""")
        violations = self.const_mgr.validate_plan_against_constitution(slug)
        assert len(violations) == 0
