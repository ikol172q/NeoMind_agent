"""
Comprehensive unit tests for agent/finance/memory_bridge.py
Tests bidirectional memory sync, Markdown parsing, and security.
"""

import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timezone

from agent.finance.memory_bridge import (
    MemoryEntry,
    SyncState,
    MemoryBridge,
    SENSITIVE_FIELDS,
    FINANCE_TAG,
    OPENCLAW_MEMORY_DIR,
)


# ── MemoryEntry Tests ───────────────────────────────────────────────

class TestMemoryEntry:
    def test_creation_minimal(self):
        entry = MemoryEntry(id="entry1", content="Some memory")
        assert entry.id == "entry1"
        assert entry.content == "Some memory"
        assert entry.category == ""
        assert entry.symbols == []
        assert entry.confidence == 0.5

    def test_creation_full(self):
        entry = MemoryEntry(
            id="id1",
            content="Apple rallied after earnings beat",
            category="insight",
            symbols=["AAPL", "MSFT"],
            confidence=0.85,
            source="neomind",
            created_at="2024-03-20T10:00:00Z",
        )
        assert entry.id == "id1"
        assert "Apple" in entry.content
        assert "AAPL" in entry.symbols
        assert entry.confidence == 0.85

    def test_compute_checksum(self):
        """Test checksum computation."""
        entry = MemoryEntry(
            id="1",
            content="Market bullish",
            category="trend",
            symbols=["SPY"],
            confidence=0.7,
        )
        checksum1 = entry.compute_checksum()
        assert len(checksum1) == 12
        assert isinstance(checksum1, str)

    def test_checksum_deterministic(self):
        """Test that same content produces same checksum."""
        entry = MemoryEntry(
            id="1",
            content="Same content",
            category="test",
            symbols=["TEST"],
            confidence=0.5,
        )
        checksum1 = entry.compute_checksum()
        checksum2 = entry.compute_checksum()
        assert checksum1 == checksum2

    def test_checksum_changes_with_content(self):
        """Test that checksum changes when content changes."""
        entry1 = MemoryEntry(id="1", content="Content A", category="test")
        entry2 = MemoryEntry(id="1", content="Content B", category="test")
        assert entry1.compute_checksum() != entry2.compute_checksum()


# ── SyncState Tests ──────────────────────────────────────────────────

class TestSyncState:
    def test_creation(self):
        state = SyncState()
        assert state.last_export == 0.0
        assert state.last_import == 0.0
        assert state.exported_checksums == {}
        assert state.imported_checksums == {}
        assert state.conflict_count == 0

    def test_state_tracking(self):
        """Test state tracking of checksums."""
        state = SyncState()
        state.exported_checksums["id1"] = "abc123"
        state.imported_checksums["id2"] = "def456"

        assert state.exported_checksums["id1"] == "abc123"
        assert state.imported_checksums["id2"] == "def456"


# ── MemoryBridge Tests ──────────────────────────────────────────────

