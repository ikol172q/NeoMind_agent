"""Raw store — Phase B1 of the provenance architecture.

Immutable, content-addressed storage for every byte the agent ever
fetches from an external source.  See
docs/design/2026-04-26_provenance-architecture.md for the full spec.

Public API (re-exported here):

  - RawStore — high-level entry point
  - blob_path / write_blob / read_blob — content-addressed file ops
  - BlobMeta — Pydantic model for the meta.json sidecar
  - CrawlRunManifest, CrawlRunReport — per-run metadata
  - RawIndex — SQLite FTS5-backed full-text + bitemporal index

Invariants enforced (per design doc):

  1. Immutable provenance — write_blob never overwrites; identical
     bytes resolve to the same path; differing bytes land at a new
     path keyed by their own sha256.
  2. Bitemporal — every blob carries valid_time + first_seen_at.
  3. Strict content addressing — sha256 of bytes IS the filename;
     readers verify on load (silent disk corruption check).
"""
from __future__ import annotations

from agent.finance.raw_store.blobs import (
    blob_path,
    write_blob,
    read_blob,
    read_blob_bytes,
    sha256_of_bytes,
)
from agent.finance.raw_store.meta import (
    BlobMeta,
    SeenAtRecord,
    CrawlRunManifest,
    CrawlRunReport,
)
from agent.finance.raw_store.index import RawIndex
from agent.finance.raw_store.store import RawStore

__all__ = [
    "RawStore",
    "blob_path", "write_blob", "read_blob", "read_blob_bytes",
    "sha256_of_bytes",
    "BlobMeta", "SeenAtRecord",
    "CrawlRunManifest", "CrawlRunReport",
    "RawIndex",
]
