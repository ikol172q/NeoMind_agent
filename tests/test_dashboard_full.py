"""
Comprehensive unit tests for agent/finance/dashboard.py
Tests HTML generation, chart creation, and dashboard rendering.
"""

import pytest
import json
from pathlib import Path
from datetime import datetime, timezone

import sys
sys.path.insert(0, '/sessions/hopeful-magical-rubin/mnt/NeoMind_agent')

from agent.finance.dashboard import (
    FinanceDashboard, build_market_digest_dashboard, _esc
)


class TestEscapeFunction:
    """Tests for HTML escaping."""

    def test_esc_basic(self):
        """Test basic escaping."""
        assert _esc("<test>") == "&lt;test&gt;"
        assert _esc('"quote"') == "&quot;quote&quot;"

    def test_esc_ampersand(self):
        """Test ampersand escaping."""
        assert _esc("A&B") == "A&amp;B"

    def test_esc_multiple(self):
        """Test multiple escape sequences."""
        assert _esc('<div class="test">') == "&lt;div class=&quot;test&quot;&gt;"

    def test_esc_empty(self):
        """Test escaping empty string."""
        assert _esc("") == ""

    def test_esc_normal_text(self):
        """Test normal text passes through."""
        assert _esc("Hello World") == "Hello World"


class TestFinanceDashboardInit:
    """Tests for FinanceDashboard initialization."""

    def test_init_basic(self):
        """Test basic initialization."""
        dash = FinanceDashboard()
        assert dash._sections == []
        assert dash._scripts == []
        assert dash._chart_count == 0
        assert dash._title == "NeoMind Finance Dashboard"

    def test_set_title(self):
        """Test setting title."""
        dash = FinanceDashboard()
        dash.set_title("Custom Title")
        assert dash._title == "Custom Title"

    def test_set_title_with_subtitle(self):
        """Test setting title with subtitle."""
        dash = FinanceDashboard()
        dash.set_title("Title", "Subtitle")
        assert dash._title == "Title"
        assert dash._subtitle == "Subtitle"

    def test_set_title_default_subtitle(self):
        """Test that default subtitle uses current datetime."""
        dash = FinanceDashboard()
        dash.set_title("Title")
        # Should have a timestamp
        assert len(dash._subtitle) > 0
        assert "UTC" in dash._subtitle


class TestKPICards:
    """Tests for KPI cards."""

    def test_add_kpi_cards_single(self):
        """Test adding single KPI card."""
        dash = FinanceDashboard()
        dash.add_kpi_cards([
            {"label": "Portfolio", "value": "$100K"}
        ])

        assert len(dash._sections) == 1
        assert "Portfolio" in dash._sections[0]
        assert "$100K" in dash._sections[0]

    def test_add_kpi_cards_multiple(self):
        """Test adding multiple KPI cards."""
        dash = FinanceDashboard()
        dash.add_kpi_cards([
            {"label": "Label1", "value": "Value1"},
            {"label": "Label2", "value": "Value2"},
            {"label": "Label3", "value": "Value3"},
        ])

        assert len(dash._sections) == 1
        assert "Label1" in dash._sections[0]
        assert "Label2" in dash._sections[0]

    def test_add_kpi_cards_with_trend(self):
        """Test KPI with trend indicator."""
        dash = FinanceDashboard()
        dash.add_kpi_cards([
            {"label": "Return", "value": "+5.2%", "trend": "positive"},
            {"label": "Loss", "value": "-2.1%", "trend": "negative"},
        ])

        assert "positive" in dash._sections[0]
        assert "negative" in dash._sections[0]

    def test_add_kpi_cards_with_detail(self):
        """Test KPI with detail text."""
        dash = FinanceDashboard()
        dash.add_kpi_cards([
            {"label": "Balance", "value": "$50K", "detail": "as of today"}
        ])

        assert "as of today" in dash._sections[0]

    def test_add_kpi_cards_escapes_html(self):
        """Test that KPI escapes HTML."""
        dash = FinanceDashboard()
        dash.add_kpi_cards([
            {"label": "<script>alert(1)</script>", "value": "test"}
        ])

        assert "&lt;script&gt;" in dash._sections[0]


