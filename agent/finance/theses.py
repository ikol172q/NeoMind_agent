"""Investment theses — what you believe about a ticker.

Per plan §5 Pillar 4. A thesis is OPTIONAL when promoting a ticker; if
absent, the chain panel renders "⚠ no thesis recorded" but does NOT
block the promote (per §2 information-not-gates philosophy).

Body markdown SHOULD contain four sections:
  ## Bull case        — 3-5 bullets why this works
  ## Bear case        — 3-5 bullets what would break it
  ## Exit triggers    — `- [ ]` checkboxes of conditions to sell
  ## Horizon          — e.g. "12-18 months" / "until next earnings"

The bear case section is critical for the PRO/CONTRA forced display
(plan §5 Pillar 1 chain enhancement #3) — anti-confirmation-bias.
A template helper builds the skeleton; user can override.

Endpoints:
  GET    /api/theses?ticker=AAPL          → list active theses for a ticker
  GET    /api/theses/{thesis_id}          → one thesis full
  POST   /api/theses                      → create
  PATCH  /api/theses/{thesis_id}          → update body / supporting refs
  POST   /api/theses/{thesis_id}/invalidate → mark invalidated with reason
  GET    /api/theses                       → list ALL active theses (no ticker arg)
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field

from agent.finance.persistence import connect, ensure_schema

logger = logging.getLogger(__name__)


_TICKER_RE = re.compile(r"^[A-Z0-9.-]{1,16}$")
_VALID_STATUS = {"active", "invalidated", "realized", "requires_review"}
_MAX_BODY_LEN = 20_000


# ── Helpers ─────────────────────────────────────────────────────────


def _t(ticker: str) -> str:
    s = (ticker or "").strip().upper()
    if not _TICKER_RE.match(s):
        raise HTTPException(400, f"invalid ticker {ticker!r}")
    return s


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def thesis_template() -> str:
    """Default markdown skeleton. Framed as 共识 (grounded, sourced facts)
    + 推断 (forward-looking inferences to validate). The conviction loop:
    每把一条『推断』验证成『共识』= 把未知压小一点。Section headers must stay
    exactly `## 共识` / `## 推断` so _extract_section can pull them."""
    return (
        "## 共识\n"
        "- [业务] (已查证的事实 — 开头加 [标签] 分类: 业务/护城河/财务/估值/"
        "风险/管理层/股东/竞争/催化剂/技术/组合; 尽量附 source, e.g. [SEC 20-F](url))\n"
        "- \n"
        "\n"
        "## 推断\n"
        "- [竞争] (基于共识的前瞻判断/赌注 — 开头加 [标签]; 可能错, 标明若错会怎样)\n"
        "- \n"
        "\n"
        "## Exit triggers\n"
        "- [ ] (触发卖出的具体条件 — e.g. '连续两季 miss')\n"
        "- [ ] \n"
        "\n"
        "## Horizon\n"
        "(e.g. '无固定 — 由 L1 a→e 决定' / '12-18 months')\n"
    )


def _extract_section(body: str, header: str) -> str:
    """Pull the markdown section under a `## header` line. Returns empty
    string if not present. Used by the chain panel to surface bull/bear
    case separately."""
    pattern = rf"^##\s+{re.escape(header)}\s*$(.*?)(?=^##\s|\Z)"
    m = re.search(pattern, body or "", re.MULTILINE | re.DOTALL)
    return (m.group(1).strip() if m else "")


def _check_required_sections(body_md: str) -> List[str]:
    """Return list of MISSING required sections. UI uses this as a
    soft warning ('your thesis is missing Bear case') but does NOT
    reject the create."""
    missing = []
    for h in ("共识", "推断", "Exit triggers"):
        if not _extract_section(body_md, h):
            missing.append(h)
    return missing


# ── Phase 4 (2026-05-10): exit-trigger parser + evaluator ──
#
# Parses the `## Exit triggers` markdown section into structured
# triggers + evaluates each against current data. Per plan §5
# Pillar 5: surfaces in chain panel as decision context, NOT as a
# gate (we never auto-sell).
#
# Trigger format we recognize (one per line):
#   - [ ] -30% drawdown                   → drawdown trigger
#   - [ ] 2 consecutive earnings miss     → earnings miss trigger
#   - [ ] thesis A breaks                  → free-form (eval='manual')
#   - [x] already-fired manually checked   → status='fired_manual'
#
# Evaluation strategy:
#   - For each trigger line, classify by keyword match
#   - Drawdown triggers: parse threshold (-N%), compare to position's
#     unrealized_pct from positions.by_ticker
#   - Earnings miss: count last 2 surprise_pct from earnings_history
#   - Free-form: status='manual', user clicks [ ] → [x] themselves


def parse_exit_triggers(body_md: str) -> List[Dict[str, Any]]:
    """Parse the `## Exit triggers` section into a list of structured
    triggers. Returns:
      [
        {"raw": "- [ ] -30% drawdown",
         "checked_in_md": False,
         "kind": "drawdown",
         "threshold_pct": -30.0,
         "text": "-30% drawdown"},
        ...
      ]
    """
    section = _extract_section(body_md, "Exit triggers")
    if not section:
        return []
    triggers = []
    # Match `- [ ] ...` or `- [x] ...` markdown checkboxes
    pattern = re.compile(r"^\s*-\s*\[\s*([ xX])\s*\]\s*(.+?)\s*$", re.MULTILINE)
    for m in pattern.finditer(section):
        check_char = m.group(1).strip().lower()
        text = m.group(2).strip()
        if not text:
            continue
        # Classify kind
        kind, threshold = _classify_trigger(text)
        triggers.append({
            "raw":            m.group(0).strip(),
            "checked_in_md":  check_char == "x",
            "kind":           kind,
            "threshold_pct":  threshold,
            "text":           text,
        })
    return triggers


_DRAWDOWN_RE = re.compile(r"-?(\d+(?:\.\d+)?)\s*%\s*(?:draw|drop|decline|down)", re.IGNORECASE)
_EARNINGS_MISS_RE = re.compile(r"(\d+)\s*(?:consecutive\s+)?(?:quarter|q|earnings)\s*miss", re.IGNORECASE)
_REGULATORY_RE = re.compile(r"(ban|sanction|export\s+control|regulatory|antitrust)", re.IGNORECASE)


def _classify_trigger(text: str) -> tuple:
    """Returns (kind, threshold_pct). kind ∈
    {drawdown, earnings_miss, regulatory, manual}."""
    m = _DRAWDOWN_RE.search(text)
    if m:
        return "drawdown", -abs(float(m.group(1)))   # always negative
    m = _EARNINGS_MISS_RE.search(text)
    if m:
        return "earnings_miss", float(m.group(1))    # number of consecutive misses
    if _REGULATORY_RE.search(text):
        return "regulatory", None
    return "manual", None


def evaluate_exit_triggers(thesis: Dict[str, Any]) -> List[Dict[str, Any]]:
    """For each parsed trigger, compute current state. Returns enriched
    triggers with extra fields:
      - fired: True/False/None  (None = can't auto-evaluate, manual)
      - current_value: numeric representation of current state
      - explanation: human-readable why-fired-or-not
    """
    triggers = parse_exit_triggers(thesis.get("body_md", ""))
    if not triggers:
        return []
    ticker = thesis.get("ticker")
    # Pull current position state once + earnings history
    pos = _safe_position(ticker)
    earnings_misses = _safe_recent_earnings_misses(ticker)
    out = []
    for t in triggers:
        ev = dict(t)
        if t["checked_in_md"]:
            ev["fired"] = True
            ev["explanation"] = "manually checked in thesis markdown"
            ev["current_value"] = None
        elif t["kind"] == "drawdown":
            current_pct = pos.get("unrealized_pct") if pos else None
            ev["current_value"] = current_pct
            if current_pct is None:
                ev["fired"] = None
                ev["explanation"] = "no position data — can't evaluate"
            else:
                fired = current_pct <= t["threshold_pct"]
                ev["fired"] = fired
                ev["explanation"] = (
                    f"current unrealized {current_pct:+.2f}% "
                    f"vs threshold {t['threshold_pct']:.0f}%; "
                    f"{'FIRED' if fired else 'not fired'}"
                )
        elif t["kind"] == "earnings_miss":
            ev["current_value"] = earnings_misses
            need = int(t["threshold_pct"]) if t["threshold_pct"] else 1
            ev["fired"] = earnings_misses >= need
            ev["explanation"] = (
                f"last {earnings_misses} earnings missed; "
                f"trigger fires at {need} consecutive miss"
            )
        else:
            # 'regulatory' and 'manual' — can't auto-evaluate
            ev["fired"] = None
            ev["current_value"] = None
            ev["explanation"] = (
                "free-form trigger — check manually + tick [x] in thesis when fired"
            )
        out.append(ev)
    return out


def _safe_position(ticker: Optional[str]) -> Dict[str, Any]:
    """Best-effort position lookup. Returns {} if ticker not held or
    positions module unavailable."""
    if not ticker:
        return {}
    try:
        from agent.finance.positions import by_ticker
        d = by_ticker(ticker)
        return d.get("summary") or {}
    except Exception as exc:
        logger.debug("position lookup %s failed: %s", ticker, exc)
        return {}


def _safe_recent_earnings_misses(ticker: Optional[str]) -> int:
    """Count of consecutive earnings_history rows (most recent first)
    where surprise_pct < 0. Stops at the first non-miss."""
    if not ticker:
        return 0
    try:
        with connect() as conn:
            rows = conn.execute(
                "SELECT surprise_pct FROM earnings_history "
                "WHERE ticker = ? ORDER BY earnings_date DESC LIMIT 8",
                (ticker,),
            ).fetchall()
        n_miss = 0
        for r in rows:
            sp = r["surprise_pct"]
            if sp is None or sp >= 0:
                break
            n_miss += 1
        return n_miss
    except Exception:
        return 0


# ── DAO ─────────────────────────────────────────────────────────────


def _row_to_dict(row: Any) -> Dict[str, Any]:
    return {
        "thesis_id":               row["thesis_id"],
        "ticker":                  row["ticker"],
        "created_at":              row["created_at"],
        "body_md":                 row["body_md"],
        "supporting_fact_ids":     json.loads(row["supporting_fact_ids"] or "[]"),
        "supporting_signal_types": json.loads(row["supporting_signal_types"] or "[]"),
        "status":                  row["status"],
        "invalidated_at":          row["invalidated_at"],
        "invalidated_reason":      row["invalidated_reason"],
        "last_health_check_at":    row["last_health_check_at"],
        # Section extracts for the chain panel — saves the frontend
        # from re-implementing the markdown parser per render.
        "sections": {
            "consensus":     _extract_section(row["body_md"], "共识"),
            "inference":     _extract_section(row["body_md"], "推断"),
            "exit_triggers": _extract_section(row["body_md"], "Exit triggers"),
            "horizon":       _extract_section(row["body_md"], "Horizon"),
            # kept for any legacy thesis still using English headers
            "bull_case":     _extract_section(row["body_md"], "Bull case"),
            "bear_case":     _extract_section(row["body_md"], "Bear case"),
        },
        "missing_sections": _check_required_sections(row["body_md"]),
    }


# ── Pydantic ────────────────────────────────────────────────────────


class CreateBody(BaseModel):
    ticker: str
    body_md: str = Field(..., max_length=_MAX_BODY_LEN)
    supporting_fact_ids: Optional[List[int]] = None
    supporting_signal_types: Optional[List[str]] = None


class UpdateBody(BaseModel):
    body_md: Optional[str] = Field(None, max_length=_MAX_BODY_LEN)
    supporting_fact_ids: Optional[List[int]] = None
    supporting_signal_types: Optional[List[str]] = None


class InvalidateBody(BaseModel):
    reason: str = Field(..., max_length=500)


# ── Router ──────────────────────────────────────────────────────────


def build_theses_router() -> APIRouter:
    router = APIRouter(prefix="/api/theses", tags=["theses"])

    @router.get("/template")
    def get_template() -> Dict[str, str]:
        """Return the default markdown skeleton for the create form."""
        return {"body_md": thesis_template()}

    @router.get("")
    def list_theses(
        ticker: Optional[str] = Query(None),
        status: str = Query("active",
            description="'active' returns active+requires_review (both"
                        " still being tracked); use 'all' to also see"
                        " invalidated/realized; or pass a specific value"),
    ) -> Dict[str, Any]:
        if status not in _VALID_STATUS and status != "all":
            raise HTTPException(400, f"status must be one of {sorted(_VALID_STATUS)} or 'all'")
        ensure_schema()
        sql = "SELECT * FROM investment_theses"
        params: List[Any] = []
        wh = []
        if ticker:
            wh.append("ticker = ?")
            params.append(_t(ticker))
        if status == "active":
            # Phase 4: include requires_review as part of "active" — the
            # thesis is still being tracked, just flagged for user
            # attention. Hiding it because the daily health-check
            # auto-flagged it would be a UX bug (thesis exists, user
            # should still see it; flagged != deleted).
            wh.append("status IN ('active', 'requires_review')")
        elif status != "all":
            wh.append("status = ?")
            params.append(status)
        if wh:
            sql += " WHERE " + " AND ".join(wh)
        sql += " ORDER BY created_at DESC"
        with connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return {"theses": [_row_to_dict(r) for r in rows], "count": len(rows)}

    @router.get("/{thesis_id}")
    def get_thesis(thesis_id: str) -> Dict[str, Any]:
        ensure_schema()
        with connect() as conn:
            row = conn.execute(
                "SELECT * FROM investment_theses WHERE thesis_id = ?",
                (thesis_id,),
            ).fetchone()
        if not row:
            raise HTTPException(404, f"thesis {thesis_id!r} not found")
        d = _row_to_dict(row)
        # Phase 4: include evaluated exit triggers when fetching a single
        # thesis (omitted from list view to keep that cheap).
        d["exit_triggers_evaluated"] = evaluate_exit_triggers(d)
        return d

    @router.get("/{thesis_id}/exit_triggers")
    def get_exit_triggers(thesis_id: str) -> Dict[str, Any]:
        """Standalone evaluator endpoint — UI can poll without
        re-fetching the full thesis body each time."""
        ensure_schema()
        with connect() as conn:
            row = conn.execute(
                "SELECT * FROM investment_theses WHERE thesis_id = ?",
                (thesis_id,),
            ).fetchone()
        if not row:
            raise HTTPException(404, f"thesis {thesis_id!r} not found")
        d = _row_to_dict(row)
        evaluated = evaluate_exit_triggers(d)
        return {
            "thesis_id": thesis_id,
            "ticker":    d["ticker"],
            "triggers":  evaluated,
            "n_fired":   sum(1 for t in evaluated if t["fired"] is True),
            "n_unfired": sum(1 for t in evaluated if t["fired"] is False),
            "n_manual":  sum(1 for t in evaluated if t["fired"] is None),
        }

    @router.post("")
    def create_thesis(body: CreateBody) -> Dict[str, Any]:
        ticker = _t(body.ticker)
        thesis_id = str(uuid.uuid4())
        now = _now()
        ensure_schema()
        with connect() as conn:
            conn.execute(
                "INSERT INTO investment_theses "
                "(thesis_id, ticker, created_at, body_md, "
                " supporting_fact_ids, supporting_signal_types, status) "
                "VALUES (?, ?, ?, ?, ?, ?, 'active')",
                (
                    thesis_id, ticker, now, body.body_md,
                    json.dumps(body.supporting_fact_ids or []),
                    json.dumps(body.supporting_signal_types or []),
                ),
            )
            # Audit trail (Phase W) — record thesis creation as
            # watchlist event. Doesn't require ticker to be in
            # user_watchlist; we still log the action.
            conn.execute(
                "INSERT INTO watchlist_audit "
                "(audit_id, ticker, action, trigger_kind, trigger_ref_id, ts, note) "
                "VALUES (?, ?, 'thesis_create', 'thesis', ?, ?, ?)",
                (str(uuid.uuid4()), ticker, thesis_id, now,
                 f"thesis created ({len(body.supporting_fact_ids or [])} facts cited)"),
            )
        missing = _check_required_sections(body.body_md)
        return {
            "thesis_id": thesis_id,
            "ticker":    ticker,
            "missing_sections": missing,    # soft warning, not error
        }

    @router.patch("/{thesis_id}")
    def update_thesis(thesis_id: str, body: UpdateBody) -> Dict[str, Any]:
        ensure_schema()
        with connect() as conn:
            cur = conn.execute(
                "SELECT thesis_id FROM investment_theses WHERE thesis_id = ?",
                (thesis_id,),
            )
            if not cur.fetchone():
                raise HTTPException(404, f"thesis {thesis_id!r} not found")
            sets = []
            params: List[Any] = []
            if body.body_md is not None:
                sets.append("body_md = ?")
                params.append(body.body_md)
            if body.supporting_fact_ids is not None:
                sets.append("supporting_fact_ids = ?")
                params.append(json.dumps(body.supporting_fact_ids))
            if body.supporting_signal_types is not None:
                sets.append("supporting_signal_types = ?")
                params.append(json.dumps(body.supporting_signal_types))
            if not sets:
                return {"ok": True, "no_change": True}
            params.append(thesis_id)
            conn.execute(
                f"UPDATE investment_theses SET {', '.join(sets)} WHERE thesis_id = ?",
                params,
            )
        return {"ok": True, "thesis_id": thesis_id}

    @router.post("/{thesis_id}/invalidate")
    def invalidate_thesis(thesis_id: str, body: InvalidateBody) -> Dict[str, Any]:
        ensure_schema()
        now = _now()
        with connect() as conn:
            cur = conn.execute(
                "SELECT ticker, status FROM investment_theses WHERE thesis_id = ?",
                (thesis_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, f"thesis {thesis_id!r} not found")
            if row["status"] == "invalidated":
                raise HTTPException(409, "already invalidated")
            conn.execute(
                "UPDATE investment_theses "
                "SET status = 'invalidated', invalidated_at = ?, invalidated_reason = ? "
                "WHERE thesis_id = ?",
                (now, body.reason, thesis_id),
            )
            conn.execute(
                "INSERT INTO watchlist_audit "
                "(audit_id, ticker, action, trigger_kind, trigger_ref_id, ts, note) "
                "VALUES (?, ?, 'thesis_invalidate', 'thesis', ?, ?, ?)",
                (str(uuid.uuid4()), row["ticker"], thesis_id, now,
                 f"invalidated: {body.reason[:200]}"),
            )
        return {"ok": True, "thesis_id": thesis_id, "status": "invalidated"}

    return router
