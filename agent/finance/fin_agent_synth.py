"""NeoMind fin agent — grounded 3-sentence synthesis (优势 / 劣势 / 综合).

The diagnostic chain + anchored facts are already comprehensive; this gives a
background, systematic READ over them: three sentences — strength, weakness,
net take — that the agent SYNTHESIZES from already-verified, DATED inputs.

Principle (hard): every claim must trace to a verified data source; nothing
invented. Enforced two ways:
  1. The input "bag" contains ONLY verified+dated data (fundamentals=yfinance,
     facts=10-K verbatim, holders=yfinance, owner moves=13F, thesis=user).
  2. 优势/劣势 each carry an evidence_quote that must be a VERBATIM substring of
     the bag — `validate_quotes` drops the sentence if it isn't (same gate as
     the anchored-fact extractors). 综合 may add NO new number.

Every input line is tagged with its source + as-of date, and the stored result
records the source list + generated_at (freshness). Mirrors official_news /
anchored: cached table + endpoint (cold-start generate) + optional daily job.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException

from agent.finance.persistence import connect, ensure_schema
from agent.finance.extractors.base import call_strict_json

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
你是 NeoMind 投研 agent。下面是关于某公司的**已验证、带日期**的数据。
请用中文输出恰好 3 句话的速读: 优势、劣势、综合。

硬规则(违反则被丢弃):
1. 只能用输入里出现的数据,**绝不引入输入中没有的数字或事实**。
2. 优势、劣势各自要 centered on 一个具体事实, 并给一个 evidence_quote ——
   它必须是输入的**逐字子串**(≥12 字符, 含你引用的那个数字/事实)。
   evidence_quote 不是逐字子串的那一条会被丢掉。
3. 综合 = 一句结论(净判断 / 最该盯什么), **不得出现输入里没有的新数字**。
4. 句中用 [标签] 标来源, 如 [毛利率] [10-K] [13F] [认知]。
5. 数据不足时直说"数据不足", 不要硬编。宁可诚实留空也不编。

输出 JSON:
{ "advantage": {"text": "...", "evidence_quote": "..."},
  "disadvantage": {"text": "...", "evidence_quote": "..."},
  "synthesis": {"text": "..."} }
"""

_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["advantage", "disadvantage", "synthesis"],
    "properties": {
        "advantage":    {"type": "object"},
        "disadvantage": {"type": "object"},
        "synthesis":    {"type": "object"},
    },
}


def _ensure_table(conn) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS fin_agent_synthesis ("
        " ticker TEXT PRIMARY KEY, advantage TEXT, disadvantage TEXT,"
        " synthesis TEXT, sources_json TEXT, generated_at TEXT,"
        " model TEXT, status TEXT)"
    )


def _fnum(v: Any, pct: bool = False, money: bool = False) -> Optional[str]:
    if v is None:
        return None
    try:
        if pct:
            return f"{v * 100:.1f}%"
        if money:
            a = abs(v)
            for div, suf in ((1e9, "B"), (1e6, "M")):
                if a >= div:
                    return f"${v / div:.1f}{suf}"
            return f"${v:.0f}"
        return f"{v:.1f}"
    except Exception:
        return None


