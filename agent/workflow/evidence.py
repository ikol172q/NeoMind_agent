# agent/workflow/evidence.py
"""
Evidence Trail — audit log for all agent operations.

Every significant action gets logged with:
- Timestamp
- Action type (command, file_edit, trade, search, etc.)
- Input (what was requested)
- Output (what happened)
- Evidence (screenshot path, log snippet, etc.)

Used by:
- coding: track file changes, test results
- fin: trade audit trail, compliance evidence
- chat: fact-check trail, source tracking
"""

import os
import json
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime, timezone


@dataclass
class EvidenceEntry:
    timestamp: str
    action: str          # "command", "file_edit", "trade", "search", "review", "screenshot"
    input_data: str      # what was requested
    output_data: str     # what happened
    mode: str = ""       # which personality
    evidence_path: str = ""  # screenshot/file path
    sprint_id: str = ""  # link to sprint if active
    severity: str = "info"  # info, warning, critical


class EvidenceTrail:
    """Append-only audit log, persisted to JSONL file.

    Usage:
        trail = EvidenceTrail()
        trail.log("command", "rm -rf /tmp/old", "Deleted 42 files", mode="coding")
        trail.log("trade", "BUY AAPL 100", "Order submitted", mode="fin",
                   evidence_path="/tmp/trade-screenshot.png")
        entries = trail.get_recent(20)
    """

    LOG_DIR = Path(os.getenv("HOME", "/data")) / ".neomind" / "evidence"

    def __init__(self):
        self.LOG_DIR.mkdir(parents=True, exist_ok=True)
        self._log_path = self.LOG_DIR / "audit.jsonl"

    def log(self, action: str, input_data: str, output_data: str,
            mode: str = "", evidence_path: str = "", sprint_id: str = "",
            severity: str = "info"):
        """Append an entry to the audit trail."""
        entry = EvidenceEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            action=action,
            input_data=input_data[:500],
            output_data=output_data[:500],
            mode=mode,
            evidence_path=evidence_path,
            sprint_id=sprint_id,
            severity=severity,
        )

        line = json.dumps({
            "ts": entry.timestamp,
            "action": entry.action,
            "input": entry.input_data,
            "output": entry.output_data,
            "mode": entry.mode,
            "evidence": entry.evidence_path,
            "sprint": entry.sprint_id,
            "severity": entry.severity,
        }, ensure_ascii=False)

        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def get_recent(self, limit: int = 20) -> List[Dict]:
        """Get the most recent N entries."""
        if not self._log_path.exists():
            return []

        lines = self._log_path.read_text(encoding="utf-8").strip().split("\n")
        entries = []
        for line in lines[-limit:]:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries

    def get_by_action(self, action: str, limit: int = 20) -> List[Dict]:
        """Filter entries by action type."""
        all_entries = self.get_recent(200)
        filtered = [e for e in all_entries if e.get("action") == action]
        return filtered[-limit:]

    def get_by_sprint(self, sprint_id: str) -> List[Dict]:
        """Get all entries for a specific sprint."""
        all_entries = self.get_recent(500)
        return [e for e in all_entries if e.get("sprint") == sprint_id]

    def format_recent(self, limit: int = 10) -> str:
        """Format recent entries for display."""
        entries = self.get_recent(limit)
        if not entries:
            return "No evidence entries yet."

        lines = ["📋 Recent Evidence Trail\n"]
        for e in entries:
            ts = e.get("ts", "")[:16]
            action = e.get("action", "?")
            severity = e.get("severity", "info")
            icon = {"info": "ℹ️", "warning": "⚠️", "critical": "🛑"}.get(severity, "ℹ️")
            input_short = e.get("input", "")[:60]
            lines.append(f"{icon} [{ts}] {action}: {input_short}")
            if e.get("evidence"):
                lines.append(f"   📎 {e['evidence']}")
        return "\n".join(lines)

    def get_stats(self) -> Dict:
        """Get evidence trail statistics."""
        entries = self.get_recent(10000)
        if not entries:
            return {"total": 0}

        action_counts = {}
        for e in entries:
            a = e.get("action", "unknown")
            action_counts[a] = action_counts.get(a, 0) + 1

        try:
            size_kb = os.path.getsize(self._log_path) / 1024
        except OSError:
            size_kb = 0

        return {
            "total": len(entries),
            "by_action": action_counts,
            "log_size_kb": round(size_kb, 1),
            "log_path": str(self._log_path),
        }


# ── Singleton ────────────────────────────────────────────────────

_trail: Optional[EvidenceTrail] = None


def get_evidence_trail() -> EvidenceTrail:
    global _trail
    if _trail is None:
        _trail = EvidenceTrail()
    return _trail
