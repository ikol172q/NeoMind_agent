"""Stock Research Drawer backend — Phase R1.

Provides:
    GET    /api/stock/{ticker}/profile        cached LLM profile
    POST   /api/stock/{ticker}/profile        force LLM regen
    GET    /api/stock/{ticker}/exposure       Smart Money join over signal_events
    GET    /api/stock/{ticker}/notes          user notes timeline
    POST   /api/stock/{ticker}/notes          append note
    PATCH  /api/stock/{ticker}/status         set decision status + reason

Design notes:
    - LLM call is opt-in (POST). GET returns cached row or 404 so the
      drawer can show "no profile yet, click ✨ regenerate" without
      burning $0.01 every page load.
    - Source citations enforced — the LLM is asked to return them in
      the JSON output (anti-hallucination contract).
    - Anti-stale: each profile records `generated_at` so the UI can
      surface "cached 3 days ago, click to refresh".
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from agent.finance import agent_audit
from agent.finance.persistence import connect, ensure_schema

logger = logging.getLogger(__name__)


# ─── ticker validation ────────────────────────────────────────────

_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def _normalize(t: str) -> str:
    t = (t or "").strip().upper()
    if not _TICKER_RE.match(t):
        raise HTTPException(400, f"invalid ticker: {t!r}")
    return t


# ─── DAO ──────────────────────────────────────────────────────────

def _row_to_profile(row: Any) -> Dict[str, Any]:
    """Convert a sqlite Row to a JSON-shaped dict, parsing JSON cols."""
    def j(s: Optional[str], default: Any = None) -> Any:
        if not s:
            return default
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return default
    return {
        "ticker":          row["ticker"],
        "name":            row["name"],
        "sector":          row["sector"],
        "summary":         row["summary"],
        "segments":        j(row["segments_json"], []),
        "upstream":        j(row["upstream_json"], []),
        "downstream":      j(row["downstream_json"], []),
        "competitors":     j(row["competitors_json"], []),
        "catalysts":       j(row["catalysts_json"], []),
        "risks":           j(row["risks_json"], []),
        "style_verdict":   row["style_verdict"],
        "quick_stats":     j(row["quick_stats_json"], {}),
        "user_status":     row["user_status"],
        "user_status_reason": row["user_status_reason"],
        "user_status_ts":  row["user_status_ts"],
        "generated_at":    row["generated_at"],
        "generated_model": row["generated_model"],
        "source_citations": j(row["source_citations_json"], []),
    }


def get_profile(ticker: str) -> Optional[Dict[str, Any]]:
    ensure_schema()
    with connect() as conn:
        cur = conn.execute("SELECT * FROM stock_profiles WHERE ticker = ?", (ticker,))
        row = cur.fetchone()
        return _row_to_profile(row) if row else None


def upsert_profile(ticker: str, fields: Dict[str, Any]) -> None:
    """Write or replace a profile row. JSON-typed fields are dumped here."""
    ensure_schema()
    payload = {
        "ticker":               ticker,
        "name":                 fields.get("name"),
        "sector":               fields.get("sector"),
        "summary":              fields.get("summary"),
        "segments_json":        json.dumps(fields.get("segments") or [], ensure_ascii=False),
        "upstream_json":        json.dumps(fields.get("upstream") or [], ensure_ascii=False),
        "downstream_json":      json.dumps(fields.get("downstream") or [], ensure_ascii=False),
        "competitors_json":     json.dumps(fields.get("competitors") or [], ensure_ascii=False),
        "catalysts_json":       json.dumps(fields.get("catalysts") or [], ensure_ascii=False),
        "risks_json":           json.dumps(fields.get("risks") or [], ensure_ascii=False),
        "style_verdict":        fields.get("style_verdict"),
        "quick_stats_json":     json.dumps(fields.get("quick_stats") or {}, ensure_ascii=False),
        "generated_at":         fields.get("generated_at"),
        "generated_model":      fields.get("generated_model"),
        "source_citations_json": json.dumps(fields.get("source_citations") or [], ensure_ascii=False),
    }
    cols = list(payload.keys())
    placeholders = ",".join("?" for _ in cols)
    setters = ",".join(f"{c}=excluded.{c}" for c in cols if c != "ticker")
    sql = (
        f"INSERT INTO stock_profiles ({','.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(ticker) DO UPDATE SET {setters}"
    )
    with connect() as conn:
        conn.execute(sql, [payload[c] for c in cols])


def update_status(ticker: str, status: str, reason: str) -> None:
    ensure_schema()
    if status not in ("researching", "watching", "pass", "own"):
        raise HTTPException(400, f"invalid status: {status!r}")
    ts = datetime.now(timezone.utc).isoformat()
    with connect() as conn:
        # Make sure a row exists so the UPDATE has something to hit.
        conn.execute(
            "INSERT INTO stock_profiles (ticker) VALUES (?) "
            "ON CONFLICT(ticker) DO NOTHING",
            (ticker,),
        )
        conn.execute(
            "UPDATE stock_profiles SET user_status=?, user_status_reason=?, user_status_ts=? "
            "WHERE ticker=?",
            (status, reason, ts, ticker),
        )


def list_notes(ticker: str, limit: int = 200) -> List[Dict[str, Any]]:
    ensure_schema()
    with connect() as conn:
        cur = conn.execute(
            "SELECT id, ticker, ts, body, tag, source FROM stock_notes "
            "WHERE ticker=? ORDER BY ts DESC LIMIT ?",
            (ticker, limit),
        )
        return [dict(r) for r in cur.fetchall()]


def append_note(ticker: str, body: str, tag: Optional[str] = None,
                source: str = "user") -> Dict[str, Any]:
    ensure_schema()
    ts = datetime.now(timezone.utc).isoformat()
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO stock_notes (ticker, ts, body, tag, source) "
            "VALUES (?,?,?,?,?)",
            (ticker, ts, body, tag, source),
        )
        return {"id": cur.lastrowid, "ticker": ticker, "ts": ts, "body": body,
                "tag": tag, "source": source}


def aggregate_exposure(ticker: str, max_age_days: int = 365) -> List[Dict[str, Any]]:
    """Pull all signal_events for this ticker across scanners. Includes
    13F whales, congress, house clerk PDF, insider Form 4 — each tagged
    with its scanner so the drawer can mix them in one timeline."""
    ensure_schema()
    cutoff = datetime.now(timezone.utc).isoformat()  # cutoff comparison done via SQL date
    with connect() as conn:
        cur = conn.execute(
            "SELECT scanner_name, signal_type, severity, title, body_json, "
            "       source_url, source_timestamp, detected_at "
            "FROM signal_events "
            "WHERE ticker=? "
            "  AND date(detected_at) >= date(?, ?) "
            "ORDER BY detected_at DESC LIMIT 200",
            (ticker, cutoff, f"-{max_age_days} days"),
        )
        events = []
        for r in cur.fetchall():
            try:
                body = json.loads(r["body_json"]) if r["body_json"] else {}
            except json.JSONDecodeError:
                body = {}
            events.append({
                "scanner":          r["scanner_name"],
                "signal_type":      r["signal_type"],
                "severity":         r["severity"],
                "title":            r["title"],
                "body":             body,
                "source_url":       r["source_url"],
                "source_timestamp": r["source_timestamp"],
                "detected_at":      r["detected_at"],
            })
        return events


# ─── LLM business summary generator ───────────────────────────────

PROFILE_PROMPT = """You are NeoMind, generating a structured stock research
profile. Output STRICT JSON only, no preamble or markdown.

