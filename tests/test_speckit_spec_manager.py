"""Unit tests for SpecManager — .specify/ artifact CRUD."""

import os
import json
import tempfile
import shutil
from pathlib import Path

import pytest

# Ensure NeoMind package is importable
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.coding.speckit.spec_manager import SpecManager, _slugify


class TestSlugify:
    def test_simple(self):
        assert _slugify("Hello World") == "hello-world"

    def test_special_chars(self):
        assert _slugify("Feature: Login & Auth!") == "feature-login-auth"

    def test_chinese(self):
        # Chinese chars are stripped as non-a-z0-9
        result = _slugify("登录功能")
        assert "login" not in result  # No transliteration

    def test_trailing_dashes(self):
        assert _slugify("-hello-") == "hello"


class TestSpecManager:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.tmpdir = tempfile.mkdtemp()
        self.mgr = SpecManager(self.tmpdir)
        yield
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_ensure_dirs(self):
        self.mgr.ensure_dirs()
        assert self.mgr.specify_dir.exists()
        assert self.mgr.memory_dir.exists()
        assert self.mgr.specs_dir.exists()

    def test_init_constitution(self):
        path = self.mgr.init_constitution("Test Project")
        assert path.exists()
        content = path.read_text()
        assert "# Constitution: Test Project" in content
        assert "## I. Identity & Purpose" in content
        assert "## II. Core Principles" in content
        assert "## VII. Governance" in content

    def test_load_constitution_none(self):
        assert self.mgr.load_constitution() is None

    def test_load_constitution(self):
        self.mgr.init_constitution("Test")
        content = self.mgr.load_constitution()
        assert content is not None
        assert "Test" in content

    def test_has_constitution(self):
        assert not self.mgr.has_constitution()
        self.mgr.init_constitution("Test")
        assert self.mgr.has_constitution()

    def test_get_constitution_prompt(self):
        self.mgr.init_constitution("Test Project")
        prompt = self.mgr.get_constitution_prompt()
        assert prompt is not None
        assert "Project Constitution" in prompt
        assert "Core Principles" in prompt or "Quality Gates" in prompt

    def test_get_constitution_prompt_empty(self):
        assert self.mgr.get_constitution_prompt() is None

    def test_create_spec(self):
        path = self.mgr.create_spec("User Login", "Add OAuth login")
        assert path.exists()
        content = path.read_text()
        assert "# Feature Specification: User Login" in content
        assert "## User Scenarios & Testing" in content
        assert "## Main Contradiction" in content

        # Check meta.json was created
        meta_path = path.parent / "meta.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text())
        assert meta["feature_name"] == "User Login"
        assert meta["status"] == "draft"

    def test_load_spec(self):
        self.mgr.create_spec("User Login", "")
        slug = _slugify("User Login")
        content = self.mgr.load_spec(slug)
        assert content is not None
        assert "User Login" in content

    def test_load_spec_missing(self):
        assert self.mgr.load_spec("nonexistent") is None

    def test_update_spec(self):
        self.mgr.create_spec("Test Feature", "")
        slug = _slugify("Test Feature")
        new_content = "# Updated spec content"
        result = self.mgr.update_spec(slug, new_content)
        assert result is True
        assert self.mgr.load_spec(slug) == "# Updated spec content"

    def test_list_specs(self):
        self.mgr.create_spec("Feature A", "")
        self.mgr.create_spec("Feature B", "")
        specs = self.mgr.list_specs()
        assert len(specs) == 2
        slugs = [s["slug"] for s in specs]
        assert "feature-a" in slugs
        assert "feature-b" in slugs

    def test_list_specs_empty(self):
        specs = self.mgr.list_specs()
        assert specs == []

    def test_create_plan(self):
        self.mgr.init_constitution("Test")
        self.mgr.create_spec("Test Feature", "")
        slug = _slugify("Test Feature")
        path = self.mgr.create_plan(slug)
        assert path.exists()
        content = path.read_text()
        assert "Implementation Plan" in content

    def test_load_plan_missing(self):
        assert self.mgr.load_plan("nonexistent") is None

    def test_create_tasks(self):
        self.mgr.create_spec("Test Feature", "")
        slug = _slugify("Test Feature")
        path = self.mgr.create_tasks(slug)
        assert path.exists()
        content = path.read_text()
        assert "Tasks:" in content or "# Tasks" in content

    def test_parse_tasks(self):
        self.mgr.create_spec("Test Feature", "")
        slug = _slugify("Test Feature")
        tasks_path = self.mgr.create_tasks(slug)
        # Write tasks with some checkboxes
        tasks_md = """
# Tasks: Test Feature

## Phase 3: User Story 1 — Login (Priority: P1)

- [ ] T008 [P] [US1] Contract test for login endpoint
- [x] T009 [P] [US1] Unit tests for login logic
- [ ] T010 [US1] Create User model in src/models/user.py
"""
        tasks_path.write_text(tasks_md)
        parsed = self.mgr.parse_tasks(slug)
        assert len(parsed) == 3
        assert parsed[0]["id"] == "T008"
        assert parsed[0]["parallel"] is True
        assert parsed[1]["completed"] is True
        assert parsed[2]["user_story"] == "US1"  # Inline [US1] tag matches

    def test_parse_tasks_empty(self):
        assert self.mgr.parse_tasks("nonexistent") == []

    def test_parse_tasks_tag_order_tolerant(self):
        """Regression: parse_tasks must accept [P] and [USx] in any order."""
        self.mgr.create_spec("Order Test", "")
        slug = _slugify("Order Test")
        tasks_path = self.mgr.create_tasks(slug)
        tasks_path.write_text("""
# Tasks: Order Test

- [ ] T100 [P] [US1] Canonical order
- [ ] T101 [US2] [P] Reversed order
- [ ] T102 [US3] Just story tag
- [ ] T103 No tags at all
""")
        parsed = self.mgr.parse_tasks(slug)
        ids = {t["id"]: t for t in parsed}
        assert len(parsed) == 4
        assert ids["T100"]["parallel"] is True
        assert ids["T100"]["user_story"] == "US1"
        # Reversed order should still extract both
        assert ids["T101"]["parallel"] is True
        assert ids["T101"]["user_story"] == "US2"
        assert ids["T101"]["description"] == "Reversed order"
        # Story-only
        assert ids["T102"]["parallel"] is False
        assert ids["T102"]["user_story"] == "US3"
        assert ids["T102"]["description"] == "Just story tag"
        # No tags
        assert ids["T103"]["parallel"] is False
        assert ids["T103"]["user_story"] == ""
        assert ids["T103"]["description"] == "No tags at all"

    def test_create_plan_version_regex_does_not_match_plan_version(self):
        """Regression: plan_version: in template should NOT be picked up
        as constitution version."""
        # Write a constitution where the YAML has a true `version: 2.5.0`
        # and a later line `plan_version: 1.0`; the plan should reference 2.5.0.
        self.mgr.ensure_dirs()
        const_path = self.mgr.memory_dir / "constitution.md"
        const_path.write_text("""---
version: 2.5.0
plan_version: 99.0
---

# Constitution: Test
""")
        self.mgr.create_spec("Version Probe", "")
        slug = _slugify("Version Probe")
        plan_path = self.mgr.create_plan(slug)
        plan_text = plan_path.read_text()
        assert "constitution_version: 2.5.0" in plan_text
        assert "constitution_version: 99.0" not in plan_text

    def test_get_constitution_prompt_robust_to_renumbered_headers(self):
        """Regression: section extraction should still work after the
        user renumbers headers (e.g. drops roman numerals)."""
        self.mgr.init_constitution("Test")
        const_path = self.mgr.memory_dir / "constitution.md"
        # Rewrite without roman-numeral prefixes
        const_path.write_text("""---
version: 1.0.0
---

# Constitution: Test

## Core Principles

### 1. Foo
Principle text.

## Quality Gates

Gate text.

## Anti-Patterns (NEVER)

Never do X.

## Agent Operating Principles

Operate truthfully.

## Governance

Stuff.
""")
        prompt = self.mgr.get_constitution_prompt()
        assert prompt is not None
        assert "Core Principles" in prompt
        assert "Quality Gates" in prompt
        assert "Anti-Patterns" in prompt
        assert "Agent Operating Principles" in prompt

    def test_write_and_load_research(self):
        self.mgr.create_spec("Test Feature", "")
        slug = _slugify("Test Feature")
        path = self.mgr.write_research(slug, "## Research findings\nKey insights here.")
        assert path.exists()
        loaded = self.mgr.load_research(slug)
        assert loaded == "## Research findings\nKey insights here."

    def test_load_research_missing(self):
        assert self.mgr.load_research("nonexistent") is None

    def test_create_checklist(self):
        self.mgr.create_spec("Test Feature", "")
        slug = _slugify("Test Feature")
        path = self.mgr.create_checklist(slug)
        assert path.exists()
        content = path.read_text()
        assert "Checklist" in content

    def test_get_checklist_stats(self):
        self.mgr.create_spec("Test Feature", "")
        slug = _slugify("Test Feature")
        checklist_path = self.mgr.create_checklist(slug)
        # Overwrite with known checkboxes
        checklist_path.write_text("""
# Checklist
- [x] Item 1
- [x] Item 2
- [ ] Item 3
- [ ] Item 4
""")
        stats = self.mgr.get_checklist_stats(slug)
        assert stats["total"] == 4
        assert stats["completed"] == 2
        assert stats["incomplete"] == 2

    def test_get_checklist_stats_empty(self):
        stats = self.mgr.get_checklist_stats("nonexistent")
        assert stats["total"] == 0

    def test_get_feature_dir(self):
        self.mgr.create_spec("Test Feature", "")
        slug = _slugify("Test Feature")
        d = self.mgr.get_feature_dir(slug)
        assert d.exists()
        assert d.name == slug