class TestMemoryBridge:
    @pytest.fixture
    def bridge(self):
        """Create bridge with temp directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            openclaw_dir = Path(tmpdir) / "openclaw" / "memory"
            bridge_dir = Path(tmpdir) / "neomind" / "bridge"

            with patch("agent.finance.memory_bridge.OPENCLAW_MEMORY_DIR", openclaw_dir):
                with patch("agent.finance.memory_bridge.NEOMIND_BRIDGE_DIR", bridge_dir):
                    bridge = MemoryBridge(memory_store=None)
                    yield bridge

    def test_initialization(self, bridge):
        """Test bridge initialization."""
        assert bridge.openclaw_dir.exists()
        assert bridge.bridge_dir.exists()
        assert bridge.state is not None

    def test_export_with_no_memory(self, bridge):
        """Test export when memory_store is None."""
        result = bridge.export_to_openclaw()
        assert result == 0

    def test_import_with_no_memory(self, bridge):
        """Test import when memory_store is None."""
        result = bridge.import_from_openclaw()
        assert result == 0

    def test_sync_basic(self, bridge):
        """Test basic sync operation."""
        result = bridge.sync()
        assert "exported" in result
        assert "imported" in result
        assert "conflicts" in result

    def test_insights_to_markdown(self, bridge):
        """Test converting insights to Markdown."""
        insights = [
            {
                "content": "Tech stocks rallying",
                "category": "market_analysis",
                "symbols": ["AAPL", "MSFT"],
                "confidence": 0.85,
                "created_at": "2024-03-20T10:00:00Z",
            },
            {
                "content": "Fed likely to cut rates",
                "category": "macro_outlook",
                "symbols": [],
                "confidence": 0.7,
                "created_at": "2024-03-20T11:00:00Z",
            },
        ]
        md = bridge._insights_to_markdown(insights)

        assert FINANCE_TAG in md
        assert "Tech stocks rallying" in md
        assert "Fed likely to cut rates" in md
        assert "AAPL" in md
        assert "85%" in md or "0.85" in md

    def test_predictions_to_markdown(self, bridge):
        """Test converting predictions to Markdown."""
        predictions = [
            {
                "symbol": "AAPL",
                "direction": "bullish",
                "confidence": 0.8,
                "resolved": False,
                "rationale": "Strong Q2 guidance",
                "created_at": "2024-03-20T10:00:00Z",
            },
            {
                "symbol": "MSFT",
                "direction": "bearish",
                "confidence": 0.6,
                "resolved": True,
                "correct": False,
                "created_at": "2024-03-19T10:00:00Z",
            },
        ]
        md = bridge._predictions_to_markdown(predictions)

        assert FINANCE_TAG in md
        assert "AAPL" in md
        assert "bullish" in md
        assert "MSFT" in md
        assert "bearish" in md
        assert "Pending" in md or "⏳" in md

    def test_watchlist_to_markdown(self, bridge):
        """Test converting watchlist to Markdown."""
        watchlist = [
            {"symbol": "AAPL", "notes": "Monitor earnings", "added_at": "2024-03-15T10:00:00Z"},
            {"symbol": "GOOGL", "notes": "AI sentiment play", "added_at": "2024-03-10T10:00:00Z"},
        ]
        md = bridge._watchlist_to_markdown(watchlist)

        assert FINANCE_TAG in md
        assert "AAPL" in md
        assert "Monitor earnings" in md
        assert "GOOGL" in md

    def test_trust_to_markdown(self, bridge):
        """Test converting source trust scores to Markdown."""
        sources = {
            "Reuters": 0.95,
            "Bloomberg": 0.92,
            "Twitter": 0.45,
            "Unknown Blog": 0.20,
        }
        md = bridge._trust_to_markdown(sources)

        assert FINANCE_TAG in md
        assert "Reuters" in md
        assert "0.95" in md
        assert "⭐⭐⭐" in md  # High trust
        assert "⚠️" in md  # Low trust

    def test_parse_openclaw_markdown(self, bridge):
        """Test parsing OpenClaw Markdown format."""
        content = """
## Market Analysis
$AAPL is strong. $MSFT also bullish.

Earnings expected strong.