Ticker: {ticker}

Schema:
{{
  "name": "<full company name>",
  "sector": "<sector + sub-industry>",
  "summary": "<2-3 sentences on business model + current narrative; cite source URLs inline using [^N] markers>",
  "segments": [
    {{"name": "<segment name>", "pct": <0-100>, "note": "<sub-note>"}}
  ],
  "upstream": [
    {{"ticker": "<TICKER>", "name": "<company>", "role": "<their role in supply chain>"}}
  ],
  "downstream": [
    {{"ticker": "<TICKER>", "name": "<company>", "role": "<customer relationship>"}}
  ],
  "competitors": [
    {{"ticker": "<TICKER>", "name": "<company>", "note": "<positioning>"}}
  ],
  "catalysts": [
    {{"when": "<YYYY-MM-DD or 'YYYY HX'>", "what": "<event>", "severity": "high|med|low"}}
  ],
  "risks": ["<risk 1>", "<risk 2>", ...],
  "style_verdict": "<emoji + 1-line summary, e.g. '🟢 长期持有候选 · 🟠 估值较贵需 timing'>",
  "quick_stats": {{
    "price": "<approx>", "marketCap": "<approx>", "pe": "<approx>"
  }},
  "source_citations": [
    {{"id": 1, "url": "<url>", "title": "<title>"}}
  ]
}}

