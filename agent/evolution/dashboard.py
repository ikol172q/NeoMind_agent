"""Generate an HTML dashboard from evolution, logging, and evidence data.

Usage:
    from agent.evolution.dashboard import generate_dashboard
    html = generate_dashboard()  # Returns complete HTML string

    # Or from CLI:
    python -m agent.evolution.dashboard  # Writes dashboard.html
"""

import json
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Dict, List, Any, Optional


def collect_metrics() -> Dict[str, Any]:
    """Gather metrics from all sources (auto_evolve, unified_logger, evidence).

    Returns a dictionary with fallback empty data if any source unavailable.
    """
    metrics = {
        "timestamp": datetime.now().isoformat(),
        "health": {},
        "daily_stats": [],
        "mode_distribution": {},
        "patterns": [],
        "evidence_recent": [],
        "evolution_timeline": [],
        "learning_log": [],
    }

    # Try to load evolution state
    try:
        from agent.evolution.auto_evolve import AutoEvolve

        # Guard: only proceed if AutoEvolve is a real class (not a MagicMock)
        if not isinstance(AutoEvolve, type):
            raise TypeError("AutoEvolve is not a real class (possibly mocked)")

        evolve = AutoEvolve()

        # Guard: validate that key attributes are real Path objects
        if not isinstance(getattr(evolve, "feedback_db", None), Path):
            raise TypeError("feedback_db is not a Path (possibly mocked)")

        # Health status
        state = getattr(evolve, "state", {})
        if isinstance(state, dict) and state.get("health"):
            metrics["health"] = state["health"]

        # Timeline of evolution events
        timeline = []
        if isinstance(state, dict):
            if state.get("last_startup_check"):
                timeline.append(("Startup Check", state["last_startup_check"]))
            if state.get("last_daily_audit"):
                timeline.append(("Daily Audit", state["last_daily_audit"]))
            if state.get("last_weekly_retro"):
                timeline.append(("Weekly Retro", state["last_weekly_retro"]))
        metrics["evolution_timeline"] = timeline

        # Recent learnings
        learning_log = getattr(evolve, "learning_log", None)
        if isinstance(learning_log, Path) and learning_log.exists():
            try:
                with open(learning_log, "r") as f:
                    recent_learnings = [
                        json.loads(line) for line in f.readlines()[-20:]
                    ]
                metrics["learning_log"] = recent_learnings
            except Exception:
                pass

        # Patterns from feedback DB
        if isinstance(evolve.feedback_db, Path) and evolve.feedback_db.exists():
            try:
                import sqlite3
                conn = sqlite3.connect(str(evolve.feedback_db), timeout=2.0)
                cursor = conn.cursor()

                cursor.execute("""
                    SELECT pattern_type, pattern_value, count
                    FROM patterns
                    ORDER BY count DESC
                    LIMIT 20
                """)

                for pattern_type, pattern_value, count in cursor.fetchall():
                    metrics["patterns"].append({
                        "type": pattern_type,
                        "value": pattern_value,
                        "count": count,
                    })

                conn.close()
            except Exception:
                pass

    except Exception:
        pass

    # Try to load unified logger stats
    try:
        from agent.logging.unified_logger import get_unified_logger
        logger = get_unified_logger()

        # Get last 7 days of stats
        today = date.today()
        for i in range(7):
            target_date = today - timedelta(days=i)
            try:
                daily = logger.get_daily_stats(target_date)
                if daily["total_events"] > 0:
                    metrics["daily_stats"].insert(0, {
                        "date": daily["date"],
                        "events": daily["total_events"],
                        "llm_calls": daily["by_type"].get("llm_call", 0),
                        "errors": daily["errors"],
                        "commands": daily["total_commands"],
                        "tokens": daily.get("total_tokens", 0),
                    })
            except Exception:
                pass

        # Get mode distribution from latest stats
        try:
            weekly = logger.get_weekly_stats()
            metrics["mode_distribution"] = weekly.get("by_mode", {})
        except Exception:
            pass

    except Exception:
        pass

    # Try to load evidence trail
    try:
        from agent.workflow.evidence import get_evidence_trail
        trail = get_evidence_trail()

        # Get recent evidence
        recent = trail.get_recent(10)
        metrics["evidence_recent"] = recent

    except Exception:
        pass

    return metrics


