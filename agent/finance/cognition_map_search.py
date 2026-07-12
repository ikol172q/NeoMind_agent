"""Cognition Map — semantic search + similar-node discovery (Phase 5).

Embeds each node's title+body with a local sentence-transformer (MiniLM,
384-d) and uses FAISS for cosine similarity. Everything stays local — no
embedding API, so personal-map content never leaves the machine.

Index is built in-memory per project and rebuilt only when the node set
changes (cheap signature check), so for personal scale (hundreds of nodes)
there's no persistence to keep consistent with the md source of truth.

Degrades gracefully: if faiss / sentence-transformers aren't installed,
search returns ``{"ok": False, "reason": "deps_unavailable"}`` and the UI
falls back to keyword search.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from typing import Any, Dict, List, Optional

from agent.finance.cognition_map import CognitionMap

logger = logging.getLogger(__name__)

try:
    import faiss  # type: ignore
    import numpy as np
    from sentence_transformers import SentenceTransformer  # type: ignore
    HAS_DEPS = True
except Exception:  # ImportError or any load failure
    HAS_DEPS = False

# Multilingual model — the user writes Chinese-with-English-terms, and the
# English-only all-MiniLM-L6-v2 mis-ranked Chinese queries badly. This one
# (50+ langs, 384-d) handles zh+en; same dim so FAISS code is unchanged.
_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
_model = None
_model_lock = threading.Lock()
_cache: Dict[str, Dict[str, Any]] = {}   # project_id -> {sig, index, ids}
_cache_lock = threading.Lock()


def _get_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                _model = SentenceTransformer(_MODEL_NAME)
    return _model


def _signature(rows: List[Dict[str, Any]]) -> str:
    """Cheap fingerprint of the node set; changes when any node is added,
    removed, or re-saved (updated_at moves)."""
    key = "|".join(f"{r['id']}:{r.get('updated_at','')}" for r in sorted(rows, key=lambda r: r["id"]))
    return hashlib.md5(key.encode("utf-8")).hexdigest()


def _ensure_index(cm: CognitionMap) -> Dict[str, Any]:
    rows = cm.list_nodes()
    sig = _signature(rows)
    with _cache_lock:
        cached = _cache.get(cm.project_id)
        if cached and cached["sig"] == sig:
            return cached
    # Rebuild from md (source of truth).
    ids: List[str] = []
    texts: List[str] = []
    for r in rows:
        node = cm.get(r["id"])
        if node is None:
            continue
        ids.append(node["id"])
        texts.append((node["title"] + "\n" + (node.get("body") or ""))[:1000])
    if texts:
        emb = _get_model().encode(texts, normalize_embeddings=True)
        emb = np.array(emb, dtype="float32")
        index = faiss.IndexFlatIP(emb.shape[1])
        index.add(emb)
    else:
        index = None
    entry = {"sig": sig, "index": index, "ids": ids}
    with _cache_lock:
        _cache[cm.project_id] = entry
    return entry


def _rows_by_id(cm: CognitionMap) -> Dict[str, Dict[str, Any]]:
    return {r["id"]: r for r in cm.list_nodes()}


def semantic_search(project_id: str, query: str, top_k: int = 10) -> Dict[str, Any]:
    if not HAS_DEPS:
        return {"ok": False, "reason": "deps_unavailable", "results": []}
    cm = CognitionMap(project_id)
    entry = _ensure_index(cm)
    if not entry["index"] or not query.strip():
        return {"ok": True, "results": []}
    q = np.array(_get_model().encode([query], normalize_embeddings=True), dtype="float32")
    k = min(top_k, len(entry["ids"]))
    scores, idxs = entry["index"].search(q, k)
    by_id = _rows_by_id(cm)
    results = []
    for s, i in zip(scores[0], idxs[0]):
        if i < 0:
            continue
        row = by_id.get(entry["ids"][i])
        if row:
            results.append({**row, "score": round(float(s), 4)})
    return {"ok": True, "results": results}


def similar_nodes(project_id: str, node_id: str, top_k: int = 8) -> Dict[str, Any]:
    """Find nodes semantically closest to a given node (excludes itself).

    Powers 'what in my map relates to this?' — a grounding-free discovery
    complement to the LLM connect/expand tools.
    """
    if not HAS_DEPS:
        return {"ok": False, "reason": "deps_unavailable", "results": []}
    cm = CognitionMap(project_id)
    node = cm.get(node_id)
    if node is None:
        return {"ok": False, "reason": "node_not_found", "results": []}
    query = node["title"] + "\n" + (node.get("body") or "")
    out = semantic_search(project_id, query, top_k=top_k + 1)
    out["results"] = [r for r in out.get("results", []) if r["id"] != node_id][:top_k]
    return out
