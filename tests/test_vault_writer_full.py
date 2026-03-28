"""Comprehensive tests for agent/vault/writer.py — VaultWriter + wikilinks."""

import pytest
from pathlib import Path
from datetime import datetime
from unittest.mock import patch

from agent.vault.writer import VaultWriter, COMMON_WORDS


@pytest.fixture
def vault_dir(tmp_path):
    d = tmp_path / "vault"
    d.mkdir()
    return d


@pytest.fixture
def writer(vault_dir):
    w = VaultWriter(vault_dir=str(vault_dir))
    return w


# ── Wikilinks Tests ───────────────────────────────────────────────────

class TestWikify:
    """Tests for _wikify() — stock ticker and code wikification."""

    def test_usd_ticker(self, writer):
        assert writer._wikify("Check $AAPL today") == "Check [[$AAPL]] today"

    def test_multiple_tickers(self, writer):
        result = writer._wikify("Look at $AAPL and $GOOGL and $MSFT")
        assert "[[$AAPL]]" in result
        assert "[[$GOOGL]]" in result
        assert "[[$MSFT]]" in result

    def test_chinese_stock_code(self, writer):
        result = writer._wikify("贵州茅台 600519 is rising")
        assert "[[600519]]" in result

    def test_chinese_stock_code_000_prefix(self, writer):
        result = writer._wikify("五粮液 000858 今天涨了")
        assert "[[000858]]" in result

    def test_preserves_code_blocks(self, writer):
        text = "```python\nprice = $AAPL\ncode = 600519\n```"
        result = writer._wikify(text)
        assert "[[$AAPL]]" not in result
        assert "[[600519]]" not in result
        assert "$AAPL" in result

    def test_preserves_existing_wikilinks(self, writer):
        text = "Already linked: [[$AAPL]] and [[600519]]"
        result = writer._wikify(text)
        assert result.count("[[$AAPL]]") == 1  # Not double-wrapped
        assert result.count("[[600519]]") == 1

    def test_no_wikify_lowercase(self, writer):
        # Only uppercase tickers get wikified
        result = writer._wikify("not a ticker: $aapl")
        assert "[[$aapl]]" not in result

    def test_no_wikify_too_long_ticker(self, writer):
        result = writer._wikify("$TOOLONG is not wikified")
        assert "[[$TOOLONG]]" not in result

    def test_ticker_at_end_of_line(self, writer):
        result = writer._wikify("Buy $TSLA")
        assert "[[$TSLA]]" in result

    def test_mixed_content(self, writer):
        text = "$AAPL is at 600519 level. 000858 too."
        result = writer._wikify(text)
        assert "[[$AAPL]]" in result
        assert "[[600519]]" in result
        assert "[[000858]]" in result

    def test_no_wikify_partial_number(self, writer):
        # 5-digit number should NOT be wikified
        result = writer._wikify("code 12345 here")
        assert "[[12345]]" not in result

    def test_7_digit_number_not_wikified(self, writer):
        result = writer._wikify("code 1234567 here")
        assert "[[1234567]]" not in result


class TestWikifyLearnings:
    """Tests for _wikify_learnings()."""

    def test_wikify_list(self, writer):
        learnings = ["Bought $AAPL at 600519", "Sold $TSLA"]
        result = writer._wikify_learnings(learnings)
        assert "[[$AAPL]]" in result[0]
        assert "[[600519]]" in result[0]
        assert "[[$TSLA]]" in result[1]

    def test_empty_list(self, writer):
        assert writer._wikify_learnings([]) == []

    def test_preserves_non_ticker_content(self, writer):
        learnings = ["Nothing special here"]
        result = writer._wikify_learnings(learnings)
        assert result == ["Nothing special here"]


# ── Structure Tests ───────────────────────────────────────────────────

class TestEnsureStructure:
    """Tests for ensure_structure()."""

    def test_creates_directories(self, writer, vault_dir):
        writer.ensure_structure()
        assert (vault_dir / "journal").is_dir()
        assert (vault_dir / "retros").is_dir()
        assert (vault_dir / "learnings").is_dir()
        assert (vault_dir / "research").is_dir()

    def test_creates_memory_file(self, writer, vault_dir):
        writer.ensure_structure()
        assert (vault_dir / "MEMORY.md").exists()
        content = (vault_dir / "MEMORY.md").read_text(encoding="utf-8")
        assert "type: memory" in content
        assert "Long-Term Memory" in content

    def test_creates_goals_file(self, writer, vault_dir):
        writer.ensure_structure()
        assert (vault_dir / "current-goals.md").exists()
        content = (vault_dir / "current-goals.md").read_text(encoding="utf-8")
        assert "type: goals" in content

    def test_creates_soul_file(self, writer, vault_dir):
        writer.ensure_structure()
        assert (vault_dir / "SOUL.md").exists()
        content = (vault_dir / "SOUL.md").read_text(encoding="utf-8")
        assert "type: soul" in content
        assert "NeoMind" in content

    def test_creates_gitignore(self, writer, vault_dir):
        writer.ensure_structure()
        assert (vault_dir / ".gitignore").exists()
        content = (vault_dir / ".gitignore").read_text(encoding="utf-8")
        assert ".obsidian/" in content

    def test_idempotent(self, writer, vault_dir):
        writer.ensure_structure()
        # Modify MEMORY.md
        (vault_dir / "MEMORY.md").write_text("Custom content", encoding="utf-8")
        # Call again — should NOT overwrite
        writer.ensure_structure()
        assert (vault_dir / "MEMORY.md").read_text(encoding="utf-8") == "Custom content"


