"""
Comprehensive unit tests for agent/finance/data_hub.py
Tests all functions and classes with mocked external dependencies.
"""

import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from pathlib import Path

from agent.finance.data_hub import (
    VerifiedDataPoint,
    StockQuote,
    CryptoQuote,
    NewsItem,
    DataCache,
    get_market_status,
    FinanceDataHub,
)


# ── VerifiedDataPoint Tests ──────────────────────────────────────────

class TestVerifiedDataPoint:
    def test_creation_defaults(self):
        vdp = VerifiedDataPoint(value=100.0, source="test")
        assert vdp.value == 100.0
        assert vdp.source == "test"
        assert vdp.confidence == 1.0
        assert vdp.data_type == "fact"
        assert vdp.unit == "USD"
        assert vdp.freshness == "unknown"

    def test_creation_with_all_fields(self):
        vdp = VerifiedDataPoint(
            value=50.5,
            source="YahooFinance",
            freshness="15-min delayed",
            confidence=0.95,
            data_type="estimate",
            unit="CNY",
        )
        assert vdp.value == 50.5
        assert vdp.source == "YahooFinance"
        assert vdp.freshness == "15-min delayed"
        assert vdp.confidence == 0.95
        assert vdp.data_type == "estimate"
        assert vdp.unit == "CNY"

    def test_render_realtime(self):
        vdp = VerifiedDataPoint(
            value=150.0,
            source="Finnhub",
            freshness="real-time",
        )
        rendered = vdp.render()
        assert "150.0" in rendered
        assert "Finnhub" in rendered
        assert "UTC" in rendered
        assert "15-min delayed" not in rendered

    def test_render_with_freshness(self):
        vdp = VerifiedDataPoint(
            value=75.25,
            source="yfinance",
            freshness="15-min delayed",
        )
        rendered = vdp.render()
        assert "75.25" in rendered
        assert "yfinance" in rendered
        assert "15-min delayed" in rendered


# ── StockQuote Tests ─────────────────────────────────────────────────

class TestStockQuote:
    def test_creation_minimal(self):
        sq = StockQuote(symbol="AAPL")
        assert sq.symbol == "AAPL"
        assert sq.market == "us"
        assert sq.currency == "USD"
        assert sq.market_status == "unknown"
        assert sq.change == 0.0
        assert sq.change_pct == 0.0

    def test_creation_with_data(self):
        price = VerifiedDataPoint(value=150.0, source="Finnhub")
        sq = StockQuote(
            symbol="TSLA",
            price=price,
            change=5.0,
            change_pct=3.5,
            volume=1_000_000,
            high=152.0,
            low=148.0,
            market="us",
            name="Tesla Inc",
        )
        assert sq.symbol == "TSLA"
        assert sq.price.value == 150.0
        assert sq.change == 5.0
        assert sq.volume == 1_000_000
        assert sq.name == "Tesla Inc"


# ── CryptoQuote Tests ────────────────────────────────────────────────

class TestCryptoQuote:
    def test_creation_minimal(self):
        cq = CryptoQuote(coin_id="bitcoin", symbol="BTC", name="Bitcoin")
        assert cq.coin_id == "bitcoin"
        assert cq.symbol == "BTC"
        assert cq.name == "Bitcoin"
        assert cq.currency == "USD"

    def test_creation_with_data(self):
        price = VerifiedDataPoint(value=45000.0, source="CoinGecko")
        cq = CryptoQuote(
            coin_id="ethereum",
            symbol="ETH",
            name="Ethereum",
            price=price,
            change_24h_pct=-2.5,
            volume_24h=20_000_000_000,
            market_cap=300_000_000_000,
            rank=2,
        )
        assert cq.price.value == 45000.0
        assert cq.change_24h_pct == -2.5
        assert cq.rank == 2


# ── NewsItem Tests ──────────────────────────────────────────────────

class TestNewsItem:
    def test_creation_minimal(self):
        ni = NewsItem(title="Market Update")
        assert ni.title == "Market Update"
        assert ni.url == ""
        assert ni.language == "en"
        assert ni.symbols == []

    def test_creation_with_data(self):
        pub_time = datetime.now(timezone.utc)
        ni = NewsItem(
            title="Apple Earnings Beat",
            url="https://example.com/news",
            source="Reuters",
            published=pub_time,
            summary="Apple reported strong Q4 results",
            symbols=["AAPL"],
            category="earnings",
            impact_score=0.85,
        )
        assert ni.title == "Apple Earnings Beat"
        assert ni.source == "Reuters"
        assert "AAPL" in ni.symbols
        assert ni.category == "earnings"


