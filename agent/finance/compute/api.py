"""FastAPI router for Phase B4 — dep_hash + compute cache.

Read endpoints
--------------
``GET  /api/compute/cache/stats?project_id=``       lifetime hit/miss + bytes
``GET  /api/compute/runs?project_id=&step=&limit=`` recent compute runs
``GET  /api/compute/runs/{compute_run_id}?project_id=`` detail with params

Hash diagnostics
----------------
``POST /api/compute/dep-hash``                      hash a DepHashInputs payload
``POST /api/compute/diff``                          which fields differ between two

Dev (gated by ``NEOMIND_RAW_DEV=1``)
-----------------------------------
``POST /api/compute/_dev/exercise_cache``           writes a fake compute_run, demonstrates put + get hit + diff

These are deliberately small, read-mostly endpoints — the real
compute pipeline (B5) will reuse the underlying cache module
directly, not go through HTTP.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .cache import open_dep_cache
from .dep_hash import (
    DepHashInputs,
    compute_dep_hash,
    diff_inputs,
    inputs_from_dict,
    inputs_to_dict,
)

router = APIRouter(prefix="/api/compute", tags=["fin-compute"])


# Same allowlist convention RawStore uses.  Hard-coded today; promote
# to a config table when fin grows beyond one project.
_KNOWN_PROJECTS = {"fin-core"}


def _check_project(project_id: str) -> None:
    if project_id not in _KNOWN_PROJECTS:
        raise HTTPException(
            400,
            f"unknown project_id {project_id!r}; known: {sorted(_KNOWN_PROJECTS)}",
        )


def _dev_enabled() -> bool:
    return os.environ.get("NEOMIND_RAW_DEV", "").strip() == "1"


# ── Pydantic input models ─────────────────────────────────────────


class DepHashInputsModel(BaseModel):
    """JSON shape for DepHashInputs.  Matches inputs_to_dict /
    inputs_from_dict convention so the API and the cache use the
    same serialisation."""

    blob_hashes:             List[str]              = Field(default_factory=list)
    prompt_template_version: str                    = ""
    llm_model_id:            str                    = ""
    llm_temperature:         float                  = 0.0
    sample_strategy:         str                    = ""
    taxonomy_version:        str                    = ""
    code_git_sha:            str                    = ""
    extra:                   Dict[str, str]         = Field(default_factory=dict)

    def to_inputs(self) -> DepHashInputs:
        return inputs_from_dict(self.model_dump())


class DiffRequest(BaseModel):
    a: DepHashInputsModel
    b: DepHashInputsModel


# ── Read endpoints ────────────────────────────────────────────────


@router.get("/cache/stats")
def cache_stats(project_id: str = Query(...)) -> Dict[str, Any]:
    """Lifetime hits, misses, hit_ratio, bytes_avoided, top steps."""
    _check_project(project_id)
    cache = open_dep_cache(project_id)
    s = cache.stats()
    s["project_id"] = project_id
    return s


@router.get("/runs")
def list_runs(
    project_id: str           = Query(...),
    step:       Optional[str] = Query(None, description="filter by step name"),
    limit:      int           = Query(50, ge=1, le=500),
) -> Dict[str, Any]:
    """Recent compute runs, most recent first."""
    _check_project(project_id)
    cache = open_dep_cache(project_id)
    rows = cache.list_recent(step=step, limit=limit)
    return {"project_id": project_id, "count": len(rows), "runs": rows}


@router.get("/runs/{compute_run_id}")
def get_run(
    project_id:     str = Query(...),
    compute_run_id: str = "",
) -> Dict[str, Any]:
    """Single compute run — full row including ``params``."""
    _check_project(project_id)
    cache = open_dep_cache(project_id)
    row = cache.get_by_id(compute_run_id)
    if row is None:
        raise HTTPException(404, f"compute_run {compute_run_id!r} not found")
    return {"project_id": project_id, "run": row}


# ── Hash diagnostics ─────────────────────────────────────────────


@router.post("/dep-hash")
def hash_inputs(payload: DepHashInputsModel) -> Dict[str, Any]:
    """Hash one DepHashInputs payload.  Returns the dep_hash plus the
    canonical input string (for debugging "what got hashed?")."""
    inputs = payload.to_inputs()
    return {
        "dep_hash":  compute_dep_hash(inputs),
        "canonical": inputs.canonical(),
        "inputs":    inputs_to_dict(inputs),
    }


@router.post("/diff")
def diff(payload: DiffRequest) -> Dict[str, Any]:
    """Which fields differ between two DepHashInputs?  Empty list
    means cache would HIT."""
    a = payload.a.to_inputs()
    b = payload.b.to_inputs()
    return {
        "a_dep_hash":  compute_dep_hash(a),
        "b_dep_hash":  compute_dep_hash(b),
        "differs":     diff_inputs(a, b),
        "would_hit":   not bool(diff_inputs(a, b)),
    }


# ── Dev endpoints ────────────────────────────────────────────────


@router.post("/_dev/exercise_cache")
def dev_exercise_cache(
    project_id: str = Query(...),
    step:       str = Query("observations"),
) -> Dict[str, Any]:
    """End-to-end smoke for the cache.

    1. Pulls 3 random blob hashes from the project's RawStore (so the
       inputs are realistic — same hashes B1 actually wrote).
    2. Builds a DepHashInputs with those blobs.
    3. Computes dep_hash, looks it up — initially MISS.
    4. Writes a fake payload via cache.put().
    5. Looks up again — now HIT.
    6. Toggles one parameter (code_git_sha) → MISS again.
    7. Reverts → HIT (proves the cache is content-addressed, not
       sequential).
    8. Returns the trace so the browser can verify each step.

    Gated by NEOMIND_RAW_DEV=1.
    """
    if not _dev_enabled():
        raise HTTPException(
            403,
            "dev endpoints disabled — export NEOMIND_RAW_DEV=1 in the "
            "uvicorn process to enable",
        )
    _check_project(project_id)

    from agent.finance.raw_store import RawStore

    raw = RawStore.for_project(project_id)
    blob_rows = raw.index.list_blobs(limit=3)
    if len(blob_rows) < 1:
        raise HTTPException(
            409,
            "no blobs in raw store yet — run "
            "`POST /api/raw/_dev/crawl_news_synthetic` first",
        )
    blob_hashes = tuple(r["sha256"] for r in blob_rows)

    cache = open_dep_cache(project_id)

    inputs_a = DepHashInputs(
        blob_hashes=             blob_hashes,
        prompt_template_version= "obs.v1",
        llm_model_id=            "deepseek-v4-flash",
        llm_temperature=         0.3,
        sample_strategy=         "top_n_relevance:3",
        taxonomy_version=        "fin.v2",
        code_git_sha=            "aabbccdd",
    )
    hash_a = compute_dep_hash(inputs_a)

    trace: List[Dict[str, Any]] = []

    # 1) initial miss
    hit_1 = cache.get(hash_a, step)
    trace.append({"step": "1.initial_lookup", "expected": "MISS", "result": "MISS" if hit_1 is None else "HIT"})

    # 2) write a fake payload
    payload_obj = {"dep_hash": hash_a, "step": step, "items": [
        {"obs_id": "ATR_5d", "value": 1.23},
        {"obs_id": "RSI_14", "value": 47.2},
    ]}
    import json as _json
    payload_bytes = _json.dumps(payload_obj, sort_keys=True).encode("utf-8")
    written = cache.put(
        inputs=inputs_a, step=step, payload=payload_bytes,
        crawl_run_id=None,
    )
    trace.append({
        "step": "2.cache_put",
        "compute_run_id": written.compute_run_id,
        "size_bytes": written.size_bytes,
        "snapshot_path_tail": (written.snapshot_path or "")[-60:],
    })

    # 3) lookup again — HIT
    hit_2 = cache.get(hash_a, step)
    trace.append({
        "step": "3.lookup_after_put",
        "expected": "HIT",
        "result": "HIT" if hit_2 else "MISS",
        "compute_run_id": hit_2.compute_run_id if hit_2 else None,
    })

    # 4) flip code_git_sha → different hash → MISS
    inputs_b = DepHashInputs(**{**inputs_a.__dict__, "code_git_sha": "eeff0011"})
    hash_b = compute_dep_hash(inputs_b)
    hit_3  = cache.get(hash_b, step)
    trace.append({
        "step": "4.lookup_changed_code_git_sha",
        "hash_b_prefix": hash_b[:12],
        "expected": "MISS",
        "result": "MISS" if hit_3 is None else "HIT",
    })

    # 5) revert → HIT (cache lookup is content-addressed)
    inputs_c = DepHashInputs(**{**inputs_b.__dict__, "code_git_sha": "aabbccdd"})
    hash_c = compute_dep_hash(inputs_c)
    hit_4  = cache.get(hash_c, step)
    trace.append({
        "step": "5.revert_lookup",
        "hash_c_eq_a": hash_c == hash_a,
        "expected": "HIT",
        "result": "HIT" if hit_4 else "MISS",
    })

    return {
        "project_id":    project_id,
        "step":          step,
        "blob_hashes":   list(blob_hashes),
        "hash_a_prefix": hash_a[:12],
        "trace":         trace,
        "diff_a_vs_b":   diff_inputs(inputs_a, inputs_b),
        "stats":         cache.stats(),
    }
