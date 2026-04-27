"""Strict ``dep_hash`` cache backed by SQLite.

Schema (one row per executed compute step):

    compute_runs(
        compute_run_id  PK,           -- short uuid hex
        dep_hash        TEXT NOT NULL,
        step            TEXT NOT NULL, -- e.g. 'observations', 'themes'
        crawl_run_id    TEXT,          -- which raw-store crawl this consumed
        started_at      TEXT NOT NULL, -- ISO 8601 UTC
        completed_at    TEXT,
        status          TEXT NOT NULL, -- 'success' / 'failed' / 'in_progress'
        snapshot_path   TEXT,          -- relative path to result blob
        size_bytes      INTEGER,
        params_json     TEXT NOT NULL  -- DepHashInputs serialised
    )

Index ``(dep_hash, step, status)`` is the cache lookup path.  Hits
are SELECT'd by ``dep_hash + step + status='success'`` ordered by
``completed_at DESC LIMIT 1`` — most recent successful run wins so
operational replays naturally use the latest stored snapshot.

The cache is strict.  It does not look at ``crawl_run_id`` at lookup
time — the dep_hash already encodes every byte of input.  Two
different crawl_runs that produced identical blob hashes (re-crawl
yielded zero changes) get the same dep_hash, so the second compute
hits the first compute's cache.  This is the desired property.

Snapshots live on disk at ``<compute_root>/snapshots/<step>/<dep_hash>.json``.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from .dep_hash import (
    DepHashInputs,
    compute_dep_hash,
    inputs_from_dict,
    inputs_to_dict,
)

logger = logging.getLogger(__name__)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS compute_runs (
    compute_run_id TEXT PRIMARY KEY,
    dep_hash       TEXT NOT NULL,
    step           TEXT NOT NULL,
    crawl_run_id   TEXT,
    started_at     TEXT NOT NULL,
    completed_at   TEXT,
    status         TEXT NOT NULL,
    snapshot_path  TEXT,
    size_bytes     INTEGER,
    params_json    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_dep_hash_step
    ON compute_runs(dep_hash, step, status);

CREATE INDEX IF NOT EXISTS idx_step_completed_at
    ON compute_runs(step, completed_at DESC);

-- Lifetime cache statistics — one row, accumulated.
CREATE TABLE IF NOT EXISTS compute_cache_stats (
    id             INTEGER PRIMARY KEY CHECK (id = 1),
    n_hits         INTEGER NOT NULL DEFAULT 0,
    n_misses       INTEGER NOT NULL DEFAULT 0,
    bytes_avoided  INTEGER NOT NULL DEFAULT 0  -- size_bytes summed across hits
);

INSERT OR IGNORE INTO compute_cache_stats(id, n_hits, n_misses, bytes_avoided)
VALUES (1, 0, 0, 0);
"""


