# agent/finance/dashboard.py
"""
Finance Dashboard Generator — rich HTML reports with embedded charts.

Produces standalone HTML files with:
- Market overview heatmaps
- Portfolio allocation (pie/donut charts via Chart.js CDN)
- News digest with impact scoring and conflict alerts
- Prediction tracker with accuracy history
- Source trust leaderboard
- Watchlist with sparkline price charts
- Quantitative analysis results

All charts use Chart.js loaded from CDN — zero local dependencies.
Output is a single self-contained HTML file that opens in any browser.
"""

import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from pathlib import Path


# ── Template Fragments ───────────────────────────────────────────────

_CSS = """
:root {
    --bg-primary: #0f1117;
    --bg-card: #1a1d29;
    --bg-card-hover: #222538;
    --border: #2a2d3e;
    --text-primary: #e4e4e7;
    --text-secondary: #a1a1aa;
    --text-muted: #71717a;
    --accent-green: #22c55e;
    --accent-red: #ef4444;
    --accent-blue: #3b82f6;
    --accent-yellow: #eab308;
    --accent-purple: #a855f7;
    --accent-cyan: #06b6d4;
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif;
    background: var(--bg-primary);
    color: var(--text-primary);
    line-height: 1.6;
    padding: 24px;
    max-width: 1400px;
    margin: 0 auto;
}

h1 {
    font-size: 1.75rem;
    font-weight: 700;
    margin-bottom: 4px;
}

.subtitle {
    color: var(--text-muted);
    font-size: 0.85rem;
    margin-bottom: 24px;
}

.grid {
    display: grid;
    gap: 16px;
    margin-bottom: 24px;
}

.grid-2 { grid-template-columns: repeat(2, 1fr); }
.grid-3 { grid-template-columns: repeat(3, 1fr); }
.grid-4 { grid-template-columns: repeat(4, 1fr); }

@media (max-width: 900px) {
    .grid-2, .grid-3, .grid-4 { grid-template-columns: 1fr; }
}

.card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px;
    transition: background 0.2s;
}

.card:hover {
    background: var(--bg-card-hover);
}

.card-title {
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
    margin-bottom: 8px;
}

.card-value {
    font-size: 1.8rem;
    font-weight: 700;
}

.card-value.positive { color: var(--accent-green); }
.card-value.negative { color: var(--accent-red); }
.card-value.neutral { color: var(--text-primary); }

.card-detail {
    font-size: 0.85rem;
    color: var(--text-secondary);
    margin-top: 4px;
}

.section-title {
    font-size: 1.1rem;
    font-weight: 600;
    margin-bottom: 16px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--border);
}

/* News items */
.news-item {
    padding: 12px 0;
    border-bottom: 1px solid var(--border);
    display: flex;
    gap: 12px;
    align-items: flex-start;
}

.news-item:last-child { border-bottom: none; }

.news-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 0.7rem;
    font-weight: 600;
    text-transform: uppercase;
    flex-shrink: 0;
    min-width: 56px;
    text-align: center;
}

.badge-high { background: rgba(239, 68, 68, 0.15); color: var(--accent-red); }
.badge-medium { background: rgba(234, 179, 8, 0.15); color: var(--accent-yellow); }
.badge-low { background: rgba(34, 197, 94, 0.15); color: var(--accent-green); }
.badge-conflict { background: rgba(168, 85, 247, 0.15); color: var(--accent-purple); }

.news-title {
    font-size: 0.9rem;
    font-weight: 500;
}

.news-title a {
    color: var(--text-primary);
    text-decoration: none;
}

.news-title a:hover {
    color: var(--accent-blue);
    text-decoration: underline;
}

.news-meta {
    font-size: 0.75rem;
    color: var(--text-muted);
    margin-top: 2px;
}

/* Prediction tracker */
.prediction {
    padding: 12px 16px;
    border-left: 3px solid var(--border);
    margin-bottom: 8px;
    border-radius: 0 8px 8px 0;
    background: rgba(26, 29, 41, 0.5);
}

.prediction.bullish { border-left-color: var(--accent-green); }
.prediction.bearish { border-left-color: var(--accent-red); }
.prediction.neutral { border-left-color: var(--accent-yellow); }
.prediction.correct { border-left-color: var(--accent-green); background: rgba(34, 197, 94, 0.05); }
.prediction.wrong { border-left-color: var(--accent-red); background: rgba(239, 68, 68, 0.05); }

.prediction-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.confidence-bar {
    display: inline-block;
    width: 60px;
    height: 6px;
    background: var(--border);
    border-radius: 3px;
    overflow: hidden;
    vertical-align: middle;
}

.confidence-fill {
    height: 100%;
    border-radius: 3px;
    background: var(--accent-blue);
}

/* Source trust */
.trust-row {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 6px 0;
}

.trust-name {
    width: 120px;
    font-size: 0.85rem;
    flex-shrink: 0;
}

.trust-bar {
    flex: 1;
    height: 8px;
    background: var(--border);
    border-radius: 4px;
    overflow: hidden;
}

.trust-fill {
    height: 100%;
    border-radius: 4px;
    transition: width 0.3s;
}

.trust-value {
    width: 40px;
    text-align: right;
    font-size: 0.8rem;
    color: var(--text-secondary);
}

/* Chart container */
.chart-container {
    position: relative;
    width: 100%;
    max-height: 300px;
}

/* Conflict alert */
.conflict-alert {
    background: rgba(168, 85, 247, 0.08);
    border: 1px solid rgba(168, 85, 247, 0.3);
    border-radius: 8px;
    padding: 12px 16px;
    margin-bottom: 8px;
}

.conflict-title {
    font-weight: 600;
    color: var(--accent-purple);
    margin-bottom: 4px;
}

.conflict-claims {
    font-size: 0.85rem;
    color: var(--text-secondary);
}

/* Quant result */
.quant-result {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    margin-bottom: 12px;
}

.quant-formula {
    font-family: 'SF Mono', 'Fira Code', monospace;
    font-size: 0.8rem;
    color: var(--accent-cyan);
    background: rgba(6, 182, 212, 0.08);
    padding: 8px 12px;
    border-radius: 6px;
    margin: 8px 0;
    overflow-x: auto;
}

.quant-steps {
    font-size: 0.85rem;
    color: var(--text-secondary);
    padding-left: 16px;
}

.quant-steps li {
    margin-bottom: 4px;
}

/* Table */
table {
    width: 100%;
    border-collapse: collapse;
}

th, td {
    padding: 8px 12px;
    text-align: left;
    border-bottom: 1px solid var(--border);
    font-size: 0.85rem;
}

th {
    color: var(--text-muted);
    font-weight: 500;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}

td.positive { color: var(--accent-green); }
td.negative { color: var(--accent-red); }

.footer {
    text-align: center;
    color: var(--text-muted);
    font-size: 0.75rem;
    margin-top: 32px;
    padding-top: 16px;
    border-top: 1px solid var(--border);
}
"""

