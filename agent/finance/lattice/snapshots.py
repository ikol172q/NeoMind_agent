"""V8 — daily lattice snapshots, V8.1 — re-run preservation.

Persist the full /calls payload (L1 + L1.5 + L2 + L3) under
``<investment_root>/<project_id>/lattice_snapshots/<YYYY-MM-DD>/<run_id>.json``
every time a fresh build completes.  Lets the UI page back through
past days without re-running the LLM.

V8.1 (Phase 2 of the temporal-replay architecture, see
docs/design/2026-04-26_temporal-replay-architecture.md):
  - Snapshots are now stored under a per-date directory keyed by
    ``run_id`` so re-running the lattice on the same day NO LONGER
    overwrites earlier evidence.
  - Legacy ``<date>.json`` files (pre-V8.1) are still readable and
    treated as a single-run-per-date for backwards compatibility.
  - ``read_snapshot(project_id, date)`` returns the LATEST run for
    that date by default; pass ``run_id=...`` for an exact match.

Storage format is just the /api/lattice/calls response dict plus a
``snapshot_meta`` wrapper with version + recorded_at + run_id.
A missing snapshot returns None; corrupt ones are skipped (caller
decides how to surface).
"""
from __future__ import annotations

import json
import logging
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.finance import investment_projects
from agent.finance.lattice import spec

logger = logging.getLogger(__name__)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RUN_ID_RE = re.compile(r"^[0-9a-fA-F-]{8,40}$")
_SNAPSHOT_VERSION = 2  # bumped — V8.1 layout
_write_lock = threading.Lock()


def _snapshot_dir(project_id: str) -> Path:
    root = investment_projects.get_investment_root()
    return (root / project_id / "lattice_snapshots").resolve()


def _date_dir(project_id: str, date_str: str) -> Path:
    """Per-date directory; one .json file per run inside."""
    if not _DATE_RE.match(date_str):
        raise ValueError(f"invalid date {date_str!r}, expected YYYY-MM-DD")
    return _snapshot_dir(project_id) / date_str


def snapshot_path(
    project_id: str,
    date_str: str,
    run_id: Optional[str] = None,
) -> Path:
    """Path for a specific run's snapshot. Does not imply existence.

    ``run_id=None`` returns the legacy v1 path (one file per date)
    so write_snapshot's old call sites still work in transition.
    """
    if not _DATE_RE.match(date_str):
        raise ValueError(f"invalid date {date_str!r}, expected YYYY-MM-DD")
    if run_id is None:
        return _snapshot_dir(project_id) / f"{date_str}.json"
    if not _RUN_ID_RE.match(run_id):
        raise ValueError(f"invalid run_id {run_id!r}")
    return _date_dir(project_id, date_str) / f"{run_id}.json"


