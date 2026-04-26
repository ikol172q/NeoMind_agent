"""Content-addressed WARC blob writer/reader.

Layout under ``<root>/<project_id>/raw/blobs/``:

    <sha256[:2]>/<sha256>.warc.gz        ← the raw bytes, WARC v1
    <sha256[:2]>/<sha256>.meta.json      ← BlobMeta sidecar

Two-character prefix subdirectory avoids the "100k files in one
folder" filesystem-stall problem (DVC convention).

INVARIANT: the filename is ``sha256(HTTP response body)``.  WARC is
the storage format (so future Wayback-style tooling can read), but
the **content identity** is the body, not the WARC envelope — WARC
adds per-write UUIDs/timestamps to its envelope so two writes of
the same body would otherwise produce different envelope bytes.

The reader extracts the body, re-hashes it, and asserts equality
with the filename — silent-disk-corruption guard.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agent.finance.raw_store.meta import BlobMeta, SeenAtRecord

logger = logging.getLogger(__name__)

_write_lock = threading.Lock()


def sha256_of_bytes(data: bytes) -> str:
    """64-char lowercase hex digest."""
    return hashlib.sha256(data).hexdigest()


def blob_path(root: Path, sha256: str, *, suffix: str = ".warc.gz") -> Path:
    """Resolve to ``<root>/blobs/<sha256[:2]>/<sha256><suffix>``.

    Does not imply existence.  Used both for writes (target path)
    and reads (lookup path).
    """
    if len(sha256) != 64 or not all(c in "0123456789abcdef" for c in sha256):
        raise ValueError(f"invalid sha256 {sha256!r}; expected 64-char lowercase hex")
    prefix = sha256[:2]
    return root / "blobs" / prefix / f"{sha256}{suffix}"


def _utcnow_iso() -> str:
    """Microsecond-precision UTC, ISO 8601 with Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _build_warc_record(
    url:               str,
    body_bytes:        bytes,
    *,
    response_status:   int,
    response_headers:  Dict[str, str],
) -> bytes:
    """Wrap one HTTP response in a WARC v1 record (gzipped)."""
    # Lazy import: warcio is a soft dep — keeps import-time cheap if
    # the package is loaded but never used.
    from warcio.warcwriter import WARCWriter
    from warcio.statusandheaders import StatusAndHeaders

    out = BytesIO()
    writer = WARCWriter(out, gzip=True)
    statusline = f"{response_status} {_status_text(response_status)}"
    http_headers = StatusAndHeaders(
        statusline,
        list(response_headers.items()),
        protocol="HTTP/1.1",
    )
    record = writer.create_warc_record(
        url,
        "response",
        payload=BytesIO(body_bytes),
        http_headers=http_headers,
    )
    writer.write_record(record)
    return out.getvalue()


def _status_text(code: int) -> str:
    return {
        200: "OK", 201: "Created", 204: "No Content",
        301: "Moved Permanently", 302: "Found", 304: "Not Modified",
        400: "Bad Request", 401: "Unauthorized", 403: "Forbidden",
        404: "Not Found", 429: "Too Many Requests",
        500: "Internal Server Error", 502: "Bad Gateway",
        503: "Service Unavailable",
    }.get(code, "")


