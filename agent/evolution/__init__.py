"""NeoMind Evolution Module — Phase 4 self-improvement system.

Provides:
- auto_evolve: Self-evolution engine with learning and feedback
- upgrade: Self-upgrade mechanism for safe updates
"""

from .auto_evolve import AutoEvolve, HealthReport, DailyReport, RetroReport

__all__ = ["AutoEvolve", "HealthReport", "DailyReport", "RetroReport"]
