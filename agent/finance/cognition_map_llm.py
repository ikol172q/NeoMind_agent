"""Cognition Map — LLM intelligence layer (L3, req3 connect + req8 expand).

Two analysis endpoints, both bound by hard rules:

* **混合路由 (privacy):** map content is personal, so calls default to the
  LOCAL MLX model (via the router). Cloud is used ONLY when the caller passes
  ``allow_cloud=True`` — otherwise, if the local model is unreachable, we fail
  loudly rather than silently shipping personal notes to a cloud vendor.

* **LLM never auto-writes (candidate zone stays user-controlled):** connect and
  expand *return suggestions*; they never create nodes or edges. The user
  applies a suggestion via the normal /node or /link endpoints, where it lands
  as an 🔴 unverified candidate. This keeps the anti-hallucination contract:
  nothing an LLM produces is ever silently promoted.

* **expand proposes questions, not facts:** per the anti-hallucination house
  rule, the LLM is asked for *adjacent topics / questions worth investigating*,
  never for numeric claims or sources. Grounding happens later via
  cognition_map_selfcheck.ground_claim against real fetched bytes.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

import httpx

from agent.finance.cognition_map import CognitionMap, EDGE_TYPES

logger = logging.getLogger(__name__)

LOCAL_MODEL = "mlx-community/Qwen3-30B-A3B-Instruct-2507-4bit"
CLOUD_MODEL = os.getenv("LLM_ROUTER_MODEL") or "deepseek-v4-flash"


class LocalModelUnavailable(RuntimeError):
    """Raised when the local MLX model can't be reached and cloud was not allowed."""


