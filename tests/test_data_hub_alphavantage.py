"""Phase 1 additions: Alpha Vantage fallback + key validation in data_hub."""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import Mock, patch

import pytest

from agent.finance.data_hub import FinanceDataHub, StockQuote


# ── Finnhub key validation warnings ─────────────────────────────────────

def test_init_warns_when_finnhub_key_missing(caplog, monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
    with caplog.at_level(logging.WARNING, logger="agent.finance.data_hub"):
        hub = FinanceDataHub()
    assert hub.finnhub_client is None
    # One of these two warnings must fire (package missing OR key missing)
    msgs = " ".join(r.message for r in caplog.records)
    assert ("FINNHUB_API_KEY" in msgs) or ("finnhub-python" in msgs)


def test_init_logs_when_alphavantage_key_missing(caplog, monkeypatch):
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
    with caplog.at_level(logging.INFO, logger="agent.finance.data_hub"):
        hub = FinanceDataHub()
    assert hub.alphavantage_key is None
    msgs = " ".join(r.message for r in caplog.records)
    assert "ALPHAVANTAGE_API_KEY" in msgs


def test_init_picks_up_alphavantage_key(monkeypatch):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "test-key-123")
    hub = FinanceDataHub()
    assert hub.alphavantage_key == "test-key-123"


# ── Alpha Vantage fetch (mocked) ────────────────────────────────────────

_AV_SUCCESS_PAYLOAD = {
    "Global Quote": {
        "01. symbol": "AAPL",
        "02. open": "149.80",
        "03. high": "152.10",
        "04. low": "149.50",
        "05. price": "151.25",
        "06. volume": "68234500",
        "07. latest trading day": "2026-04-11",
        "08. previous close": "150.00",
        "09. change": "1.25",
        "10. change percent": "0.8333%",
    }
}


def _mock_requests_get(payload=None, status=200, raise_on_call=False):
    mock_resp = Mock()
    mock_resp.status_code = status
    mock_resp.json.return_value = payload or {}
    if raise_on_call:
        import requests
        side_effect = requests.RequestException("boom")
        return Mock(side_effect=side_effect)
    return Mock(return_value=mock_resp)


@pytest.fixture
def hub_with_av_key(monkeypatch):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "test-key")
    return FinanceDataHub()


def test_av_fetch_parses_global_quote(hub_with_av_key):
    with patch(
        "agent.finance.data_hub.requests.get",
        _mock_requests_get(_AV_SUCCESS_PAYLOAD),
    ):
        quote = asyncio.get_event_loop().run_until_complete(
            hub_with_av_key._get_alphavantage_quote("AAPL")
        )
    assert quote is not None
    assert quote.symbol == "AAPL"
    assert quote.price.value == 151.25
    assert quote.price.source == "AlphaVantage"
    assert quote.change == 1.25
    assert quote.change_pct == pytest.approx(0.8333)
    assert quote.high == 152.10
    assert quote.low == 149.50
    assert quote.volume == 68234500


def test_av_fetch_returns_none_on_http_error(hub_with_av_key):
    with patch(
        "agent.finance.data_hub.requests.get",
        _mock_requests_get(status=500),
    ):
        quote = asyncio.get_event_loop().run_until_complete(
            hub_with_av_key._get_alphavantage_quote("AAPL")
        )
    assert quote is None


def test_av_fetch_returns_none_on_throttle_note(hub_with_av_key):
    throttled = {
        "Note": "Thank you for using Alpha Vantage! Our standard API rate limit is 5 calls per minute...",
    }
    with patch(
        "agent.finance.data_hub.requests.get",
        _mock_requests_get(throttled),
    ):
        quote = asyncio.get_event_loop().run_until_complete(
            hub_with_av_key._get_alphavantage_quote("AAPL")
        )
    assert quote is None


def test_av_fetch_returns_none_on_network_exception(hub_with_av_key):
    import requests
    with patch(
        "agent.finance.data_hub.requests.get",
        side_effect=requests.RequestException("connection refused"),
    ):
        quote = asyncio.get_event_loop().run_until_complete(
            hub_with_av_key._get_alphavantage_quote("AAPL")
        )
    assert quote is None


def test_av_fetch_returns_none_when_no_key(monkeypatch):
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
    hub = FinanceDataHub()
    # Should short-circuit without making any HTTP call
    with patch("agent.finance.data_hub.requests.get") as mock_get:
        quote = asyncio.get_event_loop().run_until_complete(
            hub._get_alphavantage_quote("AAPL")
        )
    assert quote is None
    mock_get.assert_not_called()


def test_av_fetch_returns_none_when_price_is_zero(hub_with_av_key):
    bad = {"Global Quote": {"05. price": "0.00"}}
    with patch(
        "agent.finance.data_hub.requests.get",
        _mock_requests_get(bad),
    ):
        quote = asyncio.get_event_loop().run_until_complete(
            hub_with_av_key._get_alphavantage_quote("AAPL")
        )
    assert quote is None


# ── Integration: get_quote chains Finnhub -> AV -> yfinance ─────────────

def test_get_quote_us_falls_through_to_alphavantage(monkeypatch):
    """When Finnhub returns None and AV key is set, AV is tried before yfinance."""
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "test-key")
    hub = FinanceDataHub()
    # Force Finnhub to return None
    hub.finnhub_client = Mock()  # truthy so the branch is taken

    async def fake_finnhub(sym):
        return None

    async def fake_yf(sym, market="us"):
        raise AssertionError("yfinance should not be reached when AV succeeds")

    with patch.object(hub, "_get_finnhub_quote", side_effect=fake_finnhub), \
         patch.object(hub, "_get_yfinance_quote", side_effect=fake_yf), \
         patch(
             "agent.finance.data_hub.requests.get",
             _mock_requests_get(_AV_SUCCESS_PAYLOAD),
         ):
        quote = asyncio.get_event_loop().run_until_complete(hub.get_quote("AAPL"))

    assert quote is not None
    assert quote.price.source == "AlphaVantage"


def test_get_quote_us_falls_through_to_yfinance_when_av_key_missing(monkeypatch):
    """Without AV key, chain is Finnhub -> yfinance (AV is skipped entirely)."""
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
    hub = FinanceDataHub()
    hub.finnhub_client = Mock()

    async def fake_finnhub(sym):
        return None

    yf_called = []

    async def fake_yf(sym, market="us"):
        yf_called.append(sym)
        return StockQuote(symbol=sym)

    with patch.object(hub, "_get_finnhub_quote", side_effect=fake_finnhub), \
         patch.object(hub, "_get_yfinance_quote", side_effect=fake_yf), \
         patch("agent.finance.data_hub.HAS_YFINANCE", True), \
         patch("agent.finance.data_hub.requests.get") as mock_get:
        quote = asyncio.get_event_loop().run_until_complete(hub.get_quote("AAPL"))

    assert quote is not None
    assert yf_called == ["AAPL"]
    mock_get.assert_not_called()  # AV never called because key missing
