"""FastAPI endpoints for the learning library.

Routes:
  GET  /api/learning/today        — fresh cases + 1 classic rotation
  GET  /api/learning/library      — filterable archive
  GET  /api/learning/themes       — distinct theme tags + counts
  GET  /api/learning/cases/{slug} — single case with full body
  POST /api/learning/cases/{slug}/seen — mark shown (rotation hint)
  POST /api/learning/refresh      — manually trigger fetcher
  POST /api/learning/seed         — populate hand-curated seeds
                                     (idempotent — upserts by slug)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query

from agent.finance import agent_audit
from agent.finance.learning import persistence as dao
from agent.finance.learning import fetcher
from agent.finance.learning.seed_cases import all_seeds

logger = logging.getLogger(__name__)


def build_learning_router() -> APIRouter:
    router = APIRouter(prefix="/api/learning", tags=["learning"])

    @router.get("/today")
    def get_today() -> Dict[str, Any]:
        return dao.list_today(fresh_limit=8)

    @router.get("/library")
    def get_library(
        theme: Optional[str] = Query(None),
        era: Optional[str] = Query(None),
        language: Optional[str] = Query(None, description="zh / en / mix"),
        q: Optional[str] = Query(None, description="substring match"),
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ) -> Dict[str, Any]:
        return dao.list_library(
            theme=theme, era=era, language=language, q=q,
            limit=limit, offset=offset,
        )

    @router.get("/themes")
    def get_themes() -> Dict[str, Any]:
        return {"themes": dao.list_themes()}

    @router.get("/books")
    def get_books() -> Dict[str, Any]:
        """Books grouped by availability (public_domain / free_web / paid)
        for the dedicated 📚 Books section in the UI."""
        return dao.list_books()

    @router.get("/cases/{slug}")
    def get_case(slug: str) -> Dict[str, Any]:
        c = dao.get_case(slug)
        if c is None:
            raise HTTPException(404, f"learning case {slug!r} not found")
        return c

    @router.post("/cases/{slug}/seen")
    def mark_seen(slug: str) -> Dict[str, Any]:
        if dao.get_case(slug) is None:
            raise HTTPException(404, f"learning case {slug!r} not found")
        dao.mark_shown(slug)
        return {"ok": True, "slug": slug}

    @router.post("/refresh")
    def refresh(
        max_accept: int = Query(8, ge=1, le=20),
    ) -> Dict[str, Any]:
        """Manually trigger the daily fetcher. Audited so the run shows
        up in NeoMind Live as agent_id='learning-refresh'."""
        return agent_audit.audited_call(
            agent_id="learning-refresh",
            endpoint="/api/learning/refresh",
            fn=fetcher.fetch_fresh_cases,
            kwargs={"max_accept": max_accept},
            extra_request={"trigger": "manual_api"},
            summarize_result=lambda r: (
                f"learning refresh: {len(r.get('new_slugs', []))} new cases" if isinstance(r, dict) else str(r)),
        )

    @router.post("/seed")
    def seed() -> Dict[str, Any]:
        """Idempotent — upsert all hand-curated seeds. Run once after
        first install or after bumping the seed file."""
        seeds = all_seeds()
        for s in seeds:
            dao.upsert_case(
                slug=s["slug"],
                title=s["title"],
                title_zh=s["title_zh"],
                summary_zh=s["summary_zh"],
                source_url=s.get("source_url"),
                source_name=s.get("source_name"),
                body=s.get("summary_zh"),  # seeds use summary as body too
                language=s.get("language", "zh"),
                themes=s.get("themes", []),
                tickers=s.get("tickers", []),
                era=s.get("era"),
                difficulty=s.get("difficulty"),
                is_classic=True,
                is_fresh=False,
            )
        return {"ok": True, "n_seeded": len(seeds)}

    return router
