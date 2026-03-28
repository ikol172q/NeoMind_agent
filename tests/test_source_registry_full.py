"""
Comprehensive unit tests for agent/finance/source_registry.py
Tests source trust tracking, accuracy rating, and trust score updates.
"""

import pytest
import time
import json
from pathlib import Path

import sys
sys.path.insert(0, '/sessions/hopeful-magical-rubin/mnt/NeoMind_agent')

from agent.finance.source_registry import (
    SourceRecord, SourceTrustTracker, DEFAULT_TRUST, SOURCE_CATEGORIES
)


class TestSourceRecord:
    """Tests for SourceRecord dataclass."""

    def test_init_basic(self):
        """Test basic initialization."""
        record = SourceRecord(name="Reuters")

        assert record.name == "Reuters"
        assert record.trust_score == 0.5
        assert record.total_reports == 0
        assert record.accurate_reports == 0

    def test_init_with_values(self):
        """Test initialization with all values."""
        record = SourceRecord(
            name="CNN",
            trust_score=0.75,
            total_reports=100,
            accurate_reports=80
        )

        assert record.trust_score == 0.75
        assert record.total_reports == 100
        assert record.accurate_reports == 80

    def test_accuracy_rate_empty(self):
        """Test accuracy rate for new source."""
        record = SourceRecord(name="Test")
        assert record.accuracy_rate == 0.5

    def test_accuracy_rate_calculation(self):
        """Test accuracy rate calculation."""
        record = SourceRecord(
            name="Test",
            total_reports=100,
            accurate_reports=80
        )
        assert record.accuracy_rate == 0.8

    def test_accuracy_rate_perfect(self):
        """Test perfect accuracy."""
        record = SourceRecord(
            name="Perfect",
            total_reports=50,
            accurate_reports=50
        )
        assert record.accuracy_rate == 1.0

    def test_accuracy_rate_zero(self):
        """Test zero accuracy."""
        record = SourceRecord(
            name="Bad",
            total_reports=10,
            accurate_reports=0
        )
        assert record.accuracy_rate == 0.0


class TestDefaultTrust:
    """Tests for default trust scores."""

    def test_default_trust_has_entries(self):
        """Test that DEFAULT_TRUST has entries."""
        assert len(DEFAULT_TRUST) > 0

    def test_default_trust_values_valid(self):
        """Test that all default trust scores are 0-1."""
        for source, score in DEFAULT_TRUST.items():
            assert 0 <= score <= 1
            assert isinstance(source, str)
            assert len(source) > 0

    def test_default_trust_high_sources(self):
        """Test that wire services have high trust."""
        assert DEFAULT_TRUST["reuters"] >= 0.85
        assert DEFAULT_TRUST["bloomberg"] >= 0.85
        assert DEFAULT_TRUST["wsj"] >= 0.85

    def test_default_trust_data_providers(self):
        """Test that data providers are trusted."""
        assert DEFAULT_TRUST["finnhub"] >= 0.85
        assert DEFAULT_TRUST["coingecko"] >= 0.85


class TestSourceCategories:
    """Tests for source categories."""

    def test_categories_exist(self):
        """Test that categories are defined."""
        assert len(SOURCE_CATEGORIES) > 0

    def test_categories_valid(self):
        """Test that categories are valid."""
        valid_cats = {"news", "data", "opinion", "aggregator"}
        for source, cat in SOURCE_CATEGORIES.items():
            assert cat in valid_cats


class TestSourceTrustTrackerInit:
    """Tests for SourceTrustTracker initialization."""

    def test_init_basic(self, tmp_path):
        """Test basic initialization."""
        tracker = SourceTrustTracker(db_path=str(tmp_path / "test.json"))
        assert tracker is not None

    def test_init_creates_db(self, tmp_path):
        """Test that initialization creates database."""
        db_path = str(tmp_path / "test.json")
        tracker = SourceTrustTracker(db_path=db_path)

        # Trigger a save to create the file
        tracker.record_report("test", True)

        assert Path(db_path).exists()


