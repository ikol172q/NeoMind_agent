"""Chat entry into the fin persona fleet — dispatches a user message
to the live ``fin-rt`` worker and returns a task_id the client polls
via ``GET /api/tasks/{task_id}``.

This is the "most painful cut" for Phase 1 of the dashboard fusion
plan (plans/2026-04-19_fin_dashboard_fusion.md §3) — it eliminates
the need to drop out of the dashboard into Telegram or CLI to talk
to the agent.

Security posture:
- All input bound by length (``_MAX_MSG_LEN``) and a denylist of
  control characters except newline/tab.
- ``project_id`` is regex-validated against
  ``investment_projects._PROJECT_ID_RE`` and must be registered.
- Every chat turn is audit-logged to
  ``<investment_root>/<project>/chat_log/YYYY-MM-DD.jsonl`` —
  append-only JSONL with timestamp, input, task_id. The assistant
  reply is NOT duplicated into the audit log because the fleet
  transcript already persists it; we just record enough to join.
- No eval / exec / subprocess — we only construct a string and hand
  it to ``FleetBackend.dispatch_chat`` which goes through the
  existing supervisor dispatch path.

The HTTP contract is intentionally identical in shape to
``/api/analyze?use_fleet=true`` so the dashboard UI reuses the same
``/api/tasks/{id}`` polling loop.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query

from agent.finance import investment_projects

logger = logging.getLogger(__name__)

# Keep messages short enough that a single DeepSeek-R1 call fits with
# fleet-injected context. 4000 chars ≈ 1000 tokens — plenty for a chat
# prompt, still well under any model context.
_MAX_MSG_LEN = 4000

# Allow printable ascii + common unicode + newline + tab. Reject other
# control chars that could confuse logs or terminal rendering.
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _validate_message(msg: str) -> str:
    if not isinstance(msg, str):
        raise HTTPException(400, "message must be a string")
    stripped = msg.strip()
    if not stripped:
        raise HTTPException(400, "message is empty")
    if len(stripped) > _MAX_MSG_LEN:
        raise HTTPException(
            400,
            f"message too long ({len(stripped)} > {_MAX_MSG_LEN} chars)",
        )
    if _CONTROL_RE.search(stripped):
        raise HTTPException(400, "message contains control characters")
    return stripped


def _validate_project(project_id: str) -> str:
    if not isinstance(project_id, str) or not investment_projects._PROJECT_ID_RE.match(project_id):
        raise HTTPException(400, f"invalid project_id {project_id!r}")
    if project_id not in investment_projects.list_projects():
        raise HTTPException(404, f"project {project_id!r} is not registered")
    return project_id


def _chat_log_path(project_id: str) -> Path:
    """`<investment_root>/<project>/chat_log/YYYY-MM-DD.jsonl`.

    Goes through ``investment_projects.get_project_dir`` so the
    Investment-root data firewall applies.
    """
    proj = investment_projects.get_project_dir(project_id)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_dir = proj / "chat_log"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / f"{day}.jsonl"


def _audit_log(
    project_id: str,
    message: str,
    task_id: str,
    member: str,
) -> None:
    """Append one JSONL line per dispatched chat. Swallow IO errors —
    audit logging is best-effort and must not break the request."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "project_id": project_id,
        "member": member,
        "task_id": task_id,
        "message": message,
    }
    try:
        path = _chat_log_path(project_id)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:  # pragma: no cover — logging best effort
        logger.warning("chat_stream: audit log write failed: %s", exc)


def build_chat_prompt(message: str, project_id: str) -> str:
    """Wrap the raw user message with a small context preamble so the
    fin persona knows the project scope. Kept short so it doesn't
    dominate the prompt.
    """
    return (
        f"[fin-dashboard chat · project={project_id}]\n"
        f"The user is asking a free-form question in the fin dashboard. "
        f"Respond in the user's language, be concrete, and if they ask "
        f"for a signal return JSON matching AgentAnalysis; otherwise a "
        f"short paragraph is fine.\n\n"
        f"User: {message}"
    )


def build_chat_router(fleet: Any) -> APIRouter:
    """Expose ``POST /api/chat`` on the dashboard app.

    ``fleet`` is the ``FleetBackend`` instance already owned by the
    dashboard — we reuse it so chat and analyze share one fleet
    session / one audit trail / one task ring buffer.
    """
    router = APIRouter()

    @router.post("/api/chat")
    async def chat(
        project_id: str = Query(..., description="registered project id"),
        message: str = Query(..., description="user's chat message"),
    ) -> Dict[str, Any]:
        pid = _validate_project(project_id)
        msg = _validate_message(message)

        prompt = build_chat_prompt(msg, pid)
        try:
            task_id = await fleet.dispatch_chat(prompt, pid, original_message=msg)
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("chat dispatch failed")
            raise HTTPException(502, f"chat dispatch failed: {exc}")

        _audit_log(
            project_id=pid,
            message=msg,
            task_id=task_id,
            member=getattr(fleet, "member", "fin-rt"),
        )
        return {
            "project_id": pid,
            "task_id": task_id,
            "status": "pending",
            "kind": "chat",
        }

    @router.get("/api/chat/log")
    def read_log(
        project_id: str = Query(...),
        limit: int = Query(50, ge=1, le=500),
    ) -> Dict[str, Any]:
        pid = _validate_project(project_id)
        path = _chat_log_path(pid)
        if not path.exists():
            return {"project_id": pid, "entries": []}
        lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
        entries = []
        for ln in lines:
            try:
                entries.append(json.loads(ln))
            except Exception:
                continue
        return {"project_id": pid, "entries": entries}

    return router
