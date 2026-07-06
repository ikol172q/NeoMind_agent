"""Interactive Brokers connector — READ by default, PAPER-ONLY orders.

⚠️ SAFETY INVARIANTS (two independent layers):
  1. Read paths (status/account/positions/quote) connect with ``readonly=True``
     so IB's own servers reject any order from that client.
  2. The ONE order path (``place_paper_bracket``) connects with readonly=False
     but is HARD-GUARDED by ``_assert_paper``: before placing anything it asserts
     EVERY managed account starts with ``DU`` (IBKR paper-account prefix). A live
     account ("U…") makes it abort and place nothing. So a real order is
     structurally impossible — it would require IBKR to hand a paper-port login a
     live account, which it does not.
This was explicitly authorized by the user for high-intensity paper testing
("下到 IBKR paper 账户"). The user's "不要执行" stands for REAL orders — paper
orders into a DU account move no real money.

Connection: the USER runs IB Gateway or TWS locally + logs in + enables the
API. We connect over a socket. Config via env:
    IB_GATEWAY_HOST   (default 127.0.0.1)
    IB_GATEWAY_PORT   (default 7497  — TWS paper; 7496 TWS live;
                        4002 Gateway paper; 4001 Gateway live)
    IB_CLIENT_ID      (default 9)

Each call runs in its OWN thread + event loop so it never collides with the
FastAPI server's loop (ib_async/ib_insync are asyncio-based).
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

# Hard, explicit invariant. Referenced in status output so the UI can prove it.
IBKR_READONLY = True
# Orders are allowed ONLY against accounts with this prefix (IBKR paper).
PAPER_ACCT_PREFIX = "DU"
# Serializes all IBKR socket access (same clientId can't have 2 live connections).
_IB_LOCK = threading.Lock()


def _config() -> Dict[str, Any]:
    return {
        "host": os.getenv("IB_GATEWAY_HOST", "127.0.0.1"),
        "port": int(os.getenv("IB_GATEWAY_PORT", "7497")),
        "client_id": int(os.getenv("IB_CLIENT_ID", "9")),
        "readonly": True,
    }


def _assert_tradeable(ib, allow_live: bool = False) -> str:
    """SAFETY GATE. Returns the account to trade, or raises.

    The order-building code is account-agnostic — paper and live run the SAME
    path. The ONLY behavioral difference between paper and real money is this
    one flag:
      • allow_live=False (default): refuse unless EVERY account is paper (DU…).
        Real (U…) accounts are structurally untouchable. This is the safe state.
      • allow_live=True: real accounts permitted = REAL MONEY. Caller must have
        deliberately enabled it (state.allow_live), which is exactly "am I using
        real money." Nothing else about the flow changes."""
    accts = [a for a in ib.managedAccounts() if a]
    if not accts:
        raise RuntimeError("无可用账户（managedAccounts 为空）— 拒绝下单")
    if not allow_live:
        bad = [a for a in accts if not a.upper().startswith(PAPER_ACCT_PREFIX)]
        if bad:
            raise RuntimeError(
                f"安全中止：检测到非 paper 账户 {bad}（real-money 未启用，paper 必须以 "
                f"{PAPER_ACCT_PREFIX} 开头）— 拒绝下任何单")
    return accts[0]


# back-compat alias (paper-only)
def _assert_paper(ib) -> str:
    return _assert_tradeable(ib, allow_live=False)