def _parse_json_robust(text: str) -> Dict[str, Any]:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-z]*\n?|\n?```$", "", t).strip()
    try:
        return json.loads(t)
    except Exception:
        m = re.search(r"\{.*\}", t, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise ValueError("LLM did not return parseable JSON")


def _call(system: str, user: str, allow_cloud: bool, max_tokens: int = 1200) -> Dict[str, Any]:
    base = (os.getenv("LLM_ROUTER_BASE_URL") or "http://127.0.0.1:8000/v1").rstrip("/")
    key = (os.getenv("LLM_ROUTER_API_KEY") or os.getenv("OPENAI_API_KEY") or "sk-local")
    model = CLOUD_MODEL if allow_cloud else LOCAL_MODEL
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "max_tokens": max_tokens, "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    try:
        with httpx.Client(timeout=httpx.Timeout(60.0)) as c:
            r = c.post(f"{base}/chat/completions",
                       headers={"Authorization": f"Bearer {key}"}, json=body)
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
    except (httpx.HTTPError, KeyError, IndexError) as e:
        if not allow_cloud:
            raise LocalModelUnavailable(
                f"本地模型 {LOCAL_MODEL} 不可达 ({e}). 启动 MLX(:8100), "
                f"或显式传 allow_cloud=true 走云端(个人内容将发送到云模型)。")
        raise
    out = _parse_json_robust(content)
    out["_model_used"] = model
    return out


def _existing_path(cm: CognitionMap, a: str, b: str, max_depth: int = 4) -> Optional[List[Dict[str, str]]]:
    """Deterministic BFS over existing typed edges — does the map already link a→b?"""
    graph = cm.graph()
    adj: Dict[str, List[Dict[str, str]]] = {}
    for e in graph["edges"]:
        adj.setdefault(e["source_id"], []).append({"to": e["target_id"], "rel": e["rel"]})
    if a == b:
        return []
    seen = {a}
    queue: List[tuple] = [(a, [])]
    for _ in range(max_depth):
        nxt = []
        for cur, path in queue:
            for edge in adj.get(cur, []):
                np = path + [{"from": cur, "to": edge["to"], "rel": edge["rel"]}]
                if edge["to"] == b:
                    return np
                if edge["to"] not in seen:
                    seen.add(edge["to"])
                    nxt.append((edge["to"], np))
        queue = nxt
        if not queue:
            break
    return None


def connect_nodes(project_id: str, a_id: str, b_id: str,
                  allow_cloud: bool = False) -> Dict[str, Any]:
    """Analyse the relationship between two existing nodes (req3).

    Returns a *suggestion* (typed edge + reason); never persists. The user
    applies it via POST /api/map/link, where it lands as an unverified edge.
    """
    cm = CognitionMap(project_id)
    a, b = cm.get(a_id), cm.get(b_id)
    if a is None or b is None:
        return {"ok": False, "reason": "node_not_found"}
    existing = _existing_path(cm, a_id, b_id)
    system = (
        "你在分析用户个人认知图谱里【两个已存在节点】之间的关系。你的任务是【分类关系】，"
        "不是编造外部事实。只能从给定的边类型词表里选 rel。\n"
        f"边类型: {json.dumps(EDGE_TYPES, ensure_ascii=False)}\n"
        '只输出 JSON: {"rel": <边类型>, "direction": "a_to_b"|"b_to_a", '
        '"weight": 0.1-1.0, "reason": "<简短中文解释，只基于给定内容>"}'
    )
    user = (
        f"节点A (id={a_id}): 标题《{a['title']}》\n正文: {a.get('body','')[:600]}\n\n"
        f"节点B (id={b_id}): 标题《{b['title']}》\n正文: {b.get('body','')[:600]}"
    )
    try:
        sug = _call(system, user, allow_cloud)
    except LocalModelUnavailable as e:
        return {"ok": False, "reason": "local_model_unavailable", "detail": str(e)}
    rel = sug.get("rel")
    if rel not in EDGE_TYPES:
        return {"ok": False, "reason": "llm_invalid_rel", "raw": sug}
    return {
        "ok": True, "model_used": sug.get("_model_used"),
        "existing_path": existing,
        "suggestion": {
            "source_id": a_id if sug.get("direction") != "b_to_a" else b_id,
            "target": b_id if sug.get("direction") != "b_to_a" else a_id,
            "rel": rel,
            "weight": max(0.1, min(1.0, float(sug.get("weight", 0.5)))),
            "reason": str(sug.get("reason", ""))[:400],
            "state": "unverified",
        },
    }


def expand_node(project_id: str, node_id: str,
                allow_cloud: bool = False) -> Dict[str, Any]:
    """Propose adjacent concepts/questions the map is missing (req8).

    Returns *titles + why* only — never facts/numbers/sources, never persists.
    The user adds the ones they want via POST /api/map/node (→ unverified).
    """
    cm = CognitionMap(project_id)
    node = cm.get(node_id)
    if node is None:
        return {"ok": False, "reason": "node_not_found"}
    existing_titles = [r["title"] for r in cm.list_nodes()][:80]
    system = (
        "你在帮用户【拓展个人认知图谱的边界】。给定一个焦点概念，提出 3-5 个【相关、但图谱里"
        "还没有】的概念或【值得调研的问题】。\n"
        "严禁: 不要给出任何具体数字、百分比、统计、来源链接或断言性事实——那是幻觉重灾区。"
        "只给【概念标题】和【为什么值得加】。事实留给用户之后用真实来源去 ground。\n"
        '只输出 JSON: {"suggestions": [{"title": "<概念/问题标题>", "type": '
        '"concept|event|entity|claim", "why": "<简短中文，为什么补这个>"}]}'
    )
    user = (
        f"焦点节点《{node['title']}》\n正文: {node.get('body','')[:600]}\n\n"
        f"图谱已有节点(避免重复): {json.dumps(existing_titles, ensure_ascii=False)}"
    )
    try:
        out = _call(system, user, allow_cloud)
    except LocalModelUnavailable as e:
        return {"ok": False, "reason": "local_model_unavailable", "detail": str(e)}
    raw = out.get("suggestions")
    if not isinstance(raw, list):
        return {"ok": False, "reason": "llm_invalid_output", "raw": out}
    have = {t.strip().lower() for t in existing_titles}
    suggestions = []
    for s in raw:
        if not isinstance(s, dict) or not s.get("title"):
            continue
        title = str(s["title"]).strip()
        if title.lower() in have:
            continue  # drop anything the map already has
        suggestions.append({
            "title": title,
            "type": s.get("type") if s.get("type") in ("concept", "event", "entity", "claim") else "concept",
            "why": str(s.get("why", ""))[:300],
            "origin": "llm-expand", "provenance_state": "unverified",
        })
    return {"ok": True, "model_used": out.get("_model_used"), "suggestions": suggestions}
