"""Resolve which fin implementation the agent loads.

Open-core split (2026-07): the full-blood fin lives in the PRIVATE
``neomind_dashboard`` package (editable-installed on the owner's machine,
where it also serves the 8001 dashboard). Public clones don't have it and
fall back to the bundled baseline ``agent.finance`` (frozen snapshot).

Both implementations share the same entry contract
(``get_finance_components`` / ``get_finance_only_components`` + submodule
layout) and the same DB (``~/.neomind/fin/fin.db``), so callers never need
to know which one they got.

Force the baseline (e.g. to test the public path) with::

    NEOMIND_FIN_IMPL=bundled
"""
from __future__ import annotations

import importlib
import logging
import os

logger = logging.getLogger(__name__)

_impl = None  # cached per process — resolution happens once


def fin_package():
    """Return the resolved fin implementation package (cached)."""
    global _impl
    if _impl is None:
        forced = os.environ.get("NEOMIND_FIN_IMPL", "").strip().lower()
        if forced != "bundled":
            try:
                import neomind_dashboard as mod  # private full-blood impl
                _impl = mod
            except ImportError:
                _impl = None
        if _impl is None:
            import agent.finance as mod  # bundled baseline
            _impl = mod
        label = "full" if _impl.__name__ == "neomind_dashboard" else "baseline"
        logger.info("fin impl resolved: %s (%s)", _impl.__name__, label)
    return _impl


def fin_module(submodule: str):
    """Import a submodule of the resolved fin package.

    ``fin_module('persistence')`` → ``neomind_dashboard.persistence`` on the
    owner's machine, ``agent.finance.persistence`` on a public clone.
    Dotted paths work too: ``fin_module('persistence.dao')``.
    """
    return importlib.import_module(f"{fin_package().__name__}.{submodule}")