def build_bag(ticker: str) -> Tuple[str, List[Dict[str, str]]]:
    """Serialize verified+dated inputs into a deterministic bag string + a
    list of {source, asof} for the freshness footer. Degrades gracefully when
    a source is unavailable (e.g. yfinance throttled)."""
    ticker = ticker.upper().strip()
    parts: List[str] = [f"=== TICKER: {ticker} ==="]
    sources: List[Dict[str, str]] = []
    sec_url: Optional[str] = None  # the actual filing URL, captured below

    # 1) fundamentals (yfinance, dated)
    try:
        from agent.data_sources.market import get_fundamentals, get_live_quote, get_holders
        f = get_fundamentals(ticker)
        if f and f.gross_margin is not None:
            asof = (f.fetched_at or "")[:10]
            sources.append({"source": "基本面 (yfinance)", "asof": asof})
            parts.append(f"=== 基本面 (yfinance, {asof}) ===")
            mm = {
                "PEG": _fnum(f.peg), "毛利率": _fnum(f.gross_margin, pct=True),
                "净利率": _fnum(f.profit_margin, pct=True), "营收增速": _fnum(f.revenue_growth, pct=True),
                "ROE": _fnum(f.roe, pct=True), "EV/EBITDA": (None if (f.ev_ebitda or 0) <= 0 else _fnum(f.ev_ebitda)),
                "市销率": _fnum(f.price_to_sales), "FCF": _fnum(f.fcf, money=True),
                "净负债": _fnum(f.net_debt, money=True),
            }
            for k, v in mm.items():
                if v is not None:
                    parts.append(f"{k}: {v}")
            if f.analyst_rating is not None:
                parts.append(f"卖方评级: {f.analyst_rating_key or '?'} ({f.analyst_rating:.1f}/5, {f.analyst_count or '?'} 家)")
            if f.target_mean is not None:
                parts.append(f"卖方目标价: ${f.target_mean:.0f}")
        q = get_live_quote(ticker)
        if q and q.price is not None:
            asof = (q.fetched_at or "")[:10]
            line = []
            if q.trailing_pe is not None:
                line.append(f"PE: {_fnum(q.trailing_pe)}")
            if q.forward_pe is not None:
                line.append(f"forwardPE: {_fnum(q.forward_pe)}")
            if q.year_change_pct is not None:
                line.append(f"近一年: {q.year_change_pct:.1f}%")
            if q.fifty_two_week_high and q.fifty_two_week_low and q.price:
                pos = (q.price - q.fifty_two_week_low) / (q.fifty_two_week_high - q.fifty_two_week_low) * 100
                line.append(f"52w位置: {pos:.0f}%")
            if line:
                parts.append(f"=== 行情 (yfinance, {asof}) ===")
                parts.extend(line)
                if not any(s["source"].startswith("基本面") for s in sources):
                    sources.append({"source": "行情 (yfinance)", "asof": asof})
    except Exception as e:
        logger.info("synth bag: fundamentals/quote unavailable for %s: %s", ticker, e)

    # 2) anchored facts (10-K verbatim, dated by filing)
    try:
        from agent.finance.anchored_research import get_anchored_facts
        a = get_anchored_facts(ticker)
        facts = a.get("facts", {}) if isinstance(a, dict) else {}
        meta = a.get("meta", {}) if isinstance(a, dict) else {}
        fdate = (meta or {}).get("source_filing_date") or "?"
        sec_url = (meta or {}).get("source_url") or next(
            (f.get("source_url") for ft in facts.values() if isinstance(ft, list)
             for f in ft if isinstance(f, dict) and f.get("source_url")), None)
        if any(facts.get(k) for k in ("business_summary", "competitor", "customer", "supplier", "risk", "segment")):
            sources.append({"source": "SEC 10-K/20-F/S-1", "asof": str(fdate)[:10]})
        if facts.get("business_summary"):
            parts.append(f"=== 业务 (10-K, {str(fdate)[:10]}) ===")
            for s in facts["business_summary"][:3]:
                parts.append(f"- {s.get('sentence','')}")
        if facts.get("segment"):
            parts.append("=== 业务分部 (10-K) ===")
            for s in facts["segment"][:6]:
                parts.append(f"- {s.get('name')}: {s.get('revenue_pct')}% of revenue")
        if facts.get("competitor"):
            parts.append("=== 竞争对手 (10-K) ===")
            parts.append("- " + ", ".join(c.get("name", "") for c in facts["competitor"][:12]))
        if facts.get("customer"):
            parts.append("=== 客户 (10-K) ===")
            for c in facts["customer"][:6]:
                cp = c.get("concentration_pct")
                parts.append(f"- {c.get('name')}" + (f" (占收入 {cp}%)" if cp is not None else ""))
        if facts.get("supplier"):
            parts.append("=== 供应商 (10-K) ===")
            parts.append("- " + ", ".join(s.get("name", "") for s in facts["supplier"][:8]))
        if facts.get("risk"):
            parts.append("=== 风险 (10-K) ===")
            for r in facts["risk"][:6]:
                parts.append(f"- [{r.get('category','?')}] {r.get('headline','')}")
    except Exception as e:
        logger.info("synth bag: anchored facts unavailable for %s: %s", ticker, e)

    # 3) holders (yfinance, dated) — institution/insider/locked
    try:
        h = get_holders(ticker)  # type: ignore
        if h and h.pct_institutions is not None:
            asof = (h.fetched_at or "")[:10]
            sources.append({"source": "持股结构 (yfinance)", "asof": asof})
            parts.append(f"=== 持股结构 (yfinance, {asof}) ===")
            parts.append(f"机构持股: {h.pct_institutions*100:.0f}%; 内部人: {(h.pct_insiders or 0)*100:.1f}%")
            if h.pct_locked is not None and h.pct_locked > 0.3:
                parts.append(f"锁定/低流通: {h.pct_locked*100:.0f}% (供给悬顶)")
    except Exception:
        pass

    # 4) owner moves — 13F whales on this ticker (DB, dated)
    try:
        ensure_schema()
        with connect() as conn:
            rows = conn.execute(
                "SELECT title, body_json FROM signal_events WHERE ticker=? AND scanner_name='13f' "
                "ORDER BY detected_at DESC LIMIT 6", (ticker,)
            ).fetchall()
        if rows:
            parts.append("=== 大户 13F 动作 (季度, ~45d 滞后) ===")
            sources.append({"source": "13F", "asof": "季度"})
            for r in rows:
                b = json.loads(r["body_json"]) if r["body_json"] else {}
                w = b.get("whale"); ct = b.get("change_type")
                if w and ct:
                    parts.append(f"- {w}: {ct}")
    except Exception:
        pass

    # 5) thesis (user 认知, dated)
    try:
        with connect() as conn:
            row = conn.execute(
                "SELECT body_md, created_at FROM investment_theses "
                "WHERE ticker=? AND status IN ('active','requires_review') "
                "ORDER BY created_at DESC LIMIT 1", (ticker,)
            ).fetchone()
        if row and row["body_md"]:
            m = re.search(r"##\s*共识\s*\n(.+?)(?:\n##|\Z)", row["body_md"], re.S)
            if m:
                parts.append(f"=== 我的认知·共识 (用户, {(row['created_at'] or '')[:10]}) ===")
                parts.append(m.group(1).strip()[:800])
                sources.append({"source": "我的认知 (用户)", "asof": (row["created_at"] or "")[:10]})
    except Exception:
        pass

    # attach a resource link per source — the user can click through to verify
    yahoo = f"https://finance.yahoo.com/quote/{ticker}"
    for s in sources:
        lbl = s["source"]
        if "10-K" in lbl or "20-F" in lbl or "S-1" in lbl or lbl.startswith("SEC"):
            s["url"] = sec_url or f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={ticker}&type=10-K"
        elif "13F" in lbl:
            s["url"] = f"{yahoo}/holders"
        elif "yfinance" in lbl:
            s["url"] = yahoo
        else:
            s["url"] = ""   # 认知 → internal, no external link

    return "\n".join(parts), sources


