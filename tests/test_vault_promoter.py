"""Tests for Promoter — moves validated patterns from SharedMemory to vault."""

import pytest
from unittest.mock import MagicMock, patch

from agent.vault.promoter import promote_patterns, PROMOTION_THRESHOLD, SECTION_MAP
from agent.vault.writer import VaultWriter


@pytest.fixture
def vault_dir(tmp_path):
    d = tmp_path / "vault"
    return d


@pytest.fixture
def writer(vault_dir):
    w = VaultWriter(vault_dir=str(vault_dir))
    w.ensure_structure()
    return w


@pytest.fixture
def mock_shared_memory():
    """Mock SharedMemory with get_all_patterns() method."""
    return MagicMock()


class TestPromoterThreshold:
    """Pattern promotion threshold logic."""

    def test_threshold_constant(self):
        """Promotion threshold is 3."""
        assert PROMOTION_THRESHOLD == 3

    def test_promote_above_threshold(self, mock_shared_memory, writer):
        """Patterns with count >= 3 get promoted."""
        mock_shared_memory.get_all_patterns.return_value = [
            {"pattern_type": "frequent_stock", "pattern_value": "AAPL", "count": 5, "source_mode": "fin"},
        ]
        promoted = promote_patterns(mock_shared_memory, writer)
        assert promoted == 1

        content = (writer.vault_dir / "MEMORY.md").read_text(encoding="utf-8")
        assert "AAPL" in content
        assert "observed 5x" in content

    def test_promote_below_threshold(self, mock_shared_memory, writer):
        """Patterns with count < 3 are NOT promoted."""
        mock_shared_memory.get_all_patterns.return_value = [
            {"pattern_type": "frequent_stock", "pattern_value": "TSLA", "count": 2, "source_mode": "fin"},
        ]
        promoted = promote_patterns(mock_shared_memory, writer)
        assert promoted == 0

        content = (writer.vault_dir / "MEMORY.md").read_text(encoding="utf-8")
        assert "TSLA" not in content

    def test_promote_exact_threshold(self, mock_shared_memory, writer):
        """Count == 3 is promoted (>= threshold)."""
        mock_shared_memory.get_all_patterns.return_value = [
            {"pattern_type": "tool", "pattern_value": "ripgrep", "count": 3, "source_mode": "coding"},
        ]
        promoted = promote_patterns(mock_shared_memory, writer)
        assert promoted == 1


class TestPromoterSectionMapping:
    """Patterns map to the correct MEMORY.md section."""

    def test_section_map_coverage(self):
        """All expected pattern types are mapped."""
        assert "frequent_stock" in SECTION_MAP
        assert "coding_language" in SECTION_MAP
        assert "tool" in SECTION_MAP
        assert "topic" in SECTION_MAP
        assert "language" in SECTION_MAP

    def test_unknown_type_maps_to_other(self, mock_shared_memory, writer):
        """Unknown pattern_type goes to 'Other Patterns' section."""
        mock_shared_memory.get_all_patterns.return_value = [
            {"pattern_type": "weird_type", "pattern_value": "something", "count": 5, "source_mode": "chat"},
        ]
        promote_patterns(mock_shared_memory, writer)

        content = (writer.vault_dir / "MEMORY.md").read_text(encoding="utf-8")
        assert "## Other Patterns" in content
        assert "something" in content


class TestPromoterEdgeCases:
    """Edge cases."""

    def test_promote_multiple_patterns(self, mock_shared_memory, writer):
        """Multiple patterns in one call."""
        mock_shared_memory.get_all_patterns.return_value = [
            {"pattern_type": "frequent_stock", "pattern_value": "AAPL", "count": 5, "source_mode": "fin"},
            {"pattern_type": "coding_language", "pattern_value": "Python", "count": 10, "source_mode": "coding"},
            {"pattern_type": "tool", "pattern_value": "pytest", "count": 1, "source_mode": "coding"},  # below threshold
        ]
        promoted = promote_patterns(mock_shared_memory, writer)
        assert promoted == 2

    def test_promote_empty_patterns(self, mock_shared_memory, writer):
        """Empty patterns list → 0 promoted."""
        mock_shared_memory.get_all_patterns.return_value = []
        promoted = promote_patterns(mock_shared_memory, writer)
        assert promoted == 0

    def test_promote_shared_memory_failure(self, mock_shared_memory, writer):
        """SharedMemory raises → returns 0, no crash."""
        mock_shared_memory.get_all_patterns.side_effect = Exception("DB error")
        promoted = promote_patterns(mock_shared_memory, writer)
        assert promoted == 0

    def test_promote_skips_empty_value(self, mock_shared_memory, writer):
        """Patterns with empty pattern_value are skipped."""
        mock_shared_memory.get_all_patterns.return_value = [
            {"pattern_type": "tool", "pattern_value": "", "count": 10, "source_mode": "coding"},
        ]
        promoted = promote_patterns(mock_shared_memory, writer)
        assert promoted == 0