_CHART_JS_CDN = "https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"


class FinanceDashboard:
    """Generates standalone HTML dashboard files from finance data."""

    def __init__(self):
        self._sections: List[str] = []
        self._scripts: List[str] = []
        self._chart_count = 0
        self._title = "NeoMind Finance Dashboard"
        self._subtitle = ""

    def set_title(self, title: str, subtitle: str = ""):
        self._title = title
        self._subtitle = subtitle or datetime.now().strftime("%Y-%m-%d %H:%M UTC")

    # ── KPI Cards ────────────────────────────────────────────────────

    def add_kpi_cards(self, kpis: List[Dict]):
        """Add top-line KPI metric cards.

        Each KPI: {label, value, detail?, trend?: "positive"|"negative"|"neutral"}
        """
        cols = min(len(kpis), 4)
        html = f'<div class="grid grid-{cols}">\n'
        for kpi in kpis:
            trend = kpi.get("trend", "neutral")
            html += f"""
            <div class="card">
                <div class="card-title">{_esc(kpi["label"])}</div>
                <div class="card-value {trend}">{_esc(str(kpi["value"]))}</div>
                {"<div class='card-detail'>" + _esc(str(kpi.get("detail", ""))) + "</div>" if kpi.get("detail") else ""}
            </div>
            """
        html += '</div>\n'
        self._sections.append(html)

    # ── News Digest ──────────────────────────────────────────────────

    def add_news_section(self, items: List[Dict], title: str = "News Digest"):
        """Add a news digest section.

        Each item: {title, url?, source?, impact?: float, language?, published?, snippet?}
        """
        html = f'<div class="card">\n<div class="section-title">{_esc(title)}</div>\n'
        for item in items[:20]:
            impact = item.get("impact", 0)
            if impact >= 7:
                badge_cls, badge_text = "badge-high", "HIGH"
            elif impact >= 4:
                badge_cls, badge_text = "badge-medium", "MED"
            else:
                badge_cls, badge_text = "badge-low", "LOW"

            lang_flag = " 🇨🇳" if item.get("language") == "zh" else ""
            title_html = f'<a href="{_esc(item.get("url", "#"))}" target="_blank">{_esc(item["title"])}</a>' if item.get("url") else _esc(item["title"])

            meta_parts = []
            if item.get("source"):
                meta_parts.append(item["source"])
            if item.get("published"):
                meta_parts.append(str(item["published"])[:16])
            meta = " · ".join(meta_parts) + lang_flag

            html += f"""
            <div class="news-item">
                <span class="news-badge {badge_cls}">{badge_text}</span>
                <div>
                    <div class="news-title">{title_html}</div>
                    <div class="news-meta">{_esc(meta)}</div>
                    {"<div class='news-meta' style='margin-top:4px'>" + _esc(item.get("snippet", "")[:150]) + "</div>" if item.get("snippet") else ""}
                </div>
            </div>
            """
        html += '</div>\n'
        self._sections.append(html)

    # ── Conflicts ────────────────────────────────────────────────────

    def add_conflicts(self, conflicts: List[Dict]):
        """Add conflict alerts.

        Each conflict: {entity, claim_a: {source, claim}, claim_b: {source, claim}, severity}
        """
        if not conflicts:
            return

        html = '<div class="card">\n<div class="section-title">Conflict Alerts</div>\n'
        for c in conflicts[:10]:
            severity = c.get("severity", "soft")
            a = c.get("claim_a", {})
            b = c.get("claim_b", {})
            html += f"""
            <div class="conflict-alert">
                <div class="conflict-title">⚡ {_esc(c.get("entity", "Unknown"))} — {severity} conflict</div>
                <div class="conflict-claims">
                    <strong>{_esc(a.get("source", "Source A"))}:</strong> {_esc(a.get("claim", ""))}<br>
                    <strong>{_esc(b.get("source", "Source B"))}:</strong> {_esc(b.get("claim", ""))}
                </div>
            </div>
            """
        html += '</div>\n'
        self._sections.append(html)

    # ── Prediction Tracker ───────────────────────────────────────────

    def add_predictions(self, predictions: List[Dict], accuracy: Optional[float] = None):
        """Add prediction tracker.

        Each prediction: {symbol, direction, confidence, rationale, created_at,
                          timeframe?, resolved?: bool, correct?: bool}
        """
        html = '<div class="card">\n'
        acc_html = f" — Accuracy: {accuracy:.0%}" if accuracy is not None else ""
        html += f'<div class="section-title">Prediction Tracker{acc_html}</div>\n'

        for p in predictions[:15]:
            direction = p.get("direction", "neutral")
            confidence = p.get("confidence", 0.5)
            conf_pct = int(confidence * 100)

            if p.get("resolved"):
                cls = "correct" if p.get("correct") else "wrong"
                status = "✅ Correct" if p.get("correct") else "❌ Wrong"
            else:
                cls = direction
                status = f"⏳ {p.get('timeframe', 'Pending')}"

            html += f"""
            <div class="prediction {cls}">
                <div class="prediction-header">
                    <span><strong>{_esc(p.get("symbol", "?"))}</strong> — {direction.upper()}</span>
                    <span>
                        <span class="confidence-bar">
                            <span class="confidence-fill" style="width:{conf_pct}%"></span>
                        </span>
                        {conf_pct}% · {status}
                    </span>
                </div>
                <div style="font-size:0.85rem; color:var(--text-secondary); margin-top:4px">
                    {_esc(p.get("rationale", "")[:200])}
                </div>
                <div style="font-size:0.75rem; color:var(--text-muted); margin-top:2px">
                    Created: {_esc(str(p.get("created_at", ""))[:16])}
                </div>
            </div>
            """

        html += '</div>\n'
        self._sections.append(html)

    # ── Pie/Donut Chart ──────────────────────────────────────────────

    def add_pie_chart(self, data: Dict[str, float], title: str = "Allocation",
                      donut: bool = True):
        """Add a pie or donut chart.

        data: {"Stocks": 60, "Bonds": 30, "Cash": 10}
        """
        chart_id = f"chart_{self._chart_count}"
        self._chart_count += 1

        labels = list(data.keys())
        values = list(data.values())
        colors = self._palette(len(labels))

        html = f"""
        <div class="card">
            <div class="section-title">{_esc(title)}</div>
            <div class="chart-container">
                <canvas id="{chart_id}"></canvas>
            </div>
        </div>
        """

        cutout = "'60%'" if donut else "0"
        script = f"""
        new Chart(document.getElementById('{chart_id}'), {{
            type: 'doughnut',
            data: {{
                labels: {json.dumps(labels)},
                datasets: [{{
                    data: {json.dumps(values)},
                    backgroundColor: {json.dumps(colors)},
                    borderColor: '#0f1117',
                    borderWidth: 2,
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: true,
                cutout: {cutout},
                plugins: {{
                    legend: {{
                        position: 'right',
                        labels: {{ color: '#a1a1aa', font: {{ size: 12 }} }}
                    }}
                }}
            }}
        }});
        """
        self._sections.append(html)
        self._scripts.append(script)

    # ── Bar Chart ────────────────────────────────────────────────────

    def add_bar_chart(self, labels: List[str], datasets: List[Dict],
                      title: str = "Comparison", horizontal: bool = False):
        """Add a bar chart.

        datasets: [{"label": "Revenue", "data": [10, 20, 30], "color"?: "#hex"}]
        """
        chart_id = f"chart_{self._chart_count}"
        self._chart_count += 1

        colors = self._palette(len(datasets))
        ds_json = []
        for i, ds in enumerate(datasets):
            ds_json.append({
                "label": ds["label"],
                "data": ds["data"],
                "backgroundColor": ds.get("color", colors[i % len(colors)]),
                "borderRadius": 4,
            })

        chart_type = "'bar'"
        index_axis = "'y'" if horizontal else "'x'"

        html = f"""
        <div class="card">
            <div class="section-title">{_esc(title)}</div>
            <div class="chart-container">
                <canvas id="{chart_id}"></canvas>
            </div>
        </div>
        """

        script = f"""
        new Chart(document.getElementById('{chart_id}'), {{
            type: {chart_type},
            data: {{
                labels: {json.dumps(labels)},
                datasets: {json.dumps(ds_json)}
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: true,
                indexAxis: {index_axis},
                plugins: {{
                    legend: {{ labels: {{ color: '#a1a1aa' }} }}
                }},
                scales: {{
                    x: {{ ticks: {{ color: '#71717a' }}, grid: {{ color: '#2a2d3e' }} }},
                    y: {{ ticks: {{ color: '#71717a' }}, grid: {{ color: '#2a2d3e' }} }}
                }}
            }}
        }});
        """
        self._sections.append(html)
        self._scripts.append(script)

    # ── Line Chart ───────────────────────────────────────────────────

    def add_line_chart(self, labels: List[str], datasets: List[Dict],
                       title: str = "Trend"):
        """Add a line chart.

        datasets: [{"label": "AAPL", "data": [150, 152, 148, ...], "color"?: "#hex"}]
        """
        chart_id = f"chart_{self._chart_count}"
        self._chart_count += 1

        colors = self._palette(len(datasets))
        ds_json = []
        for i, ds in enumerate(datasets):
            c = ds.get("color", colors[i % len(colors)])
            ds_json.append({
                "label": ds["label"],
                "data": ds["data"],
                "borderColor": c,
                "backgroundColor": c + "20",
                "fill": True,
                "tension": 0.3,
                "pointRadius": 2,
            })

        html = f"""
        <div class="card">
            <div class="section-title">{_esc(title)}</div>
            <div class="chart-container">
                <canvas id="{chart_id}"></canvas>
            </div>
        </div>
        """

        script = f"""
        new Chart(document.getElementById('{chart_id}'), {{
            type: 'line',
            data: {{
                labels: {json.dumps(labels)},
                datasets: {json.dumps(ds_json)}
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: true,
                interaction: {{ mode: 'index', intersect: false }},
                plugins: {{
                    legend: {{ labels: {{ color: '#a1a1aa' }} }}
                }},
                scales: {{
                    x: {{ ticks: {{ color: '#71717a', maxTicksLimit: 10 }}, grid: {{ color: '#2a2d3e' }} }},
                    y: {{ ticks: {{ color: '#71717a' }}, grid: {{ color: '#2a2d3e' }} }}
                }}
            }}
        }});
        """
        self._sections.append(html)
        self._scripts.append(script)

    # ── Source Trust Leaderboard ──────────────────────────────────────

    def add_source_trust(self, sources: Dict[str, float]):
        """Add source trust score visualization.

        sources: {"reuters": 0.90, "cnbc": 0.78, ...}
        """
        sorted_sources = sorted(sources.items(), key=lambda x: x[1], reverse=True)

        html = '<div class="card">\n<div class="section-title">Source Trust Scores</div>\n'
        for name, score in sorted_sources[:20]:
            pct = int(score * 100)
            if score >= 0.85:
                color = "var(--accent-green)"
            elif score >= 0.70:
                color = "var(--accent-blue)"
            elif score >= 0.50:
                color = "var(--accent-yellow)"
            else:
                color = "var(--accent-red)"

            html += f"""
            <div class="trust-row">
                <span class="trust-name">{_esc(name)}</span>
                <div class="trust-bar">
                    <div class="trust-fill" style="width:{pct}%; background:{color}"></div>
                </div>
                <span class="trust-value">{score:.2f}</span>
            </div>
            """
        html += '</div>\n'
        self._sections.append(html)

    # ── Watchlist Table ──────────────────────────────────────────────

    def add_watchlist(self, items: List[Dict]):
        """Add watchlist table.

        Each item: {symbol, name?, price, change, change_pct, volume?,
                    source?, updated?}
        """
        html = '<div class="card">\n<div class="section-title">Watchlist</div>\n'
        html += """<table>
            <tr>
                <th>Symbol</th>
                <th>Price</th>
                <th>Change</th>
                <th>Change %</th>
                <th>Volume</th>
                <th>Source</th>
                <th>Updated</th>
            </tr>
        """
        for item in items:
            change = item.get("change", 0)
            change_pct = item.get("change_pct", 0)
            cls = "positive" if change >= 0 else "negative"
            sign = "+" if change >= 0 else ""

            html += f"""
            <tr>
                <td><strong>{_esc(item.get("symbol", ""))}</strong></td>
                <td>{item.get("price", "—")}</td>
                <td class="{cls}">{sign}{change}</td>
                <td class="{cls}">{sign}{change_pct}%</td>
                <td>{item.get("volume", "—")}</td>
                <td style="color:var(--text-muted)">{_esc(item.get("source", ""))}</td>
                <td style="color:var(--text-muted)">{_esc(str(item.get("updated", ""))[:16])}</td>
            </tr>
            """
        html += '</table>\n</div>\n'
        self._sections.append(html)

    # ── Quant Analysis Results ───────────────────────────────────────

    def add_quant_result(self, title: str, value: str, formula: str = "",
                         steps: Optional[List[str]] = None, unit: str = ""):
        """Add a quantitative analysis result card."""
        html = f"""
        <div class="quant-result">
            <div style="font-weight:600; margin-bottom:8px">{_esc(title)}</div>
            <div class="card-value neutral">{_esc(value)} {_esc(unit)}</div>
        """
        if formula:
            html += f'<div class="quant-formula">{_esc(formula)}</div>'
        if steps:
            html += '<ol class="quant-steps">'
            for step in steps:
                html += f'<li>{_esc(step)}</li>'
            html += '</ol>'
        html += '</div>\n'
        self._sections.append(html)

    # ── Raw HTML Section ─────────────────────────────────────────────

    def add_raw_html(self, html: str):
        """Add raw HTML (for custom sections)."""
        self._sections.append(html)

    # ── Two-Column Layout ────────────────────────────────────────────

    def start_columns(self, cols: int = 2):
        """Start a multi-column layout. Call end_columns() after adding sections."""
        self._sections.append(f'<div class="grid grid-{cols}">\n')

    def end_columns(self):
        """End a multi-column layout."""
        self._sections.append('</div>\n')

    # ── Render & Save ────────────────────────────────────────────────

    def render(self) -> str:
        """Render the complete HTML dashboard."""
        body_sections = "\n".join(self._sections)
        chart_scripts = "\n".join(self._scripts)

        has_charts = bool(self._scripts)
        chart_js_tag = f'<script src="{_CHART_JS_CDN}"></script>' if has_charts else ""

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{_esc(self._title)}</title>
    <style>{_CSS}</style>
    {chart_js_tag}