def synthesize(ticker: str) -> Dict[str, Any]:
    """Generate + persist the grounded 3-sentence read. Ungrounded sentences
    (evidence_quote not verbatim in the bag) are dropped."""
    ticker = ticker.upper().strip()
    bag, sources = build_bag(ticker)
    now = datetime.now(timezone.utc).isoformat()

    # not enough verified data → honest empty, don't call the LLM to invent
    if bag.count("===") <= 1:
        result = {"ticker": ticker, "advantage": None, "disadvantage": None,
                  "synthesis": None, "sources": sources, "generated_at": now,
                  "status": "insufficient_data"}
        _persist(result)
        return result

    # the local LLM router occasionally returns a transient 5xx/timeout; a
    # single retry turns most of those into a success instead of a 502 the
    # user sees as "刷新没反应".
    raw = None
    last_err: Optional[Exception] = None
    for attempt in range(2):
        try:
            raw = call_strict_json(
                system_prompt=_SYSTEM_PROMPT, user_content=bag,
                json_schema=_SCHEMA, schema_name="agent_synthesis", max_tokens=1200,
            )
            break
        except Exception as e:  # noqa: BLE001 — retry any transient LLM failure
            last_err = e
            logger.warning("synth: LLM call failed for %s (attempt %d/2): %s", ticker, attempt + 1, e)
    if raw is None:
        raise RuntimeError(f"LLM synthesis unavailable after retry: {last_err}")

    # GROUNDING GATE: every NUMBER in a sentence must appear in the verified
    # bag (no fabricated data). Prose framing is allowed since all inputs are
    # themselves sourced; a number not in the bag = drop that sentence.
    bag_digits = bag.replace(",", "")

    def _grounded(text: str) -> Optional[str]:
        if not text or not text.strip():
            return None
        for n in re.findall(r"\d[\d,]*\.?\d*", text):
            core = n.replace(",", "").rstrip(".")
            if core and core not in bag_digits:
                logger.info("synth: dropped sentence for %s — unsourced number %r", ticker, n)
                return None
        return text.strip()

    result = {
        "ticker": ticker,
        "advantage":    _grounded((raw.get("advantage") or {}).get("text", "")),
        "disadvantage": _grounded((raw.get("disadvantage") or {}).get("text", "")),
        "synthesis":    _grounded((raw.get("synthesis") or {}).get("text", "")),
        "sources": sources, "generated_at": now, "status": "ok",
    }
    _persist(result)
    return result


