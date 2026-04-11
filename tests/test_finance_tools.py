"""Unit tests for agent.tools.finance_tools.

Covers the pure-function behaviour (serialization, error handling,
dict shapes) without hitting live APIs. Live data-hub tests live in
the integration test suite.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.tools import finance_tools
from agent.tools.finance_tools import (
    _resolve_coin_id,
    finance_get_stock,
    finance_get_crypto,
    finance_market_overview,
    finance_news_search,
    finance_compute,
    finance_economic_calendar,
    finance_risk_calc,
    finance_portfolio_show,
    finance_watchlist_show,
)


# ── Coin ID resolver ──────────────────────────────────────────────────

def test_resolve_coin_id_uppercase_ticker():
    assert _resolve_coin_id("BTC") == "bitcoin"
    assert _resolve_coin_id("ETH") == "ethereum"
    assert _resolve_coin_id("SOL") == "solana"
    assert _resolve_coin_id("DOGE") == "dogecoin"


def test_resolve_coin_id_already_lowercase_id():
    assert _resolve_coin_id("bitcoin") == "bitcoin"
    assert _resolve_coin_id("ethereum") == "ethereum"
    assert _resolve_coin_id("avalanche-2") == "avalanche-2"


def test_resolve_coin_id_unknown_ticker_falls_back_to_lowercase():
    assert _resolve_coin_id("XYZ") == "xyz"


def test_resolve_coin_id_empty():
    assert _resolve_coin_id("") == ""
    assert _resolve_coin_id("   ") == ""


# ── finance_get_stock ────────────────────────────────────────────────

def _make_stock_quote(symbol="AAPL", price=150.25):
    """Build a minimal StockQuote-like mock."""
    mock = MagicMock()
    mock.symbol = symbol
    mock.name = "Apple Inc."
    mock.price = MagicMock()
    mock.price.value = price
    mock.price.source = "test"
    mock.price.freshness = "real-time"
    mock.price.timestamp = datetime.now(timezone.utc)
    mock.change = 2.50
    mock.change_pct = 1.69
    mock.volume = 50_000_000
    mock.high = 151.0
    mock.low = 148.0
    mock.open = 149.0
    mock.prev_close = 147.75
    mock.market_cap = 2_500_000_000_000
    mock.pe_ratio = 29.5
    mock.currency = "USD"
    mock.market = "us"
    mock.market_status = "open"
    return mock


@pytest.mark.asyncio
async def test_get_stock_returns_dict_on_success():
    hub = MagicMock()
    hub.get_quote = AsyncMock(return_value=_make_stock_quote())
    result = await finance_get_stock(hub, "AAPL")
    assert result["ok"] is True
    assert result["symbol"] == "AAPL"
    assert result["name"] == "Apple Inc."
    assert result["price"] == 150.25
    assert result["change"] == 2.50
    assert result["source"] == "test"
    assert "timestamp" in result


@pytest.mark.asyncio
async def test_get_stock_no_data_hub():
    result = await finance_get_stock(None, "AAPL")
    assert result["ok"] is False
    assert "not available" in result["error"].lower()


@pytest.mark.asyncio
async def test_get_stock_not_found():
    hub = MagicMock()
    hub.get_quote = AsyncMock(return_value=None)
    result = await finance_get_stock(hub, "NONEXIST")
    assert result["ok"] is False
    assert "no data" in result["error"].lower()
    assert result["symbol"] == "NONEXIST"


@pytest.mark.asyncio
async def test_get_stock_exception_caught():
    hub = MagicMock()
    hub.get_quote = AsyncMock(side_effect=RuntimeError("API timeout"))
    result = await finance_get_stock(hub, "AAPL")
    assert result["ok"] is False
    assert "RuntimeError" in result["error"]
    assert "API timeout" in result["error"]


# ── finance_get_crypto ───────────────────────────────────────────────

def _make_crypto_quote(coin_id="bitcoin"):
    mock = MagicMock()
    mock.coin_id = coin_id
    mock.symbol = "BTC"
    mock.name = "Bitcoin"
    mock.price = MagicMock()
    mock.price.value = 72000
    mock.price.source = "CoinGecko"
    mock.price.freshness = "real-time"
    mock.price.timestamp = datetime.now(timezone.utc)
    mock.change_24h_pct = 1.5
    mock.volume_24h = 40_000_000_000
    mock.market_cap = 1_400_000_000_000
    mock.rank = 1
    mock.currency = "USD"
    return mock


@pytest.mark.asyncio
async def test_get_crypto_by_ticker():
    hub = MagicMock()
    hub.get_crypto = AsyncMock(return_value=_make_crypto_quote())
    result = await finance_get_crypto(hub, "BTC")
    assert result["ok"] is True
    assert result["symbol"] == "BTC"
    assert result["price"] == 72000
    # Verify ticker was resolved to coin_id
    hub.get_crypto.assert_called_once_with("bitcoin")


@pytest.mark.asyncio
async def test_get_crypto_by_coin_id():
    hub = MagicMock()
    hub.get_crypto = AsyncMock(return_value=_make_crypto_quote())
    result = await finance_get_crypto(hub, "bitcoin")
    assert result["ok"] is True
    hub.get_crypto.assert_called_once_with("bitcoin")


@pytest.mark.asyncio
async def test_get_crypto_not_found():
    hub = MagicMock()
    hub.get_crypto = AsyncMock(return_value=None)
    result = await finance_get_crypto(hub, "FAKECOIN")
    assert result["ok"] is False
    assert "no data" in result["error"].lower()


# ── finance_market_overview ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_market_overview_default_basket():
    hub = MagicMock()

    async def mock_get_quote(symbol, market="us"):
        return _make_stock_quote(symbol=symbol, price=100.0)

    hub.get_quote = AsyncMock(side_effect=mock_get_quote)
    result = await finance_market_overview(hub)
    assert result["ok"] is True
    assert len(result["quotes"]) == 5  # SPY, QQQ, DIA, IWM, VIXY
    assert result["basket"] == ["SPY", "QQQ", "DIA", "IWM", "VIXY"]
    assert all(q["price"] == 100.0 for q in result["quotes"])


@pytest.mark.asyncio
async def test_market_overview_custom_basket():
    hub = MagicMock()
    hub.get_quote = AsyncMock(return_value=_make_stock_quote())
    result = await finance_market_overview(hub, symbols=["AAPL", "MSFT"])
    assert result["basket"] == ["AAPL", "MSFT"]
    assert len(result["quotes"]) == 2


@pytest.mark.asyncio
async def test_market_overview_partial_failure():
    hub = MagicMock()

    async def mock_get_quote(symbol, market="us"):
        if symbol == "BAD":
            return None
        return _make_stock_quote(symbol=symbol)

    hub.get_quote = AsyncMock(side_effect=mock_get_quote)
    result = await finance_market_overview(hub, symbols=["SPY", "BAD", "QQQ"])
    assert result["ok"] is True
    assert len(result["quotes"]) == 2
    assert len(result["errors"]) == 1
    assert "BAD" in result["errors"][0]


# ── finance_news_search ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_news_search_no_engine():
    result = await finance_news_search(None, "Apple earnings")
    assert result["ok"] is False
    assert "not available" in result["error"].lower()


@pytest.mark.asyncio
async def test_news_search_empty_query():
    engine = MagicMock()
    result = await finance_news_search(engine, "")
    assert result["ok"] is False
    assert "empty" in result["error"].lower()


@pytest.mark.asyncio
async def test_news_search_success():
    engine = MagicMock()
    mock_item = MagicMock()
    mock_item.title = "Apple beats earnings"
    mock_item.url = "https://example.com/1"
    mock_item.source = "gnews_en"
    mock_item.snippet = "Strong Q4 results"
    mock_item.language = "en"
    mock_item.published = None

    mock_result = MagicMock()
    mock_result.items = [mock_item]
    mock_result.sources_used = ["gnews_en"]

    engine.search = AsyncMock(return_value=mock_result)
    result = await finance_news_search(engine, "Apple earnings", max_results=5)
    assert result["ok"] is True
    assert len(result["items"]) == 1
    assert result["items"][0]["title"] == "Apple beats earnings"


# ── finance_compute ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_compute_cagr_correct_math():
    quant = MagicMock()
    result = await finance_compute(
        quant, formula="cagr", initial=100, final=200, years=5
    )
    assert result["ok"] is True
    assert result["formula"] == "cagr"
    # CAGR = 2^(1/5) - 1 ≈ 0.1487 → 14.87%
    assert abs(result["cagr"] - 0.1486983549970351) < 1e-6
    assert "14.87" in result["cagr_pct"]


@pytest.mark.asyncio
async def test_compute_cagr_edge_zero_years():
    quant = MagicMock()
    result = await finance_compute(
        quant, formula="cagr", initial=100, final=200, years=0
    )
    assert result["ok"] is False


@pytest.mark.asyncio
async def test_compute_unknown_formula():
    quant = MagicMock()
    result = await finance_compute(quant, formula="wiggle")
    assert result["ok"] is False
    assert "unknown" in result["error"].lower()
    assert "cagr" in result["supported"]


@pytest.mark.asyncio
async def test_compute_missing_arg():
    quant = MagicMock()
    result = await finance_compute(quant, formula="cagr", initial=100)
    # Missing final + years
    assert result["ok"] is False
    assert "missing" in result["error"].lower()


@pytest.mark.asyncio
async def test_compute_sharpe_calls_quant_engine():
    quant = MagicMock()
    quant.sharpe_ratio = MagicMock(return_value=1.25)
    result = await finance_compute(
        quant, formula="sharpe",
        portfolio_return=0.10, risk_free_rate=0.04, std_deviation=0.048,
    )
    assert result["ok"] is True
    assert result["sharpe_ratio"] == 1.25
    quant.sharpe_ratio.assert_called_once()


# ── finance_economic_calendar ────────────────────────────────────────

@pytest.mark.asyncio
async def test_economic_calendar_placeholder_structure():
    result = await finance_economic_calendar(days=7)
    assert result["ok"] is True
    assert result["days_horizon"] == 7
    assert "recurring_releases" in result
    assert len(result["recurring_releases"]) >= 5  # CPI, NFP, FOMC, PMI, GDP at minimum
    events = [r["event"] for r in result["recurring_releases"]]
    assert any("CPI" in e for e in events)
    assert any("FOMC" in e for e in events)


# ── finance_risk_calc ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_risk_calc_position_size():
    quant = MagicMock()
    quant.position_size = MagicMock(return_value=20)
    result = await finance_risk_calc(
        quant, metric="position_size",
        portfolio_value=100000, risk_per_trade=0.01,
        entry=150, stop_loss=145,
    )
    assert result["ok"] is True
    assert result["shares"] == 20
    assert result["metric"] == "position_size"


@pytest.mark.asyncio
async def test_risk_calc_unknown_metric():
    quant = MagicMock()
    result = await finance_risk_calc(quant, metric="unknown_metric")
    assert result["ok"] is False
    assert "position_size" in result.get("supported_now", [])


# ── finance_portfolio_show / watchlist_show ──────────────────────────

@pytest.mark.asyncio
async def test_portfolio_show_no_store():
    result = await finance_portfolio_show(None, 12345)
    assert result["ok"] is False


@pytest.mark.asyncio
async def test_portfolio_show_empty_holdings():
    store = MagicMock()
    store.get_portfolio = MagicMock(return_value=[])
    result = await finance_portfolio_show(store, 12345)
    assert result["ok"] is True
    assert result["holdings"] == []
    assert result["count"] == 0


@pytest.mark.asyncio
async def test_portfolio_show_with_holdings():
    store = MagicMock()
    store.get_portfolio = MagicMock(
        return_value=[{"symbol": "AAPL", "shares": 100}]
    )
    result = await finance_portfolio_show(store, 12345)
    assert result["ok"] is True
    assert result["count"] == 1


@pytest.mark.asyncio
async def test_watchlist_show_empty():
    store = MagicMock()
    store.get_watchlist = MagicMock(return_value=[])
    result = await finance_watchlist_show(store, 12345)
    assert result["ok"] is True
    assert result["count"] == 0


@pytest.mark.asyncio
async def test_watchlist_show_with_symbols():
    store = MagicMock()
    store.get_watchlist = MagicMock(return_value=["AAPL", "TSLA", "NVDA"])
    result = await finance_watchlist_show(store, 12345)
    assert result["ok"] is True
    assert result["count"] == 3
    assert "AAPL" in result["symbols"]
