"""Per-project watchlist for the fin dashboard.

Stored as a single JSON file at
    <investment_root>/<project>/watchlist.json

Separate from ``investment_projects.register_project``'s
``watchlist.yaml`` (that file is a human-editable stub that pre-dates
the web UI — we leave it alone for backwards compat). This module
owns the structured version:

    {
      "version": 1,
      "entries": [
        {
          "symbol": "AAPL",
          "market": "US",
          "note": "core holding",
          "added_at": "2026-04-20T02:30:00+00:00"
        },
        ...
      ]
    }

Endpoints (all project-scoped, never cross-project):
    GET    /api/watchlist                     → list
    POST   /api/watchlist                     → upsert one entry
    PATCH  /api/watchlist/{symbol}            → update note
    DELETE /api/watchlist/{symbol}            → remove

A symbol is identified by ``(market, symbol)`` together — the same
code number can exist in US and CN registers, so we never match on
symbol alone.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field

from agent.finance import investment_projects

logger = logging.getLogger(__name__)

_VERSION = 1
_VALID_MARKETS = {"US", "CN", "HK"}
_SYMBOL_RE = re.compile(r"^[A-Za-z0-9._-]{1,16}$")
_MAX_NOTE_LEN = 500
_MAX_ENTRIES = 200


def _validate_project(pid: str) -> str:
    if not isinstance(pid, str) or not investment_projects._PROJECT_ID_RE.match(pid):
        raise HTTPException(400, f"invalid project_id {pid!r}")
    if pid not in investment_projects.list_projects():
        raise HTTPException(404, f"project {pid!r} is not registered")
    return pid


def _validate_symbol(sym: str) -> str:
    if not _SYMBOL_RE.match(sym):
        raise HTTPException(400, f"invalid symbol {sym!r}")
    return sym


def _validate_market(m: str) -> str:
    if m not in _VALID_MARKETS:
        raise HTTPException(400, f"invalid market {m!r} (expected US/CN/HK)")
    return m


def _watchlist_path(pid: str) -> Path:
    return investment_projects.get_project_dir(pid) / "watchlist.json"


def _load(pid: str) -> Dict[str, Any]:
    path = _watchlist_path(pid)
    if not path.exists():
        return {"version": _VERSION, "entries": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("watchlist corrupt, resetting: %s", exc)
        return {"version": _VERSION, "entries": []}
    if not isinstance(data, dict) or "entries" not in data:
        return {"version": _VERSION, "entries": []}
    return data


def _save(pid: str, data: Dict[str, Any]) -> None:
    path = _watchlist_path(pid)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _key(entry: Dict[str, Any]) -> tuple:
    return (str(entry.get("market", "")).upper(), str(entry.get("symbol", "")).upper())


class WatchEntry(BaseModel):
    symbol: str = Field(..., description="Ticker symbol, market-dependent format")
    market: str = Field(..., description="US | CN | HK")
    note: str = Field("", description="User note, optional")
    added_at: Optional[str] = None


class NotePatch(BaseModel):
    note: str = ""


def build_watchlist_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/watchlist")
    def list_entries(project_id: str = Query(...)) -> Dict[str, Any]:
        pid = _validate_project(project_id)
        data = _load(pid)
        return {"project_id": pid, "count": len(data.get("entries", [])), "entries": data.get("entries", [])}

    @router.post("/api/watchlist")
    def upsert_entry(
        project_id: str = Query(...),
        entry: WatchEntry = Body(...),
    ) -> Dict[str, Any]:
        pid = _validate_project(project_id)
        symbol = _validate_symbol(entry.symbol).upper()
        market = _validate_market(entry.market.upper())
        note = entry.note[:_MAX_NOTE_LEN] if entry.note else ""

        data = _load(pid)
        entries: List[Dict[str, Any]] = data.get("entries", [])
        key = (market, symbol)

        now = datetime.now(timezone.utc).isoformat()
        found = False
        for e in entries:
            if _key(e) == key:
                e["note"] = note
                e["updated_at"] = now
                found = True
                break
        if not found:
            if len(entries) >= _MAX_ENTRIES:
                raise HTTPException(
                    413,
                    f"watchlist full ({_MAX_ENTRIES} entries max) — remove some first",
                )
            entries.append({
                "symbol": symbol,
                "market": market,
                "note": note,
                "added_at": now,
            })
        data["entries"] = entries
        data["version"] = _VERSION
        _save(pid, data)
        return {"ok": True, "symbol": symbol, "market": market, "count": len(entries)}

    @router.patch("/api/watchlist/{symbol}")
    def update_note(
        symbol: str,
        project_id: str = Query(...),
        market: str = Query(...),
        patch: NotePatch = Body(...),
    ) -> Dict[str, Any]:
        pid = _validate_project(project_id)
        sym = _validate_symbol(symbol).upper()
        mkt = _validate_market(market.upper())
        note = (patch.note or "")[:_MAX_NOTE_LEN]

        data = _load(pid)
        entries = data.get("entries", [])
        for e in entries:
            if _key(e) == (mkt, sym):
                e["note"] = note
                e["updated_at"] = datetime.now(timezone.utc).isoformat()
                _save(pid, data)
                return {"ok": True, "symbol": sym, "market": mkt}
        raise HTTPException(404, f"{mkt}:{sym} not in watchlist")

    @router.delete("/api/watchlist/{symbol}")
    def delete_entry(
        symbol: str,
        project_id: str = Query(...),
        market: str = Query(...),
    ) -> Dict[str, Any]:
        pid = _validate_project(project_id)
        sym = _validate_symbol(symbol).upper()
        mkt = _validate_market(market.upper())

        data = _load(pid)
        entries = data.get("entries", [])
        new_entries = [e for e in entries if _key(e) != (mkt, sym)]
        if len(new_entries) == len(entries):
            raise HTTPException(404, f"{mkt}:{sym} not in watchlist")
        data["entries"] = new_entries
        _save(pid, data)
        return {"ok": True, "count": len(new_entries)}

    return router