def _run_ib(fn: Callable[[Any, Any], Any], timeout: float = 8.0,
            readonly: bool = True) -> Dict[str, Any]:
    """Run `fn(ib, m)` in an isolated thread+loop with an IB connection (`m` is
    the ib_async/ib_insync module → order classes via m.Stock/m.MarketOrder…).
    Returns {'data':...} or {'error':...}. Always disconnects.

    The ib_async/ib_insync IMPORT happens inside this worker thread on purpose:
    those libs patch asyncio at import/instantiation, which conflicts with the
    server's running loop (uvloop). A fresh thread + vanilla loop avoids that.

    SERIALIZED by _IB_LOCK: every IBKR socket op uses the same clientId, so two
    overlapping connections would collide ('clientId already in use') and one
    would spuriously report 'IBKR down'. The lock makes only one connection
    exist at a time (each op is short); concurrent requests queue instead."""
    cfg = _config()
    out: Dict[str, Any] = {}

    def worker():
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        # import inside the thread (clean loop) — prefer ib_async, fall back to ib_insync
        m = IB = None
        errs = []
        for mod in ("ib_async", "ib_insync"):
            try:
                m = __import__(mod, fromlist=["IB", "Stock"])
                IB = m.IB
                break
            except Exception as exc:
                errs.append(f"{mod}: {type(exc).__name__}: {exc}")
        if IB is None:
            out["error"] = "导入失败 — " + " | ".join(errs)
            out["lib_missing"] = True
            return
        # NOTE: do NOT call nest_asyncio.apply() — it monkeypatches asyncio
        # GLOBALLY and can poison the server's own (uvloop) event loop. The
        # dedicated thread + fresh loop + run_until_complete needs no patching.
        ib = IB()
        try:
            # use the async connect explicitly (avoids the sync wrapper's
            # asyncio-timeout-context issue inside a worker thread), then let
            # account/position data stream in before reading.
            loop.run_until_complete(ib.connectAsync(
                cfg["host"], cfg["port"], clientId=cfg["client_id"],
                timeout=min(timeout, 6.0), readonly=readonly))
            loop.run_until_complete(asyncio.sleep(0.8))
            out["data"] = fn(ib, m)
        except Exception as exc:
            out["error"] = (f"连不上 IB {cfg['host']}:{cfg['port']} — 确认 IB Gateway/TWS "
                            f"已启动并登录、API 已开启、端口/clientId 匹配。({type(exc).__name__}: {exc})")
        finally:
            try:
                ib.disconnect()
            except Exception:
                pass
            try:
                loop.close()
            except Exception:
                pass

    # serialize: one IBKR connection (one clientId) at a time across the process
    got = _IB_LOCK.acquire(timeout=timeout + 12)
    if not got:
        return {"error": "IB 忙（另一个 IBKR 操作进行中，请稍候重试）"}
    try:
        th = threading.Thread(target=worker, daemon=True)
        th.start()
        th.join(timeout=timeout + 4)
        if th.is_alive():
            return {"error": "IB 连接超时（Gateway 未响应）"}
        return out
    finally:
        _IB_LOCK.release()


def status() -> Dict[str, Any]:
    cfg = _config()
    base = {"readonly": True, "config": {"host": cfg["host"], "port": cfg["port"],
                                         "client_id": cfg["client_id"]}}
    r = _run_ib(lambda ib, m: {"accounts": list(ib.managedAccounts()),
                               "server_version": ib.client.serverVersion()})
    if r.get("error"):
        return {**base, "connected": False, "error": r["error"], "lib_missing": r.get("lib_missing", False)}
    d = r["data"]
    accts = d["accounts"]
    is_paper = bool(accts) and all(a.upper().startswith(PAPER_ACCT_PREFIX) for a in accts)
    return {**base, "connected": True, "accounts": accts,
            "server_version": d["server_version"],
            "is_paper": is_paper, "order_enabled": is_paper}


def account() -> Dict[str, Any]:
    def fn(ib, m):
        vals = ib.accountValues()
        want = {"NetLiquidation", "TotalCashValue", "AvailableFunds",
                "BuyingPower", "GrossPositionValue", "UnrealizedPnL", "RealizedPnL"}
        rows = {}
        for v in vals:
            if v.tag in want and v.currency in ("USD", "BASE", ""):
                rows[v.tag] = v.value
        return rows
    r = _run_ib(fn)
    if r.get("error"):
        return {"connected": False, "error": r["error"], "readonly": True}
    return {"connected": True, "readonly": True, "values": r["data"]}


