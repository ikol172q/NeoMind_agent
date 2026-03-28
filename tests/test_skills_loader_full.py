"""Comprehensive tests for agent/skills/loader.py — SkillLoader."""

import pytest
from pathlib import Path
from agent.skills.loader import Skill, SkillLoader, get_skill_loader


@pytest.fixture
def skills_dir(tmp_path):
    """Create a skills directory with test skills."""
    sd = tmp_path / "skills"
    sd.mkdir()
    return sd


@pytest.fixture
def sample_skill_dir(skills_dir):
    """Create a sample shared skill."""
    shared = skills_dir / "shared" / "test-skill"
    shared.mkdir(parents=True)
    (shared / "SKILL.md").write_text(
        "---\n"
        "name: test-skill\n"
        "description: A test skill\n"
        "modes: [chat, coding]\n"
        "allowed-tools: [Bash, Read]\n"
        "version: 2.0.0\n"
        "---\n\n"
        "# Test Skill\n\n"
        "This is the prompt body.\n",
        encoding="utf-8",
    )
    return skills_dir


@pytest.fixture
def multi_skill_dir(skills_dir):
    """Create multiple skills across categories."""
    # shared skill
    s1 = skills_dir / "shared" / "retro"
    s1.mkdir(parents=True)
    (s1 / "SKILL.md").write_text(
        "---\nname: retro\ndescription: Weekly retro\nmodes: [chat, coding, fin]\nversion: 1.0.0\n---\n# Retro\nBody\n",
        encoding="utf-8",
    )
    # coding-only skill
    s2 = skills_dir / "coding" / "lint"
    s2.mkdir(parents=True)
    (s2 / "SKILL.md").write_text(
        "---\nname: lint\ndescription: Code linter\nversion: 1.0.0\n---\n# Lint\nLint body\n",
        encoding="utf-8",
    )
    # fin-only skill
    s3 = skills_dir / "fin" / "analysis"
    s3.mkdir(parents=True)
    (s3 / "SKILL.md").write_text(
        "---\nname: analysis\ndescription: Financial analysis\nmodes: [fin]\nversion: 1.0.0\n---\n# Analysis\nBody\n",
        encoding="utf-8",
    )
    return skills_dir


# ── Skill Dataclass Tests ────────────────────────────────────────────

class TestSkillDataclass:
    """Tests for the Skill dataclass."""

    def test_default_values(self):
        s = Skill(name="test")
        assert s.name == "test"
        assert s.description == ""
        assert s.body == ""
        assert s.modes == ["chat", "coding", "fin"]
        assert s.allowed_tools == []
        assert s.version == "1.0.0"
        assert s.path == ""
        assert s.category == "shared"

    def test_to_system_prompt(self):
        s = Skill(name="my-skill", description="Does things", body="Prompt here")
        prompt = s.to_system_prompt()
        assert "Active Skill: my-skill" in prompt
        assert "Does things" in prompt
        assert "Prompt here" in prompt

    def test_repr(self):
        s = Skill(name="test", modes=["chat"], body="x" * 100)
        r = repr(s)
        assert "test" in r
        assert "chat" in r
        assert "100" in r


# ── SkillLoader Tests ────────────────────────────────────────────────

class TestSkillLoaderInit:
    """Tests for SkillLoader initialization."""

    def test_default_skills_dir(self):
        loader = SkillLoader()
        assert loader.skills_dir is not None

    def test_custom_skills_dir(self, skills_dir):
        loader = SkillLoader(str(skills_dir))
        assert loader.skills_dir == skills_dir

    def test_not_loaded_initially(self, skills_dir):
        loader = SkillLoader(str(skills_dir))
        assert loader._loaded is False


