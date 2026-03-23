"""Integration tests — VaultWriter → VaultReader round-trip."""

import pytest
from datetime import datetime, timedelta

from agent.vault.reader import VaultReader
from agent.vault.writer import VaultWriter
from agent.vault.promoter import promote_patterns
from unittest.mock import MagicMock


@pytest.fixture
def vault_dir(tmp_path):
    return tmp_path / "vault"


@pytest.fixture
def writer(vault_dir):
    w = VaultWriter(vault_dir=str(vault_dir))
    w.ensure_structure()
    return w


@pytest.fixture
def reader(vault_dir, writer):
    """Reader that sees the writer's vault."""
    return VaultReader(vault_dir=str(vault_dir))


class TestWriteReadRoundTrip:
    """Writer produces files that Reader can consume."""

    def test_memory_round_trip(self, writer, reader):
        """Writer's initial MEMORY.md is readable by Reader."""
        assert reader.vault_exists() is True
        ctx = reader.get_startup_context()
        assert "Long-Term Memory" in ctx

    def test_goals_round_trip(self, writer, reader):
        """Writer's goals are readable by Reader."""
        writer.write_goals([
            {
                "goal": "Improve accuracy",
                "current": "85%",
                "target": "95%",
                "metric": "accuracy",
                "action": "Better prompts",
                "timeline": "1 week",
            }
        ])
        ctx = reader.get_startup_context()
        assert "Improvement Targets" in ctx
        assert "Improve accuracy" in ctx

    def test_journal_round_trip(self, writer, reader, vault_dir):
        """Writer's journal from yesterday is picked up by Reader."""
        # Write a journal entry backdated to yesterday
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        journal_dir = vault_dir / "journal"
        journal_dir.mkdir(parents=True, exist_ok=True)
        (journal_dir / f"{yesterday}.md").write_text(
            f"---\ntype: journal\ndate: {yesterday}\nmode: fin\n---\n\n"
            f"# Journal — {yesterday}\n\n## Tasks\n1. Checked MSFT\n",
            encoding="utf-8",
        )

        ctx = reader.get_startup_context()
        assert "Yesterday's Journal" in ctx
        assert "Checked MSFT" in ctx

    def test_retro_round_trip(self, writer, reader):
        """Writer retro → Reader reads it back."""
        writer.write_retro(
            "---\ntype: retro\n---\n\n# Retro\n\nImproved accuracy by 10%.",
            date="2026-03-22",
        )
        retro = reader.read_last_retro()
        assert retro is not None
        assert "Improved accuracy by 10%" in retro


class TestPromotionIntegration:
    """Full promotion pipeline: SharedMemory → Promoter → Writer → Reader."""

    def test_promote_and_read(self, writer, reader):
        """Promoted patterns appear in Reader's startup context."""
        mock_mem = MagicMock()
        mock_mem.get_all_patterns.return_value = [
            {"pattern_type": "frequent_stock", "pattern_value": "NVDA", "count": 7, "source_mode": "fin"},
        ]
        promoted = promote_patterns(mock_mem, writer)
        assert promoted == 1

        ctx = reader.get_startup_context()
        assert "NVDA" in ctx
        assert "observed 7x" in ctx

    def test_promote_dedup_across_sessions(self, writer, reader):
        """Promoting the same pattern twice doesn't create duplicates."""
        mock_mem = MagicMock()
        mock_mem.get_all_patterns.return_value = [
            {"pattern_type": "frequent_stock", "pattern_value": "AAPL (observed 5x, source: fin)", "count": 5, "source_mode": "fin"},
        ]
        promote_patterns(mock_mem, writer)
        promote_patterns(mock_mem, writer)

        content = (writer.vault_dir / "MEMORY.md").read_text(encoding="utf-8")
        assert content.count("AAPL (observed 5x, source: fin)") == 1
