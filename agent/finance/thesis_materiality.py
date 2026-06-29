"""Goal 2 — evidence-driven review trigger (证据驱动复盘触发).

The bridge from Goal-1 (观察 / comprehensive facts) to the user's own decision
process (投资理念 L1: a→b→c→d→e). When NEW SEC hard events land since the user
last reviewed a holding, assess each against the holding's thesis (`body_md`)
and classify:

    印证 confirm · 动摇 weaken · 破 break · 无关 irrelevant

plus which philosophy element it touches (L0 下行 / L1·a 方向 / L1·b 时机 /
L1·c 认知 / L1·d 收益风险 / L1·e 仓位).

HARD BOUNDARY (per 投资理念 disagreement_protocol "只汇报,不替我做决定"):
this layer only FLAGS "该复盘 / 论点可能破了" (sets investment_theses.status =
'requires_review'). It NEVER decides, NEVER recommends buy/sell, NEVER
auto-invalidates a thesis, and NEVER touches position size / concentration.

Evidence sources (MVP — SEC hard events only):
  1. New 8-K / 6-K filings since the review anchor (recent_filings, SEC-sourced).
  2. Anchored facts from a newly-filed annual report (source_filing_date >=
     anchor) — business / risk / competitor text we can compare verbatim.

Grounding (anti-hallucination): every verdict's `why` must reference the
specific triggering event; if an event's materiality cannot be judged from what
we have (e.g. an 8-K whose body we have not fetched), the model classifies by
the item TYPE's plausible bearing on THIS thesis and says "需读原文" rather than
inventing content. The structured `ref` must match a real evidence item or the
item is dropped.

Mirrors fin_agent_synth: cached table + endpoint (cold-start compute) +
optional daily job hook.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException

from agent.finance.persistence import connect, ensure_schema
from agent.finance.extractors.base import call_strict_json

logger = logging.getLogger(__name__)

# review anchor fallback when a holding was never reviewed
_FALLBACK_LOOKBACK_DAYS = 90
_MAX_SEC_EVIDENCE = 4      # 8-K/6-K + new-annual-filing facts
_MAX_NEWS_EVIDENCE = 5     # recent company news since review
# total ≤ 9 items keeps the LLM JSON well under the token cap (no truncation)
# severity ordering — verdict for the thesis = the worst single item
_RANK = {"破": 3, "动摇": 2, "印证": 1, "无关": 0}
_CLASSES = ("印证", "动摇", "破", "无关")
_TOUCHES = ("L0 下行", "L1·a 方向", "L1·b 时机", "L1·c 认知",
            "L1·d 收益风险", "L1·e 仓位", "—")

_SYSTEM_PROMPT = """\
你是 NeoMind 投研 agent。下面给你某持仓的【投资论点(thesis)】和【自上次复盘以来的新 SEC 事件】。
任务: 逐条判断每个新事件对这条论点是否 material(实质相关),帮用户决定要不要重新复盘。

对每个事件输出: classification(印证/动摇/破/无关) + touches(触及理念哪条) + why(一句话)。

硬规则(违反则该条被丢弃):
1. 只能依据我给你的事件信息,**绝不编造事件内容**。
2. why 必须引用该事件(写明是哪个事件/什么类型),**≤25 字**,简洁。
3. 8-K/6-K 只给了条目类型(如「业绩(财报)」「高管/董事变动」),没给正文:
   - 若该类型**可能**影响这条论点 → 判「动摇」, why 写「X类事件可能影响[论点要点],需读原文」。
   - 若该类型与论点明显无关(如例行股东投票) → 判「无关」。
   - **绝不**假装知道 8-K 正文写了什么。
4. 拿到正文的(年报抽取的业务/风险事实) → 可直接判 印证/动摇/破。
5. 新闻(给了标题+摘要)→ 按内容判:实质事件(并购/诉讼/指引调整/评级或目标价大动/高管/监管/重大合同)才判 动摇/破;
   标题党、泛泛复盘("为什么X股动了""该不该买")、纯行情评论 → 判「无关」。绝不被标题情绪带跑。
6. 不确定就判「无关」。宁可漏报不要编。
7. **绝不**输出买卖建议,**绝不**评论仓位大小/集中度 —— 只判 material 与否。

touches 取值: L0 下行 / L1·a 方向 / L1·b 时机 / L1·c 认知 / L1·d 收益风险 / L1·e 仓位 / —

