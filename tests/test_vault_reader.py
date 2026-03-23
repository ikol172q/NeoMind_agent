"""Tests for VaultReader — reads vault files for system prompt injection."""

import os
import pytest
from pathlib import Path
from datetime import datetime, timedelta

from agent.vault.reader import VaultReader


@pytest.fixture
def vault_dir(tmp_path):
    """Create a temporary vault directory."""
    return tmp_path / "vault"


@pytest.fixture
def reader(vault_dir):
    """VaultReader pointed at a temp dir."""
    return VaultReader(vault_dir=str(vault_dir))


@pytest.fixture
def initialized_vault(vault_dir):
    """Create a vault with all standard files."""
    vault_dir.mkdir(parents=True, exist_ok=True)
    (vault_dir / "journal").mkdir()
    (vault_dir / "retros").mkdir()

    (vault_dir / "MEMORY.md").write_text(
        "---\ntype: memory\nlast_updated: 2026-03-22\nentries: 2\n---\n\n"
        "# NeoMind — Long-Term Memory\n\n"
        "## About Irene\n- Works in tech\n\n"
        "## Trading Patterns\n- AAPL tends to gap up after earnings\n",
        encoding="utf-8",
    )

    (vault_dir / "current-goals.md").write_text(
        "---\ntype: goals\ngenerated_by: weekly_retro\ndate: 2026-03-22\n---\n\n"
        "# Current Improvement Targets\n\n"
        "## 1. Reduce response length\n"
        "- **Current:** 450 tokens\n"
        "- **Target:** 250 tokens\n",
        encoding="utf-8",
    )

    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    (vault_dir / "journal" / f"{yesterday}.md").write_text(
        "---\ntype: journal\ndate: " + yesterday + "\nmode: fin\n---\n\n"
        "# Journal — " + yesterday + "\n\n"
        "## Tasks\n1. Analyzed AAPL earnings\n",
        encoding="utf-8",
    )

    return vault_dir


class TestVaultReaderBasic:
    """Basic read operations."""

    def test_reader_empty_vault(self, reader):
        """Vault dir doesn't exist → returns empty string."""
        assert reader.get_startup_context() == ""

    def test_reader_vault_not_exists(self, reader):
        """vault_exists() returns False when vault empty."""
        assert reader.vault_exists() is False

    def test_reader_vault_exists(self, initialized_vault):
        """vault_exists() returns True when MEMORY.md present."""
        reader = VaultReader(vault_dir=str(initialized_vault))
        assert reader.vault_exists() is True