# ── Journal Tests ─────────────────────────────────────────────────────

class TestWriteJournalEntry:
    """Tests for write_journal_entry()."""

    def test_creates_journal_file(self, writer, vault_dir):
        result = writer.write_journal_entry(
            mode="chat",
            tasks=[{"description": "task1", "status": "done"}],
            errors=[],
            learnings=["learned something"],
        )
        assert result != ""
        today = datetime.now().strftime("%Y-%m-%d")
        filepath = vault_dir / "journal" / f"{today}.md"
        assert filepath.exists()

    def test_journal_has_frontmatter(self, writer, vault_dir):
        writer.write_journal_entry(
            mode="coding",
            tasks=[{"description": "code review"}],
            errors=["minor bug"],
            learnings=[],
        )
        today = datetime.now().strftime("%Y-%m-%d")
        content = (vault_dir / "journal" / f"{today}.md").read_text(encoding="utf-8")
        assert "---" in content
        assert "type: journal" in content
        assert "mode: coding" in content

    def test_journal_wikifies_content(self, writer, vault_dir):
        writer.write_journal_entry(
            mode="fin",
            tasks=[],
            errors=[],
            learnings=["Watched $AAPL and 600519"],
        )
        today = datetime.now().strftime("%Y-%m-%d")
        content = (vault_dir / "journal" / f"{today}.md").read_text(encoding="utf-8")
        assert "[[$AAPL]]" in content
        assert "[[600519]]" in content

    def test_journal_appends_second_session(self, writer, vault_dir):
        writer.write_journal_entry(
            mode="chat", tasks=[], errors=[], learnings=["session 1"],
        )
        writer.write_journal_entry(
            mode="coding", tasks=[], errors=[], learnings=["session 2"],
        )
        today = datetime.now().strftime("%Y-%m-%d")
        content = (vault_dir / "journal" / f"{today}.md").read_text(encoding="utf-8")
        assert "session 1" in content
        assert "session 2" in content
        assert "Session" in content

    def test_tasks_status_icons(self, writer, vault_dir):
        writer.write_journal_entry(
            mode="chat",
            tasks=[
                {"description": "success task", "status": "done"},
                {"description": "failed task", "status": "failed"},
            ],
            errors=[], learnings=[],
        )
        today = datetime.now().strftime("%Y-%m-%d")
        content = (vault_dir / "journal" / f"{today}.md").read_text(encoding="utf-8")
        assert "✅" in content
        assert "❌" in content

    def test_empty_tasks(self, writer, vault_dir):
        writer.write_journal_entry(mode="chat", tasks=[], errors=[], learnings=[])
        today = datetime.now().strftime("%Y-%m-%d")
        content = (vault_dir / "journal" / f"{today}.md").read_text(encoding="utf-8")
        assert "no tasks recorded" in content

    def test_returns_empty_on_error(self, writer):
        with patch.object(Path, "write_text", side_effect=OSError("disk full")):
            result = writer.write_journal_entry(
                mode="chat", tasks=[], errors=[], learnings=[],
            )
            # Should not crash; returns "" on failure
            assert result == ""


# ── Goals Tests ───────────────────────────────────────────────────────

class TestWriteGoals:
    """Tests for write_goals()."""

    def test_writes_goals_file(self, writer, vault_dir):
        writer.write_goals([
            {"goal": "Improve speed", "current": "3s", "target": "1s",
             "metric": "latency", "action": "optimize", "timeline": "1 week"},
        ])
        content = (vault_dir / "current-goals.md").read_text(encoding="utf-8")
        assert "Improve speed" in content
        assert "Current:" in content
        assert "Target:" in content

    def test_empty_goals(self, writer, vault_dir):
        writer.write_goals([])
        content = (vault_dir / "current-goals.md").read_text(encoding="utf-8")
        assert "insufficient data" in content

    def test_goals_has_frontmatter(self, writer, vault_dir):
        writer.write_goals([{"goal": "Test"}])
        content = (vault_dir / "current-goals.md").read_text(encoding="utf-8")
        assert "type: goals" in content
        assert "generated_by: weekly_retro" in content


# ── Memory (append_to_memory) Tests ──────────────────────────────────

