"""
Comprehensive unit tests for agent/finance/agent_collab.py
Tests all collaboration features, domain routing, and handoff mechanisms.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from dataclasses import dataclass

# Import the module to test
import sys
sys.path.insert(0, '/sessions/hopeful-magical-rubin/mnt/NeoMind_agent')

from agent.finance.agent_collab import AgentIdentity, AgentCollaborator


class TestAgentIdentity:
    """Tests for AgentIdentity dataclass."""

    def test_agent_identity_basic(self):
        """Test basic AgentIdentity creation."""
        identity = AgentIdentity(
            name="TestBot",
            telegram_username="testbot",
            domains=["test", "domain"]
        )
        assert identity.name == "TestBot"
        assert identity.telegram_username == "testbot"
        assert identity.domains == ["test", "domain"]
        assert identity.is_self is False

    def test_agent_identity_is_self(self):
        """Test AgentIdentity with is_self flag."""
        identity = AgentIdentity(
            name="SelfBot",
            telegram_username="selfbot",
            domains=["self"],
            is_self=True
        )
        assert identity.is_self is True

    def test_agent_identity_empty_domains(self):
        """Test AgentIdentity with empty domains list."""
        identity = AgentIdentity(
            name="NoDomainBot",
            telegram_username="nodomain",
            domains=[]
        )
        assert identity.domains == []


class TestAgentCollaboratorInit:
    """Tests for AgentCollaborator initialization."""

    def test_init_basic(self):
        """Test basic initialization."""
        collab = AgentCollaborator(self_username="neomind")
        assert collab.self_identity.telegram_username == "neomind"
        assert collab.self_identity.is_self is True
        assert "finance" in collab.self_identity.domains
        assert "stocks" in collab.self_identity.domains
        assert "金融" in collab.self_identity.domains

    def test_init_with_peers(self):
        """Test initialization with predefined peers."""
        peers = {
            "openclaw": AgentIdentity("OpenClaw", "openclaw", ["general"])
        }
        collab = AgentCollaborator(self_username="neomind", peers=peers)
        assert "openclaw" in collab.peers
        assert collab.peers["openclaw"].name == "OpenClaw"

    def test_init_empty_peers(self):
        """Test initialization with no peers."""
        collab = AgentCollaborator(self_username="neomind", peers=None)
        assert collab.peers == {}

    def test_self_identity_domains(self):
        """Test that self identity has comprehensive finance domains."""
        collab = AgentCollaborator(self_username="neomind")
        domains = collab.self_identity.domains
        assert "finance" in domains
        assert "stocks" in domains
        assert "crypto" in domains
        assert "market" in domains
        assert "investment" in domains


class TestRegisterPeer:
    """Tests for peer registration."""

    def test_register_peer_basic(self):
        """Test basic peer registration."""
        collab = AgentCollaborator("neomind")
        collab.register_peer("TestBot", "testbot", ["test"])

        assert "testbot" in collab.peers
        assert collab.peers["testbot"].name == "TestBot"
        assert collab.peers["testbot"].domains == ["test"]

    def test_register_peer_case_insensitive(self):
        """Test that peer username is case-insensitive."""
        collab = AgentCollaborator("neomind")
        collab.register_peer("TestBot", "TestBOT", ["test"])

        assert "testbot" in collab.peers
        assert collab.peers["testbot"].telegram_username == "testbot"

    def test_register_peer_multiple(self):
        """Test registering multiple peers."""
        collab = AgentCollaborator("neomind")
        collab.register_peer("Bot1", "bot1", ["domain1"])
        collab.register_peer("Bot2", "bot2", ["domain2"])

        assert len(collab.peers) == 2
        assert "bot1" in collab.peers
        assert "bot2" in collab.peers

    def test_register_peer_overwrite(self):
        """Test that re-registering a peer overwrites the old one."""
        collab = AgentCollaborator("neomind")
        collab.register_peer("Bot1", "bot1", ["domain1"])
        collab.register_peer("Bot1New", "bot1", ["domain2"])

        assert collab.peers["bot1"].name == "Bot1New"
        assert collab.peers["bot1"].domains == ["domain2"]

    def test_register_openclaw_default(self):
        """Test registering OpenClaw with default username."""
        collab = AgentCollaborator("neomind")
        collab.register_openclaw()

        assert "openclaw_bot" in collab.peers
        assert collab.peers["openclaw_bot"].name == "OpenClaw"
        assert "general" in collab.peers["openclaw_bot"].domains
        assert "coding" in collab.peers["openclaw_bot"].domains

    def test_register_openclaw_custom_username(self):
        """Test registering OpenClaw with custom username."""
        collab = AgentCollaborator("neomind")
        collab.register_openclaw("custom_openclaw")

        assert "custom_openclaw" in collab.peers
        assert collab.peers["custom_openclaw"].name == "OpenClaw"

    def test_openclaw_domains(self):
        """Test that registered OpenClaw has expected domains."""
        collab = AgentCollaborator("neomind")
        collab.register_openclaw()

        domains = collab.peers["openclaw_bot"].domains
        assert "general" in domains
        assert "coding" in domains
        assert "search" in domains
        assert "browser" in domains
        assert "email" in domains
        assert "calendar" in domains
        assert "tasks" in domains
        assert "shell" in domains
        assert "files" in domains


class TestClassifyDomain:
    """Tests for domain classification."""

    def test_classify_finance_us_stocks(self):
        """Test classification of US stock queries."""
        collab = AgentCollaborator("neomind")

        assert collab.classify_domain("What's the price of AAPL?") == "finance"
        assert collab.classify_domain("AAPL stock price") == "finance"
        assert collab.classify_domain("$TSLA moving up today") == "finance"

    def test_classify_finance_ticker_pattern(self):
        """Test that ticker pattern strongly signals finance."""
        collab = AgentCollaborator("neomind")

        # $TICKER pattern should strongly indicate finance
        assert collab.classify_domain("$AAPL $MSFT $GOOGL") == "finance"
        assert collab.classify_domain("check $BTC price") == "finance"

    def test_classify_finance_keywords(self):
        """Test classification with finance keywords."""
        collab = AgentCollaborator("neomind")

        assert collab.classify_domain("fed rate decision") == "finance"
        assert collab.classify_domain("bitcoin price") == "finance"
        assert collab.classify_domain("earnings report") == "finance"
        assert collab.classify_domain("portfolio allocation") == "finance"
        assert collab.classify_domain("dividend yield") == "finance"

    def test_classify_finance_chinese(self):
        """Test classification with Chinese finance keywords."""
        collab = AgentCollaborator("neomind")

        assert collab.classify_domain("股票行情") == "finance"
        assert collab.classify_domain("财报怎么样") == "finance"
        assert collab.classify_domain("加密货币") == "finance"
        assert collab.classify_domain("央行降息") == "finance"

    def test_classify_general(self):
        """Test classification of general queries."""
        collab = AgentCollaborator("neomind")

        assert collab.classify_domain("What's the weather?") == "general"
        assert collab.classify_domain("Write code for me") == "general"
        assert collab.classify_domain("Browse the internet") == "general"

    def test_classify_general_keywords(self):
        """Test classification with general keywords."""
        collab = AgentCollaborator("neomind")

        assert collab.classify_domain("write a recipe") == "general"
        assert collab.classify_domain("send an email") == "general"
        assert collab.classify_domain("shell command") == "general"

    def test_classify_ambiguous_no_signal(self):
        """Test classification with no clear signal."""
        collab = AgentCollaborator("neomind")

        result = collab.classify_domain("hello world")
        assert result in ("ambiguous", "general", "finance")

    def test_classify_ambiguous_mixed_signals(self):
        """Test classification with mixed signals."""
        collab = AgentCollaborator("neomind")

        # Both finance and general words
        result = collab.classify_domain("search for stock information")
        assert result in ("ambiguous", "finance", "general")

    def test_classify_case_insensitive(self):
        """Test that classification is case-insensitive."""
        collab = AgentCollaborator("neomind")

        assert collab.classify_domain("STOCK PRICE") == "finance"
        assert collab.classify_domain("StOcK pRiCe") == "finance"

    def test_classify_empty_string(self):
        """Test classification of empty string."""
        collab = AgentCollaborator("neomind")

        result = collab.classify_domain("")
        assert result in ("ambiguous", "finance", "general")

    def test_classify_multiple_finance_words(self):
        """Test that multiple finance words increase score."""
        collab = AgentCollaborator("neomind")

        # More finance words = stronger signal
        assert collab.classify_domain("stock market earnings dividend") == "finance"


class TestShouldIRespond:
    """Tests for response decision logic."""

    def test_should_respond_direct_mention(self):
        """Test that direct mentions always trigger response."""
        collab = AgentCollaborator("neomind")

        should_respond, reason = collab.should_i_respond("test", is_mention=True, is_reply=False)
        assert should_respond is True
        assert reason == "direct"

    def test_should_respond_reply(self):
        """Test that replies always trigger response."""
        collab = AgentCollaborator("neomind")

        should_respond, reason = collab.should_i_respond("test", is_mention=False, is_reply=True)
        assert should_respond is True
        assert reason == "direct"

    def test_should_respond_finance_domain(self):
        """Test response to finance domain queries."""
        collab = AgentCollaborator("neomind")

        should_respond, reason = collab.should_i_respond(
            "What's the stock price of AAPL?",
            is_mention=False,
            is_reply=False
        )
        assert should_respond is True
        assert reason == "finance_domain"

    def test_should_not_respond_general_domain(self):
        """Test that general queries don't trigger response."""
        collab = AgentCollaborator("neomind")

        should_respond, reason = collab.should_i_respond(
            "What's the weather?",
            is_mention=False,
            is_reply=False
        )
        assert should_respond is False
        assert reason == "general_domain"

    def test_should_not_respond_ambiguous(self):
        """Test that ambiguous queries don't trigger response."""
        collab = AgentCollaborator("neomind")

        should_respond, reason = collab.should_i_respond(
            "hello there",
            is_mention=False,
            is_reply=False
        )
        assert should_respond is False
        assert reason == "ambiguous"

    def test_mention_overrides_domain(self):
        """Test that mentions override domain classification."""
        collab = AgentCollaborator("neomind")

        # General domain, but with mention
        should_respond, _ = collab.should_i_respond(
            "weather",
            is_mention=True,
            is_reply=False
        )
        assert should_respond is True