class TestVaultReaderContent:
    """Content reading and formatting."""

    def test_reader_memory_only(self, vault_dir):
        """Only MEMORY.md exists → returns its content."""
        vault_dir.mkdir(parents=True, exist_ok=True)
        (vault_dir / "MEMORY.md").write_text(
            "---\ntype: memory\n---\n\n# Memory\n\n## Facts\n- Fact one\n",
            encoding="utf-8",
        )
        reader = VaultReader(vault_dir=str(vault_dir))
        ctx = reader.get_startup_context()
        assert "Long-Term Memory" in ctx
        assert "Fact one" in ctx

    def test_reader_goals_only(self, vault_dir):
        """Only current-goals.md → returns its content."""
        vault_dir.mkdir(parents=True, exist_ok=True)
        (vault_dir / "current-goals.md").write_text(
            "---\ntype: goals\n---\n\n# Goals\n\n## 1. Be better\n",
            encoding="utf-8",
        )
        reader = VaultReader(vault_dir=str(vault_dir))
        ctx = reader.get_startup_context()
        assert "Improvement Targets" in ctx
        assert "Be better" in ctx

    def test_reader_all_three(self, initialized_vault):
        """All 3 files → returns combined, MEMORY first."""
        reader = VaultReader(vault_dir=str(initialized_vault))
        ctx = reader.get_startup_context()
        assert "Long-Term Memory" in ctx
        assert "Improvement Targets" in ctx
        assert "Yesterday's Journal" in ctx
        # Memory should come before goals in output
        mem_pos = ctx.index("Long-Term Memory")
        goal_pos = ctx.index("Improvement Targets")
        assert mem_pos < goal_pos

    def test_reader_strips_frontmatter(self, vault_dir):
        """YAML frontmatter is stripped from injected context."""
        vault_dir.mkdir(parents=True, exist_ok=True)
        (vault_dir / "MEMORY.md").write_text(
            "---\ntype: memory\nsecret_key: abc123\n---\n\nPublic content here\n",
            encoding="utf-8",
        )
        reader = VaultReader(vault_dir=str(vault_dir))
        ctx = reader.get_startup_context()
        assert "secret_key" not in ctx
        assert "abc123" not in ctx
        assert "Public content here" in ctx

    def test_reader_preserves_frontmatter_in_raw(self, vault_dir):
        """read_raw() keeps frontmatter."""
        vault_dir.mkdir(parents=True, exist_ok=True)
        (vault_dir / "MEMORY.md").write_text(
            "---\ntype: memory\n---\n\nContent\n", encoding="utf-8"
        )
        reader = VaultReader(vault_dir=str(vault_dir))
        raw = reader.read_raw("MEMORY.md")
        assert "---" in raw
        assert "type: memory" in raw

    def test_reader_truncates_to_budget(self, vault_dir):
        """Content exceeding max_tokens is truncated."""
        vault_dir.mkdir(parents=True, exist_ok=True)
        # Write a large file (10000+ chars)
        big_content = "---\ntype: memory\n---\n\n" + ("A" * 15000) + "\n"
        (vault_dir / "MEMORY.md").write_text(big_content, encoding="utf-8")
        reader = VaultReader(vault_dir=str(vault_dir))
        ctx = reader.get_startup_context(max_tokens=500)
        assert "truncated for token budget" in ctx
        assert len(ctx) < 3000  # 500 tokens * 4 chars + overhead

    def test_reader_handles_unicode(self, vault_dir):
        """Chinese/emoji in vault files."""
        vault_dir.mkdir(parents=True, exist_ok=True)
        (vault_dir / "MEMORY.md").write_text(
            "---\ntype: memory\n---\n\n# 记忆\n\n- 用户喜欢简短的回答 🎯\n",
            encoding="utf-8",
        )
        reader = VaultReader(vault_dir=str(vault_dir))
        ctx = reader.get_startup_context()
        assert "记忆" in ctx
        assert "🎯" in ctx

    def test_reader_handles_missing_journal(self, vault_dir):
        """No journal for yesterday → graceful skip."""
        vault_dir.mkdir(parents=True, exist_ok=True)
        (vault_dir / "MEMORY.md").write_text(
            "---\ntype: memory\n---\n\nSome memory\n", encoding="utf-8"
        )
        reader = VaultReader(vault_dir=str(vault_dir))
        ctx = reader.get_startup_context()
        assert "Yesterday's Journal" not in ctx
        assert "Some memory" in ctx

    def test_reader_handles_corrupt_file(self, vault_dir):
        """Invalid content → graceful skip, no crash."""
        vault_dir.mkdir(parents=True, exist_ok=True)
        # Write binary content
        (vault_dir / "MEMORY.md").write_bytes(b"\xff\xfe invalid utf-8 \x80\x81")
        reader = VaultReader(vault_dir=str(vault_dir))
        # Should not crash
        ctx = reader.get_startup_context()
        assert isinstance(ctx, str)


class TestVaultReaderJournal:
    """Journal-specific operations."""

    def test_reader_list_journal_entries(self, initialized_vault):
        """Returns sorted list of recent journal filenames."""
        reader = VaultReader(vault_dir=str(initialized_vault))
        entries = reader.list_journal_entries()
        assert len(entries) >= 1
        assert all(e.endswith(".md") for e in entries)

    def test_reader_list_journal_empty(self, vault_dir):
        """No journal dir → empty list."""
        vault_dir.mkdir(parents=True, exist_ok=True)
        reader = VaultReader(vault_dir=str(vault_dir))
        assert reader.list_journal_entries() == []

    def test_reader_read_journal_entries(self, initialized_vault):
        """Read recent journal entries with metadata."""
        reader = VaultReader(vault_dir=str(initialized_vault))
        entries = reader.read_journal_entries(days=7)
        assert len(entries) >= 1
        assert "filename" in entries[0]
        assert "raw" in entries[0]
        assert "body" in entries[0]

    def test_reader_read_last_retro(self, initialized_vault):
        """Read the most recent retro."""
        # Create a retro file
        (initialized_vault / "retros" / "retro-2026-03-22.md").write_text(
            "---\ntype: retro\n---\n\n# Retro\n\nSome retro content\n",
            encoding="utf-8",
        )
        reader = VaultReader(vault_dir=str(initialized_vault))
        retro = reader.read_last_retro()
        assert retro is not None
        assert "Some retro content" in retro

    def test_reader_read_last_retro_none(self, vault_dir):
        """No retros → None."""
        vault_dir.mkdir(parents=True, exist_ok=True)
        reader = VaultReader(vault_dir=str(vault_dir))
        assert reader.read_last_retro() is None