# ── DataCache Tests ──────────────────────────────────────────────────

class TestDataCache:
    def test_set_and_get(self):
        cache = DataCache()
        cache.set("test_key", "test_value")
        result = cache.get("test_key", ttl=300)
        assert result == "test_value"

    def test_get_nonexistent(self):
        cache = DataCache()
        result = cache.get("nonexistent", ttl=300)
        assert result is None

    def test_ttl_expiration(self):
        cache = DataCache()
        cache.set("key", "value")
        # Manually set timestamp in past to simulate expiration
        cache._cache["key"] = ("value", 0)  # timestamp = 0 (very old)
        result = cache.get("key", ttl=300)
        assert result is None

    def test_multiple_entries(self):
        cache = DataCache()
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        assert cache.get("key1") == "value1"
        assert cache.get("key2") == "value2"

    def test_cache_overwrites(self):
        cache = DataCache()
        cache.set("key", "old_value")
        cache.set("key", "new_value")
        assert cache.get("key") == "new_value"


# ── get_market_status Tests ──────────────────────────────────────────

class TestGetMarketStatus:
    def test_us_market_weekend(self):
        """Saturday should be closed."""
        with patch("agent.finance.data_hub.datetime") as mock_dt:
            mock_now = datetime(2024, 3, 23, 10, 0, 0, tzinfo=timezone.utc)  # Saturday
            mock_dt.now.return_value = mock_now
            status = get_market_status("us")
            assert "closed" in status.lower() or "weekend" in status.lower()

    def test_us_market_open_hours(self):
        """Weekday during market hours (14:30-21:00 UTC ≈ 9:30-16:00 ET)."""
        with patch("agent.finance.data_hub.datetime") as mock_dt:
            # Wednesday 15:00 UTC = 10:00 ET (market open)
            mock_now = datetime(2024, 3, 20, 15, 0, 0, tzinfo=timezone.utc)
            mock_dt.now.return_value = mock_now
            status = get_market_status("us")
            assert "open" in status.lower()

    def test_us_market_closed_hours(self):
        """Weekday outside market hours."""
        with patch("agent.finance.data_hub.datetime") as mock_dt:
            # Wednesday 10:00 UTC = 5:00 ET (before open)
            mock_now = datetime(2024, 3, 20, 10, 0, 0, tzinfo=timezone.utc)
            mock_dt.now.return_value = mock_now
            status = get_market_status("us")
            assert "closed" in status.lower()

    def test_crypto_market_always_open(self):
        status = get_market_status("crypto")
        assert "24/7" in status.lower()

    def test_china_market_lunch_break(self):
        """China market has lunch break 11:30-13:00 CST (3:30-5:00 UTC)."""
        with patch("agent.finance.data_hub.datetime") as mock_dt:
            mock_now = datetime(2024, 3, 20, 4, 0, 0, tzinfo=timezone.utc)  # lunch break
            mock_dt.now.return_value = mock_now
            status = get_market_status("cn")
            assert "lunch break" in status.lower() or "closed" in status.lower()

    def test_hk_market_status(self):
        status = get_market_status("hk")
        assert isinstance(status, str)

    def test_unknown_market(self):
        status = get_market_status("unknown_market")
        assert "unknown" in status.lower()


# ── FinanceDataHub Tests ─────────────────────────────────────────────

