"""SEC-anchored research orchestrator.

Wires:
    data_sources/sec_edgar.py    (deterministic fetch + section slicing)
    extractors/competitors.py    (LLM extraction with isolated source)
    extractors/validation.py     (verbatim-quote trust gate)
        ↓
    DB persistence with provenance (stock_anchored_facts table)
        ↓
    HTTP endpoint exposed at /api/stock/{ticker}/anchored

This is parallel to the existing /api/stock/{ticker}/profile (which
remains unchanged for fast/cheap LLM-only output). The UI can show
both side by side so the user sees the trade-off concretely:

    Old profile   = $0.005, fast, 50% fabrication risk
    Anchored      = $0.10, slow, 100% verifiable from real 10-K text

Currently extracts competitors only — Phase B will add risks,
business_summary, segments, customers, suppliers via the same shape.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException

from agent.data_sources.market import get_live_quote
from agent.data_sources.sec_edgar import get_10k_sections
from agent.finance import agent_audit
from agent.finance.extractors.business_summary import extract_business_summary
from agent.finance.extractors.competitors import extract_competitors
from agent.finance.extractors.customers import extract_customers
from agent.finance.extractors.risks import extract_risks
from agent.finance.extractors.segments import extract_segments
from agent.finance.extractors.style_verdict import synthesize_style_verdict
from agent.finance.extractors.suppliers import extract_suppliers
from agent.finance.persistence import connect, ensure_schema

logger = logging.getLogger(__name__)


def _normalize_ticker(t: str) -> str:
    t = (t or "").strip().upper()
    import re
    if not re.match(r"^[A-Z][A-Z0-9.\-]{0,9}$", t):
        raise HTTPException(400, f"invalid ticker: {t!r}")
    return t


def _persist_facts(*, ticker: str, fact_type: str,
                   verified_items: list[dict], source_url: str,
                   source_section: str, source_filing_date: str,
                   source_accession: str, extractor_model: str,
                   req_id: str) -> int:
    """Replace prior facts of this (ticker, fact_type) with the new set.

    Replace-rather-than-append because anchored_research is a SNAPSHOT
    of the latest 10-K. Stale entries from a year-old filing should
    not linger alongside the current ones. Versioning across filings
    is a separate concern (use stock_profile_versions if needed).
    """
    ensure_schema()
    now = datetime.now(timezone.utc).isoformat()
    with connect() as conn:
        conn.execute(
            "DELETE FROM stock_anchored_facts WHERE ticker=? AND fact_type=?",
            (ticker, fact_type),
        )
        for item in verified_items:
            quote = item.get("evidence_quote") or ""
            payload = {k: v for k, v in item.items() if k != "evidence_quote"}
            conn.execute(
                """INSERT INTO stock_anchored_facts
                   (ticker, fact_type, payload_json, evidence_quote,
                    source_url, source_section, source_filing_date,
                    source_accession, extracted_at, extractor_model, req_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (ticker, fact_type, json.dumps(payload, ensure_ascii=False),
                 quote, source_url, source_section, source_filing_date,
                 source_accession, now, extractor_model, req_id),
            )
    return len(verified_items)


def get_anchored_facts(ticker: str) -> dict[str, Any]:
    """Read all cached anchored facts for a ticker, grouped by fact_type."""
    ensure_schema()
    with connect() as conn:
        cur = conn.execute(
            """SELECT fact_type, payload_json, evidence_quote, source_url,
                      source_section, source_filing_date, extracted_at, req_id
               FROM stock_anchored_facts
               WHERE ticker=?
               ORDER BY fact_type, id""",
            (ticker,),
        )
        rows = cur.fetchall()
    by_type: Dict[str, list] = {}
    latest_meta: Dict[str, Any] = {}
    for r in rows:
        ft = r["fact_type"]
        try:
            payload = json.loads(r["payload_json"])
        except json.JSONDecodeError:
            payload = {}
        payload["evidence_quote"] = r["evidence_quote"]
        payload["source_url"] = r["source_url"]
        payload["source_section"] = r["source_section"]
        by_type.setdefault(ft, []).append(payload)
        # Track latest meta across all rows
        if not latest_meta or r["extracted_at"] > latest_meta.get("extracted_at", ""):
            latest_meta = {
                "source_url": r["source_url"],
                "source_filing_date": r["source_filing_date"],
                "extracted_at": r["extracted_at"],
                "req_id": r["req_id"],
            }
    return {"ticker": ticker, "facts": by_type, "meta": latest_meta or None}


# Per-fact-type extractor configuration. Adding a new fact type only
# requires writing the extractor function and adding an entry here —
# the pipeline (audit → fetch-section → extract → validate → persist)
# is identical across types.
def _extract_competitors_from(s) -> tuple[list[dict], Any]:
    return extract_competitors(s.item1_competition, s.item1a_risks)


