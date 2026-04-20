"""Backend validation for the synthesis endpoints.

These are the load-bearing middleware for chat context injection
and workflow slash commands — if they break, everything downstream
gets dumber. Keep them passing.
"""
from __future__ import annotations

import json
import urllib.request
import urllib.error
from urllib.parse import urlencode

import pytest

BASE_URL = "http://127.0.0.1:8001/"
PROJECT = "fin-core"


def _get(path: str, timeout: float = 60.0):
    with urllib.request.urlopen(BASE_URL + path, timeout=timeout) as r:
        return json.loads(r.read())


def _backend_up() -> bool:
    try:
        return _get("api/health", timeout=3).get("status") == "ok"
    except Exception:
        return False


def _quote_ok() -> bool:
    try:
        _get("api/quote/AAPL", timeout=10)
        return True
    except Exception:
        return False


@pytest.fixture(autouse=True, scope="module")
def _skip_if_no_backend():
    if not _backend_up():
        pytest.skip(f"backend not reachable at {BASE_URL}")
    if not _quote_ok():
        pytest.skip("yfinance quote upstream not reachable")


def _reset_watchlist_and_paper():
    # Clear watchlist
    try:
        wl = _get(f"api/watchlist?project_id={PROJECT}", timeout=5)
        for e in wl.get("entries", []):
            req = urllib.request.Request(
                BASE_URL + f"api/watchlist/{e['symbol']}?project_id={PROJECT}&market={e['market']}",
                method="DELETE",
            )
            urllib.request.urlopen(req, timeout=5).read()
    except Exception:
        pass
    # Reset paper
    try:
        req = urllib.request.Request(
            BASE_URL + f"api/paper/reset?project_id={PROJECT}&confirm=yes",
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5).read()
    except Exception:
        pass


def _seed_watch(symbol: str, market: str = "US", note: str = ""):
    req = urllib.request.Request(
        BASE_URL + f"api/watchlist?project_id={PROJECT}",
        data=json.dumps({"symbol": symbol, "market": market, "note": note}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=5).read()


def _seed_position(symbol: str, qty: int = 5):
    qs = urlencode({
        "project_id": PROJECT, "symbol": symbol, "side": "buy",
        "quantity": qty, "order_type": "market",
    })
    urllib.request.urlopen(
        urllib.request.Request(BASE_URL + f"api/paper/order?{qs}", method="POST"),
        timeout=10,
    ).read()
    urllib.request.urlopen(
        urllib.request.Request(BASE_URL + f"api/paper/refresh?project_id={PROJECT}", method="POST"),
        timeout=10,
    ).read()


# ── Symbol synthesis ─────────────────────────────────────

def test_symbol_synth_returns_all_sections_for_us_symbol():
    _reset_watchlist_and_paper()
    _seed_watch("AAPL", "US", "core holding")
    _seed_position("AAPL", qty=5)

    d = _get(f"api/synthesis/symbol/AAPL?project_id={PROJECT}&fresh=1", timeout=120)

    assert d["symbol"] == "AAPL"
    assert d["market"] == "US"
    # Every section should be either populated or explicitly null
    for key in ("quote", "position", "watchlist", "technical", "earnings",
                "sector", "news", "market_sentiment"):
        assert key in d, f"synth missing key {key!r}"
    # Quote should be populated (yfinance smoke passed)
    assert d["quote"] and d["quote"].get("price") is not None
    # Watchlist note round-trips
    assert d["watchlist"] and d["watchlist"]["note"] == "core holding"
    # Position round-trips
    assert d["position"] and d["position"]["quantity"] == 5
    # Technical pills have the three pill-fields
    assert d["technical"] and d["technical"].get("trend") in ("up", "down", "mixed")
    assert d["technical"]["momentum"] in ("up", "down", "neutral", "unknown")
    # Earnings has days_until
    assert d["earnings"] and "days_until" in d["earnings"]
    # Sector populated
    assert d["sector"] and d["sector"].get("sector")
    # Market sentiment
    assert d["market_sentiment"] and d["market_sentiment"].get("label")

    _reset_watchlist_and_paper()


def test_symbol_synth_partial_for_cn_symbol():
    """CN symbols don't have yfinance earnings/RS — those sections
    should be null but quote / sector / technical still populated."""
    _reset_watchlist_and_paper()
    _seed_watch("600519", "CN")

    d = _get(f"api/synthesis/symbol/600519?project_id={PROJECT}&fresh=1", timeout=120)
    assert d["market"] == "CN"
    # Earnings + RS + market_sentiment are US-only
    assert d["earnings"] is None
    assert d["rs"] is None
    assert d["market_sentiment"] is None
    # Quote + watchlist should still land
    assert d["quote"] and d["quote"].get("price") is not None
    assert d["watchlist"]
    _reset_watchlist_and_paper()


def test_symbol_synth_invalid_symbol_400():
    try:
        _get(f"api/synthesis/symbol/BAD$!?project_id={PROJECT}", timeout=5)
        assert False, "expected 400"
    except urllib.error.HTTPError as e:
        assert e.code == 400


def test_symbol_synth_unregistered_project_404():
    try:
        _get(f"api/synthesis/symbol/AAPL?project_id=does-not-exist", timeout=5)
        assert False, "expected 404"
    except urllib.error.HTTPError as e:
        assert e.code == 404


# ── Project synthesis ────────────────────────────────────

def test_project_synth_with_watchlist_and_position():
    _reset_watchlist_and_paper()
    _seed_watch("AAPL", "US", "core")
    _seed_watch("MSFT", "US")
    _seed_watch("600519", "CN")
    _seed_position("AAPL", qty=3)

    d = _get(f"api/synthesis/project?project_id={PROJECT}&fresh=1", timeout=120)

    # Watchlist count
    syms = {e["symbol"] for e in d["watchlist"]}
    assert syms == {"AAPL", "MSFT", "600519"}
    # Position made it in
    pos_syms = {p["symbol"] for p in d["positions"]}
    assert "AAPL" in pos_syms
    # Account exists and is a sensible number
    assert d["account"] and d["account"].get("equity") is not None
    # Upcoming earnings — AAPL or MSFT should surface
    upcoming_syms = {e["symbol"] for e in d["upcoming_earnings"]}
    assert upcoming_syms & {"AAPL", "MSFT"}, f"expected US watchlist earnings, got {upcoming_syms}"
    # Sector movers or sentiment present
    assert d["sector_movers"] is not None
    assert d["market_sentiment"] and d["market_sentiment"].get("label")

    _reset_watchlist_and_paper()


def test_project_synth_empty_state():
    _reset_watchlist_and_paper()
    d = _get(f"api/synthesis/project?project_id={PROJECT}&fresh=1", timeout=120)
    assert d["watchlist"] == []
    assert d["positions"] == []
    # Account may be None or have zeros — either is fine for empty
    # Sentiment + sectors still populate (market-wide, not project-dependent)
    assert d["market_sentiment"]