## Economic Outlook
Fed rates likely to stabilize. **SPY** momentum building.
"""
        entries = bridge._parse_openclaw_markdown(content, "test_file")

        assert len(entries) >= 2
        assert any("AAPL" in e.symbols for e in entries)
        assert any("SPY" in e.symbols for e in entries)

    def test_parse_extracts_symbols(self, bridge):
        """Test symbol extraction from Markdown."""
        content = "## Analysis\nTicker $AAPL and **MSFT** mentioned. Also GOOGL."
        entries = bridge._parse_openclaw_markdown(content, "test")

        # Should extract $TICKER and **TICKER** formats
        symbols = set()
        for entry in entries:
            symbols.update(entry.symbols)

        assert "AAPL" in symbols
        assert "MSFT" in symbols

    def test_is_finance_relevant_with_tag(self, bridge):
        """Test finance relevance detection with explicit tag."""
        content = f"{FINANCE_TAG} Some content"
        assert bridge._is_finance_relevant(content) is True

    def test_is_finance_relevant_with_keywords(self, bridge):
        """Test finance relevance with financial keywords."""
        content = "Stock market earnings portfolio investment trading"
        assert bridge._is_finance_relevant(content) is True

    def test_is_finance_relevant_not_finance(self, bridge):
        """Test non-financial content."""
        content = "This is about cooking recipes and gardening tips"
        assert bridge._is_finance_relevant(content) is False

    def test_is_finance_relevant_minimal_match(self, bridge):
        """Test with minimum finance keywords."""
        content = "stock price crypto"  # 2 keywords
        assert bridge._is_finance_relevant(content) is True

    def test_contains_sensitive_api_key(self, bridge):
        """Test detection of API keys."""
        content = "api_key = sk_test_12345678"
        assert bridge._contains_sensitive(content) is True

    def test_contains_sensitive_password(self, bridge):
        """Test detection of passwords."""
        content = "password: MySecretPass123"
        assert bridge._contains_sensitive(content) is True

    def test_contains_sensitive_token(self, bridge):
        """Test detection of tokens."""
        content = "token = abc123def456"
        assert bridge._contains_sensitive(content) is True

    def test_contains_sensitive_no_detection_false_positive(self, bridge):
        """Test that word 'password' without value isn't flagged."""
        content = "The password field in the database stores hashed values"
        assert bridge._contains_sensitive(content) is False

    def test_contains_sensitive_clean_content(self, bridge):
        """Test clean content."""
        content = "Apple stock is trading at $150 with strong earnings"
        assert bridge._contains_sensitive(content) is False

    def test_load_state_fresh(self, bridge):
        """Test loading state when no state file exists."""
        assert bridge.state.last_export == 0
        assert bridge.state.conflict_count == 0

    def test_save_and_load_state_roundtrip(self, bridge):
        """Test saving and loading state."""
        bridge.state.last_export = 123.456
        bridge.state.exported_checksums["id1"] = "abc123"
        bridge._save_state()

        # Create new bridge and verify state was loaded
        bridge2 = MemoryBridge(memory_store=None)
        bridge2.openclaw_dir = bridge.openclaw_dir
        bridge2.bridge_dir = bridge.bridge_dir
        bridge2._state_path = bridge._state_path
        bridge2.state = bridge2._load_state()

        assert bridge2.state.last_export == 123.456
        assert bridge2.state.exported_checksums["id1"] == "abc123"

    def test_get_status(self, bridge):
        """Test status report."""
        status = bridge.get_status()
        assert isinstance(status, str)
        assert "Memory Bridge" in status
        assert "export" in status.lower() or "import" in status.lower()

    def test_markdown_formatting_preserves_content(self, bridge):
        """Test that markdown formatting doesn't lose content."""
        original_content = "Critical: AAPL earnings beat. Market cap $3T. Very bullish!"
        insight = {
            "content": original_content,
            "category": "earnings",
            "symbols": ["AAPL"],
            "confidence": 0.95,
            "created_at": "2024-03-20T10:00:00Z",
        }
        md = bridge._insights_to_markdown([insight])

        # Original content should be in markdown
        assert original_content in md

    def test_write_markdown_creates_file(self, bridge):
        """Test that markdown is written to file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "test.md"
            content = "# Test\nContent here"

            MemoryBridge._write_markdown(filepath, content)

            assert filepath.exists()
            assert filepath.read_text() == content


# ── Edge Cases and Error Handling ────────────────────────────────────

class TestMemoryBridgeEdgeCases:
    def test_entry_empty_symbols(self):
        """Test memory entry with no symbols."""
        entry = MemoryEntry(id="1", content="Some text")
        checksum = entry.compute_checksum()
        assert len(checksum) == 12

    def test_entry_many_symbols(self):
        """Test entry with many symbols."""
        symbols = [f"SYM{i}" for i in range(100)]
        entry = MemoryEntry(id="1", content="Text", symbols=symbols)
        checksum = entry.compute_checksum()
        assert len(checksum) == 12

    def test_markdown_special_characters(self):
        """Test markdown with special characters."""
        bridge = MemoryBridge(memory_store=None)
        insights = [
            {
                "content": "Test with \"quotes\" and 'apostrophes' & symbols!",
                "category": "test",
                "symbols": ["TEST"],
                "confidence": 0.5,
                "created_at": "2024-03-20T10:00:00Z",
            }
        ]
        md = bridge._insights_to_markdown(insights)
        assert "quotes" in md
        assert "&" in md or "and" in md

    def test_markdown_very_long_content(self):
        """Test markdown generation with very long content."""
        bridge = MemoryBridge(memory_store=None)
        long_text = "A" * 10000
        insights = [
            {
                "content": long_text,
                "category": "long",
                "symbols": [],
                "confidence": 0.5,
                "created_at": "2024-03-20T10:00:00Z",
            }
        ]
        md = bridge._insights_to_markdown(insights)
        assert len(md) > len(long_text)

    def test_parse_markdown_no_sections(self):
        """Test parsing markdown with no ## sections."""
        bridge = MemoryBridge(memory_store=None)
        content = "This is just text without sections"
        entries = bridge._parse_openclaw_markdown(content, "test")

        # Should return empty or minimal entries
        assert isinstance(entries, list)

    def test_parse_markdown_empty_sections(self):
        """Test parsing markdown with empty sections."""
        bridge = MemoryBridge(memory_store=None)
        content = "## Section 1\n\n## Section 2\n"
        entries = bridge._parse_openclaw_markdown(content, "test")

        # Should handle empty sections gracefully
        assert isinstance(entries, list)

    def test_is_finance_relevant_unicode(self):
        """Test finance detection with unicode."""
        bridge = MemoryBridge(memory_store=None)
        content = "股票 投资 市场 行情"  # Chinese financial terms
        assert bridge._is_finance_relevant(content) is True

    def test_sensitive_fields_constant(self):
        """Test SENSITIVE_FIELDS contains expected values."""
        assert "api_key" in SENSITIVE_FIELDS
        assert "token" in SENSITIVE_FIELDS
        assert "password" in SENSITIVE_FIELDS
        assert "secret" in SENSITIVE_FIELDS

    def test_sync_state_conflict_tracking(self):
        """Test conflict count tracking."""
        state = SyncState()
        state.conflict_count = 0
        state.conflict_count += 1
        state.conflict_count += 1
        assert state.conflict_count == 2

    def test_memory_entry_confidence_bounds(self):
        """Test memory entry with extreme confidence values."""
        entry1 = MemoryEntry(id="1", content="Text", confidence=0.0)
        entry2 = MemoryEntry(id="2", content="Text", confidence=1.0)

        assert entry1.confidence == 0.0
        assert entry2.confidence == 1.0

    def test_memory_entry_unicode_content(self):
        """Test entry with unicode content."""
        entry = MemoryEntry(
            id="1",
            content="中文内容 English content",
            symbols=["AAPL"],
        )
        checksum = entry.compute_checksum()
        assert len(checksum) == 12

    def test_markdown_export_subdir_constant(self):
        """Test export subdirectory constant."""
        assert MemoryBridge.EXPORT_SUBDIR == "neomind-finance"

    def test_memory_bridge_sync_interval(self):
        """Test sync interval constant."""
        assert MemoryBridge.SYNC_INTERVAL == 300

    def test_parse_markdown_with_tables(self):
        """Test parsing markdown with tables."""
        bridge = MemoryBridge(memory_store=None)
        content = """
## Portfolio
| Symbol | Allocation |
|--------|-----------|
| $AAPL | 30% |
| $MSFT | 20% |
"""
        entries = bridge._parse_openclaw_markdown(content, "portfolio")

        # Should extract symbols from table
        symbols = set()
        for entry in entries:
            symbols.update(entry.symbols)

        assert "AAPL" in symbols
        assert "MSFT" in symbols