class TestLoadAll:
    """Tests for load_all()."""

    def test_loads_skills(self, sample_skill_dir):
        loader = SkillLoader(str(sample_skill_dir))
        count = loader.load_all()
        assert count == 1

    def test_loads_multiple_categories(self, multi_skill_dir):
        loader = SkillLoader(str(multi_skill_dir))
        count = loader.load_all()
        assert count == 3

    def test_returns_count(self, multi_skill_dir):
        loader = SkillLoader(str(multi_skill_dir))
        count = loader.load_all()
        assert isinstance(count, int)

    def test_sets_loaded_flag(self, sample_skill_dir):
        loader = SkillLoader(str(sample_skill_dir))
        loader.load_all()
        assert loader._loaded is True

    def test_clears_on_reload(self, sample_skill_dir):
        loader = SkillLoader(str(sample_skill_dir))
        loader.load_all()
        # Load again, should clear and reload
        count = loader.load_all()
        assert count == 1

    def test_empty_directory(self, skills_dir):
        loader = SkillLoader(str(skills_dir))
        count = loader.load_all()
        assert count == 0

    def test_skips_non_directories(self, skills_dir):
        shared = skills_dir / "shared"
        shared.mkdir()
        (shared / "not-a-dir.txt").write_text("not a skill", encoding="utf-8")
        loader = SkillLoader(str(skills_dir))
        count = loader.load_all()
        assert count == 0

    def test_skips_missing_skill_md(self, skills_dir):
        shared = skills_dir / "shared" / "empty-skill"
        shared.mkdir(parents=True)
        # No SKILL.md file
        loader = SkillLoader(str(skills_dir))
        count = loader.load_all()
        assert count == 0


class TestGet:
    """Tests for get()."""

    def test_get_existing(self, sample_skill_dir):
        loader = SkillLoader(str(sample_skill_dir))
        loader.load_all()
        skill = loader.get("test-skill")
        assert skill is not None
        assert skill.name == "test-skill"

    def test_get_nonexistent(self, sample_skill_dir):
        loader = SkillLoader(str(sample_skill_dir))
        loader.load_all()
        assert loader.get("nonexistent") is None

    def test_auto_loads_on_get(self, sample_skill_dir):
        loader = SkillLoader(str(sample_skill_dir))
        # Don't call load_all() — get() should auto-load
        skill = loader.get("test-skill")
        assert skill is not None


class TestGetSkillsForMode:
    """Tests for get_skills_for_mode()."""

    def test_get_chat_skills(self, multi_skill_dir):
        loader = SkillLoader(str(multi_skill_dir))
        loader.load_all()
        chat_skills = loader.get_skills_for_mode("chat")
        names = [s.name for s in chat_skills]
        assert "retro" in names
        assert "analysis" not in names

    def test_get_fin_skills(self, multi_skill_dir):
        loader = SkillLoader(str(multi_skill_dir))
        loader.load_all()
        fin_skills = loader.get_skills_for_mode("fin")
        names = [s.name for s in fin_skills]
        assert "retro" in names
        assert "analysis" in names

    def test_get_coding_skills(self, multi_skill_dir):
        loader = SkillLoader(str(multi_skill_dir))
        loader.load_all()
        coding_skills = loader.get_skills_for_mode("coding")
        names = [s.name for s in coding_skills]
        assert "retro" in names
        assert "lint" in names

    def test_empty_mode(self, sample_skill_dir):
        loader = SkillLoader(str(sample_skill_dir))
        loader.load_all()
        # test-skill only has modes=[chat, coding], not fin
        fin_skills = loader.get_skills_for_mode("fin")
        assert len(fin_skills) == 0


class TestListSkills:
    """Tests for list_skills()."""

    def test_list_all(self, multi_skill_dir):
        loader = SkillLoader(str(multi_skill_dir))
        loader.load_all()
        skills = loader.list_skills()
        assert len(skills) == 3

    def test_list_by_mode(self, multi_skill_dir):
        loader = SkillLoader(str(multi_skill_dir))
        loader.load_all()
        skills = loader.list_skills(mode="fin")
        assert all("fin" in s["modes"] for s in skills)

    def test_list_returns_dicts(self, sample_skill_dir):
        loader = SkillLoader(str(sample_skill_dir))
        loader.load_all()
        skills = loader.list_skills()
        assert len(skills) == 1
        s = skills[0]
        assert "name" in s
        assert "description" in s
        assert "modes" in s
        assert "category" in s
        assert "version" in s

    def test_sorted_by_category_and_name(self, multi_skill_dir):
        loader = SkillLoader(str(multi_skill_dir))
        loader.load_all()
        skills = loader.list_skills()
        categories = [s["category"] for s in skills]
        # coding < fin < shared alphabetically
        assert categories == sorted(categories)


