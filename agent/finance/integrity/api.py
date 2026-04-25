"""FastAPI router for the live integrity check — drives the UI badge.

    GET /api/integrity/check               # all layers
    GET /api/integrity/check?layer=data    # single layer

Same response shape as ``lattice/selfcheck.py`` so the UI's existing
N/N-pass badge widget renders without changes.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Query

from agent.finance.integrity import run_integrity_check

router = APIRouter(prefix="/api/integrity", tags=["fin-integrity"])


@router.get("/check")
def integrity_check(
    layer: Optional[str] = Query(
        None, description="filter: data | compute | compliance | viz",
    ),
) -> Dict[str, Any]:
    """Live integrity report — N/N pass + offender details on failures.

    Recomputed on every request. The UI badge should call this on
    mount + on the user's "refresh" click. The same payload runs in
    pre-commit (via ``python -m agent.finance.integrity.runner
    --fail-on-error``) so a green CI badge ↔ green UI badge.
    """
    return run_integrity_check(layer_filter=layer)
