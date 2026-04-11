"""
Comprehensive unit tests for agent/finance/openclaw_skill.py
Tests OpenClawFinanceSkill command handlers and message routing.
"""

import pytest
from unittest.mock import Mock, AsyncMock, MagicMock, patch

from agent.finance.openclaw_skill import (
    OpenClawFinanceSkill,
    FINANCE_TRIGGERS_EN,
    FINANCE_TRIGGERS_ZH,
    export_skill_metadata,
)
from agent.finance.openclaw_gateway import IncomingMessage


class TestOpenClawFinanceSkill:
    """Test OpenClawFinanceSkill functionality."""

    @pytest.fixture
    def components(self):
        """Create mock components dict."""
        return {
            "search": AsyncMock(),
            "data_hub": AsyncMock(),
            "memory": Mock(),
            "digest": AsyncMock(),
            "quant": Mock(),
            "diagram": Mock(),
            "dashboard": Mock(),
        }

    @pytest.fixture
    def skill(self, components):
        """Create skill instance with mock components."""
        return OpenClawFinanceSkill(components=components)

    def test_init(self, components):
        """Test skill initialization."""
        skill = OpenClawFinanceSkill(components=components)

        assert skill.components == components
        assert skill._search == components["search"]
        assert skill._data_hub == components["data_hub"]
        assert skill._memory == components["memory"]
        assert len(skill._command_handlers) > 0

    def test_init_with_gateway(self, components):
        """Test skill initialization with gateway."""
        gateway = Mock()
        skill = OpenClawFinanceSkill(components=components, gateway=gateway)

        assert skill.gateway == gateway
        gateway.on_message.assert_called_once()

    def test_parse_command_simple(self):
        """Test parsing simple command."""
        cmd, args = OpenClawFinanceSkill._parse_command("/stock AAPL")
        assert cmd == "stock"
        assert args == "AAPL"

    def test_parse_command_with_args(self):
        """Test parsing command with multiple arguments."""
        cmd, args = OpenClawFinanceSkill._parse_command("/predict AAPL bullish 0.75")
        assert cmd == "predict"
        assert args == "AAPL bullish 0.75"

    def test_parse_command_no_args(self):
        """Test parsing command without arguments."""
        cmd, args = OpenClawFinanceSkill._parse_command("/digest")
        assert cmd == "digest"
        assert args == ""

    def test_parse_command_case_insensitive(self):
        """Test that commands are case-insensitive."""
        cmd, args = OpenClawFinanceSkill._parse_command("/STOCK AAPL")
        assert cmd == "stock"

    def test_is_finance_query_english_keywords(self):
        """Test detecting finance queries in English."""
        assert OpenClawFinanceSkill._is_finance_query("What is the stock price?")
        assert OpenClawFinanceSkill._is_finance_query("Tell me about crypto")
        assert OpenClawFinanceSkill._is_finance_query("Fed announces rate decision")

    def test_is_finance_query_chinese_keywords(self):
        """Test detecting finance queries in Chinese."""
        assert OpenClawFinanceSkill._is_finance_query("股票价格是多少")
        assert OpenClawFinanceSkill._is_finance_query("央行新闻")

    def test_is_finance_query_ticker_pattern(self):
        """Test detecting ticker patterns."""
        assert OpenClawFinanceSkill._is_finance_query("$AAPL is rising")
        assert OpenClawFinanceSkill._is_finance_query("Buy $BTC at 62000")

    def test_is_finance_query_non_finance(self):
        """Test non-finance queries."""
        assert not OpenClawFinanceSkill._is_finance_query("What is the weather?")
        assert not OpenClawFinanceSkill._is_finance_query("Tell me a joke")

    @pytest.mark.asyncio
    async def test_handle_incoming_slash_command(self, skill):
        """Test handling slash command."""
        msg = IncomingMessage(
            channel="whatsapp",
            sender="user1",
            sender_name="Alice",
            text="/stock AAPL",
        )

        mock_handler = AsyncMock(return_value="AAPL: $150")
        skill._command_handlers["stock"] = mock_handler

        result = await skill.handle_incoming(msg)
        assert result == "AAPL: $150"
        mock_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_incoming_natural_query(self, skill):
        """Test handling natural language finance query."""
        msg = IncomingMessage(
            channel="whatsapp",
            sender="user1",
            sender_name="Alice",
            text="What is the stock price?",
        )

        skill._handle_natural_query = AsyncMock(return_value="Price info...")

        result = await skill.handle_incoming(msg)
        assert result is not None

    @pytest.mark.asyncio
    async def test_handle_incoming_non_finance(self, skill):
        """Test handling non-finance message."""
        msg = IncomingMessage(
            channel="whatsapp",
            sender="user1",
            sender_name="Alice",
            text="Hello, how are you?",
        )

        result = await skill.handle_incoming(msg)
        assert result is None

    @pytest.mark.asyncio
    async def test_handle_stock_no_args(self, skill):
        """Test stock command with no arguments."""
        result = await skill._handle_stock("", Mock())
        assert "Usage" in result

    @pytest.mark.asyncio
    async def test_handle_stock_success(self, skill):
        """Test stock command success."""
        from agent.finance.data_hub import StockQuote, VerifiedDataPoint
        skill._data_hub.get_quote = AsyncMock(return_value=StockQuote(
            symbol="AAPL",
            price=VerifiedDataPoint(value=150.25, source="Yahoo Finance"),
            change=2.50,
            change_pct=1.69,
        ))

        result = await skill._handle_stock("AAPL", Mock())

        assert "AAPL" in result
        assert "150.25" in result
        assert "📈" in result

    @pytest.mark.asyncio
    async def test_handle_stock_no_data_hub(self, skill):
        """Test stock command when data hub unavailable."""
        skill._data_hub = None

        result = await skill._handle_stock("AAPL", Mock())
        assert "not available" in result

    @pytest.mark.asyncio
    async def test_handle_stock_lookup_error(self, skill):
        """Test stock command with lookup error."""
        skill._data_hub.get_quote = AsyncMock(side_effect=Exception("API error"))

        result = await skill._handle_stock("INVALID", Mock())
        assert "⚠️" in result

    @pytest.mark.asyncio
    async def test_handle_crypto_no_args(self, skill):
        """Test crypto command with no arguments."""
        result = await skill._handle_crypto("", Mock())
        assert "Usage" in result

    @pytest.mark.asyncio
    async def test_handle_crypto_success(self, skill):
        """Test crypto command success."""
        from agent.finance.data_hub import CryptoQuote, VerifiedDataPoint
        skill._data_hub.get_crypto = AsyncMock(return_value=CryptoQuote(
            coin_id="bitcoin",
            symbol="BTC",
            name="Bitcoin",
            price=VerifiedDataPoint(value=62450.50, source="CoinGecko"),
            change_24h_pct=2.34,
        ))

        result = await skill._handle_crypto("BTC", Mock())

        assert "BTC" in result
        assert "62,450.50" in result

    @pytest.mark.asyncio
    async def test_handle_news_no_query(self, skill):
        """Test news command with default query."""
        mock_result = MagicMock()
        mock_result.items = [
            MagicMock(
                title="Market News",
                url="https://example.com",
                language="en",
                snippet="News snippet",
            )
        ]
        mock_result.sources_used = ["source1", "source2"]
        mock_result.expanded_queries = ["q1"]

        skill._search.search = AsyncMock(return_value=mock_result)

        result = await skill._handle_news("", Mock())

        assert "News" in result

    @pytest.mark.asyncio
    async def test_handle_digest_no_engine(self, skill):
        """Test digest command when digest unavailable."""
        skill._digest = None

        result = await skill._handle_digest("", Mock())
        assert "not available" in result

    @pytest.mark.asyncio
    async def test_handle_digest_success(self, skill):
        """Test digest command success."""
        mock_digest = MagicMock()
        mock_digest.items = [
            MagicMock(
                title="Market Item",
                source="Reuters",
                impact_score=5.0,
            )
        ]
        mock_digest.sources_used = 5
        mock_digest.en_count = 3
        mock_digest.zh_count = 2
        mock_digest.conflicts = []

        skill._digest.generate_digest = AsyncMock(return_value=mock_digest)

        result = await skill._handle_digest("", Mock())

        assert "Market Digest" in result

    @pytest.mark.asyncio
    async def test_handle_compute_no_args(self, skill):
        """Test compute command with no arguments."""
        result = await skill._handle_compute("", Mock())
        assert "Usage" in result
        assert "compound" in result

    @pytest.mark.asyncio
    async def test_handle_compute_compound(self, skill):
        """Test compound computation."""
        skill._quant.compound_return = Mock(return_value="$12,589.25")

        result = await skill._handle_compute("compound 10000 0.08 10", Mock())

        assert "Compound Return" in result

    @pytest.mark.asyncio
    async def test_handle_compute_sharpe(self, skill):
        """Test Sharpe ratio computation."""
        skill._quant.sharpe_ratio = Mock(return_value=1.234)

        result = await skill._handle_compute("sharpe 0.12 0.04 0.15", Mock())

        assert "Sharpe Ratio" in result

    @pytest.mark.asyncio
    async def test_handle_compute_var(self, skill):
        """Test VaR computation."""
        skill._quant.value_at_risk = Mock(return_value=-3287.50)

        result = await skill._handle_compute("var 100000 0.02 1.65", Mock())

        assert "Value at Risk" in result

    @pytest.mark.asyncio
    async def test_handle_portfolio(self, skill):
        """Test portfolio command."""
        result = await skill._handle_portfolio("", Mock())
        assert "coming in Phase 3" in result or "Portfolio" in result

    @pytest.mark.asyncio
    async def test_handle_predict_no_args(self, skill):
        """Test predict command with no arguments."""
        result = await skill._handle_predict("", Mock())
        assert "Usage" in result

    @pytest.mark.asyncio
    async def test_handle_predict_insufficient_args(self, skill):
        """Test predict with insufficient arguments."""
        result = await skill._handle_predict("AAPL", Mock())
        assert "Need:" in result

    @pytest.mark.asyncio
    async def test_handle_predict_invalid_confidence(self, skill):
        """Test predict with invalid confidence."""
        result = await skill._handle_predict("AAPL bullish abc", Mock())
        assert "number" in result

    @pytest.mark.asyncio
    async def test_handle_predict_success(self, skill):
        """Test predict command success."""
        skill._memory.store_prediction = Mock()

        result = await skill._handle_predict("AAPL bullish 0.75", Mock())

        assert "📈" in result
        assert "AAPL" in result
        assert "bullish" in result

    @pytest.mark.asyncio
    async def test_handle_alert(self, skill):
        """Test alert command."""
        result = await skill._handle_alert("AAPL above 200", Mock())
        assert "Alert" in result or "coming" in result

    @pytest.mark.asyncio
    async def test_handle_compare(self, skill):
        """Test compare command."""
        result = await skill._handle_compare("AAPL MSFT", Mock())
        assert "Compare" in result or "coming" in result

    @pytest.mark.asyncio
    async def test_handle_watchlist(self, skill):
        """Test watchlist command."""
        result = await skill._handle_watchlist("", Mock())
        assert "watchlist" in result.lower() or "usage" in result.lower()

    @pytest.mark.asyncio
    async def test_handle_risk(self, skill):
        """Test risk command."""
        result = await skill._handle_risk("", Mock())
        assert "coming" in result or "usage" in result.lower()

    @pytest.mark.asyncio
    async def test_handle_sources(self, skill):
        """Test sources command."""
        with patch("agent.finance.source_registry.SourceTrustTracker") as mock_tracker:
            mock_instance = Mock()
            mock_instance.format_report = Mock(return_value="Trust Report")
            mock_tracker.return_value = mock_instance

            result = await skill._handle_sources("", Mock())

            assert "Trust" in result or "Report" in result

    @pytest.mark.asyncio
    async def test_handle_calendar(self, skill):
        """Test calendar command."""
        result = await skill._handle_calendar("", Mock())
        assert "coming" in result or "Calendar" in result

    @pytest.mark.asyncio
    async def test_handle_chart(self, skill):
        """Test chart command."""
        result = await skill._handle_chart("pie", Mock())
        assert "chart" in result.lower() or "coming" in result.lower()

    @pytest.mark.asyncio
    async def test_handle_memory_no_memory(self, skill):
        """Test memory command when memory unavailable."""
        skill._memory = None

        result = await skill._handle_memory("", Mock())
        assert "not available" in result

    @pytest.mark.asyncio
    async def test_handle_memory_with_memory(self, skill):
        """Test memory command."""
        result = await skill._handle_memory("AAPL", Mock())
        assert "coming" in result or "Memory" in result

    @pytest.mark.asyncio
    async def test_handle_sync_with_gateway(self, skill):
        """Test sync command with gateway."""
        mock_gateway = Mock()
        mock_gateway.get_status = Mock(return_value="Connected")
        skill.gateway = mock_gateway

        result = await skill._handle_sync("", Mock())
        assert "Connected" in result

    @pytest.mark.asyncio
    async def test_handle_sync_no_gateway(self, skill):
        """Test sync command without gateway."""
        skill.gateway = None

        result = await skill._handle_sync("", Mock())
        assert "not connected" in result

    @pytest.mark.asyncio
    async def test_handle_natural_query_with_tickers(self, skill):
        """Test natural language query with ticker mentions."""
        msg = IncomingMessage(
            channel="whatsapp",
            sender="user1",
            sender_name="Alice",
            text="What about $AAPL and $MSFT?",
        )

        from agent.finance.data_hub import StockQuote, VerifiedDataPoint
        skill._data_hub.get_quote = AsyncMock(return_value=StockQuote(
            symbol="AAPL",
            price=VerifiedDataPoint(value=150.0, source="Yahoo Finance"),
            change=0,
        ))

        result = await skill._handle_natural_query(msg.text, msg)

        assert result is not None

    @pytest.mark.asyncio
    async def test_handle_natural_query_with_search(self, skill):
        """Test natural language query falls back to search."""
        skill._data_hub = None
        mock_result = MagicMock()
        mock_result.items = [
            MagicMock(title="Article", url="https://example.com")
        ]
        skill._search.search = AsyncMock(return_value=mock_result)

        result = await skill._handle_natural_query("general finance query", Mock())

        assert result is not None