class TestFormatSkillList:
    """Tests for format_skill_list()."""

    def test_format_all(self, multi_skill_dir):
        loader = SkillLoader(str(multi_skill_dir))
        loader.load_all()
        output = loader.format_skill_list()
        assert "/retro" in output
        assert "/lint" in output
        assert "/analysis" in output

    def test_format_by_mode(self, multi_skill_dir):
        loader = SkillLoader(str(multi_skill_dir))
        loader.load_all()
        output = loader.format_skill_list(mode="fin")
        assert "/analysis" in output
        assert "/retro" in output

    def test_empty_skills(self, skills_dir):
        loader = SkillLoader(str(skills_dir))
        loader.load_all()
        output = loader.format_skill_list()
        assert "No skills loaded" in output

    def test_category_icons(self, multi_skill_dir):
        loader = SkillLoader(str(multi_skill_dir))
        loader.load_all()
        output = loader.format_skill_list()
        assert "🔗" in output  # shared
        assert "💻" in output  # coding
        assert "📈" in output  # fin


class TestCount:
    """Tests for count property."""

    def test_count(self, multi_skill_dir):
        loader = SkillLoader(str(multi_skill_dir))
        loader.load_all()
        assert loader.count == 3

    def test_count_auto_loads(self, sample_skill_dir):
        loader = SkillLoader(str(sample_skill_dir))
        assert loader.count == 1


# ── Parsing Tests ─────────────────────────────────────────────────────

class TestParseSkillFile:
    """Tests for _parse_skill_file()."""

    def test_parse_with_frontmatter(self, sample_skill_dir):
        loader = SkillLoader(str(sample_skill_dir))
        skill_file = sample_skill_dir / "shared" / "test-skill" / "SKILL.md"
        skill = loader._parse_skill_file(skill_file, "shared")
        assert skill.name == "test-skill"
        assert skill.description == "A test skill"
        assert skill.modes == ["chat", "coding"]
        assert skill.allowed_tools == ["Bash", "Read"]
        assert skill.version == "2.0.0"
        assert "Test Skill" in skill.body

    def test_parse_without_frontmatter(self, skills_dir):
        d = skills_dir / "shared" / "bare"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text("# Just a title\n\nBody content\n", encoding="utf-8")
        loader = SkillLoader(str(skills_dir))
        skill = loader._parse_skill_file(d / "SKILL.md", "shared")
        assert skill.name == "bare"  # Uses directory name
        assert "Body content" in skill.body

    def test_parse_string_modes(self, skills_dir):
        d = skills_dir / "shared" / "single-mode"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            "---\nname: single\nmodes: chat\n---\nBody\n",
            encoding="utf-8",
        )
        loader = SkillLoader(str(skills_dir))
        skill = loader._parse_skill_file(d / "SKILL.md", "shared")
        assert skill.modes == ["chat"]

    def test_parse_no_modes_shared(self, skills_dir):
        d = skills_dir / "shared" / "all-modes"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            "---\nname: all-modes\n---\nBody\n",
            encoding="utf-8",
        )
        loader = SkillLoader(str(skills_dir))
        skill = loader._parse_skill_file(d / "SKILL.md", "shared")
        assert skill.modes == ["chat", "coding", "fin"]

    def test_parse_no_modes_coding(self, skills_dir):
        d = skills_dir / "coding" / "code-skill"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            "---\nname: code-skill\n---\nBody\n",
            encoding="utf-8",
        )
        loader = SkillLoader(str(skills_dir))
        skill = loader._parse_skill_file(d / "SKILL.md", "coding")
        assert skill.modes == ["coding"]


class TestSplitFrontmatter:
    """Tests for _split_frontmatter() static method."""

    def test_with_frontmatter(self):
        content = "---\nname: test\n---\n# Body"
        fm, body = SkillLoader._split_frontmatter(content)
        assert fm == "name: test"
        assert body == "# Body"

    def test_without_frontmatter(self):
        content = "# Just a title\n\nBody content"
        fm, body = SkillLoader._split_frontmatter(content)
        assert fm is None
        assert "Body content" in body

    def test_incomplete_frontmatter(self):
        content = "---\nname: test\nno closing"
        fm, body = SkillLoader._split_frontmatter(content)
        assert fm is None

    def test_empty_content(self):
        fm, body = SkillLoader._split_frontmatter("")
        assert fm is None
        assert body == ""


# ── Singleton Tests ──────────────────────────────────────────────────

class TestGetSkillLoader:
    """Tests for get_skill_loader() singleton."""

    def test_returns_loader(self):
        import agent.skills.loader as mod
        mod._loader_instance = None
        loader = get_skill_loader()
        assert isinstance(loader, SkillLoader)

    def test_singleton(self):
        import agent.skills.loader as mod
        mod._loader_instance = None
        l1 = get_skill_loader()
        l2 = get_skill_loader()
        assert l1 is l2
        mod._loader_instance = None  # Cleanup