def today_str() -> str:
    """UTC-today YYYY-MM-DD. Matches the backend's other date-keyed
    stores (chat_log, audit) which also use UTC."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def write_snapshot(
    project_id: str,
    payload: Dict[str, Any],
    *,
    date_str: Optional[str] = None,
    run_id: Optional[str] = None,
) -> Path:
    """V8.1: write to per-date directory keyed by run_id so multiple
    runs on the same day are all preserved.  ``run_id=None`` →
    auto-generate a UUID4 (so callers that don't carry a run id
    still don't overwrite each other).
    """
    d = date_str or today_str()
    rid = run_id or str(uuid.uuid4())
    target = snapshot_path(project_id, d, rid)
    target.parent.mkdir(parents=True, exist_ok=True)
    envelope = {
        "snapshot_meta": {
            "version":          _SNAPSHOT_VERSION,
            "date":             d,
            "run_id":           rid,
            "recorded_at":      datetime.now(timezone.utc).isoformat(),
            "output_language":  payload.get("output_language")
                or spec.OUTPUT_LANGUAGE_DEFAULT,
        },
        "payload": payload,
    }
    tmp = target.with_suffix(".json.tmp")
    with _write_lock:
        tmp.write_text(json.dumps(envelope, ensure_ascii=False, indent=2))
        tmp.replace(target)
    return target


def _list_runs_for_date(project_id: str, date_str: str) -> List[Path]:
    """Sorted list (newest first by mtime) of run files for one date.
    Includes the legacy single-file-per-date layout if present."""
    out: List[Path] = []
    dd = _date_dir(project_id, date_str)
    if dd.is_dir():
        out.extend(p for p in dd.glob("*.json") if not p.name.startswith("."))
    legacy = _snapshot_dir(project_id) / f"{date_str}.json"
    if legacy.is_file():
        out.append(legacy)
    out.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return out


def read_snapshot(
    project_id: str,
    date_str: str,
    run_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Return the stored envelope, or None if missing.

    Lookup order:
      1. exact ``run_id`` if given (V8.1 path) → 404 if not found
      2. otherwise: latest run in the per-date directory by mtime
      3. otherwise: legacy ``<date>.json`` single-file path (V8.0)

    Corrupt files: log + return None (don't raise — a broken single
    day shouldn't bring down the endpoint).
    """
    if run_id is not None:
        target = snapshot_path(project_id, date_str, run_id)
        if not target.is_file():
            return None
        return _safe_load(target, date_str, project_id)

    runs = _list_runs_for_date(project_id, date_str)
    if not runs:
        return None
    return _safe_load(runs[0], date_str, project_id)


def _safe_load(p: Path, date_str: str, project_id: str) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(
            "lattice snapshot %s (%s) for %s unreadable: %s",
            date_str, p.name, project_id, exc,
        )
        return None


def list_snapshots(project_id: str) -> List[Dict[str, Any]]:
    """List available snapshot dates for a project, newest first.

    V8.1: each entry now also carries ``run_count`` and
    ``latest_run_id`` so the UI can decide whether to expose a
    per-run sub-selector.

    Each entry: {date, size_bytes (sum), run_count, latest_run_id,
                 output_language, recorded_at (latest)}.
    Safe to call when the snapshot dir doesn't exist yet (returns []).
    """
    sd = _snapshot_dir(project_id)
    if not sd.is_dir():
        return []

    by_date: Dict[str, Dict[str, Any]] = {}

    # V8.1 layout: per-date directories with run-id files inside
    for d in sd.iterdir():
        if d.is_dir() and _DATE_RE.match(d.name):
            date_str = d.name
            run_files = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            if not run_files:
                continue
            latest_meta = _safe_meta(run_files[0])
            by_date[date_str] = {
                "date":            date_str,
                "size_bytes":      sum(p.stat().st_size for p in run_files),
                "run_count":       len(run_files),
                "latest_run_id":   latest_meta.get("run_id"),
                "output_language": latest_meta.get("output_language"),
                "recorded_at":     latest_meta.get("recorded_at"),
            }

    # V8.0 legacy: <date>.json single file. If a date already has
    # V8.1 entries, the legacy file is ALSO counted into run_count
    # (the legacy file was effectively run #1).
    for p in sd.glob("*.json"):
        stem = p.stem
        if not _DATE_RE.match(stem):
            continue
        meta = _safe_meta(p)
        if stem in by_date:
            by_date[stem]["run_count"] += 1
            by_date[stem]["size_bytes"] += p.stat().st_size
        else:
            by_date[stem] = {
                "date":            stem,
                "size_bytes":      p.stat().st_size,
                "run_count":       1,
                "latest_run_id":   meta.get("run_id"),  # may be None for true legacy
                "output_language": meta.get("output_language"),
                "recorded_at":     meta.get("recorded_at"),
            }

    out = list(by_date.values())
    out.sort(key=lambda x: x["date"], reverse=True)
    return out


def _safe_meta(p: Path) -> Dict[str, Any]:
    try:
        raw = json.loads(p.read_text())
        return raw.get("snapshot_meta", {})
    except (json.JSONDecodeError, OSError):
        return {}


def list_runs_for_date(project_id: str, date_str: str) -> List[Dict[str, Any]]:
    """Phase 2: every run we have on disk for one date, newest first.
    Used by the UI's per-date "version dropdown".  Each entry is
    {run_id, recorded_at, output_language, size_bytes, theme_count,
    call_count, source: 'v8.1' | 'legacy'}."""
    out: List[Dict[str, Any]] = []
    for p in _list_runs_for_date(project_id, date_str):
        meta = _safe_meta(p)
        is_legacy = p.name == f"{date_str}.json"
        out.append({
            "run_id":          meta.get("run_id"),
            "recorded_at":     meta.get("recorded_at"),
            "output_language": meta.get("output_language"),
            "size_bytes":      p.stat().st_size,
            "source":          "legacy" if is_legacy else "v8.1",
        })
    return out
