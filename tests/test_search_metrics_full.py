"""
Comprehensive unit tests for agent/search/metrics.py

Tests search quality metrics tracking and reporting.
"""

import pytest
import os
import tempfile
import json
from datetime import datetime, timezone
from unittest.mock import patch

from agent.search.metrics import SearchMetrics


class TestSearchMetricsInit:
    """Tests for SearchMetrics initialization."""

    def test_init_default_storage_dir(self):
        """Test initialization with default storage directory."""
        metrics = SearchMetrics()
        assert metrics._storage_dir == os.path.expanduser("~/.neomind")

    def test_init_custom_storage_dir(self):
        """Test initialization with custom storage directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            metrics = SearchMetrics(storage_dir=tmpdir)
            assert metrics._storage_dir == tmpdir

    def test_init_creates_storage_directory(self):
        """Test that initialization creates storage directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_dir = os.path.join(tmpdir, "neomind")
            metrics = SearchMetrics(storage_dir=storage_dir)

            assert os.path.exists(storage_dir)

    def test_init_graceful_degradation_no_permission(self):
        """Test graceful degradation when directory creation fails."""
        with patch('os.makedirs', side_effect=PermissionError("No permission")):
            metrics = SearchMetrics()
            # Should not raise, just degrade
            assert metrics._log_path is None


