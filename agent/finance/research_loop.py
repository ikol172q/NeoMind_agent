"""Disciplined IC deep-research loop — insider trigger → low-coverage filter →
anchored deep-dive → mechanism + conservative conviction → auto-sizing → thesis.

Scheduler-runnable. Five disciplined stages:

DISCOVER (deterministic): ``insider_buy_cluster`` with ``n_insiders >= N`` on
the PRICED universe, recent, not already researched — the selective FEW, deduped
vs existing theses. THEN a LOW-COVERAGE SMALL-CAP filter (Finnhub profile2 market
cap < ~$3B AND recommendation analyst count <= ~12): the edge lives in the
information crack, not in names 30 analysts already cover.

RESEARCH (just-in-time, per ONE name): insider details + price (DB) + Finnhub
fundamentals/news, PLUS crux facts from the anchored deep-dive — POST
/anchored/regenerate (~60-90s, triggers 10-K extraction) then GET /anchored,
folding the debt/business/risk/segment/competitor facts into the packet.

SYNTHESIZE (LLM via local router): a DISCIPLINED prompt — mechanism (who is
mispricing + who won't correct it + the catalyst insiders are betting on),
honest knowledge gaps, invalidation, retirement (exit once the info goes
public). Conviction is CONSERVATIVE: any admitted gap caps it at MED. Uses ONLY
packet + anchored facts (anti-hallucination enforced in-prompt).

THESIS (/api/theses): body_md with the five disciplined sections
机制 / 认知缺口 / Invalidation / 退役 / Sizing. The Sizing section is filled from
GET /api/portfolio/size_position (risk-budget vs ¼-Kelly vs single-name cap).
Create is verified to return missing_sections == []. → your human gate.

Run:  python -m agent.finance.research_loop --limit 1
(anchored is slow, so each run deep-researches only `limit` names; candidates
that yield no crux facts are skipped gracefully, never crash the run.)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from agent.finance.persistence import connect
from agent.data_sources.finnhub_news import get_company_news

_DASH = "http://127.0.0.1:8001"
_ROUTER = "http://127.0.0.1:8000/v1"
_MODEL = "deepseek-v4-flash"  # glm-* are 429/quota-exhausted on the router (2026-07)
_FINNHUB = "https://finnhub.io/api/v1"

# Low-coverage small-cap gate (the information-crack edge). profile2's
# marketCapitalization is in $millions, so <$3B ⇒ < 3000.
_MAX_MARKET_CAP_M = 3000.0
_MAX_ANALYSTS = 12
# Crux fact types pulled from the anchored deep-dive into the packet.
_CRUX_FACT_TYPES = ("debt", "business_summary", "risk", "segment", "competitor")
# Anchored regenerate runs every 10-K extractor back-to-back (~60-100s observed).
_ANCHORED_TIMEOUT = 220.0


def _fk() -> str:
    return (os.getenv("FINNHUB_API_KEY") or "").strip()


def _http_json(url: str, data: Optional[dict] = None, headers: Optional[dict] = None,
               timeout: float = 30) -> Any:
    req = urllib.request.Request(
        url, data=(json.dumps(data).encode() if data is not None else None),
        headers=headers or {}, method=("POST" if data is not None else "GET"))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _finnhub(path: str) -> Any:
    k = _fk()
    if not k:
        return None
    sep = "&" if "?" in path else "?"
    try:
        return _http_json(f"{_FINNHUB}{path}{sep}token={k}", timeout=12)
    except Exception:
        return None


def _parse_json(txt: str) -> Optional[dict]:
    try:
        return json.loads(txt)
    except Exception:
        m = re.search(r"\{.*\}", txt, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


def _analyst_count(rec: Any) -> Optional[int]:
    """Total analysts in the most-recent recommendation period. Returns None
    when Finnhub has NO recommendation rows — the caller treats that as
    zero-coverage (the ultimate information crack), not as missing data."""
    if not isinstance(rec, list) or not rec:
        return None
    r0 = rec[0]  # Finnhub returns most-recent period first
    return sum(int(r0.get(k) or 0)
               for k in ("strongBuy", "buy", "hold", "sell", "strongSell"))


def _low_coverage(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep only small-cap, thinly-covered names. Market cap is the HARD gate
    (must be present AND < ~$3B); analyst count uses recommendation (missing ⇒
    treated as 0 = zero coverage). Attaches market_cap_m + n_analysts."""
    kept: List[Dict[str, Any]] = []
    for c in candidates:
        t = c["ticker"]
        prof = _finnhub(f"/stock/profile2?symbol={urllib.parse.quote(t)}")
        mcap = (prof or {}).get("marketCapitalization")
        if not isinstance(mcap, (int, float)) or mcap <= 0 or mcap >= _MAX_MARKET_CAP_M:
            continue  # can't confirm small-cap ⇒ fail closed (no edge claim)
        rec = _finnhub(f"/stock/recommendation?symbol={urllib.parse.quote(t)}")
        n_an = _analyst_count(rec)
        n_an_eff = 0 if n_an is None else n_an
        if n_an_eff > _MAX_ANALYSTS:
            continue
        kept.append({**c, "market_cap_m": round(float(mcap), 1),
                     "n_analysts": n_an_eff})
    return kept


