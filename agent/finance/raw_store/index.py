"""SQLite + FTS5 index over the raw store.

Three concerns:

  1. **Bitemporal lookup** — query `(valid_time, tx_time)` ranges
     without scanning the whole filesystem.
  2. **Crawl-run lookup** — list every blob touched by a given
     `crawl_run_id`.
  3. **Full-text search** — find blobs by article text (FTS5).

The on-disk path is ``<root>/_index.sqlite``.  Index is a
*derived* artifact: it can be rebuilt from blob meta.json files.
B1 keeps the rebuild simple (`reindex_all`); B7's validation step
verifies index ↔ filesystem consistency.

WAL mode + busy_timeout 5s for the multi-process case (uvicorn
worker + crawl scheduler running concurrently).
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from agent.finance.raw_store.meta import BlobMeta

logger = logging.getLogger(__name__)


_SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous   = NORMAL;
PRAGMA busy_timeout  = 5000;

CREATE TABLE IF NOT EXISTS blobs (
    sha256          TEXT PRIMARY KEY,
    size_bytes      INTEGER NOT NULL,
    url             TEXT NOT NULL,
    response_status INTEGER NOT NULL,
    valid_time      TEXT NOT NULL,                  -- ISO 8601 UTC
    first_seen_at   TEXT NOT NULL,                  -- ISO 8601 UTC
    simhash_64      INTEGER,                        -- nullable until B3
    schema_version  INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_blobs_valid_time    ON blobs(valid_time);
CREATE INDEX IF NOT EXISTS idx_blobs_first_seen_at ON blobs(first_seen_at);
CREATE INDEX IF NOT EXISTS idx_blobs_url           ON blobs(url);
CREATE INDEX IF NOT EXISTS idx_blobs_simhash       ON blobs(simhash_64);

-- Many-to-many: which crawl_runs hit which blobs, with tx_time.
-- Lets us answer "give me every blob crawl_run X selected" cheaply.
CREATE TABLE IF NOT EXISTS blob_seen_at (
    sha256        TEXT NOT NULL,
    crawl_run_id  TEXT NOT NULL,
    tx_time       TEXT NOT NULL,
    PRIMARY KEY (sha256, crawl_run_id),
    FOREIGN KEY (sha256) REFERENCES blobs(sha256) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_seen_run_id ON blob_seen_at(crawl_run_id);

-- Crawl-run registry.  One row per crawl run.  Manifest JSON lives
-- on the filesystem; this table is the index for fast lookups.
CREATE TABLE IF NOT EXISTS crawl_runs (
    crawl_run_id    TEXT PRIMARY KEY,
    source          TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    completed_at    TEXT,
    status          TEXT NOT NULL,                  -- running|success|partial|failed
    blob_count      INTEGER NOT NULL DEFAULT 0,
    new_blob_count  INTEGER NOT NULL DEFAULT 0,
    schema_version  INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_runs_source        ON crawl_runs(source);
CREATE INDEX IF NOT EXISTS idx_runs_started_at    ON crawl_runs(started_at);

-- FTS5 virtual table for full-text search over extracted article text.
-- Populated lazily: we don't extract text in B1 (raw bytes are stored,
-- text extraction is a B3+ concern).  The table is created here so
-- B3 just needs to start writing into it.
CREATE VIRTUAL TABLE IF NOT EXISTS blob_fts USING fts5(
    sha256       UNINDEXED,
    extracted_text,
    title,
    tokenize = 'unicode61 remove_diacritics 2'
);
"""