def _serialize_position(p) -> Dict[str, Any]:
    """Serialize an IBKR Position incl. option contract details (strike/right/
    expiry/multiplier) so spreads are readable — these were dropped before
    2026-07-05, making 'NVDA OPT -1 / +1' ambiguous (can't tell the legs)."""
    c = p.contract
    d = {"symbol": getattr(c, "symbol", "?"),
         "sec_type": getattr(c, "secType", ""),
         "position": p.position, "avg_cost": round(p.avgCost, 2),
         "account": p.account}
    if getattr(c, "secType", "") in ("OPT", "FOP"):
        d.update({"expiry": getattr(c, "lastTradeDateOrContractMonth", "") or "",
                  "strike": getattr(c, "strike", None),
                  "right": getattr(c, "right", "") or "",
                  "multiplier": getattr(c, "multiplier", "") or ""})
    return d


def positions() -> Dict[str, Any]:
    def fn(ib, m):
        return [_serialize_position(p) for p in ib.positions()]
    r = _run_ib(fn)
    if r.get("error"):
        return {"connected": False, "error": r["error"], "readonly": True, "positions": []}
    return {"connected": True, "readonly": True, "positions": r["data"]}


def quote(symbol: str) -> Dict[str, Any]:
    def fn(ib, m):
        # 1=real-time(needs subscription), 3=delayed(free, ~15min), 4=delayed-frozen.
        # Fall back to delayed so the field isn't null without a market-data sub.
        try:
            ib.reqMarketDataType(3)
        except Exception:
            pass
        contract = m.Stock(symbol.upper(), "SMART", "USD")
        ib.qualifyContracts(contract)
        t = ib.reqTickers(contract)
        if not t:
            return None
        tk = t[0]
        def _v(x):
            return None if x is None or (isinstance(x, float) and x != x) else x  # drop NaN
        return {"symbol": symbol.upper(), "last": _v(tk.last), "bid": _v(tk.bid),
                "ask": _v(tk.ask), "close": _v(tk.close),
                "freshness": "delayed(~15m)"}
    r = _run_ib(fn)
    if r.get("error"):
        return {"connected": False, "error": r["error"], "readonly": True}
    return {"connected": True, "readonly": True, "quote": r["data"]}


def bars(symbol: str, duration: str = "1 Y", bar_size: str = "1 day") -> Dict[str, Any]:
    """Read-only historical OHLCV from IBKR (same source as execution → no
    data-source mismatch between backtest/scan and fills). `duration` e.g.
    '1 Y' / '6 M' / '5 D'; `bar_size` e.g. '1 day' / '1 hour' / '15 mins'."""
    def fn(ib, m):
        contract = m.Stock(symbol.upper(), "SMART", "USD")
        ib.qualifyContracts(contract)
        bs = ib.reqHistoricalData(contract, endDateTime="", durationStr=duration,
                                  barSizeSetting=bar_size, whatToShow="TRADES",
                                  useRTH=True, formatDate=1)
        return [{"date": str(b.date), "open": b.open, "high": b.high, "low": b.low,
                 "close": b.close, "volume": b.volume} for b in (bs or [])]
    r = _run_ib(fn, timeout=20.0)
    if r.get("error"):
        return {"connected": False, "error": r["error"], "readonly": True, "bars": []}
    return {"connected": True, "readonly": True, "bars": r["data"], "source": "ibkr"}


def bars_multi(symbols: List[str], duration: str = "1 Y",
               bar_size: str = "1 day") -> Dict[str, Any]:
    """Fetch historical OHLCV for MANY symbols in ONE connection (vs one socket
    per symbol). Big speedup for the venue=ibkr scan. Returns {sym: [bars]}."""
    syms = [s.upper() for s in (symbols or []) if s]

    def fn(ib, m):
        out: Dict[str, Any] = {}
        for s in syms:
            try:
                c = m.Stock(s, "SMART", "USD")
                ib.qualifyContracts(c)
                bs = ib.reqHistoricalData(c, endDateTime="", durationStr=duration,
                                          barSizeSetting=bar_size, whatToShow="TRADES",
                                          useRTH=True, formatDate=1)
                out[s] = [{"date": str(b.date), "open": b.open, "high": b.high,
                           "low": b.low, "close": b.close, "volume": b.volume}
                          for b in (bs or [])]
            except Exception:
                out[s] = []
        return out
    r = _run_ib(fn, timeout=max(20.0, 2.5 * len(syms)))
    if r.get("error"):
        return {"connected": False, "error": r["error"], "bars": {}}
    return {"connected": True, "bars": r["data"], "source": "ibkr"}