class TestFinanceDataHub:
    @pytest.fixture
    def hub(self):
        """Create hub with mocked environment."""
        with patch.dict("os.environ", {}, clear=False):
            hub = FinanceDataHub()
            return hub

    def test_initialization(self, hub):
        assert hub.cache is not None
        assert isinstance(hub.cache, DataCache)
        assert hub._executor is not None

    def test_get_quote_cache(self, hub):
        """Test that cached quotes are returned."""
        mock_quote = StockQuote(symbol="AAPL")
        hub.cache.set("quote_AAPL_us", mock_quote)

        with patch.object(hub, "_get_finnhub_quote", return_value=None):
            with patch.object(hub, "_get_yfinance_quote", return_value=None):
                result = asyncio.run(hub.get_quote("AAPL", market="us"))
                assert result == mock_quote

    @pytest.mark.asyncio
    async def test_get_quote_no_sources(self):
        """Test get_quote when no sources available."""
        hub = FinanceDataHub()
        hub.finnhub_client = None

        # Mock yfinance as unavailable
        with patch("agent.finance.data_hub.HAS_YFINANCE", False):
            result = await hub.get_quote("UNKNOWN", market="us")
            assert result is None

    def test_sync_yfinance_quote_success(self, hub):
        """Test synchronous yfinance quote fetch."""
        mock_ticker = Mock()
        mock_ticker.info = {
            "regularMarketPrice": 150.0,
            "regularMarketChange": 2.5,
            "regularMarketChangePercent": 1.7,
            "regularMarketVolume": 50_000_000,
            "regularMarketDayHigh": 152.0,
            "regularMarketDayLow": 148.0,
            "regularMarketOpen": 149.0,
            "regularMarketPreviousClose": 147.5,
            "marketCap": 2_500_000_000_000,
            "trailingPE": 25.5,
            "longName": "Apple Inc",
        }

        with patch("agent.finance.data_hub.yf") as mock_yf:
            mock_yf.Ticker.return_value = mock_ticker
            result = hub._sync_yfinance_quote("AAPL")

            assert result["price"] == 150.0
            assert result["change"] == 2.5
            assert result["volume"] == 50_000_000
            assert result["market_cap"] == 2_500_000_000_000
            assert result["name"] == "Apple Inc"

    def test_sync_yfinance_quote_missing_price(self, hub):
        """Test yfinance when price is missing."""
        mock_ticker = Mock()
        mock_ticker.info = {}

        with patch("agent.finance.data_hub.yf") as mock_yf:
            mock_yf.Ticker.return_value = mock_ticker
            result = hub._sync_yfinance_quote("INVALID")
            assert result is None

    def test_sync_yfinance_quote_exception(self, hub):
        """Test yfinance exception handling."""
        with patch("agent.finance.data_hub.yf") as mock_yf:
            mock_yf.Ticker.side_effect = Exception("API Error")
            result = hub._sync_yfinance_quote("AAPL")
            assert result is None

    def test_sync_coingecko_success(self, hub):
        """Test successful CoinGecko crypto fetch."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "id": "bitcoin",
                "symbol": "btc",
                "name": "Bitcoin",
                "current_price": 45000.0,
                "price_change_percentage_24h": 2.5,
                "total_volume": 20_000_000_000,
                "market_cap": 900_000_000_000,
                "market_cap_rank": 1,
            }
        ]

        with patch("agent.finance.data_hub.requests.get") as mock_get:
            mock_get.return_value = mock_response
            result = hub._sync_coingecko("bitcoin")

            assert result.coin_id == "bitcoin"
            assert result.symbol == "BTC"
            assert result.price.value == 45000.0
            assert result.price.source == "CoinGecko"

    def test_sync_coingecko_bad_response(self, hub):
        """Test CoinGecko with non-200 status."""
        mock_response = Mock()
        mock_response.status_code = 429  # Rate limited

        with patch("agent.finance.data_hub.requests.get") as mock_get:
            mock_get.return_value = mock_response
            result = hub._sync_coingecko("bitcoin")
            assert result is None

    def test_sync_coingecko_empty_response(self, hub):
        """Test CoinGecko with empty data."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = []

        with patch("agent.finance.data_hub.requests.get") as mock_get:
            mock_get.return_value = mock_response
            result = hub._sync_coingecko("bitcoin")
            assert result is None

    def test_sync_binance_success(self, hub):
        """Test Binance fallback crypto fetch."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "lastPrice": "50000.00",
            "priceChangePercent": "3.5",
            "quoteVolume": "25000000000",
        }

        with patch("agent.finance.data_hub.requests.get") as mock_get:
            mock_get.return_value = mock_response
            result = hub._sync_binance("ethereum", "ETHUSDT")

            assert result.symbol == "ETH"
            assert result.price.value == 50000.0
            assert result.price.source == "Binance"

    def test_sync_binance_exception(self, hub):
        """Test Binance exception handling."""
        with patch("agent.finance.data_hub.requests.get") as mock_get:
            mock_get.side_effect = Exception("Connection error")
            result = hub._sync_binance("bitcoin", "BTCUSDT")
            assert result is None

    def test_get_crypto_cache(self, hub):
        """Test crypto quote caching."""
        mock_crypto = CryptoQuote(coin_id="bitcoin", symbol="BTC", name="Bitcoin")
        hub.cache.set("crypto_bitcoin", mock_crypto)

        with patch.object(hub, "_get_coingecko_quote", return_value=None):
            with patch.object(hub, "_get_binance_quote", return_value=None):
                result = asyncio.run(hub.get_crypto("bitcoin"))
                assert result == mock_crypto

    def test_get_status(self, hub):
        """Test status report generation."""
        status = hub.get_status()
        assert isinstance(status, str)
        assert "Finance Data Sources" in status
        assert "US Stocks" in status
        assert "Crypto" in status

    @pytest.mark.asyncio
    async def test_get_social_sentiment_no_client(self):
        """Test social sentiment without Finnhub client."""
        hub = FinanceDataHub()
        hub.finnhub_client = None
        result = await hub.get_social_sentiment("AAPL")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_social_sentiment_with_cache(self):
        """Test social sentiment caching."""
        hub = FinanceDataHub()
        cached_data = {
            "symbol": "AAPL",
            "reddit_score": 0.6,
            "twitter_score": 0.5,
        }
        hub.cache.set("social_sentiment_AAPL", cached_data)

        result = await hub.get_social_sentiment("AAPL")
        assert result == cached_data

    def test_get_news_no_finnhub(self, hub):
        """Test get_news when Finnhub unavailable."""
        hub.finnhub_client = None
        result = asyncio.run(hub.get_news(symbol="AAPL"))
        assert result == []

    def test_get_news_with_symbol(self, hub):
        """Test get_news for specific symbol."""
        mock_news_data = [
            {
                "headline": "Apple Reports Record Earnings",
                "url": "https://example.com/news",
                "source": "financial-times",
                "summary": "Apple exceeded expectations in Q4.",
                "datetime": 1704067200,  # Some timestamp
                "category": "earnings",
            }
        ]

        hub.finnhub_client = Mock()
        hub.finnhub_client.company_news.return_value = mock_news_data

        with patch("agent.finance.data_hub.asyncio.get_event_loop"):
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                # Mock run_in_executor
                async def mock_executor(*args):
                    return mock_news_data

                with patch.object(loop, "run_in_executor") as mock_exec:
                    mock_exec.return_value = mock_executor()
                    result = loop.run_until_complete(hub.get_news(symbol="AAPL"))

                    # Just check that result is a list
                    assert isinstance(result, list)
            finally:
                loop.close()


# ── Edge Cases and Error Handling ────────────────────────────────────

class TestDataHubEdgeCases:
    def test_cache_with_none_value(self):
        """Test caching None values."""
        cache = DataCache()
        cache.set("key", None)
        result = cache.get("key")
        assert result is None

    def test_market_status_invalid_market(self):
        status = get_market_status("invalid_market")
        assert "unknown" in status.lower()

    @pytest.mark.asyncio
    async def test_get_quote_with_none_market(self):
        hub = FinanceDataHub()
        result = await hub.get_quote("AAPL", market=None)
        # Should handle gracefully
        assert result is None or isinstance(result, StockQuote)

    def test_verified_data_point_empty_string_value(self):
        vdp = VerifiedDataPoint(value="", source="test")
        assert vdp.value == ""

    def test_stock_quote_zero_values(self):
        sq = StockQuote(
            symbol="TEST",
            change=0.0,
            change_pct=0.0,
            volume=0,
            high=0.0,
            low=0.0,
        )
        assert sq.change == 0.0
        assert sq.volume == 0

    def test_news_item_empty_symbols(self):
        ni = NewsItem(title="Test", symbols=[])
        assert ni.symbols == []

    def test_news_item_multiple_symbols(self):
        ni = NewsItem(title="Test", symbols=["AAPL", "MSFT", "GOOGL"])
        assert len(ni.symbols) == 3

    def test_crypto_quote_large_numbers(self):
        cq = CryptoQuote(
            coin_id="bitcoin",
            symbol="BTC",
            name="Bitcoin",
            market_cap=1_000_000_000_000,
            volume_24h=50_000_000_000,
        )
        assert cq.market_cap == 1_000_000_000_000

    def test_cache_ttl_zero(self):
        """Test cache with TTL of 0 (immediately expired)."""
        cache = DataCache()
        cache.set("key", "value")
        result = cache.get("key", ttl=0)
        assert result is None