class TestNewsSection:
    """Tests for news section."""

    def test_add_news_section_basic(self):
        """Test adding news section."""
        dash = FinanceDashboard()
        items = [
            {"title": "Test News", "url": "http://example.com"}
        ]
        dash.add_news_section(items)

        assert len(dash._sections) == 1
        assert "Test News" in dash._sections[0]

    def test_add_news_section_multiple(self):
        """Test multiple news items."""
        dash = FinanceDashboard()
        items = [
            {"title": f"News {i}", "url": f"http://example.com/{i}"}
            for i in range(5)
        ]
        dash.add_news_section(items)

        for i in range(5):
            assert f"News {i}" in dash._sections[0]

    def test_add_news_section_impact_levels(self):
        """Test news impact scoring."""
        dash = FinanceDashboard()
        items = [
            {"title": "High Impact", "impact": 8},
            {"title": "Medium Impact", "impact": 5},
            {"title": "Low Impact", "impact": 2},
        ]
        dash.add_news_section(items)

        html = dash._sections[0]
        assert "HIGH" in html
        assert "MED" in html
        assert "LOW" in html

    def test_add_news_section_language_flag(self):
        """Test Chinese language flag."""
        dash = FinanceDashboard()
        items = [
            {"title": "English News", "language": "en"},
            {"title": "Chinese News", "language": "zh"},
        ]
        dash.add_news_section(items)

        assert "🇨🇳" in dash._sections[0]

    def test_add_news_section_limit(self):
        """Test that only first 20 items shown."""
        dash = FinanceDashboard()
        items = [
            {"title": f"News {i}"}
            for i in range(50)
        ]
        dash.add_news_section(items)

        # Count occurrences of "News"
        count = dash._sections[0].count("news-item")
        assert count <= 20


class TestConflicts:
    """Tests for conflict alerts."""

    def test_add_conflicts_basic(self):
        """Test adding conflict alert."""
        dash = FinanceDashboard()
        conflicts = [
            {
                "entity": "AAPL",
                "claim_a": {"source": "Reuters", "claim": "Up 5%"},
                "claim_b": {"source": "Bloomberg", "claim": "Up 3%"},
                "severity": "soft"
            }
        ]
        dash.add_conflicts(conflicts)

        html = dash._sections[0]
        assert "AAPL" in html
        assert "Reuters" in html
        assert "Bloomberg" in html

    def test_add_conflicts_empty(self):
        """Test adding empty conflicts list."""
        dash = FinanceDashboard()
        dash.add_conflicts([])

        assert len(dash._sections) == 0

    def test_add_conflicts_limit(self):
        """Test that only first 10 conflicts shown."""
        dash = FinanceDashboard()
        conflicts = [
            {
                "entity": f"Entity{i}",
                "claim_a": {"source": "A", "claim": "X"},
                "claim_b": {"source": "B", "claim": "Y"},
            }
            for i in range(20)
        ]
        dash.add_conflicts(conflicts)

        count = dash._sections[0].count("conflict-alert")
        assert count <= 10