class RawIndex:
    """Thin SQLite wrapper.  Connections are per-thread (sqlite3
    objects aren't safe across threads); a small pool keeps writes
    on a single dedicated connection."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.db_path = self.root / "_index.sqlite"
        self._local = threading.local()
        self.root.mkdir(parents=True, exist_ok=True)
        # Initialise schema using a one-shot connection.
        with self._open() as conn:
            conn.executescript(_SCHEMA_SQL)

    @contextmanager
    def _open(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    # ── upsert: blob meta ─────────────────────────────────────────

    def upsert_blob(self, meta: BlobMeta) -> None:
        """Insert or update a row in blobs +  refresh blob_seen_at.

        Idempotent — calling repeatedly with the same meta is a no-op.
        """
        with self._open() as conn:
            conn.execute(
                """
                INSERT INTO blobs (
                    sha256, size_bytes, url, response_status,
                    valid_time, first_seen_at, simhash_64, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sha256) DO UPDATE SET
                    size_bytes=excluded.size_bytes,
                    url=excluded.url,
                    response_status=excluded.response_status,
                    valid_time=excluded.valid_time,
                    first_seen_at=excluded.first_seen_at,
                    simhash_64=excluded.simhash_64,
                    schema_version=excluded.schema_version
                """,
                (
                    meta.sha256, meta.size_bytes, meta.url,
                    meta.response_status, meta.valid_time, meta.first_seen_at,
                    meta.simhash_64, meta.schema_version,
                ),
            )
            for s in meta.seen_at:
                if not s.crawl_run_id:
                    continue
                conn.execute(
                    """
                    INSERT OR IGNORE INTO blob_seen_at
                        (sha256, crawl_run_id, tx_time)
                    VALUES (?, ?, ?)
                    """,
                    (meta.sha256, s.crawl_run_id, s.tx_time),
                )

    # ── upsert: crawl run ─────────────────────────────────────────

    def upsert_crawl_run(
        self,
        crawl_run_id:   str,
        source:         str,
        started_at:     str,
        completed_at:   Optional[str],
        status:         str,
        blob_count:     int,
        new_blob_count: int,
    ) -> None:
        with self._open() as conn:
            conn.execute(
                """
                INSERT INTO crawl_runs (
                    crawl_run_id, source, started_at, completed_at,
                    status, blob_count, new_blob_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(crawl_run_id) DO UPDATE SET
                    source=excluded.source,
                    started_at=excluded.started_at,
                    completed_at=excluded.completed_at,
                    status=excluded.status,
                    blob_count=excluded.blob_count,
                    new_blob_count=excluded.new_blob_count
                """,
                (
                    crawl_run_id, source, started_at, completed_at,
                    status, blob_count, new_blob_count,
                ),
            )

    # ── reads ─────────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        """Top-level counts for the /api/raw/stats endpoint."""
        with self._open() as conn:
            blob_row = conn.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(size_bytes),0) AS sz FROM blobs",
            ).fetchone()
            run_row = conn.execute(
                "SELECT COUNT(*) AS n FROM crawl_runs",
            ).fetchone()
            time_row = conn.execute(
                "SELECT MIN(first_seen_at) AS oldest, MAX(first_seen_at) AS newest "
                "FROM blobs",
            ).fetchone()
            return {
                "blob_count":     blob_row["n"],
                "total_bytes":    blob_row["sz"],
                "crawl_run_count": run_row["n"],
                "oldest_tx_time": time_row["oldest"],
                "newest_tx_time": time_row["newest"],
            }

    def list_blobs(
        self,
        *,
        limit:         int = 50,
        since_tx_time: Optional[str] = None,
        source_url:    Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        sql_parts = ["SELECT * FROM blobs WHERE 1=1"]
        params: List[Any] = []
        if since_tx_time:
            sql_parts.append("AND first_seen_at >= ?")
            params.append(since_tx_time)
        if source_url:
            sql_parts.append("AND url LIKE ?")
            params.append(f"%{source_url}%")
        sql_parts.append("ORDER BY first_seen_at DESC LIMIT ?")
        params.append(int(limit))
        with self._open() as conn:
            rows = conn.execute(" ".join(sql_parts), params).fetchall()
            return [dict(r) for r in rows]

    def get_blob(self, sha256: str) -> Optional[Dict[str, Any]]:
        with self._open() as conn:
            row = conn.execute(
                "SELECT * FROM blobs WHERE sha256 = ?", (sha256,),
            ).fetchone()
            if not row:
                return None
            d = dict(row)
            seen = conn.execute(
                "SELECT crawl_run_id, tx_time FROM blob_seen_at "
                "WHERE sha256 = ? ORDER BY tx_time ASC",
                (sha256,),
            ).fetchall()
            d["seen_at"] = [dict(s) for s in seen]
            return d

    def list_crawl_runs(
        self, *, limit: int = 50, source: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM crawl_runs WHERE 1=1"
        params: List[Any] = []
        if source:
            sql += " AND source = ?"
            params.append(source)
        sql += " ORDER BY started_at DESC LIMIT ?"
        params.append(int(limit))
        with self._open() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def list_blobs_for_run(self, crawl_run_id: str) -> List[Dict[str, Any]]:
        with self._open() as conn:
            return [dict(r) for r in conn.execute(
                """
                SELECT b.*, sa.tx_time
                FROM blobs b
                JOIN blob_seen_at sa ON sa.sha256 = b.sha256
                WHERE sa.crawl_run_id = ?
                ORDER BY sa.tx_time ASC
                """,
                (crawl_run_id,),
            ).fetchall()]

    def search(self, query: str, *, limit: int = 20) -> List[Dict[str, Any]]:
        """FTS5 search.  In B1 the index has no rows yet (text
        extraction lands in B3), so this returns []."""
        with self._open() as conn:
            try:
                rows = conn.execute(
                    """
                    SELECT b.*, snippet(blob_fts, 1, '<mark>', '</mark>', '…', 12) AS snippet
                    FROM blob_fts
                    JOIN blobs b ON b.sha256 = blob_fts.sha256
                    WHERE blob_fts MATCH ?
                    LIMIT ?
                    """,
                    (query, int(limit)),
                ).fetchall()
                return [dict(r) for r in rows]
            except sqlite3.OperationalError:
                return []

    def index_text(
        self, sha256: str, *, extracted_text: str, title: str = "",
    ) -> None:
        """Populate FTS5 row.  Used by B3+ when the crawler extracts
        article text."""
        with self._open() as conn:
            conn.execute("DELETE FROM blob_fts WHERE sha256 = ?", (sha256,))
            conn.execute(
                "INSERT INTO blob_fts (sha256, extracted_text, title) VALUES (?, ?, ?)",
                (sha256, extracted_text, title),
            )

    # ── maintenance ──────────────────────────────────────────────

    def reindex_all_meta(self, meta_iter: Iterator[BlobMeta]) -> int:
        """Walk every meta.json on disk and upsert into blobs +
        blob_seen_at.  Used after a fresh clone / corruption recovery.
        Returns count of upserted blobs."""
        n = 0
        for m in meta_iter:
            self.upsert_blob(m)
            n += 1
        return n
