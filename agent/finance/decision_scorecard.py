"""Decision Scorecard — synthesize every signal into one clear read:
should I buy / add / hold / trim / sell / watch / pass, and how strongly.

User's north star (2026-05-22): every signal in the dashboard must ladder
up to a clear "should I, and to what degree, buy/sell/hold" answer. This
module is that synthesis layer. It is RULE-BASED (deterministic, no LLM,
no hallucination) so the logic is auditable and the user can adjust weights.

IMPORTANT — this is a SIGNAL SUMMARY, not financial advice. It describes
what the signals say + applies the user's own IPS rules, then suggests a
lean. The decision is always the user's (consistent with their IPS, which
values their own judgment + falsifiable thesis).

Four lenses (each → a sub-read + score), combined → suggested lean:

  ① 质量门槛 Quality gate   — is the business good? (FCF/ROIC/margins)
       → a GATE: if it fails, the overall is capped at watch/avoid.
       (Pending fundamental-data integration; currently neutral + flagged.)
  ② 持仓 Positioning        — is smart money behind it? (13F long whales
       net + 13D activist + insider cluster buys)
  ③ 估值 Valuation/entry    — cheap or expensive? (forward P/E level;
       history-percentile pending)
  ④ 契合 Fit (your IPS)     — does adding violate concentration / circle?

Each lens explanation doubles as the "?" help content the UI surfaces.
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _fmt_money(v: Any) -> str:
    """Compact human-readable money (e.g. 1.2T / 3.4B / 567M)."""
    try:
        v = float(v)
    except Exception:
        return str(v)
    s = "-" if v < 0 else ""
    a = abs(v)
    if a >= 1e12: return f"{s}${a/1e12:.1f}T"
    if a >= 1e9:  return f"{s}${a/1e9:.1f}B"
    if a >= 1e6:  return f"{s}${a/1e6:.0f}M"
    if a >= 1e3:  return f"{s}${a/1e3:.0f}K"
    return f"{s}${a:.0f}"


# Shared yfinance .info fetch — quality + valuation both need it. Fetch once,
# cache briefly (15 min), retry once on a cold/empty miss (yfinance is flaky
# right after a process restart). Avoids double HTTP + the "拉取失败" flash.
import time as _time
_YF_INFO_CACHE: Dict[str, tuple] = {}   # tk -> (ts, info)
_YF_INFO_TTL = 900.0


def _yf_info(ticker: str) -> Dict[str, Any]:
    tk = ticker.upper()
    hit = _YF_INFO_CACHE.get(tk)
    if hit and (_time.monotonic() - hit[0]) < _YF_INFO_TTL and hit[1]:
        return hit[1]
    info: Dict[str, Any] = {}
    for attempt in range(2):
        try:
            import yfinance as yf
            info = yf.Ticker(tk).info or {}
        except Exception as exc:
            logger.debug("yfinance .info failed for %s (attempt %d): %s", tk, attempt, exc)
            info = {}
        # treat a dict with no usable fundamentals as a miss worth retrying
        if info.get("freeCashflow") is not None or info.get("forwardPE") is not None \
           or info.get("trailingPE") is not None or info.get("profitMargins") is not None:
            break
        _time.sleep(0.4)
    if info:
        _YF_INFO_CACHE[tk] = (_time.monotonic(), info)
    return info


# ── "?" help content — how to USE each signal toward the decision ───
# Surfaced verbatim in the UI tooltips so the user learns the framework.
LENS_HELP = {
    "quality": (
        "生意质量门槛 (FCF/ROIC/利润率/净债). 长线收益的根本驱动. "
        "差的生意 → 无论谁持有都回避; 这是 gate, 不过关直接把结论封顶到'观望/回避'."
    ),
    "positioning": (
        "聪明钱是否在背后. 长线大师 13F 净买 + 13D 活动家举牌 + 内部人 cluster 买入. "
        "净买 → 支持加仓; 净卖 (高权重 whale) → 谨慎. 量化基金 (低权重) 的 13F 是噪音, 已降权."
    ),
    "valuation": (
        "vs 自身/同业的估值. 过热 → 等回调或减仓; 便宜 → 加仓时点好. "
        "注: 当前用 forward P/E 水平, 历史百分位待接入; 周期股 (内存等) P/E 会失真."
    ),
    "fit": (
        "是否契合你 IPS. 单票 >30% / sector >65% → 即使信号好也别加 (集中度). "
        "圈外资产 (期权/做空/小盘 illiquid 等) → pass."
    ),
    "overall": (
        "综合 4 个 lens 的信号摘要 → 一个动作倾向 + 程度. "
        "这是【信号摘要, 不是买卖建议】— 决策永远是你的. 质量门槛不过关会封顶."
    ),
}


# ── Lens ②: Positioning (smart money) ───────────────────────────────


def _positioning(ticker: str) -> Dict[str, Any]:
    """Aggregate smart-money positioning from signal_events.

    - 13F: net conviction among QUALITY whales (weight>=1.0, long/medium),
      NEW positions weighted 1.5x. Quant funds (weight 0.3) down-weighted.
    - insider_form4: open-market BUYS (the scanner already filters sells).
    - 13D/13G: activist filings (when that scanner lands).
    """
    from agent.finance.persistence import connect
    from agent.finance.regime.scanners.whale_scanner import WHALES_BY_KEY

    tk = ticker.upper()
    with connect() as conn:
        rows = conn.execute(
            "SELECT scanner_name, signal_type, body_json, source_timestamp, source_url "
            "  FROM signal_events "
            " WHERE ticker = ? AND scanner_name IN ('13f','insider_form4','13d') "
            " ORDER BY source_timestamp DESC",
            (tk,),
        ).fetchall()

    # 13F: keep latest action per whale + its source filing (provenance)
    whale_latest: Dict[str, str] = {}
    whale_detail: Dict[str, Dict[str, Any]] = {}   # wk -> {action, date, url}
    insider_buys = 0
    insider_src: List[str] = []
    activist = []           # all 13D filers (for display/provenance)
    activist_recent = []    # only ≤400d old → counts as live conviction
    activist_detail: List[Dict[str, Any]] = []
    from datetime import datetime, timezone, timedelta
    activist_cutoff = (datetime.now(timezone.utc) - timedelta(days=400)).date().isoformat()
    for r in rows:
        try:
            b = json.loads(r["body_json"]) if r["body_json"] else {}
        except Exception:
            b = {}
        if r["scanner_name"] == "13f":
            wk = b.get("whale_key"); ct = b.get("change_type")
            if wk and ct and wk not in whale_latest:
                whale_latest[wk] = ct
                whale_detail[wk] = {
                    "action": ct,
                    "date": (r["source_timestamp"] or "")[:10],
                    "url": r["source_url"],
                }
        elif r["scanner_name"] == "insider_form4":
            insider_buys += 1
            if r["source_url"]:
                insider_src.append(r["source_url"])
        elif r["scanner_name"] == "13d":
            filer = b.get("filer") or b.get("whale") or "activist"
            fdate = b.get("file_date") or (r["source_timestamp"] or "")[:10]
            activist.append(filer)
            if fdate >= activist_cutoff:
                activist_recent.append(filer)
            activist_detail.append({
                "whale": f"🏴 {filer}",
                "whale_key": "13d",
                "action": "increase" if (b.get("form") or "").endswith("/A") else "new",
                "date": fdate,
                "url": r["source_url"],
                "weight": 1.0 if fdate >= activist_cutoff else 0.3,
            })

    def wt(wk: str) -> float:
        return WHALES_BY_KEY.get(wk, {}).get("signal_weight", 1.0)

    GOOD = {k for k, w in WHALES_BY_KEY.items()
            if w.get("signal_weight", 1) >= 1.0 and w.get("horizon") in ("long", "medium")}
    conv = 0.0
    buyers, sellers = [], []
    for wk, ct in whale_latest.items():
        w = wt(wk)
        is_good = wk in GOOD
        # quant/low-weight contribute little
        if ct == "new":
            conv += (w * 1.5 if is_good else w * 0.3)
            buyers.append(wk)
        elif ct == "increase":
            conv += (w if is_good else w * 0.2)
            buyers.append(wk)
        elif ct in ("decrease", "exit"):
            conv -= (w if is_good else w * 0.2)
            sellers.append(wk)

    # insider + activist nudges. Only RECENT (≤400d) 13D counts as live
    # activist conviction; older campaigns are surfaced as context but don't
    # move the score (a 2023 13D ≠ "an activist is pushing this today").
    if insider_buys >= 2:
        conv += 1.0
    elif insider_buys == 1:
        conv += 0.5
    if activist_recent:
        conv += 1.0

    # Map conv → score -2..+2
    if conv >= 3:    score = 2
    elif conv >= 1:  score = 1
    elif conv > -1:  score = 0
    elif conv > -3:  score = -1
    else:            score = -2

    activist_tag = ""
    if activist_recent:
        activist_tag = " + 活动家举牌"
    elif activist:
        activist_tag = " (有历史 13D 控制方)"
    read = {
        2:  "强正 — 多家长线大师在买" + ("+ 内部人买入" if insider_buys else ""),
        1:  "偏正 — 聪明钱净买入",
        0:  "中性/分歧 — 买卖参半或无信号",
        -1: "偏负 — 聪明钱净卖出",
        -2: "强负 — 长线大师在撤",
    }[score] + activist_tag

    # Per-whale drill-down detail (whale name + action + date + filing URL)
    def whale_name(wk: str) -> str:
        return WHALES_BY_KEY.get(wk, {}).get("short", wk)
    detail = []
    for wk, d in whale_detail.items():
        detail.append({
            "whale": whale_name(wk),
            "whale_key": wk,
            "action": d["action"],
            "date": d["date"],
            "url": d["url"],
            "weight": wt(wk),
        })
    detail.extend(activist_detail)  # 🏴 13D filers alongside 13F whales
    detail.sort(key=lambda x: (x["action"] not in ("new", "increase"), -x["weight"]))

    # Provenance sources: distinct SEC 13F filing URLs + insider + activist
    sources = []
    seen_urls = set()
    for d in detail:
        if d["url"] and d["url"] not in seen_urls:
            seen_urls.add(d["url"])
            is_13d = d.get("whale_key") == "13d"
            kind = "13d" if is_13d else "sec_13f"
            form = "13D" if is_13d else "13F"
            sources.append({
                "label": f"{d['whale']} {form} ({d['action']}, {d['date']})",
                "url": d["url"], "kind": kind,
            })
    for u in insider_src[:3]:
        if u not in seen_urls:
            seen_urls.add(u)
            sources.append({"label": "Insider Form 4", "url": u, "kind": "insider"})

    return {
        "score": score,
        "read": read,
        "conv_raw": round(conv, 1),
        "buyers": sorted(buyers),
        "sellers": sorted(sellers),
        "insider_buys": insider_buys,
        "activist": activist,
        "detail": detail,
        "sources": sources,
    }


# ── Lens ③: Valuation ───────────────────────────────────────────────


def _valuation(ticker: str) -> Dict[str, Any]:
    """Rough valuation read from live quote forward/trailing P/E.
    History-percentile + sector-relative is a TODO (flagged)."""
    info = _yf_info(ticker)
    fpe = info.get("forwardPE")
    tpe = info.get("trailingPE")

    from datetime import datetime, timezone
    # Data origin = yfinance (Yahoo). Verification link → stockanalysis.com
    # (Yahoo blocks automated validation; stockanalysis HEAD-validates + is
    # an authoritative free statistics source to cross-check the P/E).
    verify_url = f"https://stockanalysis.com/stocks/{ticker.upper()}/statistics/"
    val_sources = [{
        "label": f"P/E via yfinance (源 Yahoo) · 取于 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} · 核对 stockanalysis.com",
        "url": verify_url, "kind": "yfinance",
    }]
    pe = fpe or tpe
    if pe is None:
        return {"score": 0, "read": "估值数据缺失 (无 P/E)", "pe": None, "pe_kind": None, "sources": val_sources}
    try:
        pe = float(pe)
    except Exception:
        return {"score": 0, "read": "估值数据无法解析", "pe": None, "pe_kind": None, "sources": val_sources}

    # Sector-agnostic, coarse. Flagged as rough.
    if pe <= 0:      score, label = 0, f"P/E 负 ({pe:.0f}) — 亏损/周期, 单看 P/E 无意义"
    elif pe < 15:    score, label = 2, f"便宜 (~{pe:.0f}x)"
    elif pe < 28:    score, label = 1, f"合理 (~{pe:.0f}x)"
    elif pe < 45:    score, label = 0, f"偏贵 (~{pe:.0f}x)"
    elif pe < 70:    score, label = -1, f"贵 (~{pe:.0f}x)"
    else:            score, label = -2, f"过热 (~{pe:.0f}x)"
    return {
        "score": score,
        "read": label + " ⚠️粗略, 历史百分位/同业对比待接入; 周期股失真",
        "pe": round(pe, 1),
        "pe_kind": "forward" if fpe else "trailing",
        "sources": val_sources,
    }


# ── Lens ④: Fit (IPS concentration) ─────────────────────────────────


def _fit(ticker: str) -> Dict[str, Any]:
    """Check against IPS sizing rules + current portfolio weight."""
    tk = ticker.upper()
    weight = 0.0
    held = False
    max_single = 0.30
    try:
        from agent.finance.positions import portfolio_summary
        ps = portfolio_summary()
        total = ps.get("total_value") or 0
        for row in ps.get("by_ticker", []):
            if (row.get("ticker") or "").upper() == tk:
                held = True
                mv = row.get("market_value") or row.get("value") or 0
                weight = (mv / total) if total else 0
                break
    except Exception as exc:
        logger.debug("fit portfolio lookup failed: %s", exc)
    try:
        from agent.finance.investment_philosophy import get_active
        p = get_active() or {}
        sr = p.get("sizing_rules") or {}
        max_single = float(sr.get("max_single_position_pct", 0.30))
    except Exception:
        pass

    if held and weight > max_single:
        return {"score": -2, "read": f"已超配 ({weight:.0%} > 上限 {max_single:.0%}) — 别加, 考虑 trim",
                "held": True, "weight": round(weight, 3)}
    if held and weight > max_single * 0.7:
        return {"score": -1, "read": f"接近上限 ({weight:.0%}) — 加仓空间有限",
                "held": True, "weight": round(weight, 3)}
    if held:
        return {"score": 0, "read": f"持有 {weight:.0%}, 仍有加仓空间",
                "held": True, "weight": round(weight, 3)}
    return {"score": 1, "read": "未持有 — 有建仓空间 (新位 ≤5% 起)",
            "held": False, "weight": 0.0}


# ── Lens ①: Quality gate (pending fundamentals) ─────────────────────


def _quality(ticker: str) -> Dict[str, Any]:
    """Business-quality gate from fundamentals (yfinance .info).

    Four coarse checks → a GATE score (-2..+2). Clearly-bad business caps the
    overall read. COARSE + sector-sensitive: financials/REITs/utilities carry
    structurally high leverage, deep cyclicals (memory/commodities) swing
    margins — so a single bad metric is flagged, not treated as gospel.

      • 自由现金流 FCF      — the single best quality signal (positive & real)
      • 净利率 net margin   — pricing power / efficiency
      • ROE                — capital efficiency (ROIC proper needs financials,
                              flagged as TODO; ROE used as proxy)
      • 杠杆 debt/equity   — balance-sheet risk (sector-sensitive → soft)
    """
    tk = ticker.upper()
    info = _yf_info(tk)

    from datetime import datetime, timezone
    # Data origin = yfinance (Yahoo). Verification link → stockanalysis.com
    # financials (HEAD-validates, free authoritative cross-check).
    verify_url = f"https://stockanalysis.com/stocks/{tk}/financials/"
    src = [{
        "label": f"基本面 via yfinance (源 Yahoo) · 取于 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} · 核对 stockanalysis.com/financials",
        "url": verify_url, "kind": "yfinance",
    }]

    fcf       = info.get("freeCashflow")
    net_marg  = info.get("profitMargins")
    roe       = info.get("returnOnEquity")
    d2e       = info.get("debtToEquity")   # percent, e.g. 150.0 == 150%

    # No fundamentals at all → stay neutral + pending (honest, no fake gate).
    if all(v is None for v in (fcf, net_marg, roe, d2e)):
        return {
            "score": 0,
            "read": "⏳ 基本面拉取失败 (yfinance 无返回) — 暂中性, 未做质量门槛",
            "pending": True, "metrics": [], "sources": src,
        }

    metrics: List[Dict[str, Any]] = []  # {k, v, verdict ∈ good/ok/bad, pts}
    pts = 0.0
    n = 0

    if fcf is not None:
        n += 1
        if fcf > 0:
            metrics.append({"k": "自由现金流", "v": _fmt_money(fcf), "verdict": "good"}); pts += 1
        else:
            metrics.append({"k": "自由现金流", "v": _fmt_money(fcf), "verdict": "bad"});  pts -= 1

    if net_marg is not None:
        n += 1
        if net_marg >= 0.15:
            metrics.append({"k": "净利率", "v": f"{net_marg*100:.0f}%", "verdict": "good"}); pts += 1
        elif net_marg >= 0.03:
            metrics.append({"k": "净利率", "v": f"{net_marg*100:.0f}%", "verdict": "ok"})
        else:
            metrics.append({"k": "净利率", "v": f"{net_marg*100:.0f}%", "verdict": "bad"}); pts -= 1

    if roe is not None:
        n += 1
        if roe >= 0.15:
            metrics.append({"k": "ROE", "v": f"{roe*100:.0f}%", "verdict": "good"}); pts += 1
        elif roe >= 0:
            metrics.append({"k": "ROE", "v": f"{roe*100:.0f}%", "verdict": "ok"})
        else:
            metrics.append({"k": "ROE", "v": f"{roe*100:.0f}%", "verdict": "bad"}); pts -= 1

    if d2e is not None:
        n += 1
        # debtToEquity reported as a percent. Sector-sensitive → soft scoring.
        if d2e < 100:
            metrics.append({"k": "负债/权益", "v": f"{d2e:.0f}%", "verdict": "good"}); pts += 1
        elif d2e <= 250:
            metrics.append({"k": "负债/权益", "v": f"{d2e:.0f}%", "verdict": "ok"})
        else:
            metrics.append({"k": "负债/权益", "v": f"{d2e:.0f}% (高杠杆⚠)", "verdict": "bad"}); pts -= 1

    avg = (pts / n) if n else 0.0
    if   avg >= 0.6:  score = 2
    elif avg >= 0.2:  score = 1
    elif avg > -0.2:  score = 0
    elif avg > -0.6:  score = -1
    else:             score = -2

    read = {
        2:  "优质 — 现金流/利润率/回报俱佳",
        1:  "尚可 — 基本面稳健",
        0:  "中性 — 喜忧参半",
        -1: "偏弱 — 多项基本面不佳",
        -2: "差 — 质量门槛不过关 (回避/封顶观望)",
    }[score]
    n_good = sum(1 for m in metrics if m["verdict"] == "good")
    n_bad  = sum(1 for m in metrics if m["verdict"] == "bad")
    read += f" · {n_good}优/{n_bad}差/{n}项 ⚠️粗略, ROIC 用 ROE 近似; 金融/REIT/周期股失真"

    return {
        "score": score,
        "read": read,
        "metrics": metrics,
        "sources": src,
    }


# ── Synthesis ───────────────────────────────────────────────────────


# URL validation cache (module-level) — every source link the UI shows must
# be validated (user requirement 2026-05-22: all conclusions traceable to a
# validated source). HEAD-check once per URL, cache the result.
_URL_VALID_CACHE: Dict[str, bool] = {}


def _validate_source_url(url: str, timeout: float = 4.0) -> bool:
    if not url or not url.startswith(("http://", "https://")):
        return False
    if url in _URL_VALID_CACHE:
        return _URL_VALID_CACHE[url]
    ok = False
    # SEC fair-access policy requires a descriptive UA with contact; a
    # generic UA gets 403. SEC also rate-limits ~10 req/s → retry once on
    # transient failure so a single hiccup doesn't mark a good link bad.
    ua = "NeoMind Research admin@neomind.local"
    import time as _t
    for attempt in range(2):
        try:
            import httpx
            with httpx.Client(timeout=httpx.Timeout(timeout), follow_redirects=True) as c:
                r = c.head(url, headers={"User-Agent": ua})
                if r.status_code in (403, 405, 429) or r.status_code >= 500:
                    r = c.get(url, headers={"User-Agent": ua})
                ok = 200 <= r.status_code < 400
        except Exception:
            ok = False
        if ok:
            break
        _t.sleep(0.3)  # respect SEC rate limit before retry
    _URL_VALID_CACHE[url] = ok
    return ok


def _validate_sources(sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """HEAD-validate each external source URL; mark validated true/false.
    Internal-data sources (kind=internal) are inherently traceable → ok."""
    out = []
    for s in sources or []:
        if s.get("kind") == "internal":
            out.append({**s, "validated": True})
        else:
            out.append({**s, "validated": _validate_source_url(s.get("url", ""))})
    return out


def build_scorecard(ticker: str) -> Dict[str, Any]:
    """Compute all lenses → suggested lean + degree + transparent breakdown.
    Every lens carries VALIDATED source links for traceability."""
    tk = ticker.upper()
    q = _quality(tk)
    pos = _positioning(tk)
    val = _valuation(tk)
    fit = _fit(tk)

    # ── Attach + validate provenance sources per lens ──
    # Fit + quality sources are internal (your own data) → traceable in-app.
    fit["sources"] = [{
        "label": "持仓 (tax_lots) + IPS sizing_rules — 见 dashboard 持仓 / IPS widget",
        "kind": "internal", "url": None,
    }]
    pos["sources"] = _validate_sources(pos.get("sources", []))
    val["sources"] = _validate_sources(val.get("sources", []))
    fit["sources"] = _validate_sources(fit["sources"])
    q["sources"]   = _validate_sources(q.get("sources", []))

    held = fit.get("held", False)
    q_pending = bool(q.get("pending"))
    # Weighted blend. Quality + positioning + fit primary; valuation modulates.
    # When quality is pending (no data) it contributes 0 → no false signal.
    raw = pos["score"] * 1.0 + val["score"] * 0.7 + fit["score"] * 1.0 + q["score"] * 0.8
    # Quality gate: a clearly-bad business caps the read regardless of the
    # blend (you don't add to a bad business just because smart money is in).
    quality_fail = (not q_pending) and (q.get("score", 0) <= -1)
    quality_hard_fail = (not q_pending) and (q.get("score", 0) <= -2)

    # Map raw → lean. Vocabulary matches the drawer's decision buttons.
    if held:
        if fit["score"] <= -2:        lean, degree = "trim", "建议减仓 (超配)"
        elif raw >= 2.5:              lean, degree = "add", "可加仓"
        elif raw >= 0.5:              lean, degree = "hold", "持有 (信号偏正)"
        elif raw > -1.5:             lean, degree = "hold", "持有/观察"
        else:                         lean, degree = "trim", "考虑减仓 (信号偏负)"
    else:
        if raw >= 2.5:                lean, degree = "add", "可建仓 (分批, ≤5% 起)"
        elif raw >= 1.0:              lean, degree = "watch_only", "观望偏正 — 等更好时点/确认"
        elif raw > -1.0:             lean, degree = "watch_only", "观望 — 信号不足"
        else:                         lean, degree = "pass", "暂不考虑"

    # Quality gate caps (a bad business is a hard veto on adding):
    if quality_fail and lean == "add":
        lean = "hold" if held else "watch_only"
        degree += " (质量门槛偏弱 → 降级)"
    if quality_hard_fail:
        if held and lean in ("add", "hold"):
            lean, degree = "trim", "质量门槛不过关 → 考虑减仓"
        elif not held and lean in ("add", "watch_only"):
            lean, degree = "pass", "质量门槛不过关 → 暂不考虑"

    # One-line synthesis
    parts = []
    if not q_pending:
        parts.append(f"质量 {q['read'].split(' ·')[0].split(' ⚠️')[0]}")
    parts.append(f"持仓 {pos['read']}")
    parts.append(f"估值 {val['read'].split(' ⚠️')[0]}")
    parts.append(f"契合 {fit['read']}")
    summary = "; ".join(parts)

    return {
        "ticker": tk,
        "held": held,
        "suggested_lean": lean,          # add/hold/trim/sell/watch_only/pass
        "degree": degree,
        "raw_score": round(raw, 2),
        "summary": summary,
        "lenses": {
            "quality":     q,
            "positioning": pos,
            "valuation":   val,
            "fit":         fit,
        },
        "help": LENS_HELP,
        "disclaimer": "信号摘要, 非买卖建议. 决策是你的. 数据可能滞后, 动手前复核.",
    }
