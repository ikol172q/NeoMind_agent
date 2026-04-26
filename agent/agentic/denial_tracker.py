"""Denial tracker — circuit breaker for repeated tool denials.

Mirrors Claude Code's denial tracking in utils/permissions/permissions.ts:964.
When the same tool is denied N times consecutively, the circuit breaks:
  - The tool is temporarily hidden from the LLM (removed from prompt)
  - A diagnostic message is logged
  - After cooling off, the tool can be re-enabled

This prevents infinite denial loops where the LLM keeps proposing the same
dangerous operation and the user keeps rejecting it.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class DenialRecord:
    """Track consecutive denials for a single tool."""
    tool_name: str
    denied_commands: List[str] = field(default_factory=list)
    consecutive_count: int = 0
    first_denial_time: float = 0.0
    last_denial_time: float = 0.0
    circuit_broken: bool = False
    circuit_broken_time: float = 0.0


class DenialTracker:
    """Tracks tool denials and triggers circuit breakers.

    Usage:
        tracker = DenialTracker(threshold=3, cooldown_sec=300)
        ...
        if user_denied_the_tool:
            tracker.record_denial("Bash", "rm -rf /tmp/*")
            if tracker.is_circuit_broken("Bash"):
                # Remove Bash from the LLM's tool prompt
                ...
    """

    def __init__(self, threshold: int = 3, cooldown_sec: float = 300.0):
        self._threshold = threshold
        self._cooldown_sec = cooldown_sec
        self._records: Dict[str, DenialRecord] = {}

    def record_denial(self, tool_name: str, command: str = "") -> DenialRecord:
        """Record a denial for a tool. Returns the updated record."""
        now = time.time()
        key = tool_name.lower()

        if key not in self._records:
            self._records[key] = DenialRecord(tool_name=tool_name)

        rec = self._records[key]

        # If circuit was broken but cooldown expired, reset
        if rec.circuit_broken and (now - rec.circuit_broken_time) > self._cooldown_sec:
            rec.circuit_broken = False
            rec.consecutive_count = 0
            rec.denied_commands = []

        rec.consecutive_count += 1
        rec.last_denial_time = now
        if rec.first_denial_time == 0.0:
            rec.first_denial_time = now
        if command:
            rec.denied_commands.append(command)

        # Check threshold
        if rec.consecutive_count >= self._threshold and not rec.circuit_broken:
            rec.circuit_broken = True
            rec.circuit_broken_time = now
            logger.warning(
                f"Circuit breaker tripped for {tool_name}: "
                f"{rec.consecutive_count} consecutive denials. "
                f"Tool will be hidden for {self._cooldown_sec}s."
            )

        return rec

    def record_approval(self, tool_name: str) -> None:
        """Reset denial count when a tool is approved — the pattern was acceptable."""
        key = tool_name.lower()
        if key in self._records:
            rec = self._records[key]
            rec.consecutive_count = 0
            rec.denied_commands = []
            rec.circuit_broken = False

    def is_circuit_broken(self, tool_name: str) -> bool:
        """Check if the circuit breaker is tripped for a tool.

        When True, the tool should be hidden from the LLM prompt.
        """
        key = tool_name.lower()
        if key not in self._records:
            return False
        rec = self._records[key]
        if not rec.circuit_broken:
            return False
        # Check if cooldown has expired
        if (time.time() - rec.circuit_broken_time) > self._cooldown_sec:
            rec.circuit_broken = False
            rec.consecutive_count = 0
            return False
        return True

    def get_broken_tools(self) -> List[str]:
        """Return tool names whose circuit is currently broken.

        These should be filtered from the LLM's tool prompt.
        """
        return [name for name in self._records if self.is_circuit_broken(name)]

    def get_denial_summary(self) -> str:
        """Human-readable summary for /context or diagnostics."""
        if not self._records:
            return "No denials recorded."
        lines = ["Denial summary:"]
        for rec in self._records.values():
            status = "BROKEN" if rec.circuit_broken else f"{rec.consecutive_count}/{self._threshold}"
            lines.append(f"  {rec.tool_name}: {status} denials")
            if rec.denied_commands:
                lines.append(f"    last: {rec.denied_commands[-1][:60]}")
        return "\n".join(lines)

    def reset(self) -> None:
        """Reset all tracking state."""
        self._records.clear()