class TestSearchMetricsRecord:
    """Tests for record() method."""

    @pytest.fixture
    def temp_metrics(self):
        """Create temporary metrics instance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield SearchMetrics(storage_dir=tmpdir)

    def test_record_basic(self, temp_metrics):
        """Test basic record operation."""
        temp_metrics.record(
            query="test query",
            query_type="general",
            sources_used=["source1", "source2"],
            sources_failed=[],
            result_count=5,
            extraction_count=2,
            reranked=True,
            cached=False,
            latency_ms=150.5,
        )

        assert len(temp_metrics._session_events) == 1
        event = temp_metrics._session_events[0]
        assert event["query"] == "test query"
        assert event["query_type"] == "general"
        assert event["result_count"] == 5

    def test_record_truncates_long_query(self, temp_metrics):
        """Test that long queries are truncated."""
        long_query = "a" * 500
        temp_metrics.record(
            query=long_query,
            query_type="general",
            sources_used=[],
            sources_failed=[],
            result_count=0,
            extraction_count=0,
            reranked=False,
            cached=False,
            latency_ms=0,
        )

        event = temp_metrics._session_events[0]
        assert len(event["query"]) <= 200

    def test_record_rounds_latency(self, temp_metrics):
        """Test that latency is rounded to 1 decimal place."""
        temp_metrics.record(
            query="test",
            query_type="general",
            sources_used=[],
            sources_failed=[],
            result_count=0,
            extraction_count=0,
            reranked=False,
            cached=False,
            latency_ms=123.456789,
        )

        event = temp_metrics._session_events[0]
        assert event["latency_ms"] == 123.5

    def test_record_counts_expansion_queries(self, temp_metrics):
        """Test that expanded_queries are counted."""
        temp_metrics.record(
            query="test",
            query_type="general",
            sources_used=[],
            sources_failed=[],
            result_count=0,
            extraction_count=0,
            reranked=False,
            cached=False,
            latency_ms=0,
            expanded_queries=["test", "variant1", "variant2"],
        )

        event = temp_metrics._session_events[0]
        assert event["expansion_count"] == 3

    def test_record_expansion_count_default(self, temp_metrics):
        """Test expansion count defaults to 1 when None."""
        temp_metrics.record(
            query="test",
            query_type="general",
            sources_used=[],
            sources_failed=[],
            result_count=0,
            extraction_count=0,
            reranked=False,
            cached=False,
            latency_ms=0,
            expanded_queries=None,
        )

        event = temp_metrics._session_events[0]
        assert event["expansion_count"] == 1

    def test_record_persistence_to_file(self, temp_metrics):
        """Test that records are persisted to file."""
        temp_metrics.record(
            query="test",
            query_type="general",
            sources_used=["test_source"],
            sources_failed=[],
            result_count=1,
            extraction_count=0,
            reranked=False,
            cached=False,
            latency_ms=100,
        )

        # Check file exists and contains data
        assert os.path.exists(temp_metrics._log_path)
        with open(temp_metrics._log_path, 'r') as f:
            lines = f.readlines()
            assert len(lines) > 0
            data = json.loads(lines[0])
            assert data["query"] == "test"


class TestSearchMetricsSessionStats:
    """Tests for session statistics."""

    @pytest.fixture
    def temp_metrics_with_events(self):
        """Create metrics with sample events."""
        with tempfile.TemporaryDirectory() as tmpdir:
            m = SearchMetrics(storage_dir=tmpdir)
            # Add some events
            for i in range(3):
                m.record(
                    query=f"query{i}",
                    query_type="general",
                    sources_used=["source1"],
                    sources_failed=[],
                    result_count=5 + i,
                    extraction_count=2,
                    reranked=i % 2 == 0,
                    cached=i == 0,
                    latency_ms=100.0 + i * 50,
                )
            yield m

    def test_get_session_stats_returns_dict(self, temp_metrics_with_events):
        """Test get_session_stats returns a dict."""
        stats = temp_metrics_with_events.get_session_stats()
        assert isinstance(stats, dict)

    def test_session_stats_contains_expected_keys(self, temp_metrics_with_events):
        """Test session stats contains all expected keys."""
        stats = temp_metrics_with_events.get_session_stats()

        expected_keys = [
            "total_searches",
            "avg_latency_ms",
            "p50_latency_ms",
            "cache_hit_rate",
            "rerank_rate",
            "avg_results_per_search",
            "source_usage",
        ]

        for key in expected_keys:
            assert key in stats

    def test_session_stats_total_searches(self, temp_metrics_with_events):
        """Test total_searches count."""
        stats = temp_metrics_with_events.get_session_stats()
        assert stats["total_searches"] == 3

    def test_session_stats_cache_hit_rate(self, temp_metrics_with_events):
        """Test cache hit rate calculation."""
        stats = temp_metrics_with_events.get_session_stats()
        # 1 out of 3 cached
        assert stats["cache_hit_rate"] >= 30  # At least 30%

    def test_session_stats_rerank_rate(self, temp_metrics_with_events):
        """Test rerank rate calculation."""
        stats = temp_metrics_with_events.get_session_stats()
        # 2 out of 3 reranked
        assert stats["rerank_rate"] >= 50

    def test_session_stats_source_usage(self, temp_metrics_with_events):
        """Test source usage tracking."""
        stats = temp_metrics_with_events.get_session_stats()
        assert "source_usage" in stats
        assert "source1" in stats["source_usage"]


class TestSearchMetricsAllTimeStats:
    """Tests for all-time statistics."""

    @pytest.fixture
    def temp_metrics_persisted(self):
        """Create metrics with persisted events."""
        with tempfile.TemporaryDirectory() as tmpdir:
            m = SearchMetrics(storage_dir=tmpdir)
            # Add events
            for i in range(2):
                m.record(
                    query=f"query{i}",
                    query_type="general",
                    sources_used=["source1"],
                    sources_failed=[],
                    result_count=5,
                    extraction_count=1,
                    reranked=False,
                    cached=False,
                    latency_ms=100,
                )
            yield m

    def test_get_all_stats_returns_dict(self, temp_metrics_persisted):
        """Test get_all_stats returns dict."""
        stats = temp_metrics_persisted.get_all_stats()
        assert isinstance(stats, dict)

    def test_get_all_stats_from_file(self, temp_metrics_persisted):
        """Test get_all_stats loads from file."""
        stats = temp_metrics_persisted.get_all_stats()
        # Should have loaded from disk
        assert stats["total_searches"] >= 2


class TestSearchMetricsComputeStats:
    """Tests for _compute_stats method."""

    def test_compute_stats_empty_events(self):
        """Test compute_stats with empty events."""
        metrics = SearchMetrics()
        stats = metrics._compute_stats([])

        assert stats["total_searches"] == 0
        assert "message" in stats

    def test_compute_stats_single_event(self):
        """Test compute_stats with single event."""
        metrics = SearchMetrics()
        event = {
            "latency_ms": 100,
            "cached": False,
            "reranked": True,
            "result_count": 5,
            "extraction_count": 2,
            "sources_used": ["source1"],
            "sources_failed": [],
            "query_type": "general",
        }

        stats = metrics._compute_stats([event])

        assert stats["total_searches"] == 1
        assert stats["avg_latency_ms"] == 100.0
        assert stats["rerank_rate"] == 100.0

    def test_compute_stats_multiple_events(self):
        """Test compute_stats with multiple events."""
        metrics = SearchMetrics()
        events = [
            {
                "latency_ms": 100,
                "cached": False,
                "reranked": True,
                "result_count": 5,
                "extraction_count": 2,
                "sources_used": ["source1"],
                "sources_failed": [],
                "query_type": "general",
            },
            {
                "latency_ms": 200,
                "cached": True,
                "reranked": False,
                "result_count": 10,
                "extraction_count": 1,
                "sources_used": ["source1", "source2"],
                "sources_failed": ["source3"],
                "query_type": "news",
            },
        ]

        stats = metrics._compute_stats(events)

        assert stats["total_searches"] == 2
        assert stats["avg_latency_ms"] == 150.0
        assert stats["cache_hit_rate"] == 50.0


class TestSearchMetricsFormatReport:
    """Tests for format_report method."""

    @pytest.fixture
    def temp_metrics_with_data(self):
        """Create metrics with data for reporting."""
        with tempfile.TemporaryDirectory() as tmpdir:
            m = SearchMetrics(storage_dir=tmpdir)
            for i in range(5):
                m.record(
                    query=f"query{i}",
                    query_type="general" if i < 3 else "news",
                    sources_used=["source1", "source2"],
                    sources_failed=["source3"] if i == 4 else [],
                    result_count=5 + i,
                    extraction_count=2,
                    reranked=True,
                    cached=i % 2 == 0,
                    latency_ms=100.0 + i * 10,
                )
            yield m

    def test_format_report_no_data(self):
        """Test format_report with no data."""
        metrics = SearchMetrics()
        report = metrics.format_report()

        assert "No search data yet" in report

    def test_format_report_session_data(self, temp_metrics_with_data):
        """Test format_report with session data."""
        report = temp_metrics_with_data.format_report(all_time=False)

        assert "Search Quality Metrics" in report
        assert "Total searches" in report
        assert "Avg latency" in report

    def test_format_report_contains_source_info(self, temp_metrics_with_data):
        """Test format_report includes source information."""
        report = temp_metrics_with_data.format_report(all_time=False)

        assert "Source usage" in report
        assert "source1" in report or "Source" in report

    def test_format_report_contains_query_types(self, temp_metrics_with_data):
        """Test format_report includes query type distribution."""
        report = temp_metrics_with_data.format_report(all_time=False)

        assert "Query type distribution" in report


class TestSearchMetricsClear:
    """Tests for clear method."""

    @pytest.fixture
    def temp_metrics_to_clear(self):
        """Create metrics with data to clear."""
        with tempfile.TemporaryDirectory() as tmpdir:
            m = SearchMetrics(storage_dir=tmpdir)
            m.record(
                query="test",
                query_type="general",
                sources_used=[],
                sources_failed=[],
                result_count=0,
                extraction_count=0,
                reranked=False,
                cached=False,
                latency_ms=0,
            )
            yield m

    def test_clear_removes_session_events(self, temp_metrics_to_clear):
        """Test clear removes session events."""
        assert len(temp_metrics_to_clear._session_events) > 0

        temp_metrics_to_clear.clear()

        assert len(temp_metrics_to_clear._session_events) == 0

    def test_clear_removes_log_file(self, temp_metrics_to_clear):
        """Test clear removes the log file."""
        assert os.path.exists(temp_metrics_to_clear._log_path)

        temp_metrics_to_clear.clear()

        assert not os.path.exists(temp_metrics_to_clear._log_path)


class TestSearchMetricsEdgeCases:
    """Tests for edge cases."""

    def test_record_with_zero_latency(self):
        """Test recording with zero latency."""
        metrics = SearchMetrics()
        metrics.record(
            query="test",
            query_type="general",
            sources_used=[],
            sources_failed=[],
            result_count=0,
            extraction_count=0,
            reranked=False,
            cached=False,
            latency_ms=0,
        )

        assert metrics._session_events[0]["latency_ms"] == 0.0

    def test_record_with_many_sources(self):
        """Test recording with many sources."""
        metrics = SearchMetrics()
        sources = [f"source{i}" for i in range(20)]

        metrics.record(
            query="test",
            query_type="general",
            sources_used=sources,
            sources_failed=[],
            result_count=100,
            extraction_count=50,
            reranked=False,
            cached=False,
            latency_ms=500,
        )

        event = metrics._session_events[0]
        assert len(event["sources_used"]) == 20

    def test_compute_stats_with_high_percentiles(self):
        """Test percentile calculations with varied latencies."""
        metrics = SearchMetrics()
        events = [{"latency_ms": i * 10, "cached": False, "reranked": False,
                   "result_count": 0, "extraction_count": 0, "sources_used": [],
                   "sources_failed": [], "query_type": "general"} for i in range(100)]

        stats = metrics._compute_stats(events)

        assert stats["p50_latency_ms"] > 0
        assert stats["p95_latency_ms"] > stats["p50_latency_ms"]
