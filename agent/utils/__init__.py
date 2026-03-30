"""NeoMind utils — shared utilities for the agent.

Includes:
- structured_log: JSON-format logging for observability
- circuit_breaker: Resilience pattern for API calls
- cgroup_memory: Docker memory limit detection via cgroup v1/v2
- degradation: Graceful service degradation (LIVE → CACHE → STATIC)
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import cgroup_memory
    from . import degradation


def __getattr__(name: str):
    """Lazy module accessors for cgroup_memory and degradation."""
    if name == "cgroup_memory":
        from . import cgroup_memory as mod
        return mod
    if name == "degradation":
        from . import degradation as mod
        return mod
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
