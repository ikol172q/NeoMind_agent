"""NeoMind Unified Logger

Every operation is logged to daily JSONL files:
~/.neomind/logs/YYYY-MM-DD.jsonl

Log types:
- llm_call: model, prompt_tokens, completion_tokens, latency_ms, mode
- command: cmd, args, exit_code, duration_ms, mode
- file_op: operation (read/write/delete), path, size_bytes, mode
- provider_switch: from_provider, to_provider, updated_by
- error: error_type, message, traceback, severity, mode
- search: query, results_count, source, mode

Features:
- Daily rotation (new file each day)
- Auto-sanitize PII before logging
- Query interface: search, filter by date/type/mode
- Stats: daily/weekly/monthly summaries
"""

import json
import os
import re
import time
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any

from .pii_sanitizer import PIISanitizer


class UnifiedLogger:
    """Central logging system for all NeoMind operations."""

    def __init__(self, log_dir: Optional[str] = None):
        """Initialize the unified logger.

        Args:
            log_dir: Directory to store logs (default: ~/.neomind/logs)
        """
        self.log_dir = Path(log_dir or os.path.expanduser("~/.neomind/logs"))
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._sanitizer = PIISanitizer(mode="strict")

    def log(self, log_type: str, mode: str = "unknown", **kwargs) -> None:
        """Log an event with auto-timestamp and PII sanitization.

        Args:
            log_type: Type of log entry (llm_call, command, file_op, etc.)
            mode: Execution mode (cli, coding, fin, chat, etc.)
            **kwargs: Additional fields to log
        """
        entry = {
            "ts": datetime.now().isoformat(),
            "type": log_type,
            "mode": mode,
            **self._sanitizer.sanitize_dict(kwargs)
        }
        self._append(entry)

    def log_llm_call(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: float,
        mode: str = "unknown",
        **extra
    ) -> None:
        """Log an LLM API call.

        Args:
            model: Model name (gpt-4, claude-3-sonnet, etc.)
            prompt_tokens: Input tokens
            completion_tokens: Output tokens
            latency_ms: Response time in milliseconds
            mode: Execution mode
            **extra: Additional fields
        """
        self.log(
            "llm_call",
            mode=mode,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            total_tokens=prompt_tokens + completion_tokens,
            **extra
        )

    def log_command(
        self,
        cmd: str,
        exit_code: int,
        duration_ms: float,
        mode: str = "unknown",
        **extra
    ) -> None:
        """Log a shell command execution.

        Args:
            cmd: Command string
            exit_code: Process exit code
            duration_ms: Execution time in milliseconds
            mode: Execution mode
            **extra: Additional fields (args, stdout, stderr, etc.)
        """
        self.log(
            "command",
            mode=mode,
            cmd=cmd,
            exit_code=exit_code,
            duration_ms=duration_ms,
            success=exit_code == 0,
            **extra
        )

    def log_file_op(
        self,
        operation: str,
        path: str,
        mode: str = "unknown",
        **extra
    ) -> None:
        """Log a file operation (read/write/delete).

        Args:
            operation: Operation type (read, write, delete, append)
            path: File path
            mode: Execution mode
            **extra: Additional fields (size_bytes, permissions, etc.)
        """
        self.log(
            "file_op",
            mode=mode,
            operation=operation,
            path=path,
            **extra
        )

    def log_error(
        self,
        error_type: str,
        message: str,
        severity: str = "error",
        mode: str = "unknown",
        **extra
    ) -> None:
        """Log an error event.

        Args:
            error_type: Error class name or category
            message: Error message
            severity: "debug", "info", "warning", "error", "critical"
            mode: Execution mode
            **extra: Additional fields (traceback, context, etc.)
        """
        self.log(
            "error",
            mode=mode,
            error_type=error_type,
            message=message,
            severity=severity,
            **extra
        )

    def log_search(
        self,
        query: str,
        results_count: int,
        source: str = "unknown",
        mode: str = "unknown",
        **extra
    ) -> None:
        """Log a search operation.

        Args:
            query: Search query
            results_count: Number of results returned
            source: Search source (web, file, db, etc.)
            mode: Execution mode
            **extra: Additional fields
        """
        self.log(
            "search",
            mode=mode,
            query=query,
            results_count=results_count,
            source=source,
            **extra
        )

    def log_provider_switch(
        self,
        from_provider: str,
        to_provider: str,
        updated_by: str = "system",
        **extra
    ) -> None:
        """Log a provider/model switch.

        Args:
            from_provider: Previous provider
            to_provider: New provider
            updated_by: Who initiated the switch
            **extra: Additional fields (reason, etc.)
        """
        self.log(
            "provider_switch",
            mode="system",
            from_provider=from_provider,
            to_provider=to_provider,
            updated_by=updated_by,
            **extra
        )

    def query(
        self,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        log_type: Optional[str] = None,
        mode: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Query logs with filters.

        Args:
            date_from: Start date (inclusive)
            date_to: End date (inclusive)
            log_type: Filter by log type
            mode: Filter by mode
            limit: Maximum results to return

        Returns:
            List of matching log entries
        """
        if date_from is None:
            date_from = date.today()
        if date_to is None:
            date_to = date.today()

        entries = []
        current_date = date_from

        # Iterate through date range
        while current_date <= date_to:
            log_file = self.log_dir / f"{current_date.isoformat()}.jsonl"
            if log_file.exists():
                try:
                    with open(log_file, 'r', encoding='utf-8') as f:
                        for line in f:
                            if not line.strip():
                                continue
                            try:
                                entry = json.loads(line)
                                if log_type and entry.get('type') != log_type:
                                    continue
                                if mode and entry.get('mode') != mode:
                                    continue
                                entries.append(entry)
                            except json.JSONDecodeError:
                                continue
                except (IOError, OSError):
                    continue

            current_date += timedelta(days=1)

        # Return most recent first, limit results
        return sorted(entries, key=lambda x: x.get('ts', ''), reverse=True)[:limit]

    def get_daily_stats(self, target_date: Optional[date] = None) -> Dict[str, Any]:
        """Get stats for a specific day.

        Args:
            target_date: Date to analyze (default: today)

        Returns:
            Dictionary with stats (total_events, llm_calls, errors, by_mode, tokens, etc.)
        """
        if target_date is None:
            target_date = date.today()

        log_file = self.log_dir / f"{target_date.isoformat()}.jsonl"
        if not log_file.exists():
            return {
                "date": target_date.isoformat(),
                "total_events": 0,
                "by_type": {},
                "by_mode": {},
                "errors": 0,
                "total_tokens": 0,
                "total_commands": 0,
            }

        entries = []
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except (IOError, OSError):
            return {
                "date": target_date.isoformat(),
                "total_events": 0,
                "by_type": {},
                "by_mode": {},
                "errors": 0,
                "total_tokens": 0,
                "total_commands": 0,
            }

        # Build stats
        by_type = {}
        by_mode = {}
        total_tokens = 0
        error_count = 0
        command_count = 0

        for entry in entries:
            entry_type = entry.get('type', 'unknown')
            entry_mode = entry.get('mode', 'unknown')

            by_type[entry_type] = by_type.get(entry_type, 0) + 1
            by_mode[entry_mode] = by_mode.get(entry_mode, 0) + 1

            if entry_type == 'llm_call':
                total_tokens += entry.get('total_tokens', 0)
            elif entry_type == 'error':
                error_count += 1
            elif entry_type == 'command':
                command_count += 1

        return {
            "date": target_date.isoformat(),
            "total_events": len(entries),
            "by_type": by_type,
            "by_mode": by_mode,
            "errors": error_count,
            "total_tokens": total_tokens,
            "total_commands": command_count,
            "log_file": str(log_file),
            "log_size_bytes": log_file.stat().st_size,
        }

    def get_weekly_stats(self) -> Dict[str, Any]:
        """Aggregate stats for the last 7 days.

        Returns:
            Dictionary with aggregated stats
        """
        today = date.today()
        week_ago = today - timedelta(days=7)

        daily_stats = []
        total_events = 0
        total_tokens = 0
        total_errors = 0
        total_commands = 0
        all_types = {}
        all_modes = {}

        for i in range(8):
            target_date = week_ago + timedelta(days=i)
            stats = self.get_daily_stats(target_date)

            if stats['total_events'] > 0:
                daily_stats.append(stats)

            total_events += stats['total_events']
            total_tokens += stats['total_tokens']
            total_errors += stats['errors']
            total_commands += stats['total_commands']

            for k, v in stats['by_type'].items():
                all_types[k] = all_types.get(k, 0) + v
            for k, v in stats['by_mode'].items():
                all_modes[k] = all_modes.get(k, 0) + v

        return {
            "period": f"{week_ago.isoformat()} to {today.isoformat()}",
            "total_events": total_events,
            "total_tokens": total_tokens,
            "total_errors": total_errors,
            "total_commands": total_commands,
            "by_type": all_types,
            "by_mode": all_modes,
            "days_with_activity": len(daily_stats),
            "daily_breakdown": daily_stats,
        }

    def search(self, keyword: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Full-text search across all logs.

        Args:
            keyword: Search term (case-insensitive)
            limit: Maximum results

        Returns:
            List of matching entries
        """
        keyword_lower = keyword.lower()
        pattern = re.compile(keyword_lower)
        matches = []

        # Search all log files in the directory
        for log_file in sorted(self.log_dir.glob("*.jsonl"), reverse=True):
            if len(matches) >= limit:
                break

            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        if len(matches) >= limit:
                            break

                        if not line.strip():
                            continue

                        try:
                            entry = json.loads(line)
                            # Search all string values in entry
                            entry_str = json.dumps(entry).lower()
                            if pattern.search(entry_str):
                                matches.append(entry)
                        except json.JSONDecodeError:
                            continue
            except (IOError, OSError):
                continue

        return matches

    def cleanup_old_logs(self, keep_days: int = 90) -> int:
        """Remove logs older than keep_days.

        Args:
            keep_days: Number of days of logs to keep

        Returns:
            Number of files deleted
        """
        cutoff_date = date.today() - timedelta(days=keep_days)
        deleted_count = 0

        for log_file in self.log_dir.glob("*.jsonl"):
            # Extract date from filename (YYYY-MM-DD.jsonl)
            try:
                file_date_str = log_file.stem
                file_date = datetime.fromisoformat(file_date_str).date()

                if file_date < cutoff_date:
                    log_file.unlink()
                    deleted_count += 1
            except (ValueError, AttributeError):
                # Skip files that don't match expected naming
                continue

        return deleted_count

    def get_all_stats(self) -> Dict[str, Any]:
        """Get comprehensive stats across all logs.

        Returns:
            Dictionary with overall statistics
        """
        all_types = {}
        all_modes = {}
        total_events = 0
        total_tokens = 0
        total_errors = 0
        total_commands = 0
        total_size_bytes = 0
        date_range = None

        for log_file in sorted(self.log_dir.glob("*.jsonl")):
            total_size_bytes += log_file.stat().st_size

            try:
                file_date_str = log_file.stem
                file_date = datetime.fromisoformat(file_date_str).date()

                if date_range is None:
                    date_range = (file_date, file_date)
                else:
                    date_range = (min(date_range[0], file_date), max(date_range[1], file_date))
            except (ValueError, AttributeError):
                continue

            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        if not line.strip():
                            continue
                        try:
                            entry = json.loads(line)

                            entry_type = entry.get('type', 'unknown')
                            entry_mode = entry.get('mode', 'unknown')

                            all_types[entry_type] = all_types.get(entry_type, 0) + 1
                            all_modes[entry_mode] = all_modes.get(entry_mode, 0) + 1

                            total_events += 1

                            if entry_type == 'llm_call':
                                total_tokens += entry.get('total_tokens', 0)
                            elif entry_type == 'error':
                                total_errors += 1
                            elif entry_type == 'command':
                                total_commands += 1
                        except json.JSONDecodeError:
                            continue
            except (IOError, OSError):
                continue

        return {
            "total_events": total_events,
            "total_tokens": total_tokens,
            "total_errors": total_errors,
            "total_commands": total_commands,
            "by_type": all_types,
            "by_mode": all_modes,
            "log_files": len(list(self.log_dir.glob("*.jsonl"))),
            "total_size_bytes": total_size_bytes,
            "date_range": f"{date_range[0]} to {date_range[1]}" if date_range else "none",
            "log_dir": str(self.log_dir),
        }

    def _append(self, entry: Dict[str, Any]) -> None:
        """Append entry to today's log file (atomic write).

        Args:
            entry: Log entry dictionary
        """
        today = date.today().isoformat()
        log_file = self.log_dir / f"{today}.jsonl"

        line = json.dumps(entry, ensure_ascii=False) + "\n"

        # Atomic append
        try:
            with open(log_file, "a", encoding='utf-8') as f:
                f.write(line)
        except (IOError, OSError):
            # Silently fail — don't disrupt application
            pass


# ── Singleton ────────────────────────────────────────────────────

_logger: Optional[UnifiedLogger] = None


def get_unified_logger(log_dir: Optional[str] = None) -> UnifiedLogger:
    """Get or create the global unified logger.

    Args:
        log_dir: Optional log directory override

    Returns:
        UnifiedLogger instance
    """
    global _logger
    if _logger is None:
        _logger = UnifiedLogger(log_dir)
    return _logger
