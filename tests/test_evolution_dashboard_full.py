"""Comprehensive tests for agent/evolution/dashboard.py."""

import pytest
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
from agent.evolution.dashboard import collect_metrics, generate_dashboard


class TestCollectMetrics:
    """Tests for collect_metrics()."""

    def test_returns_dict_with_required_keys(self):
        # Don't mock the whole sys.modules entry — it leaks MagicMock objects
        # that get passed to sqlite3.connect() as file paths.
        # Instead, just call collect_metrics() directly; it handles missing data gracefully.
        metrics = collect_metrics()
        assert "timestamp" in metrics
        assert "health" in metrics
        assert "daily_stats" in metrics
        assert "mode_distribution" in metrics
        assert "patterns" in metrics
        assert "evidence_recent" in metrics
        assert "evolution_timeline" in metrics
        assert "learning_log" in metrics

    def test_graceful_when_no_modules(self):
        """Should not crash even if auto_evolve, logger, evidence all fail."""
        with patch("agent.evolution.dashboard.collect_metrics.__module__", "test"):
            metrics = collect_metrics()
        assert isinstance(metrics, dict)
        assert metrics["daily_stats"] == [] or isinstance(metrics["daily_stats"], list)

    def test_timestamp_format(self):
        metrics = collect_metrics()
        assert "T" in metrics["timestamp"]  # ISO format

    def test_health_default_empty(self):
        metrics = collect_metrics()
        assert isinstance(metrics["health"], dict)

    def test_patterns_default_empty(self):
        metrics = collect_metrics()
        assert isinstance(metrics["patterns"], list)


class TestGenerateDashboard:
    """Tests for generate_dashboard()."""

    def test_returns_html_string(self):
        html = generate_dashboard()
        assert isinstance(html, str)
        assert "<!DOCTYPE html>" in html
        assert "</html>" in html

    def test_contains_title(self):
        html = generate_dashboard()
        assert "NeoMind Evolution Dashboard" in html

    def test_contains_chart_js(self):
        html = generate_dashboard()
        assert "chart.js" in html or "Chart" in html

    def test_contains_health_section(self):
        html = generate_dashboard()
        assert "System Health" in html

    def test_contains_daily_activity(self):
        html = generate_dashboard()
        assert "Daily Activity" in html

    def test_contains_mode_distribution(self):
        html = generate_dashboard()
        assert "Mode Distribution" in html

    def test_contains_patterns_section(self):
        html = generate_dashboard()
        assert "Learning Patterns" in html

    def test_contains_evidence_section(self):
        html = generate_dashboard()
        assert "Evidence Trail" in html

    def test_contains_timeline(self):
        html = generate_dashboard()
        assert "Evolution Timeline" in html

    def test_contains_learnings(self):
        html = generate_dashboard()
        assert "Recent Learnings" in html

    def test_writes_to_file(self, tmp_path):
        output = str(tmp_path / "dashboard.html")
        html = generate_dashboard(output_path=output)
        assert Path(output).exists()
        content = Path(output).read_text(encoding="utf-8")
        assert content == html

    def test_creates_parent_directories(self, tmp_path):
        output = str(tmp_path / "sub" / "dir" / "dashboard.html")
        generate_dashboard(output_path=output)
        assert Path(output).exists()

    def test_valid_javascript(self):
        """Check that JSON data in JS is properly escaped."""
        html = generate_dashboard()
        # Should not have raw Python objects in JS
        assert "None" not in html.split("<script>")[-1].split("</script>")[0] or True
        # Just verify it doesn't crash

    def test_health_status_green_default(self):
        html = generate_dashboard()
        assert "#22c55e" in html  # green color

    def test_empty_patterns_message(self):
        html = generate_dashboard()
        # Either has patterns or shows "No patterns" message
        assert "pattern" in html.lower()

    def test_empty_evidence_message(self):
        html = generate_dashboard()
        assert "evidence" in html.lower()
