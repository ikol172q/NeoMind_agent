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


@router.get("/blobs/as-of")
def blobs_as_of(
    project_id:     str           = Query(...),
    valid_time_max: Optional[str] = Query(None, description="ISO 8601 — blob.valid_time <= this"),
    tx_time_max:    Optional[str] = Query(None, description="ISO 8601 — blob.first_seen_at <= this"),
    valid_time_min: Optional[str] = Query(None),
    tx_time_min:    Optional[str] = Query(None),
    source_url:     Optional[str] = Query(None),
    limit:          int           = Query(100, ge=1, le=500),
) -> Dict[str, Any]:
    """Phase B2 — bitemporal AS-OF query.

    Implements the SQL:2011 ``FOR SYSTEM_TIME AS OF`` semantics on
    top of the raw store: returns blobs that satisfy *both* the
    valid-time bound (the underlying event happened before the
    requested wall-clock) AND the transaction-time bound (we had
    observed it by the requested observation moment).

    Either bound is optional — provide one to narrow that dimension
    only.

    Note: route declared BEFORE /blobs/{sha256} so FastAPI matches
    the literal "as-of" before treating it as a path parameter.
    """
    _check_project(project_id)
    store = RawStore.for_project(project_id)
    rows = store.index.query_bitemporal(
        valid_time_max=valid_time_max,
        valid_time_min=valid_time_min,
        tx_time_max=tx_time_max,
        tx_time_min=tx_time_min,
        source_url=source_url,
        limit=limit,
    )
    return {
        "project_id":     project_id,
        "count":          len(rows),
        "blobs":          rows,
        "valid_time_max": valid_time_max,
        "tx_time_max":    tx_time_max,
        "valid_time_min": valid_time_min,
        "tx_time_min":    tx_time_min,
        "explanation": (
            "Bitemporal point-in-time query: rows match both valid_time "
            "AND transaction_time (first_seen_at) bounds."
        ),
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


@router.post("/_dev/crawl_news_synthetic")
def dev_crawl_news_synthetic(
    project_id:     str  = Query(...),
    n_articles:     int  = Query(5,  ge=1, le=50),
    n_reposts:      int  = Query(2,  ge=0, le=20,
                                description="N of the articles get reposted to extra sources"),
    silent_edit:    bool = Query(False,
                                description="re-fetch one article with edited body (silent edit demo)"),
    valid_time_age_hours: float = Query(6.0, ge=0, le=720,
                                description="how far in the past valid_time should be (vs now)"),
) -> Dict[str, Any]:
    """Phase B3 dev endpoint — simulates a realistic news crawl.

    Generates synthetic news entries that go through the SAME code
    path the real news crawler will use in production:
      - one CrawlRunHandle per call
      - each entry as one blob, content-addressed by body bytes
      - bitemporal: valid_time set to (now - valid_time_age_hours),
        transaction_time set to now → exercises B2's AS-OF queries
      - multi-source reposts: same article URL on different domain
        → produces distinct blobs (B3 will SimHash-dedupe in the
        compute step, not here)
      - optional silent edit: re-fetches one URL with different body
        bytes, demonstrates B1's supersede detection

    Gated by NEOMIND_RAW_DEV=1.  Used to exercise B1+B2+B3 end-to-end
    in the browser without needing Miniflux running.
    """
    import json as _json
    from datetime import datetime, timedelta, timezone
    if not _dev_enabled():
        raise HTTPException(
            403,
            "dev endpoints disabled — export NEOMIND_RAW_DEV=1 in the "
            "uvicorn process to enable",
        )
    _check_project(project_id)
    store = RawStore.for_project(project_id)

    now      = datetime.now(timezone.utc)
    valid_t  = (now - timedelta(hours=valid_time_age_hours)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    # Realistic-ish news content templates
    headlines = [
        ("AAPL hits new 52w high on services momentum",
         "Apple shares surged 2.3% as services revenue beat consensus..."),
        ("META reports earnings tomorrow; options volume spikes",
         "Implied volatility on Meta options has expanded to 4.2 vol points..."),
        ("MSFT closed +1.5% as cloud growth accelerates",
         "Microsoft's Azure segment grew 28% YoY versus 24% prior quarter..."),
        ("AMD outlook tempered by datacenter inventory glut",
         "Advanced Micro Devices guided down on Q4 datacenter ramp..."),
        ("ARM IPO lockup expires in 10 days; insider selling watched",
         "Arm Holdings' 180-day lockup unlocks an additional 95M shares..."),
    ]
    sources = [
        ("Reuters",     "https://reuters.com/markets/"),
        ("Bloomberg",   "https://bloomberg.com/news/articles/"),
        ("YahooFin",    "https://finance.yahoo.com/news/"),
        ("Xueqiu",      "https://xueqiu.com/today/"),
    ]

    blobs_written: List[Dict[str, Any]] = []
    with store.open_crawl_run(
        source="dev.news_synthetic",
        query={
            "n_articles": n_articles, "n_reposts": n_reposts,
            "silent_edit": silent_edit,
            "valid_time_age_hours": valid_time_age_hours,
        },
    ) as run:
        for i in range(min(n_articles, len(headlines))):
            title, body = headlines[i]
            # Primary source
            src_name, src_base = sources[0]
            url   = f"{src_base}article-{i}"
            entry = {
                "title":         title,
                "url":           url,
                "source":        src_name,
                "published_at":  valid_t,
                "body":          body,
                "id":            i,
            }
            payload = _json.dumps(entry, ensure_ascii=False).encode("utf-8")
            meta = run.add_blob(
                payload, url=url, response_status=200,
                response_headers={"Content-Type": "application/json"},
                valid_time=valid_t,
            )
            blobs_written.append({"url": url, "sha256": meta.sha256, "src": src_name})

            # Reposts: same body content reposted to additional sources
            # For B3 dedupe testing, we use IDENTICAL body bytes across
            # sources — that means content-addressing makes them ONE blob
            # (correct: same content). UI will surface "×4 sources" via
            # the URL multi-mapping (TODO in compute step).
            #
            # If we wanted DIFFERENT blobs per source, we'd vary the
            # body slightly (e.g. include source-specific header).
            #
            # For the demo: vary body so each repost is a distinct blob,
            # which exercises the storage layer; SimHash-dedup is a
            # later compute-side concern.
            if i < n_reposts:
                for src_name2, src_base2 in sources[1:1 + 2]:
                    url2 = f"{src_base2}article-{i}"
                    entry2 = dict(entry, source=src_name2, url=url2)
                    payload2 = _json.dumps(entry2, ensure_ascii=False).encode("utf-8")
                    m2 = run.add_blob(
                        payload2, url=url2, response_status=200,
                        response_headers={"Content-Type": "application/json"},
                        valid_time=valid_t,
                    )
                    blobs_written.append({"url": url2, "sha256": m2.sha256, "src": src_name2})

        # Silent edit: re-fetch article 0 with edited body bytes.
        # Same URL, different content → B1 should detect this and add
        # a supersede entry to the manifest.
        if silent_edit:
            src_name, src_base = sources[0]
            url   = f"{src_base}article-0"
            entry = {
                "title":         headlines[0][0] + " — UPDATED",
                "url":           url,
                "source":        src_name,
                "published_at":  valid_t,
                "body":          headlines[0][1] + " (UPDATED 30 min later: revenue figure revised)",
                "id":            0,
            }
            payload = _json.dumps(entry, ensure_ascii=False).encode("utf-8")
            meta = run.add_blob(
                payload, url=url, response_status=200,
                response_headers={"Content-Type": "application/json"},
                valid_time=valid_t,
            )
            blobs_written.append({"url": url, "sha256": meta.sha256, "src": src_name + " (edited)"})

        run_id   = run.crawl_run_id
        date_str = run.date_str

    return {
        "project_id":   project_id,
        "crawl_run_id": run_id,
        "date":         date_str,
        "blobs":        blobs_written,
        "wrote_n":      len(blobs_written),
        "explanation": (
            f"Wrote {len(blobs_written)} synthetic news blobs through the "
            f"same RawStore code path the real news crawler will use in "
            f"production. valid_time={valid_t} (different from now() "
            f"so AS-OF queries demonstrate bitemporal). Repeat this "
            f"endpoint with silent_edit=true to see B1's supersede "
            f"detection fire."
        ),
    }
