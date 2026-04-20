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

    GET /audit                        — HTML visual browser
    GET /api/audit/recent?limit=&days=&kind=
    GET /api/audit/task/{task_id}
    GET /api/audit/req/{req_id}
    GET /api/audit/stats?days=
    """
    from fastapi import APIRouter, Query
    from fastapi.responses import JSONResponse, HTMLResponse

    router = APIRouter()
    log = get_default_audit()

    @router.get("/audit", response_class=HTMLResponse)
    def audit_viewer() -> HTMLResponse:
        return HTMLResponse(content=_AUDIT_HTML)

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


# ── Visual HTML viewer ────────────────────────────────────────────

_AUDIT_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>neomind · agent audit</title>
<style>
:root {
  --bg:#0b0d12; --panel:#141822; --border:#1f2631;
  --text:#d8dde6; --dim:#7c8598; --accent:#4dd0e1;
  --green:#6fd07a; --red:#e57373; --yellow:#f3c969; --blue:#8ab4f8;
}
* { box-sizing:border-box; }
body { margin:0; font-family:-apple-system, SF Mono, Menlo, monospace;
       background:var(--bg); color:var(--text); font-size:13px; }
header { padding:12px 20px; border-bottom:1px solid var(--border);
         background:var(--panel); display:flex; gap:14px; align-items:center;
         flex-wrap:wrap; position:sticky; top:0; z-index:10; }
header h1 { margin:0; font-size:15px; }
header .stats { color:var(--dim); font-size:11px; }
input, select, button { background:#0e1219; color:var(--text);
         border:1px solid var(--border); border-radius:4px;
         padding:5px 9px; font-family:inherit; font-size:12px; }
button { cursor:pointer; color:var(--bg); background:var(--accent);
         border-color:var(--accent); font-weight:600; }
main { padding:16px 20px; }
.entry { background:var(--panel); border:1px solid var(--border);
         border-radius:5px; margin-bottom:10px; overflow:hidden; }
.entry-head { padding:8px 12px; cursor:pointer; display:flex;
              gap:10px; align-items:center; font-size:12px;
              border-bottom:1px solid transparent; }
.entry.open .entry-head { border-bottom-color:var(--border); }
.badge { display:inline-block; padding:2px 8px; border-radius:3px;
         font-size:11px; font-weight:600; letter-spacing:0.04em; }
.badge-request  { background:rgba(138,180,248,.18); color:var(--blue); }
.badge-response { background:rgba(111,208,122,.18); color:var(--green); }
.badge-error    { background:rgba(229,115,115,.22); color:var(--red); }
.meta { color:var(--dim); font-size:11px; }
.meta code { color:var(--text); background:rgba(120,160,220,.08);
             padding:1px 5px; border-radius:3px; }
.entry-body { display:none; padding:10px 14px; }
.entry.open .entry-body { display:block; }
.section-label { color:var(--dim); font-size:10px; text-transform:uppercase;
                 letter-spacing:0.06em; margin:8px 0 4px; }
pre { background:#0e1219; border:1px solid var(--border);
      border-radius:4px; padding:10px 12px; margin:0; overflow-x:auto;
      white-space:pre-wrap; word-break:break-word; font-size:12px;
      line-height:1.55; max-height:400px; overflow-y:auto; }
.msg-turn { background:#0e1219; border:1px solid var(--border);
            border-radius:4px; padding:8px 10px; margin-bottom:6px; }
.msg-role { font-size:10px; color:var(--accent); text-transform:uppercase; }
.kpi { display:inline-block; margin-right:12px; }
.kpi-lab { color:var(--dim); }
.kpi-val { color:var(--text); font-weight:600; }
.empty { color:var(--dim); padding:40px 10px; text-align:center; font-style:italic; }
.search-match { background:rgba(243,201,105,.3); color:var(--yellow); }
</style>
</head>
<body>
<header>
  <h1>◇ agent audit</h1>
  <span class="stats" id="stats">…</span>
  <span style="flex:1"></span>
  <input id="search" placeholder="search content/task_id/req_id" style="width:280px;">
  <select id="kind-filter">
    <option value="">all kinds</option>
    <option value="request">request</option>
    <option value="response">response</option>
    <option value="error">error</option>
  </select>
  <select id="limit">
    <option value="50">50</option>
    <option value="100">100</option>
    <option value="200">200</option>
    <option value="500">500</option>
  </select>
  <button id="refresh">↻ reload</button>
</header>
<main id="list"><div class="empty">loading…</div></main>

<script>
const $ = id => document.getElementById(id);

function esc(s) {
  return String(s ?? "").replace(/[<>&"']/g, c => ({
    "<":"&lt;", ">":"&gt;", "&":"&amp;", '"':"&quot;", "'":"&#39;"
  })[c]);
}

function prettyJSON(v) {
  try { return JSON.stringify(v, null, 2); }
  catch { return String(v); }
}

function renderEntry(e, q) {
  const kind = e.kind || "?";
  const p = e.payload || {};
  const ts = (e.ts || "").replace("T"," ").slice(0, 19);
  const dur = p.duration_ms != null ? p.duration_ms + "ms" : "";
  const tokens = p.usage?.total_tokens != null ? p.usage.total_tokens + " tok" : "";
  const model = p.model || "";
  const contentLen = kind === "response" ? (p.content || "").length + "c" : "";

  // Body
  let body = "";
  if (kind === "request") {
    body += '<div class="section-label">Messages (' + (p.messages||[]).length + ' turns)</div>';
    (p.messages || []).forEach(m => {
      body += '<div class="msg-turn"><div class="msg-role">' + esc(m.role) + '</div>';
      body += '<pre>' + esc(m.content || "") + '</pre></div>';
    });
    body += '<div class="section-label">Model / params</div>';
    body += '<pre>' + esc(prettyJSON({
      model: p.model, max_tokens: p.max_tokens, temperature: p.temperature
    })) + '</pre>';
  } else if (kind === "response") {
    body += '<div class="section-label">Content (' + (p.content||"").length + ' chars)</div>';
    body += '<pre>' + esc(p.content || "") + '</pre>';
    if (p.reasoning_content) {
      body += '<div class="section-label">Reasoning content (' + p.reasoning_content.length + ' chars)</div>';
      body += '<pre>' + esc(p.reasoning_content) + '</pre>';
    }
    body += '<div class="section-label">Usage · finish</div>';
    body += '<pre>' + esc(prettyJSON({
      usage: p.usage, finish_reason: p.finish_reason, duration_ms: p.duration_ms
    })) + '</pre>';
  } else if (kind === "error") {
    body += '<div class="section-label">Error</div>';
    body += '<pre>' + esc(p.error_type + ": " + p.error_msg) + '</pre>';
    if (p.traceback) {
      body += '<div class="section-label">Traceback</div>';
      body += '<pre>' + esc(p.traceback) + '</pre>';
    }
  }

  return `
    <div class="entry" data-all="${esc((e.task_id||"")+" "+(e.req_id||"")+" "+JSON.stringify(p))}">
      <div class="entry-head">
        <span class="badge badge-${kind}">${kind}</span>
        <span class="meta">${ts}</span>
        <span class="meta"><code>req</code> ${esc((e.req_id||"").slice(0,10))}</span>
        <span class="meta"><code>task</code> ${esc((e.task_id||"-").slice(0,16))}</span>
        <span class="meta">${esc(e.agent_id||"")}</span>
        <span style="flex:1"></span>
        <span class="kpi"><span class="kpi-lab">${model}</span></span>
        ${contentLen ? '<span class="kpi"><span class="kpi-val">'+contentLen+'</span></span>' : ''}
        ${tokens ? '<span class="kpi"><span class="kpi-val">'+tokens+'</span></span>' : ''}
        ${dur ? '<span class="kpi"><span class="kpi-val">'+dur+'</span></span>' : ''}
      </div>
      <div class="entry-body">${body}</div>
    </div>`;
}

async function load() {
  const kind = $("kind-filter").value;
  const limit = $("limit").value;
  const url = "/api/audit/recent?limit=" + limit + (kind ? "&kind=" + kind : "");
  try {
    const r = await fetch(url);
    const d = await r.json();
    const entries = d.entries || [];
    $("list").innerHTML = entries.length
      ? entries.map(e => renderEntry(e)).join("")
      : '<div class="empty">no entries (try a chat first, then ↻ reload)</div>';
    applySearch();
  } catch (e) {
    $("list").innerHTML = '<div class="empty">error: ' + esc(e.message) + '</div>';
  }

  try {
    const s = await fetch("/api/audit/stats").then(r => r.json());
    $("stats").textContent =
      s.total_entries + " entries · " +
      s.tokens_in.toLocaleString() + " in / " +
      s.tokens_out.toLocaleString() + " out tokens · today";
  } catch {}
}

function applySearch() {
  const q = $("search").value.trim().toLowerCase();
  document.querySelectorAll(".entry").forEach(el => {
    const hay = (el.dataset.all || "").toLowerCase();
    el.style.display = !q || hay.includes(q) ? "" : "none";
  });
}

document.addEventListener("click", e => {
  const head = e.target.closest(".entry-head");
  if (head) head.parentElement.classList.toggle("open");
});

$("refresh").onclick = load;
$("kind-filter").onchange = load;
$("limit").onchange = load;
$("search").oninput = applySearch;
load();
setInterval(load, 30000);  // auto-refresh every 30s
</script>
</body>
</html>
"""