class TestPredictionTracker:
    """Tests for prediction tracker."""

    def test_add_predictions_basic(self):
        """Test adding predictions."""
        dash = FinanceDashboard()
        predictions = [
            {
                "symbol": "AAPL",
                "direction": "bullish",
                "confidence": 0.8,
                "rationale": "Strong earnings"
            }
        ]
        dash.add_predictions(predictions)

        assert "AAPL" in dash._sections[0]
        assert "bullish" in dash._sections[0]
        assert "80%" in dash._sections[0]

    def test_add_predictions_resolved(self):
        """Test resolved predictions."""
        dash = FinanceDashboard()
        predictions = [
            {
                "symbol": "AAPL",
                "direction": "bullish",
                "resolved": True,
                "correct": True
            }
        ]
        dash.add_predictions(predictions)

        assert "✅" in dash._sections[0]

    def test_add_predictions_accuracy(self):
        """Test accuracy percentage."""
        dash = FinanceDashboard()
        predictions = []
        dash.add_predictions(predictions, accuracy=0.75)

        assert "75%" in dash._sections[0] or "Accuracy" in dash._sections[0]

    def test_add_predictions_limit(self):
        """Test that only first 15 predictions shown."""
        dash = FinanceDashboard()
        predictions = [
            {"symbol": f"SYM{i}", "direction": "bullish"}
            for i in range(30)
        ]
        dash.add_predictions(predictions)

        count = dash._sections[0].count("prediction")
        assert count <= 15


class TestPieChart:
    """Tests for pie chart."""

    def test_add_pie_chart_basic(self):
        """Test adding pie chart."""
        dash = FinanceDashboard()
        data = {"Stocks": 60, "Bonds": 30, "Cash": 10}
        dash.add_pie_chart(data, title="Portfolio")

        assert len(dash._sections) == 1
        assert len(dash._scripts) == 1
        assert "Portfolio" in dash._sections[0]

    def test_add_pie_chart_donut(self):
        """Test donut chart cutout."""
        dash = FinanceDashboard()
        dash.add_pie_chart({"A": 50, "B": 50}, donut=True)

        # Check that script includes cutout
        assert "'60%'" in dash._scripts[0]

    def test_add_pie_chart_pie(self):
        """Test regular pie chart."""
        dash = FinanceDashboard()
        dash.add_pie_chart({"A": 50, "B": 50}, donut=False)

        # Should not have cutout
        assert "0" in dash._scripts[0]

    def test_add_pie_chart_chart_id(self):
        """Test unique chart IDs."""
        dash = FinanceDashboard()
        dash.add_pie_chart({"A": 50}, title="Chart1")
        dash.add_pie_chart({"B": 50}, title="Chart2")

        assert dash._chart_count == 2
        assert "chart_0" in dash._sections[0]
        assert "chart_1" in dash._sections[1]


class TestBarChart:
    """Tests for bar chart."""

    def test_add_bar_chart_basic(self):
        """Test adding bar chart."""
        dash = FinanceDashboard()
        labels = ["Jan", "Feb", "Mar"]
        datasets = [{"label": "Revenue", "data": [10, 20, 30]}]
        dash.add_bar_chart(labels, datasets)

        assert "Revenue" in dash._sections[0]
        assert "Jan" in str(dash._scripts[0])

    def test_add_bar_chart_multiple_datasets(self):
        """Test bar chart with multiple datasets."""
        dash = FinanceDashboard()
        labels = ["A", "B"]
        datasets = [
            {"label": "DS1", "data": [10, 20]},
            {"label": "DS2", "data": [5, 15]}
        ]
        dash.add_bar_chart(labels, datasets)

        assert "DS1" in str(dash._scripts[0])
        assert "DS2" in str(dash._scripts[0])

    def test_add_bar_chart_horizontal(self):
        """Test horizontal bar chart."""
        dash = FinanceDashboard()
        dash.add_bar_chart(["A", "B"], [{"label": "Data", "data": [1, 2]}], horizontal=True)

        # Check for y-axis orientation
        assert "'y'" in dash._scripts[0]


class TestLineChart:
    """Tests for line chart."""

    def test_add_line_chart_basic(self):
        """Test adding line chart."""
        dash = FinanceDashboard()
        labels = ["Day1", "Day2", "Day3"]
        datasets = [{"label": "Price", "data": [100, 105, 103]}]
        dash.add_line_chart(labels, datasets)

        assert "Price" in str(dash._scripts[0])


