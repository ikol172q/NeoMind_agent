"""Tests for agent.finance.cn_data — A-share quote via AkShare with
local SQLite TTL cache and self-throttling.

The actual AkShare calls are replaced by a fake DataFrame-like
object so tests never hit the network. Verifies:
- Quote parsing from item→value rows
- Invalid code rejected
- Cache hit skips rate limit
- Upstream error wraps cleanly as UpstreamError / HTTP 502
- API route returns the expected shape
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.finance import cn_data


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    """Redirect cache DB to a tmp file per test so we never share
    state between tests."""
    monkeypatch.setattr(cn_data, "_CACHE_DB", tmp_path / "cn_cache.sqlite3")
    # Drop rate limit for test speed
    monkeypatch.setattr(cn_data, "_RATE_LIMIT_SEC", 0.0)
    monkeypatch.setattr(cn_data, "_last_call_ts", 0.0)
    yield


class _FakeDF:
    """Mimics the pandas DataFrame returned by
    ``akshare.stock_bid_ask_em`` with .iterrows yielding the expected
    item/value pairs."""

    def __init__(self, rows):
        self._rows = rows

    def iterrows(self):
        for i, (k, v) in enumerate(self._rows):
            yield i, {"item": k, "value": v}


def _moutai_rows():
    return [
        ("sell_1", 1407.27),
        ("buy_1", 1407.24),
        ("最新", 1407.24),
        ("均价", 1407.89),
        ("涨幅", -3.8),
        ("涨跌", -55.6),
        ("总手", 96825.0),
        ("金额", 13631929446.0),
        ("换手", 0.77),
        ("最高", 1421.0),
        ("最低", 1399.87),
        ("今开", 1400.0),
        ("昨收", 1462.84),
        ("涨停", 1609.12),
        ("跌停", 1316.56),
    ]


def _fake_ak(code: str):
    assert code == "600519"
    return _FakeDF(_moutai_rows())


# ── Parsing ────────────────────────────────────────────────────────


def test_parse_moutai_full_shape():
    df = _FakeDF(_moutai_rows())
    q = cn_data._parse_bid_ask_em(df, "600519")
    assert q["symbol"] == "600519"
    assert q["market"] == "cn"
    assert q["currency"] == "CNY"
    assert q["price"] == 1407.24
    assert q["change"] == -55.6
    assert q["change_pct"] == -3.8
    assert q["volume"] == 96825 * 100
    assert q["high"] == 1421.0
    assert q["low"] == 1399.87
    assert q["open"] == 1400.0
    assert q["prev_close"] == 1462.84
    assert q["limit_up"] == 1609.12
    assert q["limit_down"] == 1316.56
    assert abs(q["turnover_rate_pct"] - 0.77) < 1e-9


def test_parse_missing_price_raises():
    df = _FakeDF([("涨幅", -3.8), ("涨跌", -55.6)])
    with pytest.raises(cn_data.UpstreamError):
        cn_data._parse_bid_ask_em(df, "600519")


def test_get_cn_quote_happy_path():
    q = cn_data.get_cn_quote("600519", _ak_call=_fake_ak)
    assert q["price"] == 1407.24
    assert q["symbol"] == "600519"


def test_get_cn_quote_invalid_code():
    for bad in ["60051", "6005199", "abc123", "", "../etc/passwd"]:
        with pytest.raises(ValueError):
            cn_data.get_cn_quote(bad, _ak_call=_fake_ak)


def test_get_cn_quote_upstream_error_wraps():
    def _broken(code):
        raise RuntimeError("fake network down")

    with pytest.raises(cn_data.UpstreamError):
        cn_data.get_cn_quote("600519", _ak_call=_broken)


# ── Cache behavior ─────────────────────────────────────────────────


def test_cache_hit_skips_upstream_call():
    calls = {"n": 0}

    def _counting(code):
        calls["n"] += 1
        return _FakeDF(_moutai_rows())

    # First call hits upstream
    cn_data.get_cn_quote("600519", _ak_call=_counting)
    assert calls["n"] == 1
    # Second call (within TTL) should use cache
    cn_data.get_cn_quote("600519", _ak_call=_counting)
    assert calls["n"] == 1


def test_cache_expiry(monkeypatch):
    monkeypatch.setattr(cn_data, "_TTL_QUOTE", 0.1)  # 100 ms
    calls = {"n": 0}

    def _counting(code):
        calls["n"] += 1
        return _FakeDF(_moutai_rows())

    cn_data.get_cn_quote("600519", _ak_call=_counting)
    assert calls["n"] == 1
    time.sleep(0.2)
    cn_data.get_cn_quote("600519", _ak_call=_counting)
    assert calls["n"] == 2


# ── Router ─────────────────────────────────────────────────────────


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(cn_data.build_cn_router(ak_call=_fake_ak))
    return TestClient(app)


def test_route_quote_returns_shape(client):
    r = client.get("/api/cn/quote/600519")
    assert r.status_code == 200
    q = r.json()
    assert q["symbol"] == "600519"
    assert q["price"] == 1407.24
    assert q["currency"] == "CNY"


def test_route_invalid_code(client):
    r = client.get("/api/cn/quote/abc")
    assert r.status_code == 400


def test_route_upstream_error_502():
    def _broken(code):
        raise RuntimeError("upstream down")

    app = FastAPI()
    app.include_router(cn_data.build_cn_router(ak_call=_broken))
    c = TestClient(app)
    r = c.get("/api/cn/quote/600519")
    assert r.status_code == 502
    assert "AkShare" in r.json()["detail"]


def test_cache_status_route(client):
    # prime the cache
    client.get("/api/cn/quote/600519")
    r = client.get("/api/cn/cache/status")
    assert r.status_code == 200
    body = r.json()
    assert body["rows"] >= 1
