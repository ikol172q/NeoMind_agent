"""Tests for VaultWriter — writes structured markdown to the vault."""

import os
import pytest
from pathlib import Path
from datetime import datetime

from agent.vault.writer import VaultWriter


@pytest.fixture
def vault_dir(tmp_path):
    """Create a temporary vault directory."""
    return tmp_path / "vault"


@pytest.fixture
def writer(vault_dir):
    """VaultWriter pointed at a temp dir."""
    return VaultWriter(vault_dir=str(vault_dir))


class TestWriterEnsureStructure:
    """Vault directory scaffolding."""

    def test_writer_ensure_structure(self, writer, vault_dir):
        """Creates all required dirs and root files."""
        writer.ensure_structure()

        assert (vault_dir / "journal").is_dir()
        assert (vault_dir / "retros").is_dir()
        assert (vault_dir / "learnings").is_dir()
        assert (vault_dir / "research").is_dir()
        assert (vault_dir / "MEMORY.md").is_file()
        assert (vault_dir / "current-goals.md").is_file()
        assert (vault_dir / "SOUL.md").is_file()
        assert (vault_dir / ".gitignore").is_file()

    def test_writer_ensure_structure_idempotent(self, writer, vault_dir):
        """Calling ensure_structure() twice doesn't overwrite existing files."""
        writer.ensure_structure()
        # Modify MEMORY.md
        mem_path = vault_dir / "MEMORY.md"
        mem_path.write_text("custom content", encoding="utf-8")

        writer.ensure_structure()
        assert mem_path.read_text(encoding="utf-8") == "custom content"

    def test_writer_initial_files(self, writer, vault_dir):
        """Initial files contain expected frontmatter and headings."""
        writer.ensure_structure()

        memory = (vault_dir / "MEMORY.md").read_text(encoding="utf-8")
        assert "type: memory" in memory
        assert "entries: 0" in memory
        assert "# NeoMind — Long-Term Memory" in memory

        goals = (vault_dir / "current-goals.md").read_text(encoding="utf-8")
        assert "type: goals" in goals
        assert "# Current Improvement Targets" in goals

        soul = (vault_dir / "SOUL.md").read_text(encoding="utf-8")
        assert "type: soul" in soul
        assert "Core Values" in soul


class TestWriterJournal:
    """Journal entry writing."""

    def test_writer_journal_entry(self, writer, vault_dir):
        """Writes a journal file with correct name and content."""
        path = writer.write_journal_entry(
            mode="fin",
            tasks=[{"description": "Analyzed AAPL", "status": "done"}],
            errors=[],
            learnings=["Earnings beat expectations"],
        )

        today = datetime.now().strftime("%Y-%m-%d")
        assert path == f"journal/{today}.md"
        content = (vault_dir / "journal" / f"{today}.md").read_text(encoding="utf-8")
        assert "type: journal" in content
        assert "mode: fin" in content
        assert "Analyzed AAPL" in content
        assert "Earnings beat expectations" in content

    def test_writer_journal_append(self, writer, vault_dir):
        """Second call appends a new session section, doesn't overwrite."""
        writer.write_journal_entry(
            mode="chat",
            tasks=[{"description": "First task", "status": "done"}],
            errors=[],
            learnings=[],
        )
        writer.write_journal_entry(
            mode="chat",
            tasks=[{"description": "Second task", "status": "done"}],
            errors=[],
            learnings=[],
        )

        today = datetime.now().strftime("%Y-%m-%d")
        content = (vault_dir / "journal" / f"{today}.md").read_text(encoding="utf-8")
        assert "First task" in content
        assert "Second task" in content
        assert "## Session" in content

    def test_writer_journal_errors_and_learnings(self, writer, vault_dir):
        """Errors and learnings sections render properly."""
        writer.write_journal_entry(
            mode="coding",
            tasks=[{"description": "Fixed bug", "status": "done"}],
            errors=["TypeError in line 42"],
            learnings=["Always check types"],
        )

        today = datetime.now().strftime("%Y-%m-%d")
        content = (vault_dir / "journal" / f"{today}.md").read_text(encoding="utf-8")
        assert "## Errors" in content
        assert "TypeError in line 42" in content
        assert "## Learnings" in content
        assert "Always check types" in content

    def test_writer_journal_failed_tasks(self, writer, vault_dir):
        """Failed tasks show ❌, completed show ✅."""
        writer.write_journal_entry(
            mode="chat",
            tasks=[
                {"description": "Good task", "status": "done"},
                {"description": "Bad task", "status": "failed"},
            ],
            errors=[],
            learnings=[],
        )

        today = datetime.now().strftime("%Y-%m-%d")
        content = (vault_dir / "journal" / f"{today}.md").read_text(encoding="utf-8")
        assert "tasks_completed: 1" in content
        assert "tasks_failed: 1" in content
        assert "✅ Good task" in content
        assert "❌ Bad task" in content

    def test_writer_empty_tasks(self, writer, vault_dir):
        """Empty task list shows placeholder."""
        writer.write_journal_entry(
            mode="chat", tasks=[], errors=[], learnings=[]
        )

        today = datetime.now().strftime("%Y-%m-%d")
        content = (vault_dir / "journal" / f"{today}.md").read_text(encoding="utf-8")
        assert "(no tasks recorded)" in content

    def test_writer_unicode(self, writer, vault_dir):
        """Chinese/emoji in journal entries."""
        writer.write_journal_entry(
            mode="chat",
            tasks=[{"description": "分析了AAPL 🎯", "status": "done"}],
            errors=[],
            learnings=["用户喜欢简短的回答"],
        )

        today = datetime.now().strftime("%Y-%m-%d")
        content = (vault_dir / "journal" / f"{today}.md").read_text(encoding="utf-8")
        assert "分析了AAPL 🎯" in content
        assert "用户喜欢简短的回答" in content


