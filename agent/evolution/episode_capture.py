"""Episode capture for manual evolve loop (C1).

Each LLM turn appends one structured episode to a per-day JSONL file under
``_evolution/episodes/YYYY-MM-DD.jsonl``. Schema is intentionally narrow:
fields you'd want to look at when asking "did this turn go well?" — query,
reply, tool calls, and signals (latency, tokens, finish reason, compact).

Reflect (``agent.evolution.reflect``) reads these files, sends batches to a
cheap LLM, and returns *suggestions* — never auto-injects. User decides
whether to update prompts.

Design notes
------------
- Best-effort: any exception inside ``record_episode`` is swallowed by the
  caller's wrapper. Capture must never break the main response path.
- File-per-day to keep each file bounded; reflect handles concatenation.
- Schema-stable: don't rename fields. Add new ones at the end if needed
  (downstream parsers can ignore unknown).
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

EPISODES_ROOT = Path(__file__).resolve().parents[2] / "_evolution" / "episodes"
_WRITE_LOCK = threading.Lock()


def _today_path() -> Path:
    return EPISODES_ROOT / f"{datetime.now(timezone.utc).date().isoformat()}.jsonl"


def record_episode(
    *,
    mode: str,
    query: str,
    reply: str,
    tool_calls: list[dict[str, Any]] | None = None,
    signals: dict[str, Any] | None = None,
    session_id: str | None = None,
    project_id: str | None = None,
    req_id: str | None = None,
) -> None:
    """Append one episode. Caller wraps in try/except — never re-raise here."""
    EPISODES_ROOT.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "session_id": session_id,
        "project_id": project_id,
        "req_id": req_id,
        "query": query,
        "reply": reply,
        "tool_calls": tool_calls or [],
        "signals": signals or {},
    }
    line = json.dumps(record, ensure_ascii=False)
    path = _today_path()
    with _WRITE_LOCK:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def iter_recent_episodes(
    limit: int = 50,
    mode_filter: str | None = None,
    days_back: int = 7,
) -> Iterable[dict[str, Any]]:
    """Yield up to ``limit`` most-recent episodes (newest first), optionally
    filtered by mode. Walks back up to ``days_back`` daily files.
    """
    if not EPISODES_ROOT.exists():
        return
    files = sorted(EPISODES_ROOT.glob("*.jsonl"), reverse=True)[:days_back]
    seen = 0
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for raw in reversed(lines):
            if not raw.strip():
                continue
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if mode_filter and rec.get("mode") != mode_filter:
                continue
            yield rec
            seen += 1
            if seen >= limit:
                return