def _extract_risks_from(s) -> tuple[list[dict], Any]:
    return extract_risks(s.item1a_risks)


def _extract_business_summary_from(s) -> tuple[list[dict], Any]:
    return extract_business_summary(s.item1_full)


def _extract_customers_from(s) -> tuple[list[dict], Any]:
    return extract_customers(s.item1_customers)


def _extract_suppliers_from(s) -> tuple[list[dict], Any]:
    return extract_suppliers(s.item1_suppliers)


def _extract_segments_from(s) -> tuple[list[dict], Any]:
    return extract_segments(s.item7_mda)


_PIPELINES: dict[str, dict] = {
    "competitor": {
        "extract": _extract_competitors_from,
        "section": "item1.competition+item1a.risks",
    },
    "risk": {
        "extract": _extract_risks_from,
        "section": "item1a.risks",
    },
    "business_summary": {
        "extract": _extract_business_summary_from,
        "section": "item1.business",
    },
    "customer": {
        "extract": _extract_customers_from,
        "section": "item1.customers",
    },
    "supplier": {
        "extract": _extract_suppliers_from,
        "section": "item1.suppliers",
    },
    "segment": {
        "extract": _extract_segments_from,
        "section": "item7.mda",
    },
}


def _run_pipeline(ticker: str, fact_type: str) -> Dict[str, Any]:
    """Generic pipeline: fetch 10-K → slice → extract → validate → persist.

    Same shape for every fact_type. The extractor function (registered
    in _PIPELINES) decides which sliced sections it consumes.
    """
    if fact_type not in _PIPELINES:
        raise HTTPException(400, f"unknown fact_type: {fact_type}")
    cfg = _PIPELINES[fact_type]

    sections = get_10k_sections(ticker)
    if sections is None:
        raise HTTPException(
            404,
            f"no 10-K filing found for {ticker} on SEC EDGAR",
        )

    agent_id = f"anchored-{fact_type}"
    endpoint = f"/api/stock/{ticker}/anchored/{fact_type}/regenerate"
    req_id = agent_audit.new_req_id()
    agent_audit.audit_request(
        req_id=req_id,
        endpoint=endpoint,
        agent_id=agent_id,
        messages=[],  # extractor records its own prompt internally
        model="deepseek-v4-flash",
        max_tokens=16000,
        temperature=0.0,
        extra={
            "ticker": ticker,
            "fact_type": fact_type,
            "source_url": sections.source_url,
            "item1_full_chars": len(sections.item1_full or ""),
            "item1_competition_chars": len(sections.item1_competition or ""),
            "item1a_risks_chars": len(sections.item1a_risks or ""),
        },
    )

    t0 = time.monotonic()
    try:
        verified, outcome = cfg["extract"](sections)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("anchored %s failed for %s", fact_type, ticker)
        agent_audit.audit_error(
            req_id=req_id, endpoint=endpoint, agent_id=agent_id,
            error_type=type(exc).__name__, error_msg=str(exc),
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
        raise HTTPException(502, f"anchored {fact_type} extraction failed: {exc}")

    duration_ms = int((time.monotonic() - t0) * 1000)
    agent_audit.audit_response(
        req_id=req_id, endpoint=endpoint, agent_id=agent_id,
        content=json.dumps(verified, ensure_ascii=False),
        duration_ms=duration_ms,
        extra={
            "ticker": ticker, "fact_type": fact_type,
            "n_emitted": outcome.n_total,
            "n_verified": len(outcome.verified),
            "n_dropped": len(outcome.dropped),
            "drop_reasons": [r for _, r in outcome.dropped],
        },
    )

    n_persisted = _persist_facts(
        ticker=ticker, fact_type=fact_type, verified_items=verified,
        source_url=sections.source_url, source_section=cfg["section"],
        source_filing_date=sections.filing_date,
        source_accession=sections.accession,
        extractor_model="deepseek-v4-flash", req_id=req_id,
    )

    return {
        "ticker": ticker, "fact_type": fact_type,
        "n_emitted": outcome.n_total,
        "n_verified": len(outcome.verified),
        "n_dropped": len(outcome.dropped),
        "drop_reasons": [r for _, r in outcome.dropped],
        "n_persisted": n_persisted,
        "source_url": sections.source_url,
        "source_filing_date": sections.filing_date,
        "duration_ms": duration_ms,
        "req_id": req_id,
    }


def _run_style_verdict(ticker: str) -> Dict[str, Any]:
    """Synthesize a style verdict from already-cached anchored facts +
    live quote. Persists as fact_type='style_verdict'.

    Pre-condition: anchored facts already exist for the ticker (run
    /anchored/regenerate first or POST /anchored/business_summary +
    /anchored/risk individually). Otherwise the verdict will be
    'data 不足'."""
    facts = get_anchored_facts(ticker)
    by_type = facts.get("facts") or {}
    live = get_live_quote(ticker)
    live_dict = live.to_dict() if live else None

    req_id = agent_audit.new_req_id()
    endpoint = f"/api/stock/{ticker}/anchored/style_verdict/regenerate"
    agent_audit.audit_request(
        req_id=req_id, endpoint=endpoint, agent_id="anchored-style_verdict",
        messages=[], model="deepseek-v4-flash",
        max_tokens=4000, temperature=0.0,
        extra={"ticker": ticker,
               "has_live_quote": live_dict is not None,
               "n_business_summary": len(by_type.get("business_summary") or []),
               "n_segments": len(by_type.get("segment") or []),
               "n_risks": len(by_type.get("risk") or []),
               "n_competitors": len(by_type.get("competitor") or [])},
    )

    t0 = time.monotonic()
    try:
        verdict, outcome = synthesize_style_verdict(
            ticker=ticker,
            live_quote=live_dict,
            business_summary=by_type.get("business_summary"),
            segments=by_type.get("segment"),
            risks=by_type.get("risk"),
            competitors_count=len(by_type.get("competitor") or []),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("style_verdict failed for %s", ticker)
        agent_audit.audit_error(
            req_id=req_id, endpoint=endpoint, agent_id="anchored-style_verdict",
            error_type=type(exc).__name__, error_msg=str(exc),
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
        raise HTTPException(502, f"style_verdict failed: {exc}")

    duration_ms = int((time.monotonic() - t0) * 1000)
    agent_audit.audit_response(
        req_id=req_id, endpoint=endpoint, agent_id="anchored-style_verdict",
        content=json.dumps(verdict, ensure_ascii=False) if verdict else "",
        duration_ms=duration_ms,
        extra={"ticker": ticker,
               "n_emitted": outcome.n_total,
               "n_verified": len(outcome.verified),
               "n_dropped": len(outcome.dropped),
               "drop_reasons": [r for _, r in outcome.dropped]},
    )

    n_persisted = 0
    if verdict is not None:
        # Synthesis is a single fact, persist as fact_type='style_verdict'.
        # The "source" here is the bag of anchored facts, not a single
        # filing section. Source URL points to the most recent filing
        # the bag was based on (same as other facts).
        meta = facts.get("meta") or {}
        n_persisted = _persist_facts(
            ticker=ticker, fact_type="style_verdict",
            verified_items=[verdict],
            source_url=meta.get("source_url", "synthesized"),
            source_section="synthesized.from_anchored_facts",
            source_filing_date=meta.get("source_filing_date") or "",
            source_accession="",
            extractor_model="deepseek-v4-flash", req_id=req_id,
        )

    return {
        "ticker": ticker, "fact_type": "style_verdict",
        "verdict": verdict,
        "n_verified": len(outcome.verified),
        "n_dropped": len(outcome.dropped),
        "drop_reasons": [r for _, r in outcome.dropped],
        "n_persisted": n_persisted,
        "duration_ms": duration_ms,
        "req_id": req_id,
    }


def build_anchored_research_router() -> APIRouter:
    router = APIRouter(prefix="/api/stock", tags=["anchored-research"])

    @router.get("/{ticker}/anchored")
    def get_anchored(ticker: str) -> dict[str, Any]:
        t = _normalize_ticker(ticker)
        return get_anchored_facts(t)

    @router.post("/{ticker}/anchored/style_verdict/regenerate")
    def regen_style_verdict(ticker: str) -> dict[str, Any]:
        t = _normalize_ticker(ticker)
        return _run_style_verdict(t)

    @router.post("/{ticker}/anchored/{fact_type}/regenerate")
    def regen_one(ticker: str, fact_type: str) -> dict[str, Any]:
        t = _normalize_ticker(ticker)
        return _run_pipeline(t, fact_type)

    @router.post("/{ticker}/anchored/regenerate")
    def regen_all(ticker: str) -> dict[str, Any]:
        """Run every registered pipeline back-to-back. The slicer's
        cache means the 10-K HTML is fetched once and reused across
        extractors, so total wall-time is ~3x single-extractor."""
        t = _normalize_ticker(ticker)
        results = {}
        for ft in _PIPELINES:
            try:
                results[ft] = _run_pipeline(t, ft)
            except HTTPException as e:
                results[ft] = {"error": str(e.detail), "status": e.status_code}
        return {"ticker": t, "results": results}

    return router