输出 JSON: {"items": [{"ref": "<事件标识(原样抄我给的 ref)>", "classification": "...", "touches": "...", "why": "..."}]}
"""

_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["items"],
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["ref", "classification", "touches", "why"],
                "properties": {
                    "ref":            {"type": "string"},
                    "classification": {"type": "string", "enum": list(_CLASSES)},
                    "touches":        {"type": "string"},
                    "why":            {"type": "string"},
                },
            },
        },
    },
}


def _ensure_table(conn) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS thesis_materiality ("
        " ticker TEXT PRIMARY KEY, thesis_id TEXT, verdict TEXT,"
        " items_json TEXT, anchor_at TEXT, computed_at TEXT, status TEXT)"
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _anchor(conn, ticker: str) -> Tuple[str, str]:
    """(anchor_iso, source) — last_reviewed_at, else 90d fallback."""
    row = conn.execute(
        "SELECT last_reviewed_at FROM user_watchlist WHERE ticker = ?", (ticker,)
    ).fetchone()
    last = row["last_reviewed_at"] if row else None
    if last:
        try:
            dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat(), "last_reviewed_at"
        except Exception:
            pass
    return (_now() - timedelta(days=_FALLBACK_LOOKBACK_DAYS)).isoformat(), "fallback_90d"


def _read_thesis(conn, ticker: str) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        "SELECT thesis_id, body_md, status FROM investment_theses "
        "WHERE ticker = ? AND status IN ('active','requires_review') "
        "ORDER BY created_at DESC LIMIT 1",
        (ticker,),
    ).fetchone()
    if not row or not (row["body_md"] or "").strip():
        return None
    return {"thesis_id": row["thesis_id"], "body_md": row["body_md"], "status": row["status"]}


def _gather_evidence(conn, ticker: str, anchor_iso: str) -> List[Dict[str, str]]:
    """New SEC hard events since the anchor. Each = {ref, kind, detail}."""
    ev: List[Dict[str, str]] = []
    anchor_date = anchor_iso[:10]

    # 1) new 8-K / 6-K filings (SEC-sourced, real filing dates)
    try:
        from agent.finance.recent_filings import get_recent_filings
        rf = get_recent_filings(ticker)
        for f in rf.get("filings", []):
            if (f.get("date") or "") >= anchor_date and f.get("form", "").startswith(("8-K", "6-K")):
                ref = f"{f['date']} {f['form']} {f.get('event','')}".strip()
                ev.append({"ref": ref, "kind": "SEC事件(只有条目类型,无正文)",
                           "detail": f"{f['form']} · {f.get('event','')} · items={f.get('items','')}"})
    except Exception as exc:
        logger.debug("recent_filings unavailable for %s: %s", ticker, exc)

    # 2) anchored facts from a newly-filed annual report (we have the text)
    rows = conn.execute(
        "SELECT fact_type, evidence_quote, source_filing_date FROM stock_anchored_facts "
        "WHERE ticker = ? AND source_filing_date >= ? "
        "  AND fact_type IN ('business_summary','risk','competitor','customer','supplier') "
        "ORDER BY source_filing_date DESC",
        (ticker, anchor_date),
    ).fetchall()
    for r in rows:
        q = (r["evidence_quote"] or "").strip()
        if not q:
            continue
        ref = f"{r['source_filing_date']} 年报{r['fact_type']}"
        ev.append({"ref": ref, "kind": f"年报抽取事实({r['fact_type']},有正文)",
                   "detail": q[:280]})
    sec_ev = ev[:_MAX_SEC_EVIDENCE]

    # 3) recent company news since the anchor (Finnhub company-news, free)
    news_ev: List[Dict[str, str]] = []
    try:
        from agent.data_sources.finnhub_news import get_company_news
        try:
            gap_days = (datetime.now(timezone.utc) - datetime.fromisoformat(anchor_iso)).days
        except Exception:
            gap_days = 14
        for n in get_company_news(ticker, days=min(max(gap_days, 1), 30), limit=12):
            if n.get("date") and n["date"] >= anchor_date:
                news_ev.append({
                    "ref": f"{n['date']} 新闻·{n.get('source','')}",
                    "kind": "新闻(有标题/摘要)",
                    "detail": f"{n['headline']} — {(n.get('summary') or '')[:160]}",
                })
            if len(news_ev) >= _MAX_NEWS_EVIDENCE:
                break
    except Exception as exc:
        logger.debug("news evidence unavailable for %s: %s", ticker, exc)

    return sec_ev + news_ev


def compute(ticker: str, since: Optional[str] = None) -> Dict[str, Any]:
    """Assess new SEC evidence against the holding's thesis. Flags
    requires_review on 破/动摇. Never decides, never invalidates.

    `since` (ISO ts) overrides the review anchor — used by tests and a future
    daily job that wants a fixed window instead of per-holding last_reviewed_at.
    """
    ticker = ticker.upper().strip()
    now_iso = _now().isoformat()
    with connect() as conn:
        ensure_schema()
        _ensure_table(conn)
        thesis = _read_thesis(conn, ticker)
        if not thesis:
            result = {"ticker": ticker, "status": "no_thesis", "verdict": None,
                      "items": [], "anchor_at": None, "computed_at": now_iso}
            _persist(conn, result)
            return result
        anchor_iso, anchor_src = (since, "override") if since else _anchor(conn, ticker)
        evidence = _gather_evidence(conn, ticker, anchor_iso)
        if not evidence:
            result = {"ticker": ticker, "status": "no_new_evidence", "verdict": "无关",
                      "items": [], "anchor_at": anchor_iso, "anchor_source": anchor_src,
                      "computed_at": now_iso, "thesis_id": thesis["thesis_id"]}
            _persist(conn, result)
            return result

    # build prompt (outside the connection — LLM call can be slow)
    ev_lines = "\n".join(
        f"[{i}] ref=「{e['ref']}」 类型={e['kind']}\n    内容: {e['detail']}"
        for i, e in enumerate(evidence)
    )
    user_content = (
        f"=== 投资论点 (thesis, ticker {ticker}) ===\n{thesis['body_md']}\n\n"
        f"=== 自上次复盘以来的新 SEC 事件 ({len(evidence)} 条) ===\n{ev_lines}"
    )
    valid_refs = {e["ref"] for e in evidence}

    raw = None
    last_err: Optional[Exception] = None
    for attempt in range(2):
        try:
            raw = call_strict_json(
                system_prompt=_SYSTEM_PROMPT, user_content=user_content,
                json_schema=_SCHEMA, schema_name="thesis_materiality", max_tokens=3500,
            )
            break
        except Exception as e:  # noqa: BLE001 — transient LLM failure → one retry
            last_err = e
            logger.warning("materiality LLM failed %s (try %d/2): %s", ticker, attempt + 1, e)
    if raw is None:
        raise RuntimeError(f"materiality LLM unavailable after retry: {last_err}")

    # GROUNDING GATE: keep only items whose ref matches a real evidence item
    # and whose classification is valid. Anything else is dropped (no invented
    # materiality). `touches` is normalized to the allowed set or "—".
    items: List[Dict[str, str]] = []
    for it in (raw.get("items") or []):
        ref = (it.get("ref") or "").strip()
        cls = (it.get("classification") or "").strip()
        if ref not in valid_refs or cls not in _CLASSES:
            logger.info("materiality: dropped ungrounded item for %s ref=%r cls=%r", ticker, ref, cls)
            continue
        # normalize touches leniently (LLM may drop the space, e.g. "L0下行")
        raw_touch = (it.get("touches") or "—").strip()
        touches = next((c for c in _TOUCHES if c.replace(" ", "") == raw_touch.replace(" ", "")), "—")
        why = (it.get("why") or "").strip()[:80]
        items.append({"ref": ref, "classification": cls, "touches": touches, "why": why})

    verdict = "无关"
    for it in items:
        if _RANK[it["classification"]] > _RANK[verdict]:
            verdict = it["classification"]

    result = {
        "ticker": ticker, "thesis_id": thesis["thesis_id"], "status": "ok",
        "verdict": verdict, "items": items, "anchor_at": anchor_iso,
        "anchor_source": anchor_src, "computed_at": now_iso,
    }

    with connect() as conn:
        _ensure_table(conn)
        _persist(conn, result)
        # FLAG ONLY — never invalidate. 破/动摇 ⇒ requires_review.
        if verdict in ("破", "动摇"):
            conn.execute(
                "UPDATE investment_theses SET status='requires_review', last_health_check_at=? "
                "WHERE thesis_id=? AND status='active'",
                (now_iso, thesis["thesis_id"]),
            )
    return result


def _persist(conn, r: Dict[str, Any]) -> None:
    conn.execute(
        "INSERT INTO thesis_materiality (ticker, thesis_id, verdict, items_json, anchor_at, computed_at, status) "
        "VALUES (?,?,?,?,?,?,?) ON CONFLICT(ticker) DO UPDATE SET "
        "thesis_id=excluded.thesis_id, verdict=excluded.verdict, items_json=excluded.items_json, "
        "anchor_at=excluded.anchor_at, computed_at=excluded.computed_at, status=excluded.status",
        (r["ticker"], r.get("thesis_id"), r.get("verdict"),
         json.dumps(r.get("items", []), ensure_ascii=False),
         r.get("anchor_at"), r["computed_at"], r.get("status", "ok")),
    )


def read(ticker: str) -> Optional[Dict[str, Any]]:
    ticker = ticker.upper().strip()
    with connect() as conn:
        _ensure_table(conn)
        row = conn.execute("SELECT * FROM thesis_materiality WHERE ticker=?", (ticker,)).fetchone()
    if not row:
        return None
    return {
        "ticker": row["ticker"], "thesis_id": row["thesis_id"], "verdict": row["verdict"],
        "items": json.loads(row["items_json"] or "[]"), "anchor_at": row["anchor_at"],
        "computed_at": row["computed_at"], "status": row["status"],
    }


def build_thesis_materiality_router() -> APIRouter:
    router = APIRouter(prefix="/api/stock", tags=["thesis-materiality"])

    @router.get("/{ticker}/thesis_review")
    def thesis_review(ticker: str, refresh: bool = False) -> Dict[str, Any]:
        if not refresh:
            cached = read(ticker)
            if cached:
                return cached
        try:
            return compute(ticker)
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, f"thesis materiality failed: {e}")

    return router
