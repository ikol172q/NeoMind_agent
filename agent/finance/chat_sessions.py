"""Dashboard chat session persistence — per-project, append-only JSONL.

Separate concern from the existing Telegram-oriented ``chat_store.py``
(SQLite, int chat_id). Dashboard sessions are browser-scoped and use
string session ids, so they live in the Investment-root data firewall
instead of the global chat DB:

    <investment_root>/<project>/chat_sessions/<session_id>.jsonl

Each line is one message:
    {"role":"user|assistant|error","content":"...","ts":"...","req_id":"..."}

The first line also carries session-level metadata via ``meta`` block
so the list endpoint can show a preview without reading every file:
    {"meta": {"session_id":"...","created_at":"...","title":"first ~60 chars"}}

Endpoints:
    POST   /api/chat_sessions                  -> create
    GET    /api/chat_sessions                  -> list (newest first)
    GET    /api/chat_sessions/{session_id}     -> load messages
    POST   /api/chat_sessions/{session_id}/append -> append one message
    DELETE /api/chat_sessions/{session_id}     -> archive (rename .archived)

Security / safety:
- project_id validated through ``investment_projects``.
- session_id = 16-char hex, validated with regex; no path traversal.
- Append is best-effort (one write per turn), total file size capped
  at 2 MiB to bound worst case.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field

from agent.finance import investment_projects

logger = logging.getLogger(__name__)

_SESSION_ID_RE = re.compile(r"^[a-f0-9]{16}$")
_MAX_FILE_BYTES = 2 * 1024 * 1024  # 2 MiB per session
_MAX_CONTENT_LEN = 32_000          # per message
_VALID_ROLES = {"user", "assistant", "error", "system"}


def _validate_project(pid: str) -> str:
    if not isinstance(pid, str) or not investment_projects._PROJECT_ID_RE.match(pid):
        raise HTTPException(400, f"invalid project_id {pid!r}")
    if pid not in investment_projects.list_projects():
        raise HTTPException(404, f"project {pid!r} is not registered")
    return pid


def _validate_session_id(sid: str) -> str:
    if not _SESSION_ID_RE.match(sid):
        raise HTTPException(400, f"invalid session_id {sid!r}")
    return sid


def _sessions_dir(pid: str) -> Path:
    proj = investment_projects.get_project_dir(pid)
    d = proj / "chat_sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _session_path(pid: str, sid: str) -> Path:
    return _sessions_dir(pid) / f"{sid}.jsonl"


def _new_session_id() -> str:
    return secrets.token_hex(8)  # 16 hex chars


def _read_meta(path: Path) -> Optional[Dict[str, Any]]:
    """First line is the meta record. Returns None if unreadable."""
    try:
        with path.open("r", encoding="utf-8") as f:
            first = f.readline()
        if not first.strip():
            return None
        obj = json.loads(first)
        if isinstance(obj, dict) and "meta" in obj:
            return obj["meta"]
    except Exception as exc:
        logger.debug("chat_sessions: meta read failed for %s: %s", path, exc)
    return None


def _count_messages(path: Path) -> int:
    """Number of non-meta lines. Cheap-ish but not free — used only in list."""
    try:
        with path.open("rb") as f:
            return max(0, sum(1 for _ in f) - 1)
    except Exception:
        return 0


class CreateSessionReply(BaseModel):
    session_id: str
    created_at: str


class SessionSummary(BaseModel):
    session_id: str
    created_at: str
    updated_at: Optional[str] = None
    title: str = ""
    message_count: int = 0


class Message(BaseModel):
    role: str = Field(..., description="user | assistant | error | system")
    content: str
    ts: Optional[str] = None
    req_id: Optional[str] = None


def build_chat_sessions_router() -> APIRouter:
    router = APIRouter()

    @router.post("/api/chat_sessions")
    def create_session(project_id: str = Query(...)) -> CreateSessionReply:
        pid = _validate_project(project_id)
        sid = _new_session_id()
        path = _session_path(pid, sid)
        now = datetime.now(timezone.utc).isoformat()
        meta = {"session_id": sid, "created_at": now, "title": ""}
        with path.open("w", encoding="utf-8") as f:
            f.write(json.dumps({"meta": meta}, ensure_ascii=False) + "\n")
        return CreateSessionReply(session_id=sid, created_at=now)

    @router.get("/api/chat_sessions")
    def list_sessions(
        project_id: str = Query(...),
        limit: int = Query(50, ge=1, le=500),
    ) -> Dict[str, Any]:
        pid = _validate_project(project_id)
        d = _sessions_dir(pid)
        rows: List[SessionSummary] = []
        for p in d.glob("*.jsonl"):
            sid = p.stem
            if not _SESSION_ID_RE.match(sid):
                continue
            meta = _read_meta(p) or {}
            try:
                mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat()
            except Exception:
                mtime = None
            rows.append(SessionSummary(
                session_id=sid,
                created_at=meta.get("created_at", mtime or ""),
                updated_at=mtime,
                title=meta.get("title", "") or "",
                message_count=_count_messages(p),
            ))
        rows.sort(key=lambda r: r.updated_at or r.created_at, reverse=True)
        rows = rows[:limit]
        return {"project_id": pid, "count": len(rows), "sessions": [r.model_dump() for r in rows]}

    @router.get("/api/chat_sessions/{session_id}")
    def load_session(
        session_id: str,
        project_id: str = Query(...),
    ) -> Dict[str, Any]:
        pid = _validate_project(project_id)
        sid = _validate_session_id(session_id)
        path = _session_path(pid, sid)
        if not path.exists():
            raise HTTPException(404, f"session {sid!r} not found")
        messages: List[Dict[str, Any]] = []
        meta: Dict[str, Any] = {}
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if isinstance(obj, dict) and "meta" in obj:
                    meta = obj["meta"]
                    continue
                if isinstance(obj, dict) and obj.get("role") in _VALID_ROLES:
                    messages.append(obj)
        return {"project_id": pid, "session_id": sid, "meta": meta, "messages": messages}

    @router.post("/api/chat_sessions/{session_id}/append")
    def append_message(
        session_id: str,
        project_id: str = Query(...),
        message: Message = Body(...),
    ) -> Dict[str, Any]:
        pid = _validate_project(project_id)
        sid = _validate_session_id(session_id)
        if message.role not in _VALID_ROLES:
            raise HTTPException(400, f"invalid role {message.role!r}")
        if len(message.content) > _MAX_CONTENT_LEN:
            raise HTTPException(400, f"content too long ({len(message.content)} > {_MAX_CONTENT_LEN})")
        path = _session_path(pid, sid)
        if not path.exists():
            raise HTTPException(404, f"session {sid!r} not found")
        try:
            if path.stat().st_size >= _MAX_FILE_BYTES:
                raise HTTPException(413, "session full — start a new one")
        except OSError:
            pass

        entry = message.model_dump(exclude_none=True)
        entry.setdefault("ts", datetime.now(timezone.utc).isoformat())
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        # Update title on first user message (seed for session list preview)
        if message.role == "user":
            meta = _read_meta(path) or {}
            if not meta.get("title"):
                meta["title"] = message.content.strip().replace("\n", " ")[:60]
                _rewrite_meta(path, meta)

        return {"ok": True, "session_id": sid}

    @router.delete("/api/chat_sessions/{session_id}")
    def archive_session(
        session_id: str,
        project_id: str = Query(...),
    ) -> Dict[str, Any]:
        pid = _validate_project(project_id)
        sid = _validate_session_id(session_id)
        path = _session_path(pid, sid)
        if not path.exists():
            raise HTTPException(404, f"session {sid!r} not found")
        archived = path.with_suffix(".jsonl.archived")
        path.rename(archived)
        return {"ok": True, "session_id": sid, "archived_to": str(archived)}

    return router


def _rewrite_meta(path: Path, meta: Dict[str, Any]) -> None:
    """Rewrite the first line (meta record) in-place while preserving the
    append-only log body. Best-effort; if it fails we keep going."""
    try:
        with path.open("r", encoding="utf-8") as f:
            lines = f.readlines()
        if not lines:
            return
        lines[0] = json.dumps({"meta": meta}, ensure_ascii=False) + "\n"
        tmp = path.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            f.writelines(lines)
        tmp.replace(path)
    except Exception as exc:
        logger.debug("chat_sessions: meta rewrite failed: %s", exc)