def open_orders() -> Dict[str, Any]:
    """Read-only: list open/pending orders + recent trades in the account."""
    def fn(ib, m):
        rows = []
        for t in ib.openTrades():
            o, c, st = t.order, t.contract, t.orderStatus
            rows.append({"order_id": o.orderId, "symbol": getattr(c, "symbol", "?"),
                         "action": o.action, "qty": o.totalQuantity,
                         "type": o.orderType, "tif": getattr(o, "tif", ""),
                         "limit": getattr(o, "lmtPrice", None) or None,
                         "stop": getattr(o, "auxPrice", None) or None,
                         "status": st.status, "filled": st.filled,
                         "remaining": st.remaining, "oca": getattr(o, "ocaGroup", "")})
        return rows
    r = _run_ib(fn)
    if r.get("error"):
        return {"connected": False, "error": r["error"], "readonly": True, "orders": []}
    return {"connected": True, "readonly": True, "orders": r["data"]}


def account_snapshot() -> Dict[str, Any]:
    """Read EVERYTHING (accounts + values + positions + open orders + today's
    fills) in ONE socket connection. The scan/snapshot/verify paths used to open
    a fresh connection per call (5–12 per scan → 80s+ and connection churn);
    this collapses them into a single round-trip. Read-only."""
    def fn(ib, m):
        # each sub-read is isolated: a slow/flaky one (e.g. openTrades) must NOT
        # blank out the whole snapshot, else the scan wrongly thinks IBKR is down.
        errs = {}
        try:
            ib.reqExecutions()
        except Exception:
            pass
        ib.sleep(0.7)
        try:
            accts = [a for a in ib.managedAccounts() if a]
        except Exception as e:
            accts = []; errs["accounts"] = str(e)
        want = {"NetLiquidation", "TotalCashValue", "AvailableFunds", "BuyingPower",
                "GrossPositionValue", "UnrealizedPnL", "RealizedPnL"}
        try:
            values = {v.tag: v.value for v in ib.accountValues()
                      if v.tag in want and v.currency in ("USD", "BASE", "")}
        except Exception as e:
            values = {}; errs["values"] = str(e)
        try:
            positions = [_serialize_position(p) for p in ib.positions()]
        except Exception as e:
            positions = []; errs["positions"] = str(e)
        orders = []
        try:
            for t in ib.openTrades():
                o, c, st = t.order, t.contract, t.orderStatus
                orders.append({"order_id": o.orderId, "symbol": getattr(c, "symbol", "?"),
                               "action": o.action, "qty": o.totalQuantity, "type": o.orderType,
                               "tif": getattr(o, "tif", ""),
                               "limit": getattr(o, "lmtPrice", None) or None,
                               "stop": getattr(o, "auxPrice", None) or None,
                               "status": st.status, "filled": st.filled,
                               "remaining": st.remaining, "oca": getattr(o, "ocaGroup", "")})
        except Exception as e:
            errs["orders"] = str(e)
        fills = []
        try:
            for f in ib.fills():
                e_, c = f.execution, f.contract
                cm = getattr(f, "commissionReport", None)
                fills.append({"exec_id": e_.execId, "time": str(e_.time),
                              "symbol": getattr(c, "symbol", "?"), "side": e_.side,
                              "shares": float(e_.shares), "price": float(e_.price),
                              "account": e_.acctNumber,
                              "commission": getattr(cm, "commission", None) if cm else None})
        except Exception as e:
            errs["fills"] = str(e)
        return {"accounts": accts, "values": values, "positions": positions,
                "orders": orders, "fills": fills, "partial_errors": errs or None}
    r = _run_ib(fn, timeout=18.0)
    if r.get("error"):
        return {"connected": False, "error": r["error"], "accounts": [], "values": {},
                "positions": [], "orders": [], "fills": []}
    return {"connected": True, **r["data"]}


