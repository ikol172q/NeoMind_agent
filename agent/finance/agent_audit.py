"""Zero-data-loss audit log for every agent LLM turn.

Every time a NeoMind component calls an LLM (direct, through the
fleet worker, via the OpenBB Copilot agent endpoint, anything),
this module records:

1. A ``request`` event with the FULL prompt (system + messages
   array) + model + max_tokens + temperature + caller metadata.
2. A ``response`` event with the FULL content, reasoning_content
   (if present), finish_reason, usage dict, duration_ms.
3. An ``error`` event if the call fails, with the full traceback.

Storage: append-only JSONL at
``<investment_root>/_audit/YYYY-MM-DD.jsonl``. Each line is a
self-contained JSON object. Line-flushed after every write so a
process crash loses at most the in-flight line.

Design non-negotiables (user-stated 2026-04-19):
- No truncation. Full bodies, full tracebacks.
- No overwrite. Append-only. Past lines never mutated.
- Easy to read. jq / ripgrep / ``AuditLog.query`` all work.
- Easy to correlate. Every event carries ``req_id`` (unique per
  LLM call) and ``task_id`` (fleet task id, if known).

Typical query patterns:

    # Everything today
    jq -s . ~/Desktop/Investment/_audit/2026-04-19.jsonl

    # All turns for a fleet task
    jq -c 'select(.task_id=="task_123_45")' audit/*.jsonl

    # Just the responses that took >5s
    jq -c 'select(.kind=="response" and .payload.duration_ms>5000)' audit/*.jsonl

The /api/audit/* HTTP endpoints expose the same store through JSON.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "AuditLogger",
    "get_default_audit",
    "audit_request",
    "audit_response",
    "audit_error",
    "new_req_id",
]

# ── Storage root ──────────────────────────────────────────────────

_DEFAULT_SUBDIR = "_audit"


def _audit_root() -> Path:
    """Central audit dir under the Investment root. Uses
    ``NEOMIND_INVESTMENT_ROOT`` env override if set (tests)."""
    env = os.environ.get("NEOMIND_INVESTMENT_ROOT")
    if env:
        base = Path(env).expanduser().resolve()
    else:
        base = (Path.home() / "Desktop" / "Investment").resolve()
    root = base / _DEFAULT_SUBDIR
    root.mkdir(parents=True, exist_ok=True)
    return root


def _today_path() -> Path:
    return _audit_root() / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.jsonl"


# ── ID helpers ────────────────────────────────────────────────────


def new_req_id() -> str:
    """UUID4 hex — unique per LLM request, independent of task_id."""
    return uuid.uuid4().hex


# ── Core logger ───────────────────────────────────────────────────


class AuditLogger:
    """Thread-safe append-only JSONL writer + simple read API.

    Instances are cheap; the default module-level one (returned by
    ``get_default_audit()``) is fine for production. Tests spin
    their own with a monkey-patched root.
    """

    def __init__(self, root: Optional[Path] = None):
        self._root = root
        self._lock = threading.Lock()

    @property
    def root(self) -> Path:
        return self._root if self._root is not None else _audit_root()

    def _today(self) -> Path:
        if self._root is not None:
            self._root.mkdir(parents=True, exist_ok=True)
            return self._root / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.jsonl"
        return _today_path()

    def _write(self, entry: Dict[str, Any]) -> None:
        path = self._today()
        line = json.dumps(entry, ensure_ascii=False, default=str)
        # Append-only + line flush: even on crash the on-disk state
        # lags at most one in-flight line.
        try:
            with self._lock:
                with path.open("a", encoding="utf-8", buffering=1) as f:
                    f.write(line + "\n")
        except Exception as exc:  # pragma: no cover
            # Never raise from audit — upstream must not die because
            # we can't write. Log to stderr instead.
            logger.error(
                "agent_audit: failed to write to %s: %s", path, exc
            )

    def record_request(
        self,
        *,
        req_id: str,
        endpoint: str,
        agent_id: str,
        messages: List[Dict[str, Any]],
        model: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        project_id: Optional[str] = None,
        task_id: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record the FULL request before calling the LLM."""
        self._write({
            "req_id": req_id,
            "task_id": task_id,
            "project_id": project_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            "agent_id": agent_id,
            "endpoint": endpoint,
            "kind": "request",
            "payload": {
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": messages,
                **(extra or {}),
            },
        })

    def record_response(
        self,
        *,
        req_id: str,
        content: str,
        reasoning_content: Optional[str] = None,
        finish_reason: Optional[str] = None,
        usage: Optional[Dict[str, Any]] = None,
        duration_ms: Optional[int] = None,
        project_id: Optional[str] = None,
        task_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        endpoint: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record the FULL response after the LLM returns."""
        self._write({
            "req_id": req_id,
            "task_id": task_id,
            "project_id": project_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            "agent_id": agent_id,
            "endpoint": endpoint,
            "kind": "response",
            "payload": {
                "content": content,
                "reasoning_content": reasoning_content,
                "finish_reason": finish_reason,
                "usage": usage,
                "duration_ms": duration_ms,
                **(extra or {}),
            },
        })

    def record_error(
        self,
        *,
        req_id: str,
        error_type: str,
        error_msg: str,
        traceback_text: Optional[str] = None,
        duration_ms: Optional[int] = None,
        project_id: Optional[str] = None,
        task_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        endpoint: Optional[str] = None,
    ) -> None:
        self._write({
            "req_id": req_id,
            "task_id": task_id,
            "project_id": project_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            "agent_id": agent_id,
            "endpoint": endpoint,
            "kind": "error",
            "payload": {
                "error_type": error_type,
                "error_msg": error_msg,
                "traceback": traceback_text,
                "duration_ms": duration_ms,
            },
        })

    # ── Read API ─────────────────────────────────────────────

    def _iter_files(self, days: int) -> Iterator[Path]:
        """Yield audit files newest-first, up to ``days`` back."""
        if not self.root.exists():
            return
        files = sorted(
            (p for p in self.root.iterdir()
             if p.is_file() and p.suffix == ".jsonl"),
            reverse=True,
        )
        for p in files[:max(1, days)]:
            yield p

    def iter_entries(
        self,
        *,
        days: int = 7,
        kind: Optional[str] = None,
        task_id: Optional[str] = None,
        req_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> Iterator[Dict[str, Any]]:
        for p in self._iter_files(days):
            try:
                with p.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                        except Exception:
                            continue
                        if kind and entry.get("kind") != kind:
                            continue
                        if task_id and entry.get("task_id") != task_id:
                            continue
                        if req_id and entry.get("req_id") != req_id:
                            continue
                        if project_id and entry.get("project_id") != project_id:
                            continue
                        yield entry
            except Exception as exc:  # pragma: no cover
                logger.warning("audit read %s failed: %s", p, exc)

    def recent(
        self,
        *,
        limit: int = 50,
        days: int = 1,
        kind: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Latest entries, newest-first, across the last ``days``.
        Clamps limit 1..500."""
        limit = max(1, min(int(limit), 500))
        # Walk files newest-first, collect per-file entries reversed
        out: List[Dict[str, Any]] = []
        for p in self._iter_files(days):
            try:
                lines = p.read_text(encoding="utf-8").splitlines()
            except Exception:
                continue
            for line in reversed(lines):
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                if kind and entry.get("kind") != kind:
                    continue
                out.append(entry)
                if len(out) >= limit:
                    return out
        return out

    def by_task(self, task_id: str, days: int = 7) -> List[Dict[str, Any]]:
        return list(self.iter_entries(task_id=task_id, days=days))

    def by_req(self, req_id: str, days: int = 7) -> List[Dict[str, Any]]:
        return list(self.iter_entries(req_id=req_id, days=days))

    def stats(self, days: int = 1) -> Dict[str, Any]:
        """Quick counts by kind / agent / endpoint for a dashboard."""
        total = 0
        by_kind: Dict[str, int] = {}
        by_agent: Dict[str, int] = {}
        by_endpoint: Dict[str, int] = {}
        total_tokens_in = 0
        total_tokens_out = 0
        for e in self.iter_entries(days=days):
            total += 1
            by_kind[e.get("kind", "?")] = by_kind.get(e.get("kind", "?"), 0) + 1
            ag = e.get("agent_id") or "?"
            by_agent[ag] = by_agent.get(ag, 0) + 1
            ep = e.get("endpoint") or "?"
            by_endpoint[ep] = by_endpoint.get(ep, 0) + 1
            if e.get("kind") == "response":
                usage = (e.get("payload") or {}).get("usage") or {}
                total_tokens_in += int(usage.get("prompt_tokens") or 0)
                total_tokens_out += int(usage.get("completion_tokens") or 0)
        return {
            "days": days,
            "total_entries": total,
            "by_kind": by_kind,
            "by_agent": by_agent,
            "by_endpoint": by_endpoint,
            "tokens_in": total_tokens_in,
            "tokens_out": total_tokens_out,
        }


# ── Default singleton ─────────────────────────────────────────────

_default: Optional[AuditLogger] = None


def get_default_audit() -> AuditLogger:
    global _default
    if _default is None:
        _default = AuditLogger()
    return _default


# ── Convenience functions ─────────────────────────────────────────


def audit_request(**kwargs) -> None:
    get_default_audit().record_request(**kwargs)


def audit_response(**kwargs) -> None:
    get_default_audit().record_response(**kwargs)


def audit_error(**kwargs) -> None:
    get_default_audit().record_error(**kwargs)


# ── HTTP router (mounted under /api/audit/*) ─────────────────────


def build_audit_router():
    """FastAPI router with debug-oriented query endpoints.

    GET /api/audit/recent?limit=&days=&kind=
    GET /api/audit/task/{task_id}
    GET /api/audit/req/{req_id}
    GET /api/audit/stats?days=
    """
    from fastapi import APIRouter, Query
    from fastapi.responses import JSONResponse

    router = APIRouter()
    log = get_default_audit()

    @router.get("/api/audit/recent")
    def recent(
        limit: int = Query(50, ge=1, le=500),
        days: int = Query(1, ge=1, le=90),
        kind: Optional[str] = Query(None),
    ) -> JSONResponse:
        return JSONResponse(content={
            "entries": log.recent(limit=limit, days=days, kind=kind),
            "audit_root": str(log.root),
        })

    @router.get("/api/audit/task/{task_id}")
    def by_task(task_id: str, days: int = Query(7, ge=1, le=90)) -> JSONResponse:
        return JSONResponse(content={
            "task_id": task_id,
            "entries": log.by_task(task_id, days=days),
        })

    @router.get("/api/audit/req/{req_id}")
    def by_req(req_id: str, days: int = Query(7, ge=1, le=90)) -> JSONResponse:
        return JSONResponse(content={
            "req_id": req_id,
            "entries": log.by_req(req_id, days=days),
        })

    @router.get("/api/audit/stats")
    def stats(days: int = Query(1, ge=1, le=90)) -> JSONResponse:
        return JSONResponse(content=log.stats(days=days))

    return router