def discover(min_insiders: int = 5, lookback_days: int = 90) -> List[Dict[str, Any]]:
    """Deterministic insider trigger → dedup vs existing theses → low-coverage
    small-cap filter. Returns the thinly-covered few worth deep-researching."""
    since = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).date().isoformat()
    with connect() as c:
        rows = c.execute(
            """SELECT ticker,
                      MAX(CAST(json_extract(body_json,'$.n_insiders') AS INT)) mi,
                      MAX(json_extract(body_json,'$.filing_date')) latest,
                      (SELECT COUNT(*) FROM market_data_daily m WHERE m.symbol=signal_events.ticker) pr
               FROM signal_events
               WHERE signal_type='insider_buy_cluster'
                 AND ticker IN (SELECT DISTINCT symbol FROM market_data_daily)
                 AND CAST(json_extract(body_json,'$.n_insiders') AS INT) >= ?
                 AND json_extract(body_json,'$.filing_date') >= ?
               GROUP BY ticker HAVING pr >= 250
               ORDER BY latest DESC""", (min_insiders, since)).fetchall()
    theses = _http_json(f"{_DASH}/api/theses") or []
    tl = theses if isinstance(theses, list) else theses.get("theses", [])
    seen = {t.get("ticker") for t in tl}
    raw = [{"ticker": r[0], "n_insiders": r[1], "latest": (r[2] or "")[:10]}
           for r in rows if r[0] not in seen]
    return _low_coverage(raw)


def _fetch_anchored_crux(ticker: str) -> tuple[Dict[str, Any], Optional[Dict[str, Any]], int]:
    """Deep-dive: POST /anchored/regenerate (triggers 10-K extraction, ~60-100s)
    then GET /anchored, folding the crux facts (debt/business/risk/segment/
    competitor) into a compact, cited form. Graceful — any failure ⇒ ({}, None, 0).

    Each fact keeps its real content field(s) + verbatim evidence_quote + source
    section (anti-hallucination: the LLM must reason over THESE bytes, not invent).
    """
    q = urllib.parse.quote(ticker)
    try:
        _http_json(f"{_DASH}/api/stock/{q}/anchored/regenerate", data={},
                   headers={"Content-Type": "application/json"},
                   timeout=_ANCHORED_TIMEOUT)
    except Exception:
        pass  # partial/failed regen — still try to read whatever got cached
    try:
        anc = _http_json(f"{_DASH}/api/stock/{q}/anchored", timeout=30)
    except Exception:
        return {}, None, 0
    facts = (anc or {}).get("facts") or {}
    meta = (anc or {}).get("meta") or None
    drop = {"fact_id", "confidence", "requires_reextract", "is_stale",
            "polarity", "source_url", "ticker"}
    compact: Dict[str, Any] = {}
    n = 0
    for ft in _CRUX_FACT_TYPES:
        rows = []
        for it in (facts.get(ft) or [])[:8]:
            row = {k: v for k, v in it.items() if k not in drop}
            for tk in ("evidence_quote", "sentence", "headline"):
                if isinstance(row.get(tk), str) and len(row[tk]) > 320:
                    row[tk] = row[tk][:320] + "…"
            rows.append(row)
        if rows:
            compact[ft] = rows
            n += len(rows)
    return compact, meta, n