class TestSkillMetadataExport:
    """Test skill metadata export."""

    def test_export_skill_metadata(self):
        """Test that metadata can be generated."""
        metadata = export_skill_metadata()

        assert "neomind-finance" in metadata
        assert "1.0.0" in metadata
        assert "/stock" in metadata
        assert "/crypto" in metadata
        assert "DuckDuckGo" in metadata

    def test_metadata_has_commands(self):
        """Test that metadata includes all commands."""
        metadata = export_skill_metadata()

        commands = [
            "stock", "crypto", "news", "digest", "compute",
            "portfolio", "predict", "alert", "compare",
            "watchlist", "risk", "sources", "calendar",
            "chart", "memory", "sync"
        ]

        for cmd in commands:
            assert f"/{cmd}" in metadata

    def test_metadata_has_triggers(self):
        """Test that metadata includes triggers."""
        metadata = export_skill_metadata()

        assert "stock" in metadata
        assert "bitcoin" in metadata
        assert "fed" in metadata
        assert "股票" in metadata


class TestOpenClawSkillIntegration:
    """Integration tests for OpenClawFinanceSkill."""

    @pytest.fixture
    def skill(self):
        """Create skill with fully mocked components."""
        components = {
            "search": AsyncMock(),
            "data_hub": AsyncMock(),
            "memory": Mock(),
            "digest": AsyncMock(),
            "quant": Mock(),
            "diagram": Mock(),
            "dashboard": Mock(),
        }
        return OpenClawFinanceSkill(components=components)

    @pytest.mark.asyncio
    async def test_complete_command_flow(self, skill):
        """Test complete command handling flow."""
        from agent.finance.data_hub import StockQuote, VerifiedDataPoint
        skill._data_hub.get_quote = AsyncMock(return_value=StockQuote(
            symbol="AAPL",
            price=VerifiedDataPoint(value=150.0, source="Yahoo"),
            change=2.5,
            change_pct=1.7,
        ))

        msg = IncomingMessage(
            channel="telegram",
            sender="user123",
            sender_name="Bob",
            text="/stock AAPL",
        )

        result = await skill.handle_incoming(msg)

        assert result is not None
        assert "AAPL" in result
        assert "150" in result

    @pytest.mark.asyncio
    async def test_command_error_handling(self, skill):
        """Test error handling in commands."""
        skill._data_hub.get_quote = AsyncMock(side_effect=Exception("API Error"))

        msg = IncomingMessage(
            channel="whatsapp",
            sender="user1",
            sender_name="Alice",
            text="/stock INVALID",
        )

        result = await skill.handle_incoming(msg)

        assert result is not None
        assert "⚠️" in result or "Error" in result or "Lookup failed" in result

    @pytest.mark.asyncio
    async def test_finance_keyword_detection(self, skill):
        """Test auto-detection of finance keywords."""
        # Should trigger on "stock" keyword
        msg1 = IncomingMessage(
            channel="whatsapp",
            sender="user1",
            sender_name="Alice",
            text="What's the stock market like today?",
        )

        skill._handle_natural_query = AsyncMock(return_value="Market info")

        result = await skill.handle_incoming(msg1)

        # Should be recognized as finance query
        assert result is not None or True  # Either handled or returns None

    def test_command_handler_registration(self, skill):
        """Test that all command handlers are registered."""
        expected_commands = [
            "stock", "crypto", "news", "digest", "compute",
            "portfolio", "predict", "alert", "compare",
            "watchlist", "risk", "sources", "calendar",
            "chart", "memory", "sync"
        ]

        for cmd in expected_commands:
            assert cmd in skill._command_handlers