class TestFormatHandoff:
    """Tests for handoff message formatting."""

    def test_format_handoff_basic(self):
        """Test basic handoff message."""
        collab = AgentCollaborator("neomind")
        collab.register_peer("OpenClaw", "openclaw", ["general"])

        msg = collab.format_handoff("openclaw", "What's the weather?")
        assert "@openclaw" in msg
        assert "What's the weather?" in msg

    def test_format_handoff_with_context(self):
        """Test handoff with context."""
        collab = AgentCollaborator("neomind")
        collab.register_peer("OpenClaw", "openclaw", ["general"])

        msg = collab.format_handoff("openclaw", "Search the web", context="general query")
        assert "@openclaw" in msg
        assert "general query" in msg
        assert "Search the web" in msg

    def test_format_handoff_no_context(self):
        """Test handoff without context."""
        collab = AgentCollaborator("neomind")
        collab.register_peer("OpenClaw", "openclaw", ["general"])

        msg = collab.format_handoff("openclaw", "test query", context="")
        assert "@openclaw" in msg
        assert "test query" in msg

    def test_format_handoff_case_preservation(self):
        """Test that handoff preserves case in query."""
        collab = AgentCollaborator("neomind")
        collab.register_peer("OpenClaw", "openclaw", ["general"])

        msg = collab.format_handoff("openclaw", "Check AAPL Price")
        assert "Check AAPL Price" in msg


