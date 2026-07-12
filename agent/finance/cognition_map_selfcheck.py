"""Cognition Map — verification / self-check layer (L2, req7).

Two responsibilities, both honest about what "verified" can mean:

1. **selfcheck(project_id)** — a *deterministic* scan (no LLM, no embeddings)
   that surfaces what needs a human's attention: unsourced claims, stale
   nodes, dangling source/edge refs, un-promoted LLM candidates, and explicit
   contradictions.  It does NOT make anything "correct" — it flags.

2. **ground_claim(project_id, node_id, url, phrase)** — the promotion gate.
   Fetches the url into RawStore (raw://<sha256>) and promotes the node only
   if ``phrase`` appears *literally* in the fetched bytes.  This reuses the
   strategies auditor's fetch + the same "substring must exist" mechanic, so
   an LLM (or a human in a hurry) can never bless a claim that isn't actually
   in a real source.  Mirrors the anti-hallucination house rule.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from agent.finance.cognition_map import CognitionMap, TRUSTED_PROVENANCE_STATES
# Reuse the auditor's fetch→RawStore helper. We do NOT reuse its _read_blob_text:
# that uses read_blob_bytes() which returns the raw .warc.gz *envelope*, so the
# substring check would run against gzip bytes and always miss. We read the
# decoded HTTP body via read_blob() instead.
from agent.finance.strategies.auditor import _fetch_into_rawstore

logger = logging.getLogger(__name__)


def _blob_text(raw_ref: str, project_id: str) -> str:
    """Resolve raw://<sha256> to the decoded HTTP response body (not the gzip
    WARC envelope) so substring grounding works on gzip-served pages."""
    from agent.finance.raw_store import RawStore
    from agent.finance.raw_store.blobs import read_blob
    sha = raw_ref.replace("raw://", "")
    store = RawStore.for_project(project_id)
    _meta, body = read_blob(store.raw_root, sha)
    return body.decode("utf-8", errors="replace")

STALE_DAYS_DEFAULT = 90
_WS_RE = re.compile(r"\s+")


def _norm(s: str) -> str:
    """Whitespace-collapsed text for a tolerant-but-literal substring check.

    We deliberately do NOT lowercase or strip punctuation: the phrase must
    really be in the bytes.  Only whitespace runs are normalised (web HTML
    is noisy with newlines/tabs)."""
    return _WS_RE.sub(" ", s).strip()


# ── self-check scanner ────────────────────────────────────────────────

def selfcheck(project_id: str, stale_days: int = STALE_DAYS_DEFAULT) -> Dict[str, Any]:
    """Scan every node; return a flat list of issues + counts by severity."""
    cm = CognitionMap(project_id)
    rows = cm.list_nodes()
    node_ids = {r["id"] for r in rows}
    issues: List[Dict[str, Any]] = []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=stale_days)).date().isoformat()

    def add(node_id: str, title: str, severity: str, kind: str, detail: str) -> None:
        issues.append({"node_id": node_id, "title": title,
                       "severity": severity, "kind": kind, "detail": detail})

    for row in rows:
        node = cm.get(row["id"])
        if node is None:
            continue
        nid, title = node["id"], node["title"]
        state = node["provenance"]["state"]
        trusted = state in TRUSTED_PROVENANCE_STATES

        # Claim with no grounding and not yet trusted.
        if node["type"] == "claim" and not node["sources"] and not trusted:
            add(nid, title, "warn", "unsourced_claim",
                "claim 节点没有任何 raw:// 来源，且未验证")

        # LLM/chat candidate that has never been reviewed.
        if node["origin"] in ("llm-expand", "chat") and state == "unverified":
            add(nid, title, "info", "unreviewed_candidate",
                f"来自 {node['origin']} 的候选节点仍在 🔴 候选区，未晋升")

        # Stale: not checked in a long time (AI facts rot fast).
        if (node.get("last_checked") or "") < cutoff:
            add(nid, title, "info", "stale",
                f"last_checked={node.get('last_checked')} 早于 {stale_days} 天阈值")

        # Dangling source: a raw:// ref that no longer resolves in RawStore.
        for ref in node["sources"]:
            try:
                _blob_text(ref, project_id)
            except Exception:
                add(nid, title, "warn", "dangling_source",
                    f"来源 {ref[:20]}… 在 RawStore 中无法解析")

        # Edges: dangling target, unverified edge, explicit contradiction.
        for e in node["edges"]:
            if e["target"] not in node_ids:
                add(nid, title, "warn", "dangling_edge",
                    f"边 {e['rel']}→{e['target']} 指向不存在的节点")
            if e["rel"] == "contradicts":
                add(nid, title, "info", "contradiction",
                    f"与 {e['target']} 存在 contradicts 边 — 需人工裁决信念冲突")
            elif e["state"] == "unverified":
                add(nid, title, "info", "unverified_edge",
                    f"边 {e['rel']}→{e['target']} 未验证")

    counts: Dict[str, int] = {}
    for it in issues:
        counts[it["severity"]] = counts.get(it["severity"], 0) + 1
    by_kind: Dict[str, int] = {}
    for it in issues:
        by_kind[it["kind"]] = by_kind.get(it["kind"], 0) + 1

    return {
        "project_id": project_id,
        "node_count": len(rows),
        "issue_count": len(issues),
        "by_severity": counts,
        "by_kind": by_kind,
        "issues": issues,
    }


# ── grounding / promotion gate ────────────────────────────────────────

def _apply_grounding(cm: CognitionMap, node: Dict[str, Any], raw_ref: str,
                     blob_text: str, phrase: str) -> Dict[str, Any]:
    """Promote a node iff ``phrase`` is literally present in ``blob_text``.

    Pure (no network) so it's unit-testable.  On success appends the raw://
    ref and lifts the node to ``rawstore_grounded`` (its source is a real
    fetched blob that verbatim contains the phrase).  On failure the node is
    left untouched — honest: an unverifiable claim stays unverified.
    """
    if _norm(phrase) and _norm(phrase) in _norm(blob_text):
        if raw_ref not in node["sources"]:
            node["sources"].append(raw_ref)
        node["provenance"]["state"] = "rawstore_grounded"
        node["provenance"]["source"] = f"grounded: phrase verbatim in {raw_ref}"
        node["last_checked"] = datetime.now(timezone.utc).date().isoformat()
        cm.save(node)
        return {"ok": True, "node_id": node["id"], "state": "rawstore_grounded",
                "raw_ref": raw_ref}
    return {"ok": False, "node_id": node["id"], "reason": "phrase_not_found_verbatim",
            "raw_ref": raw_ref}


def ground_claim(project_id: str, node_id: str, url: str, phrase: str) -> Dict[str, Any]:
    """Fetch ``url`` into RawStore, then promote ``node_id`` only if ``phrase``
    appears verbatim in the fetched bytes."""
    cm = CognitionMap(project_id)
    node = cm.get(node_id)
    if node is None:
        return {"ok": False, "reason": "node_not_found"}
    raw_ref = _fetch_into_rawstore(url, project_id)
    if not raw_ref:
        return {"ok": False, "reason": "fetch_failed", "url": url}
    blob_text = _blob_text(raw_ref, project_id)
    return _apply_grounding(cm, node, raw_ref, blob_text, phrase)