class TestSourceTrust:
    """Tests for source trust leaderboard."""

    def test_add_source_trust_basic(self):
        """Test adding source trust."""
        dash = FinanceDashboard()
        sources = {
            "reuters": 0.95,
            "bloomberg": 0.90,
            "cnbc": 0.85
        }
        dash.add_source_trust(sources)

        html = dash._sections[0]
        assert "reuters" in html
        assert "0.95" in html

    def test_add_source_trust_color_coding(self):
        """Test source trust color coding."""
        dash = FinanceDashboard()
        sources = {
            "high_trust": 0.95,
            "medium_trust": 0.75,
            "low_trust": 0.45
        }
        dash.add_source_trust(sources)

        # Should have color references
        assert "accent-green" in dash._sections[0]
        assert "accent-yellow" in dash._sections[0]

    def test_add_source_trust_limit(self):
        """Test source trust limit."""
        dash = FinanceDashboard()
        sources = {f"source{i}": 0.5 for i in range(50)}
        dash.add_source_trust(sources)

        count = dash._sections[0].count("trust-row")
        assert count <= 20


class TestWatchlist:
    """Tests for watchlist."""

    def test_add_watchlist_basic(self):
        """Test adding watchlist."""
        dash = FinanceDashboard()
        items = [
            {"symbol": "AAPL", "price": 150, "change": 2.5, "change_pct": 1.5}
        ]
        dash.add_watchlist(items)

        html = dash._sections[0]
        assert "AAPL" in html
        assert "150" in html

    def test_add_watchlist_color_change(self):
        """Test watchlist color coding for changes."""
        dash = FinanceDashboard()
        items = [
            {"symbol": "UP", "change": 5, "change_pct": 2},
            {"symbol": "DOWN", "change": -5, "change_pct": -2},
        ]
        dash.add_watchlist(items)

        html = dash._sections[0]
        assert "positive" in html
        assert "negative" in html


class TestQuantResult:
    """Tests for quant results."""

    def test_add_quant_result_basic(self):
        """Test adding quant result."""
        dash = FinanceDashboard()
        dash.add_quant_result("DCF Value", "125.50", unit="USD")

        assert "DCF Value" in dash._sections[0]
        assert "125.50" in dash._sections[0]

    def test_add_quant_result_formula(self):
        """Test quant result with formula."""
        dash = FinanceDashboard()
        dash.add_quant_result("PE Ratio", "25", formula="Price / EPS")

        assert "Price / EPS" in dash._sections[0]

    def test_add_quant_result_steps(self):
        """Test quant result with steps."""
        dash = FinanceDashboard()
        steps = ["Step 1", "Step 2", "Step 3"]
        dash.add_quant_result("Result", "100", steps=steps)

        for step in steps:
            assert step in dash._sections[0]


class TestRawHTML:
    """Tests for raw HTML insertion."""

    def test_add_raw_html(self):
        """Test adding raw HTML."""
        dash = FinanceDashboard()
        html = "<div>Custom Content</div>"
        dash.add_raw_html(html)

        assert html in dash._sections[0]


class TestColumns:
    """Tests for column layout."""

    def test_start_end_columns(self):
        """Test column start and end."""
        dash = FinanceDashboard()
        dash.start_columns(2)
        dash.end_columns()

        assert len(dash._sections) == 2
        assert "grid-2" in dash._sections[0]


