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
from agent.finance.lattice.observations import build_observations, build_observations_run
from agent.finance.lattice.selfcheck import run_selfcheck
from agent.finance.lattice.snapshots import list_runs_for_date, list_snapshots, read_snapshot
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

        # B5-L1: the strict ``dep_hash`` cache replaces the old 60s
        # in-process TTL cache for L1 observations.  We still keep the
        # surrounding payload keys (count, observations, taxonomy_version,
        # theme_signatures, fetched_at, duration_ms) for backwards
        # compatibility, and add a ``run_meta`` block carrying
        # (dep_hash, compute_run_id, cache_hit, started_at, completed_at,
        # taxonomy_version, code_git_sha, pipeline_version, inputs_summary).
        # The UI breadcrumb reads run_meta to show "this view was
        # produced by compute_run_id … hashing N raw inputs to
        # dep_hash …" — exactly the data-coherence story the design
        # doc spells out.

        t0 = time.monotonic()
        try:
            rows, run_meta = build_observations_run(project_id, fresh=fresh)
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
            "run_meta": run_meta,
        }
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
        project_id: str        = Query(...),
        fresh: bool            = Query(False),
        as_of: Optional[str]   = Query(None, description="'live' or YYYY-MM-DD"),
    ) -> Dict[str, Any]:
        """Structural view of the lattice — pure transformation of
        /api/lattice/calls. Designed for V3 visualisation: each node
        carries provenance (computed_by ∈ spec.PROVENANCE_KINDS),
        each edge carries a computation breakdown that the V4
        invariant tests recompute via spec.final_membership_weight
        to prove the graph cannot drift from the underlying formula.

        Phase A: when ``as_of`` is set, build the graph from that
        date's snapshot instead of live build_calls. Widget payloads
        for L0 nodes also come from the snapshot if present (V10·A3
        captured them inline); otherwise L0 nodes lack raw_payload
        for historical views — UI tolerates missing payloads.
        """
        if project_id not in investment_projects.list_projects():
            raise HTTPException(404, f"project {project_id!r} is not registered")

        # Phase A: historical replay path
        if as_of and as_of != "live":
            envelope = read_snapshot(project_id, as_of)
            if envelope is None:
                raise HTTPException(
                    404,
                    f"no lattice snapshot for {as_of}; pick a different "
                    f"date (see /api/lattice/snapshots) or refresh live."
                )
            calls_payload = envelope.get("payload", {}) or {}
            try:
                graph = build_graph(calls_payload, widget_payloads={})
            except Exception as exc:
                logger.exception("lattice graph (historical) failed")
                raise HTTPException(502, f"graph build failed: {exc}")
            tax = load_taxonomy()
            graph.setdefault("meta", {})
            meta = envelope.get("snapshot_meta", {}) or {}
            graph["meta"].update({
                "taxonomy_version": tax.version,
                "historical":       True,
                "snapshot_date":    as_of,
                "snapshot_run_id":  meta.get("run_id"),
                "recorded_at":      meta.get("recorded_at"),
            })
            return graph

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
        run_id: Optional[str] = Query(
            None, description="optional — when omitted, returns the latest run for that date",
        ),
    ) -> Dict[str, Any]:
        """V8.1: return the archived lattice for a specific day, or
        a specific RUN within a day. 404 when the date has no
        snapshots, or when run_id is given but doesn't match.
        """
        if project_id not in investment_projects.list_projects():
            raise HTTPException(404, f"project {project_id!r} is not registered")
        envelope = read_snapshot(project_id, date, run_id=run_id)
        if envelope is None:
            who = f"{date} run_id={run_id}" if run_id else date
            raise HTTPException(404, f"no lattice snapshot for {who}")
        # Decorate the payload with historical markers so the UI can
        # render a banner without diffing against live state.
        envelope["payload"]["historical"]      = True
        envelope["payload"]["snapshot_date"]   = date
        meta = envelope.get("snapshot_meta", {}) or {}
        envelope["payload"]["recorded_at"]     = meta.get("recorded_at")
        envelope["payload"]["snapshot_run_id"] = meta.get("run_id")
        return envelope["payload"]

    @router.get("/api/lattice/runs-for-date")
    def list_runs_for_one_date(
        project_id: str = Query(...),
        date: str       = Query(..., description="YYYY-MM-DD"),
    ) -> Dict[str, Any]:
        """V8.1: every snapshot run we have for one date, newest first.
        Powers the per-date 'version dropdown' so the operator can
        pick a specific re-run instead of just 'latest'."""
        if project_id not in investment_projects.list_projects():
            raise HTTPException(404, f"project {project_id!r} is not registered")
        runs = list_runs_for_date(project_id, date)
        return {
            "project_id": project_id,
            "date":       date,
            "count":      len(runs),
            "runs":       runs,
        }

    @router.get("/api/lattice/calls")
    def list_calls(
        project_id: str        = Query(...),
        fresh: bool            = Query(False),
        as_of: Optional[str]   = Query(None, description="'live' or YYYY-MM-DD"),
    ) -> Dict[str, Any]:
        if project_id not in investment_projects.list_projects():
            raise HTTPException(404, f"project {project_id!r} is not registered")

        # Phase A: historical replay — when as_of is set, pull the
        # archived /calls payload for that date instead of live.
        if as_of and as_of != "live":
            envelope = read_snapshot(project_id, as_of)
            if envelope is None:
                raise HTTPException(
                    404,
                    f"no lattice snapshot for {as_of}; pick a different "
                    f"date (see /api/lattice/snapshots) or refresh live."
                )
            payload = envelope.get("payload", {}) or {}
            payload["historical"]      = True
            payload["snapshot_date"]   = as_of
            meta = envelope.get("snapshot_meta", {}) or {}
            payload["recorded_at"]     = meta.get("recorded_at")
            payload["snapshot_run_id"] = meta.get("run_id")
            return payload

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
