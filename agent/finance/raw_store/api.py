"""FastAPI router exposing read-only views over the raw store +
a guarded dev-seed endpoint for browser smoke testing.

Endpoints:

  GET  /api/raw/stats?project_id=...                       blob_count, total_bytes, …
  GET  /api/raw/blobs?project_id=...&limit=&since=         list recent blobs
  GET  /api/raw/blobs/{sha256}?project_id=...              one blob's meta + body preview
  GET  /api/raw/blobs/{sha256}/raw?project_id=...          raw .warc.gz download
  GET  /api/raw/crawl-runs?project_id=...&limit=&source=   recent crawl runs
  GET  /api/raw/crawl-runs/{run_id}?project_id=...&date=   one crawl run + manifest + report
  GET  /api/raw/search?project_id=...&q=...                FTS5 search (B3+ wires text)
  POST /api/raw/_dev/seed?project_id=...&n=3               generate test blobs (dev only)

The dev-seed endpoint is gated by the env var NEOMIND_RAW_DEV=1
to keep it off in any production deployment.
"""
from __future__ import annotations

import base64
import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from agent.finance import investment_projects
from agent.finance.raw_store.blobs import read_blob, read_blob_bytes
from agent.finance.raw_store.store import RawStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/raw", tags=["raw-store"])


def _check_project(project_id: str) -> None:
    if project_id not in investment_projects.list_projects():
        raise HTTPException(404, f"project {project_id!r} is not registered")


@router.get("/stats")
def raw_stats(project_id: str = Query(...)) -> Dict[str, Any]:
    _check_project(project_id)
    store = RawStore.for_project(project_id)
    s = store.stats()
    s["project_id"] = project_id
    s["explanation"] = (
        "Counts and bytes of the immutable raw store. "
        "index_drift=true means the SQLite index disagrees with the "
        "on-disk blob count — run /api/raw/_dev/reindex to recover."
    )
    return s


@router.get("/blobs")
def list_blobs(
    project_id:    str = Query(...),
    limit:         int = Query(50, ge=1, le=500),
    since_tx_time: Optional[str] = Query(None, description="ISO 8601 — first_seen_at >= this"),
    source_url:    Optional[str] = Query(None, description="LIKE-match on URL"),
) -> Dict[str, Any]:
    _check_project(project_id)
    store = RawStore.for_project(project_id)
    rows = store.index.list_blobs(
        limit=limit,
        since_tx_time=since_tx_time,
        source_url=source_url,
    )
    return {
        "project_id": project_id,
        "count":      len(rows),
        "blobs":      rows,
    }


@router.get("/blobs/{sha256}")
def get_blob(
    project_id:    str = Query(...),
    sha256:        str = "",
    body_preview:  int = Query(500, ge=0, le=8000),
) -> Dict[str, Any]:
    _check_project(project_id)
    store = RawStore.for_project(project_id)
    row = store.index.get_blob(sha256)
    if row is None:
        raise HTTPException(404, f"unknown blob {sha256!r}")
    # Try to read body preview; tolerate read errors (return what we have).
    preview: Optional[str] = None
    body_bytes_len: Optional[int] = None
    try:
        meta, body = read_blob(store.raw_root, sha256)
        body_bytes_len = len(body)
        if body_preview > 0:
            preview = body[:body_preview].decode(errors="replace")
        # also pull the response_headers from the sidecar for the UI
        row["response_headers"] = meta.response_headers
    except Exception as exc:  # noqa: BLE001
        row["read_error"] = f"{type(exc).__name__}: {exc}"
    row["body_bytes_len"] = body_bytes_len
    row["body_preview"]   = preview
    return row


@router.get("/blobs/{sha256}/raw")
def get_blob_raw(
    project_id: str = Query(...),
    sha256:     str = "",
) -> Response:
    """Return the raw .warc.gz bytes (download)."""
    _check_project(project_id)
    store = RawStore.for_project(project_id)
    try:
        data = read_blob_bytes(store.raw_root, sha256)
    except FileNotFoundError:
        raise HTTPException(404, f"blob {sha256!r} not found")
    except RuntimeError as exc:
        raise HTTPException(500, str(exc))
    return Response(
        content=data,
        media_type="application/warc",
        headers={
            "Content-Disposition": f'attachment; filename="{sha256[:12]}.warc.gz"',
        },
    )


