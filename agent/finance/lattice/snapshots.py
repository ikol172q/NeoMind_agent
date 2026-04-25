"""V8 — daily lattice snapshots.

Persist the full /calls payload (L1 + L1.5 + L2 + L3) under
``<investment_root>/<project_id>/lattice_snapshots/<YYYY-MM-DD>.json``
every time a fresh build completes. Lets the UI page back through
past days without re-running the LLM.

Storage format is just the /api/lattice/calls response dict plus a
``snapshot_meta`` wrapper with version + recorded_at. A missing
snapshot returns None; corrupt ones are skipped (caller decides how
to surface).
"""
from __future__ import annotations

import json
import logging
import re
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.finance import investment_projects
from agent.finance.lattice import spec

logger = logging.getLogger(__name__)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SNAPSHOT_VERSION = 1
_write_lock = threading.Lock()


def _snapshot_dir(project_id: str) -> Path:
    root = investment_projects.get_investment_root()
    return (root / project_id / "lattice_snapshots").resolve()


def snapshot_path(project_id: str, date_str: str) -> Path:
    """Path for a specific day's snapshot. Does not imply existence."""
    if not _DATE_RE.match(date_str):
        raise ValueError(f"invalid date {date_str!r}, expected YYYY-MM-DD")
    return _snapshot_dir(project_id) / f"{date_str}.json"


def today_str() -> str:
    """UTC-today YYYY-MM-DD. Matches the backend's other date-keyed
    stores (chat_log, audit) which also use UTC."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def write_snapshot(
    project_id: str,
    payload: Dict[str, Any],
    *,
    date_str: Optional[str] = None,
) -> Path:
    """Overwrite the same-day file. Best-effort: logs + raises on
    filesystem errors; caller decides whether to swallow.

    The snapshot is a minimal envelope around the /calls payload:
        {
          "snapshot_meta": {"version": 1, "date": "2026-04-23",
                            "recorded_at": "2026-04-23T..Z",
                            "output_language": "en"},
          "payload": <the /calls payload dict>
        }
    """
    d = date_str or today_str()
    target = snapshot_path(project_id, d)
    target.parent.mkdir(parents=True, exist_ok=True)
    envelope = {
        "snapshot_meta": {
            "version": _SNAPSHOT_VERSION,
            "date": d,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "output_language": payload.get("output_language")
                or spec.OUTPUT_LANGUAGE_DEFAULT,
        },
        "payload": payload,
    }
    tmp = target.with_suffix(".json.tmp")
    with _write_lock:
        tmp.write_text(json.dumps(envelope, ensure_ascii=False, indent=2))
        tmp.replace(target)
    return target


def read_snapshot(project_id: str, date_str: str) -> Optional[Dict[str, Any]]:
    """Return the stored envelope, or None if missing.
    Corrupt files: log + return None (don't raise — a broken single
    day shouldn't bring down the endpoint)."""
    target = snapshot_path(project_id, date_str)
    if not target.is_file():
        return None
    try:
        return json.loads(target.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(
            "lattice snapshot %s for %s unreadable: %s",
            date_str, project_id, exc,
        )
        return None


def list_snapshots(project_id: str) -> List[Dict[str, Any]]:
    """List available snapshot dates for a project, newest first.
    Each entry: {date, size_bytes, output_language, recorded_at}.
    Safe to call when the snapshot dir doesn't exist yet (returns [])."""
    sd = _snapshot_dir(project_id)
    if not sd.is_dir():
        return []
    out: List[Dict[str, Any]] = []
    for p in sd.glob("*.json"):
        stem = p.stem
        if not _DATE_RE.match(stem):
            continue
        try:
            raw = json.loads(p.read_text())
            meta = raw.get("snapshot_meta", {})
        except (json.JSONDecodeError, OSError):
            continue
        out.append({
            "date": stem,
            "size_bytes": p.stat().st_size,
            "output_language": meta.get("output_language"),
            "recorded_at": meta.get("recorded_at"),
        })
    out.sort(key=lambda x: x["date"], reverse=True)
    return out
