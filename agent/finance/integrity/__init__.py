"""Live integrity check for the fin data platform.

Mirrors the structure of ``agent/finance/lattice/selfcheck.py`` —
same report shape, same UI badge contract — extended over the new
SQLite persistence + scheduler layers.

Three concentric circles of invariants:

  1. **Data layer** — schema/dedup/attribution/temporal consistency.
     Things that should never go wrong even if every job fails.

  2. **Compute & compliance layer** — tax/wash-sale/PDT/holding-period
     formulas hold; analysis_runs ↔ strategy_signals ↔ scheduler_jobs
     references resolve.

  3. **Visualization layer** — UI numbers match DB queries (this
     check lives in the API/UI tests, not here, because it needs a
     running uvicorn + browser; see scripts/integrity_visual.py).

Reports are returned in the same shape as ``lattice.selfcheck`` so
the existing UI badge widget can render them with no plumbing changes
beyond pointing at a different endpoint.

Usage:
    from agent.finance.integrity import run_integrity_check
    report = run_integrity_check()
    # report = {"summary": "11/11 pass", "all_pass": True,
    #           "checks": [...], "timestamp": "..."}

CLI:
    python -m agent.finance.integrity.runner

HTTP:
    GET /api/integrity/check
"""

from agent.finance.integrity.core import (
    CHECKS,
    IntegrityReport,
    run_integrity_check,
)

__all__ = ["CHECKS", "IntegrityReport", "run_integrity_check"]
