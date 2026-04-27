"""News pull — every Miniflux entry becomes a content-addressed blob.

This is Phase B3-real. Replaces the synthetic dev endpoint
``/api/raw/_dev/crawl_news_synthetic`` for production traffic: each
entry pulled from the local Miniflux instance is written through the
exact same RawStore code path the synthetic crawl exercises.

Cron default: every 30 minutes during US market hours, then hourly
overnight. Tuned conservatively — Miniflux already does its own
RSS polling, this job just snapshots what Miniflux already has.

What gets persisted
-------------------
Per entry:
  * **body** = canonical JSON (sorted keys, UTF-8) — deterministic so
    identical Miniflux entries produce identical blob hashes (no
    spurious supersedes). When Miniflux updates an entry's title /
    snippet (silent retroactive edit), bytes change → B1 supersede
    chain fires.
  * **url** = entry.url (the original article URL, NOT the Miniflux
    proxy URL — that's the natural identity for cross-source dedup
    later in B3 SimHash).
  * **valid_time** = entry.published_at (when the article was
    published, not when we observed it). Drives B2 AS-OF queries.
  * **response_status** = 200 (Miniflux returned it OK; the upstream
    fetch errors are Miniflux's problem, not ours).
  * **response_headers** = ``{"Content-Type": "application/json",
    "X-Source": "miniflux", "X-Feed-Title": entry.feed_title}``.

Failure modes
-------------
Miniflux missing / unreachable / 401 → job returns
``{"status": "skipped", "reason": ...}``. We don't fail the scheduler
or pollute analysis_runs with a synthetic "failed" status; this is
expected on dev machines that haven't booted Miniflux yet.

Other exceptions → propagate (job marked failed, retry next cron).
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import Any, Dict

from fastapi import HTTPException

from agent.finance.persistence import connect, dao, ensure_schema

logger = logging.getLogger(__name__)


JOB_NAME = "news_pull"
# Every 20 minutes — Miniflux's own RSS poll is typically 60min, so
# 20min is more than fast enough to catch updates without spamming.
DEFAULT_CRON = "*/20 * * * *"
DESCRIPTION = (
    "Pull recent entries from local Miniflux and persist each one as "
    "a content-addressed blob in the raw store (one CrawlRunHandle "
    "per pull). Miniflux missing/unreachable → graceful skip."
)


# Hard-coded for V1 — fin dashboard has exactly one project.
_PROJECT_ID = "fin-core"
# Default page size; Miniflux caps at 100 per request anyway.
_DEFAULT_LIMIT = 100


async def run(limit: int = _DEFAULT_LIMIT) -> Dict[str, Any]:
    """Execute one pull. Returns a summary dict.

    Synchronous Miniflux call inside an async function — fine for
    Phase 1 single-instance Miniflux on localhost. If we ever scale
    out, swap for ``aiohttp``.
    """
    ensure_schema()

    # Lazy imports keep scheduler module load cheap and avoid coupling
    # the scheduler to RawStore / news_hub at process startup.
    from agent.finance.news_hub import fetch_entries
    from agent.finance.raw_store import RawStore

    # Phase 1: register a logical analysis_run so the scheduler UI can
    # show "last_run_at / status" the same way other jobs do.
    with connect() as conn:
        run_id = dao.start_analysis_run(
            conn,
            job_name=JOB_NAME,
            run_type="scheduled",
            metadata={"limit": int(limit)},
        )

    # Try Miniflux. Configuration / network errors are NOT fatal — we
    # surface them as a "skipped" summary so the scheduler row shows
    # last_run_status='completed' with a skip reason instead of a red
    # "failed" badge that would scare the user into thinking RawStore
    # itself is broken.
    try:
        entries = fetch_entries(limit=int(limit))
    except HTTPException as exc:
        # 503/502 from news_hub means Miniflux side is the problem.
        with connect() as conn:
            dao.complete_analysis_run(
                conn, run_id,
                status="completed",
                error_message=None,
                rows_written=0,
            )
        summary = {
            "run_id":          run_id,
            "status":          "skipped",
            "reason":          str(exc.detail),
            "wrote_n":         0,
            "crawl_run_id":    None,
            "explanation":     (
                "Miniflux not reachable / not configured. This is "
                "expected if you haven't booted the miniflux container "
                "yet — set MINIFLUX_USERNAME + MINIFLUX_PASSWORD and "
                "`docker compose up -d miniflux`, then re-run."
            ),
        }
        logger.info("news_pull: skipped — %s", exc.detail)
        return summary

    # Persist each entry as a blob inside one CrawlRunHandle.
    store = RawStore.for_project(_PROJECT_ID)
    blobs_written: list[dict[str, Any]] = []
    with store.open_crawl_run(
        source="news_hub",
        query={"limit": int(limit)},
    ) as crawl:
        for e in entries:
            # Canonical JSON body — sorted keys, UTF-8, ensure_ascii=False
            # so non-ASCII titles (Chinese feeds, etc.) hash stably.
            body = json.dumps(
                asdict(e), sort_keys=True, ensure_ascii=False,
            ).encode("utf-8")

            meta = crawl.add_blob(
                body,
                url=e.url or f"miniflux://entry/{e.id}",
                response_status=200,
                response_headers={
                    "Content-Type":  "application/json",
                    "X-Source":      "miniflux",
                    "X-Feed-Title":  e.feed_title or "",
                    "X-Miniflux-Id": str(e.id),
                },
                valid_time=e.published_at or None,
            )
            blobs_written.append({
                "url":    e.url,
                "sha256": meta.sha256,
                "title":  e.title[:80],
            })

        crawl_run_id = crawl.crawl_run_id
        date_str     = crawl.date_str

    # Mirror into analysis_runs for the scheduler UI.
    with connect() as conn:
        dao.complete_analysis_run(
            conn, run_id,
            status="completed",
            error_message=None,
            rows_written=len(blobs_written),
        )

    summary = {
        "run_id":         run_id,
        "status":         "completed",
        "crawl_run_id":   crawl_run_id,
        "date":           date_str,
        "wrote_n":        len(blobs_written),
        "blobs_sample":   blobs_written[:3],
        "explanation":    (
            f"Wrote {len(blobs_written)} blobs through the same "
            f"RawStore code path the synthetic crawl uses. Each blob "
            f"is keyed by sha256(canonical_json_body). Re-running "
            f"this job is idempotent: identical Miniflux entries "
            f"produce identical hashes (no new blob, just an extra "
            f"seen_at row). Updated entries fire B1's supersede "
            f"detection."
        ),
    }
    logger.info("news_pull complete: %s", {k: v for k, v in summary.items() if k != "blobs_sample"})
    return summary
