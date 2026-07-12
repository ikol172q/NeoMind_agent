"""IBKR Flex Web Service — authoritative statement backstop.

The live API (ib_async over the Gateway) only returns the CURRENT day's
executions, so a fill that happens while nothing is polling is lost from our
local archive. IBKR's **Flex Web Service** is the server-side, permanent record
(trades / positions / cash) — including paper accounts. This module pulls a
Flex statement and hands the parsed rows to the desk for archiving into
``ibkr_log`` (deduped by IBKR's tradeID), so backtrace is lossless even across
days the Gateway was off.

Setup the USER does once in IBKR Client Portal:
  1. Performance & Reports → Flex Queries → create an *Activity* Flex Query
     (include Trades, Open Positions, Cash Report). Note its **Query ID**.
  2. Generate a **Flex Web Service token** (same area / Settings).
Then paste token + query id into the Trading tab; we store them locally and
never return the token over any API.

Protocol (v3):
  SendRequest?t=<token>&q=<queryId>&v=3  → ReferenceCode + base Url
  <Url>?t=<token>&q=<ReferenceCode>&v=3  → the FlexQueryResponse XML
"""
from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

_SEND_URL = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/SendRequest"
_TIMEOUT = 25


def _get(url: str, params: Dict[str, str]) -> str:
    r = requests.get(url, params=params, timeout=_TIMEOUT,
                     headers={"User-Agent": "neomind-fin/1.0"})
    r.raise_for_status()
    return r.text


def fetch_statement(token: str, query_id: str, max_wait: float = 30.0) -> Dict[str, Any]:
    """Run the 2-step Flex Web Service flow. Returns
    {'ok':True,'account':..,'trades':[..],'positions':[..],'cash':[..]} or
    {'ok':False,'error':..}. Never raises for IBKR-side errors."""
    token = (token or "").strip()
    query_id = (query_id or "").strip()
    if not token or not query_id:
        return {"ok": False, "error": "缺少 Flex token 或 query id"}

    # ── step 1: request statement generation ──
    try:
        xml1 = _get(_SEND_URL, {"t": token, "q": query_id, "v": "3"})
    except Exception as exc:
        return {"ok": False, "error": f"SendRequest 失败: {type(exc).__name__}: {exc}"}
    try:
        root1 = ET.fromstring(xml1)
    except ET.ParseError as exc:
        return {"ok": False, "error": f"SendRequest 返回非 XML: {exc} — {xml1[:120]}"}
    status = (root1.findtext("Status") or "").strip()
    if status.lower() != "success":
        return {"ok": False, "error": f"Flex SendRequest 状态={status or '?'}: "
                f"{root1.findtext('ErrorCode') or ''} {root1.findtext('ErrorMessage') or xml1[:160]}"}
    ref = (root1.findtext("ReferenceCode") or "").strip()
    base = (root1.findtext("Url") or "").strip()
    if not ref or not base:
        return {"ok": False, "error": "Flex 响应缺少 ReferenceCode/Url"}

    # ── step 2: poll for the statement (generation can lag a few seconds) ──
    deadline = time.time() + max_wait
    xml2 = ""
    while time.time() < deadline:
        try:
            xml2 = _get(base, {"t": token, "q": ref, "v": "3"})
        except Exception as exc:
            return {"ok": False, "error": f"GetStatement 失败: {type(exc).__name__}: {exc}"}
        # if still generating, IBKR returns a FlexStatementResponse w/ a Warn status
        if "<FlexQueryResponse" in xml2:
            break
        if "Statement generation in progress" in xml2 or "<Status>Warn</Status>" in xml2:
            time.sleep(2.0)
            continue
        break
    if "<FlexQueryResponse" not in xml2:
        return {"ok": False, "error": f"Flex 未就绪/出错: {xml2[:200]}"}

    return _parse_statement(xml2)


def _parse_statement(xml_text: str) -> Dict[str, Any]:
    """Defensively parse trades / open positions / cash out of a Flex
    statement. Field sets vary by how the user configured the query, so we read
    attributes by name and tolerate absence."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        return {"ok": False, "error": f"statement 解析失败: {exc}"}

    stmt = root.find(".//FlexStatement")
    account = stmt.get("accountId") if stmt is not None else None

    def attr(el, *names):
        for n in names:
            v = el.get(n)
            if v not in (None, ""):
                return v
        return None

    trades: List[Dict[str, Any]] = []
    for t in root.findall(".//Trade"):
        trades.append({
            "trade_id": attr(t, "tradeID", "transactionID"),
            "symbol": attr(t, "symbol"),
            "side": (attr(t, "buySell") or "").upper(),
            "qty": _f(attr(t, "quantity")),
            "price": _f(attr(t, "tradePrice", "price")),
            "datetime": attr(t, "dateTime", "tradeDate", "orderTime"),
            "commission": _f(attr(t, "ibCommission", "commission")),
            "proceeds": _f(attr(t, "proceeds")),
            "account": attr(t, "accountId") or account,
        })

    positions: List[Dict[str, Any]] = []
    for p in root.findall(".//OpenPosition"):
        positions.append({
            "symbol": attr(p, "symbol"),
            "qty": _f(attr(p, "position")),
            "cost_basis_price": _f(attr(p, "costBasisPrice", "openPrice")),
            "mark_price": _f(attr(p, "markPrice")),
            "account": attr(p, "accountId") or account,
        })

    cash: List[Dict[str, Any]] = []
    for c in root.findall(".//CashReportCurrency"):
        cash.append({
            "currency": attr(c, "currency"),
            "ending_cash": _f(attr(c, "endingCash", "endingSettledCash")),
            "account": attr(c, "accountId") or account,
        })

    return {"ok": True, "account": account, "trades": trades,
            "positions": positions, "cash": cash}


def _f(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