def generate_dashboard(output_path: Optional[str] = None) -> str:
    """Generate a complete self-contained HTML dashboard.

    Args:
        output_path: Optional file path to write HTML to

    Returns:
        HTML string with embedded CSS/JS
    """
    metrics = collect_metrics()

    # Prepare data for charts
    daily_dates = [d["date"][-5:] for d in metrics["daily_stats"]]  # MM-DD format
    daily_events = [d["events"] for d in metrics["daily_stats"]]
    daily_errors = [d["errors"] for d in metrics["daily_stats"]]
    daily_calls = [d["llm_calls"] for d in metrics["daily_stats"]]

    mode_labels = list(metrics["mode_distribution"].keys())
    mode_values = list(metrics["mode_distribution"].values())

    pattern_labels = [p["value"] for p in metrics["patterns"][:10]]
    pattern_values = [p["count"] for p in metrics["patterns"][:10]]

    # Health status
    health = metrics["health"]
    checks_passed = health.get("checks_passed", 0)
    checks_failed = health.get("checks_failed", 0)
    health_status = "green" if checks_failed == 0 else ("yellow" if checks_failed < 2 else "red")
    health_icon = "✓" if health_status == "green" else ("!" if health_status == "yellow" else "✗")

    # Color for health status
    health_color = {"green": "#22c55e", "yellow": "#eab308", "red": "#ef4444"}.get(health_status, "#22c55e")
    health_text = {"green": "Healthy", "yellow": "Caution", "red": "Issues Detected"}.get(health_status, "Unknown")

    # Build issues HTML
    issues_html = ""
    if health.get("issues"):
        issues_items = "".join([f"<li>{issue}</li>" for issue in health.get("issues", [])])
        issues_html = f'<div style="margin-top: 1.5rem; padding-top: 1.5rem; border-top: 1px solid rgba(148, 163, 184, 0.2);"><strong>Issues:</strong><ul style="margin-top: 0.5rem; list-style: disc; padding-left: 1.5rem;">{issues_items}</ul></div>'

    # Build patterns HTML
    patterns_html = ""
    if metrics["patterns"]:
        patterns_items = "".join([f'''<div>
                    <div style="font-weight: 500; margin-bottom: 0.75rem; color: #94a3b8; text-transform: uppercase; font-size: 0.75rem;">
                        {p["type"].upper()}
                    </div>
                    <div style="font-size: 1.25rem; color: #60a5fa; font-weight: bold;">{p["value"]}</div>
                    <div style="color: #64748b; font-size: 0.875rem; margin-top: 0.25rem;">
                        Seen {p["count"]} time{"s" if p["count"] != 1 else ""}
                    </div>
                </div>''' for p in metrics["patterns"][:6]])
        patterns_html = f'<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1.5rem;">{patterns_items}</div>'
    else:
        patterns_html = '<p style="color: #94a3b8;">No patterns learned yet. Start using the system to develop patterns.</p>'

    # Build evidence HTML
    evidence_html = ""
    if metrics["evidence_recent"]:
        evidence_items = "".join([f'''<div class="evidence-entry {e.get("severity", "info")}">
                    <div style="display: flex; justify-content: space-between; margin-bottom: 0.5rem;">
                        <span style="font-weight: 500;">{e.get("action", "?").upper()}</span>
                        <span style="color: #64748b;">{e.get("ts", "")[:16]}</span>
                    </div>
                    <div style="color: #cbd5e1; font-size: 0.875rem; margin-bottom: 0.5rem;">
                        Input: {e.get("input", "")[:80]}
                    </div>
                    <div style="color: #94a3b8; font-size: 0.875rem;">
                        Output: {e.get("output", "")[:80]}
                    </div>
                </div>''' for e in metrics["evidence_recent"][-10:]])
        evidence_html = evidence_items
    else:
        evidence_html = '<p style="color: #94a3b8;">No evidence entries yet.</p>'

    # Build timeline HTML
    timeline_html = ""
    if metrics["evolution_timeline"]:
        timeline_items = "".join([f'''<div class="timeline-item">
                    <div style="font-weight: 500; color: #60a5fa;">{event}</div>
                    <div class="time">{ts[:19]}</div>
                </div>''' for event, ts in metrics["evolution_timeline"]])
        timeline_html = timeline_items
    else:
        timeline_html = '<p style="color: #94a3b8;">No evolution events recorded yet.</p>'

    # Build learning log HTML
    learning_html = ""
    if metrics["learning_log"]:
        learning_items = "".join([f'''<div style="padding: 0.75rem; border-bottom: 1px solid rgba(148, 163, 184, 0.1); font-size: 0.875rem;">
                    <div style="display: flex; justify-content: space-between; margin-bottom: 0.25rem;">
                        <span class="pattern-tag">{entry.get("type", "unknown")}</span>
                        <span style="color: #64748b;">{entry.get("timestamp", "")[:10]}</span>
                    </div>
                    <div style="color: #cbd5e1;">{entry.get("content", "")[:120]}</div>
                </div>''' for entry in metrics["learning_log"][-20:]])
        learning_html = f'<div style="max-height: 400px; overflow-y: auto;">{learning_items}</div>'
    else:
        learning_html = '<p style="color: #94a3b8;">No learning entries yet.</p>'

    # Build CSS with proper escaping
    css_styles = """
        body {
            background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
            color: #e2e8f0;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        }
        .card {
            background: rgba(30, 41, 59, 0.8);
            border: 1px solid rgba(148, 163, 184, 0.2);
            border-radius: 12px;
            padding: 1.5rem;
            backdrop-filter: blur(10px);
        }
        .header {
            background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
            border-bottom: 2px solid rgba(148, 163, 184, 0.3);
            padding: 2rem;
            margin-bottom: 2rem;
        }
        .metric {
            display: inline-block;
            margin-right: 2rem;
        }
        .metric-value {
            font-size: 1.875rem;
            font-weight: bold;
            color: #60a5fa;
        }
        .metric-label {
            font-size: 0.875rem;
            color: #94a3b8;
            margin-top: 0.25rem;
        }
        .health-indicator {
            display: inline-block;
            width: 16px;
            height: 16px;
            border-radius: 50%;
            margin-right: 0.5rem;
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.7; }
        }
        .chart-container {
            position: relative;
            height: 300px;
            margin-bottom: 2rem;
        }
        .evidence-entry {
            background: rgba(15, 23, 42, 0.5);
            border-left: 3px solid #60a5fa;
            padding: 1rem;
            margin-bottom: 1rem;
            border-radius: 6px;
            font-size: 0.875rem;
        }
        .evidence-entry.critical {
            border-left-color: #ef4444;
        }
        .evidence-entry.warning {
            border-left-color: #eab308;
        }
        .pattern-tag {
            display: inline-block;
            background: rgba(96, 165, 250, 0.2);
            color: #60a5fa;
            padding: 0.25rem 0.75rem;
            border-radius: 9999px;
            font-size: 0.75rem;
            margin-right: 0.5rem;
            margin-bottom: 0.5rem;
        }
        .timeline-item {
            padding: 0.5rem 0;
            border-left: 2px solid rgba(148, 163, 184, 0.2);
            padding-left: 1rem;
            margin-left: 0.5rem;
        }
        .timeline-item .time {
            color: #94a3b8;
            font-size: 0.875rem;
        }
    """

    # Build JavaScript data
    daily_dates_json = json.dumps(daily_dates)
    daily_calls_json = json.dumps(daily_calls)
    daily_errors_json = json.dumps(daily_errors)
    mode_labels_json = json.dumps(mode_labels)
    mode_values_json = json.dumps(mode_values)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NeoMind Evolution Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
{css_styles}
    </style>