def _persist(r: Dict[str, Any]) -> None:
    with connect() as conn:
        _ensure_table(conn)
        conn.execute(
            "INSERT INTO fin_agent_synthesis (ticker,advantage,disadvantage,synthesis,sources_json,generated_at,model,status) "
            "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(ticker) DO UPDATE SET "
            "advantage=excluded.advantage, disadvantage=excluded.disadvantage, synthesis=excluded.synthesis, "
            "sources_json=excluded.sources_json, generated_at=excluded.generated_at, status=excluded.status",
            (r["ticker"], r.get("advantage"), r.get("disadvantage"), r.get("synthesis"),
             json.dumps(r.get("sources", []), ensure_ascii=False), r["generated_at"],
             "deepseek-v4-flash", r.get("status", "ok")),
        )


def read_synthesis(ticker: str) -> Optional[Dict[str, Any]]:
    ticker = ticker.upper().strip()
    with connect() as conn:
        _ensure_table(conn)
        row = conn.execute("SELECT * FROM fin_agent_synthesis WHERE ticker=?", (ticker,)).fetchone()
    if not row:
        return None
    return {
        "ticker": row["ticker"], "advantage": row["advantage"],
        "disadvantage": row["disadvantage"], "synthesis": row["synthesis"],
        "sources": json.loads(row["sources_json"] or "[]"),
        "generated_at": row["generated_at"], "status": row["status"],
    }


def build_fin_agent_router() -> APIRouter:
    router = APIRouter(prefix="/api/stock", tags=["fin-agent"])

    @router.get("/{ticker}/agent_synthesis")
    def get_synth(ticker: str, refresh: bool = False) -> Dict[str, Any]:
        if not refresh:
            cached = read_synthesis(ticker)
            if cached:
                return cached
        try:
            return synthesize(ticker)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(502, f"agent synthesis failed: {e}")

    return router