class TestRender:
    """Tests for HTML rendering."""

    def test_render_basic(self):
        """Test basic rendering."""
        dash = FinanceDashboard()
        dash.set_title("Test Dashboard")

        html = dash.render()

        assert "<!DOCTYPE html>" in html
        assert "Test Dashboard" in html
        assert "NeoMind Finance" in html

    def test_render_includes_chart_js(self):
        """Test that Chart.js is included when needed."""
        dash = FinanceDashboard()
        dash.add_pie_chart({"A": 50})

        html = dash.render()
        assert "chart.js" in html.lower()

    def test_render_no_chart_js_when_not_needed(self):
        """Test Chart.js excluded when no charts."""
        dash = FinanceDashboard()
        dash.add_kpi_cards([{"label": "Test", "value": "100"}])

        html = dash.render()
        # Should not include script tag for charts
        assert "chart.js" not in html.lower()

    def test_render_valid_html(self):
        """Test that rendered HTML is valid."""
        dash = FinanceDashboard()
        dash.set_title("Test")
        dash.add_kpi_cards([{"label": "L", "value": "V"}])

        html = dash.render()

        # Basic HTML structure checks
        assert "<html" in html
        assert "</html>" in html
        assert "<body" in html
        assert "</body>" in html


class TestSave:
    """Tests for saving dashboard."""

    def test_save_to_file(self, tmp_path):
        """Test saving dashboard to file."""
        dash = FinanceDashboard()
        dash.set_title("Test")

        filepath = str(tmp_path / "dashboard.html")
        result = dash.save(filepath)

        assert Path(filepath).exists()
        assert result == filepath

    def test_save_creates_directories(self, tmp_path):
        """Test that save creates parent directories."""
        dash = FinanceDashboard()

        filepath = str(tmp_path / "subdir" / "dashboard.html")
        dash.save(filepath)

        assert Path(filepath).exists()

    def test_saved_file_content(self, tmp_path):
        """Test saved file content."""
        dash = FinanceDashboard()
        dash.set_title("My Dashboard")

        filepath = str(tmp_path / "test.html")
        dash.save(filepath)

        content = Path(filepath).read_text()
        assert "My Dashboard" in content
        assert "<!DOCTYPE html>" in content


class TestReset:
    """Tests for dashboard reset."""

    def test_reset_clears_sections(self):
        """Test reset clears sections."""
        dash = FinanceDashboard()
        dash.add_kpi_cards([{"label": "L", "value": "V"}])

        assert len(dash._sections) > 0

        dash.reset()

        assert dash._sections == []
        assert dash._scripts == []
        assert dash._chart_count == 0


class TestBuildMarketDigestDashboard:
    """Tests for convenient factory function."""

    def test_build_basic(self):
        """Test basic digest dashboard building."""
        news = [{"title": "News", "impact": 5}]
        dash = build_market_digest_dashboard(news_items=news)

        assert isinstance(dash, FinanceDashboard)
        assert len(dash._sections) > 0

    def test_build_with_all_components(self):
        """Test building with all components."""
        news = [{"title": "News"}]
        conflicts = [{"entity": "Entity", "claim_a": {"source": "A", "claim": "X"}, "claim_b": {"source": "B", "claim": "Y"}}]
        watchlist = [{"symbol": "SYM", "price": 100}]
        predictions = [{"symbol": "SYM", "direction": "bullish"}]
        portfolio = {"Stocks": 60, "Bonds": 40}
        kpis = [{"label": "KPI", "value": "100"}]

        dash = build_market_digest_dashboard(
            news_items=news,
            conflicts=conflicts,
            watchlist=watchlist,
            predictions=predictions,
            portfolio=portfolio,
            kpis=kpis
        )

        assert isinstance(dash, FinanceDashboard)


class TestEdgeCases:
    """Tests for edge cases."""

    def test_render_empty_dashboard(self):
        """Test rendering empty dashboard."""
        dash = FinanceDashboard()
        html = dash.render()

        assert "<!DOCTYPE html>" in html

    def test_unicode_in_content(self):
        """Test unicode characters."""
        dash = FinanceDashboard()
        dash.set_title("测试 Dashboard 🌍")

        html = dash.render()
        assert "测试" in html
        assert "🌍" in html

    def test_very_large_data(self):
        """Test handling large datasets."""
        dash = FinanceDashboard()
        items = [{"title": f"Item {i}"} for i in range(1000)]
        dash.add_news_section(items)

        html = dash.render()
        assert len(html) > 1000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
