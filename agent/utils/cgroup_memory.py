"""NeoMind cgroup-aware Memory Monitor — Docker Memory Limit Detection

Detects actual memory limits inside Docker containers via cgroup v1/v2,
instead of relying on os.sysconf which reports host memory.

Research source: Round 2 Docker optimization — Python processes inside containers
see host memory by default, leading to OOM kills when container limit is lower.

No external dependencies — stdlib only.
"""

import logging
import os
import resource
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# cgroup paths
CGROUP_V2_MAX = Path("/sys/fs/cgroup/memory.max")
CGROUP_V2_CURRENT = Path("/sys/fs/cgroup/memory.current")
CGROUP_V1_LIMIT = Path("/sys/fs/cgroup/memory/memory.limit_in_bytes")
CGROUP_V1_USAGE = Path("/sys/fs/cgroup/memory/memory.usage_in_bytes")

# Memory safety margin: trigger warning at this percentage of limit
MEMORY_WARNING_THRESHOLD = 0.80  # 80%
MEMORY_CRITICAL_THRESHOLD = 0.90  # 90%

# Default container memory limit if detection fails (2GB — matches NeoMind Docker config)
DEFAULT_MEMORY_LIMIT_MB = 2048


def _read_cgroup_value(path: Path) -> Optional[int]:
    """Read an integer value from a cgroup file."""
    try:
        if path.exists():
            content = path.read_text().strip()
            if content == "max":  # cgroup v2 unlimited
                return None
            val = int(content)
            # cgroup v1: very large number means unlimited
            if val > 2**62:
                return None
            return val
    except (ValueError, PermissionError, OSError) as e:
        logger.debug(f"Cannot read cgroup {path}: {e}")
    return None


def get_memory_limit_bytes() -> int:
    """Get the effective memory limit for this process.

    Checks cgroup v2 first, then v1, falls back to default.

    Returns:
        Memory limit in bytes
    """
    # Try cgroup v2
    limit = _read_cgroup_value(CGROUP_V2_MAX)
    if limit is not None:
        logger.debug(f"cgroup v2 memory limit: {limit / 1024**2:.0f} MB")
        return limit

    # Try cgroup v1
    limit = _read_cgroup_value(CGROUP_V1_LIMIT)
    if limit is not None:
        logger.debug(f"cgroup v1 memory limit: {limit / 1024**2:.0f} MB")
        return limit

    # Fallback to default
    logger.debug(f"No cgroup limit detected, using default: {DEFAULT_MEMORY_LIMIT_MB} MB")
    return DEFAULT_MEMORY_LIMIT_MB * 1024 * 1024


def get_memory_usage_bytes() -> int:
    """Get current memory usage of the container/cgroup.

    Returns:
        Current memory usage in bytes
    """
    # Try cgroup v2
    usage = _read_cgroup_value(CGROUP_V2_CURRENT)
    if usage is not None:
        return usage

    # Try cgroup v1
    usage = _read_cgroup_value(CGROUP_V1_USAGE)
    if usage is not None:
        return usage

    # Fallback to process RSS via resource module
    try:
        rusage = resource.getrusage(resource.RUSAGE_SELF)
        # ru_maxrss is in KB on Linux
        return rusage.ru_maxrss * 1024
    except Exception:
        return 0


def get_memory_status() -> Dict[str, Any]:
    """Get comprehensive memory status.

    Returns:
        Dict with limit_mb, usage_mb, usage_pct, level (ok|warning|critical)
    """
    limit = get_memory_limit_bytes()
    usage = get_memory_usage_bytes()
    limit_mb = limit / (1024 * 1024)
    usage_mb = usage / (1024 * 1024)
    pct = usage / limit if limit > 0 else 0

    if pct >= MEMORY_CRITICAL_THRESHOLD:
        level = "critical"
    elif pct >= MEMORY_WARNING_THRESHOLD:
        level = "warning"
    else:
        level = "ok"

    return {
        "limit_mb": round(limit_mb, 1),
        "usage_mb": round(usage_mb, 1),
        "usage_pct": round(pct * 100, 1),
        "level": level,
        "cgroup_detected": _detect_cgroup_version(),
    }


def _detect_cgroup_version() -> str:
    """Detect which cgroup version is in use."""
    if CGROUP_V2_MAX.exists() or CGROUP_V2_CURRENT.exists():
        return "v2"
    if CGROUP_V1_LIMIT.exists() or CGROUP_V1_USAGE.exists():
        return "v1"
    return "none"


def is_memory_safe(safety_margin_mb: int = 200) -> bool:
    """Check if there's enough memory headroom.

    Args:
        safety_margin_mb: Required free memory in MB

    Returns:
        True if memory usage is within safe limits
    """
    limit = get_memory_limit_bytes()
    usage = get_memory_usage_bytes()
    free = limit - usage
    return free > (safety_margin_mb * 1024 * 1024)


def set_process_memory_limit(fraction: float = 0.85) -> None:
    """Set process soft memory limit as fraction of container limit.

    Uses resource.setrlimit to prevent Python from consuming
    more than the specified fraction of the container's memory limit.

    Args:
        fraction: Fraction of container limit (0.0-1.0)
    """
    limit = get_memory_limit_bytes()
    soft_limit = int(limit * fraction)

    try:
        resource.setrlimit(resource.RLIMIT_AS, (soft_limit, limit))
        logger.info(
            f"Set process memory limit: soft={soft_limit // (1024**2)}MB, "
            f"hard={limit // (1024**2)}MB ({fraction*100:.0f}% of container)"
        )
    except (ValueError, OSError) as e:
        logger.warning(f"Cannot set process memory limit: {e}")
