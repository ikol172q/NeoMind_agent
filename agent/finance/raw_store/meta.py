"""BlobMeta + crawl-run dataclasses for the raw store.

We deliberately use plain ``@dataclass`` rather than Pydantic to
keep the package import-light; FastAPI handlers will validate at
the HTTP boundary.  Every model carries ``schema_version`` so old
files can be read forever as the schema evolves (Phase B1 = v1).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


SCHEMA_VERSION_BLOB_META       = 1
SCHEMA_VERSION_CRAWL_MANIFEST  = 1
SCHEMA_VERSION_CRAWL_REPORT    = 1


@dataclass
class SeenAtRecord:
    """One entry in BlobMeta.seen_at: a crawl run that hit this blob."""
    crawl_run_id: str
    tx_time:      str            # ISO 8601 UTC, e.g. "2026-04-26T03:14:15Z"


@dataclass
class BlobMeta:
    """Meta.json sidecar for a content-addressed blob.

    Stored next to ``<sha256>.warc.gz`` as ``<sha256>.meta.json``.
    """
    sha256:           str         # 64-char lowercase hex
    size_bytes:       int         # bytes of the .warc.gz file
    url:              str         # source URL (canonical form)
    response_status:  int         # HTTP status as fetched
    response_headers: Dict[str, str]
    valid_time:       str         # when the underlying event happened
                                  #   (e.g., article.published_at)
    first_seen_at:    str         # tx_time of the FIRST crawl that fetched
                                  #   this exact byte sequence
    seen_at:          List[SeenAtRecord]
                                  # every (crawl_run_id, tx_time) that has
                                  #   re-fetched the same bytes since
    prev_version_hash: Optional[str] = None
                                  # if this URL had a different blob earlier
                                  #   (silent retroactive edit), the older
                                  #   blob's sha256
    simhash_64:       Optional[int] = None
                                  # 64-bit SimHash over canonicalised text
                                  #   for multi-source dedupe (B3 wires it
                                  #   in; B1 just reserves the field)
    schema_version:   int = SCHEMA_VERSION_BLOB_META

    def to_json(self) -> Dict[str, Any]:
        d = asdict(self)
        d["seen_at"] = [asdict(s) for s in self.seen_at]
        return d

    @classmethod
    def from_json(cls, raw: Dict[str, Any]) -> "BlobMeta":
        seen = [SeenAtRecord(**s) for s in raw.get("seen_at", [])]
        return cls(
            sha256=            raw["sha256"],
            size_bytes=        raw["size_bytes"],
            url=               raw["url"],
            response_status=   raw["response_status"],
            response_headers=  dict(raw.get("response_headers", {})),
            valid_time=        raw["valid_time"],
            first_seen_at=     raw["first_seen_at"],
            seen_at=           seen,
            prev_version_hash= raw.get("prev_version_hash"),
            simhash_64=        raw.get("simhash_64"),
            schema_version=    raw.get("schema_version", SCHEMA_VERSION_BLOB_META),
        )


@dataclass
class CrawlRunManifest:
    """Per-crawl manifest stored at
       crawl_runs/<YYYY-MM-DD>/<crawl_run_id>.json.

    Records: which blobs THIS crawl run selected (referenced), which
    were newly fetched, which ones were a different version of an
    already-known URL (silent edits).
    """
    crawl_run_id:        str
    source:              str         # e.g. "news.yfinance" / "yfinance.bars"
    query:               Dict[str, Any]
                                     # whatever params drove the crawl
                                     #   (e.g. {symbol: "AAPL", limit: 30})
    started_at:          str
    completed_at:        Optional[str] = None
    status:              str = "running"     # running | success | partial | failed
    selected_blobs:      List[str] = field(default_factory=list)
                                     # every sha256 this run touched
    newly_fetched_blobs: List[str] = field(default_factory=list)
                                     # subset that wasn't in raw store before
    superseded_versions: List[Dict[str, str]] = field(default_factory=list)
                                     # [{url, old_hash, new_hash}] — silent edits
    error:               Optional[str] = None
    schema_version:      int = SCHEMA_VERSION_CRAWL_MANIFEST

    def to_json(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, raw: Dict[str, Any]) -> "CrawlRunManifest":
        return cls(
            crawl_run_id=        raw["crawl_run_id"],
            source=              raw["source"],
            query=               dict(raw.get("query", {})),
            started_at=          raw["started_at"],
            completed_at=        raw.get("completed_at"),
            status=              raw.get("status", "running"),
            selected_blobs=      list(raw.get("selected_blobs", [])),
            newly_fetched_blobs= list(raw.get("newly_fetched_blobs", [])),
            superseded_versions= list(raw.get("superseded_versions", [])),
            error=               raw.get("error"),
            schema_version=      raw.get("schema_version", SCHEMA_VERSION_CRAWL_MANIFEST),
        )


@dataclass
class CrawlRunReport:
    """Per-crawl readiness/health report at
       crawl_runs/<YYYY-MM-DD>/<crawl_run_id>.report.json.

    Operator-facing summary so the human / a downstream LLM can
    spot-check what the crawl actually got.
    """
    crawl_run_id:    str
    totals:          Dict[str, int]
                                     # {fetched, new, deduped_by_simhash,
                                     #  superseded, http_4xx, http_5xx}
    sample:          List[Dict[str, Any]]
                                     # 5 random items: {url, valid_time,
                                     #   first_120_chars, sha256}
    anomaly_alerts:  List[str] = field(default_factory=list)
    schema_version:  int = SCHEMA_VERSION_CRAWL_REPORT

    def to_json(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, raw: Dict[str, Any]) -> "CrawlRunReport":
        return cls(
            crawl_run_id=    raw["crawl_run_id"],
            totals=          dict(raw.get("totals", {})),
            sample=          list(raw.get("sample", [])),
            anomaly_alerts=  list(raw.get("anomaly_alerts", [])),
            schema_version=  raw.get("schema_version", SCHEMA_VERSION_CRAWL_REPORT),
        )
