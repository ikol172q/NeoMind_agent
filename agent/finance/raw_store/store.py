"""High-level RawStore facade.

Wraps blob writes + meta sidecar + index + crawl-run manifests so
callers don't have to coordinate the four pieces themselves.

Usage in a crawler (B3 will refactor existing crawlers onto this):

    store = RawStore.for_project(project_id="fin-core")
    with store.open_crawl_run(source="news.yfinance",
                              query={"symbol": "AAPL", "limit": 30}) as run:
        for url, body, status, headers, valid_time in fetched:
            run.add_blob(
                body, url=url,
                response_status=status, response_headers=headers,
                valid_time=valid_time,
            )
        # run.finish() called by context manager
"""
from __future__ import annotations

import json
import logging
import random
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from agent.finance import investment_projects
from agent.finance.raw_store.blobs import (
    blob_path, list_blob_paths, read_blob, sha256_of_bytes, stats as fs_stats,
    write_blob,
)
from agent.finance.raw_store.index import RawIndex
from agent.finance.raw_store.meta import (
    BlobMeta, CrawlRunManifest, CrawlRunReport, SeenAtRecord,
)

logger = logging.getLogger(__name__)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class CrawlRunHandle:
    """Per-crawl writer.  Created by RawStore.open_crawl_run().
    Tracks which blobs the run has touched so we can write a
    coherent manifest + report at finish().
    """

    def __init__(
        self,
        store:        "RawStore",
        crawl_run_id: str,
        source:       str,
        query:        Dict[str, Any],
        date_str:     str,
    ) -> None:
        self.store        = store
        self.crawl_run_id = crawl_run_id
        self.source       = source
        self.query        = dict(query)
        self.date_str     = date_str
        self.started_at   = _utcnow_iso()
        self._touched:           List[str] = []
        self._newly_fetched:     List[str] = []
        self._superseded:        List[Dict[str, str]] = []
        self._http_4xx:          int = 0
        self._http_5xx:          int = 0
        self._closed:            bool = False
        self._url_to_hash_seen:  Dict[str, str] = {}
        # Index a "running" row early so the UI / Status panel can
        # see in-flight crawls.
        self.store.index.upsert_crawl_run(
            crawl_run_id=crawl_run_id,
            source=source,
            started_at=self.started_at,
            completed_at=None,
            status="running",
            blob_count=0,
            new_blob_count=0,
        )

    def add_blob(
        self,
        body_bytes: bytes,
        *,
        url:              str,
        response_status:  int,
        response_headers: Optional[Dict[str, str]] = None,
        valid_time:       Optional[str] = None,
        simhash_64:       Optional[int] = None,
    ) -> BlobMeta:
        """Write one fetched response.  Returns the BlobMeta.

        Detects silent retroactive edits: if this URL was previously
        recorded with a *different* sha256 in the same run, log a
        supersede entry.  (Cross-run edits — same URL, different
        bytes across two runs — are detected by the index queries
        in B7's validation step.)
        """
        if response_status >= 500:
            self._http_5xx += 1
        elif response_status >= 400:
            self._http_4xx += 1

        meta, is_new = write_blob(
            self.store.raw_root,
            body_bytes,
            url=url,
            response_status=response_status,
            response_headers=response_headers,
            valid_time=valid_time,
            crawl_run_id=self.crawl_run_id,
            simhash_64=simhash_64,
        )

        # Cross-run silent-edit detection: if this URL has a previous
        # BlobMeta on disk with a different sha256, record a supersede.
        prior_hashes = [
            row["sha256"] for row in self.store.index.list_blobs(
                limit=10, source_url=url,
            ) if row["sha256"] != meta.sha256
        ]
        if prior_hashes and is_new:
            self._superseded.append({
                "url": url, "old_hash": prior_hashes[0], "new_hash": meta.sha256,
            })

        self.store.index.upsert_blob(meta)
        self._touched.append(meta.sha256)
        if is_new:
            self._newly_fetched.append(meta.sha256)
        self._url_to_hash_seen[url] = meta.sha256
        return meta

    def fail(self, error: str) -> None:
        """Mark the crawl run as failed.  Manifest still written so
        partial progress is recorded; status='failed'."""
        self._closed = True
        self._write_manifest_and_report(status="failed", error=error)

    def _write_manifest_and_report(
        self, *, status: str, error: Optional[str] = None,
    ) -> None:
        completed_at = _utcnow_iso()
        manifest = CrawlRunManifest(
            crawl_run_id=        self.crawl_run_id,
            source=              self.source,
            query=               self.query,
            started_at=          self.started_at,
            completed_at=        completed_at,
            status=              status,
            selected_blobs=      list(dict.fromkeys(self._touched)),       # dedup, preserve order
            newly_fetched_blobs= list(dict.fromkeys(self._newly_fetched)),
            superseded_versions= list(self._superseded),
            error=               error,
        )
        self.store.write_crawl_manifest(self.date_str, manifest)

        # Build a report — sample 5 random blobs for spot-check.
        sample_hashes = random.sample(
            list(set(self._touched)),
            k=min(5, len(set(self._touched))),
        )
        sample_items = []
        for h in sample_hashes:
            try:
                m, body = read_blob(self.store.raw_root, h)
                first_120 = body[:120].decode(errors="replace")
                sample_items.append({
                    "sha256":          h,
                    "url":             m.url,
                    "valid_time":      m.valid_time,
                    "first_120_chars": first_120,
                })
            except Exception as exc:  # noqa: BLE001
                sample_items.append({"sha256": h, "error": str(exc)})

        report = CrawlRunReport(
            crawl_run_id=    self.crawl_run_id,
            totals={
                "fetched":            len(self._touched),
                "new":                len(self._newly_fetched),
                "deduped_by_simhash": 0,             # B3 will fill
                "superseded":         len(self._superseded),
                "http_4xx":           self._http_4xx,
                "http_5xx":           self._http_5xx,
            },
            sample=          sample_items,
            anomaly_alerts=  list(self._compute_anomaly_alerts()),
        )
        self.store.write_crawl_report(self.date_str, report)
        # Update index row to final status.
        self.store.index.upsert_crawl_run(
            crawl_run_id=self.crawl_run_id,
            source=self.source,
            started_at=self.started_at,
            completed_at=completed_at,
            status=status,
            blob_count=len(set(self._touched)),
            new_blob_count=len(set(self._newly_fetched)),
        )

    def _compute_anomaly_alerts(self) -> Iterator[str]:
        if self._http_5xx > 0:
            yield f"{self._http_5xx} responses returned HTTP 5xx"
        if self._superseded:
            yield (
                f"{len(self._superseded)} URL(s) returned different bytes "
                f"than a previous crawl — silent retroactive edit suspected"
            )
        if not self._touched:
            yield "crawl run produced 0 blobs"


