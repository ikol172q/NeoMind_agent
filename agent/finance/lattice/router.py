"""FastAPI router for the Insight Lattice.

v1 exposes only L1 (observations). L2 (clusters) and L3 (apex)
will be added under the same `/api/lattice/*` prefix in D2-D3.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query

from agent.finance import investment_projects
from agent.finance.lattice.observations import build_observations
from agent.finance.lattice.taxonomy import load_taxonomy

logger = logging.getLogger(__name__)

_TTL_S = 60.0
_cache: Dict[str, tuple[float, Dict[str, Any]]] = {}
_cache_lock = threading.Lock()


def _cached(key: str) -> Optional[Dict[str, Any]]:
    with _cache_lock:
        entry = _cache.get(key)
    if entry is None:
        return None
    if time.time() - entry[0] > _TTL_S:
        return None
    return entry[1]


def _put(key: str, value: Dict[str, Any]) -> None:
    with _cache_lock:
        _cache[key] = (time.time(), value)


def build_lattice_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/lattice/observations")
    def list_observations(
        project_id: str = Query(...),
        fresh: bool = Query(False),
    ) -> Dict[str, Any]:
        if project_id not in investment_projects.list_projects():
            raise HTTPException(404, f"project {project_id!r} is not registered")

        cache_key = f"obs::{project_id}"
        if not fresh:
            cached = _cached(cache_key)
            if cached is not None:
                return cached

        t0 = time.monotonic()
        try:
            rows = build_observations(project_id, fresh=fresh)
        except Exception as exc:
            logger.exception("lattice observations failed")
            raise HTTPException(502, f"observations build failed: {exc}")
        duration_ms = int((time.monotonic() - t0) * 1000)

        tax = load_taxonomy()
        payload = {
            "project_id": project_id,
            "count": len(rows),
            "observations": [r.to_dict() for r in rows],
            "taxonomy_version": tax.version,
            "theme_signatures": [
                {"id": s.id, "title": s.title,
                 "any_of": sorted(s.any_of), "all_of": sorted(s.all_of)}
                for s in tax.themes
            ],
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "duration_ms": duration_ms,
        }
        _put(cache_key, payload)
        return payload

    return router