class TestWriterGoals:
    """Goal writing."""

    def test_writer_goals(self, writer, vault_dir):
        """Writes goals with proper frontmatter and structure."""
        writer.write_goals([
            {
                "goal": "Reduce response length",
                "current": "450 tokens",
                "target": "250 tokens",
                "metric": "avg_tokens_per_response",
                "action": "Use shorter sentences",
                "timeline": "1 week",
            }
        ])

        content = (vault_dir / "current-goals.md").read_text(encoding="utf-8")
        assert "type: goals" in content
        assert "generated_by: weekly_retro" in content
        assert "## 1. Reduce response length" in content
        assert "**Current:** 450 tokens" in content
        assert "**Target:** 250 tokens" in content

    def test_writer_goals_empty(self, writer, vault_dir):
        """Empty improvements list produces a 'no targets' message."""
        writer.write_goals([])
        content = (vault_dir / "current-goals.md").read_text(encoding="utf-8")
        assert "No targets generated this week" in content


class TestWriterMemory:
    """MEMORY.md append operations."""

    def test_writer_append_memory(self, writer, vault_dir):
        """Appends entry under existing section."""
        writer.ensure_structure()
        writer.append_to_memory("Trading Patterns", "AAPL gaps up after earnings (observed 5x, source: fin)")

        content = (vault_dir / "MEMORY.md").read_text(encoding="utf-8")
        assert "AAPL gaps up after earnings" in content

    def test_writer_append_memory_dedup(self, writer, vault_dir):
        """Same entry isn't added twice."""
        writer.ensure_structure()
        writer.append_to_memory("Trading Patterns", "AAPL gaps up (5x)")
        writer.append_to_memory("Trading Patterns", "AAPL gaps up (5x)")

        content = (vault_dir / "MEMORY.md").read_text(encoding="utf-8")
        assert content.count("AAPL gaps up (5x)") == 1

    def test_writer_append_memory_new_section(self, writer, vault_dir):
        """Creates new section if it doesn't exist in MEMORY.md."""
        writer.ensure_structure()
        writer.append_to_memory("Totally New Section", "Something new")

        content = (vault_dir / "MEMORY.md").read_text(encoding="utf-8")
        assert "## Totally New Section" in content
        assert "- Something new" in content

    def test_writer_memory_entry_count(self, writer, vault_dir):
        """Entry count in frontmatter updates on append."""
        writer.ensure_structure()
        content_before = (vault_dir / "MEMORY.md").read_text(encoding="utf-8")
        assert "entries: 0" in content_before

        writer.append_to_memory("Trading Patterns", "First entry")
        content_after = (vault_dir / "MEMORY.md").read_text(encoding="utf-8")
        # entries count should be > 0 now
        assert "entries: 0" not in content_after


class TestWriterRetro:
    """Retro writing."""

    def test_writer_retro(self, writer, vault_dir):
        """Writes retro file with given content and date."""
        writer.write_retro("# Weekly Retro\n\nGood week.", date="2026-03-22")

        filepath = vault_dir / "retros" / "retro-2026-03-22.md"
        assert filepath.is_file()
        content = filepath.read_text(encoding="utf-8")
        assert "Good week." in content

    def test_writer_retro_default_date(self, writer, vault_dir):
        """Retro with no date uses today."""
        writer.write_retro("Some retro content")

        today = datetime.now().strftime("%Y-%m-%d")
        filepath = vault_dir / "retros" / f"retro-{today}.md"
        assert filepath.is_file()


class TestWriterEdgeCases:
    """Edge cases and error handling."""

    def test_writer_handles_readonly_fs(self, tmp_path):
        """Read-only directory → graceful failure, no crash."""
        ro_dir = tmp_path / "readonly_vault"
        ro_dir.mkdir()
        ro_dir.chmod(0o444)

        writer = VaultWriter(vault_dir=str(ro_dir))
        # Should not raise
        writer.ensure_structure()
        result = writer.write_journal_entry(
            mode="chat", tasks=[], errors=[], learnings=[]
        )
        assert result == ""

        # Cleanup: restore permissions so pytest can clean up tmp_path
        ro_dir.chmod(0o755)
