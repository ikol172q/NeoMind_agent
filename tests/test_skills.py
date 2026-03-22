"""
Tests for the NeoMind Skill System.

Covers:
  1. SKILL.md parsing (frontmatter + body)
  2. Skill registry (load, get, list)
  3. Per-mode skill filtering
  4. Shared vs mode-specific skills
  5. Error handling (missing files, bad YAML)

Run: pytest tests/test_skills.py -v
"""

import os
import sys
import pytest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestSkillLoader:

    @pytest.fixture(autouse=True)
    def setup(self):
        from agent.skills.loader import SkillLoader
        self.loader = SkillLoader()
        self.loader.load_all()

    def test_loads_all_skills(self):
        assert self.loader.count >= 10

    def test_shared_skills_exist(self):
        for name in ["browse", "careful", "investigate"]:
            skill = self.loader.get(name)
            assert skill is not None, f"Shared skill {name} not found"
            assert skill.category == "shared"

    def test_chat_skills_exist(self):
        skill = self.loader.get("office-hours")
        assert skill is not None
        assert "chat" in skill.modes
        assert skill.category == "chat"

    def test_coding_skills_exist(self):
        for name in ["eng-review", "qa", "ship"]:
            skill = self.loader.get(name)
            assert skill is not None, f"Coding skill {name} not found"
            assert "coding" in skill.modes

    def test_fin_skills_exist(self):
        for name in ["trade-review", "finance-briefing", "qa-trading"]:
            skill = self.loader.get(name)
            assert skill is not None, f"Fin skill {name} not found"
            assert "fin" in skill.modes

    def test_shared_available_in_all_modes(self):
        """Shared skills should be available in chat, coding, and fin."""
        for mode in ["chat", "coding", "fin"]:
            skills = self.loader.get_skills_for_mode(mode)
            names = [s.name for s in skills]
            assert "browse" in names, f"browse not in {mode}"
            assert "careful" in names, f"careful not in {mode}"
            assert "investigate" in names, f"investigate not in {mode}"

    def test_mode_specific_not_leaked(self):
        """Mode-specific skills should NOT appear in other modes."""
        chat_names = [s.name for s in self.loader.get_skills_for_mode("chat")]
        coding_names = [s.name for s in self.loader.get_skills_for_mode("coding")]
        fin_names = [s.name for s in self.loader.get_skills_for_mode("fin")]

        # office-hours is chat only
        assert "office-hours" in chat_names
        assert "office-hours" not in coding_names
        assert "office-hours" not in fin_names

        # eng-review is coding only
        assert "eng-review" in coding_names
        assert "eng-review" not in chat_names
        assert "eng-review" not in fin_names

        # trade-review is fin only
        assert "trade-review" in fin_names
        assert "trade-review" not in chat_names
        assert "trade-review" not in coding_names

    def test_skill_has_body(self):
        """Every skill should have non-empty prompt body."""
        for skill in self.loader._skills.values():
            assert len(skill.body) > 50, f"{skill.name} has empty/short body"

    def test_skill_has_description(self):
        for skill in self.loader._skills.values():
            assert skill.description, f"{skill.name} has no description"

    def test_to_system_prompt(self):
        skill = self.loader.get("careful")
        prompt = skill.to_system_prompt()
        assert "Active Skill: careful" in prompt
        assert "Safety Guard" in prompt or "CAREFUL" in prompt

    def test_format_skill_list(self):
        output = self.loader.format_skill_list()
        assert "SHARED" in output
        assert "/browse" in output
        assert "/careful" in output

    def test_format_skill_list_filtered(self):
        output = self.loader.format_skill_list(mode="fin")
        assert "/trade-review" in output
        assert "/browse" in output  # shared
        assert "/eng-review" not in output  # coding only


class TestSkillParsing:

    def test_parse_with_frontmatter(self, tmp_path):
        from agent.skills.loader import SkillLoader
        skill_dir = tmp_path / "shared" / "test-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: test-skill\n"
            "description: A test skill\n"
            "modes: [chat, fin]\n"
            "version: 2.0.0\n"
            "---\n\n"
            "# Test Skill\n\nThis is the body."
        )

        loader = SkillLoader(skills_dir=str(tmp_path))
        loader.load_all()
        skill = loader.get("test-skill")

        assert skill is not None
        assert skill.name == "test-skill"
        assert skill.description == "A test skill"
        assert skill.modes == ["chat", "fin"]
        assert skill.version == "2.0.0"
        assert "This is the body" in skill.body

    def test_parse_without_frontmatter(self, tmp_path):
        from agent.skills.loader import SkillLoader
        skill_dir = tmp_path / "shared" / "bare-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# Bare Skill\n\nJust a prompt, no YAML.")

        loader = SkillLoader(skills_dir=str(tmp_path))
        loader.load_all()
        skill = loader.get("bare-skill")

        assert skill is not None
        assert skill.name == "bare-skill"
        assert "Just a prompt" in skill.body

    def test_missing_skill_md(self, tmp_path):
        """Directory without SKILL.md should be silently skipped."""
        from agent.skills.loader import SkillLoader
        (tmp_path / "shared" / "empty-dir").mkdir(parents=True)

        loader = SkillLoader(skills_dir=str(tmp_path))
        count = loader.load_all()
        assert count == 0

    def test_get_nonexistent_skill(self):
        from agent.skills.loader import SkillLoader
        loader = SkillLoader()
        loader.load_all()
        assert loader.get("nonexistent-skill-xyz") is None


class TestSkillSingleton:

    def test_singleton_returns_same_instance(self):
        from agent.skills import get_skill_loader
        l1 = get_skill_loader()
        l2 = get_skill_loader()
        assert l1 is l2
        assert l1.count >= 10
