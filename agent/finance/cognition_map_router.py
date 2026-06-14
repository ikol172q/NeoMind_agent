"""FastAPI routes for the Cognition Map (L1).

Thin HTTP layer over :class:`agent.finance.cognition_map.CognitionMap`.
All endpoints are project-scoped via ``?project_id=`` (data-firewall), same
convention as the other finance routers.  Request bodies are plain dicts —
``CognitionMap.normalise_node`` is the authoritative validator/gate, so the
router stays thin and the anti-hallucination rules live in one place.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import Response

from agent.finance.cognition_map import (
    CognitionMap,
    EDGE_TYPES,
    LENSES,
    NODE_TYPES,
    CONFIDENCE_LEVELS,
    PROVENANCE_STATES,
    TRUSTED_PROVENANCE_STATES,
)
from agent.finance.investment_projects import InvestmentPathError


def _map(project_id: str) -> CognitionMap:
    try:
        return CognitionMap(project_id)
    except InvestmentPathError as e:
        raise HTTPException(400, str(e))


def build_cognition_map_router() -> APIRouter:
    router = APIRouter(prefix="/api/map", tags=["cognition-map"])

    @router.get("/meta")
    def meta() -> Dict[str, Any]:
        """Vocabularies the frontend needs to render pickers + legends."""
        return {
            "node_types": list(NODE_TYPES),
            "edge_types": EDGE_TYPES,
            "lenses": {k: list(v) for k, v in LENSES.items()},
            "confidence_levels": list(CONFIDENCE_LEVELS),
            "provenance_states": list(PROVENANCE_STATES),
            "trusted_states": list(TRUSTED_PROVENANCE_STATES),
        }

    @router.get("/nodes")
    def list_nodes(
        project_id: str = Query(...),
        state: Optional[str] = Query(None, description="filter by provenance state"),
        trusted_only: bool = Query(False),
    ) -> Dict[str, Any]:
        cm = _map(project_id)
        items = cm.list_nodes(prov_state=state, trusted_only=trusted_only)
        return {"project_id": project_id, "items": items, "n": len(items)}

    @router.get("/node")
    def get_node(project_id: str = Query(...), id: str = Query(...)) -> Dict[str, Any]:
        cm = _map(project_id)
        node = cm.get(id)
        if node is None:
            raise HTTPException(404, f"node {id!r} not found")
        return node

    @router.post("/node")
    def save_node(project_id: str = Query(...),
                  node: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        if not str(node.get("title") or "").strip():
            raise HTTPException(400, "node.title is required")
        cm = _map(project_id)
        return cm.save(node)

    @router.delete("/node")
    def delete_node(project_id: str = Query(...), id: str = Query(...)) -> Dict[str, Any]:
        cm = _map(project_id)
        if not cm.delete(id):
            raise HTTPException(404, f"node {id!r} not found")
        return {"ok": True, "deleted": id}

    @router.post("/link")
    def link(project_id: str = Query(...),
             body: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        src = body.get("source_id")
        tgt = body.get("target")
        rel = body.get("rel")
        if not (src and tgt and rel):
            raise HTTPException(400, "source_id, target, rel are required")
        if rel not in EDGE_TYPES:
            raise HTTPException(400, f"rel must be one of {sorted(EDGE_TYPES)}")
        cm = _map(project_id)
        ok = cm.link(src, tgt, rel,
                     weight=float(body.get("weight", 0.5)),
                     state=body.get("state", "unverified"),
                     note=body.get("note"))
        if not ok:
            raise HTTPException(404, f"source node {src!r} not found")
        return {"ok": True, "source_id": src, "target": tgt, "rel": rel}

    @router.get("/graph")
    def graph(project_id: str = Query(...),
              lens: Optional[str] = Query(None)) -> Dict[str, Any]:
        if lens and lens not in LENSES:
            raise HTTPException(400, f"lens must be one of {sorted(LENSES)}")
        cm = _map(project_id)
        return {"project_id": project_id, "lens": lens, **cm.graph(lens=lens)}

    @router.get("/history")
    def history(project_id: str = Query(...),
                id: Optional[str] = Query(None),
                limit: int = Query(50)) -> Dict[str, Any]:
        cm = _map(project_id)
        return {"project_id": project_id, "node_id": id,
                "commits": cm.history(node_id=id, limit=max(1, min(limit, 500)))}

    @router.post("/reindex")
    def reindex(project_id: str = Query(...)) -> Dict[str, Any]:
        cm = _map(project_id)
        return {"ok": True, "indexed": cm.rebuild_index()}

    @router.get("/selfcheck")
    def selfcheck_route(project_id: str = Query(...),
                        stale_days: int = Query(90)) -> Dict[str, Any]:
        from agent.finance.cognition_map_selfcheck import selfcheck
        try:
            return selfcheck(project_id, stale_days=max(1, stale_days))
        except InvestmentPathError as e:
            raise HTTPException(400, str(e))

    @router.post("/ground")
    def ground_route(project_id: str = Query(...),
                     body: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        """Promote a node iff `phrase` appears verbatim in fetched `url` bytes."""
        node_id = body.get("node_id")
        url = body.get("url")
        phrase = body.get("phrase")
        if not (node_id and url and phrase):
            raise HTTPException(400, "node_id, url, phrase are required")
        from agent.finance.cognition_map_selfcheck import ground_claim
        try:
            return ground_claim(project_id, node_id, url, phrase)
        except InvestmentPathError as e:
            raise HTTPException(400, str(e))

    @router.post("/connect")
    def connect_route(project_id: str = Query(...),
                      body: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        """LLM analyses the relationship between two nodes (req3). Returns a
        suggestion only — never persists. Personal content → local model unless
        body.allow_cloud is true."""
        a, b = body.get("a"), body.get("b")
        if not (a and b):
            raise HTTPException(400, "a and b (node ids) are required")
        from agent.finance.cognition_map_llm import connect_nodes
        try:
            return connect_nodes(project_id, a, b, bool(body.get("allow_cloud", False)))
        except InvestmentPathError as e:
            raise HTTPException(400, str(e))

    @router.get("/backup")
    def backup_route(project_id: str = Query(...)) -> Response:
        """Download a git bundle (full history, single file) of the vault."""
        cm = _map(project_id)
        try:
            data = cm.backup_bundle()
        except Exception as e:
            raise HTTPException(400, f"backup failed (vault may be empty): {e}")
        return Response(
            content=data, media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="cognition-{project_id}.bundle"'},
        )

    @router.get("/search")
    def search_route(project_id: str = Query(...), q: str = Query(...),
                     top_k: int = Query(10)) -> Dict[str, Any]:
        """Semantic search over node title+body (local embeddings)."""
        from agent.finance.cognition_map_search import semantic_search
        try:
            return semantic_search(project_id, q, top_k=max(1, min(top_k, 50)))
        except InvestmentPathError as e:
            raise HTTPException(400, str(e))

    @router.get("/similar")
    def similar_route(project_id: str = Query(...), node_id: str = Query(...),
                      top_k: int = Query(8)) -> Dict[str, Any]:
        """Nodes semantically closest to a given node."""
        from agent.finance.cognition_map_search import similar_nodes
        try:
            return similar_nodes(project_id, node_id, top_k=max(1, min(top_k, 50)))
        except InvestmentPathError as e:
            raise HTTPException(400, str(e))

    @router.post("/expand")
    def expand_route(project_id: str = Query(...),
                     body: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        """LLM proposes adjacent concepts/questions (req8). Titles only, no
        facts; never persists. Personal content → local model unless
        body.allow_cloud is true."""
        node_id = body.get("node_id")
        if not node_id:
            raise HTTPException(400, "node_id is required")
        from agent.finance.cognition_map_llm import expand_node
        try:
            return expand_node(project_id, node_id, bool(body.get("allow_cloud", False)))
        except InvestmentPathError as e:
            raise HTTPException(400, str(e))

    return router