</head>
<body>
    <div class="header">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <div>
                <h1 style="font-size: 2.25rem; font-weight: bold; margin-bottom: 0.5rem;">
                    📊 NeoMind Evolution Dashboard
                </h1>
                <p style="color: #94a3b8;">Real-time metrics and performance analytics</p>
            </div>
            <div class="metric">
                <div style="font-size: 0.875rem; color: #94a3b8; margin-bottom: 0.5rem;">Last Updated</div>
                <div style="font-size: 1.125rem; color: #60a5fa;">{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div>
            </div>
        </div>
    </div>

    <div class="container mx-auto px-4 pb-8">
        <!-- Health Status -->
        <div class="card mb-8">
            <h2 style="font-size: 1.5rem; font-weight: bold; margin-bottom: 1.5rem; display: flex; align-items: center;">
                <span class="health-indicator" style="background: {health_color};"></span>
                System Health
            </h2>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1.5rem;">
                <div>
                    <div class="metric-value">{health_icon}</div>
                    <div class="metric-label">Status</div>
                    <div style="color: {health_color}; font-weight: 500; margin-top: 0.5rem;">
                        {health_text}
                    </div>
                </div>
                <div>
                    <div class="metric-value">{checks_passed}</div>
                    <div class="metric-label">Checks Passed</div>
                </div>
                <div>
                    <div class="metric-value">{checks_failed}</div>
                    <div class="metric-label">Issues</div>
                </div>
                <div>
                    <div class="metric-value">{health.get("last_successful_run", "N/A")[:10] if health.get("last_successful_run") else "N/A"}</div>
                    <div class="metric-label">Last Check</div>
                </div>
            </div>
            {issues_html}
        </div>

        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(400px, 1fr)); gap: 2rem; margin-bottom: 2rem;">
            <!-- Daily Activity Chart -->
            <div class="card">
                <h2 style="font-size: 1.25rem; font-weight: bold; margin-bottom: 1.5rem;">📈 Daily Activity (7 Days)</h2>
                <div class="chart-container">
                    <canvas id="dailyChart"></canvas>
                </div>
            </div>

            <!-- Mode Distribution -->
            <div class="card">
                <h2 style="font-size: 1.25rem; font-weight: bold; margin-bottom: 1.5rem;">⚙️ Mode Distribution</h2>
                <div class="chart-container">
                    <canvas id="modeChart"></canvas>
                </div>
            </div>
        </div>

        <!-- Top Patterns -->
        <div class="card mb-8">
            <h2 style="font-size: 1.25rem; font-weight: bold; margin-bottom: 1.5rem;">🧠 Top Learning Patterns</h2>
            {patterns_html}
        </div>

        <!-- Recent Evidence Trail -->
        <div class="card mb-8">
            <h2 style="font-size: 1.25rem; font-weight: bold; margin-bottom: 1.5rem;">📋 Recent Evidence Trail</h2>
            {evidence_html}
        </div>

        <!-- Evolution Timeline -->
        <div class="card mb-8">
            <h2 style="font-size: 1.25rem; font-weight: bold; margin-bottom: 1.5rem;">⏱️ Evolution Timeline</h2>
            {timeline_html}
        </div>

        <!-- Learning Log -->
        <div class="card">
            <h2 style="font-size: 1.25rem; font-weight: bold; margin-bottom: 1.5rem;">🎓 Recent Learnings</h2>
            {learning_html}
        </div>
    </div>

    <script>
        // Daily Activity Chart
        const dailyCtx = document.getElementById('dailyChart');
        if (dailyCtx) {{
            new Chart(dailyCtx, {{
                type: 'bar',
                data: {{
                    labels: {daily_dates_json},
                    datasets: [
                        {{
                            label: 'LLM Calls',
                            data: {daily_calls_json},
                            backgroundColor: 'rgba(96, 165, 250, 0.7)',
                            borderColor: 'rgba(96, 165, 250, 1)',
                            borderWidth: 2,
                        }},
                        {{
                            label: 'Errors',
                            data: {daily_errors_json},
                            backgroundColor: 'rgba(239, 68, 68, 0.7)',
                            borderColor: 'rgba(239, 68, 68, 1)',
                            borderWidth: 2,
                        }},
                    ]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {{
                        legend: {{
                            labels: {{ color: '#e2e8f0' }}
                        }}
                    }},
                    scales: {{
                        y: {{
                            ticks: {{ color: '#94a3b8' }},
                            grid: {{ color: 'rgba(148, 163, 184, 0.1)' }},
                        }},
                        x: {{
                            ticks: {{ color: '#94a3b8' }},
                            grid: {{ color: 'rgba(148, 163, 184, 0.1)' }},
                        }},
                    }}
                }}
            }});
        }}

        // Mode Distribution Chart
        const modeCtx = document.getElementById('modeChart');
        if (modeCtx && {mode_labels_json} && {mode_labels_json}.length > 0) {{
            new Chart(modeCtx, {{
                type: 'doughnut',
                data: {{
                    labels: {mode_labels_json},
                    datasets: [{{
                        data: {mode_values_json},
                        backgroundColor: [
                            'rgba(96, 165, 250, 0.8)',
                            'rgba(34, 197, 94, 0.8)',
                            'rgba(249, 115, 22, 0.8)',
                            'rgba(168, 85, 247, 0.8)',
                            'rgba(236, 72, 153, 0.8)',
                        ],
                        borderColor: [
                            'rgba(96, 165, 250, 1)',
                            'rgba(34, 197, 94, 1)',
                            'rgba(249, 115, 22, 1)',
                            'rgba(168, 85, 247, 1)',
                            'rgba(236, 72, 153, 1)',
                        ],
                        borderWidth: 2,
                    }}]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {{
                        legend: {{
                            labels: {{ color: '#e2e8f0' }}
                        }}
                    }}
                }}
            }});
        }}
    </script>
</body>
</html>
"""

    # Write to file if output_path provided
    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)

    return html


if __name__ == "__main__":
    import sys

    # Default to ~/.neomind/dashboard.html
    output_path = Path.home() / ".neomind" / "dashboard.html"

    if len(sys.argv) > 1:
        output_path = Path(sys.argv[1])

    html = generate_dashboard(str(output_path))
    print(f"Dashboard generated: {output_path}")