Rules:
- All claims must trace to a citation in source_citations (use [^N] inline in summary).
- If you don't know a field reliably, leave segments/upstream/etc empty rather than fabricate.
- Numbers (price, marketCap, PE) are approximate from training cutoff; user knows to verify.
- Output JSON ONLY. No explanation outside JSON.
"""


def llm_generate_profile(ticker: str) -> Dict[str, Any]:
    """Call DeepSeek to generate structured profile JSON. Returns dict
    suitable for upsert_profile(). Raises HTTPException on failure."""
    base = os.getenv("LLM_ROUTER_BASE_URL") or "http://127.0.0.1:8000/v1"
    key = os.getenv("LLM_ROUTER_API_KEY") or os.getenv("DEEPSEEK_API_KEY") or "dummy"
    model = os.getenv("STOCK_RESEARCH_MODEL") or "deepseek-v4-flash"
    prompt = PROFILE_PROMPT.format(ticker=ticker)
    messages = [{"role": "user", "content": prompt}]

    req_id = agent_audit.new_req_id()
    agent_audit.audit_request(
        req_id=req_id,
        endpoint=f"/api/stock/{ticker}/profile",
        agent_id="stock-research",
        messages=messages,
        model=model,
        max_tokens=3000,
        temperature=0.2,
        extra={"ticker": ticker},
    )

    t0 = time.monotonic()
    try:
        with httpx.Client(timeout=httpx.Timeout(60.0)) as client:
            resp = client.post(
                f"{base.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": 0.2,
                    "max_tokens": 3000,
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.exception("LLM profile gen failed for %s", ticker)
        agent_audit.audit_error(
            req_id=req_id,
            endpoint=f"/api/stock/{ticker}/profile",
            agent_id="stock-research",
            error_type=type(exc).__name__,
            error_msg=str(exc),
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
        raise HTTPException(502, f"LLM call failed: {exc}")

    raw = (data["choices"][0]["message"]["content"] or "").strip()
    # Strip ``` fences if model snuck them in
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("LLM returned non-JSON for %s: %s", ticker, raw[:200])
        raise HTTPException(502, f"LLM output not JSON: {exc}; raw[:200]={raw[:200]!r}")

    parsed["generated_at"] = datetime.now(timezone.utc).isoformat()
    parsed["generated_model"] = model
    # URL hallucination guard (system-wide policy enforced by
    # agent.llm_url_guard — single chokepoint for ALL LLM URL output).
    from agent.llm_url_guard import verify_citations, sanitize_text
    parsed["source_citations"] = verify_citations(parsed.get("source_citations") or [])
    n_verified = sum(1 for c in parsed["source_citations"] if c.get("verified"))
    # Also sanitize the summary field if it contains URLs (LLMs sometimes
    # inline-cite alongside the [^N] markers).
    if parsed.get("summary"):
        sanitized, stats = sanitize_text(parsed["summary"], context_hint=ticker)
        parsed["summary"] = sanitized
        if stats["n_dead"]:
            logger.info("stock_research: %s summary had %d dead URLs replaced",
                        ticker, stats["n_dead"])
    elapsed = int((time.monotonic() - t0) * 1000)
    logger.info(
        "stock_research: generated %s profile in %dms (citations: %d/%d verified)",
        ticker, elapsed, n_verified, len(parsed["source_citations"]),
    )
    agent_audit.audit_response(
        req_id=req_id,
        endpoint=f"/api/stock/{ticker}/profile",
        agent_id="stock-research",
        content=raw,
        finish_reason=(data.get("choices") or [{}])[0].get("finish_reason"),
        usage=data.get("usage"),
        duration_ms=elapsed,
        extra={
            "ticker": ticker,
            "n_citations": len(parsed["source_citations"]),
            "n_verified_citations": n_verified,
        },
    )
    parsed["req_id"] = req_id
    return parsed


# ─── FastAPI router ───────────────────────────────────────────────

class NoteIn(BaseModel):
    body: str
    tag: Optional[str] = None


class StatusIn(BaseModel):
    status: str
    reason: str = ""


def build_stock_research_router() -> APIRouter:
    router = APIRouter(prefix="/api/stock", tags=["stock-research"])

    @router.get("/{ticker}/profile")
    def get_profile_endpoint(ticker: str) -> Dict[str, Any]:
        t = _normalize(ticker)
        prof = get_profile(t)
        if prof is None:
            raise HTTPException(404, f"no cached profile for {t}; POST to generate")
        return prof

    @router.post("/{ticker}/profile")
    def regenerate_profile(ticker: str) -> Dict[str, Any]:
        t = _normalize(ticker)
        # Preserve existing user_status before clobbering
        existing = get_profile(t) or {}
        gen = llm_generate_profile(t)
        upsert_profile(t, gen)
        # Re-fetch to include preserved status fields
        merged = get_profile(t) or {}
        if existing.get("user_status"):
            with connect() as conn:
                conn.execute(
                    "UPDATE stock_profiles SET user_status=?, user_status_reason=?, user_status_ts=? "
                    "WHERE ticker=?",
                    (existing["user_status"], existing.get("user_status_reason"),
                     existing.get("user_status_ts"), t),
                )
            merged = get_profile(t) or merged
        # req_id isn't a DB column — surface it from the LLM gen so
        # the UI can click-jump to /audit/req/{id} for this run.
        if gen.get("req_id"):
            merged["req_id"] = gen["req_id"]
        return merged

    @router.get("/{ticker}/exposure")
    def get_exposure(
        ticker: str,
        max_age_days: int = Query(365, ge=1, le=3650),
    ) -> Dict[str, Any]:
        t = _normalize(ticker)
        events = aggregate_exposure(t, max_age_days=max_age_days)
        return {"ticker": t, "n": len(events), "events": events}

    @router.get("/{ticker}/notes")
    def get_notes(ticker: str) -> Dict[str, Any]:
        t = _normalize(ticker)
        return {"ticker": t, "notes": list_notes(t)}

    @router.post("/{ticker}/notes")
    def post_note(ticker: str, payload: NoteIn) -> Dict[str, Any]:
        t = _normalize(ticker)
        if not payload.body.strip():
            raise HTTPException(400, "note body is empty")
        return append_note(t, payload.body.strip(), payload.tag, source="user")

    @router.patch("/{ticker}/status")
    def patch_status(ticker: str, payload: StatusIn) -> Dict[str, Any]:
        t = _normalize(ticker)
        update_status(t, payload.status, payload.reason)
        prof = get_profile(t)
        return prof or {"ticker": t, "user_status": payload.status,
                        "user_status_reason": payload.reason}

    return router