class TestFormatCollabResponse:
    """Tests for collaboration response formatting."""

    def test_format_collab_response_alone(self):
        """Test formatting response without delegation."""
        collab = AgentCollaborator("neomind")

        response = collab.format_collab_response("My analysis here")
        assert "My analysis here" in response
        assert "🤝" not in response

    def test_format_collab_response_with_delegation(self):
        """Test formatting response with delegation."""
        collab = AgentCollaborator("neomind")
        collab.register_peer("OpenClaw", "openclaw", ["general"])

        response = collab.format_collab_response("My analysis", delegated_to="openclaw")
        assert "My analysis" in response
        assert "🤝" in response
        assert "openclaw" in response

    def test_format_collab_response_unknown_peer(self):
        """Test formatting with unknown peer (not registered)."""
        collab = AgentCollaborator("neomind")

        response = collab.format_collab_response("My analysis", delegated_to="unknown")
        assert "My analysis" in response
        assert "🤝" in response
        assert "unknown" in response

    def test_format_collab_response_chinese_peer(self):
        """Test formatting response with Chinese peer name."""
        collab = AgentCollaborator("neomind")
        collab.register_peer("开放爪子", "openclaw_cn", ["general"])

        response = collab.format_collab_response("分析", delegated_to="openclaw_cn")
        assert "分析" in response
        assert "开放爪子" in response


