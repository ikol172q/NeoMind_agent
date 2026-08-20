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
    """Lazy module accessors for cgroup_memory and degradation.

    importlib.import_module, not `from . import X`: the latter resolves X by
    calling getattr on this package first, which lands back in this function
    and recurses until the stack blows —

        RecursionError: maximum recursion depth exceeded
          agent/utils/__init__.py:23: in __getattr__
              from . import degradation as mod

    import_module goes through the import system directly and does not
    re-enter __getattr__.
    """
    if name in ("cgroup_memory", "degradation"):
        import importlib

        return importlib.import_module(f".{name}", __name__)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