class TestAppendToMemory:
    """Tests for append_to_memory()."""

    def test_appends_to_existing_section(self, writer, vault_dir):
        writer.ensure_structure()
        writer.append_to_memory("Trading Patterns", "$AAPL (observed 5x, source: fin)")
        content = (vault_dir / "MEMORY.md").read_text(encoding="utf-8")
        assert "$AAPL" in content or "[[$AAPL]]" in content

    def test_creates_new_section(self, writer, vault_dir):
        writer.ensure_structure()
        writer.append_to_memory("New Section", "new entry")
        content = (vault_dir / "MEMORY.md").read_text(encoding="utf-8")
        assert "## New Section" in content
        assert "new entry" in content

    def test_deduplication(self, writer, vault_dir):
        writer.ensure_structure()
        writer.append_to_memory("Trading Patterns", "AAPL pattern")
        writer.append_to_memory("Trading Patterns", "AAPL pattern")  # duplicate
        content = (vault_dir / "MEMORY.md").read_text(encoding="utf-8")
        assert content.count("AAPL pattern") == 1

    def test_wikifies_entry(self, writer, vault_dir):
        writer.ensure_structure()
        writer.append_to_memory("Trading Patterns", "$TSLA observed 3x")
        content = (vault_dir / "MEMORY.md").read_text(encoding="utf-8")
        assert "[[$TSLA]]" in content

    def test_updates_entry_count(self, writer, vault_dir):
        writer.ensure_structure()
        writer.append_to_memory("Trading Patterns", "entry 1")
        writer.append_to_memory("Trading Patterns", "entry 2")
        content = (vault_dir / "MEMORY.md").read_text(encoding="utf-8")
        # Should have updated entries count
        assert "entries:" in content

    def test_updates_last_updated_date(self, writer, vault_dir):
        writer.ensure_structure()
        writer.append_to_memory("Trading Patterns", "new entry")
        content = (vault_dir / "MEMORY.md").read_text(encoding="utf-8")
        today = datetime.now().strftime("%Y-%m-%d")
        assert f"last_updated: {today}" in content


# ── Retro Tests ───────────────────────────────────────────────────────

class TestWriteRetro:
    """Tests for write_retro()."""

    def test_writes_retro_file(self, writer, vault_dir):
        writer.write_retro("# Weekly Retro\nGood week.", date="2024-01-15")
        filepath = vault_dir / "retros" / "retro-2024-01-15.md"
        assert filepath.exists()
        content = filepath.read_text(encoding="utf-8")
        assert "Good week" in content

    def test_default_date(self, writer, vault_dir):
        writer.write_retro("# Retro")
        today = datetime.now().strftime("%Y-%m-%d")
        assert (vault_dir / "retros" / f"retro-{today}.md").exists()


# ── Frontmatter Tests ────────────────────────────────────────────────

class TestBuildFrontmatter:
    """Tests for _build_frontmatter()."""

    def test_basic_frontmatter(self, writer):
        fm = writer._build_frontmatter({"type": "journal", "date": "2024-01-15"})
        assert "---" in fm
        assert "type: journal" in fm
        assert "date: 2024-01-15" in fm

    def test_list_values(self, writer):
        fm = writer._build_frontmatter({"tags": ["tag1", "tag2"]})
        assert "tags: [tag1, tag2]" in fm

    def test_bool_values(self, writer):
        fm = writer._build_frontmatter({"active": True, "hidden": False})
        assert "active: true" in fm
        assert "hidden: false" in fm


# ── Initial Templates Tests ──────────────────────────────────────────

class TestInitialTemplates:
    """Tests for _write_initial_* methods."""

    def test_initial_memory_template(self, writer, vault_dir):
        writer._write_initial_memory()
        content = (vault_dir / "MEMORY.md").read_text(encoding="utf-8")
        assert "Long-Term Memory" in content
        assert "About Irene" in content
        assert "Trading Patterns" in content
        assert "Coding Preferences" in content
        assert "Corrections & Lessons" in content

    def test_initial_goals_template(self, writer, vault_dir):
        writer._write_initial_goals()
        content = (vault_dir / "current-goals.md").read_text(encoding="utf-8")
        assert "Improvement Targets" in content

    def test_initial_soul_template(self, writer, vault_dir):
        writer._write_initial_soul()
        content = (vault_dir / "SOUL.md").read_text(encoding="utf-8")
        assert "NeoMind" in content
        assert "Core Values" in content
        assert "Financial data MUST come from tool calls" in content


# ── COMMON_WORDS Tests ───────────────────────────────────────────────

class TestCommonWords:
    """Tests for COMMON_WORDS exclusion set."""

    def test_common_words_are_uppercase(self):
        for word in COMMON_WORDS:
            assert word == word.upper()

    def test_expected_words_present(self):
        assert "THE" in COMMON_WORDS
        assert "AND" in COMMON_WORDS
        assert "FOR" in COMMON_WORDS
        assert "NOT" in COMMON_WORDS

    def test_count(self):
        assert len(COMMON_WORDS) >= 20