def fetch_packet(ticker: str) -> Dict[str, Any]:
    """Just-in-time: assemble ONLY real data for this one name — insider + price
    (DB), Finnhub fundamentals/news, PLUS anchored 10-K crux facts."""
    with connect() as c:
        ins = c.execute(
            """SELECT json_extract(body_json,'$.company'), json_extract(body_json,'$.trade_date'),
                      json_extract(body_json,'$.filing_date'), json_extract(body_json,'$.n_insiders'),
                      json_extract(body_json,'$.value_usd'), json_extract(body_json,'$.price')
               FROM signal_events WHERE ticker=? AND signal_type='insider_buy_cluster'
               ORDER BY json_extract(body_json,'$.filing_date') DESC LIMIT 6""", (ticker,)).fetchall()
        px = c.execute("SELECT trade_date, close FROM market_data_daily WHERE symbol=? "
                       "ORDER BY trade_date DESC LIMIT 1", (ticker,)).fetchone()
        hl = c.execute("SELECT ROUND(MAX(close),2), ROUND(MIN(close),2) FROM market_data_daily "
                       "WHERE symbol=? AND trade_date >= date('now','-365 days')", (ticker,)).fetchone()
    profile = _finnhub(f"/stock/profile2?symbol={urllib.parse.quote(ticker)}")
    metric = _finnhub(f"/stock/metric?symbol={urllib.parse.quote(ticker)}&metric=all")
    news = get_company_news(ticker, days=21, limit=8) or []
    anchored_facts, anchored_meta, n_crux = _fetch_anchored_crux(ticker)
    return {
        "ticker": ticker,
        "insider_cluster_events": [
            {"company": i[0], "trade_date": i[1], "filing_date": i[2],
             "n_insiders": i[3], "value_usd": i[4], "buy_price": i[5]} for i in ins],
        "price_now": (px[1] if px else None), "price_date": (px[0] if px else None),
        "week52_high": (hl[0] if hl else None), "week52_low": (hl[1] if hl else None),
        "finnhub_profile": profile,
        "finnhub_metrics": ((metric or {}).get("metric") if metric else None),
        "recent_news": [{"headline": n.get("headline"), "source": n.get("source"),
                         "url": n.get("url")} for n in news[:8]],
        # Anchored 10-K deep-dive crux facts (cited, verbatim-gated).
        "anchored_facts": anchored_facts,
        "anchored_source": (anchored_meta or {}).get("source_url"),
        "anchored_filing_date": (anchored_meta or {}).get("source_filing_date"),
        "n_crux_facts": n_crux,
    }


_PROMPT = """你是纪律严明的 IC（投资委员会）深研分析师，做一个小盘、低分析师覆盖的名字。
触发信号 = insider_buy_cluster（多名内部人集群买入）。**只用下面提供的真实数据（含
anchored 10-K 抽取的事实与其 evidence_quote），绝不编造任何事实、数字、新闻或引用。**

写作纪律：
1. 每个论断必须能追溯到提供的数据；数据里没有的，写"无数据"，绝不脑补。
2. **机制（mechanism）**才是 edge——不是"内部人买了所以看涨"这种表面信号。必须讲清三件事：
   (a) 谁在错价这个名字、为什么（低覆盖/被忽视/错杀/结构性卖压）；
   (b) 谁本该来纠正错价却没来（为什么套利/分析师/大资金缺席）；
   (c) 内部人在押的那个具体催化剂是什么（用 anchored 业务/债务/风险事实支撑）。
3. **认知缺口（knowledge_gap）**：诚实列出你还不知道、但决定这笔投资成败的关键未知。
4. **retirement（退役）**：这条 edge 什么时候失效——通常是信息公开（催化剂兑现/被券商覆盖/
   财报揭晓）之后 edge 消失，该退出。
5. **conviction 必须保守**：LOW=机制不成立或基本面缺失；HIGH 三条缺一不可（机制清晰完整 +
   无重大数据缺口 + anchored 有明确催化支撑）；**只要你在 knowledge_gap 里承认任何缺口/未知，
   conviction 最高只能 MED**。宁保守勿吹。conviction 只能是 LOW / MED / HIGH。
6. 严格输出 JSON，无多余文字。

数据：
{packet}

输出 JSON：
{{"conviction":"LOW|MED|HIGH",
  "mechanism_md":"机制：谁在错价+为什么 / 谁不来纠正 / 内部人押的催化剂（引 anchored 事实）",
  "knowledge_gap_md":"诚实的关键未知（缺哪些数据、哪些假设未验证）",
  "invalidation_triggers":["具体可检验的证伪条件1","2"],
  "retirement_md":"信息公开即退：这条 edge 何时因信息扩散而消失、该退出"}}"""


def synthesize(packet: Dict[str, Any]) -> Dict[str, Any]:
    import time as _t
    from urllib.error import HTTPError
    body = {"model": _MODEL, "temperature": 0.2,
            "messages": [{"role": "user",
                          "content": _PROMPT.format(packet=json.dumps(packet, ensure_ascii=False, default=str))}]}
    last = "unknown"
    for attempt in range(4):
        try:
            resp = _http_json(f"{_ROUTER}/chat/completions", data=body,
                              headers={"Content-Type": "application/json", "Authorization": "Bearer dummy"},
                              timeout=90)
            txt = resp["choices"][0]["message"]["content"]
            parsed = _parse_json(txt)
            if parsed and parsed.get("mechanism_md"):
                return parsed
            last = f"parse-fail: {txt[:400]}"
            break
        except HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code == 429:
                _t.sleep(3 * (attempt + 1))
                continue
            break
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
            break
    return {"conviction": "LOW", "mechanism_md": "", "knowledge_gap_md": "",
            "invalidation_triggers": [], "retirement_md": "",
            "_synthesize_error": last}


