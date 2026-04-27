"""Tiny helper: stable short git SHA for ``DepHashInputs.code_git_sha``.

Resolved once at import time and cached.  If the working tree
isn't a git repo (e.g. CI docker image without ``.git``), or git
is missing, falls back to ``"unknown"`` so dep_hash is still
deterministic — just not bound to a code revision.

This is intentionally synchronous and short — it runs at module
import, so it must NEVER block.  ``subprocess.run`` with a tight
timeout protects against hung git processes on weird filesystems.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


_CACHED_SHA: str | None = None


def _detect_git_sha() -> str:
    """Run ``git rev-parse --short=8 HEAD`` from the repo root.
    Returns ``"unknown"`` on any failure.
    """
    # Climb from this file up to the repo root (the dir containing
    # .git).  Robust against being called from arbitrary CWDs.
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        if (parent / ".git").exists():
            cwd = parent
            break
    else:
        return "unknown"

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=8", "HEAD"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        if result.returncode != 0:
            return "unknown"
        sha = result.stdout.strip()
        # rev-parse can echo the abbreviated sha or the full one
        # depending on repo state; clamp to 8 chars defensively.
        return sha[:8] if sha else "unknown"
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        logger.debug("codeversion: git rev-parse failed: %s", exc)
        return "unknown"


def get_code_git_sha() -> str:
    """8-character short SHA of the working tree's HEAD, or
    ``"unknown"``.  Cached after first call."""
    global _CACHED_SHA
    if _CACHED_SHA is None:
        # Allow override for tests / deterministic CI builds
        env_override = os.environ.get("NEOMIND_CODE_GIT_SHA")
        if env_override:
            _CACHED_SHA = env_override.strip()[:8] or "unknown"
        else:
            _CACHED_SHA = _detect_git_sha()
    return _CACHED_SHA


def clear_cache() -> None:
    """Test hook — force re-detection on next call."""
    global _CACHED_SHA
    _CACHED_SHA = None