def executions() -> Dict[str, Any]:
    """Read-only: today's fills (IBKR only returns the current day via API —
    this is exactly why we archive snapshots locally)."""
    def fn(ib, m):
        try:
            ib.reqExecutions()
        except Exception:
            pass
        ib.sleep(0.6)
        rows = []
        for f in ib.fills():
            e, c = f.execution, f.contract
            cm = getattr(f, "commissionReport", None)
            rows.append({"exec_id": e.execId, "time": str(e.time),
                         "symbol": getattr(c, "symbol", "?"), "side": e.side,
                         "shares": float(e.shares), "price": float(e.price),
                         "account": e.acctNumber,
                         "commission": getattr(cm, "commission", None) if cm else None})
        return rows
    r = _run_ib(fn)
    if r.get("error"):
        return {"connected": False, "error": r["error"], "readonly": True, "fills": []}
    return {"connected": True, "readonly": True, "fills": r["data"]}


def place_paper_bracket(symbol: str, action: str, quantity: int,
                        limit_price: Optional[float] = None,
                        stop_loss: Optional[float] = None,
                        take_profit: Optional[float] = None,
                        timeout: float = 14.0,
                        allow_live: bool = False) -> Dict[str, Any]:
    """Place a bracket: parent market (or limit) entry + optional OCA stop-loss
    / take-profit children. Account-agnostic — paper and live run this SAME
    code. Guarded by _assert_tradeable(allow_live): with allow_live=False
    (default) any non-DU (real) account is refused, so real money is untouchable
    unless the caller has deliberately enabled it.

    Returns {'ok':True, 'account':..., 'orders':[...]} or {'ok':False,'error':...}."""
    action = (action or "").upper()
    if action not in ("BUY", "SELL"):
        return {"ok": False, "error": "action 必须是 BUY 或 SELL"}
    quantity = int(quantity)
    if quantity <= 0:
        return {"ok": False, "error": "quantity 必须 > 0"}

    def fn(ib, m):
        acct = _assert_tradeable(ib, allow_live)   # <-- SAFETY GATE
        contract = m.Stock(symbol.upper(), "SMART", "USD")
        ib.qualifyContracts(contract)
        opp = "SELL" if action == "BUY" else "BUY"

        # TPS: async swing → GTC (let the market come to you, survives overnight)
        # + outsideRth so a limit can also fill pre/post-market. Applied to every
        # leg so the whole bracket is GTC.
        def _gtc(o):
            o.tif = "GTC"
            o.outsideRth = True
            return o

        parent = (m.LimitOrder(action, quantity, round(float(limit_price), 2))
                  if limit_price else m.MarketOrder(action, quantity))
        _gtc(parent)
        parent.orderId = ib.client.getReqId()
        parent.account = acct
        parent.transmit = False

        children = []
        oca = f"oca_{parent.orderId}"
        if take_profit:
            tp = _gtc(m.LimitOrder(opp, quantity, round(float(take_profit), 2)))
            tp.orderId = ib.client.getReqId(); tp.parentId = parent.orderId
            tp.account = acct; tp.ocaGroup = oca; tp.ocaType = 1; tp.transmit = False
            children.append(tp)
        if stop_loss:
            sl = _gtc(m.StopOrder(opp, quantity, round(float(stop_loss), 2)))
            sl.orderId = ib.client.getReqId(); sl.parentId = parent.orderId
            sl.account = acct; sl.ocaGroup = oca; sl.ocaType = 1; sl.transmit = False
            children.append(sl)
        # the LAST order transmitted flips the whole bundle live
        (children[-1] if children else parent).transmit = True

        trades = [ib.placeOrder(contract, parent)]
        for ch in children:
            trades.append(ib.placeOrder(contract, ch))
        ib.sleep(1.2)   # let order acks come back
        symu = symbol.upper()
        return {"account": acct,
                "orders": [{"order_id": t.order.orderId, "symbol": symu,
                            "kind": t.order.orderType, "action": t.order.action,
                            "qty": t.order.totalQuantity,
                            "status": t.orderStatus.status} for t in trades]}

    r = _run_ib(fn, timeout=timeout, readonly=False)
    if r.get("error"):
        return {"ok": False, "error": r["error"]}
    return {"ok": True, "readonly": False, **r["data"]}