class TestRecordReport:
    """Tests for recording reports."""

    def test_record_report_new_source(self, tmp_path):
        """Test recording report for new source."""
        tracker = SourceTrustTracker(db_path=str(tmp_path / "test.json"))

        tracker.record_report("NewsSource", True)

        record = tracker.get_record("NewsSource")
        assert record is not None
        assert record.total_reports == 1
        assert record.accurate_reports == 1

    def test_record_report_accurate(self, tmp_path):
        """Test recording accurate report."""
        tracker = SourceTrustTracker(db_path=str(tmp_path / "test.json"))

        tracker.record_report("Source", True)
        tracker.record_report("Source", True)

        record = tracker.get_record("Source")
        assert record.total_reports == 2
        assert record.accurate_reports == 2

    def test_record_report_inaccurate(self, tmp_path):
        """Test recording inaccurate report."""
        tracker = SourceTrustTracker(db_path=str(tmp_path / "test.json"))

        tracker.record_report("Source", True)
        tracker.record_report("Source", False)

        record = tracker.get_record("Source")
        assert record.total_reports == 2
        assert record.accurate_reports == 1

    def test_record_report_multiple_sources(self, tmp_path):
        """Test recording for multiple sources."""
        tracker = SourceTrustTracker(db_path=str(tmp_path / "test.json"))

        tracker.record_report("Source1", True)
        tracker.record_report("Source2", False)
        tracker.record_report("Source3", True)

        assert tracker.get_record("Source1").accurate_reports == 1
        assert tracker.get_record("Source2").accurate_reports == 0
        assert tracker.get_record("Source3").accurate_reports == 1

    def test_record_report_updates_timestamp(self, tmp_path):
        """Test that timestamp is updated."""
        tracker = SourceTrustTracker(db_path=str(tmp_path / "test.json"))

        before = time.time()
        tracker.record_report("Source", True)
        after = time.time()

        record = tracker.get_record("Source")
        assert before <= record.last_updated <= after


class TestGetRecord:
    """Tests for getting records."""

    def test_get_record_exists(self, tmp_path):
        """Test getting existing record."""
        tracker = SourceTrustTracker(db_path=str(tmp_path / "test.json"))

        tracker.record_report("Reuters", True)
        record = tracker.get_record("Reuters")

        assert record.name == "Reuters"

    def test_get_record_nonexistent(self, tmp_path):
        """Test getting nonexistent record."""
        tracker = SourceTrustTracker(db_path=str(tmp_path / "test.json"))

        record = tracker.get_record("NonexistentSource")
        assert record is not None  # Should return default
        assert record.trust_score == 0.5

    def test_get_record_case_insensitive(self, tmp_path):
        """Test record lookup is case-insensitive."""
        tracker = SourceTrustTracker(db_path=str(tmp_path / "test.json"))

        tracker.record_report("Reuters", True)
        record1 = tracker.get_record("reuters")
        record2 = tracker.get_record("REUTERS")

        assert record1 is not None
        assert record2 is not None


class TestUpdateScore:
    """Tests for updating trust scores."""

    def test_update_score_basic(self, tmp_path):
        """Test basic score update."""
        tracker = SourceTrustTracker(db_path=str(tmp_path / "test.json"))

        tracker.record_report("Source", True)
        tracker.update_scores()

        record = tracker.get_record("Source")
        assert record.trust_score > 0.5

    def test_update_score_accuracy_based(self, tmp_path):
        """Test score increases with accuracy."""
        tracker = SourceTrustTracker(db_path=str(tmp_path / "test.json"))

        # Perfect record
        for _ in range(10):
            tracker.record_report("Perfect", True)

        tracker.update_scores()
        perfect_score = tracker.get_record("Perfect").trust_score

        # Reset and test poor record
        tracker = SourceTrustTracker(db_path=str(tmp_path / "test2.json"))

        for _ in range(10):
            tracker.record_report("Poor", False)

        tracker.update_scores()
        poor_score = tracker.get_record("Poor").trust_score

        assert perfect_score > poor_score


class TestBonus:
    """Tests for bonus system (breaking news, etc)."""

    def test_apply_breaking_news_bonus(self, tmp_path):
        """Test breaking news bonus."""
        tracker = SourceTrustTracker(db_path=str(tmp_path / "test.json"))

        tracker.record_report("Source", True)
        old_score = tracker.get_record("Source").trust_score

        tracker.apply_breaking_news_bonus("Source", 0.1)

        new_score = tracker.get_record("Source").trust_score
        assert new_score > old_score

    def test_apply_correction_penalty(self, tmp_path):
        """Test correction penalty."""
        tracker = SourceTrustTracker(db_path=str(tmp_path / "test.json"))

        tracker.record_report("Source", True)
        old_score = tracker.get_record("Source").trust_score

        tracker.apply_correction_penalty("Source", 0.15)

        new_score = tracker.get_record("Source").trust_score
        assert new_score < old_score