@router.get("/crawl-runs")
def list_crawl_runs(
    project_id: str = Query(...),
    limit:      int = Query(50, ge=1, le=500),
    source:     Optional[str] = Query(None),
) -> Dict[str, Any]:
    _check_project(project_id)
    store = RawStore.for_project(project_id)
    runs = store.index.list_crawl_runs(limit=limit, source=source)
    return {
        "project_id": project_id,
        "count":      len(runs),
        "runs":       runs,
    }


@router.get("/crawl-runs/{crawl_run_id}")
def get_crawl_run(
    project_id:   str = Query(...),
    date:         str = Query(..., description="YYYY-MM-DD when the run started"),
    crawl_run_id: str = "",
) -> Dict[str, Any]:
    _check_project(project_id)
    store = RawStore.for_project(project_id)
    manifest = store.read_crawl_manifest(date, crawl_run_id)
    if manifest is None:
        raise HTTPException(404, f"crawl_run {crawl_run_id!r} not found on {date}")
    report = store.read_crawl_report(date, crawl_run_id)
    blobs = store.index.list_blobs_for_run(crawl_run_id)
    return {
        "project_id": project_id,
        "date":       date,
        "manifest":   manifest.to_json(),
        "report":     report.to_json() if report else None,
        "blobs":      blobs,
    }


@router.get("/search")
def search(
    project_id: str = Query(...),
    q:          str = Query(..., min_length=1),
    limit:      int = Query(20, ge=1, le=200),
) -> Dict[str, Any]:
    _check_project(project_id)
    store = RawStore.for_project(project_id)
    results = store.index.search(q, limit=limit)
    return {
        "project_id": project_id,
        "query":      q,
        "count":      len(results),
        "results":    results,
        "explanation": (
            "FTS5 full-text search over extracted_text. In Phase B1 the "
            "FTS index is empty (text extraction is wired in B3); this "
            "endpoint will return [] until then."
        ),
    }


# ── dev-only endpoints (gated by NEOMIND_RAW_DEV=1) ──────────────


def _dev_enabled() -> bool:
    return os.environ.get("NEOMIND_RAW_DEV") == "1"


@router.post("/_dev/seed")
def dev_seed(
    project_id: str = Query(...),
    n:          int = Query(3, ge=1, le=20),
) -> Dict[str, Any]:
    """Generate N synthetic raw blobs for browser smoke-testing.

    Off by default; export NEOMIND_RAW_DEV=1 to enable.  Lets you
    verify the read endpoints without yet wiring real crawlers.
    """
    if not _dev_enabled():
        raise HTTPException(
            403,
            "dev seeding disabled — export NEOMIND_RAW_DEV=1 in the "
            "uvicorn process to enable",
        )
    _check_project(project_id)
    store = RawStore.for_project(project_id)
    written: List[Dict[str, Any]] = []
    with store.open_crawl_run(
        source="dev.seed", query={"n": n},
    ) as run:
        for i in range(n):
            url = f"https://example.com/dev/news/{i}"
            body = (
                f"<html><body><h1>Synthetic news #{i}</h1>"
                f"<p>AAPL near 52w high, {i} day(s) into earnings season.</p>"
                f"</body></html>"
            ).encode("utf-8")
            meta = run.add_blob(
                body,
                url=url,
                response_status=200,
                response_headers={"Content-Type": "text/html"},
            )
            written.append({"sha256": meta.sha256, "url": url})
    return {
        "project_id": project_id,
        "crawl_run_id": run.crawl_run_id,
        "wrote_n":    len(written),
        "blobs":      written,
        "explanation": (
            "Wrote N synthetic blobs through the same code path real "
            "crawlers will use in B3.  Inspect them via /api/raw/blobs."
        ),
    }


@router.post("/_dev/reindex")
def dev_reindex(project_id: str = Query(...)) -> Dict[str, Any]:
    """Rebuild SQLite index by walking blobs/meta.json.  Used after
    sync / corruption recovery.  Gated like /_dev/seed."""
    if not _dev_enabled():
        raise HTTPException(403, "dev endpoints disabled — export NEOMIND_RAW_DEV=1")
    _check_project(project_id)
    store = RawStore.for_project(project_id)
    n = store.reindex_from_disk()
    return {"project_id": project_id, "reindexed_blobs": n}