def write_blob(
    root:              Path,
    body_bytes:        bytes,
    *,
    url:               str,
    response_status:   int,
    response_headers:  Optional[Dict[str, str]] = None,
    valid_time:        Optional[str] = None,
    crawl_run_id:      Optional[str] = None,
    simhash_64:        Optional[int] = None,
) -> Tuple[BlobMeta, bool]:
    """Write a fetched response into the raw store.

    Returns ``(meta, is_new)``:
      - ``is_new == True``  when these exact bytes were not yet on disk
        (i.e., a fresh blob was written).
      - ``is_new == False`` when the blob already existed (idempotent
        rewrite); seen_at is appended in-place.

    Behaviour for "different bytes, same URL" (silent edit): the new
    bytes get a NEW sha256 and a new blob.  The OLD blob's meta is
    updated with no change (already-fetched URLs from earlier crawl
    runs still resolve to their original bytes).  The crawler that
    discovered the diff is responsible for recording the supersede
    relation in its crawl_run manifest (see CrawlRunManifest.
    superseded_versions).  This module only handles bytes ↔ hash.

    Args:
      root:    e.g. ``<investment_root>/<project_id>/raw``
      body_bytes:  raw HTTP response body bytes (un-decoded)
      url:     canonical request URL
      response_status:  HTTP status code
      response_headers: response headers dict (header name preserved
                        as fetched; we don't lowercase)
      valid_time:  ISO datetime — when the underlying event happened
                   (article published_at / market trade_date / ...).
                   Defaults to now if not known (useful for raw HTML
                   without parsed content yet).
      crawl_run_id:  the crawl run that discovered this blob.  Used
                     to populate seen_at on first write.
      simhash_64:  optional precomputed SimHash for multi-source
                   dedupe (B3 sets it; B1 leaves None).

    Side effects:
      - writes ``<root>/blobs/<sha256[:2]>/<sha256>.warc.gz``
      - writes/updates ``<root>/blobs/<sha256[:2]>/<sha256>.meta.json``
    """
    if not isinstance(body_bytes, (bytes, bytearray)):
        raise TypeError(f"body_bytes must be bytes, got {type(body_bytes).__name__}")
    headers = dict(response_headers or {})
    valid_t = valid_time or _utcnow_iso()
    tx_time = _utcnow_iso()

    # Content identity = sha256 of the BODY (not the WARC envelope).
    # WARC envelopes vary across writes (per-record UUID, timestamp);
    # the body is the meaningful unit of "same content".
    body = bytes(body_bytes)
    sha256 = sha256_of_bytes(body)

    target_warc = blob_path(root, sha256, suffix=".warc.gz")
    target_meta = blob_path(root, sha256, suffix=".meta.json")
    target_warc.parent.mkdir(parents=True, exist_ok=True)

    # Critical section — multiple concurrent crawlers may race for the
    # same sha256.  File-level lock would be ideal; in-process lock
    # covers the single-uvicorn case.
    is_new: bool
    with _write_lock:
        if not target_warc.exists():
            # Truly new content — build & write the WARC envelope.
            warc_bytes = _build_warc_record(
                url, body,
                response_status=response_status,
                response_headers=headers,
            )
            tmp_warc = target_warc.with_suffix(".warc.gz.tmp")
            tmp_warc.write_bytes(warc_bytes)
            tmp_warc.replace(target_warc)
            is_new = True
            seen_at = [SeenAtRecord(crawl_run_id=crawl_run_id or "", tx_time=tx_time)] \
                if crawl_run_id else []
            meta = BlobMeta(
                sha256=            sha256,
                size_bytes=        len(body),         # bytes of the body, not envelope
                url=               url,
                response_status=   response_status,
                response_headers=  headers,
                valid_time=        valid_t,
                first_seen_at=     tx_time,
                seen_at=           seen_at,
                prev_version_hash= None,
                simhash_64=        simhash_64,
            )
        else:
            # Already on disk.  Re-read sidecar; append seen_at if a
            # crawl_run_id was supplied; never modify the bytes.
            is_new = False
            try:
                meta = BlobMeta.from_json(json.loads(target_meta.read_text()))
            except (FileNotFoundError, json.JSONDecodeError) as exc:
                # Sidecar lost / corrupt: rebuild from on-disk bytes.
                logger.warning(
                    "blob %s missing/corrupt sidecar; rebuilding: %s", sha256, exc,
                )
                meta = BlobMeta(
                    sha256=           sha256,
                    size_bytes=       target_warc.stat().st_size,
                    url=              url,
                    response_status=  response_status,
                    response_headers= headers,
                    valid_time=       valid_t,
                    first_seen_at=    tx_time,
                    seen_at=          [],
                    simhash_64=       simhash_64,
                )
            if crawl_run_id:
                # Idempotent append — don't add the same (run_id, tx_time) twice
                already = any(s.crawl_run_id == crawl_run_id for s in meta.seen_at)
                if not already:
                    meta.seen_at.append(SeenAtRecord(crawl_run_id=crawl_run_id, tx_time=tx_time))

        # Always rewrite sidecar (atomic) — captures any seen_at update.
        tmp_meta = target_meta.with_suffix(".meta.json.tmp")
        tmp_meta.write_text(json.dumps(meta.to_json(), ensure_ascii=False, indent=2))
        tmp_meta.replace(target_meta)

    return meta, is_new


def read_blob(root: Path, sha256: str) -> Tuple[BlobMeta, bytes]:
    """Read meta + decoded HTTP response body for a blob.

    Identity = sha256 of the BODY.  We extract the body from the WARC
    envelope on disk and verify its hash matches the requested sha256
    (silent disk corruption guard).  Raises FileNotFoundError if blob
    missing, RuntimeError if hash mismatch.
    """
    warc_p = blob_path(root, sha256, suffix=".warc.gz")
    meta_p = blob_path(root, sha256, suffix=".meta.json")
    if not warc_p.is_file():
        raise FileNotFoundError(f"blob {sha256} not found at {warc_p}")
    if not meta_p.is_file():
        raise FileNotFoundError(f"blob {sha256} sidecar not found at {meta_p}")

    warc_bytes = warc_p.read_bytes()
    body = _extract_response_body(warc_bytes)
    actual = sha256_of_bytes(body)
    if actual != sha256:
        raise RuntimeError(
            f"blob body hash mismatch: expected {sha256}, got {actual} "
            f"(silent disk corruption — WARC envelope OK but body bytes "
            f"don't hash to the filename)"
        )

    meta = BlobMeta.from_json(json.loads(meta_p.read_text()))
    return meta, body


def read_blob_bytes(root: Path, sha256: str) -> bytes:
    """Return the raw .warc.gz envelope bytes (for download).

    NOTE: the WARC envelope contains per-record UUIDs / timestamps,
    so two writes of the same body produce different envelope bytes.
    We do NOT hash-verify the envelope — only the extracted body
    (read_blob() does that).  This function is for raw streaming
    download; callers wanting to verify content should use read_blob().
    """
    warc_p = blob_path(root, sha256, suffix=".warc.gz")
    if not warc_p.is_file():
        raise FileNotFoundError(f"blob {sha256} not found")
    return warc_p.read_bytes()


def _extract_response_body(warc_bytes: bytes) -> bytes:
    """Pull the HTTP response payload out of a WARC envelope."""
    from warcio.archiveiterator import ArchiveIterator
    for rec in ArchiveIterator(BytesIO(warc_bytes)):
        if rec.rec_type == "response":
            return rec.content_stream().read()
    raise RuntimeError("WARC record contained no response payload")


def list_blob_paths(root: Path) -> List[Path]:
    """Walk blobs/ and return every .warc.gz path. Cheap; used by
    indexer warm-up + admin scripts."""
    base = root / "blobs"
    if not base.is_dir():
        return []
    return sorted(base.glob("*/*.warc.gz"))


def stats(root: Path) -> Dict[str, Any]:
    """Quick file-system count + size totals for the stats endpoint."""
    paths = list_blob_paths(root)
    total = sum(p.stat().st_size for p in paths)
    return {
        "blob_count":     len(paths),
        "total_bytes":    total,
    }