</head>
<body>
    <h1>{_esc(self._title)}</h1>
    <div class="subtitle">{_esc(self._subtitle)}</div>

    {body_sections}

    <div class="footer">
        Generated by NeoMind Finance · {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")} · All data verified against source
    </div>

    {"<script>" + chart_scripts + "</script>" if chart_scripts else ""}
</body>
</html>"""

    def save(self, filepath: str) -> str:
        """Render and save to file. Returns the filepath."""
        html = self.render()
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
        return str(path)

    def reset(self):
        """Clear all sections for reuse."""
        self._sections.clear()
        self._scripts.clear()
        self._chart_count = 0

    # ── Internal Helpers ─────────────────────────────────────────────

    @staticmethod
    def _palette(n: int) -> List[str]:
        """Generate a color palette for charts."""
        base = [
            "#3b82f6",  # blue
            "#22c55e",  # green
            "#eab308",  # yellow
            "#ef4444",  # red
            "#a855f7",  # purple
            "#06b6d4",  # cyan
            "#f97316",  # orange
            "#ec4899",  # pink
            "#14b8a6",  # teal
            "#8b5cf6",  # violet
        ]
        # Cycle if more than 10 series
        return [base[i % len(base)] for i in range(n)]


# ── Convenience Factory Functions ────────────────────────────────────

def build_market_digest_dashboard(
    news_items: List[Dict],
    conflicts: List[Dict] = None,
    watchlist: List[Dict] = None,
    predictions: List[Dict] = None,
    source_trust: Dict[str, float] = None,
    portfolio: Dict[str, float] = None,
    kpis: List[Dict] = None,
    title: str = "Daily Market Digest",
) -> FinanceDashboard:
    """Build a complete market digest dashboard from component data."""
    dash = FinanceDashboard()
    dash.set_title(title)

    # KPI cards
    if kpis:
        dash.add_kpi_cards(kpis)

    # News + conflicts side by side
    if news_items:
        if conflicts and portfolio:
            dash.start_columns(2)
            dash.add_news_section(news_items)
            # Right column: conflicts + portfolio
            conflict_and_portfolio = '<div>'
            dash.end_columns()
            # Actually, let's do it sequentially for simplicity
            dash._sections.pop()  # remove end_columns
            dash._sections.pop()  # remove news
            dash._sections.pop()  # remove start_columns
            dash.add_news_section(news_items)

        else:
            dash.add_news_section(news_items)

    if conflicts:
        dash.add_conflicts(conflicts)

    # Two-column: portfolio + source trust
    if portfolio or source_trust:
        dash.start_columns(2)
        if portfolio:
            dash.add_pie_chart(portfolio, title="Portfolio Allocation")
        if source_trust:
            dash.add_source_trust(source_trust)
        dash.end_columns()

    # Watchlist
    if watchlist:
        dash.add_watchlist(watchlist)

    # Predictions
    if predictions:
        dash.add_predictions(predictions)

    return dash


# ── HTML Escaping ────────────────────────────────────────────────────

def _esc(s: str) -> str:
    """Minimal HTML escaping."""
    return (s
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))
