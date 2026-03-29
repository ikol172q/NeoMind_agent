"""Log command formatting helpers.

Extracted from core.py (Tier 2D). Pure formatting functions
for the /logs command output.

Created: 2026-03-28 (Tier 2D)
"""

from __future__ import annotations

from typing import Optional


def format_log_stats(stats: dict, period: str = "today") -> str:
    """Format daily log statistics."""
    lines = [
        f"📊 Log Statistics - {period.upper()}",
        f"  Date: {stats.get('date', 'N/A')}",
        f"  Total Events: {stats.get('total_events', 0)}",
        f"  LLM Calls: {stats.get('by_type', {}).get('llm_call', 0)}",
        f"  Commands: {stats.get('total_commands', 0)}",
        f"  Errors: {stats.get('errors', 0)}",
        f"  Total Tokens: {stats.get('total_tokens', 0):,}",
        "",
    ]

    by_mode = stats.get('by_mode', {})
    if by_mode:
        lines.append("  By Mode:")
        for mode, count in sorted(by_mode.items(), key=lambda x: -x[1]):
            lines.append(f"    {mode}: {count}")

    by_type = stats.get('by_type', {})
    if by_type:
        lines.append("")
        lines.append("  By Type:")
        for log_type, count in sorted(by_type.items(), key=lambda x: -x[1]):
            lines.append(f"    {log_type}: {count}")

    if stats.get('log_file'):
        lines.append("")
        lines.append(f"  Log File: {stats['log_file']}")
        size_kb = stats.get('log_size_bytes', 0) / 1024
        lines.append(f"  Log Size: {size_kb:.1f} KB")

    return "\n".join(lines)


def format_log_weekly_stats(stats: dict) -> str:
    """Format weekly log statistics."""
    lines = [
        f"📊 Weekly Log Statistics",
        f"  Period: {stats.get('period', 'N/A')}",
        f"  Total Events: {stats.get('total_events', 0):,}",
        f"  LLM Calls: {stats.get('by_type', {}).get('llm_call', 0)}",
        f"  Commands: {stats.get('total_commands', 0)}",
        f"  Errors: {stats.get('total_errors', 0)}",
        f"  Total Tokens: {stats.get('total_tokens', 0):,}",
        f"  Days with Activity: {stats.get('days_with_activity', 0)}/7",
        "",
    ]

    by_mode = stats.get('by_mode', {})
    if by_mode:
        lines.append("  By Mode:")
        for mode, count in sorted(by_mode.items(), key=lambda x: -x[1]):
            lines.append(f"    {mode}: {count}")

    by_type = stats.get('by_type', {})
    if by_type:
        lines.append("")
        lines.append("  By Type:")
        for log_type, count in sorted(by_type.items(), key=lambda x: -x[1]):
            lines.append(f"    {log_type}: {count}")

    return "\n".join(lines)


def format_log_search_results(results: list, keyword: str) -> str:
    """Format log search results."""
    if not results:
        return f"🔍 No logs found matching '{keyword}'"

    lines = [
        f"🔍 Search Results for '{keyword}' ({len(results)} matches)",
        "",
    ]

    for i, entry in enumerate(results[:10], 1):
        log_type = entry.get('type', 'unknown')
        ts = entry.get('ts', 'N/A')
        mode = entry.get('mode', 'unknown')
        summary = f"[{log_type}] {ts} ({mode})"

        if log_type == 'llm_call':
            tokens = entry.get('total_tokens', 0)
            latency = entry.get('latency_ms', 0)
            summary += f" | {tokens} tokens | {latency:.0f}ms"
        elif log_type == 'command':
            cmd = entry.get('cmd', '')[:50]
            exit_code = entry.get('exit_code', -1)
            summary += f" | {cmd} (exit: {exit_code})"
        elif log_type == 'error':
            error_msg = entry.get('message', '')[:60]
            summary += f" | {error_msg}"

        lines.append(f"  {i}. {summary}")

    return "\n".join(lines)


def format_log_recent(results: list, limit: int) -> str:
    """Format recent log entries."""
    if not results:
        return "📭 No log entries found"

    lines = [
        f"📜 Most Recent {min(len(results), limit)} Log Entries",
        "",
    ]

    for i, entry in enumerate(results[:limit], 1):
        log_type = entry.get('type', 'unknown')
        ts = entry.get('ts', 'N/A')
        mode = entry.get('mode', 'unknown')
        summary = f"[{log_type}] {ts} ({mode})"

        if log_type == 'llm_call':
            model = entry.get('model', 'unknown')
            tokens = entry.get('total_tokens', 0)
            summary += f" | {model} | {tokens} tokens"
        elif log_type == 'command':
            cmd = entry.get('cmd', '')[:45]
            exit_code = entry.get('exit_code', -1)
            summary += f" | {cmd} (exit: {exit_code})"
        elif log_type == 'error':
            error_type = entry.get('error_type', 'unknown')
            message = entry.get('message', '')[:40]
            summary += f" | {error_type}: {message}"
        elif log_type == 'search':
            query = entry.get('query', '')[:40]
            results_count = entry.get('results_count', 0)
            summary += f" | '{query}' ({results_count} results)"

        lines.append(f"  {i}. {summary}")

    return "\n".join(lines)