def _norm_conviction(conv: str) -> str:
    """Normalize LLM conviction to the LOW/MED/HIGH vocabulary size_position
    expects (MEDIUM/M → MED)."""
    c = (conv or "").strip().upper()
    if c.startswith("MED") or c == "M":
        return "MED"
    if c in ("LOW", "HIGH"):
        return c
    return "MED"


def _derive_invalidation(packet: Dict[str, Any]) -> tuple[Optional[float], Optional[float], str]:
    """Deterministic price stop for sizing (must be BELOW entry). Priority, all
    tied to real data: (1) insider cluster cost line if insiders bought BELOW
    current → a fall back under their entry breaks the thesis; (2) else the
    52-week low → a break to new lows; (3) else a 20% technical stop."""
    entry = packet.get("price_now")
    try:
        entry = float(entry)
    except (TypeError, ValueError):
        return None, None, ""
    if entry <= 0:
        return None, None, ""
    bps = [float(e["buy_price"]) for e in packet.get("insider_cluster_events", [])
           if e.get("buy_price") not in (None, "")]
    insider_avg = (sum(bps) / len(bps)) if bps else None
    lo = packet.get("week52_low")
    lo = float(lo) if isinstance(lo, (int, float)) else None
    if insider_avg and insider_avg < entry:
        inval, basis = round(insider_avg, 2), f"跌回内部人集群成本线 ~${round(insider_avg, 2)}"
    elif lo and lo < entry:
        inval, basis = round(lo, 2), f"跌破 52 周低 ${round(lo, 2)}"
    else:
        inval, basis = round(entry * 0.80, 2), f"20% 技术止损 ${round(entry * 0.80, 2)}"
    if inval >= entry:  # guard: sizing requires stop strictly below entry
        inval, basis = round(entry * 0.80, 2), f"20% 技术止损 ${round(entry * 0.80, 2)}"
    return round(entry, 2), inval, basis


def _sizing_md(ticker: str, entry: Optional[float], inval: Optional[float],
               basis: str, conv: str) -> str:
    """Fill the Sizing section from GET /api/portfolio/size_position."""
    if entry is None or inval is None:
        return "- 无现价/失效价，无法计算仓位（缺数据）。"
    q = urllib.parse.quote(ticker)
    url = (f"{_DASH}/api/portfolio/size_position?ticker={q}&entry_price={entry}"
           f"&invalidation_price={inval}&conviction={urllib.parse.quote(conv)}")
    try:
        s = _http_json(url, timeout=15)
    except Exception as e:
        return f"- size_position 调用失败：{type(e).__name__}（entry ${entry} / 失效 ${inval}）。"
    if not isinstance(s, dict) or s.get("error"):
        return f"- size_position 返回错误：{(s or {}).get('error')}（entry ${entry} / 失效 ${inval}）。"
    sp = s.get("suggested_position") or {}
    return (
        f"- 现价(entry) **${entry}** · 失效价(stop) **${inval}**（{basis}）· "
        f"止损距离 {s.get('stop_distance_pct')}%\n"
        f"- conviction **{s.get('conviction')}** → 建议仓位 **${sp.get('dollars')}** "
        f"（{sp.get('shares')} 股, 占账户 {sp.get('pct_of_account')}%）\n"
        f"- 触止损亏损 ${sp.get('dollar_risk_at_stop')}（账户 {sp.get('risk_pct_of_account')}%）· "
        f"binding = **{s.get('binding_constraint')}**（min of "
        f"{s.get('candidates_dollars')}）\n"
        f"- account_value ${s.get('account_value')}（{s.get('account_value_source')}）· 只建议不下单")