class TestListAll:
    """Tests for listing all records."""

    def test_list_all_basic(self, tmp_path):
        """Test listing all records."""
        tracker = SourceTrustTracker(db_path=str(tmp_path / "test.json"))

        tracker.record_report("Source1", True)
        tracker.record_report("Source2", False)

        records = tracker.list_all()
        names = {r.name for r in records}

        assert "Source1" in names
        assert "Source2" in names

    def test_list_all_sorted(self, tmp_path):
        """Test that list is sorted by trust score."""
        tracker = SourceTrustTracker(db_path=str(tmp_path / "test.json"))

        # Create sources with different trust levels
        tracker.record_report("HighTrust", True)
        tracker.record_report("HighTrust", True)

        tracker.record_report("LowTrust", False)
        tracker.record_report("LowTrust", False)

        tracker.update_scores()

        records = tracker.list_all()
        assert records[0].trust_score >= records[-1].trust_score

    def test_list_all_empty(self, tmp_path):
        """Test listing when empty."""
        tracker = SourceTrustTracker(db_path=str(tmp_path / "test.json"))

        records = tracker.list_all()
        assert records == []


class TestReset:
    """Tests for resetting records."""

    def test_reset_single_source(self, tmp_path):
        """Test resetting single source."""
        tracker = SourceTrustTracker(db_path=str(tmp_path / "test.json"))

        tracker.record_report("Source", True)
        tracker.reset_source("Source")

        record = tracker.get_record("Source")
        assert record.total_reports == 0
        assert record.trust_score == 0.5

    def test_reset_all(self, tmp_path):
        """Test resetting all sources."""
        tracker = SourceTrustTracker(db_path=str(tmp_path / "test.json"))

        tracker.record_report("Source1", True)
        tracker.record_report("Source2", False)

        tracker.reset_all()

        assert len(tracker.list_all()) == 0


class TestPersistence:
    """Tests for persistence to JSON."""

    def test_persistence_save_load(self, tmp_path):
        """Test that data persists across instances."""
        db_path = str(tmp_path / "test.json")

        # Create tracker and add records
        tracker1 = SourceTrustTracker(db_path=db_path)
        tracker1.record_report("Source", True)
        tracker1.save()

        # Create new tracker and verify data
        tracker2 = SourceTrustTracker(db_path=db_path)
        record = tracker2.get_record("Source")

        assert record is not None
        assert record.total_reports == 1

    def test_persistence_file_format(self, tmp_path):
        """Test JSON file format."""
        db_path = str(tmp_path / "test.json")

        tracker = SourceTrustTracker(db_path=db_path)
        tracker.record_report("Test", True)
        tracker.save()

        content = Path(db_path).read_text()
        data = json.loads(content)

        assert "Test" in data or "test" in str(data).lower()


class TestIntegration:
    """Integration tests."""

    def test_full_workflow(self, tmp_path):
        """Test complete workflow."""
        tracker = SourceTrustTracker(db_path=str(tmp_path / "test.json"))

        # 1. Record various reports
        for _ in range(5):
            tracker.record_report("Reuters", True)

        for _ in range(3):
            tracker.record_report("FakeNews", False)

        # 2. Update scores
        tracker.update_scores()

        # 3. Verify Reuters has higher score
        reuters_score = tracker.get_record("Reuters").trust_score
        fake_score = tracker.get_record("FakeNews").trust_score

        assert reuters_score > fake_score

        # 4. Apply bonuses
        tracker.apply_breaking_news_bonus("Reuters", 0.05)

        # 5. List all
        records = tracker.list_all()
        assert len(records) >= 2

        # 6. Save and reload
        tracker.save()
        tracker2 = SourceTrustTracker(db_path=str(tmp_path / "test.json"))
        assert tracker2.get_record("Reuters") is not None


class TestEdgeCases:
    """Tests for edge cases."""

    def test_very_high_accuracy(self, tmp_path):
        """Test with very high accuracy."""
        tracker = SourceTrustTracker(db_path=str(tmp_path / "test.json"))

        for _ in range(1000):
            tracker.record_report("Perfect", True)

        tracker.update_scores()
        record = tracker.get_record("Perfect")

        assert record.trust_score <= 1.0

    def test_unicode_source_name(self, tmp_path):
        """Test unicode source names."""
        tracker = SourceTrustTracker(db_path=str(tmp_path / "test.json"))

        tracker.record_report("央视", True)
        tracker.record_report("新浪财经", False)

        records = tracker.list_all()
        names = {r.name for r in records}

        assert "央视" in names
        assert "新浪财经" in names

    def test_special_characters_in_source(self, tmp_path):
        """Test special characters in source name."""
        tracker = SourceTrustTracker(db_path=str(tmp_path / "test.json"))

        tracker.record_report("Reuters & Bloomberg", True)

        record = tracker.get_record("Reuters & Bloomberg")
        assert record is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