def place_option_order(symbol: str, expiry: str, strike: float, right: str,
                       action: str, quantity: int, limit_price: Optional[float] = None,
                       timeout: float = 16.0, allow_live: bool = False) -> Dict[str, Any]:
    """Place an OPTION order — HEDGE-ONLY by hard rule: only BUY PUT is allowed
    (protective hedge). Selling / calls are blocked at this lowest level so the
    user's red line ('options 仅对冲，不裸卖，不买 call 投机') can't be violated
    even by a wrong caller. DU-account guarded (paper unless allow_live). GTC
    limit. `expiry` is YYYYMMDD.

    Returns {'ok':True,'order_id':..,'status':..} or {'ok':False,'error':..}."""
    right = (right or "").upper()[:1]
    action = (action or "").upper()
    if right != "P" or action != "BUY":
        return {"ok": False, "error": "对冲叠加层只允许「买入 PUT」（保护性对冲）；"
                "卖出 / CALL 被红线拦截"}
    quantity = int(quantity)
    if quantity <= 0:
        return {"ok": False, "error": "quantity 必须 > 0"}

    def fn(ib, m):
        acct = _assert_tradeable(ib, allow_live)        # <-- DU SAFETY GATE
        c = m.Option(symbol.upper(), expiry, float(strike), "P", "SMART")
        c.currency = "USD"
        ib.qualifyContracts(c)
        if not getattr(c, "conId", None):
            raise RuntimeError(f"期权合约无法解析（{symbol} {expiry} {strike}P）")
        order = (m.LimitOrder("BUY", quantity, round(float(limit_price), 2))
                 if limit_price else m.MarketOrder("BUY", quantity))
        order.tif = "GTC"
        order.account = acct
        t = ib.placeOrder(c, order)
        ib.sleep(1.3)
        return {"account": acct, "order_id": t.order.orderId,
                "symbol": symbol.upper(), "expiry": expiry, "strike": float(strike),
                "right": "P", "action": "BUY", "qty": quantity,
                "limit": round(float(limit_price), 2) if limit_price else None,
                "status": t.orderStatus.status,
                "con_id": getattr(c, "conId", None)}
    r = _run_ib(fn, timeout=timeout, readonly=False)
    if r.get("error"):
        return {"ok": False, "error": r["error"]}
    return {"ok": True, "readonly": False, **r["data"]}


def cancel_all_paper(timeout: float = 12.0, allow_live: bool = False) -> Dict[str, Any]:
    """Cancel ALL open orders in the account. Guarded by _assert_tradeable."""
    def fn(ib, m):
        acct = _assert_tradeable(ib, allow_live)
        n = 0
        for t in ib.openTrades():
            ib.cancelOrder(t.order); n += 1
        ib.sleep(1.0)
        return {"account": acct, "cancelled": n}
    r = _run_ib(fn, timeout=timeout, readonly=False)
    if r.get("error"):
        return {"ok": False, "error": r["error"]}
    return {"ok": True, **r["data"]}


def cancel_symbol_orders(symbol: str, timeout: float = 12.0,
                         allow_live: bool = False) -> Dict[str, Any]:
    """Cancel only the open orders for ONE symbol (e.g. a position's resting
    OCA bracket before a time-stop close). Guarded by _assert_tradeable."""
    symu = (symbol or "").upper()

    def fn(ib, m):
        acct = _assert_tradeable(ib, allow_live)
        n = 0
        for t in ib.openTrades():
            if getattr(t.contract, "symbol", "").upper() == symu:
                ib.cancelOrder(t.order); n += 1
        ib.sleep(1.0)
        return {"account": acct, "cancelled": n, "symbol": symu}
    r = _run_ib(fn, timeout=timeout, readonly=False)
    if r.get("error"):
        return {"ok": False, "error": r["error"]}
    return {"ok": True, **r["data"]}