def _utcnow_iso() -> str:
    """ISO 8601, microsecond precision, always 'Z' suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _new_compute_run_id() -> str:
    return uuid.uuid4().hex


# ── Public dataclass ──────────────────────────────────────────────


@dataclass(frozen=True)
class CachedRun:
    """Result of a cache hit.  ``payload`` is lazily loaded from disk
    via ``read_payload()``; we don't auto-load it because consumers
    sometimes only need metadata (e.g. "show me what was cached")."""

    compute_run_id: str
    dep_hash:       str
    step:           str
    crawl_run_id:   Optional[str]
    started_at:     str
    completed_at:   Optional[str]
    status:         str
    snapshot_path:  Optional[str]   # absolute path
    size_bytes:     Optional[int]
    inputs:         DepHashInputs

    def read_payload(self) -> Optional[bytes]:
        if not self.snapshot_path:
            return None
        p = Path(self.snapshot_path)
        if not p.exists():
            return None
        return p.read_bytes()


# ── DepCache ──────────────────────────────────────────────────────


class DepCache:
    """Strict content-addressed cache over compute step outputs.

    Construct via :func:`open_dep_cache` so the per-project root is
    consistent with RawStore.  One DepCache per project per process
    is sufficient; SQLite handles concurrent access.
    """

    def __init__(self, compute_root: Path) -> None:
        self.compute_root = Path(compute_root)
        self.compute_root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.compute_root / "_dep_index.sqlite"
        self.snapshots_root = self.compute_root / "snapshots"
        self.snapshots_root.mkdir(exist_ok=True)
        self._lock = threading.RLock()
        with self._open() as conn:
            conn.executescript(_SCHEMA)

    # ── connection management ──

    @contextmanager
    def _open(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ── cache lookup ──

    def get(self, dep_hash: str, step: str) -> Optional[CachedRun]:
        """Strict lookup.  Returns the most recent successful run
        with matching ``(dep_hash, step)``, or ``None`` on miss.

        Side effect: increments ``n_hits`` (or ``n_misses``) and the
        running ``bytes_avoided`` counter.  Stats are best-effort
        observability — failure to update them never fails the lookup.
        """
        with self._open() as conn:
            row = conn.execute(
                """
                SELECT * FROM compute_runs
                WHERE dep_hash = ?
                  AND step = ?
                  AND status = 'success'
                ORDER BY completed_at DESC
                LIMIT 1
                """,
                (dep_hash, step),
            ).fetchone()

            if row is None:
                conn.execute(
                    "UPDATE compute_cache_stats SET n_misses = n_misses + 1 WHERE id=1"
                )
                return None

            conn.execute(
                """UPDATE compute_cache_stats
                       SET n_hits = n_hits + 1,
                           bytes_avoided = bytes_avoided + COALESCE(?, 0)
                       WHERE id=1""",
                (row["size_bytes"],),
            )

        # Resolve snapshot_path to absolute on read.  ``snapshot_path``
        # in the DB is stored relative to ``snapshots_root`` (not
        # ``compute_root``) — see ``put()`` which uses
        # ``rel_path = Path(step) / "<hash>.json"``.
        rel = row["snapshot_path"]
        abs_path = str((self.snapshots_root / rel).resolve()) if rel else None
        params = json.loads(row["params_json"])
        return CachedRun(
            compute_run_id= row["compute_run_id"],
            dep_hash=       row["dep_hash"],
            step=           row["step"],
            crawl_run_id=   row["crawl_run_id"],
            started_at=     row["started_at"],
            completed_at=   row["completed_at"],
            status=         row["status"],
            snapshot_path=  abs_path,
            size_bytes=     row["size_bytes"],
            inputs=         inputs_from_dict(params),
        )

    # ── cache write ──

    def put(
        self,
        *,
        inputs:         DepHashInputs,
        step:           str,
        payload:        bytes,
        crawl_run_id:   Optional[str] = None,
        started_at:     Optional[str] = None,
        compute_run_id: Optional[str] = None,
    ) -> CachedRun:
        """Persist one successful compute run.  Snapshot is written
        first (atomic via temp + rename), then the row is inserted —
        so a row never points at a missing file.

        ``compute_run_id`` is auto-generated if not supplied.  Pass
        one only when you want to align the cache row with an
        externally-visible run id (e.g. the value the UI breadcrumb
        already shows).
        """
        dep_hash = compute_dep_hash(inputs)
        run_id   = compute_run_id or _new_compute_run_id()
        now_iso  = _utcnow_iso()
        started  = started_at or now_iso

        # Snapshot path is content-addressed by dep_hash so two writes
        # of the same hash refer to the same file (last writer wins is
        # fine — payload bytes are identical).
        step_dir = self.snapshots_root / step
        step_dir.mkdir(parents=True, exist_ok=True)
        rel_path = Path(step) / f"{dep_hash}.json"
        abs_path = self.snapshots_root / rel_path

        # Atomic write
        tmp = abs_path.with_suffix(abs_path.suffix + ".tmp")
        tmp.write_bytes(payload)
        tmp.replace(abs_path)

        size_bytes = len(payload)
        params_json = json.dumps(inputs_to_dict(inputs), sort_keys=True, ensure_ascii=False)

        with self._open() as conn:
            conn.execute(
                """
                INSERT INTO compute_runs
                  (compute_run_id, dep_hash, step, crawl_run_id,
                   started_at, completed_at, status,
                   snapshot_path, size_bytes, params_json)
                VALUES (?, ?, ?, ?, ?, ?, 'success', ?, ?, ?)
                """,
                (
                    run_id, dep_hash, step, crawl_run_id,
                    started, now_iso,
                    str(rel_path), size_bytes, params_json,
                ),
            )

        return CachedRun(
            compute_run_id= run_id,
            dep_hash=       dep_hash,
            step=           step,
            crawl_run_id=   crawl_run_id,
            started_at=     started,
            completed_at=   now_iso,
            status=         "success",
            snapshot_path=  str(abs_path),
            size_bytes=     size_bytes,
            inputs=         inputs,
        )

    # ── listing / stats ──

    def list_recent(self, *, step: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Recent compute runs (any status), most recent first.
        Used by the Data Lake "Compute Runs" view."""
        with self._open() as conn:
            if step:
                rows = conn.execute(
                    """SELECT * FROM compute_runs WHERE step=?
                           ORDER BY started_at DESC LIMIT ?""",
                    (step, int(limit)),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM compute_runs
                           ORDER BY started_at DESC LIMIT ?""",
                    (int(limit),),
                ).fetchall()

        out: List[Dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            # Don't ship the full params_json blob in list view — keep
            # the row light; consumers can request /api/compute/runs/{id}
            # for the detail.
            d.pop("params_json", None)
            out.append(d)
        return out

    def get_by_id(self, compute_run_id: str) -> Optional[Dict[str, Any]]:
        """Detail row including the full ``params_json``."""
        with self._open() as conn:
            row = conn.execute(
                "SELECT * FROM compute_runs WHERE compute_run_id=?",
                (compute_run_id,),
            ).fetchone()
        if row is None:
            return None
        d = dict(row)
        try:
            d["params"] = json.loads(d.pop("params_json"))
        except Exception:
            d["params"] = None
        return d

    def stats(self) -> Dict[str, Any]:
        """Cache stats — n_hits / n_misses / bytes_avoided / row counts."""
        with self._open() as conn:
            r = conn.execute(
                "SELECT n_hits, n_misses, bytes_avoided FROM compute_cache_stats WHERE id=1"
            ).fetchone()
            n_runs = conn.execute(
                "SELECT COUNT(*) FROM compute_runs WHERE status='success'"
            ).fetchone()[0]
            n_steps = conn.execute(
                "SELECT COUNT(DISTINCT step) FROM compute_runs WHERE status='success'"
            ).fetchone()[0]
            recent = conn.execute(
                """SELECT step, COUNT(*) AS n
                       FROM compute_runs WHERE status='success'
                       GROUP BY step ORDER BY n DESC LIMIT 5"""
            ).fetchall()
        n_hits   = int(r["n_hits"]   if r else 0)
        n_misses = int(r["n_misses"] if r else 0)
        total = n_hits + n_misses
        return {
            "n_hits":         n_hits,
            "n_misses":       n_misses,
            "hit_ratio":      (n_hits / total) if total else 0.0,
            "bytes_avoided":  int(r["bytes_avoided"] if r else 0),
            "n_success_runs": int(n_runs),
            "n_steps":        int(n_steps),
            "top_steps":      [{"step": x["step"], "n": int(x["n"])} for x in recent],
        }


# ── Module entry point ────────────────────────────────────────────


_instances: Dict[str, "DepCache"] = {}
_instances_lock = threading.Lock()


def open_dep_cache(project_id: str) -> DepCache:
    """Memoised per-project DepCache.  Aligns with RawStore so the
    on-disk layout is:

        <investment_root>/<project_id>/
            raw/                    ← RawStore (B1-B3)
            compute/                ← DepCache (B4)
                _dep_index.sqlite
                snapshots/<step>/<dep_hash>.json
    """
    from agent.finance import investment_projects

    with _instances_lock:
        inst = _instances.get(project_id)
        if inst is None:
            root = investment_projects.get_investment_root() / project_id / "compute"
            inst = DepCache(root)
            _instances[project_id] = inst
        return inst
