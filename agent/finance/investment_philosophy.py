"""Personal Investment Philosophy — living document / Ulysses contract.

Implements the user-facing CRUD around the `investment_philosophy`
table. The structure is industry-standard IPS (Investment Policy
Statement, CFA spec) adapted for an individual concentrated-tech
investor with hedge needs:

  · NORTH STAR     — 1-sentence "why am I doing this"
  · IDENTITY        — 1 paragraph: who I am as investor
  · BELIEFS         — array of falsifiable claims I'm betting on
  · CIRCLE          — what I'll trade / what I'll skip
  · HORIZON+SIZING  — concrete numeric rules
  · ENTRY RULES     — what MUST be true before I buy
  · EXIT RULES      — when do I sell (both up + down)
  · HEDGE PLAN      — anti-fragile: what if main thesis fails?
  · DISAGREEMENT    — protocol for handling being wrong
  · REVIEW          — schedule + last-reviewed timestamp

Every save creates a new version row (versioned), so you can audit
how your thinking evolved over months/years.

Endpoints:
  GET  /api/philosophy           — active philosophy
  GET  /api/philosophy/history   — version log
  PUT  /api/philosophy           — update fields + bump version
  POST /api/philosophy/reset     — clear and start fresh (rare)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agent.finance.persistence import connect, ensure_schema


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# ── Initial seed ────────────────────────────────────────────────────
#
# PRIVACY: the seed contains the user's PERSONAL investment profile
# (real holdings, position concentration, drawdown tolerance, cash-flow
# runway). That is sensitive financial PII and MUST NOT live in the
# source tree / git history (this repo is public on GitHub).
#
# Resolution order for the first-run seed:
#   1. ~/.neomind/fin/seed_philosophy.json   (gitignored; the user's real
#      profile lives here — written once, never committed)
#   2. DEFAULT_SEED below                     (a neutral, generic template
#      with NO personal data — safe to ship publicly)
#
# To set up your personal seed: copy seed_philosophy.example.json to
# ~/.neomind/fin/seed_philosophy.json and edit, OR just fill it in via the
# IPS editor UI (which writes to the DB, also gitignored).

DEFAULT_SEED = {
    "version": "v0.1",
    "north_star": (
        "(示例 — 请通过 IPS 编辑器填写) 用一句话写下你为什么投资、目标回报、"
        "和能承受的最大回撤. 例: 在 N 年里以 X% CAGR 复利本金, 能承受 Y% drawdown."
    ),
    "identity": (
        "(示例) 一段话描述你是什么类型的投资者: 持有期偏好、决策风格、"
        "会做/不做什么、你的 edge 来自哪里."
    ),
    "beliefs_json": json.dumps([
        {"claim": "(示例) 我在 bet 的一条可证伪的核心信念",
         "why": "为什么我相信它",
         "falsified_if": "什么证据出现会让我承认这条信念错了"},
    ], ensure_ascii=False),
    "circle_competence": (
        "(示例) **会做**: 你真正理解的资产类别 / 行业. "
        "**不会做**: 你刻意回避的 (复杂衍生品 / 你不懂的市场等)."
    ),
    "time_horizon": (
        "(示例) 默认持有期, core 仓 vs 试探仓的不同 horizon 规则."
    ),
    "sizing_rules_json": json.dumps({
        "max_single_position_pct": 0.30,
        "max_sector_pct": 0.65,
        "cash_floor_pct": 0.05,
        "max_new_position_pct": 0.05,
        "notes": "(示例) 单一持仓 / 单一 sector 上限, cash floor, 新仓建仓节奏.",
    }, ensure_ascii=False),
    "entry_rules": "(示例) 列出建仓前必须满足的条件清单.",
    "exit_rules": "(示例) Stop-loss / thesis-break / profit-taking 各自的规则; 以及'绝不卖'的情形.",
    "hedge_plan": "(示例) 主线 thesis 失败的几种场景 + 各自的对冲动作.",
    "disagreement_protocol": "(示例) 当 smart money 跟你方向相反时的处理流程.",
    "review_cadence": "monthly",
    "last_reviewed_at": _today(),
    "change_note": "v0.1 — neutral template. 填入你的个人 IPS (写到 DB, 不进 git).",
}


def _load_seed() -> Dict[str, Any]:
    """Load the user's personal seed from the gitignored local file if
    present; otherwise fall back to the neutral DEFAULT_SEED. This keeps
    real financial PII out of the source tree + git history."""
    import os
    path = os.path.expanduser("~/.neomind/fin/seed_philosophy.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data.get("north_star"):
                data.setdefault("last_reviewed_at", _today())
                return data
        except Exception:
            pass
    return DEFAULT_SEED


# ── DAO ─────────────────────────────────────────────────────────────


def get_active() -> Optional[Dict[str, Any]]:
    ensure_schema()
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM investment_philosophy "
            "WHERE is_active = 1 ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
    return _row_to_dict(row) if row else None


def get_history(limit: int = 20) -> List[Dict[str, Any]]:
    ensure_schema()
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM investment_philosophy "
            "ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def _row_to_dict(row) -> Dict[str, Any]:
    if not row:
        return {}
    d = dict(row)
    for key in ("beliefs_json", "sizing_rules_json"):
        if d.get(key):
            try: d[key.replace("_json", "")] = json.loads(d[key])
            except json.JSONDecodeError: pass
    return d


def upsert(fields: Dict[str, Any], change_note: Optional[str] = None) -> Dict[str, Any]:
    """Save a new version. Deactivates prior active row + inserts new."""
    ensure_schema()
    current = get_active() or {}
    # Bump version
    cur_ver = current.get("version") or "v0.0"
    try:
        major, minor = cur_ver.lstrip("v").split(".")
        new_ver = f"v{major}.{int(minor) + 1}"
    except (ValueError, AttributeError):
        new_ver = "v1.0"

    payload = {**current, **fields,
               "version": new_ver,
               "is_active": 1,
               "change_note": change_note or "(no note)",
               "updated_at": _now()}
    if "created_at" not in payload or not payload["created_at"]:
        payload["created_at"] = payload["updated_at"]

    # Normalize structured fields
    if isinstance(payload.get("beliefs"), (list, dict)):
        payload["beliefs_json"] = json.dumps(payload["beliefs"], ensure_ascii=False)
        payload.pop("beliefs", None)
    if isinstance(payload.get("sizing_rules"), dict):
        payload["sizing_rules_json"] = json.dumps(payload["sizing_rules"], ensure_ascii=False)
        payload.pop("sizing_rules", None)

    with connect() as conn:
        conn.execute("UPDATE investment_philosophy SET is_active = 0 WHERE is_active = 1")
        conn.execute(
            "INSERT INTO investment_philosophy "
            "(version, is_active, north_star, identity, beliefs_json, "
            " circle_competence, time_horizon, sizing_rules_json, "
            " entry_rules, exit_rules, hedge_plan, disagreement_protocol, "
            " review_cadence, last_reviewed_at, change_note, "
            " created_at, updated_at) "
            "VALUES (?,1,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (payload["version"],
             payload.get("north_star"),
             payload.get("identity"),
             payload.get("beliefs_json"),
             payload.get("circle_competence"),
             payload.get("time_horizon"),
             payload.get("sizing_rules_json"),
             payload.get("entry_rules"),
             payload.get("exit_rules"),
             payload.get("hedge_plan"),
             payload.get("disagreement_protocol"),
             payload.get("review_cadence"),
             payload.get("last_reviewed_at"),
             payload.get("change_note"),
             payload.get("created_at"),
             payload.get("updated_at")),
        )
    return get_active() or {}


def seed_if_empty() -> Dict[str, Any]:
    """First-run seed. Loads the user's personal profile from the
    gitignored ~/.neomind/fin/seed_philosophy.json if present, else uses
    the neutral DEFAULT_SEED. Real financial PII never lives in source."""
    if get_active():
        return get_active()
    seed = _load_seed()
    return upsert(seed, change_note=seed.get("change_note", "initial seed"))


# ── API ─────────────────────────────────────────────────────────────


class UpdateBody(BaseModel):
    north_star:            Optional[str] = None
    identity:              Optional[str] = None
    beliefs:               Optional[List[Dict[str, Any]]] = None
    circle_competence:     Optional[str] = None
    time_horizon:          Optional[str] = None
    sizing_rules:          Optional[Dict[str, Any]] = None
    entry_rules:           Optional[str] = None
    exit_rules:            Optional[str] = None
    hedge_plan:            Optional[str] = None
    disagreement_protocol: Optional[str] = None
    review_cadence:        Optional[str] = None
    last_reviewed_at:      Optional[str] = None
    change_note:           Optional[str] = None


def build_philosophy_router() -> APIRouter:
    router = APIRouter(prefix="/api/philosophy", tags=["philosophy"])

    @router.get("")
    def get_endpoint() -> Dict[str, Any]:
        # Seed on first read so widget never shows empty
        p = seed_if_empty()
        return p or {}

    @router.get("/history")
    def history_endpoint(limit: int = 20) -> Dict[str, Any]:
        return {"history": get_history(limit), "n": len(get_history(limit))}

    @router.put("")
    def put_endpoint(body: UpdateBody) -> Dict[str, Any]:
        fields = {k: v for k, v in body.dict().items() if v is not None}
        change_note = fields.pop("change_note", None)
        return upsert(fields, change_note=change_note)

    @router.post("/touch_review")
    def touch_review_endpoint() -> Dict[str, Any]:
        """Mark today as the last review date (lightweight ack — 'I read it')."""
        return upsert({"last_reviewed_at": _today()},
                      change_note="review touchstone (no content change)")

    return router