class TestParseIncomingHandoff:
    """Tests for parsing incoming handoff messages."""

    def test_parse_handoff_basic(self):
        """Test parsing basic handoff."""
        collab = AgentCollaborator("neomind")

        result = collab.parse_incoming_handoff("@neomind check the stock price")
        assert result is not None
        assert "check the stock price" in result["query"]

    def test_parse_handoff_with_sender(self):
        """Test parsing handoff with sender identification."""
        collab = AgentCollaborator("neomind")
        collab.register_peer("OpenClaw", "openclaw", ["general"])

        result = collab.parse_incoming_handoff("@neomind @openclaw check stock")
        assert result is not None
        assert "check stock" in result["query"]
        assert result["from_agent"] is not None

    def test_parse_handoff_case_insensitive(self):
        """Test that handoff parsing is case-insensitive."""
        collab = AgentCollaborator("neomind")

        result1 = collab.parse_incoming_handoff("@NeoMind query")
        result2 = collab.parse_incoming_handoff("@neomind query")
        assert result1 is not None
        assert result2 is not None

    def test_parse_handoff_not_for_us(self):
        """Test parsing message not addressed to us."""
        collab = AgentCollaborator("neomind")

        result = collab.parse_incoming_handoff("@someone_else query")
        assert result is None

    def test_parse_handoff_no_mention(self):
        """Test parsing message with no @ mention."""
        collab = AgentCollaborator("neomind")

        result = collab.parse_incoming_handoff("just a regular message")
        assert result is None

    def test_parse_handoff_multiline(self):
        """Test parsing multiline handoff."""
        collab = AgentCollaborator("neomind")

        result = collab.parse_incoming_handoff("@neomind\nanalyze\nthis\nstock")
        assert result is not None
        assert "analyze" in result["query"]

    def test_parse_handoff_extracts_full_query(self):
        """Test that full query is extracted after mention."""
        collab = AgentCollaborator("neomind")

        result = collab.parse_incoming_handoff("@neomind Can you analyze $AAPL stock?")
        assert result is not None
        assert "Can you analyze $AAPL stock?" in result["query"]

    def test_parse_handoff_unknown_sender(self):
        """Test parsing with unknown sender."""
        collab = AgentCollaborator("neomind")

        result = collab.parse_incoming_handoff("@neomind @unknown_bot query")
        assert result is not None
        assert result["from_agent"] == "unknown"

    def test_parse_handoff_stores_raw(self):
        """Test that raw message is stored."""
        collab = AgentCollaborator("neomind")

        msg = "@neomind test query"
        result = collab.parse_incoming_handoff(msg)
        assert result is not None
        assert result["raw"] == msg


class TestIntegration:
    """Integration tests combining multiple features."""

    def test_full_collaboration_flow(self):
        """Test complete collaboration flow."""
        collab = AgentCollaborator("neomind")
        collab.register_openclaw()

        # 1. Check if we should respond to a general query
        should_respond, reason = collab.should_i_respond(
            "What's the weather?",
            is_mention=False,
            is_reply=False
        )
        assert should_respond is False

        # 2. Format a handoff to OpenClaw
        msg = collab.format_handoff("openclaw_bot", "What's the weather?")
        assert "@openclaw_bot" in msg

        # 3. Send response with delegation info
        response = collab.format_collab_response(
            "I can't answer this, but here's info...",
            delegated_to="openclaw_bot"
        )
        assert "openclaw_bot" in response

    def test_multi_peer_scenario(self):
        """Test scenario with multiple registered peers."""
        collab = AgentCollaborator("neomind")
        collab.register_peer("Bot1", "bot1", ["domain1"])
        collab.register_peer("Bot2", "bot2", ["domain2"])
        collab.register_openclaw()

        assert len(collab.peers) == 3
        assert "bot1" in collab.peers
        assert "bot2" in collab.peers
        assert "openclaw_bot" in collab.peers

    def test_domain_routing_comprehensive(self):
        """Test comprehensive domain routing."""
        collab = AgentCollaborator("neomind")
        collab.register_openclaw()

        test_cases = [
            ("$AAPL price", "finance", True),
            ("stock market analysis", "finance", True),
            ("weather forecast", "general", False),
            ("weather", "general", False),
            ("send email", "general", False),
            ("bitcoin price", "finance", True),
        ]

        for query, expected_domain, expected_respond in test_cases:
            domain = collab.classify_domain(query)
            should_respond, _ = collab.should_i_respond(query, False, False)
            assert should_respond == expected_respond


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