def create_thesis(ticker: str, research: Dict[str, Any],
                  packet: Dict[str, Any]) -> tuple[Optional[str], List[str]]:
    conv = _norm_conviction(research.get("conviction", "LOW"))
    trigs = research.get("invalidation_triggers", []) or []
    mechanism = research.get("mechanism_md", "").strip() or "（synthesize 未产出机制）"
    gap = research.get("knowledge_gap_md", "").strip() or "（未列出——视为高缺口，conviction 应保守）"
    retirement = research.get("retirement_md", "").strip() or "信息公开（催化兑现/被覆盖/财报揭晓）后 edge 消失即退出。"
    entry, inval, basis = _derive_invalidation(packet)
    sizing = _sizing_md(ticker, entry, inval, basis, conv)

    n_crux = packet.get("n_crux_facts", 0)
    mcap = packet.get("finnhub_profile", {}).get("marketCapitalization") if isinstance(packet.get("finnhub_profile"), dict) else None
    inval_lines = "\n".join(f"- {t}" for t in trigs) if trigs else "- （未产出可检验触发）"
    body_md = (
        f"# {ticker} — insider cluster · 低覆盖小盘深研 (auto IC)\n\n"
        f"**Conviction: {conv}**  ·  市值 ${round(mcap,1) if isinstance(mcap,(int,float)) else '?'}M  ·  "
        f"anchored crux facts: {n_crux}  ·  新闻: {len(packet.get('recent_news', []))} 条\n\n"
        f"## 机制\n{mechanism}\n\n"
        f"## 认知缺口\n{gap}\n\n"
        f"## Invalidation\n{inval_lines}\n"
        f"- 价格止损：{basis}\n\n"
        f"## 退役\n{retirement}\n\n"
        f"## Sizing\n{sizing}\n\n"
        f"---\n*auto by research_loop · 源: signal_events + market_data_daily + Finnhub + "
        f"anchored 10-K({packet.get('anchored_filing_date') or 'n/a'}) · size_position · "
        f"{datetime.now(timezone.utc).isoformat()}*")
    r = _http_json(f"{_DASH}/api/theses",
                   data={"ticker": ticker, "body_md": body_md,
                         "supporting_signal_types": ["insider_buy_cluster"]},
                   headers={"Content-Type": "application/json"})
    if not isinstance(r, dict):
        return None, ["<non-dict response>"]
    return (r.get("thesis_id") or r.get("id")), (r.get("missing_sections") or [])


def run(limit: int = 1, min_insiders: int = 5,
        max_attempts: Optional[int] = None) -> List[Dict[str, Any]]:
    """Deep-research candidates until `limit` disciplined theses are produced.
    Because the anchored deep-dive is slow (~60-100s/name), attempts are bounded
    by `max_attempts` (default limit+3). A candidate that yields NO crux facts,
    or whose synthesis fails, is SKIPPED gracefully — never crashes the run."""
    cands = discover(min_insiders=min_insiders)
    cap = max_attempts if max_attempts is not None else (limit + 3)
    print(f"discover: {len(cands)} low-coverage candidates "
          f"(insider n>={min_insiders}, mcap<${_MAX_MARKET_CAP_M:.0f}M, analysts<={_MAX_ANALYSTS}); "
          f"target {limit} thesis, ≤{cap} attempts")
    out: List[Dict[str, Any]] = []
    attempts = 0
    for c in cands:
        if len(out) >= limit or attempts >= cap:
            break
        attempts += 1
        t = c["ticker"]
        print(f"  [{attempts}] deep-research {t} (n_insiders={c['n_insiders']}, "
              f"mcap=${c.get('market_cap_m')}M, analysts={c.get('n_analysts')}, filed {c['latest']})...")
        try:
            pk = fetch_packet(t)
            if pk.get("n_crux_facts", 0) == 0:
                print(f"    → skip: 0 anchored crux facts (no deep substrate)")
                continue
            res = synthesize(pk)
            if not res.get("mechanism_md"):
                print(f"    → skip: synthesize produced no mechanism "
                      f"({res.get('_synthesize_error', 'empty')})")
                continue
            tid, missing = create_thesis(t, res, pk)
            rec = {"ticker": t, "conviction": _norm_conviction(res.get("conviction")),
                   "thesis_id": tid, "n_crux_facts": pk.get("n_crux_facts"),
                   "market_cap_m": c.get("market_cap_m"), "n_analysts": c.get("n_analysts"),
                   "missing_sections": missing}
            out.append(rec)
            print(f"    → thesis_id={tid} conviction={rec['conviction']} "
                  f"crux={rec['n_crux_facts']} missing_sections={missing}")
        except Exception as e:
            print(f"    → skip: {type(e).__name__}: {e}")
            continue
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=1, help="target # disciplined theses to produce")
    ap.add_argument("--min-insiders", type=int, default=5)
    ap.add_argument("--max-attempts", type=int, default=None,
                    help="cap on deep-dive attempts (default limit+3)")
    a = ap.parse_args()
    print(json.dumps(run(a.limit, a.min_insiders, a.max_attempts),
                     ensure_ascii=False, indent=2, default=str))
