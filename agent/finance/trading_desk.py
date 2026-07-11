"""Short-term Trading Desk — the natural-language → quantified-formula loop.

This is DELIBERATELY SEPARATE from the long-term stack (smart-money 13F /
decision_scorecard). Those signals are quarterly-lagged and would actively
mislead on a swing/opportunistic timeframe. Nothing here reads them.

Three layers, all under /api/trading:

  ① Trading Policy (TPS)  — the ring-fenced short-term playbook (red lines,
       risk caps, kill-switch). Versioned like the IPS. Personal $ figures
       live in a gitignored seed, never in source.
  ② Setups               — each = {natural-language description} + {quant_spec
       the LLM distilled from it} + {latest backtest stats}. Versioned per
       setup so you can audit how the math evolved as you refine the words.
  ③ Compile + verify     — a quant_spec evaluator that turns entry/exit rules
       (over technical indicators) into trades on real OHLCV bars, plus a
       backtest summary and a paper-parallel trigger scan. Reuses
       technical_indicators.py (pure-python SMA/EMA/RSI/MACD/BB/ATR) and the
       existing PaperTradingEngine.

Honest scope: backtest is long-only, one position at a time, entry at the
signal bar's close, intrabar exit at stop/target (stop-first on ambiguous
bars), no leverage. Assumptions are surfaced in the response so the user
never mistakes a rough sim for a guarantee.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agent.finance.persistence import connect, ensure_schema
from agent.finance import technical_indicators as ti

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# ════════════════════════════════════════════════════════════════════
#  ① TRADING POLICY (TPS)
# ════════════════════════════════════════════════════════════════════
#
# PRIVACY: any personal $ budget figures belong in the gitignored seed
# ~/.neomind/fin/seed_trading_policy.json — NOT here. DEFAULT_TPS_SEED below
# holds only principles/percentages (no PII) and is safe to ship publicly.
# It is the policy distilled from the user's own words across the planning
# discussion (opportunistic / low-freq / no-leverage / async orders / etc.).

DEFAULT_TPS_SEED = {
    "version": "v0.1",
    "north_star": (
        "用 ring-fenced 小金额、机会驱动地学习短线 edge。目标是用数据验证"
        "我到底有没有 edge —— 不是赚钱。盈利是副产品，纪律是主产品。"
    ),
    "identity": (
        "低频、机会驱动、不盯盘的 swing trader。通过【异步挂单】交易"
        "(GTC limit + bracket)，不被市场时段绑住。决策必须满足书面 setup，"
        "不追多巴胺。"
    ),
    "red_lines": [
        "永远 limit order，绝不 market —— 尤其任何盘前/盘后/overnight 时段。",
        "绝不用杠杆、不做空。",
        "options 仅用于对冲（保护性 put / collar），不裸卖、不买 call 投机。",
        "大盘 risk-off（SPY<200日线）时停开新仓，考虑提现金/保护性 put。",
        "不持仓过 earnings（二元赌博）；持任何票前查 earnings / Fed 日历。",
        "进场即同时挂 stop + target (bracket / OCO)，成交后不需盯盘。",
        "永不补仓 (no averaging down)；总预算 ring-fenced，亏完即止，绝不追加。",
        "每笔交易必须满足预先写下的 setup checklist 才出手。",
        "用 IBKR cash account（避开无预警自动强平 + 免 PDT）。",
    ],
    "risk_rules": {
        "budget_pct_of_liquid": 1.5,     # 总预算 ≤ 流动资产的 ~1-2%
        "risk_per_trade_pct": 1.0,       # 单笔风险 ≤ 总预算的 ~1%
        "max_pos_pct": 5.0,              # 单仓 ≤ 总预算 5%
        "no_leverage": True,
        "options_hedge_only": True,   # options 仅对冲 (protective put/collar)，不投机
        "no_short": True,
        "no_earnings_hold": True,
        "no_averaging_down": True,
    },
    "entry_protocol": (
        "晚上做完分析 → 在目标价位挂 GTC limit，让市场来找你，不追价。"
        "进场单同时附 bracket(stop + target)。机会必须满足书面 setup 条件。"
    ),
    "exit_protocol": (
        "进场即挂 stop + target。按'止损可能被跳空'来 size 仓位 —— stop 挡不住"
        "隔夜/周末 gap。time-stop：超过 N 根 bar 没动到 target 就按规则平。"
    ),
    "kill_switch": (
        "亏到总预算 -X% 或连续亏 N 笔 → 停一个月，复盘 journal 再决定是否继续。"
    ),
    "execution_rules": (
        "IBKR cash account；IBKR Pro(SmartRouting，执行更好)；订阅实时行情，"
        "绝不用延迟报价下单；用 mobile/Client Portal 低频下单，每单看 preview。"
    ),
    "validation_rules": (
        "每个 setup 先 paper-parallel 验证再上真钱；低频=小样本，5 笔赢别当 edge，"
        "variance 主导；用回测 + paper 统计判断，不凭感觉。"
    ),
    "tax_note": (
        "短线 = ordinary income（边际可能 ~45-50%，含州税）。每笔记 journal"
        "(entry 理由 / stop / target / 结果)；注意 wash sale。"
    ),
    "review_cadence": "monthly",
    "last_reviewed_at": _today(),
    "change_note": "v0.1 — 从规划讨论蒸馏的初始短线 playbook。",
}


def _load_tps_seed() -> Dict[str, Any]:
    import os
    path = os.path.expanduser("~/.neomind/fin/seed_trading_policy.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data.get("north_star"):
                data.setdefault("last_reviewed_at", _today())
                return data
        except Exception:
            pass
    return DEFAULT_TPS_SEED


def _tps_row_to_dict(row) -> Dict[str, Any]:
    if not row:
        return {}
    d = dict(row)
    for key in ("red_lines_json", "risk_rules_json"):
        if d.get(key):
            try:
                d[key.replace("_json", "")] = json.loads(d[key])
            except json.JSONDecodeError:
                pass
    return d


def tps_get_active() -> Optional[Dict[str, Any]]:
    ensure_schema()
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM trading_policy WHERE is_active = 1 "
            "ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
    return _tps_row_to_dict(row) if row else None


def tps_history(limit: int = 20) -> List[Dict[str, Any]]:
    ensure_schema()
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM trading_policy ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_tps_row_to_dict(r) for r in rows]


def tps_upsert(fields: Dict[str, Any], change_note: Optional[str] = None) -> Dict[str, Any]:
    ensure_schema()
    current = tps_get_active() or {}
    cur_ver = current.get("version") or "v0.0"
    try:
        major, minor = cur_ver.lstrip("v").split(".")
        new_ver = f"v{major}.{int(minor) + 1}"
    except (ValueError, AttributeError):
        new_ver = "v1.0"

    payload = {**current, **fields,
               "version": new_ver, "is_active": 1,
               "change_note": change_note or "(no note)",
               "updated_at": _now()}
    payload.setdefault("created_at", payload["updated_at"])

    if isinstance(payload.get("red_lines"), list):
        payload["red_lines_json"] = json.dumps(payload["red_lines"], ensure_ascii=False)
        payload.pop("red_lines", None)
    if isinstance(payload.get("risk_rules"), dict):
        payload["risk_rules_json"] = json.dumps(payload["risk_rules"], ensure_ascii=False)
        payload.pop("risk_rules", None)

    with connect() as conn:
        conn.execute("UPDATE trading_policy SET is_active = 0 WHERE is_active = 1")
        conn.execute(
            "INSERT INTO trading_policy "
            "(version, is_active, north_star, identity, red_lines_json, "
            " risk_rules_json, entry_protocol, exit_protocol, kill_switch, "
            " execution_rules, validation_rules, tax_note, review_cadence, "
            " last_reviewed_at, change_note, created_at, updated_at) "
            "VALUES (?,1,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (payload["version"], payload.get("north_star"), payload.get("identity"),
             payload.get("red_lines_json"), payload.get("risk_rules_json"),
             payload.get("entry_protocol"), payload.get("exit_protocol"),
             payload.get("kill_switch"), payload.get("execution_rules"),
             payload.get("validation_rules"), payload.get("tax_note"),
             payload.get("review_cadence"), payload.get("last_reviewed_at"),
             payload.get("change_note"), payload.get("created_at"),
             payload.get("updated_at")),
        )
    return tps_get_active() or {}


def tps_seed_if_empty() -> Dict[str, Any]:
    if tps_get_active():
        return tps_get_active()
    seed = _load_tps_seed()
    return tps_upsert(seed, change_note=seed.get("change_note", "initial seed"))


# ════════════════════════════════════════════════════════════════════
#  ② SETUPS (versioned per setup_id)
# ════════════════════════════════════════════════════════════════════


def _setup_row_to_dict(row) -> Dict[str, Any]:
    if not row:
        return {}
    d = dict(row)
    for key in ("quant_spec_json", "backtest_stats_json"):
        if d.get(key):
            try:
                d[key.replace("_json", "")] = json.loads(d[key])
            except json.JSONDecodeError:
                pass
    return d


def setups_list() -> List[Dict[str, Any]]:
    ensure_schema()
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM trading_setups WHERE is_active = 1 "
            "ORDER BY updated_at DESC"
        ).fetchall()
    return [_setup_row_to_dict(r) for r in rows]


def setup_get(setup_id: str) -> Optional[Dict[str, Any]]:
    ensure_schema()
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM trading_setups WHERE setup_id = ? AND is_active = 1 "
            "ORDER BY version DESC LIMIT 1",
            (setup_id,),
        ).fetchone()
    return _setup_row_to_dict(row) if row else None


def setup_history(setup_id: str) -> List[Dict[str, Any]]:
    ensure_schema()
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM trading_setups WHERE setup_id = ? ORDER BY version DESC",
            (setup_id,),
        ).fetchall()
    return [_setup_row_to_dict(r) for r in rows]


def setup_save(setup_id: Optional[str], fields: Dict[str, Any],
               change_note: Optional[str] = None) -> Dict[str, Any]:
    """Create (setup_id None) or update (bumps version, deactivates prior)."""
    ensure_schema()
    now = _now()
    if setup_id:
        current = setup_get(setup_id) or {}
        new_version = int(current.get("version", 0)) + 1
        created_at = current.get("created_at") or now
    else:
        setup_id = "stp_" + uuid.uuid4().hex[:10]
        current = {}
        new_version = 1
        created_at = now

    payload = {**current, **fields}
    spec = payload.get("quant_spec")
    if isinstance(spec, (dict, list)):
        spec_json = json.dumps(spec, ensure_ascii=False)
    else:
        spec_json = payload.get("quant_spec_json")
    stats = payload.get("backtest_stats")
    if isinstance(stats, (dict, list)):
        stats_json = json.dumps(stats, ensure_ascii=False)
    else:
        stats_json = payload.get("backtest_stats_json")

    with connect() as conn:
        conn.execute(
            "UPDATE trading_setups SET is_active = 0 WHERE setup_id = ?",
            (setup_id,),
        )
        conn.execute(
            "INSERT INTO trading_setups "
            "(setup_id, version, is_active, name, status, nl_description, "
            " quant_spec_json, backtest_stats_json, change_note, created_at, updated_at) "
            "VALUES (?,?,1,?,?,?,?,?,?,?,?)",
            (setup_id, new_version,
             payload.get("name") or "未命名 setup",
             payload.get("status") or "idea",
             payload.get("nl_description"),
             spec_json, stats_json,
             change_note or "(no note)", created_at, now),
        )
    return setup_get(setup_id) or {}


def setup_delete(setup_id: str) -> bool:
    ensure_schema()
    with connect() as conn:
        cur = conn.execute("DELETE FROM trading_setups WHERE setup_id = ?", (setup_id,))
    return cur.rowcount > 0


# ════════════════════════════════════════════════════════════════════
#  ③ NL → QUANT DISTILLATION (local LLM)
# ════════════════════════════════════════════════════════════════════

# The exact vocabulary the evaluator understands. The LLM is told to ONLY
# emit operands from here so every distilled spec is executable.
INDICATOR_VOCAB = {
    "price fields": ["open", "high", "low", "close", "volume"],
    "indicators": [
        "sma(N)", "ema(N)", "rsi(N)", "atr(N)",
        "macd()", "macd_signal()", "macd_hist()",
        "bb_upper(N)", "bb_mid(N)", "bb_lower(N)",
        "vol_sma(N)",                 # average volume (breakout volume confirm)
        "highest(N)", "lowest(N)",    # prior-N-bar high/low (Donchian / N-day breakout)
    ],
}

_QUANT_SPEC_SCHEMA = """{
  "timeframe": "1d",                // one of: 1d, 1h, 30m, 15m, 1wk
  "lookback": "1y",                 // backtest window: 6mo,1y,2y,5y
  "direction": "long",              // long ONLY (policy: no shorting)
  "entry": {
    "logic": "AND",                 // AND | OR
    "conditions": [                 // each: {left, op, right, rmult?}
      {"left": "rsi(14)", "op": "<", "right": 30},
      {"left": "close", "op": ">", "right": "sma(50)"},
      {"left": "close", "op": "cross_above", "right": "highest(20)"},
      {"left": "volume", "op": ">", "right": "vol_sma(20)", "rmult": 1.5}
    ]
  },
  "exit": {
    "stop":   {"type": "atr", "value": 2.0},   // type: atr(mult) | pct
    "target": {"type": "rr",  "value": 2.0},   // type: rr(R multiple) | pct
    "time_stop_bars": 20                        // force-exit after N bars (0 = off)
  },
  "sizing": {"risk_pct": 1.0, "max_pos_pct": 5.0}
}"""


def _call_llm_json(system: str, user: str, max_tokens: int = 2000) -> Dict[str, Any]:
    """Sync call to the local LLM router → robust-parsed JSON object."""
    import os
    import httpx
    base = (os.getenv("LLM_ROUTER_BASE_URL") or "http://127.0.0.1:8000/v1").rstrip("/")
    key = (os.getenv("LLM_ROUTER_API_KEY") or os.getenv("OPENAI_API_KEY") or "sk-local")
    body = {
        "model": os.getenv("LLM_ROUTER_MODEL") or "deepseek-v4-flash",
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "max_tokens": max_tokens,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    with httpx.Client(timeout=httpx.Timeout(120.0)) as c:
        r = c.post(f"{base}/chat/completions",
                   headers={"Authorization": f"Bearer {key}"}, json=body)
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
    return _parse_json_robust(content)


def _parse_json_robust(text: str) -> Dict[str, Any]:
    """Reuse whale_research's salvage parser; fall back to a minimal one."""
    try:
        from agent.finance.regime.whale_research import _parse_json_robust as wr_parse
        return wr_parse(text)
    except Exception:
        pass
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-z]*\n?|\n?```$", "", t).strip()
    try:
        return json.loads(t)
    except Exception:
        m = re.search(r"\{.*\}", t, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise


def distill_setup(nl_description: str, current_spec: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Natural language → structured quant_spec via the local LLM."""
    system = (
        "你是一个量化交易策略编译器。把用户用自然语言描述的短线 setup 翻译成"
        "一个严格的 JSON quant_spec。只能使用下列操作数，不许发明指标:\n"
        f"  价格字段: {INDICATOR_VOCAB['price fields']}\n"
        f"  指标: {INDICATOR_VOCAB['indicators']}\n"
        "规则: direction 只能是 long(政策禁止做空)。每个 entry condition 是"
        " {left, op, right}，op ∈ [<,>,<=,>=,cross_above,cross_below]，"
        "left/right 是价格字段、指标(如 'sma(50)')、或数字。\n"
        "严格只输出符合下面结构的 JSON，不要任何解释文字:\n" + _QUANT_SPEC_SCHEMA
    )
    user = f"自然语言 setup:\n{nl_description}"
    if current_spec:
        user += f"\n\n当前 spec(在此基础上按上面描述修改):\n{json.dumps(current_spec, ensure_ascii=False)}"
    spec = _call_llm_json(system, user)
    # Enforce policy invariants regardless of what the model returned.
    spec["direction"] = "long"
    return spec


# ════════════════════════════════════════════════════════════════════
#  ③b QUANT_SPEC EVALUATOR + BACKTEST
# ════════════════════════════════════════════════════════════════════

_TF_TO_YF = {  # spec timeframe → (yfinance interval, default period)
    "1d": ("1d", "1y"), "1wk": ("1wk", "5y"), "1h": ("60m", "1mo"),
    "60m": ("60m", "1mo"), "30m": ("30m", "1mo"), "15m": ("15m", "5d"),
}

_OPERAND_RE = re.compile(r"^([a-z_]+)\((\d*)\)$")


_BARS_CACHE: Dict[str, tuple] = {}     # (sym,interval,period) -> (ts, bars)
_BARS_TTL = 600.0                       # 10 min — intraday-ok, makes optimizer fast


# yfinance interval/period → IBKR bar_size/duration (for venue-aligned scan data)
_YF_TO_IBKR_BAR = {"1d": "1 day", "1wk": "1 week", "60m": "1 hour", "30m": "30 mins",
                   "15m": "15 mins", "5m": "5 mins"}
_YF_TO_IBKR_DUR = {"1mo": "1 M", "3mo": "3 M", "6mo": "6 M", "1y": "1 Y",
                   "2y": "2 Y", "3y": "3 Y", "5y": "5 Y"}


def _fetch_bars(symbol: str, interval: str, period: str,
                prefer_ibkr: bool = False) -> List[Dict[str, Any]]:
    """Synchronous OHLCV fetch (oldest→newest), cached per (symbol,interval,
    period) for 10 min. When prefer_ibkr=True (scan in venue=ibkr), pull bars
    from IBKR — the SAME source as execution, so the data that triggers an
    order matches the venue it fills on (no yfinance↔IBKR divergence). Falls
    back to yfinance if IBKR is unavailable. Backtest/optimizer stay on
    yfinance to avoid IBKR's historical-data pacing limits."""
    import time as _t
    key = f"{'IB:' if prefer_ibkr else ''}{symbol}|{interval}|{period}"
    hit = _BARS_CACHE.get(key)
    if hit and (_t.monotonic() - hit[0]) < _BARS_TTL:
        return hit[1]
    if prefer_ibkr:
        try:
            from agent.finance import ibkr_connector
            r = ibkr_connector.bars(symbol,
                                    duration=_YF_TO_IBKR_DUR.get(period, "1 Y"),
                                    bar_size=_YF_TO_IBKR_BAR.get(interval, "1 day"))
            ibk = r.get("bars") or []
            if r.get("connected") and ibk:
                _BARS_CACHE[key] = (_t.monotonic(), ibk)
                return ibk
            # IBKR connected but no data, or not connected → fall through to yfinance
        except Exception:
            pass
    import yfinance as yf
    try:
        df = yf.Ticker(symbol).history(period=period, interval=interval)
    except Exception:
        df = None
    if df is None or df.empty:
        _BARS_CACHE[key] = (_t.monotonic(), [])
        return []
    bars = []
    for ts, row in df.iterrows():
        try:
            bars.append({
                "date": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                "open": float(row["Open"]), "high": float(row["High"]),
                "low": float(row["Low"]), "close": float(row["Close"]),
                "volume": int(row["Volume"]) if row["Volume"] == row["Volume"] else 0,
            })
        except Exception:
            continue
    _BARS_CACHE[key] = (_t.monotonic(), bars)
    return bars


def _series_for_operand(operand: str, ohlc: Dict[str, List[float]]) -> Optional[List[Optional[float]]]:
    """Resolve an operand string to an aligned per-bar series, or None for numbers."""
    op = operand.strip().lower()
    if op in ("open", "high", "low", "close", "volume"):
        return [float(x) for x in ohlc[op]]
    m = _OPERAND_RE.match(op)
    if not m:
        return None  # numeric literal
    name, period_s = m.group(1), m.group(2)
    period = int(period_s) if period_s else None
    closes = ohlc["close"]
    if name == "sma":
        return ti.sma(closes, period or 20)
    if name == "ema":
        return ti.ema(closes, period or 20)
    if name == "rsi":
        return ti.rsi(closes, period or 14)
    if name == "atr":
        return ti.atr(ohlc["high"], ohlc["low"], closes, period or 14)
    if name == "vol_sma":               # avg volume — for breakout vol confirmation
        return ti.sma([float(v) for v in ohlc["volume"]], period or 20)
    if name in ("highest", "lowest"):   # rolling N-bar high/low (Donchian/breakout)
        src = ohlc["high"] if name == "highest" else ohlc["low"]
        p = period or 20
        out: List[Optional[float]] = [None] * len(src)
        for i in range(len(src)):
            if i >= p:                  # prior-N (exclude current bar → true breakout)
                window = src[i - p:i]
                out[i] = max(window) if name == "highest" else min(window)
        return out
    if name in ("macd", "macd_signal", "macd_hist"):
        line, sig, hist = ti.macd(closes)
        return {"macd": line, "macd_signal": sig, "macd_hist": hist}[name]
    if name in ("bb_upper", "bb_mid", "bb_lower"):
        up, mid, lo = ti.bollinger_bands(closes, period or 20)
        return {"bb_upper": up, "bb_mid": mid, "bb_lower": lo}[name]
    return None


def _val(operand, series_cache, ohlc, i) -> Optional[float]:
    """Value of an operand at bar i — number literal, price, or indicator."""
    if isinstance(operand, (int, float)):
        return float(operand)
    op = str(operand).strip()
    try:
        return float(op)  # numeric string
    except ValueError:
        pass
    if op not in series_cache:
        series_cache[op] = _series_for_operand(op, ohlc)
    s = series_cache[op]
    if s is None:
        return None
    return s[i] if 0 <= i < len(s) else None


def _cond_true(cond: Dict[str, Any], series_cache, ohlc, i) -> Optional[bool]:
    left, op, right = cond.get("left"), cond.get("op"), cond.get("right")
    rmult = float(cond.get("rmult", 1) or 1)   # right-side multiplier (e.g. volume > 1.5×vol_sma)
    lv, rv = _val(left, series_cache, ohlc, i), _val(right, series_cache, ohlc, i)
    if rv is not None:
        rv *= rmult
    if op in ("cross_above", "cross_below"):
        lp, rp = _val(left, series_cache, ohlc, i - 1), _val(right, series_cache, ohlc, i - 1)
        if None in (lv, rv, lp, rp):
            return None
        rp *= rmult
        return (lp <= rp and lv > rv) if op == "cross_above" else (lp >= rp and lv < rv)
    if lv is None or rv is None:
        return None
    return {"<": lv < rv, ">": lv > rv, "<=": lv <= rv, ">=": lv >= rv,
            "==": lv == rv}.get(op)


# Realistic frictions — backtests WITHOUT these systematically overstate edge
# (esp. for short-term/high-turnover strategies). Slippage per side + a
# round-trip commission, applied to every trade so reported stats are net.
COST_SLIPPAGE_PCT = 0.05    # per side (% of price) — bid/ask + market impact
COST_COMMISSION_PCT = 0.0   # per side (% of notional); IBKR ~$0.005/share≈tiny
OOS_FRACTION = 0.30         # last 30% of the period = out-of-sample (unseen)


def evaluate_spec(spec: Dict[str, Any], symbol: str) -> Dict[str, Any]:
    """Compile a quant_spec to trades on real bars + summary stats.

    Long-only, one position at a time, entry at signal bar close, intrabar
    exit at stop/target (stop checked first on ambiguous bars), optional
    time-stop. Trades are NET of slippage + commission. Also splits results
    into in-sample (first 70%) vs out-of-sample (last 30%) to expose
    overfitting. Assumptions are returned so the user sees the model.
    """
    tf = (spec.get("timeframe") or "1d").lower()
    interval, default_period = _TF_TO_YF.get(tf, ("1d", "1y"))
    period = spec.get("lookback") or default_period
    bars = _fetch_bars(symbol, interval, period)
    if len(bars) < 30:
        return {"error": f"数据不足 (仅 {len(bars)} 根 bar) — 换更长 lookback 或更大 timeframe",
                "symbol": symbol, "n_bars": len(bars)}

    ohlc = {k: [b[k] for b in bars] for k in ("open", "high", "low", "close", "volume")}
    series_cache: Dict[str, Any] = {}
    entry = spec.get("entry") or {}
    conds = entry.get("conditions") or []
    logic = (entry.get("logic") or "AND").upper()
    exit_cfg = spec.get("exit") or {}
    stop_cfg = exit_cfg.get("stop") or {"type": "pct", "value": 5.0}
    target_cfg = exit_cfg.get("target") or {"type": "rr", "value": 2.0}
    time_stop = int(exit_cfg.get("time_stop_bars") or 0)

    def entry_ok(i) -> bool:
        results = [_cond_true(c, series_cache, ohlc, i) for c in conds]
        if any(r is None for r in results) or not results:
            return False
        return all(results) if logic == "AND" else any(results)

    def stop_target(entry_px, i):
        atr_series = _series_for_operand("atr(14)", ohlc)
        a = atr_series[i] if atr_series and atr_series[i] is not None else entry_px * 0.02
        if stop_cfg.get("type") == "atr":
            stop = entry_px - float(stop_cfg.get("value", 2.0)) * a
        else:  # pct
            stop = entry_px * (1 - float(stop_cfg.get("value", 5.0)) / 100.0)
        risk = max(entry_px - stop, 1e-9)
        if target_cfg.get("type") == "rr":
            target = entry_px + float(target_cfg.get("value", 2.0)) * risk
        else:  # pct
            target = entry_px * (1 + float(target_cfg.get("value", 10.0)) / 100.0)
        return stop, target

    def entry_detail(i):
        """The actual operand values that satisfied each entry condition at
        bar i — so a trade can be traced back to exactly why it fired."""
        rows = []
        for c in conds:
            lv = _val(c.get("left"), series_cache, ohlc, i)
            rv = _val(c.get("right"), series_cache, ohlc, i)
            rmult = float(c.get("rmult", 1) or 1)
            if rv is not None:
                rv *= rmult
            rows.append({
                "left": str(c.get("left")), "op": c.get("op"),
                "right": str(c.get("right")) + (f"×{rmult}" if rmult != 1 else ""),
                "lval": round(lv, 2) if isinstance(lv, (int, float)) else None,
                "rval": round(rv, 2) if isinstance(rv, (int, float)) else None,
                "note": c.get("note"),
            })
        return rows

    trades: List[Dict[str, Any]] = []
    in_pos = False
    entry_px = stop = target = 0.0
    entry_i = 0
    entry_rows: List[Dict[str, Any]] = []
    n = len(bars)
    for i in range(1, n):
        if not in_pos:
            if entry_ok(i):
                entry_px = ohlc["close"][i]
                stop, target = stop_target(entry_px, i)
                entry_i, in_pos = i, True
                entry_rows = entry_detail(i)
        else:
            hi, lo = ohlc["high"][i], ohlc["low"][i]
            exit_px = reason = None
            if lo <= stop:                       # stop-first (conservative)
                exit_px, reason = stop, "stop"
            elif hi >= target:
                exit_px, reason = target, "target"
            elif time_stop and (i - entry_i) >= time_stop:
                exit_px, reason = ohlc["close"][i], "time_stop"
            if exit_px is not None:
                risk = max(entry_px - stop, 1e-9)
                # apply slippage (buy higher, sell lower) + round-trip commission
                slip = COST_SLIPPAGE_PCT / 100.0
                comm = COST_COMMISSION_PCT / 100.0
                eff_entry = entry_px * (1 + slip)
                eff_exit = exit_px * (1 - slip)
                net_ret = (eff_exit / eff_entry - 1) * 100 - comm * 200
                trades.append({
                    "entry_date": bars[entry_i]["date"][:10], "entry_px": round(entry_px, 2),
                    "exit_date": bars[i]["date"][:10], "exit_px": round(exit_px, 2),
                    "reason": reason, "bars_held": i - entry_i,
                    "return_pct": round(net_ret, 2),
                    "R": round((eff_exit - eff_entry) / risk, 2),
                    "entry_detail": entry_rows,
                })
                in_pos = False

    stats = _summarize(trades, bars)
    # benchmark: buy-and-hold the symbol over the same window — a strategy that
    # doesn't beat just holding (esp. risk-adjusted) isn't worth the churn/tax.
    closes_bh = ohlc["close"]
    if len(closes_bh) >= 2 and closes_bh[0]:
        bh = (closes_bh[-1] / closes_bh[0] - 1) * 100
        stats["buy_hold_pct"] = round(bh, 1)
        stats["beats_buy_hold"] = (stats.get("total_return_pct") or 0) > bh
    stats["assumptions"] = (
        f"long-only · 单仓 · 信号bar收盘进场 · 盘中触stop/target(同bar优先stop) · "
        f"已扣滑点{COST_SLIPPAGE_PCT}%/边" +
        (f"+佣金{COST_COMMISSION_PCT}%/边" if COST_COMMISSION_PCT else "") +
        " · 历史≠未来"
    )

    # In-sample (first 70%) vs out-of-sample (last 30%) split by entry date —
    # exposes overfitting: if OOS collapses vs IS, the rules are curve-fit.
    cutoff_idx = int(len(bars) * (1 - OOS_FRACTION))
    cutoff_date = bars[cutoff_idx]["date"][:10] if 0 <= cutoff_idx < len(bars) else None
    is_trades = [t for t in trades if t["entry_date"] < (cutoff_date or "9999")]
    oos_trades = [t for t in trades if cutoff_date and t["entry_date"] >= cutoff_date]
    is_stats = _summarize(is_trades, bars)
    oos_stats = _summarize(oos_trades, bars)
    robustness = _robustness(is_stats, oos_stats)

    return {"symbol": symbol, "timeframe": tf, "n_bars": len(bars),
            "trades": trades, "stats": stats,
            "oos_cutoff": cutoff_date,
            "is_stats": is_stats, "oos_stats": oos_stats,
            "robustness": robustness}


def _robustness(is_stats: Dict[str, Any], oos_stats: Dict[str, Any]) -> Dict[str, Any]:
    """Compare in-sample vs out-of-sample to flag overfitting."""
    is_r = is_stats.get("avg_R")
    oos_r = oos_stats.get("avg_R")
    if not is_stats.get("n_trades") or not oos_stats.get("n_trades"):
        return {"verdict": "unknown", "note": "样本不足以做 IS/OOS 对比"}
    if oos_r is None or is_r is None:
        return {"verdict": "unknown", "note": "无 avgR"}
    # OOS turned negative while IS was decent → classic overfit
    if is_r > 0.2 and oos_r < 0:
        return {"verdict": "overfit", "note": f"样本内 avgR {is_r} 转样本外 {oos_r} → 疑似过拟合"}
    if oos_r < is_r * 0.4:
        return {"verdict": "weak", "note": f"样本外 avgR {oos_r} 明显弱于样本内 {is_r} → 谨慎"}
    return {"verdict": "robust", "note": f"样本外 avgR {oos_r} 与样本内 {is_r} 一致 → 较稳健"}


def _summarize(trades: List[Dict[str, Any]], bars: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(trades)
    if n == 0:
        return {"n_trades": 0, "win_rate": None, "avg_R": None,
                "total_return_pct": 0.0, "max_drawdown_pct": 0.0, "avg_bars_held": None}
    wins = [t for t in trades if t["return_pct"] > 0]
    equity, peak, max_dd = 1.0, 1.0, 0.0
    for t in trades:
        equity *= (1 + t["return_pct"] / 100.0)
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak)
    return {
        "n_trades": n,
        "win_rate": round(len(wins) / n * 100, 1),
        "avg_R": round(sum(t["R"] for t in trades) / n, 2),
        "total_return_pct": round((equity - 1) * 100, 1),
        "max_drawdown_pct": round(max_dd * 100, 1),
        "avg_bars_held": round(sum(t["bars_held"] for t in trades) / n, 1),
        "best_R": round(max(t["R"] for t in trades), 2),
        "worst_R": round(min(t["R"] for t in trades), 2),
    }


# ════════════════════════════════════════════════════════════════════
#  ③c PAPER-PARALLEL TRIGGER SCAN
# ════════════════════════════════════════════════════════════════════


def scan_setups(symbols: Optional[List[str]] = None) -> Dict[str, Any]:
    """For each active setup, check whether entry triggers on the latest bar
    for each symbol in the setup's universe (or `symbols`). Reports would-be
    entries — the user decides whether to fire the paper order."""
    if symbols is None:
        symbols = _watchlist_symbols()
    triggers: List[Dict[str, Any]] = []
    for s in setups_list():
        if s.get("status") == "retired":
            continue
        spec = s.get("quant_spec")
        if not isinstance(spec, dict) or not (spec.get("entry") or {}).get("conditions"):
            continue
        for sym in symbols:
            try:
                res = evaluate_spec(spec, sym)
            except Exception as exc:
                logger.debug("scan eval %s/%s failed: %s", s.get("setup_id"), sym, exc)
                continue
            if res.get("error"):
                continue
            # Re-check entry on the most recent bar specifically.
            fired = _entry_on_last_bar(spec, sym)
            if fired:
                triggers.append({
                    "setup_id": s.get("setup_id"), "setup_name": s.get("name"),
                    "symbol": sym, "as_of": fired.get("date"),
                    "entry_px": fired.get("close"),
                })
    return {"n_triggers": len(triggers), "triggers": triggers, "scanned": len(symbols)}


def _entry_on_last_bar(spec: Dict[str, Any], symbol: str,
                       prefer_ibkr: bool = False) -> Optional[Dict[str, Any]]:
    tf = (spec.get("timeframe") or "1d").lower()
    interval, default_period = _TF_TO_YF.get(tf, ("1d", "1y"))
    bars = _fetch_bars(symbol, interval, spec.get("lookback") or default_period,
                       prefer_ibkr=prefer_ibkr)
    if len(bars) < 30:
        return None
    ohlc = {k: [b[k] for b in bars] for k in ("open", "high", "low", "close", "volume")}
    series_cache: Dict[str, Any] = {}
    entry = spec.get("entry") or {}
    conds = entry.get("conditions") or []
    logic = (entry.get("logic") or "AND").upper()
    i = len(bars) - 1
    results = [_cond_true(c, series_cache, ohlc, i) for c in conds]
    if any(r is None for r in results) or not results:
        return None
    ok = all(results) if logic == "AND" else any(results)
    if ok:
        return {"date": bars[i]["date"][:10], "close": round(ohlc["close"][i], 2)}
    return None


def _watchlist_symbols() -> List[str]:
    try:
        with connect() as conn:
            return [r["ticker"].upper() for r in
                    conn.execute("SELECT ticker FROM user_watchlist").fetchall()
                    if r["ticker"]]
    except Exception:
        return []


# ── Correlation / concentration (the foundation of real diversification) ──
# Multiple long positions in correlated names = one concentrated bet wearing
# a diversification costume. We compute pairwise return-correlation so the
# scan can refuse to pile into a name that just mirrors something held.
CORRELATION_THRESHOLD = 0.75
_RET_CACHE: Dict[str, tuple] = {}   # sym -> (ts, returns list)


def _daily_returns(symbol: str, period: str = "6mo") -> List[float]:
    import time as _t
    hit = _RET_CACHE.get(symbol)
    if hit and (_t.monotonic() - hit[0]) < 900:
        return hit[1]
    bars = _fetch_bars(symbol, "1d", period)
    closes = [b["close"] for b in bars]
    rets = [(closes[i] / closes[i - 1] - 1) for i in range(1, len(closes)) if closes[i - 1]]
    _RET_CACHE[symbol] = (_t.monotonic(), rets)
    return rets


def _corr(a: str, b: str) -> Optional[float]:
    ra, rb = _daily_returns(a), _daily_returns(b)
    n = min(len(ra), len(rb))
    if n < 30:
        return None
    ra, rb = ra[-n:], rb[-n:]
    ma, mb = sum(ra) / n, sum(rb) / n
    cov = sum((ra[i] - ma) * (rb[i] - mb) for i in range(n))
    va = sum((x - ma) ** 2 for x in ra) ** 0.5
    vb = sum((x - mb) ** 2 for x in rb) ** 0.5
    if va == 0 or vb == 0:
        return None
    return cov / (va * vb)


def portfolio_risk(project_id: str) -> Dict[str, Any]:
    """Correlation matrix of current holdings + concentration warnings.
    VENUE-AWARE: uses IBKR positions when venue=ibkr."""
    if current_venue() == "ibkr":
        from agent.finance import ibkr_connector
        snap = ibkr_connector.account_snapshot()
        syms = sorted({p["symbol"] for p in (snap.get("positions") or [])
                       if (p.get("position") or 0) > 0})
    else:
        from agent.finance.paper_trading import get_project_engine
        eng = get_project_engine(project_id)
        syms = sorted({p.symbol for p in eng.get_all_positions() if p.quantity > 0})
    matrix, warnings = [], []
    for i, a in enumerate(syms):
        row = []
        for b in syms:
            c = 1.0 if a == b else _corr(a, b)
            row.append(round(c, 2) if c is not None else None)
            if a < b and c is not None and c >= CORRELATION_THRESHOLD:
                warnings.append({"a": a, "b": b, "corr": round(c, 2)})
        matrix.append({"symbol": a, "row": row})
    return {"symbols": syms, "matrix": matrix, "warnings": warnings,
            "threshold": CORRELATION_THRESHOLD, "n_positions": len(syms)}


def _correlated_holding(symbol: str, held: set) -> Optional[Dict[str, Any]]:
    """Is `symbol` highly correlated with anything already held?"""
    for h in held:
        if h == symbol:
            continue
        c = _corr(symbol, h)
        if c is not None and c >= CORRELATION_THRESHOLD:
            return {"with": h, "corr": round(c, 2)}
    return None


# ════════════════════════════════════════════════════════════════════
#  ④ EMERGENCY BRAKES + TRADING STATE
# ════════════════════════════════════════════════════════════════════
#
# Design: the ONLY manual controls are emergency brakes. Everything else
# (scan, score, backtest, entry) is automated. The brakes:
#   1. global_halt  — master freeze on all automated order placement.
#   2. flatten_all  — panic-close every open paper position now.
#   3. per-setup arm — only status 'paper'/'live' setups auto-trade.
#   4. kill-switch  — AUTO-flips global_halt on a policy breach (drawdown /
#      consecutive losses); user must manually resume. Automation detects,
#      human acknowledges.


def get_state() -> Dict[str, Any]:
    ensure_schema()
    with connect() as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(trading_state)").fetchall()}
        if "ibkr_route" not in cols:
            conn.execute("ALTER TABLE trading_state ADD COLUMN ibkr_route INTEGER DEFAULT 0")
        # execution venue: 'sim' (internal engine, offline) | 'ibkr' (IBKR account = truth)
        if "venue" not in cols:
            conn.execute("ALTER TABLE trading_state ADD COLUMN venue TEXT DEFAULT 'sim'")
            # backfill from legacy ibkr_route so behavior is preserved
            conn.execute("UPDATE trading_state SET venue = CASE WHEN ibkr_route = 1 "
                         "THEN 'ibkr' ELSE 'sim' END WHERE venue IS NULL OR venue = ''")
        # real-money switch: 0 = paper-only (DU-guard active); 1 = real orders allowed.
        if "allow_live" not in cols:
            conn.execute("ALTER TABLE trading_state ADD COLUMN allow_live INTEGER DEFAULT 0")
        # absolute ring-fenced budget in USD (0 = derive from budget_pct_of_liquid)
        if "trading_budget_usd" not in cols:
            conn.execute("ALTER TABLE trading_state ADD COLUMN trading_budget_usd REAL DEFAULT 0")
        # NetLiq high-water mark for the venue=ibkr kill-switch drawdown
        if "ibkr_hwm" not in cols:
            conn.execute("ALTER TABLE trading_state ADD COLUMN ibkr_hwm REAL DEFAULT 0")
        row = conn.execute("SELECT * FROM trading_state WHERE id = 1").fetchone()
        if not row:
            conn.execute(
                "INSERT INTO trading_state (id, global_halt, auto_trade, venue, updated_at) "
                "VALUES (1, 0, 1, 'sim', ?)", (_now(),))
            row = conn.execute("SELECT * FROM trading_state WHERE id = 1").fetchone()
    d = dict(row)
    d["venue"] = d.get("venue") or ("ibkr" if d.get("ibkr_route") else "sim")
    return d


def current_venue() -> str:
    """'sim' = internal engine (offline/instant, for backtest+dry-run);
    'ibkr' = IBKR account is the single source of truth (forward paper/live)."""
    return get_state().get("venue") or "sim"


def set_halt(on: bool, reason: Optional[str] = None, by: str = "user") -> Dict[str, Any]:
    ensure_schema()
    get_state()  # ensure row exists
    with connect() as conn:
        conn.execute(
            "UPDATE trading_state SET global_halt = ?, halt_reason = ?, "
            "halted_by = ?, updated_at = ? WHERE id = 1",
            (1 if on else 0, reason if on else None, by if on else None, _now()),
        )
    return get_state()


def set_auto_trade(on: bool) -> Dict[str, Any]:
    """Master arm/disarm for automated entries. OFF = scan is report-only
    (the '一键断开自动进场' switch). Distinct from global_halt (emergency)."""
    ensure_schema()
    get_state()
    with connect() as conn:
        conn.execute("UPDATE trading_state SET auto_trade = ?, updated_at = ? WHERE id = 1",
                     (1 if on else 0, _now()))
    return get_state()


def set_venue(venue: str) -> Dict[str, Any]:
    """Set the execution venue + single source of truth.
      'sim'  — internal engine (offline/instant fills) for backtest + dry-run.
      'ibkr' — the IBKR account is truth; forward orders go to IBKR via the
               SAME code path as real money (only the account differs: a paper
               DU… account on port 4002 vs a live U… account on 4001). This is
               what makes paper and live 100% identical."""
    venue = venue if venue in ("sim", "ibkr") else "sim"
    get_state()  # ensures columns + row exist
    with connect() as conn:
        conn.execute("UPDATE trading_state SET venue = ?, ibkr_route = ?, updated_at = ? WHERE id = 1",
                     (venue, 1 if venue == "ibkr" else 0, _now()))
    return get_state()


def set_ibkr_route(on: bool) -> Dict[str, Any]:
    """Back-compat alias → set_venue('ibkr'|'sim')."""
    return set_venue("ibkr" if on else "sim")


def set_trading_budget(usd: float) -> Dict[str, Any]:
    """Ring-fenced budget in absolute USD (0 = derive from budget_pct_of_liquid
    × account). risk_per_trade_pct / max_pos_pct apply to THIS budget."""
    get_state()
    with connect() as conn:
        conn.execute("UPDATE trading_state SET trading_budget_usd = ?, updated_at = ? WHERE id = 1",
                     (max(0.0, float(usd or 0)), _now()))
    return get_state()


def _resolve_budget(equity: float) -> float:
    """Sizing base: explicit trading_budget_usd if set, else budget_pct × equity.
    Always capped at equity (can't deploy more than the account holds)."""
    st = get_state()
    rr = (tps_seed_if_empty() or {}).get("risk_rules") or {}
    abs_budget = float(st.get("trading_budget_usd") or 0)
    if abs_budget > 0:
        return min(abs_budget, equity or abs_budget)
    pct = float(rr.get("budget_pct_of_liquid", 1.5))
    return (equity or 0) * (pct / 100.0)


# The one phrase that flips real money on. Deliberately verbose so it can't be
# toggled accidentally — this is the sole behavioral difference vs paper.
_LIVE_CONFIRM = "I_UNDERSTAND_REAL_MONEY"


def set_allow_live(on: bool, confirm: str = "") -> Dict[str, Any]:
    """Enable/disable REAL-MONEY orders. Turning ON requires the exact confirm
    phrase. OFF (default) keeps the DU-only guard = paper can never touch a real
    account. This flag is the ONLY thing that differs between paper and live —
    the order code path is identical."""
    if on and confirm != _LIVE_CONFIRM:
        return {**get_state(), "error": f"启用真钱需传 confirm='{_LIVE_CONFIRM}'（防误触）"}
    get_state()
    with connect() as conn:
        conn.execute("UPDATE trading_state SET allow_live = ?, updated_at = ? WHERE id = 1",
                     (1 if on else 0, _now()))
    return get_state()


# ════════════════════════════════════════════════════════════════════
#  IBKR durable archive — every order we send + periodic snapshots are
#  written to the local `ibkr_log` table so the history is queryable
#  FOREVER, regardless of whether IB Gateway is running. (IBKR's own API
#  only returns current state + today's fills.)
# ════════════════════════════════════════════════════════════════════
_IBKR_LOG_DDL = """
CREATE TABLE IF NOT EXISTS ibkr_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, kind TEXT NOT NULL,
    ext_id TEXT UNIQUE, account TEXT, symbol TEXT, action TEXT, qty REAL,
    order_type TEXT, price REAL, status TEXT, source TEXT, detail TEXT);
CREATE INDEX IF NOT EXISTS idx_ibkr_log_ts ON ibkr_log(ts DESC);
CREATE INDEX IF NOT EXISTS idx_ibkr_log_symbol ON ibkr_log(symbol);
CREATE INDEX IF NOT EXISTS idx_ibkr_log_kind ON ibkr_log(kind);
"""


def _ensure_ibkr_log(conn) -> None:
    conn.executescript(_IBKR_LOG_DDL)


def ibkr_log_event(kind: str, *, ext_id: Optional[str] = None, account: Optional[str] = None,
                   symbol: Optional[str] = None, action: Optional[str] = None,
                   qty: Optional[float] = None, order_type: Optional[str] = None,
                   price: Optional[float] = None, status: Optional[str] = None,
                   source: Optional[str] = None, detail: Optional[Any] = None) -> None:
    """Append one row to the durable IBKR log. Fills (with ext_id=execId) dedupe
    via INSERT OR IGNORE on the UNIQUE ext_id."""
    ensure_schema()
    with connect() as conn:
        _ensure_ibkr_log(conn)
        conn.execute(
            "INSERT OR IGNORE INTO ibkr_log "
            "(ts, kind, ext_id, account, symbol, action, qty, order_type, price, status, source, detail) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (_now(), kind, ext_id, account, symbol, action, qty, order_type, price, status, source,
             json.dumps(detail, ensure_ascii=False) if detail is not None else None))


def ibkr_log_order(res: Dict[str, Any], source: str) -> None:
    """Record the result of a place_paper_bracket call (each leg = one row)."""
    if not isinstance(res, dict):
        return
    acct = res.get("account")
    for o in (res.get("orders") or []):
        ibkr_log_event("order", account=acct, symbol=o.get("symbol"),
                       action=o.get("action"), qty=o.get("qty"),
                       order_type=o.get("kind"), status=o.get("status"),
                       source=source, detail=o)
    if not res.get("orders") and res.get("error"):
        ibkr_log_event("order", account=acct, status="error", source=source,
                       detail={"error": res.get("error")})


_REJECTED_STATUSES = {"rejected", "validationerror", "error", "cancelled", "inactive", "apicancelled"}


def _verify_ibkr_presence(symbol: str, order_ids: List[Any]) -> Dict[str, Any]:
    """Independently confirm a just-placed order across THREE IBKR subsystems —
    open-orders book, today's executions, current positions — read in ONE
    batched connection (account_snapshot) for speed/reliability. Still three
    independent data sources, just one round-trip."""
    from agent.finance import ibkr_connector
    symu = (symbol or "").upper()
    ids = set(order_ids or [])
    snap = ibkr_connector.account_snapshot()
    err = snap.get("error")
    oo_hit = [o for o in (snap.get("orders") or [])
              if o.get("order_id") in ids or (o.get("symbol") or "").upper() == symu]
    fl_hit = [f for f in (snap.get("fills") or []) if (f.get("symbol") or "").upper() == symu]
    ps_hit = [p for p in (snap.get("positions") or []) if (p.get("symbol") or "").upper() == symu]
    checks = {
        "open_orders": {"ok": bool(oo_hit), "n": len(oo_hit), "err": err},   # source #2
        "fills": {"ok": bool(fl_hit), "n": len(fl_hit), "err": err},         # source #3
        "positions": {"ok": bool(ps_hit), "n": len(ps_hit), "err": err},     # source #4
    }
    confirms = sum(1 for c in checks.values() if c["ok"])
    return {"symbol": symu, "order_ids": list(ids),
            "independent_confirms": confirms, "checks": checks}


def place_log_verify(symbol: str, action: str, qty: int, *,
                     stop_loss: Optional[float] = None, take_profit: Optional[float] = None,
                     limit_price: Optional[float] = None, source: str = "manual") -> Dict[str, Any]:
    """The ONLY sanctioned path to send an order to IBKR from the desk. It makes
    every real buy/sell durable + cross-verified:
      (0) log INTENT to ibkr_log BEFORE sending — survives any later crash/hang
      (1) place the bracket (source #1 = IBKR orderStatus ack)
      (2) log every leg of the send result
      (3) INDEPENDENTLY verify presence via open-orders / fills / positions (#2–#4)
      (4) log the verification verdict (verified / rejected / UNCONFIRMED).
    A real buy/sell is thus recorded in ≥3 rows and confirmed by ≥2 sources."""
    from agent.finance import ibkr_connector
    sym = (symbol or "").upper()
    allow_live = bool(get_state().get("allow_live"))   # sole paper/real difference
    intent = {"symbol": sym, "action": action, "qty": qty, "stop_loss": stop_loss,
              "take_profit": take_profit, "limit_price": limit_price, "source": source,
              "allow_live": allow_live}
    # (0) INTENT — durable before anything can fail
    ibkr_log_event("order_intent", symbol=sym, action=action, qty=qty,
                   order_type="LMT" if limit_price else "MKT", price=limit_price,
                   status="intent", source=source, detail=intent)
    # (1) send (source #1) — same call for paper & live; allow_live is the only diff
    res = ibkr_connector.place_paper_bracket(sym, action, qty, limit_price=limit_price,
                                             stop_loss=stop_loss, take_profit=take_profit,
                                             allow_live=allow_live)
    # (2) log each leg
    ibkr_log_order(res, source=source)
    legs = res.get("orders") or []
    sent_ok = bool(res.get("ok") and legs and
                   all(str(o.get("status") or "").lower() not in _REJECTED_STATUSES for o in legs))
    # (3) independent verification (sources #2–#4)
    ver = _verify_ibkr_presence(sym, [o.get("order_id") for o in legs])
    if not sent_ok:
        verdict = "rejected"          # not accepted → absence is consistent (no error)
    elif ver["independent_confirms"] >= 1:
        verdict = "verified"          # acked + ≥1 independent source = ≥2 places agree
    else:
        verdict = "UNCONFIRMED"       # acked but found nowhere → LOUD discrepancy
    ver["sent_ok"] = sent_ok
    ver["verdict"] = verdict
    ver["total_confirming_sources"] = (1 if sent_ok else 0) + ver["independent_confirms"]
    # (4) log verdict
    ibkr_log_event("order_verify", symbol=sym, action=action, qty=qty,
                   status=verdict, source=source, detail=ver)
    res["verify"] = ver
    return res


def ibkr_snapshot() -> Dict[str, Any]:
    """Pull current IBKR account / positions / open orders / today's fills and
    archive them into ibkr_log. Best-effort: returns what was captured. This is
    the backbone of long-term backtrace — call it on a schedule + on demand."""
    from agent.finance import ibkr_connector
    out: Dict[str, Any] = {"ts": _now(), "captured": {}, "errors": {}}
    snap = ibkr_connector.account_snapshot()      # ONE connection for everything
    if not snap.get("connected"):
        ibkr_log_event("snapshot_error", status="not_connected", source="snapshot",
                       detail={"error": snap.get("error", "未连接")})
        return {"ok": False, "error": snap.get("error", "未连接"), **out}
    acct_id = (snap.get("accounts") or [None])[0]

    vals = snap.get("values") or {}
    if vals:
        ibkr_log_event("account", account=acct_id, source="snapshot", detail=vals,
                       price=_safe_float(vals.get("NetLiquidation")), status="ok")
        out["captured"]["account"] = 1

    n_pos = 0
    for p in (snap.get("positions") or []):
        ibkr_log_event("position", account=p.get("account") or acct_id, symbol=p.get("symbol"),
                       qty=p.get("position"), price=p.get("avg_cost"), source="snapshot", detail=p)
        n_pos += 1
    out["captured"]["positions"] = n_pos

    n_oo = 0
    for o in (snap.get("orders") or []):
        ibkr_log_event("open_order", account=acct_id, symbol=o.get("symbol"),
                       action=o.get("action"), qty=o.get("qty"), order_type=o.get("type"),
                       price=o.get("limit") or o.get("stop"), status=o.get("status"),
                       source="snapshot", detail=o)
        n_oo += 1
    out["captured"]["open_orders"] = n_oo

    n_fill = 0
    for f in (snap.get("fills") or []):
        ibkr_log_event("fill", ext_id=f.get("exec_id"), account=f.get("account") or acct_id,
                       symbol=f.get("symbol"), action=(f.get("side") or "").upper().replace("BOT", "BUY").replace("SLD", "SELL"),
                       qty=f.get("shares"), price=f.get("price"), status="filled",
                       source="snapshot", detail=f)
        n_fill += 1
    out["captured"]["fills"] = n_fill
    out["ok"] = True
    return out


def _safe_float(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def ibkr_log_list(symbol: Optional[str] = None, kind: Optional[str] = None,
                  since: Optional[str] = None, until: Optional[str] = None,
                  limit: int = 200) -> Dict[str, Any]:
    """Query the durable IBKR archive — works even when Gateway is OFF."""
    ensure_schema()
    with connect() as conn:
        _ensure_ibkr_log(conn)
        q = "SELECT * FROM ibkr_log WHERE 1=1"
        args: List[Any] = []
        if symbol:
            q += " AND symbol = ?"; args.append(symbol.upper())
        if kind:
            q += " AND kind = ?"; args.append(kind)
        if since:
            q += " AND ts >= ?"; args.append(since)
        if until:
            q += " AND ts <= ?"; args.append(until)
        q += " ORDER BY ts DESC, id DESC LIMIT ?"; args.append(int(limit))
        rows = [dict(r) for r in conn.execute(q, args).fetchall()]
    return {"n": len(rows), "rows": rows}


# ════════════════════════════════════════════════════════════════════
#  IBKR Flex Web Service backstop — authoritative server-side statement
#  (trades/positions/cash, incl. days the Gateway was off). Token is stored
#  locally and NEVER returned by any API.
# ════════════════════════════════════════════════════════════════════
_IBKR_FLEX_DDL = """
CREATE TABLE IF NOT EXISTS ibkr_flex (
    id INTEGER PRIMARY KEY CHECK (id = 1), token TEXT, query_id TEXT, updated_at TEXT);
"""


def _ensure_flex(conn) -> None:
    conn.executescript(_IBKR_FLEX_DDL)


def flex_set_config(token: str, query_id: str) -> Dict[str, Any]:
    ensure_schema()
    with connect() as conn:
        _ensure_flex(conn)
        conn.execute("INSERT INTO ibkr_flex (id, token, query_id, updated_at) VALUES (1,?,?,?) "
                     "ON CONFLICT(id) DO UPDATE SET token=excluded.token, "
                     "query_id=excluded.query_id, updated_at=excluded.updated_at",
                     ((token or "").strip(), (query_id or "").strip(), _now()))
    return flex_config_status()


def _flex_get_config() -> Dict[str, Optional[str]]:
    """Internal — returns the raw token. Never expose via an endpoint."""
    import os
    ensure_schema()
    with connect() as conn:
        _ensure_flex(conn)
        row = conn.execute("SELECT token, query_id FROM ibkr_flex WHERE id = 1").fetchone()
    token = (dict(row).get("token") if row else None) or os.getenv("IB_FLEX_TOKEN")
    query_id = (dict(row).get("query_id") if row else None) or os.getenv("IB_FLEX_QUERY_ID")
    return {"token": token, "query_id": query_id}


def flex_config_status() -> Dict[str, Any]:
    """Safe status — reports whether configured + the (non-secret) query id,
    but NEVER the token."""
    cfg = _flex_get_config()
    return {"configured": bool(cfg["token"] and cfg["query_id"]),
            "query_id": cfg["query_id"]}


def flex_sync() -> Dict[str, Any]:
    """Pull the authoritative Flex statement and archive trades/positions/cash
    into ibkr_log. Trades dedupe on IBKR tradeID (ext_id='flex_<tradeID>'), so
    repeated syncs never double-count — this is the lossless backstop."""
    from agent.finance import ibkr_flex
    cfg = _flex_get_config()
    if not (cfg["token"] and cfg["query_id"]):
        return {"ok": False, "error": "Flex 未配置（缺 token / query id）"}
    res = ibkr_flex.fetch_statement(cfg["token"], cfg["query_id"])
    if not res.get("ok"):
        ibkr_log_event("flex_error", status="error", source="flex",
                       detail={"error": res.get("error")})
        return res
    acct = res.get("account")
    n_tr = n_pos = n_cash = 0
    for t in res.get("trades") or []:
        tid = t.get("trade_id")
        ibkr_log_event("flex_trade", ext_id=(f"flex_{tid}" if tid else None),
                       account=t.get("account") or acct, symbol=t.get("symbol"),
                       action=t.get("side"), qty=t.get("qty"), order_type="FILL",
                       price=t.get("price"), status="filled", source="flex", detail=t)
        n_tr += 1
    for p in res.get("positions") or []:
        ibkr_log_event("flex_position", account=p.get("account") or acct,
                       symbol=p.get("symbol"), qty=p.get("qty"),
                       price=p.get("cost_basis_price"), status="open",
                       source="flex", detail=p)
        n_pos += 1
    for c in res.get("cash") or []:
        ibkr_log_event("flex_cash", account=c.get("account") or acct,
                       price=c.get("ending_cash"), status=c.get("currency"),
                       source="flex", detail=c)
        n_cash += 1
    return {"ok": True, "account": acct,
            "archived": {"trades": n_tr, "positions": n_pos, "cash": n_cash}}


def _exec_key(symbol, action, qty, price) -> Optional[tuple]:
    """Canonical key for matching an execution across two sources. Qty is made
    positive; price rounded to the cent. Returns None if too sparse to match."""
    sym = (symbol or "").upper()
    act = (action or "").upper()
    act = "BUY" if act in ("BUY", "BOT") else ("SELL" if act in ("SELL", "SLD") else act)
    try:
        q = abs(round(float(qty)))
        p = round(float(price), 2)
    except (TypeError, ValueError):
        return None
    if not sym or not act or q == 0:
        return None
    return (sym, act, q, p)


def flex_reconcile(sync: bool = True) -> Dict[str, Any]:
    """Cross-check our locally-logged executions against IBKR's authoritative
    Flex statement → prove the archive is complete.

    Compares (as multisets, keyed on symbol/side/qty/price):
      • flex_trade rows (authoritative IBKR books)
      • our live 'fill' rows (captured via snapshots / reqExecutions)
    Reports:
      matched      — present in both (good)
      flex_only    — in IBKR but we never logged live → the backstop caught it
      local_only   — we logged but not (yet) in Flex → usually same-day lag
    Pending (un-filled) orders are excluded — they aren't trades yet."""
    from collections import Counter
    out: Dict[str, Any] = {}
    if sync:
        out["sync"] = flex_sync()
        if not out["sync"].get("ok"):
            return {"ok": False, "error": out["sync"].get("error"), **out}
    ensure_schema()
    with connect() as conn:
        _ensure_ibkr_log(conn)
        flex_rows = [dict(r) for r in conn.execute(
            "SELECT symbol, action, qty, price, detail FROM ibkr_log WHERE kind = 'flex_trade'").fetchall()]
        fill_rows = [dict(r) for r in conn.execute(
            "SELECT symbol, action, qty, price, detail FROM ibkr_log WHERE kind = 'fill'").fetchall()]

    def keys(rows):
        c = Counter()
        unkeyed = 0
        for r in rows:
            k = _exec_key(r.get("symbol"), r.get("action"), r.get("qty"), r.get("price"))
            if k is None:
                unkeyed += 1
            else:
                c[k] += 1
        return c, unkeyed

    flex_c, flex_unk = keys(flex_rows)
    fill_c, fill_unk = keys(fill_rows)

    matched = flex_c & fill_c          # multiset intersection
    flex_only = flex_c - fill_c
    local_only = fill_c - flex_c

    def fmt(counter):
        return [{"symbol": k[0], "side": k[1], "qty": k[2], "price": k[3], "count": n}
                for k, n in sorted(counter.items())]

    n_match = sum(matched.values())
    n_flex_only = sum(flex_only.values())
    n_local_only = sum(local_only.values())
    return {"ok": True,
            "summary": {"flex_trades": sum(flex_c.values()), "local_fills": sum(fill_c.values()),
                        "matched": n_match, "flex_only": n_flex_only, "local_only": n_local_only,
                        "flex_unkeyed": flex_unk, "local_unkeyed": fill_unk,
                        "complete": n_flex_only == 0},
            "flex_only": fmt(flex_only), "local_only": fmt(local_only),
            **({k: v for k, v in out.items() if k == "sync"})}


def flatten_paper(project_id: str) -> Dict[str, Any]:
    """Panic-close every open position. Emergency brake — VENUE-AWARE: in
    venue=ibkr it closes the REAL IBKR positions (cancel each bracket + GTC
    limit sell), not the internal sim engine (which would be empty)."""
    if current_venue() == "ibkr":
        return _flatten_ibkr()
    from agent.finance.paper_trading import (
        get_project_engine, save_project_engine, OrderSide, OrderType,
    )
    eng = get_project_engine(project_id)
    closed = []
    for pos in list(eng.get_all_positions()):
        if pos.quantity <= 0:
            continue
        px = _latest_price(pos.symbol)
        if px:
            eng.update_price(pos.symbol, px)
        order = eng.place_order(pos.symbol, OrderSide.SELL, pos.quantity, OrderType.MARKET)
        closed.append({"symbol": pos.symbol, "qty": pos.quantity,
                       "status": getattr(order.status, "value", str(order.status))})
    save_project_engine(project_id)
    return {"flattened": len(closed), "positions": closed, "venue": "sim"}


def _flatten_ibkr() -> Dict[str, Any]:
    """Panic-flatten the REAL IBKR account: cancel ALL resting orders (kills
    every bracket) then place a GTC limit SELL for each open position at the
    current quote. Limit (not market) honors the TPS red line; it's priced at
    the bid so it's marketable. Every action is logged durably."""
    from agent.finance import ibkr_connector
    allow_live = bool(get_state().get("allow_live"))
    cancel = ibkr_connector.cancel_all_paper(allow_live=allow_live)
    ibkr_log_event("flatten_cancel", status=("ok" if cancel.get("ok") else "error"),
                   source="flatten", detail=cancel)
    snap = ibkr_connector.account_snapshot()
    closed = []
    for p in (snap.get("positions") or []):
        sym = p.get("symbol"); qty = int(p.get("position") or 0)
        if qty <= 0:
            continue
        q = (ibkr_connector.quote(sym) or {}).get("quote") or {}
        px = q.get("bid") or q.get("last") or q.get("close") or p.get("avg_cost")
        res = place_log_verify(sym, "SELL", qty,
                               limit_price=round(float(px), 2) if px else None,
                               source="flatten")
        closed.append({"symbol": sym, "qty": qty,
                       "verdict": (res.get("verify") or {}).get("verdict")})
    return {"flattened": len(closed), "positions": closed, "venue": "ibkr",
            "cancelled": cancel.get("cancelled")}


def _latest_price(symbol: str) -> Optional[float]:
    try:
        bars = _fetch_bars(symbol, "1d", "5d")
        return bars[-1]["close"] if bars else None
    except Exception:
        return None


def refresh_positions(project_id: str) -> Dict[str, Any]:
    """Feed the latest price for every held position + open order into the
    paper engine. This is what makes stop/target/OCO settle automatically:
    update_price() triggers any pending order that has crossed its level
    (and OCO cancels the sibling). The last piece of the closed loop."""
    from agent.finance.paper_trading import get_project_engine, save_project_engine
    eng = get_project_engine(project_id)
    syms = set(eng.account.positions.keys())
    for o in eng.get_open_orders():
        syms.add(o.symbol)
    updated, fills_before = [], _count_fills(eng)
    for sym in sorted(syms):
        px = _latest_price(sym)
        if px:
            eng.update_price(sym, px)   # may trigger stop/limit/OCO fills
            updated.append({"symbol": sym, "price": round(px, 2)})
    settled = _count_fills(eng) - fills_before
    if updated:
        save_project_engine(project_id)
    return {"updated": updated, "n": len(updated), "orders_settled": max(0, settled)}


def _count_fills(eng) -> int:
    from agent.finance.paper_trading import OrderStatus
    return sum(1 for o in eng.orders.values() if o.status == OrderStatus.FILLED)


def _kill_switch_metrics_ibkr() -> Tuple[float, int]:
    """(drawdown_pct_from_peak, consecutive_losses) for the live IBKR account.
    Drawdown is measured vs a persisted NetLiq high-water mark; consecutive
    losses come from the most-recent closed journal entries' return_pct."""
    from agent.finance import ibkr_connector
    acc = ibkr_connector.account()
    netliq = _safe_float((acc.get("values") or {}).get("NetLiquidation"))
    dd_pct = 0.0
    if netliq and netliq > 0:
        st = get_state()
        hwm = float(st.get("ibkr_hwm") or 0)
        hwm = max(hwm, netliq)
        with connect() as conn:    # persist the peak
            conn.execute("UPDATE trading_state SET ibkr_hwm = ?, updated_at = ? WHERE id = 1",
                         (hwm, _now()))
        dd_pct = (netliq / hwm - 1) * 100 if hwm else 0.0
    # consecutive losing CLOSED trades (newest first)
    consec = 0
    closed = [j for j in journal_list(200) if j.get("status") == "closed"]
    closed.sort(key=lambda j: (j.get("exit_date") or j.get("updated_at") or ""), reverse=True)
    for j in closed:
        r = j.get("return_pct")
        if r is not None and r < 0:
            consec += 1
        else:
            break
    return round(dd_pct, 2), consec


def check_kill_switch(project_id: str) -> Dict[str, Any]:
    """Auto-detect a policy breach (drawdown / consecutive losses vs TPS
    thresholds). If breached → auto-set global_halt. VENUE-AWARE: in venue=ibkr
    it measures the REAL IBKR account (drawdown from a NetLiq high-water mark +
    consecutive losing closed-journal trades), not the empty sim engine."""
    tps = tps_seed_if_empty() or {}
    rr = tps.get("risk_rules") or {}
    dd_limit = float(rr.get("kill_switch_dd_pct", 20))
    consec_limit = int(rr.get("kill_switch_consec_losses", 4))

    if current_venue() == "ibkr":
        total_pnl_pct, consec = _kill_switch_metrics_ibkr()
    else:
        from agent.finance.paper_trading import get_project_engine
        eng = get_project_engine(project_id)
        summ = eng.get_account_summary()
        total_pnl_pct = summ.get("total_pnl_pct")
        if total_pnl_pct is None:
            equity = summ.get("total_value") or summ.get("equity") or 0
            init = summ.get("initial_capital") or 100000
            total_pnl_pct = (equity / init - 1) * 100 if init else 0
        trades = sorted(eng.get_trade_history(), key=lambda t: t.timestamp or datetime.min)
        consec = 0
        for t in reversed(trades):
            pnl = getattr(t, "realized_pnl", None)
            if pnl is None:
                pnl = getattr(t, "pnl", 0)
            if pnl is not None and pnl < 0:
                consec += 1
            else:
                break

    breached = (total_pnl_pct <= -dd_limit) or (consec >= consec_limit)
    reason = None
    if breached:
        reason = (f"kill-switch: 回撤 {total_pnl_pct:.1f}% (限 -{dd_limit}%)"
                  if total_pnl_pct <= -dd_limit else
                  f"kill-switch: 连亏 {consec} 笔 (限 {consec_limit})")
        if not get_state().get("global_halt"):
            set_halt(True, reason, by="kill_switch")
    return {"breached": breached, "reason": reason,
            "total_pnl_pct": round(total_pnl_pct, 1), "consecutive_losses": consec,
            "dd_limit_pct": dd_limit, "consec_limit": consec_limit}


# ════════════════════════════════════════════════════════════════════
#  ④b MARKET REGIME / RISK-OFF (portfolio-level hedge, long-only friendly)
# ════════════════════════════════════════════════════════════════════


def market_regime() -> Dict[str, Any]:
    """Risk-on/risk-off from the broad market (SPY vs its 200-day SMA). When
    risk-off, the scan stops opening NEW positions (and suggests raising cash
    / protective puts). This is the long-only hedge: don't fight a downtrend."""
    try:
        bars = _fetch_bars("SPY", "1d", "2y")
        closes = [b["close"] for b in bars]
        sma200 = ti.sma(closes, 200)
        last, ma = closes[-1], sma200[-1]
        if ma is None:
            return {"regime": "unknown", "note": "SPY 数据不足"}
        risk_off = last < ma
        return {"regime": "risk_off" if risk_off else "risk_on",
                "spy": round(last, 2), "spy_sma200": round(ma, 2),
                "note": ("大盘 SPY 跌破 200 日线 → risk-off：停新仓，考虑提现金/保护性 put"
                         if risk_off else "大盘 SPY 在 200 日线上方 → risk-on")}
    except Exception as exc:
        return {"regime": "unknown", "note": f"regime 检测失败: {exc}"}


# ════════════════════════════════════════════════════════════════════
#  ⑥b PRE-TRADE VALIDATION (catch anomalies BEFORE execution)
# ════════════════════════════════════════════════════════════════════


def validate_order(symbol: str, qty: int, entry_px: float, stop_px: float,
                   target_px: float, equity: float, max_pos_pct: float,
                   held: Optional[set] = None, last_px: Optional[float] = None) -> Dict[str, Any]:
    """Pre-flight checks. Returns {ok, blocks:[...], warnings:[...]}. A block
    means do NOT execute; a warning is advisory."""
    blocks: List[str] = []
    warnings: List[str] = []
    if qty < 1:
        blocks.append("数量<1（风险预算/价格导致仓位过小）")
    if stop_px is None or stop_px >= entry_px:
        blocks.append(f"止损无效（stop {stop_px} ≥ 进场 {entry_px}）— 无保护")
    if target_px is not None and target_px <= entry_px:
        blocks.append(f"目标无效（target {target_px} ≤ 进场 {entry_px}）— 无上行")
    notional = qty * entry_px
    if equity and notional > equity * (max_pos_pct / 100.0) * 1.05:
        blocks.append(f"仓位 ${notional:,.0f} 超单仓上限 {max_pos_pct}%（${equity*max_pos_pct/100:,.0f}）")
    if last_px and entry_px and abs(entry_px / last_px - 1) > 0.05:
        warnings.append(f"进场价 {entry_px} 偏离最新价 {last_px} >5%（数据陈旧/跳空？）")
    if held:
        corr = _correlated_holding(symbol, held)
        if corr:
            warnings.append(f"与持仓 {corr['with']} 相关 {corr['corr']}（集中风险）")
    return {"ok": len(blocks) == 0, "blocks": blocks, "warnings": warnings}


def validate_setup_spec(spec: Dict[str, Any], symbol: str = "AAPL") -> Dict[str, Any]:
    """Sanity-check a setup's spec for anomalies (never/always triggers,
    missing exits) before it's armed."""
    issues: List[str] = []
    conds = (spec.get("entry") or {}).get("conditions") or []
    if not conds:
        issues.append("无进场条件")
    exit_cfg = spec.get("exit") or {}
    if not exit_cfg.get("stop"):
        issues.append("无止损")
    if not exit_cfg.get("target") and not exit_cfg.get("time_stop_bars"):
        issues.append("无目标也无 time-stop（可能永不出场）")
    try:
        res = evaluate_spec({**spec, "lookback": "2y"}, symbol)
        if not res.get("error"):
            n = res.get("stats", {}).get("n_trades", 0)
            bars = res.get("n_bars", 0)
            if n == 0:
                issues.append(f"在 {symbol} 2年内 0 次触发（条件可能太严/永不满足）")
            elif bars and n > bars * 0.3:
                issues.append(f"触发过于频繁（{n} 次/{bars} bar）— 条件可能太松")
    except Exception:
        pass
    return {"ok": len(issues) == 0, "issues": issues}


# ════════════════════════════════════════════════════════════════════
#  ④c AUTO-RETIRE UNDERPERFORMERS + IMPROVEMENT SUGGESTIONS
# ════════════════════════════════════════════════════════════════════


def review_setups(auto_retire: bool = True) -> Dict[str, Any]:
    """Check each armed setup's backtest stats; auto-RETIRE clear losers
    (per user decision: auto-retire OK), and emit improvement SUGGESTIONS for
    everything (changes require human approval — never auto-applied)."""
    retired, suggestions = [], []
    for s in setups_list():
        if s.get("status") not in ("paper", "live"):
            continue
        st = s.get("backtest_stats") or {}
        n = st.get("n_trades") or 0
        avg_r = st.get("avg_R")
        win = st.get("win_rate")
        rob = (st.get("robustness") or {}).get("verdict")
        name = s["name"]

        breach = None
        if rob == "overfit":
            breach = "样本外过拟合"
        elif n >= 10 and avg_r is not None and avg_r < 0:
            breach = f"期望为负 (avgR {avg_r}, {n} 笔)"
        if breach:
            if auto_retire:
                setup_save(s["setup_id"], {"status": "retired"}, change_note=f"auto-retire: {breach}")
                retired.append({"setup_id": s["setup_id"], "name": name, "reason": breach})
            continue

        # suggestions (advisory only)
        tips = []
        if n == 0:
            tips.append("0 触发 → 放宽阈值或换更长 lookback / 更大 timeframe")
        elif n < 5:
            tips.append("样本太少 → 放宽条件或在更多标的回测，结论不可信")
        if win is not None and win < 40 and avg_r is not None and avg_r < 0.2:
            tips.append("低胜率+低期望 → 收紧入场过滤（加趋势/动量确认）或提高盈亏比")
        if rob == "weak":
            tips.append("样本外偏弱 → 减少条件数（防过拟合）/ 在更多标的验证")
        if tips:
            suggestions.append({"setup_id": s["setup_id"], "name": name, "tips": tips})
    return {"retired": retired, "suggestions": suggestions,
            "n_retired": len(retired), "n_suggestions": len(suggestions)}


# ════════════════════════════════════════════════════════════════════
#  ⑤ AUTO PAPER ENTRY (triggers → orders), gated by brakes
# ════════════════════════════════════════════════════════════════════


def _position_qty(entry_px: float, stop_px: float, account_equity: float,
                  risk_pct: float, max_pos_pct: float) -> int:
    """Risk-based sizing: risk_pct of equity / per-share risk, capped by
    max_pos_pct of equity. Returns whole shares (≥0)."""
    per_share_risk = max(entry_px - stop_px, entry_px * 0.005)
    risk_budget = account_equity * (risk_pct / 100.0)
    qty = int(risk_budget / per_share_risk)
    max_qty = int((account_equity * (max_pos_pct / 100.0)) / entry_px)
    return max(0, min(qty, max_qty))


def _parse_date(s) -> Optional["date"]:
    from datetime import datetime
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s)[:10]).date()
    except Exception:
        return None


def _time_stop_for_setup(setup_name: Optional[str], specs: Dict[str, Dict]) -> int:
    """Resolve a journal entry's setup name → its time_stop_bars. Handles
    'combo/member' names. 0 = no time stop."""
    if not setup_name:
        return 0
    candidates = [setup_name]
    if "/" in setup_name:
        candidates.append(setup_name.split("/")[-1])
    for key in candidates:
        spec = specs.get(key)
        if spec:
            return int((spec.get("exit") or {}).get("time_stop_bars") or 0)
    return 0


def _enforce_time_stops_ibkr(positions: List[Dict[str, Any]], act: bool) -> List[Dict[str, Any]]:
    """IBKR brackets have stop+target but NO time exit, so the backtest's
    time_stop_bars would be silently dropped in venue=ibkr. This enforces it:
    for each IBKR position past its setup's time_stop (in trading days), cancel
    the resting bracket + place a GTC LIMIT close (never market — TPS red line).
    When act=False (disarmed/halted) it only flags. Best-effort; never raises."""
    from datetime import datetime, timezone
    exits: List[Dict[str, Any]] = []
    if not positions:
        return exits
    try:
        jmap: Dict[str, Dict] = {}
        for j in journal_list(200):           # DESC → first per symbol = newest open
            if j.get("status") == "open" and j.get("symbol"):
                jmap.setdefault(j["symbol"].upper(), j)
        specs = {s["name"]: (s.get("quant_spec") or {}) for s in setups_list()}
        allow_live = bool(get_state().get("allow_live"))
        from agent.finance import ibkr_connector
    except Exception:
        logger.exception("time-stop setup failed")
        return exits

    for p in positions:
        sym = (p.get("symbol") or "").upper()
        qty = int(p.get("position") or 0)
        j = jmap.get(sym)
        if qty <= 0 or not j:
            continue
        ts_bars = _time_stop_for_setup(j.get("setup_name"), specs)
        entry_dt = _parse_date(j.get("entry_date"))
        if not ts_bars or not entry_dt:
            continue
        cal_days = (datetime.now(timezone.utc).date() - entry_dt).days
        trading_days = int(cal_days * 5 / 7)        # ~trading days
        if trading_days < ts_bars:
            continue
        rec = {"symbol": sym, "qty": qty, "cal_days": cal_days,
               "trading_days": trading_days, "time_stop_bars": ts_bars}
        if not act:
            rec["action"] = "flag_only(未武装/已停止)"
            exits.append(rec)
            continue
        try:
            ibkr_connector.cancel_symbol_orders(sym, allow_live=allow_live)
            q = (ibkr_connector.quote(sym) or {}).get("quote") or {}
            px = q.get("bid") or q.get("last") or q.get("close") or p.get("avg_cost")
            sell = place_log_verify(sym, "SELL", qty,
                                    limit_price=round(float(px), 2) if px else None,
                                    source="time_stop")
            rec["close_verdict"] = (sell.get("verify") or {}).get("verdict")
            ibkr_log_event("time_stop_exit", symbol=sym, action="SELL", qty=qty,
                           price=round(float(px), 2) if px else None, status="placed",
                           source="time_stop", detail=rec)
        except Exception as exc:
            rec["error"] = f"{type(exc).__name__}: {exc}"
            ibkr_log_event("time_stop_exit", symbol=sym, action="SELL", qty=qty,
                           status="error", source="time_stop", detail=rec)
        exits.append(rec)
    return exits


_SCAN_LOCK = threading.Lock()


def scan_and_trade(project_id: str, symbols: Optional[List[str]] = None,
                   auto_execute: bool = True) -> Dict[str, Any]:
    """Public entry — serialized: only ONE scan runs at a time. Two concurrent
    scans (e.g. the daily cron firing while a manual scan runs) would each read
    `held` before either placed, and double-enter the same symbol. The lock
    makes the second caller bail out cleanly instead."""
    if not _SCAN_LOCK.acquire(blocking=False):
        return {"error": "扫描已在进行中（避免重复下单），请稍候再试",
                "n_triggers": 0, "n_executed": 0, "triggers": [], "executed": [],
                "scanned": 0}
    try:
        return _scan_and_trade_impl(project_id, symbols, auto_execute)
    finally:
        _SCAN_LOCK.release()


def _scan_and_trade_impl(project_id: str, symbols: Optional[List[str]] = None,
                         auto_execute: bool = True) -> Dict[str, Any]:
    """Scan active armed setups for entry triggers on the latest bar; for
    each, optionally auto-place a risk-sized BUY + protective bracket. Gated by
    global_halt + per-setup status + not already holding. Runs kill-switch first."""
    from agent.finance.paper_trading import (
        get_project_engine, save_project_engine, OrderSide, OrderType,
    )
    if symbols is None:
        symbols = _watchlist_symbols()

    state = get_state()
    venue = state.get("venue") or "sim"
    ks = check_kill_switch(project_id)
    regime = market_regime()
    # FAIL-CLOSED: only 'risk_on' permits new entries. 'risk_off' AND 'unknown'
    # (data fetch failed) both block — never open new positions when we can't
    # confirm the market regime (TPS red line: risk-off 停新仓).
    regime_state = regime.get("regime")
    block_new_regime = regime_state != "risk_on"
    risk_off = regime_state == "risk_off"
    halted = bool(state.get("global_halt"))
    auto_armed = bool(state.get("auto_trade"))
    if not auto_armed:
        auto_execute = False   # master disconnect → report-only

    eng = get_project_engine(project_id)
    venue_note = None
    time_stop_exits: List[Dict[str, Any]] = []
    if venue == "ibkr":
        # IBKR is the single source of truth: size off real NetLiquidation,
        # `held` from real IBKR positions. IBKR settles its own OCO brackets,
        # so we do NOT run the internal-engine refresh — we snapshot instead.
        from agent.finance import ibkr_connector
        snap = ibkr_connector.account_snapshot()       # ONE connection
        if not snap.get("connected"):
            auto_execute = False
            venue_note = f"IBKR 未连接，扫描只读: {(snap.get('error') or '')[:60]}"
        equity = _safe_float((snap.get("values") or {}).get("NetLiquidation")) or 0
        held = {p["symbol"] for p in (snap.get("positions") or []) if (p.get("position") or 0) > 0}
        # P3: a resting (unfilled) BUY entry must ALSO block re-entry, else the
        # next scan would place a duplicate order for the same symbol.
        held |= {o["symbol"] for o in (snap.get("orders") or [])
                 if (o.get("action") or "").upper() == "BUY"}
        # P4: enforce time-stop exits on aged IBKR positions before new entries
        time_stop_exits = _enforce_time_stops_ibkr(snap.get("positions") or [],
                                                   act=(auto_execute and not halted))
        refresh = {"ok": True, "via": "account_snapshot"}  # the snapshot below archives
        # PERF: pre-warm bars for ALL scan symbols in ONE connection per distinct
        # (interval,period) the armed setups actually use — else the venue=ibkr
        # scan opens a socket per symbol → 60s+. Cache keys must match what
        # _fetch_bars(prefer_ibkr) computes, so we use the same interval/period.
        if snap.get("connected"):
            all_syms = set(symbols)
            armed = [s for s in setups_list() if s.get("status") in ("paper", "live")
                     and isinstance(s.get("quant_spec"), dict)]
            for c in combos_list():
                if c.get("status") in ("paper", "live"):
                    all_syms.update(c.get("symbols") or [])
            combos = {ip for s in armed for ip in [(
                _TF_TO_YF.get((s["quant_spec"].get("timeframe") or "1d").lower(), ("1d", "1y"))[0],
                s["quant_spec"].get("lookback")
                or _TF_TO_YF.get((s["quant_spec"].get("timeframe") or "1d").lower(), ("1d", "1y"))[1],
            )]}
            try:
                import time as _t
                for interval, period in combos:
                    bm = ibkr_connector.bars_multi(
                        sorted(all_syms),
                        duration=_YF_TO_IBKR_DUR.get(period, "1 Y"),
                        bar_size=_YF_TO_IBKR_BAR.get(interval, "1 day"))
                    if bm.get("connected"):
                        for s, bb in (bm.get("bars") or {}).items():
                            if bb:
                                _BARS_CACHE[f"IB:{s}|{interval}|{period}"] = (_t.monotonic(), bb)
            except Exception:
                logger.exception("bars_multi pre-warm failed")
    else:
        # sim venue: settle internal OCO first so exits free capital + clear held
        refresh = refresh_positions(project_id)
        summ = eng.get_account_summary()
        equity = summ.get("total_value") or summ.get("equity") or summ.get("initial_capital") or 100000
        held = {p.symbol for p in eng.get_all_positions() if p.quantity > 0}

    tps = tps_seed_if_empty() or {}
    rr = tps.get("risk_rules") or {}
    risk_pct = float(rr.get("risk_per_trade_pct", 1.0))
    max_pos_pct = float(rr.get("max_pos_pct", 5.0))
    # P1: risk_pct / max_pos_pct apply to the RING-FENCED budget, NOT the full
    # NetLiquidation. Budget = explicit trading_budget_usd, else budget_pct × equity.
    trading_budget = _resolve_budget(equity)

    triggers: List[Dict[str, Any]] = []
    executed: List[Dict[str, Any]] = []

    use_ib_bars = (venue == "ibkr")   # align trigger data with execution venue

    def try_enter(spec, sym, source_name, weight=1.0):
        """Shared entry path for both standalone setups and combo members."""
        try:
            fired = _entry_on_last_bar(spec, sym, prefer_ibkr=use_ib_bars)
        except Exception:
            fired = None
        if not fired:
            return
        entry_px = fired["close"]
        stop_px = _stop_for(spec, sym, entry_px, prefer_ibkr=use_ib_bars)
        trig = {"setup_name": source_name, "symbol": sym, "as_of": fired["date"],
                "entry_px": entry_px, "stop_px": round(stop_px, 2), "weight": weight}
        triggers.append(trig)
        if not auto_execute:
            return
        if halted:
            trig["skipped"] = "global_halt"; return
        if block_new_regime:
            trig["skipped"] = ("risk_off (大盘<200日线，停新仓)" if risk_off
                               else f"regime 无法核实({regime.get('note','')[:40]})—守红线不开新仓")
            return
        if sym in held:
            trig["skipped"] = "already_holding"; return
        # earnings guard (TPS red line: 不持仓过 earnings) — fail-CLOSED
        eb = _earnings_block(sym)
        if eb:
            trig["skipped"] = eb.get("reason") or (
                f"临近财报 {eb.get('date')} ({eb.get('days_until')}d) — 不持仓过 earnings")
            trig["earnings"] = eb; return
        corr = _correlated_holding(sym, held)
        if corr:
            trig["skipped"] = f"与持仓 {corr['with']} 相关 {corr['corr']} (集中风险)"
            trig["correlation"] = corr; return
        # weight scales the risk budget (combo members can be weighted).
        # sizing + validation use the ring-fenced budget, not full equity (P1).
        qty = _position_qty(entry_px, stop_px, trading_budget, risk_pct * weight, max_pos_pct * weight)
        target_px = _target_for(spec, entry_px, stop_px)
        v = validate_order(sym, qty, entry_px, stop_px, target_px, trading_budget, max_pos_pct,
                           held=held, last_px=entry_px)
        if not v["ok"]:
            trig["skipped"] = "pre-trade 拦截: " + "; ".join(v["blocks"]); return
        if v["warnings"]:
            trig["warnings"] = v["warnings"]
        target_px = round(target_px, 2); stop_px2 = round(stop_px, 2)

        if venue == "ibkr":
            # IDENTICAL path to real money — only the account differs (DU paper
            # vs U live). LIMIT entry at the signal close (TPS红线: 永远 limit,
            # 让市场来找你, 不追价) — GTC is set in the connector.
            ib_res = place_log_verify(sym, "BUY", qty, limit_price=round(entry_px, 2),
                                      stop_loss=stop_px2, take_profit=target_px, source="auto")
            ver = ib_res.get("verify") or {}
            placed = bool(ver.get("sent_ok"))
            exec_row = {**trig, "qty": qty, "target_px": target_px, "venue": "ibkr",
                        "entry_status": ("placed" if placed else "rejected"),
                        "ibkr_verdict": ver.get("verdict"), "ibkr": ib_res,
                        "stop_placed": placed, "target_placed": placed}
            executed.append(exec_row)
            if placed:
                held.add(sym)
                try:
                    journal_add_from_entry(sym, source_name, entry_px, stop_px2, target_px,
                                           thesis=f"{source_name} 信号触发 @ {entry_px} (IBKR)")
                except Exception:
                    logger.exception("journal_add_from_entry failed for %s", sym)
                _send_telegram(f"⚡ 自动进场(IBKR) {sym} ×{qty} @ {entry_px}\n来源: {source_name}\n"
                               f"🛡 stop {stop_px2} · 🎯 target {target_px} · 核对 {ver.get('verdict')}")
            return

        # ── sim venue: internal engine (offline/instant) ──
        eng.update_price(sym, entry_px)
        o1 = eng.place_order(sym, OrderSide.BUY, qty, OrderType.MARKET)
        ok = getattr(o1.status, "value", str(o1.status)) not in ("rejected",)
        stop_order = tgt_order = None
        if ok:
            import uuid as _uuid
            grp = _uuid.uuid4().hex[:8]
            stop_order = eng.place_order(sym, OrderSide.SELL, qty, OrderType.STOP, stop_price=stop_px2)
            stop_order.metadata["oco_group"] = grp
            tgt_order = eng.place_order(sym, OrderSide.SELL, qty, OrderType.LIMIT, price=target_px)
            tgt_order.metadata["oco_group"] = grp
            held.add(sym)
        exec_row = {**trig, "qty": qty, "target_px": target_px, "venue": "sim",
                    "entry_status": getattr(o1.status, "value", str(o1.status)),
                    "stop_placed": stop_order is not None, "target_placed": tgt_order is not None}
        executed.append(exec_row)
        if ok:
            try:
                journal_add_from_entry(sym, source_name, entry_px, stop_px2, target_px,
                                       thesis=f"{source_name} 信号触发 @ {entry_px}")
            except Exception:
                pass
            _send_telegram(f"⚡ 自动进场(sim) {sym} ×{qty} @ {entry_px}\n来源: {source_name}\n"
                           f"🛡 stop {stop_px2} · 🎯 target {target_px} (OCO)")

    # 1) standalone armed setups → watchlist symbols
    for s in setups_list():
        if s.get("status") not in ("paper", "live"):
            continue
        spec = s.get("quant_spec")
        if not isinstance(spec, dict) or not (spec.get("entry") or {}).get("conditions"):
            continue
        for sym in symbols:
            try_enter(spec, sym, s["name"], weight=1.0)

    # 2) armed combos → their assigned symbols, member specs weighted
    setup_by_id = {s["setup_id"]: s for s in setups_list()}
    for c in combos_list():
        if c.get("status") not in ("paper", "live"):
            continue
        c_syms = c.get("symbols") or []
        for mem in (c.get("members") or []):
            ms = setup_by_id.get(mem.get("setup_id"))
            if not ms or not isinstance(ms.get("quant_spec"), dict):
                continue
            w = float(mem.get("weight") or 1.0)
            for sym in c_syms:
                try_enter(ms["quant_spec"], sym, f"{c['name']}/{ms['name']}", weight=w)

    if venue == "sim" and executed:
        save_project_engine(project_id)
    # archive a full IBKR snapshot after an IBKR-venue scan — never silent
    if venue == "ibkr" and executed:
        try:
            ibkr_snapshot()
        except Exception as exc:
            try:
                ibkr_log_event("snapshot_error", status="exception", source="scan",
                               detail={"error": f"{type(exc).__name__}: {exc}"})
            except Exception:
                logger.exception("snapshot + snapshot_error logging both failed")
    return {"halted": halted, "kill_switch": ks, "refresh": refresh,
            "regime": regime, "risk_off": risk_off, "venue": venue, "venue_note": venue_note,
            "n_triggers": len(triggers), "triggers": triggers,
            "n_executed": len(executed), "executed": executed,
            "time_stop_exits": time_stop_exits, "scanned": len(symbols)}


def _stop_for(spec: Dict[str, Any], symbol: str, entry_px: float,
              prefer_ibkr: bool = False) -> float:
    """Compute the stop price the way evaluate_spec does (atr/pct)."""
    stop_cfg = (spec.get("exit") or {}).get("stop") or {"type": "pct", "value": 5.0}
    if stop_cfg.get("type") == "atr":
        try:
            bars = _fetch_bars(symbol, _TF_TO_YF.get((spec.get("timeframe") or "1d").lower(), ("1d", "1y"))[0],
                               spec.get("lookback") or "1y", prefer_ibkr=prefer_ibkr)
            ohlc = {k: [b[k] for b in bars] for k in ("open", "high", "low", "close", "volume")}
            atr_s = _series_for_operand("atr(14)", ohlc)
            a = atr_s[-1] if atr_s and atr_s[-1] is not None else entry_px * 0.02
        except Exception:
            a = entry_px * 0.02
        return entry_px - float(stop_cfg.get("value", 2.0)) * a
    return entry_px * (1 - float(stop_cfg.get("value", 5.0)) / 100.0)


def _target_for(spec: Dict[str, Any], entry_px: float, stop_px: float) -> float:
    """Take-profit price (rr multiple of risk, or pct)."""
    tcfg = (spec.get("exit") or {}).get("target") or {"type": "rr", "value": 2.0}
    risk = max(entry_px - stop_px, 1e-9)
    if tcfg.get("type") == "rr":
        return entry_px + float(tcfg.get("value", 2.0)) * risk
    return entry_px * (1 + float(tcfg.get("value", 10.0)) / 100.0)


def _send_telegram(text: str) -> bool:
    """Fire-and-forget Telegram alert to the configured admin chat(s).
    Gracefully no-ops if TELEGRAM_BOT_TOKEN / TELEGRAM_ADMIN_USERS unset
    (chat ids are PII → only ever read from env, never stored in source)."""
    import os
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_env = (os.getenv("TRADING_ALERT_CHAT_ID")
                or os.getenv("TELEGRAM_ADMIN_USERS") or "").strip()
    if not token or not chat_env:
        return False
    chat_ids = [c.strip() for c in chat_env.split(",") if c.strip()]
    ok = False
    try:
        import httpx
        with httpx.Client(timeout=8.0) as c:
            for cid in chat_ids:
                r = c.post(f"https://api.telegram.org/bot{token}/sendMessage",
                           json={"chat_id": cid, "text": text})
                ok = ok or (r.status_code == 200)
    except Exception as exc:
        logger.debug("telegram alert failed: %s", exc)
    return ok


def chart_data(spec: Dict[str, Any], symbol: str) -> Dict[str, Any]:
    """Close series + trade markers for visualizing where a setup fired.
    Reuses evaluate_spec for the trades; returns a downsampled close line."""
    res = evaluate_spec(spec, symbol)
    if res.get("error"):
        return {"error": res["error"], "symbol": symbol}
    tf = (spec.get("timeframe") or "1d").lower()
    interval, default_period = _TF_TO_YF.get(tf, ("1d", "1y"))
    bars = _fetch_bars(symbol, interval, spec.get("lookback") or default_period)
    series = [{"date": b["date"][:10], "close": round(b["close"], 2)} for b in bars]
    # cap to ~240 points for a compact sparkline-ish chart
    if len(series) > 240:
        step = len(series) // 240 + 1
        series = series[::step]
    return {"symbol": symbol, "series": series,
            "trades": res.get("trades", []), "stats": res.get("stats", {}),
            "is_stats": res.get("is_stats"), "oos_stats": res.get("oos_stats"),
            "robustness": res.get("robustness"), "oos_cutoff": res.get("oos_cutoff")}


# ════════════════════════════════════════════════════════════════════
#  ⑥ SCORING (跑分) — auto-rank setups by expectancy
# ════════════════════════════════════════════════════════════════════


def compare_setups(symbol: str, lookback: str = "3y") -> Dict[str, Any]:
    """Run EVERY setup on the SAME symbol + period so they can be compared
    head-to-head on a common basis (the leaderboard score uses each setup's
    own saved backtest which may be on different symbols — this is apples-to-
    apples). Returns rows sorted by expectancy (avg_R)."""
    sym = symbol.upper()
    rows: List[Dict[str, Any]] = []
    for s in setups_list():
        spec = s.get("quant_spec")
        if not isinstance(spec, dict) or not (spec.get("entry") or {}).get("conditions"):
            continue
        spec = {**spec, "lookback": lookback}   # force common period
        try:
            res = evaluate_spec(spec, sym)
        except Exception as exc:
            logger.debug("compare %s/%s failed: %s", s.get("setup_id"), sym, exc)
            continue
        if res.get("error"):
            rows.append({"setup_id": s["setup_id"], "name": s["name"],
                         "status": s.get("status"), "stats": {"n_trades": 0},
                         "score": None, "error": res["error"]})
            continue
        stats = res.get("stats", {})
        rows.append({"setup_id": s["setup_id"], "name": s["name"],
                     "status": s.get("status"), "stats": stats,
                     "score": setup_score(stats)})
    rows.sort(key=lambda r: (r.get("score") or {}).get("score", -1e9), reverse=True)
    return {"symbol": sym, "lookback": lookback, "rows": rows}


def setup_score(stats: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Expectancy-based score from backtest stats. Returns None if untested.

    expectancy_R = avg_R (mean R per trade) — the core edge metric.
    score blends expectancy with a sample-size confidence factor so a
    2-trade fluke doesn't outrank a 30-trade edge.
    """
    if not stats or not stats.get("n_trades"):
        return None
    n = stats["n_trades"]
    avg_r = stats.get("avg_R") or 0.0
    win = stats.get("win_rate") or 0.0
    # confidence: ramps 0→1 over ~20 trades
    conf = min(1.0, n / 20.0)
    score = round(avg_r * conf * 100, 1)   # scaled for readability
    grade = ("A" if avg_r >= 0.5 and n >= 10 else
             "B" if avg_r >= 0.2 else
             "C" if avg_r >= 0 else "D")
    # Out-of-sample penalty — an overfit strategy cannot earn a good grade
    # no matter how pretty the full-period stats look.
    robustness = (stats.get("robustness") or {}).get("verdict")
    overfit = False
    if robustness == "overfit":
        grade, overfit = "D", True
    elif robustness == "weak" and grade in ("A", "B"):
        grade = "C"
    return {"score": score, "grade": grade, "expectancy_R": round(avg_r, 2),
            "win_rate": win, "n_trades": n, "confidence": round(conf, 2),
            "robustness": robustness, "overfit": overfit}


# ════════════════════════════════════════════════════════════════════
#  ⑦ COMBOS (modular strategy combinations + portfolio backtest)
# ════════════════════════════════════════════════════════════════════


def _combo_row_to_dict(row) -> Dict[str, Any]:
    if not row:
        return {}
    d = dict(row)
    for key in ("members_json", "symbols_json", "stats_json"):
        if d.get(key):
            try:
                d[key.replace("_json", "")] = json.loads(d[key])
            except json.JSONDecodeError:
                pass
    return d


def combos_list() -> List[Dict[str, Any]]:
    ensure_schema()
    with connect() as conn:
        rows = conn.execute("SELECT * FROM trading_combos ORDER BY updated_at DESC").fetchall()
    return [_combo_row_to_dict(r) for r in rows]


def combo_get(combo_id: str) -> Optional[Dict[str, Any]]:
    ensure_schema()
    with connect() as conn:
        row = conn.execute("SELECT * FROM trading_combos WHERE combo_id = ?", (combo_id,)).fetchone()
    return _combo_row_to_dict(row) if row else None


def combo_save(combo_id: Optional[str], fields: Dict[str, Any]) -> Dict[str, Any]:
    ensure_schema()
    now = _now()
    if not combo_id:
        combo_id = "cmb_" + uuid.uuid4().hex[:10]
        current = {}
    else:
        current = combo_get(combo_id) or {}
    payload = {**current, **fields}
    members = payload.get("members")
    symbols = payload.get("symbols")
    stats = payload.get("stats")
    with connect() as conn:
        conn.execute(
            "INSERT INTO trading_combos (combo_id, name, members_json, symbols_json, "
            " status, stats_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT(combo_id) DO UPDATE SET name=excluded.name, "
            " members_json=excluded.members_json, symbols_json=excluded.symbols_json, "
            " status=excluded.status, stats_json=excluded.stats_json, updated_at=excluded.updated_at",
            (combo_id, payload.get("name") or "未命名组合",
             json.dumps(members if members is not None else (current.get("members") or []), ensure_ascii=False),
             json.dumps(symbols if symbols is not None else (current.get("symbols") or []), ensure_ascii=False),
             payload.get("status") or "idea",
             json.dumps(stats, ensure_ascii=False) if stats is not None else current.get("stats_json"),
             current.get("created_at") or now, now),
        )
    return combo_get(combo_id) or {}


def combo_delete(combo_id: str) -> bool:
    ensure_schema()
    with connect() as conn:
        cur = conn.execute("DELETE FROM trading_combos WHERE combo_id = ?", (combo_id,))
    return cur.rowcount > 0


def backtest_combo(member_setup_ids: List[str], symbols: List[str],
                   capital: float = 100_000.0, lookback: str = "3y",
                   max_concurrent: int = 6,
                   weights: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """Portfolio backtest: run member strategies across symbols with SHARED
    capital + a max-concurrent-position cap → one combined equity curve.
    Shows diversification (smoother curve / lower maxDD than any single
    member). Net of costs; daily timeframe. `weights` (setup_id→weight) scales
    each member's per-position allocation."""
    weights = weights or {}
    members = [setup_get(sid) for sid in member_setup_ids]
    members = [m for m in members if m and isinstance(m.get("quant_spec"), dict)]
    if not members or not symbols:
        return {"error": "需要至少 1 个有效成员策略 + 1 个标的"}

    # Pre-fetch bars per symbol (daily), align on a common date index.
    sym_bars: Dict[str, List[Dict[str, Any]]] = {}
    for sym in symbols:
        b = _fetch_bars(sym, "1d", lookback)
        if len(b) >= 15:   # allow short windows (the 'short-term backtest' case)
            sym_bars[sym] = b
    if not sym_bars:
        return {"error": "标的数据不足 (窗口太短或代码无效)"}
    # union of dates → ordered
    all_dates = sorted({b["date"][:10] for bars in sym_bars.values() for b in bars})
    # per (sym): map date->bar + precomputed ohlc + per-member entry flags
    sym_ohlc = {s: {k: [bb[k] for bb in bars] for k in ("open", "high", "low", "close", "volume")}
                for s, bars in sym_bars.items()}
    sym_dateidx = {s: {bb["date"][:10]: i for i, bb in enumerate(bars)} for s, bars in sym_bars.items()}

    slip = COST_SLIPPAGE_PCT / 100.0
    cash = capital
    positions: List[Dict[str, Any]] = []   # {sym, setup, qty, entry_px, stop, target, entry_i, entry_date}
    equity_curve: List[Dict[str, Any]] = []
    trades: List[Dict[str, Any]] = []
    per_member = {m["setup_id"]: {"name": m["name"], "n": 0, "wins": 0, "sumR": 0.0} for m in members}

    def mtm(date) -> float:
        val = cash
        for p in positions:
            di = sym_dateidx[p["sym"]].get(date)
            px = sym_ohlc[p["sym"]]["close"][di] if di is not None else p["entry_px"]
            val += px * p["qty"]
        return val

    for date in all_dates:
        # 1) manage exits
        still = []
        for p in positions:
            di = sym_dateidx[p["sym"]].get(date)
            if di is None:
                still.append(p); continue
            hi, lo, cl = sym_ohlc[p["sym"]]["high"][di], sym_ohlc[p["sym"]]["low"][di], sym_ohlc[p["sym"]]["close"][di]
            exit_px = reason = None
            if lo <= p["stop"]: exit_px, reason = p["stop"], "stop"
            elif hi >= p["target"]: exit_px, reason = p["target"], "target"
            elif p["time_stop"] and (di - p["entry_i"]) >= p["time_stop"]: exit_px, reason = cl, "time_stop"
            if exit_px is not None:
                eff_exit = exit_px * (1 - slip)
                cash += eff_exit * p["qty"]
                risk = max(p["entry_px"] - p["stop"], 1e-9)
                R = (eff_exit - p["entry_px"] * (1 + slip)) / risk
                ret = (eff_exit / (p["entry_px"] * (1 + slip)) - 1) * 100
                trades.append({"sym": p["sym"], "setup": p["setup_name"], "entry_date": p["entry_date"],
                               "exit_date": date, "reason": reason, "return_pct": round(ret, 2), "R": round(R, 2)})
                pm = per_member[p["setup_id"]]; pm["n"] += 1; pm["sumR"] += R
                if ret > 0: pm["wins"] += 1
            else:
                still.append(p)
        positions = still

        # 2) entries (each member × each symbol), shared capital + concurrency cap
        held_keys = {(p["sym"], p["setup_id"]) for p in positions}
        for m in members:
            spec = m["quant_spec"]; conds = (spec.get("entry") or {}).get("conditions") or []
            logic = (spec.get("entry") or {}).get("logic", "AND").upper()
            exit_cfg = spec.get("exit") or {}
            for sym in sym_bars:
                if len(positions) >= max_concurrent: break
                if (sym, m["setup_id"]) in held_keys: continue
                di = sym_dateidx[sym].get(date)
                if di is None or di < 1: continue
                ohlc = sym_ohlc[sym]; sc: Dict[str, Any] = {}
                res = [_cond_true(c, sc, ohlc, di) for c in conds]
                if not res or any(r is None for r in res): continue
                ok = all(res) if logic == "AND" else any(res)
                if not ok: continue
                entry_px = ohlc["close"][di]
                stop_px = _stop_for(spec, sym, entry_px)
                target_px = _target_for(spec, entry_px, stop_px)
                alloc = capital * 0.05 * float(weights.get(m["setup_id"], 1.0))  # weighted per-position
                qty = int(min(alloc, cash) / (entry_px * (1 + slip)))
                if qty < 1: continue
                cash -= entry_px * (1 + slip) * qty
                positions.append({"sym": sym, "setup_id": m["setup_id"], "setup_name": m["name"],
                                  "qty": qty, "entry_px": entry_px, "stop": stop_px, "target": target_px,
                                  "entry_i": di, "entry_date": date,
                                  "time_stop": int(exit_cfg.get("time_stop_bars") or 0)})
                held_keys.add((sym, m["setup_id"]))
        equity_curve.append({"date": date, "equity": round(mtm(date), 0)})

    # combined stats
    n = len(trades); wins = sum(1 for t in trades if t["return_pct"] > 0)
    eq = [e["equity"] for e in equity_curve]
    peak = eq[0] if eq else capital; max_dd = 0.0
    for v in eq:
        peak = max(peak, v); max_dd = max(max_dd, (peak - v) / peak if peak else 0)
    total_ret = round((eq[-1] / capital - 1) * 100, 1) if eq else 0.0
    # downsample curve
    curve = equity_curve
    if len(curve) > 240:
        step = len(curve)//240 + 1; curve = curve[::step]
    contrib = [{"setup_id": k, "name": v["name"], "n": v["n"],
                "win_rate": round(v["wins"]/v["n"]*100, 1) if v["n"] else None,
                "avg_R": round(v["sumR"]/v["n"], 2) if v["n"] else None}
               for k, v in per_member.items()]
    start_date = all_dates[0] if all_dates else None
    end_date = all_dates[-1] if all_dates else None
    n_days = len(all_dates)
    # benchmark: equal-weight buy-and-hold of the basket over the same window
    bh_rets = []
    for s, bars in sym_bars.items():
        if len(bars) >= 2 and bars[0]["close"]:
            bh_rets.append((bars[-1]["close"] / bars[0]["close"] - 1) * 100)
    bh = round(sum(bh_rets) / len(bh_rets), 1) if bh_rets else None
    return {"symbols": list(sym_bars.keys()), "n_members": len(members),
            "stats": {"n_trades": n, "win_rate": round(wins/n*100, 1) if n else None,
                      "total_return_pct": total_ret, "max_drawdown_pct": round(max_dd*100, 1),
                      "avg_R": round(sum(t["R"] for t in trades)/n, 2) if n else None,
                      "buy_hold_pct": bh, "beats_buy_hold": (bh is not None and total_ret > bh),
                      "assumptions": f"组合共享资金 ${capital:,.0f} · 单仓5% · max{max_concurrent}并发 · 已扣滑点{COST_SLIPPAGE_PCT}%/边 · vs 等权买入持有 · 历史≠未来"},
            "equity_curve": curve, "contributions": contrib, "capital": capital,
            "start_date": start_date, "end_date": end_date, "n_bars": n_days}


def optimize_combos(symbols: List[str], max_size: int = 3, lookback: str = "3y",
                    max_candidates: int = 6) -> Dict[str, Any]:
    """One-click: test every combination of strategies (size 1..max_size) on
    the SAME symbols + shared capital, rank by risk-adjusted score. Size-1 =
    single strategies, size≥2 = combos — all in one ranked table, so you see
    which single OR combo is best AND how combos compare to singles.

    Bounded: only the top `max_candidates` strategies (by their own score) are
    used as building blocks, max_size caps subset size — so the search stays
    fast (with bar caching, no network in the loop)."""
    from itertools import combinations
    cand = [s for s in setups_list()
            if s.get("status") != "retired" and isinstance(s.get("quant_spec"), dict)
            and (s.get("quant_spec", {}).get("entry") or {}).get("conditions")]
    # rank candidates by their own score, keep top N to bound 2^N
    cand.sort(key=lambda s: (setup_score(s.get("backtest_stats")) or {}).get("score", -1e9), reverse=True)
    cand = cand[:max_candidates]
    if not cand or not symbols:
        return {"error": "需要至少 1 个策略 + 1 个标的", "rows": []}

    rows: List[Dict[str, Any]] = []
    seen = 0
    for size in range(1, min(max_size, len(cand)) + 1):
        for subset in combinations(cand, size):
            seen += 1
            ids = [s["setup_id"] for s in subset]
            res = backtest_combo(ids, symbols, lookback=lookback)
            if res.get("error"):
                continue
            st = res.get("stats", {})
            n = st.get("n_trades") or 0
            ret = st.get("total_return_pct") or 0
            dd = st.get("max_drawdown_pct") or 0
            # risk-adjusted score (Calmar-ish): return per unit of drawdown,
            # require a minimum sample so flukes don't win.
            score = round(ret / max(dd, 1.0), 2) if n >= 5 else round(ret / max(dd, 1.0) * (n / 5.0), 2)
            rows.append({
                "size": size, "is_single": size == 1,
                "members": [s["name"] for s in subset],
                "member_ids": ids,
                "n_trades": n, "win_rate": st.get("win_rate"),
                "total_return_pct": ret, "max_drawdown_pct": dd,
                "avg_R": st.get("avg_R"), "score": score})
    rows.sort(key=lambda r: r["score"], reverse=True)
    best_single = next((r for r in rows if r["is_single"]), None)
    best_overall = rows[0] if rows else None
    return {"symbols": symbols, "lookback": lookback, "n_tested": len(rows),
            "rows": rows, "best_overall": best_overall, "best_single": best_single,
            "candidates": [s["name"] for s in cand]}


def optimize_plan(symbols: List[str], max_size: int = 3, max_candidates: int = 6) -> Dict[str, Any]:
    """Enumerate the subsets to test (NO backtest) so the frontend can show
    real X/Y progress + run them one-by-one with incremental results."""
    from itertools import combinations
    cand = [s for s in setups_list()
            if s.get("status") != "retired" and isinstance(s.get("quant_spec"), dict)
            and (s.get("quant_spec", {}).get("entry") or {}).get("conditions")]
    cand.sort(key=lambda s: (setup_score(s.get("backtest_stats")) or {}).get("score", -1e9), reverse=True)
    cand = cand[:max_candidates]
    if not cand or not symbols:
        return {"error": "需要至少 1 个策略 + 1 个标的", "subsets": []}
    subsets = []
    for size in range(1, min(max_size, len(cand)) + 1):
        for subset in combinations(cand, size):
            subsets.append({"member_ids": [s["setup_id"] for s in subset],
                            "names": [s["name"] for s in subset],
                            "size": size, "is_single": size == 1})
    return {"subsets": subsets, "n": len(subsets), "candidates": [s["name"] for s in cand]}


def save_combo_from_optimizer(member_ids: List[str], symbols: List[str], name: str) -> Dict[str, Any]:
    return combo_save(None, {"name": name, "members": [{"setup_id": i, "weight": 1} for i in member_ids],
                             "symbols": symbols, "status": "idea"})


# ════════════════════════════════════════════════════════════════════
#  ⑧ EARNINGS CALENDAR GUARD (enforces TPS '不持仓过 earnings')
# ════════════════════════════════════════════════════════════════════

EARNINGS_GUARD_DAYS = 7


def earnings_for(symbols: List[str]) -> Dict[str, Dict[str, Any]]:
    """Next-earnings-date + days_until per symbol (reuses agent.finance.earnings)."""
    out: Dict[str, Dict[str, Any]] = {}
    try:
        from agent.finance.earnings import fetch_symbols
        for row in fetch_symbols([s.upper() for s in symbols]):
            out[row["symbol"]] = {"next_earnings_date": row.get("next_earnings_date"),
                                  "days_until": row.get("days_until")}
    except Exception as exc:
        logger.debug("earnings_for failed: %s", exc)
    return out


def _earnings_block(symbol: str) -> Optional[Dict[str, Any]]:
    """Block opening a swing position into an earnings binary event.
    FAIL-CLOSED: if the earnings CHECK itself errors, we can't verify → block
    (TPS red line: 持任何票前查 earnings). Returns a block dict, or None to allow."""
    try:
        from agent.finance.earnings import fetch_symbols
        rows = fetch_symbols([symbol.upper()])
    except Exception as exc:
        return {"unverified": True,
                "reason": f"earnings 无法核实({type(exc).__name__})—守红线不开新仓"}
    if rows:
        du = rows[0].get("days_until")
        if du is not None and 0 <= du <= EARNINGS_GUARD_DAYS:
            return {"days_until": du, "date": rows[0].get("next_earnings_date"),
                    "reason": f"临近财报 {rows[0].get('next_earnings_date')} ({du}d) — 不持仓过 earnings"}
    return None


# ════════════════════════════════════════════════════════════════════
#  ⑩ TODAY COCKPIT (consolidated morning view — the daily routine)
# ════════════════════════════════════════════════════════════════════


def _cockpit_ibkr() -> Dict[str, Any]:
    """Cockpit built from the IBKR account = the single source of truth when
    venue='ibkr'. Positions/stops/targets/equity all come from IBKR, so what
    you see here is exactly what the broker holds (paper or live)."""
    from agent.finance import ibkr_connector
    snap = ibkr_connector.account_snapshot()        # ONE connection
    connected = bool(snap.get("connected"))
    acct_id = (snap.get("accounts") or [None])[0]
    is_paper = bool(acct_id and acct_id.upper().startswith("DU"))
    netliq = _safe_float((snap.get("values") or {}).get("NetLiquidation"))
    # map symbol → resting stop/target from open SELL orders
    legs: Dict[str, Dict[str, float]] = {}
    for o in (snap.get("orders") or []):
        if (o.get("action") or "").upper() == "SELL":
            d = legs.setdefault(o.get("symbol"), {})
            if (o.get("type") or "").upper() in ("STP", "STOP") and o.get("stop"):
                d["stop"] = o["stop"]
            elif (o.get("type") or "").upper() in ("LMT", "LIMIT") and o.get("limit"):
                d["target"] = o["limit"]
    positions = []
    for p in (snap.get("positions") or []):
        if (p.get("position") or 0) <= 0:
            continue
        sym = p["symbol"]; entry = p.get("avg_cost") or 0
        leg = legs.get(sym, {})
        positions.append({"symbol": sym, "qty": p.get("position"), "entry": round(entry, 2),
                          "current": None, "stop": leg.get("stop"), "target": leg.get("target"),
                          "R": None, "unrealized_pct": None, "days": None})
    held = [p["symbol"] for p in positions]
    edata = earnings_for(held) if held else {}
    earnings_soon = [{"symbol": k, **v} for k, v in edata.items()
                     if v.get("days_until") is not None and 0 <= v["days_until"] <= EARNINGS_GUARD_DAYS]
    earnings_soon.sort(key=lambda x: x.get("days_until", 999))
    st2 = get_state()
    return {
        "regime": market_regime(),
        "halted": bool(st2.get("global_halt")), "auto_armed": bool(st2.get("auto_trade")),
        "venue": "ibkr", "ibkr_connected": connected,
        "account": acct_id, "is_paper": is_paper, "net_liquidation": netliq,
        "positions": positions, "n_positions": len(positions),
        "earnings_soon": earnings_soon, "held_into_earnings": list(earnings_soon),
        "open_journal": len([j for j in journal_list(200) if j.get("status") == "open"]),
        "ibkr_error": snap.get("error") if not connected else None,
    }


def cockpit(project_id: str) -> Dict[str, Any]:
    """One-screen morning view: regime + open positions (stop/target/R/days/
    unrealized) + upcoming earnings on held+watchlist + open-journal count.
    When venue='ibkr', the IBKR account is the single source of truth."""
    if current_venue() == "ibkr":
        return _cockpit_ibkr()
    from agent.finance.paper_trading import get_project_engine, OrderSide, OrderType
    from datetime import datetime, timezone
    eng = get_project_engine(project_id)
    open_orders = eng.get_open_orders()
    # map symbol → {stop, target} from resting OCO sell orders
    legs: Dict[str, Dict[str, float]] = {}
    for o in open_orders:
        if o.side == OrderSide.SELL:
            d = legs.setdefault(o.symbol, {})
            if o.order_type == OrderType.STOP and o.stop_price:
                d["stop"] = o.stop_price
            elif o.order_type == OrderType.LIMIT and o.price:
                d["target"] = o.price
    positions = []
    for p in eng.get_all_positions():
        if p.quantity <= 0:
            continue
        leg = legs.get(p.symbol, {})
        stop = leg.get("stop"); target = leg.get("target")
        cur = p.current_price or p.entry_price
        r_mult = None
        if stop and (p.entry_price - stop) > 0:
            r_mult = round((cur - p.entry_price) / (p.entry_price - stop), 2)
        days = None
        if getattr(p, "opened_at", None):
            try:
                days = (datetime.now(timezone.utc) - p.opened_at).days
            except Exception:
                days = None
        positions.append({
            "symbol": p.symbol, "qty": p.quantity, "entry": round(p.entry_price, 2),
            "current": round(cur, 2), "stop": round(stop, 2) if stop else None,
            "target": round(target, 2) if target else None, "R": r_mult,
            "unrealized_pct": round(getattr(p, "unrealized_pnl_pct", 0) or 0, 2), "days": days})

    # earnings: only for HELD names (fast — usually 0-5 symbols). The most
    # actionable signal is "you're holding INTO earnings → exit". New entries
    # are already earnings-guarded in the scan, so no need to scan the whole
    # watchlist here (that was making the morning glance take 15s+).
    held = [p["symbol"] for p in positions]
    edata = earnings_for(held) if held else {}
    earnings_soon = [{"symbol": k, **v} for k, v in edata.items()
                     if v.get("days_until") is not None and 0 <= v["days_until"] <= EARNINGS_GUARD_DAYS]
    earnings_soon.sort(key=lambda x: x.get("days_until", 999))
    held_into_earnings = list(earnings_soon)

    n_open_journal = len([j for j in journal_list(200) if j.get("status") == "open"])
    st = get_state()
    return {
        "regime": market_regime(),
        "halted": bool(st.get("global_halt")), "auto_armed": bool(st.get("auto_trade")),
        "venue": "sim",
        "positions": positions, "n_positions": len(positions),
        "earnings_soon": earnings_soon, "held_into_earnings": held_into_earnings,
        "open_journal": n_open_journal,
    }


# ════════════════════════════════════════════════════════════════════
#  ⑨ TRADE JOURNAL + WEEKLY REVIEW (the discipline layer)
# ════════════════════════════════════════════════════════════════════


def journal_list(limit: int = 100) -> List[Dict[str, Any]]:
    ensure_schema()
    with connect() as conn:
        rows = conn.execute("SELECT * FROM trade_journal ORDER BY entry_date DESC, created_at DESC LIMIT ?",
                            (limit,)).fetchall()
    return [dict(r) for r in rows]


def journal_save(journal_id: Optional[str], fields: Dict[str, Any]) -> Dict[str, Any]:
    ensure_schema()
    now = _now()
    if not journal_id:
        journal_id = "jnl_" + uuid.uuid4().hex[:10]
        cur = {}
    else:
        with connect() as conn:
            row = conn.execute("SELECT * FROM trade_journal WHERE journal_id = ?", (journal_id,)).fetchone()
        cur = dict(row) if row else {}
    p = {**cur, **fields}
    cols = ("symbol", "setup_name", "status", "thesis", "catalyst", "emotion", "followed_plan",
            "entry_date", "entry_px", "stop_px", "target_px", "exit_date", "exit_px",
            "exit_reason", "return_pct", "r_multiple", "lesson")
    with connect() as conn:
        conn.execute(
            f"INSERT INTO trade_journal (journal_id, {','.join(cols)}, created_at, updated_at) "
            f"VALUES (?,{','.join('?' for _ in cols)},?,?) "
            f"ON CONFLICT(journal_id) DO UPDATE SET "
            + ", ".join(f"{c}=excluded.{c}" for c in cols) + ", updated_at=excluded.updated_at",
            (journal_id, *[p.get(c) for c in cols], cur.get("created_at") or now, now))
    with connect() as conn:
        return dict(conn.execute("SELECT * FROM trade_journal WHERE journal_id = ?", (journal_id,)).fetchone())


def journal_delete(journal_id: str) -> bool:
    ensure_schema()
    with connect() as conn:
        return conn.execute("DELETE FROM trade_journal WHERE journal_id = ?", (journal_id,)).rowcount > 0


def journal_add_from_entry(symbol: str, setup_name: str, entry_px: float,
                           stop_px: float, target_px: float, thesis: str) -> None:
    """Auto-create an OPEN journal stub when auto-entry fires (idempotent per
    symbol+setup+date)."""
    today = _today()
    ensure_schema()
    with connect() as conn:
        dup = conn.execute(
            "SELECT 1 FROM trade_journal WHERE symbol=? AND setup_name=? AND entry_date=? LIMIT 1",
            (symbol, setup_name, today)).fetchone()
        if dup:
            return
    journal_save(None, {"symbol": symbol, "setup_name": setup_name, "status": "open",
                        "thesis": thesis, "catalyst": "technical", "entry_date": today,
                        "entry_px": round(entry_px, 2), "stop_px": round(stop_px, 2),
                        "target_px": round(target_px, 2)})


def _journal_sync_ibkr() -> Dict[str, Any]:
    """venue=ibkr journal reconcile: close open entries whose symbol is no
    longer an IBKR position, using the most-recent SELL fill (from the durable
    ibkr_log — live fills OR Flex trades) as the exit. Keeps the journal honest
    + revives the kill-switch's consecutive-loss signal for the real account."""
    from agent.finance import ibkr_connector
    snap = ibkr_connector.account_snapshot()
    if not snap.get("connected"):
        return {"closed": 0, "note": "IBKR 未连接"}
    open_syms = {p["symbol"] for p in (snap.get("positions") or []) if (p.get("position") or 0) > 0}
    sells: Dict[str, Dict] = {}    # newest SELL fill per symbol (rows are DESC by ts)
    for r in ibkr_log_list(limit=500).get("rows", []):
        if r.get("kind") in ("fill", "flex_trade") and (r.get("action") or "").upper() in ("SELL", "SLD"):
            s = r.get("symbol")
            if s and s not in sells and r.get("price"):
                sells[s] = r
    closed = 0
    for j in journal_list(500):
        if j.get("status") != "open":
            continue
        sym = j.get("symbol")
        if not sym or sym in open_syms or sym not in sells:
            continue
        entry = j.get("entry_px") or 0
        stop = j.get("stop_px"); target = j.get("target_px")
        exit_px = sells[sym]["price"]
        ret = (exit_px / entry - 1) * 100 if entry else None
        r_m = ((exit_px - entry) / (entry - stop)) if (entry and stop and entry > stop) else None
        reason = ("target" if (target and exit_px >= target * 0.99)
                  else "stop" if (stop and exit_px <= stop * 1.01) else "discretionary")
        journal_save(j["journal_id"], {
            "status": "closed", "exit_px": round(exit_px, 2),
            "exit_date": (sells[sym].get("ts") or _now())[:10], "exit_reason": reason,
            "return_pct": round(ret, 2) if ret is not None else None,
            "r_multiple": round(r_m, 2) if r_m is not None else None})
        closed += 1
    return {"closed": closed, "venue": "ibkr"}


def journal_sync_from_paper(project_id: str) -> Dict[str, Any]:
    """Reconcile open journal entries with the account: any open entry whose
    symbol no longer has an open position is auto-closed using the realized
    exit — so the journal becomes a complete record without manual marking.
    VENUE-AWARE: uses IBKR fills when venue=ibkr."""
    if current_venue() == "ibkr":
        return _journal_sync_ibkr()
    from agent.finance.paper_trading import get_project_engine, OrderSide
    from datetime import datetime, timezone
    eng = get_project_engine(project_id)
    open_syms = {p.symbol for p in eng.get_all_positions() if p.quantity > 0}
    sells = [t for t in eng.get_trade_history() if t.side == OrderSide.SELL]
    closed = 0
    for j in journal_list(500):
        if j.get("status") != "open":
            continue
        sym = j.get("symbol")
        if not sym or sym in open_syms:
            continue
        cand = [t for t in sells if t.symbol == sym]
        if not cand:
            continue
        t = max(cand, key=lambda x: x.timestamp or datetime.min.replace(tzinfo=timezone.utc))
        entry = j.get("entry_px") or 0
        stop = j.get("stop_px"); target = j.get("target_px")
        exit_px = t.price
        ret = (exit_px / entry - 1) * 100 if entry else None
        r = ((exit_px - entry) / (entry - stop)) if (entry and stop and entry > stop) else None
        reason = ("target" if (target and exit_px >= target * 0.99)
                  else "stop" if (stop and exit_px <= stop * 1.01) else "discretionary")
        journal_save(j["journal_id"], {
            "status": "closed", "exit_px": round(exit_px, 2),
            "exit_date": (t.timestamp.date().isoformat() if t.timestamp else _today()),
            "exit_reason": reason,
            "return_pct": round(ret, 2) if ret is not None else None,
            "r_multiple": round(r, 2) if r is not None else None})
        closed += 1
    return {"closed": closed}


def journal_weekly(days: int = 7) -> Dict[str, Any]:
    """Aggregate CLOSED journal entries in the last `days` for the weekly review:
    win rate, avg R, followed-plan %, by-catalyst, holding-period vs outcome."""
    from datetime import datetime, timezone, timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    closed = [j for j in journal_list(500)
              if j.get("status") == "closed" and (j.get("exit_date") or j.get("entry_date") or "") >= cutoff]
    n = len(closed)
    if n == 0:
        return {"days": days, "n": 0, "note": "本期无已平仓记录"}
    wins = [j for j in closed if (j.get("return_pct") or 0) > 0]
    rs = [j["r_multiple"] for j in closed if j.get("r_multiple") is not None]
    followed = [j for j in closed if j.get("followed_plan") == 1]
    by_cat: Dict[str, Dict[str, Any]] = {}
    for j in closed:
        c = j.get("catalyst") or "other"
        by_cat.setdefault(c, {"n": 0, "wins": 0})
        by_cat[c]["n"] += 1
        if (j.get("return_pct") or 0) > 0:
            by_cat[c]["wins"] += 1
    return {
        "days": days, "n": n,
        "win_rate": round(len(wins) / n * 100, 1),
        "avg_R": round(sum(rs) / len(rs), 2) if rs else None,
        "avg_return_pct": round(sum(j.get("return_pct") or 0 for j in closed) / n, 2),
        "followed_plan_pct": round(len(followed) / n * 100, 1),
        "by_catalyst": [{"catalyst": k, "n": v["n"], "win_rate": round(v["wins"] / v["n"] * 100, 1)} for k, v in by_cat.items()],
        "avg_hold_days": None,  # entry/exit dates available; left simple
    }


# ════════════════════════════════════════════════════════════════════
#  TRADING PLANS — local markdown playbooks (SpaceX event plan, discipline
#  cards, manual checklists, …).
#
#  These are PERSONAL trading data. They are served ONLY from the local
#  ~/trading_plans directory, strictly READ-ONLY, and MUST NEVER be written
#  to git or uploaded anywhere. File CONTENTS are never logged — only names.
# ════════════════════════════════════════════════════════════════════


def _trading_plans_dir() -> Path:
    return (Path.home() / "trading_plans").resolve()


def _safe_plan_path(name: str) -> Path:
    """Resolve ``name`` to a file strictly inside ~/trading_plans, ending in
    ``.md``. Path-traversal hardened: ``name`` must be a bare ``.md`` basename
    with no separators and no parent refs. Raises HTTPException on any breach.
    """
    # (1) bare basename only — reject separators, parent refs, absolute paths
    if (not name
            or name != Path(name).name          # any '/' collapses to the last segment
            or "/" in name or "\\" in name
            or ".." in name
            or not name.endswith(".md")):
        raise HTTPException(status_code=400, detail="非法计划名")
    base = _trading_plans_dir()
    target = (base / name).resolve()
    # (2) defense in depth: the resolved path must stay directly under base
    if target.parent != base:
        raise HTTPException(status_code=400, detail="非法路径")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="计划不存在")
    return target


def _plan_title(path: Path) -> Optional[str]:
    """First markdown ``# `` heading, else None. Scans only the file head."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for _ in range(200):               # head only — never slurp the whole file
                line = fh.readline()
                if not line:
                    break
                s = line.strip()
                if s.startswith("#"):
                    return s.lstrip("#").strip() or None
    except OSError:
        return None
    return None


def list_trading_plans() -> Dict[str, Any]:
    """List ~/trading_plans/*.md — {filename, title, mtime, size}, newest first.
    No file contents are read beyond each plan's title heading."""
    base = _trading_plans_dir()
    if not base.is_dir():
        return {"plans": [], "n": 0, "note": "无 ~/trading_plans 目录"}
    plans: List[Dict[str, Any]] = []
    for p in base.glob("*.md"):                # non-recursive: direct children only
        if not p.is_file():
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        plans.append({
            "filename": p.name,
            "title": _plan_title(p),
            "mtime": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
            "size": st.st_size,
        })
    plans.sort(key=lambda x: x["mtime"], reverse=True)
    return {"plans": plans, "n": len(plans)}


def read_trading_plan(name: str) -> Dict[str, Any]:
    """Return one plan's raw markdown content. Path-traversal-guarded."""
    path = _safe_plan_path(name)
    content = path.read_text(encoding="utf-8", errors="replace")
    return {"filename": path.name, "title": _plan_title(path),
            "content": content, "size": len(content.encode("utf-8"))}


# ════════════════════════════════════════════════════════════════════
#  ROUTER
# ════════════════════════════════════════════════════════════════════


class TPSBody(BaseModel):
    north_star: Optional[str] = None
    identity: Optional[str] = None
    red_lines: Optional[List[str]] = None
    risk_rules: Optional[Dict[str, Any]] = None
    entry_protocol: Optional[str] = None
    exit_protocol: Optional[str] = None
    kill_switch: Optional[str] = None
    execution_rules: Optional[str] = None
    validation_rules: Optional[str] = None
    tax_note: Optional[str] = None
    review_cadence: Optional[str] = None
    last_reviewed_at: Optional[str] = None
    change_note: Optional[str] = None


class SetupBody(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None
    nl_description: Optional[str] = None
    quant_spec: Optional[Dict[str, Any]] = None
    change_note: Optional[str] = None


class DistillBody(BaseModel):
    nl_description: str
    current_spec: Optional[Dict[str, Any]] = None


class BacktestBody(BaseModel):
    symbol: str
    quant_spec: Optional[Dict[str, Any]] = None  # if omitted, use saved setup spec


class ComboBody(BaseModel):
    name: Optional[str] = None
    members: Optional[List[Dict[str, Any]]] = None  # [{setup_id, weight}]
    symbols: Optional[List[str]] = None
    status: Optional[str] = None


class FlexCfgBody(BaseModel):
    token: str
    query_id: str


def build_trading_router() -> APIRouter:
    router = APIRouter(prefix="/api/trading", tags=["trading"])

    # ── Policy ──
    @router.get("/policy")
    def get_policy() -> Dict[str, Any]:
        return tps_seed_if_empty() or {}

    @router.get("/policy/history")
    def policy_history(limit: int = 20) -> Dict[str, Any]:
        h = tps_history(limit)
        return {"history": h, "n": len(h)}

    @router.put("/policy")
    def put_policy(body: TPSBody) -> Dict[str, Any]:
        fields = {k: v for k, v in body.dict().items() if v is not None}
        note = fields.pop("change_note", None)
        return tps_upsert(fields, change_note=note)

    @router.get("/vocab")
    def get_vocab() -> Dict[str, Any]:
        return {"vocab": INDICATOR_VOCAB, "spec_schema": _QUANT_SPEC_SCHEMA}

    # ── Setups CRUD ──
    @router.get("/setups")
    def list_setups() -> Dict[str, Any]:
        items = setups_list()
        for s in items:
            s["score"] = setup_score(s.get("backtest_stats"))
        # leaderboard: scored setups first, by score desc
        items.sort(key=lambda s: (s.get("score") or {}).get("score", -1e9), reverse=True)
        return {"setups": items, "n": len(items)}

    @router.get("/setups/{setup_id}")
    def get_setup(setup_id: str) -> Dict[str, Any]:
        s = setup_get(setup_id)
        if not s:
            raise HTTPException(404, "setup not found")
        return s

    @router.get("/setups/{setup_id}/history")
    def get_setup_history(setup_id: str) -> Dict[str, Any]:
        h = setup_history(setup_id)
        return {"history": h, "n": len(h)}

    @router.post("/setups")
    def create_setup(body: SetupBody) -> Dict[str, Any]:
        fields = {k: v for k, v in body.dict().items() if v is not None}
        note = fields.pop("change_note", None)
        return setup_save(None, fields, change_note=note)

    @router.put("/setups/{setup_id}")
    def update_setup(setup_id: str, body: SetupBody) -> Dict[str, Any]:
        if not setup_get(setup_id):
            raise HTTPException(404, "setup not found")
        fields = {k: v for k, v in body.dict().items() if v is not None}
        note = fields.pop("change_note", None)
        return setup_save(setup_id, fields, change_note=note)

    @router.delete("/setups/{setup_id}")
    def delete_setup(setup_id: str) -> Dict[str, Any]:
        return {"ok": setup_delete(setup_id)}

    # ── Distill (NL → quant) ──
    @router.post("/setups/distill")
    def distill(body: DistillBody) -> Dict[str, Any]:
        try:
            spec = distill_setup(body.nl_description, body.current_spec)
            return {"ok": True, "quant_spec": spec}
        except Exception as exc:
            logger.exception("distill failed")
            raise HTTPException(502, f"蒸馏失败 (LLM): {exc}")

    # ── Backtest ──
    @router.post("/setups/{setup_id}/backtest")
    def backtest_setup(setup_id: str, body: BacktestBody) -> Dict[str, Any]:
        spec = body.quant_spec
        if spec is None:
            s = setup_get(setup_id)
            if not s:
                raise HTTPException(404, "setup not found")
            spec = s.get("quant_spec")
        if not isinstance(spec, dict):
            raise HTTPException(400, "no quant_spec to backtest")
        res = evaluate_spec(spec, body.symbol.upper())
        # persist latest stats onto the active setup version (incl. OOS
        # robustness so the score/grade reflects overfitting).
        if setup_get(setup_id) and not res.get("error"):
            try:
                setup_save(setup_id, {"backtest_stats": {
                    **res.get("stats", {}), "symbol": body.symbol.upper(),
                    "robustness": res.get("robustness"),
                    "oos_stats": res.get("oos_stats"),
                    "is_stats": res.get("is_stats")}},
                    change_note=f"backtest {body.symbol.upper()}")
            except Exception:
                pass
        return res

    @router.post("/backtest_adhoc")
    def backtest_adhoc(body: BacktestBody) -> Dict[str, Any]:
        if not isinstance(body.quant_spec, dict):
            raise HTTPException(400, "quant_spec required")
        return evaluate_spec(body.quant_spec, body.symbol.upper())

    @router.post("/setups/{setup_id}/chart")
    def setup_chart(setup_id: str, body: BacktestBody) -> Dict[str, Any]:
        spec = body.quant_spec
        if spec is None:
            s = setup_get(setup_id)
            if not s:
                raise HTTPException(404, "setup not found")
            spec = s.get("quant_spec")
        if not isinstance(spec, dict):
            raise HTTPException(400, "no quant_spec to chart")
        return chart_data(spec, body.symbol.upper())

    # ── Compare all setups on a common symbol/period ──
    @router.post("/compare")
    def compare(symbol: str, lookback: str = "3y") -> Dict[str, Any]:
        return compare_setups(symbol, lookback)

    # ── Combos (modular strategy combinations + portfolio backtest) ──
    @router.get("/combos")
    def list_combos() -> Dict[str, Any]:
        items = combos_list()
        return {"combos": items, "n": len(items)}

    @router.post("/combos")
    def create_combo(body: ComboBody) -> Dict[str, Any]:
        return combo_save(None, {k: v for k, v in body.dict().items() if v is not None})

    @router.put("/combos/{combo_id}")
    def update_combo(combo_id: str, body: ComboBody) -> Dict[str, Any]:
        if not combo_get(combo_id):
            raise HTTPException(404, "combo not found")
        return combo_save(combo_id, {k: v for k, v in body.dict().items() if v is not None})

    @router.delete("/combos/{combo_id}")
    def delete_combo(combo_id: str) -> Dict[str, Any]:
        return {"ok": combo_delete(combo_id)}

    @router.post("/combos/{combo_id}/backtest")
    def backtest_combo_ep(combo_id: str, lookback: str = "3y") -> Dict[str, Any]:
        c = combo_get(combo_id)
        if not c:
            raise HTTPException(404, "combo not found")
        members = [m.get("setup_id") for m in (c.get("members") or []) if m.get("setup_id")]
        weights = {m["setup_id"]: float(m.get("weight") or 1.0) for m in (c.get("members") or []) if m.get("setup_id")}
        symbols = c.get("symbols") or []
        res = backtest_combo(members, symbols, lookback=lookback, weights=weights)
        if not res.get("error"):
            try:
                combo_save(combo_id, {"stats": res.get("stats")})
            except Exception:
                pass
        return res

    # ── Scan (report-only, no execution) ──
    @router.post("/scan")
    def scan() -> Dict[str, Any]:
        return scan_setups()

    # ── Emergency brakes + automated scan/trade ──
    @router.get("/state")
    def get_trading_state() -> Dict[str, Any]:
        return get_state()

    @router.post("/halt")
    def post_halt(on: bool = True, reason: Optional[str] = None) -> Dict[str, Any]:
        return set_halt(on, reason or ("用户手动停止" if on else None), by="user")

    @router.post("/auto_trade")
    def post_auto_trade(on: bool = True) -> Dict[str, Any]:
        """Master arm/disarm for automated entries (一键断开自动进场)."""
        return set_auto_trade(on)

    @router.post("/optimize")
    def post_optimize(symbols: str, max_size: int = 3, lookback: str = "3y") -> Dict[str, Any]:
        """One-click: test all strategy combinations on `symbols` (comma-sep),
        rank singles + combos head-to-head."""
        syms = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        return optimize_combos(syms, max_size=max_size, lookback=lookback)

    @router.post("/optimize/plan")
    def post_optimize_plan(symbols: str, max_size: int = 3) -> Dict[str, Any]:
        """Enumerate subsets (no backtest) → frontend runs them with progress."""
        syms = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        return optimize_plan(syms, max_size=max_size)

    @router.post("/backtest_combo_adhoc")
    def backtest_combo_adhoc(body: Dict[str, Any]) -> Dict[str, Any]:
        """Backtest one ad-hoc member set on symbols — used by the optimizer's
        per-subset progress loop."""
        ids = body.get("member_ids") or []
        syms = [s.strip().upper() for s in (body.get("symbols") or []) if s.strip()]
        lookback = body.get("lookback") or "3y"
        return backtest_combo(ids, syms, lookback=lookback)

    @router.post("/optimize/save")
    def post_optimize_save(member_ids: str, symbols: str, name: str) -> Dict[str, Any]:
        """Save a combo found by the optimizer for reuse."""
        return save_combo_from_optimizer(
            [m for m in member_ids.split(",") if m],
            [s.strip().upper() for s in symbols.split(",") if s.strip()], name)

    @router.post("/flatten")
    def post_flatten(project_id: str = "fin-core") -> Dict[str, Any]:
        return flatten_paper(project_id)

    @router.post("/refresh_positions")
    def post_refresh(project_id: str = "fin-core") -> Dict[str, Any]:
        """Settle pending stop/target/OCO by feeding latest prices."""
        return refresh_positions(project_id)

    @router.post("/kill_switch_check")
    def post_kill_switch(project_id: str = "fin-core") -> Dict[str, Any]:
        return check_kill_switch(project_id)

    @router.post("/portfolio_risk")
    def post_portfolio_risk(project_id: str = "fin-core") -> Dict[str, Any]:
        """Correlation matrix + concentration warnings for paper holdings."""
        return portfolio_risk(project_id)

    @router.get("/regime")
    def get_regime() -> Dict[str, Any]:
        """Market risk-on/risk-off (SPY vs 200-day SMA) — the long-only hedge."""
        return market_regime()

    @router.post("/earnings")
    def post_earnings(symbols: str) -> Dict[str, Any]:
        """Next earnings date + days_until for symbols (comma-sep). Surfaces the
        'don't hold over earnings' calendar in the workflow."""
        syms = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        data = earnings_for(syms)
        soon = [{"symbol": k, **v} for k, v in data.items()
                if v.get("days_until") is not None and 0 <= v["days_until"] <= EARNINGS_GUARD_DAYS]
        soon.sort(key=lambda x: x.get("days_until", 999))
        return {"earnings": data, "upcoming": soon, "guard_days": EARNINGS_GUARD_DAYS}

    # ── Trade journal ──
    @router.get("/journal")
    def get_journal(limit: int = 100) -> Dict[str, Any]:
        items = journal_list(limit)
        return {"entries": items, "n": len(items)}

    @router.post("/journal")
    def post_journal(body: Dict[str, Any]) -> Dict[str, Any]:
        jid = body.pop("journal_id", None)
        return journal_save(jid, body)

    @router.delete("/journal/{journal_id}")
    def delete_journal(journal_id: str) -> Dict[str, Any]:
        return {"ok": journal_delete(journal_id)}

    @router.get("/journal/weekly")
    def get_journal_weekly(days: int = 7) -> Dict[str, Any]:
        return journal_weekly(days)

    @router.post("/journal/sync")
    def post_journal_sync(project_id: str = "fin-core") -> Dict[str, Any]:
        """Auto-close journal entries whose paper position has exited."""
        return journal_sync_from_paper(project_id)

    @router.post("/journal/sync-ibkr")
    def post_journal_sync_ibkr() -> Dict[str, Any]:
        """Reconcile the trade journal against REAL IBKR fills: close open
        entries whose symbol has left the IBKR book, using the durable
        ibkr_log SELL fill as the exit. Venue-independent (always the IBKR
        path) — this is what the daily scheduler job calls so the real
        trading process leaves an automatic paper trail. Honest 0 when
        IBKR is disconnected or no sell fills are on record."""
        return _journal_sync_ibkr()

    # ── Trading plans (local markdown playbooks — personal, read-only) ──
    @router.get("/plans")
    def get_trading_plans() -> Dict[str, Any]:
        """List ~/trading_plans/*.md → {filename, title, mtime, size}.
        Local-only personal data; never uploaded."""
        return list_trading_plans()

    @router.get("/plan/{name}")
    def get_trading_plan(name: str) -> Dict[str, Any]:
        """Return one plan's markdown content. Path-traversal-guarded:
        only bare ``.md`` basenames under ~/trading_plans are served."""
        return read_trading_plan(name)

    @router.post("/cockpit")
    def post_cockpit(project_id: str = "fin-core") -> Dict[str, Any]:
        """Today's consolidated view: regime + positions + earnings + journal."""
        return cockpit(project_id)

    # ── IBKR (READ-ONLY — no order endpoints exist, by design) ──
    @router.get("/ibkr/status")
    def ibkr_status() -> Dict[str, Any]:
        from agent.finance import ibkr_connector
        return ibkr_connector.status()

    @router.get("/ibkr/account")
    def ibkr_account() -> Dict[str, Any]:
        from agent.finance import ibkr_connector
        return ibkr_connector.account()

    @router.get("/ibkr/positions")
    def ibkr_positions() -> Dict[str, Any]:
        from agent.finance import ibkr_connector
        return ibkr_connector.positions()

    @router.get("/ibkr/spreads")
    def ibkr_spreads() -> Dict[str, Any]:
        """Live OPT legs grouped into verticals + defined-risk status
        (credit / max P&L / DTE / cushion) from underlying + terms."""
        from agent.finance import ibkr_connector
        return ibkr_connector.spreads()

    @router.get("/ibkr/quote/{symbol}")
    def ibkr_quote(symbol: str) -> Dict[str, Any]:
        from agent.finance import ibkr_connector
        return ibkr_connector.quote(symbol)

    @router.get("/ibkr/bars/{symbol}")
    def ibkr_bars(symbol: str, duration: str = "1 Y", bar_size: str = "1 day") -> Dict[str, Any]:
        from agent.finance import ibkr_connector
        return ibkr_connector.bars(symbol, duration=duration, bar_size=bar_size)

    @router.get("/ibkr/open_orders")
    def ibkr_open_orders() -> Dict[str, Any]:
        from agent.finance import ibkr_connector
        return ibkr_connector.open_orders()

    @router.post("/ibkr/route")
    def ibkr_set_route(on: bool = True) -> Dict[str, Any]:
        """Back-compat: on→venue=ibkr, off→venue=sim."""
        return set_ibkr_route(on)

    @router.post("/venue")
    def post_venue(venue: str = "sim") -> Dict[str, Any]:
        """Set execution venue + single source of truth: 'sim' | 'ibkr'."""
        return set_venue(venue)

    @router.post("/allow_live")
    def post_allow_live(on: bool = False, confirm: str = "") -> Dict[str, Any]:
        """REAL-MONEY switch. ON requires confirm='I_UNDERSTAND_REAL_MONEY'.
        This is the ONLY behavioral difference between paper and live."""
        return set_allow_live(on, confirm)

    @router.post("/budget")
    def post_budget(usd: float = 0) -> Dict[str, Any]:
        """Ring-fenced budget in USD (0 = derive from budget_pct_of_liquid)."""
        return set_trading_budget(usd)

    @router.post("/ibkr/test_order")
    def ibkr_test_order(symbol: str = "AAPL", quantity: int = 1,
                        limit_price: Optional[float] = None,
                        stop_loss: Optional[float] = None,
                        take_profit: Optional[float] = None) -> Dict[str, Any]:
        """Place ONE small paper order to prove the pipe + DU-guard. With a
        limit far from market it rests as pending (safe to cancel). Pass
        stop_loss + take_profit to exercise the full bracket (OCA) path."""
        # intent-log + send + leg-log + 3-source verification
        return place_log_verify(symbol, "BUY", quantity, limit_price=limit_price,
                                stop_loss=stop_loss, take_profit=take_profit, source="test")

    @router.post("/ibkr/cancel_all")
    def ibkr_cancel_all() -> Dict[str, Any]:
        from agent.finance import ibkr_connector
        # snapshot what's open BEFORE cancelling, so the archive records exactly
        # which orders were killed (not just a count)
        try:
            before = ibkr_connector.open_orders().get("orders") or []
        except Exception:
            before = []
        res = ibkr_connector.cancel_all_paper(allow_live=bool(get_state().get("allow_live")))
        ibkr_log_event("cancel_all", account=res.get("account"),
                       status=("ok" if res.get("ok") else "error"), source="manual",
                       detail={"cancelled": res.get("cancelled"), "error": res.get("error"),
                               "orders_before": before})
        return res

    @router.get("/ibkr/executions")
    def ibkr_executions() -> Dict[str, Any]:
        from agent.finance import ibkr_connector
        return ibkr_connector.executions()

    @router.post("/ibkr/snapshot")
    def ibkr_snapshot_now() -> Dict[str, Any]:
        """Archive current IBKR account/positions/orders/fills into ibkr_log."""
        return ibkr_snapshot()

    @router.get("/ibkr/log")
    def ibkr_log(symbol: Optional[str] = None, kind: Optional[str] = None,
                 since: Optional[str] = None, until: Optional[str] = None,
                 limit: int = 200) -> Dict[str, Any]:
        """Query the durable IBKR archive — works even with the Gateway OFF."""
        return ibkr_log_list(symbol=symbol, kind=kind, since=since, until=until, limit=limit)

    @router.get("/ibkr/flex/config")
    def ibkr_flex_config_get() -> Dict[str, Any]:
        """Safe status only — never returns the token."""
        return flex_config_status()

    @router.post("/ibkr/flex/config")
    def ibkr_flex_config_set(cfg: FlexCfgBody) -> Dict[str, Any]:
        return flex_set_config(cfg.token, cfg.query_id)

    @router.post("/ibkr/flex/sync")
    def ibkr_flex_sync() -> Dict[str, Any]:
        """Pull the authoritative Flex statement → archive into ibkr_log."""
        return flex_sync()

    @router.post("/ibkr/flex/reconcile")
    def ibkr_flex_reconcile(sync: bool = True) -> Dict[str, Any]:
        """Cross-check local executions vs IBKR Flex books → prove completeness."""
        return flex_reconcile(sync=sync)

    @router.post("/review")
    def post_review(auto_retire: bool = True) -> Dict[str, Any]:
        """Auto-retire underperformers + improvement suggestions (#4)."""
        return review_setups(auto_retire=auto_retire)

    @router.post("/scan_trade")
    def post_scan_trade(project_id: str = "fin-core", auto_execute: bool = True) -> Dict[str, Any]:
        """Automated scan: triggers → risk-sized paper entries (gated by the
        global halt + per-setup arming + kill-switch)."""
        return scan_and_trade(project_id, auto_execute=auto_execute)

    return router
