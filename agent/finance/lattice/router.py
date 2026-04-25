"""FastAPI router for the Insight Lattice.

Endpoints under `/api/lattice/*`:
  - /observations   L1 — atomic tagged facts
  - /themes         L1+L2 — clusters + narratives
  - /calls          L1+L2+L3 — Toulmin-structured apex calls
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query

from agent.finance import investment_projects
from agent.finance.lattice import runtime, spec
from agent.finance.lattice.calls import build_calls, get_call_trace, get_call_pool_trace
from agent.finance.lattice.graph import build_graph
from agent.finance.lattice.observations import build_observations
from agent.finance.lattice.selfcheck import run_selfcheck
from agent.finance.lattice.snapshots import list_snapshots, read_snapshot
from agent.finance.lattice.taxonomy import load_taxonomy
from agent.finance.lattice.themes import build_themes, get_narrative_trace

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

    @router.get("/api/lattice/themes")
    def list_themes(
        project_id: str = Query(...),
        fresh: bool = Query(False),
    ) -> Dict[str, Any]:
        if project_id not in investment_projects.list_projects():
            raise HTTPException(404, f"project {project_id!r} is not registered")

        lang = runtime.get_effective_language()
        bh = runtime.budget_hash(runtime.get_effective_budgets())
        cache_key = f"themes::{lang}::{bh}::{project_id}"
        if not fresh:
            cached = _cached(cache_key)
            if cached is not None:
                return cached

        t0 = time.monotonic()
        try:
            result = build_themes(project_id, fresh=fresh)
        except Exception as exc:
            logger.exception("lattice themes failed")
            raise HTTPException(502, f"themes build failed: {exc}")
        duration_ms = int((time.monotonic() - t0) * 1000)

        tax = load_taxonomy()
        payload = {
            **result,
            "taxonomy_version": tax.version,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "duration_ms": duration_ms,
        }
        _put(cache_key, payload)
        return payload

    @router.get("/api/lattice/language")
    def get_language() -> Dict[str, Any]:
        """Introspect current active language + available values."""
        return {
            "active": runtime.get_effective_language(),
            "override": runtime.get_language_override(),
            "yaml_default": load_taxonomy().output_language,
            "available": list(spec.OUTPUT_LANGUAGES),
        }

    @router.post("/api/lattice/language")
    def set_language(lang: str = Query(...)) -> Dict[str, Any]:
        """Set a runtime language override. Pass `clear` to revert
        to the YAML default.

        V8: all downstream caches (narrative, calls, router) are
        keyed by the effective language, so toggling is just a
        pointer flip — no cache clearing. First fetch in each
        language pays the LLM cost; every subsequent toggle between
        already-seen languages is a cache hit (near-instant).
        """
        try:
            active = runtime.set_language_override(lang)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return {
            "active": active,
            "override": runtime.get_language_override(),
            "yaml_default": load_taxonomy().output_language,
        }

    @router.get("/api/lattice/selfcheck")
    def selfcheck(project_id: str = Query(...)) -> Dict[str, Any]:
        """V10·A2: live integrity check over the current lattice.
        Runs every documented invariant against live output; returns
        a structured pass/fail report per check. The UI surfaces
        this as a ✓/⚠ badge — click to see details."""
        if project_id not in investment_projects.list_projects():
            raise HTTPException(404, f"project {project_id!r} is not registered")
        try:
            return run_selfcheck(project_id)
        except Exception as exc:
            logger.exception("selfcheck failed")
            raise HTTPException(502, f"selfcheck failed: {exc}")

    @router.get("/api/lattice/budgets")
    def get_budgets() -> Dict[str, Any]:
        """V9: introspect current effective layer budgets + the YAML
        default + whether an override is active. The UI reads this to
        populate its knob panel."""
        from dataclasses import asdict
        from agent.finance.lattice.taxonomy import load_taxonomy
        effective = runtime.get_effective_budgets()
        override = runtime.get_budget_override()
        yaml_default = load_taxonomy().layer_budgets
        return {
            "effective": asdict(effective),
            "override": asdict(override) if override is not None else None,
            "yaml_default": asdict(yaml_default),
            "effective_hash": runtime.budget_hash(effective),
        }

    @router.post("/api/lattice/budgets")
    def set_budgets(payload: Dict[str, Any]) -> Dict[str, Any]:
        """V9: set (or clear, by sending `{}` / `{"clear": true}`) a
        runtime budget override. The body mirrors the YAML schema:

            {"themes": {"max_items": 7},
             "calls":  {"max_items": 3, "mmr_lambda": 0.5}}

        Cache keys include budget_hash, so switching budgets is a
        rekey (other budgets' cached payloads survive, instant on
        flip-back). Only *fresh* generation paths will actually call
        the LLM — a budget already seen this process is an in-memory
        hit.
        """
        from dataclasses import asdict
        if payload.get("clear"):
            payload = {}
        # Strip the `clear` sentinel if present alongside real data.
        raw = {k: v for k, v in payload.items() if k != "clear"}
        try:
            effective = runtime.set_budget_override(raw if raw else None)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return {
            "effective": asdict(effective),
            "override": (asdict(runtime.get_budget_override())
                         if runtime.get_budget_override() is not None else None),
            "effective_hash": runtime.budget_hash(effective),
        }

    @router.get("/api/lattice/trace/{node_id}")
    def get_trace(
        node_id: str,
        project_id: str = Query(...),
    ) -> Dict[str, Any]:
        """V6 deep-trace: returns the full LLM conversation + validator
        outcome + candidate pool for a specific node.

        Dispatch by node_id prefix:
          - theme_*     → narrative LLM trace
          - subtheme_*  → note: sub-themes are deterministic (no LLM)
          - call_*      → per-call origin trace + shared pool trace
          - obs_*       → note: observations are deterministic
          - widget:*    → note: external widget (L0)

        404 when the trace has expired (TTL) or was never captured
        (e.g., served from cache on the request that's asking;
        re-fetch /api/lattice/calls?fresh=1 to populate)."""
        if project_id not in investment_projects.list_projects():
            raise HTTPException(404, f"project {project_id!r} is not registered")

        if node_id.startswith("theme_"):
            trace = get_narrative_trace(node_id)
            if trace is None:
                raise HTTPException(404, (
                    f"no trace captured for {node_id}. "
                    "Trace is populated when the narrative is freshly "
                    "generated; if it expired or was served from cache, "
                    "re-fetch /api/lattice/calls?fresh=1 and try again."
                ))
            return {"node_id": node_id, "layer": "L2", "trace": trace}

        if node_id.startswith("subtheme_"):
            return {
                "node_id": node_id, "layer": "L1.5",
                "trace": {
                    "kind": "deterministic",
                    "note": "Sub-themes are produced by a pure tag-intersection "
                            "cluster — same math as themes, but without the LLM "
                            "narrative step. There is no LLM conversation to show. "
                            "Click the incoming membership edges from L1 to see "
                            "the Jaccard breakdown per observation.",
                },
            }

        if node_id.startswith("call_"):
            per_call = get_call_trace(node_id)
            pool = get_call_pool_trace()
            if per_call is None and pool is None:
                raise HTTPException(404, (
                    f"no trace captured for {node_id}. Re-fetch "
                    "/api/lattice/calls?fresh=1 to populate."
                ))
            return {
                "node_id": node_id, "layer": "L3",
                "trace": {
                    "kind": "llm+mmr",
                    "per_call": per_call,
                    "pool": pool,
                },
            }

        if node_id.startswith("obs_"):
            return {
                "node_id": node_id, "layer": "L1",
                "trace": {
                    "kind": "deterministic",
                    "note": "Observations are emitted by deterministic Python "
                            "generators. See the upstream L0 source widget via "
                            "the source_emission edge (the generator function "
                            "and the specific widget field are in that edge's "
                            "computation detail).",
                },
            }

        if node_id.startswith("widget:"):
            return {
                "node_id": node_id, "layer": "L0",
                "trace": {
                    "kind": "source",
                    "note": f"{node_id!r} is an external widget (dashboard "
                            "synthesis input). Its values flow into L1 via "
                            "specific generator functions.",
                },
            }

        raise HTTPException(404, f"unknown node_id shape: {node_id!r}")

    @router.get("/api/lattice/graph")
    def list_graph(
        project_id: str = Query(...),
        fresh: bool = Query(False),
    ) -> Dict[str, Any]:
        """Structural view of the lattice — pure transformation of
        /api/lattice/calls. Designed for V3 visualisation: each node
        carries provenance (computed_by ∈ spec.PROVENANCE_KINDS),
        each edge carries a computation breakdown that the V4
        invariant tests recompute via spec.final_membership_weight
        to prove the graph cannot drift from the underlying formula.
        """
        if project_id not in investment_projects.list_projects():
            raise HTTPException(404, f"project {project_id!r} is not registered")

        lang = runtime.get_effective_language()
        bh = runtime.budget_hash(runtime.get_effective_budgets())
        cache_key = f"graph::{lang}::{bh}::{project_id}"
        if not fresh:
            cached = _cached(cache_key)
            if cached is not None:
                return cached

        t0 = time.monotonic()
        try:
            calls_payload = build_calls(project_id, fresh=fresh)
            # V10·A3: pipe widget payloads onto L0 nodes so trace UI
            # can show what the source widgets actually returned.
            from agent.finance.lattice.observations import get_last_widget_payloads
            widget_payloads = get_last_widget_payloads(project_id)
            graph = build_graph(calls_payload, widget_payloads=widget_payloads)
        except Exception as exc:
            logger.exception("lattice graph failed")
            raise HTTPException(502, f"graph build failed: {exc}")
        duration_ms = int((time.monotonic() - t0) * 1000)

        tax = load_taxonomy()
        graph.setdefault("meta", {})
        graph["meta"].update({
            "taxonomy_version": tax.version,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "duration_ms": duration_ms,
        })
        _put(cache_key, graph)
        return graph

    @router.get("/api/lattice/snapshots")
    def list_snapshot_dates(project_id: str = Query(...)) -> Dict[str, Any]:
        """V8: list every archived daily snapshot for a project,
        newest first. Populated automatically whenever /calls runs
        with fresh=1. Empty list is a valid response (new install,
        nothing built yet)."""
        if project_id not in investment_projects.list_projects():
            raise HTTPException(404, f"project {project_id!r} is not registered")
        return {"project_id": project_id, "snapshots": list_snapshots(project_id)}

    @router.get("/api/lattice/snapshot")
    def get_snapshot(
        project_id: str = Query(...),
        date: str = Query(..., description="YYYY-MM-DD"),
    ) -> Dict[str, Any]:
        """V8: return the archived lattice for a specific day.
        404 when no snapshot exists for that date (the UI should
        offer to run a live refresh instead)."""
        if project_id not in investment_projects.list_projects():
            raise HTTPException(404, f"project {project_id!r} is not registered")
        envelope = read_snapshot(project_id, date)
        if envelope is None:
            raise HTTPException(404, f"no lattice snapshot for {date}")
        # Return the stored payload plus a `historical` marker so the
        # UI can render a banner without having to diff against live.
        envelope["payload"]["historical"] = True
        envelope["payload"]["snapshot_date"] = date
        envelope["payload"]["recorded_at"] = (
            envelope.get("snapshot_meta", {}).get("recorded_at")
        )
        return envelope["payload"]

    @router.get("/api/lattice/calls")
    def list_calls(
        project_id: str = Query(...),
        fresh: bool = Query(False),
    ) -> Dict[str, Any]:
        if project_id not in investment_projects.list_projects():
            raise HTTPException(404, f"project {project_id!r} is not registered")

        lang = runtime.get_effective_language()
        bh = runtime.budget_hash(runtime.get_effective_budgets())
        cache_key = f"calls::{lang}::{bh}::{project_id}"
        if not fresh:
            cached = _cached(cache_key)
            if cached is not None:
                return cached

        t0 = time.monotonic()
        try:
            result = build_calls(project_id, fresh=fresh)
        except Exception as exc:
            logger.exception("lattice calls failed")
            raise HTTPException(502, f"calls build failed: {exc}")
        duration_ms = int((time.monotonic() - t0) * 1000)

        tax = load_taxonomy()
        payload = {
            **result,
            "taxonomy_version": tax.version,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "duration_ms": duration_ms,
        }
        _put(cache_key, payload)
        return payload

    return router
