"""Bucket ① — long-term CORE holdings: risk monitor + (Phase 2) hedge overlay.

This is the home for managing the holdings you intend to KEEP (the tax_lots
book), as opposed to the ring-fenced quant swing sleeve (Trading tab) or the
research/idea layers (Research / Strategies). Quant's highest-value use for a
real portfolio is systematic RISK MANAGEMENT, not prediction — so this module
quantifies concentration / beta / vol / drawdown / regime, and (Phase 2) turns
that into a rules-based, hedge-only (protective put / collar) overlay.

Read-only with respect to the core book — it never trades your holdings.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter

logger = logging.getLogger(__name__)


def _portfolio_value_series(qty: Dict[str, float], period: str = "1y"):
    """Build a daily value series for the CURRENT holdings applied to historical
    prices (a 'static portfolio' — what this exact book would have done). Returns
    (dates, value_series, per-symbol close DataFrame, index closes dict)."""
    import yfinance as yf
    import numpy as np
    syms = [s for s in qty if qty[s]]
    idx = ["QQQ", "SPY"]
    px = yf.download(syms + idx, period=period, interval="1d",
                     auto_adjust=True, progress=False)["Close"]
    if hasattr(px, "columns"):
        px = px.dropna(axis=1, how="all")
    have = [s for s in syms if s in getattr(px, "columns", [])]
    # value series = Σ qty * price (forward-fill gaps, drop leading NaN rows)
    sub = px[have].ffill()
    val = sum(sub[s] * qty[s] for s in have)
    val = val.dropna()
    return val, px, have


def _max_drawdown(series) -> float:
    peak, mdd = None, 0.0
    for v in series:
        peak = v if peak is None else max(peak, v)
        if peak and peak > 0:
            mdd = min(mdd, v / peak - 1)
    return mdd * 100.0


def core_risk_monitor() -> Dict[str, Any]:
    """One-shot risk x-ray of the core (tax_lots) book: holdings + weights +
    sector mix + concentration (top-3 / HHI) + beta vs QQQ&SPY + annualized vol
    + 1y static-portfolio max drawdown + market regime + correlation warnings."""
    import numpy as np
    from agent.finance.positions import portfolio_summary
    from agent.finance.trading_desk import market_regime, CORRELATION_THRESHOLD, _corr

    summ = portfolio_summary("SPY")
    holdings = [t for t in summ.get("by_ticker", []) if t.get("market_value")]
    total = summ.get("total_value") or 0.0
    out: Dict[str, Any] = {
        "total_value": total, "total_cost": summ.get("total_cost"),
        "unrealized": summ.get("unrealized"), "unrealized_pct": summ.get("unrealized_pct"),
        "n_tickers": len(holdings),
        "holdings": [{"ticker": t["ticker"], "qty": t["quantity"],
                      "price": t["current_price"], "value": t["market_value"],
                      "weight_pct": round(t["weight_pct"], 1) if t.get("weight_pct") else None,
                      "unrealized_pct": round(t["unrealized_pct"], 1) if t.get("unrealized_pct") is not None else None,
                      "sector": t.get("sector")} for t in holdings],
        "by_sector": summ.get("by_sector"),
        "regime": market_regime(),
    }
    if not holdings or total <= 0:
        out["note"] = "core 持仓为空（tax_lots 无数据）"
        return out

    # ── concentration ──
    weights = sorted([(t["ticker"], (t["weight_pct"] or 0)) for t in holdings],
                     key=lambda x: -x[1])
    out["concentration"] = {
        "largest": {"ticker": weights[0][0], "pct": round(weights[0][1], 1)},
        "top3_pct": round(sum(w for _, w in weights[:3]), 1),
        "hhi": round(sum((w / 100.0) ** 2 for _, w in weights), 3),  # 0..1, >0.25 = concentrated
    }

    # ── beta / vol / drawdown via static-portfolio value series ──
    qty = {t["ticker"]: t["quantity"] for t in holdings}
    try:
        val, px, have = _portfolio_value_series(qty, "1y")
        pr = val.pct_change().dropna()
        rets = px.pct_change().dropna()
        risk = {"ann_vol_pct": round(float(pr.std() * np.sqrt(252) * 100), 0),
                "max_drawdown_1y_pct": round(_max_drawdown(val.values), 1)}
        for ix in ("QQQ", "SPY"):
            if ix in rets:
                a = pr.align(rets[ix], join="inner")
                b = float(np.cov(a[0], a[1])[0, 1] / np.var(a[1])) if np.var(a[1]) else None
                risk[f"beta_{ix.lower()}"] = round(b, 2) if b is not None else None
        out["risk"] = risk
        out["priced_symbols"] = have
    except Exception as exc:
        logger.exception("core risk math failed")
        out["risk"] = {"error": f"{type(exc).__name__}: {exc}"}

    # ── correlation warnings among top holdings (concentration of factor) ──
    warns = []
    top = [t["ticker"] for t in holdings[:8]]
    for i, a in enumerate(top):
        for b in top[i + 1:]:
            c = _corr(a, b)
            if c is not None and c >= CORRELATION_THRESHOLD:
                warns.append({"a": a, "b": b, "corr": round(c, 2)})
    out["correlation_warnings"] = warns
    out["correlation_threshold"] = CORRELATION_THRESHOLD
    return out


def _qqq_put_quote(otm_pct: float, expiry_days: int):
    """Fetch real QQQ spot + a put premium ~otm_pct out, ~expiry_days to expiry.
    Returns (spot, strike, expiry_str, premium_per_share, iv) or (spot, ...None)."""
    import yfinance as yf, datetime as dt
    q = yf.Ticker("QQQ")
    spot = float(q.history(period="1d")["Close"].iloc[-1])
    exps = list(q.options or [])
    today = dt.date.today()
    pick = None
    for e in exps:
        d = (dt.date.fromisoformat(e) - today).days
        if expiry_days - 20 <= d <= expiry_days + 25:
            pick = e
            break
    if not pick and exps:
        pick = min(exps, key=lambda e: abs((dt.date.fromisoformat(e) - today).days - expiry_days))
    if not pick:
        return spot, None, None, None, None
    puts = q.option_chain(pick).puts
    target = round(spot * (1 - otm_pct) / 5) * 5
    row = puts.iloc[(puts["strike"] - target).abs().argmin()]
    mid = float((row["bid"] + row["ask"]) / 2) if row["ask"] > 0 else float(row["lastPrice"])
    return spot, float(row["strike"]), pick, mid, float(row.get("impliedVolatility") or 0)


def hedge_plan(coverage: float = 0.5, otm_pct: float = 0.10,
               expiry_days: int = 55, hedge_beta: Optional[float] = None) -> Dict[str, Any]:
    """Hedge-ONLY overlay calculator (protective QQQ puts). Sizes a beta-adjusted
    QQQ-put hedge for the core book, with REAL premiums, scenario P&L, rule
    status, and a ready-to-place order ticket. Read-only — never auto-trades.

      coverage    : fraction of beta-adjusted exposure to hedge (0..1)
      otm_pct     : how far out-of-the-money the put strike is
      hedge_beta  : beta to size on (default = realized beta_qqq, capped at 2.5
                    because a hot-year realized beta overstates the selloff beta)
    """
    core = core_risk_monitor()
    total = core.get("total_value") or 0.0
    realized_beta = (core.get("risk") or {}).get("beta_qqq")
    if hedge_beta is None:
        hedge_beta = min(realized_beta, 2.5) if realized_beta else 1.0
    out: Dict[str, Any] = {
        "total_value": total, "realized_beta_qqq": realized_beta, "hedge_beta": round(hedge_beta, 2),
        "coverage": coverage, "otm_pct": otm_pct,
        "concentration": core.get("concentration"), "regime": core.get("regime"),
    }
    if total <= 0:
        out["note"] = "core 持仓为空"
        return out

    try:
        spot, strike, expiry, prem, iv = _qqq_put_quote(otm_pct, expiry_days)
    except Exception as exc:
        return {**out, "error": f"取 QQQ 期权报价失败: {type(exc).__name__}: {exc}"}
    if not strike or not prem:
        return {**out, "qqq_spot": spot, "error": "QQQ 期权链无合适报价（休市/数据缺失）"}

    notional = total * hedge_beta * coverage
    per_contract_notional = spot * 100
    contracts = max(0, round(notional / per_contract_notional))
    cost = contracts * prem * 100
    out.update({
        "qqq_spot": round(spot, 2), "strike": strike, "expiry": expiry,
        "premium_per_share": round(prem, 2), "premium_per_contract": round(prem * 100, 0),
        "iv_pct": round(iv * 100, 0), "contracts": contracts,
        "cost": round(cost, 0), "cost_pct": round(cost / total * 100, 2) if total else None,
        "hedged_notional": round(contracts * per_contract_notional, 0),
    })

    # scenario P&L: QQQ drops X% → portfolio loss (≈ beta×X) vs hedged
    scenarios = []
    for mv in (-0.10, -0.20, -0.30):
        port_loss = total * hedge_beta * mv          # beta-amplified portfolio loss
        qqq_at = spot * (1 + mv)
        put_payoff = max(0.0, strike - qqq_at) * 100 * contracts - cost
        scenarios.append({
            "qqq_move_pct": int(mv * 100),
            "port_loss_unhedged": round(port_loss, 0),
            "put_net_payoff": round(put_payoff, 0),
            "port_loss_hedged": round(port_loss + put_payoff, 0),
        })
    out["scenarios"] = scenarios

    # rule status: hedge-trigger = risk_off regime OR drawdown breach
    regime = (core.get("regime") or {}).get("regime")
    dd = (core.get("risk") or {}).get("max_drawdown_1y_pct")
    triggered = (regime == "risk_off")
    out["rule_status"] = {
        "regime": regime, "regime_risk_off": regime == "risk_off",
        "max_drawdown_1y_pct": dd, "triggered": triggered,
        "reason": ("大盘 risk-off（SPY<200日线）→ 规则建议上对冲" if triggered
                   else "regime risk-on → 规则不强制对冲（可自行择时；常年挂保险有负 carry）"),
    }

    # ready-to-place order ticket (you place it in IBKR; live one-click = Phase 2b)
    out["order_ticket"] = (f"BUY {contracts} × QQQ {expiry} {int(strike)} PUT "
                           f"@ limit ~${prem:.2f} (GTC)") if contracts > 0 else "持仓太小，0 张"
    out["caveats"] = [
        "保费为 mid/indicative，实际看盘口；用 limit 单。",
        "指数 put 保市场/科技 beta，保不了单只个股爆雷——集中度优先减仓。",
        f"按 hedge_beta={round(hedge_beta,2)} 估算（实测 {realized_beta} 被慢牛年夸大，下跌时会压缩）。",
        "别常年满仓挂保险（负 carry 拖累收益）——这是择时工具。",
    ]
    return out


def execute_hedge(coverage: float = 0.5, otm_pct: float = 0.10, expiry_days: int = 55,
                  hedge_beta: Optional[float] = None, confirm: bool = False) -> Dict[str, Any]:
    """Place the protective QQQ-put hedge from hedge_plan() — BUY PUT only (the
    connector enforces it), DU-account guarded (paper unless allow_live), GTC
    limit, durably logged. Requires confirm=True (two-step). Read-only re: the
    core book — it only buys protective puts, never touches your holdings."""
    plan = hedge_plan(coverage=coverage, otm_pct=otm_pct,
                      expiry_days=expiry_days, hedge_beta=hedge_beta)
    if plan.get("error") or not plan.get("contracts"):
        return {"ok": False, "error": plan.get("error") or "对冲张数为 0", "plan": plan}
    if not confirm:
        return {"ok": False, "needs_confirm": True, "plan": plan,
                "message": f"将买入 {plan['contracts']} 张 QQQ {plan['expiry']} "
                           f"{int(plan['strike'])} PUT，约 ${plan['cost']:,.0f}（确认后下单）"}

    from agent.finance import ibkr_connector
    from agent.finance.trading_desk import get_state, ibkr_log_event
    allow_live = bool(get_state().get("allow_live"))
    expiry_ibkr = str(plan["expiry"]).replace("-", "")
    # (0) durable intent — before anything can fail
    ibkr_log_event("hedge_intent", symbol="QQQ", action="BUY", qty=plan["contracts"],
                   order_type="OPT_PUT", price=plan.get("premium_per_share"),
                   status="intent", source="hedge", detail=plan)
    # (1) place — connector hard-limits to BUY PUT + DU guard
    res = ibkr_connector.place_option_order(
        "QQQ", expiry_ibkr, plan["strike"], "P", "BUY", plan["contracts"],
        limit_price=plan.get("premium_per_share"), allow_live=allow_live)
    # (2) durable order log
    ibkr_log_event("hedge_order", symbol="QQQ", action="BUY", qty=plan["contracts"],
                   order_type="OPT_PUT", price=plan.get("premium_per_share"),
                   status=(res.get("status") or ("ok" if res.get("ok") else "error")),
                   source="hedge", detail=res)
    return {"ok": bool(res.get("ok")), "result": res, "plan": plan,
            "account": res.get("account"), "paper": not allow_live}


# ── Position sizing (IPS-driven) ────────────────────────────────────
#
# Turns the IPS `sizing_rules` (max-loss risk budget + fractional Kelly +
# single-name cap) into a concrete "how many shares" recommendation for a
# NEW entry, given (entry, invalidation, conviction). All rule VALUES are
# read live from investment_philosophy.sizing_rules — never hard-coded — so
# editing the IPS immediately changes sizing.
#
# The one interpretation the IPS does NOT store is how conviction maps to a
# Kelly edge; that table lives here, clearly labelled + tunable in one place.
# We use a deliberately conservative even-money (b=1) full-Kelly f*=2p-1,
# then apply the IPS's own kelly_fraction (¼-Kelly) and edge_haircut.

_CONVICTION_WIN_PROB = {"LOW": 0.55, "MED": 0.60, "HIGH": 0.67}
_DEFAULT_ACCOUNT_VALUE = 100_000.0

# IPS fallbacks — used ONLY if a key is missing from sizing_rules, so the
# tool degrades gracefully rather than crashing. Live IPS values win.
_SIZING_DEFAULTS = {
    "per_trade_risk_budget_pct": 0.02,
    "kelly_fraction": 0.25,
    "edge_haircut": 0.5,
    "max_single_position_pct": 0.12,
}


def _load_sizing_rules():
    """Return (sizing_rules_dict, ips_version) from the active IPS."""
    from agent.finance.investment_philosophy import get_active
    p = get_active() or {}
    sr = p.get("sizing_rules")
    if not isinstance(sr, dict):
        sr = {}
    return sr, p.get("version")


def _resolve_account_value(account_value: Optional[float]):
    """Explicit value wins; else fall back to /api/trading/state (NetLiq
    high-water mark, then ring-fenced budget); else a neutral default."""
    if account_value and float(account_value) > 0:
        return float(account_value), "explicit"
    try:
        from agent.finance.trading_desk import get_state
        st = get_state() or {}
        for key in ("ibkr_hwm", "trading_budget_usd"):
            v = st.get(key)
            if v and float(v) > 0:
                return float(v), f"trading_state.{key}"
    except Exception:
        pass
    return _DEFAULT_ACCOUNT_VALUE, "default"


def size_position(ticker: str, entry_price: float, invalidation_price: float,
                  account_value: Optional[float] = None,
                  conviction: str = "MED") -> Dict[str, Any]:
    """Suggest a NEW-entry position from the IPS sizing_rules.

    Three constraints, each producing a candidate $ size; the recommendation
    is the MIN (the tightest binds), and we report WHICH one bound it:

      · risk_budget      — max tolerable loss: account × per_trade_risk_budget_pct
                           / ((entry − invalidation) / entry). Caps the $ lost
                           if the stop (=invalidation) trades.
      · kelly            — ¼-Kelly of an edge-haircut'd, conviction-derived edge:
                           f* = 2p−1 (even-money), × kelly_fraction × (1−edge_haircut).
      · single_name_cap  — account × max_single_position_pct (concentration ceiling).

    Read-only; suggests, never trades.
    """
    conv = (conviction or "MED").upper()
    if conv not in _CONVICTION_WIN_PROB:
        conv = "MED"

    sr, ips_version = _load_sizing_rules()

    def _rule(key: str) -> float:
        v = sr.get(key)
        return float(v) if v is not None else float(_SIZING_DEFAULTS[key])

    risk_budget_pct = _rule("per_trade_risk_budget_pct")
    kelly_fraction  = _rule("kelly_fraction")
    edge_haircut    = _rule("edge_haircut")
    max_single_pct  = _rule("max_single_position_pct")

    acct, acct_src = _resolve_account_value(account_value)

    try:
        entry = float(entry_price)
        inval = float(invalidation_price)
    except (TypeError, ValueError):
        return {"error": "entry_price and invalidation_price must be numbers"}
    if entry <= 0:
        return {"error": "entry_price must be > 0"}
    if inval >= entry:
        return {"error": "invalidation_price must be BELOW entry_price "
                         "(this sizes a long with a stop at invalidation)"}

    stop_frac = (entry - inval) / entry           # fractional loss if stopped

    # ① risk budget (max tolerable loss)
    size_risk = acct * risk_budget_pct / stop_frac

    # ② fractional Kelly (conviction edge, ¼-Kelly, edge haircut)
    p = _CONVICTION_WIN_PROB[conv]
    full_kelly = max(0.0, 2 * p - 1)              # even-money (b=1), conservative
    kelly_pct = full_kelly * kelly_fraction * (1 - edge_haircut)
    size_kelly = acct * kelly_pct

    # ③ single-name concentration cap
    size_cap = acct * max_single_pct

    candidates = {
        "risk_budget": round(size_risk, 2),
        "kelly": round(size_kelly, 2),
        "single_name_cap": round(size_cap, 2),
    }
    binding = min(candidates, key=candidates.get)
    size_dollars = candidates[binding]

    shares = int(size_dollars // entry)           # whole shares, never over
    dollars = round(shares * entry, 2)
    risk_at_stop = round(shares * (entry - inval), 2)

    return {
        "ticker": (ticker or "").upper(),
        "conviction": conv,
        "entry_price": entry,
        "invalidation_price": inval,
        "stop_distance_pct": round(stop_frac * 100, 2),
        "account_value": round(acct, 2),
        "account_value_source": acct_src,
        "suggested_position": {
            "dollars": dollars,
            "shares": shares,
            "pct_of_account": round(dollars / acct * 100, 2) if acct else None,
            "dollar_risk_at_stop": risk_at_stop,
            "risk_pct_of_account": round(risk_at_stop / acct * 100, 2) if acct else None,
        },
        "binding_constraint": binding,
        "candidates_dollars": candidates,
        "rules_used": {
            "per_trade_risk_budget_pct": risk_budget_pct,
            "kelly_fraction": kelly_fraction,
            "edge_haircut": edge_haircut,
            "max_single_position_pct": max_single_pct,
            "conviction_win_prob": p,
            "kelly_pct_of_account": round(kelly_pct, 4),
            "ips_version": ips_version,
        },
        "notes": [
            "建议仓位 = min(风险预算, Kelly, 单名顶) — 最紧的约束 binding。",
            "风险预算法先封死下行：止损打到失效价时亏损 = "
            f"{round(risk_budget_pct * 100, 2)}% 账户。",
            "Kelly 用保守 even-money(b=1) f*=2p−1，再 ¼-Kelly + edge 砍半。",
            f"account_value 来源: {acct_src}（可传 account_value 覆盖；"
            "trading_state 是 ring-fenced 交易 sleeve netliq，非整户）。",
            "只做建议，不下单。",
        ],
    }


def build_portfolio_router() -> APIRouter:
    router = APIRouter(prefix="/api/portfolio", tags=["portfolio-hedge"])

    @router.get("/core_risk")
    def get_core_risk() -> Dict[str, Any]:
        return core_risk_monitor()

    @router.get("/size_position")
    def get_size_position(ticker: str, entry_price: float, invalidation_price: float,
                          account_value: Optional[float] = None,
                          conviction: str = "MED") -> Dict[str, Any]:
        """Suggest a NEW-entry size from the IPS sizing_rules: risk-budget
        (max tolerable loss) vs ¼-Kelly vs single-name cap → recommend the min
        + report the binding constraint. Read-only (suggests, never trades)."""
        return size_position(ticker=ticker, entry_price=entry_price,
                             invalidation_price=invalidation_price,
                             account_value=account_value, conviction=conviction)

    @router.get("/hedge_plan")
    def get_hedge_plan(coverage: float = 0.5, otm_pct: float = 0.10,
                       expiry_days: int = 55, hedge_beta: Optional[float] = None) -> Dict[str, Any]:
        return hedge_plan(coverage=coverage, otm_pct=otm_pct,
                          expiry_days=expiry_days, hedge_beta=hedge_beta)

    @router.post("/hedge_execute")
    def post_hedge_execute(coverage: float = 0.5, otm_pct: float = 0.10,
                           expiry_days: int = 55, hedge_beta: Optional[float] = None,
                           confirm: bool = False) -> Dict[str, Any]:
        """Place the protective QQQ-put hedge (BUY PUT only, DU-guarded, GTC).
        confirm=False returns the plan + needs_confirm; confirm=True places it."""
        return execute_hedge(coverage=coverage, otm_pct=otm_pct, expiry_days=expiry_days,
                             hedge_beta=hedge_beta, confirm=confirm)

    return router