class RawStore:
    """Project-scoped store.  Each project gets its own raw/ tree
    + _index.sqlite.  Path-portable: the root is configurable so
    future multi-machine sync only needs to swap one parameter."""

    _instances:       Dict[str, "RawStore"] = {}
    _instances_lock:  threading.Lock = threading.Lock()

    def __init__(self, project_id: str, raw_root: Path) -> None:
        self.project_id = project_id
        self.raw_root   = Path(raw_root)
        self.raw_root.mkdir(parents=True, exist_ok=True)
        (self.raw_root / "blobs").mkdir(exist_ok=True)
        (self.raw_root / "crawl_runs").mkdir(exist_ok=True)
        self.index = RawIndex(self.raw_root)

    @classmethod
    def for_project(cls, project_id: str) -> "RawStore":
        """Memoised per-project entry point.  Singleton per project
        per process — multiple opens share one RawIndex."""
        with cls._instances_lock:
            inst = cls._instances.get(project_id)
            if inst is None:
                root = investment_projects.get_investment_root() / project_id / "raw"
                inst = cls(project_id, root)
                cls._instances[project_id] = inst
            return inst

    # ── crawl-run lifecycle ──────────────────────────────────────

    @contextmanager
    def open_crawl_run(
        self,
        *,
        source: str,
        query:  Optional[Dict[str, Any]] = None,
    ) -> Iterator[CrawlRunHandle]:
        crawl_run_id = uuid.uuid4().hex
        date_str     = _today_str()
        handle = CrawlRunHandle(
            store=self, crawl_run_id=crawl_run_id, source=source,
            query=query or {}, date_str=date_str,
        )
        try:
            yield handle
        except Exception as exc:  # noqa: BLE001
            handle.fail(error=f"{type(exc).__name__}: {exc}")
            raise
        else:
            if not handle._closed:
                handle._write_manifest_and_report(status="success")
                handle._closed = True

    # ── manifest + report on-disk ────────────────────────────────

    def crawl_runs_dir(self, date_str: str) -> Path:
        return self.raw_root / "crawl_runs" / date_str

    def write_crawl_manifest(self, date_str: str, m: CrawlRunManifest) -> Path:
        d = self.crawl_runs_dir(date_str)
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{m.crawl_run_id}.json"
        p.write_text(json.dumps(m.to_json(), ensure_ascii=False, indent=2))
        return p

    def write_crawl_report(self, date_str: str, r: CrawlRunReport) -> Path:
        d = self.crawl_runs_dir(date_str)
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{r.crawl_run_id}.report.json"
        p.write_text(json.dumps(r.to_json(), ensure_ascii=False, indent=2))
        return p

    def read_crawl_manifest(
        self, date_str: str, crawl_run_id: str,
    ) -> Optional[CrawlRunManifest]:
        p = self.crawl_runs_dir(date_str) / f"{crawl_run_id}.json"
        if not p.is_file():
            return None
        return CrawlRunManifest.from_json(json.loads(p.read_text()))

    def read_crawl_report(
        self, date_str: str, crawl_run_id: str,
    ) -> Optional[CrawlRunReport]:
        p = self.crawl_runs_dir(date_str) / f"{crawl_run_id}.report.json"
        if not p.is_file():
            return None
        return CrawlRunReport.from_json(json.loads(p.read_text()))

    # ── stats ──────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        idx = self.index.stats()
        fs  = fs_stats(self.raw_root)
        # If the two disagree → silent corruption / index drift.
        idx["fs_blob_count"]  = fs["blob_count"]
        idx["fs_total_bytes"] = fs["total_bytes"]
        idx["index_drift"]    = (idx["blob_count"] != fs["blob_count"])
        return idx

    # ── reindex (rebuild from disk) ──────────────────────────────

    def reindex_from_disk(self) -> int:
        """Re-walk every meta.json on disk and upsert into the index.
        Used after corruption recovery / fresh clone of the data dir."""
        def iter_meta() -> Iterator[BlobMeta]:
            for p in list_blob_paths(self.raw_root):
                meta_p = p.with_suffix(".meta.json").with_name(
                    p.stem.replace(".warc", "") + ".meta.json",
                )
                # Actually .warc.gz → stem is "abc...def.warc"; want
                # "abc...def.meta.json"
                stem_no_warc = p.name.removesuffix(".warc.gz")
                meta_p = p.parent / f"{stem_no_warc}.meta.json"
                if meta_p.is_file():
                    yield BlobMeta.from_json(json.loads(meta_p.read_text()))
        return self.index.reindex_all_meta(iter_meta())
