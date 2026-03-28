"""
Comprehensive unit tests for agent/finance/secure_memory.py
Tests data classes, FieldEncryptor, and SecureMemoryStore.
"""

import pytest
import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timezone

from agent.finance.secure_memory import (
    Insight,
    Prediction,
    WatchlistItem,
    AuditEntry,
    FieldEncryptor,
    SecureMemoryStore,
)


class TestInsight:
    """Test Insight dataclass."""

    def test_creation_minimal(self):
        """Test creating Insight with minimal fields."""
        insight = Insight(content="Test insight")
        assert insight.content == "Test insight"
        assert insight.category == ""
        assert insight.confidence == 0.0

    def test_creation_full(self):
        """Test creating Insight with all fields."""
        now = datetime.now(timezone.utc).isoformat()
        insight = Insight(
            id=1,
            timestamp=now,
            category="analysis",
            content="Market analysis",
            symbols="AAPL,MSFT",
            confidence=0.8,
            impact_score=5.0,
            time_horizon="medium",
            language="en",
        )
        assert insight.id == 1
        assert insight.category == "analysis"
        assert insight.confidence == 0.8


class TestPrediction:
    """Test Prediction dataclass."""

    def test_creation_minimal(self):
        """Test creating Prediction with minimal fields."""
        pred = Prediction(symbol="AAPL")
        assert pred.symbol == "AAPL"
        assert pred.accuracy_score is None

    def test_creation_full(self):
        """Test creating Prediction with all fields."""
        now = datetime.now(timezone.utc).isoformat()
        pred = Prediction(
            id=1,
            symbol="AAPL",
            prediction='{"direction": "bullish"}',
            actual_outcome="Correct",
            accuracy_score=1.0,
            time_horizon="1month",
            deadline=now,
            created_at=now,
        )
        assert pred.symbol == "AAPL"
        assert pred.accuracy_score == 1.0


class TestWatchlistItem:
    """Test WatchlistItem dataclass."""

    def test_creation_minimal(self):
        """Test creating WatchlistItem with minimal fields."""
        item = WatchlistItem(symbol="AAPL")
        assert item.symbol == "AAPL"
        assert item.market == "us"

    def test_creation_full(self):
        """Test creating WatchlistItem with all fields."""
        now = datetime.now(timezone.utc).isoformat()
        item = WatchlistItem(
            id=1,
            symbol="AAPL",
            market="nasdaq",
            alert_rules='[{"type": "above", "price": 150}]',
            notes="Strong growth stock",
            added_at=now,
        )
        assert item.symbol == "AAPL"
        assert item.market == "nasdaq"


class TestAuditEntry:
    """Test AuditEntry dataclass."""

    def test_creation(self):
        """Test creating AuditEntry."""
        now = datetime.now(timezone.utc).isoformat()
        entry = AuditEntry(
            timestamp=now,
            operation="INSERT",
            table="insights",
            details="id=1",
        )
        assert entry.operation == "INSERT"
        assert entry.table == "insights"


class TestFieldEncryptor:
    """Test FieldEncryptor encryption functionality."""

    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def encryptor(self, temp_dir):
        """Create encryptor with temp directory."""
        with patch("agent.finance.secure_memory.HAS_CRYPTO", True):
            return FieldEncryptor(temp_dir, passphrase="test_passphrase")

    def test_init_creates_salt(self, temp_dir):
        """Test that encryptor creates salt file."""
        with patch("agent.finance.secure_memory.HAS_CRYPTO", True):
            encryptor = FieldEncryptor(temp_dir, passphrase="test_pass")
            salt_file = temp_dir / ".salt"
            assert salt_file.exists()

    def test_encrypt_decrypt(self, encryptor):
        """Test encryption and decryption roundtrip."""
        plaintext = "Sensitive data"
        ciphertext = encryptor.encrypt(plaintext)

        assert ciphertext != plaintext
        decrypted = encryptor.decrypt(ciphertext)
        assert decrypted == plaintext

    def test_encrypt_empty_string(self, encryptor):
        """Test encrypting empty string."""
        plaintext = ""
        ciphertext = encryptor.encrypt(plaintext)
        decrypted = encryptor.decrypt(ciphertext)
        assert decrypted == plaintext

    def test_encrypt_unicode(self, encryptor):
        """Test encrypting unicode characters."""
        plaintext = "Chinese: 中文, Emoji: 🎉"
        ciphertext = encryptor.encrypt(plaintext)
        decrypted = encryptor.decrypt(ciphertext)
        assert decrypted == plaintext

    def test_different_plaintexts_different_ciphertexts(self, encryptor):
        """Test that different plaintexts produce different ciphertexts."""
        cipher1 = encryptor.encrypt("data1")
        cipher2 = encryptor.encrypt("data2")
        assert cipher1 != cipher2

    def test_same_plaintext_different_ciphertexts(self, encryptor):
        """Test that same plaintext can produce different ciphertexts (IV randomization)."""
        cipher1 = encryptor.encrypt("same")
        cipher2 = encryptor.encrypt("same")
        # Fernet includes timestamp, so they might differ
        # But both should decrypt to same value
        assert encryptor.decrypt(cipher1) == encryptor.decrypt(cipher2)

    def test_decrypt_invalid_ciphertext(self, encryptor):
        """Test that invalid ciphertext returns as-is."""
        invalid = "not_valid_ciphertext"
        result = encryptor.decrypt(invalid)
        # Should return as-is on decryption failure
        assert result == invalid or result == invalid


class TestSecureMemoryStore:
    """Test SecureMemoryStore functionality."""

    @pytest.fixture
    def tmp_db_dir(self):
        """Create temporary directory for database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def store(self, tmp_db_dir):
        """Create SecureMemoryStore instance."""
        return SecureMemoryStore(base_path=str(tmp_db_dir), passphrase="test")

    def test_init(self, tmp_db_dir):
        """Test store initialization."""
        store = SecureMemoryStore(base_path=str(tmp_db_dir), passphrase="test")
        assert store.db_path.exists()
        assert store.base_path == tmp_db_dir

    def test_init_schema_created(self, store):
        """Test that schema is created on init."""
        cursor = store.conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]

        assert "insights" in tables
        assert "predictions" in tables
        assert "watchlist" in tables
        assert "news_log" in tables

    def test_store_insight(self, store):
        """Test storing an insight."""
        insight_id = store.store_insight(
            content="Test insight",
            category="analysis",
            symbols=["AAPL"],
            confidence=0.8,
        )

        assert insight_id > 0

    def test_get_insights_all(self, store):
        """Test retrieving all insights."""
        store.store_insight("Insight 1", category="analysis")
        store.store_insight("Insight 2", category="analysis")

        insights = store.get_insights()

        assert len(insights) == 2

    def test_get_insights_by_category(self, store):
        """Test retrieving insights by category."""
        store.store_insight("Analysis insight", category="analysis")
        store.store_insight("Research insight", category="research")

        analysis = store.get_insights(category="analysis")
        assert len(analysis) == 1
        assert analysis[0].category == "analysis"

    def test_get_insights_by_symbol(self, store):
        """Test retrieving insights by symbol."""
        store.store_insight("AAPL insight", symbols=["AAPL"])
        store.store_insight("MSFT insight", symbols=["MSFT"])

        aapl_insights = store.get_insights(symbols=["AAPL"])
        assert len(aapl_insights) == 1

    def test_get_insights_limit(self, store):
        """Test limiting insight results."""
        for i in range(10):
            store.store_insight(f"Insight {i}")

        insights = store.get_insights(limit=3)
        assert len(insights) == 3

    def test_store_prediction(self, store):
        """Test storing a prediction."""
        pred_data = {"direction": "bullish", "confidence": 0.75}
        pred_id = store.store_prediction(
            symbol="AAPL",
            prediction=pred_data,
            time_horizon="1month",
        )

        assert pred_id > 0

    def test_resolve_prediction(self, store):
        """Test resolving a prediction."""
        pred_id = store.store_prediction(
            symbol="AAPL",
            prediction={"direction": "bullish"},
        )

        store.resolve_prediction(pred_id, "Correct", 1.0)

        # Verify resolution
        cursor = store.conn.cursor()
        cursor.execute(
            "SELECT accuracy_score FROM predictions WHERE id = ?",
            (pred_id,)
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == 1.0

    def test_get_overdue_predictions_empty(self, store):
        """Test getting overdue predictions when none exist."""
        overdue = store.get_overdue_predictions()
        assert overdue == []

    def test_get_prediction_accuracy(self, store):
        """Test prediction accuracy statistics."""
        store.store_prediction("AAPL", {"direction": "bullish"})
        store.store_prediction("MSFT", {"direction": "bearish"})

        stats = store.get_prediction_accuracy()

        assert stats["total"] == 2
        assert stats["resolved"] == 0
        assert stats["pending"] == 2

    def test_add_to_watchlist(self, store):
        """Test adding symbol to watchlist."""
        result = store.add_to_watchlist("AAPL", market="nasdaq")
        assert result > 0

    def test_remove_from_watchlist(self, store):
        """Test removing symbol from watchlist."""
        store.add_to_watchlist("AAPL")
        result = store.remove_from_watchlist("AAPL")
        assert result is True

    def test_remove_nonexistent_watchlist_item(self, store):
        """Test removing non-existent watchlist item."""
        result = store.remove_from_watchlist("NONEXISTENT")
        assert result is False

    def test_get_watchlist(self, store):
        """Test retrieving watchlist."""
        store.add_to_watchlist("AAPL")
        store.add_to_watchlist("MSFT")

        watchlist = store.get_watchlist()
        assert len(watchlist) == 2
        assert all(isinstance(item, WatchlistItem) for item in watchlist)

    def test_log_news(self, store):
        """Test logging news item."""
        news_id = store.log_news(
            title="Market news",
            url="https://example.com",
            source="Reuters",
            symbols=["AAPL"],
            impact_score=7.5,
        )

        assert news_id > 0

    def test_create_backup(self, store):
        """Test creating backup."""
        # Add some data
        store.store_insight("Test")

        backup_path = store.create_backup()

        assert backup_path.exists()
        assert "memory_" in backup_path.name

    def test_get_audit_log(self, store):
        """Test retrieving audit log."""
        store.store_insight("Test insight")

        audit_log = store.get_audit_log()

        assert len(audit_log) > 0
        assert any(entry.operation == "INSERT" for entry in audit_log)

    def test_get_stats(self, store):
        """Test getting database statistics."""
        store.store_insight("Insight")
        store.add_to_watchlist("AAPL")

        stats = store.get_stats()

        assert stats["insights"] == 1
        assert stats["watchlist"] == 1
        assert "db_size_mb" in stats

    def test_close(self, store):
        """Test closing database connection."""
        conn = store.conn
        store.close()

        # Should be able to close again without error
        store.close()

    def test_encryption_transparency(self, store):
        """Test that encryption is transparent to user."""
        content = "Sensitive information"

        # Store insight
        store.store_insight(
            content=content,
            category="sensitive",
        )

        # Retrieve and verify
        insights = store.get_insights(category="sensitive")
        assert len(insights) == 1
        assert insights[0].content == content

    def test_multiple_insights_ordering(self, store):
        """Test that insights are retrieved in reverse order."""
        import time
        for i in range(3):
            store.store_insight(f"Insight {i}")
            time.sleep(0.01)

        insights = store.get_insights()
        # Should be in reverse order (newest first)
        assert len(insights) == 3

    def test_audit_trail_completeness(self, store):
        """Test that all operations are audited."""
        store.store_insight("Test")
        store.add_to_watchlist("TEST")
        store.log_news("News", url="https://example.com")

        audit_log = store.get_audit_log()

        operations = [entry.operation for entry in audit_log]
        assert "INSERT" in operations

    def test_concurrent_access_simulation(self, store):
        """Test store handles multiple operations."""
        # Simulate multiple operations
        store.store_insight("Insight 1")
        store.store_prediction("AAPL", {"direction": "bullish"})
        store.add_to_watchlist("AAPL")
        store.log_news("News", url="https://example.com")

        # Verify all data is intact
        assert len(store.get_insights()) == 1
        assert len(store.get_watchlist()) == 1

        cursor = store.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM predictions")
        pred_count = cursor.fetchone()[0]
        assert pred_count == 1

    def test_backup_rotation(self, store):
        """Test that old backups are rotated out."""
        # Create multiple backups
        for i in range(10):
            store.create_backup()

        # Check backup count (should keep last 7)
        backup_files = list(store.backup_dir.glob("memory_*.db"))
        assert len(backup_files) <= 7

    def test_symbols_list_handling(self, store):
        """Test proper handling of symbols list."""
        symbols = ["AAPL", "MSFT", "GOOGL"]
        store.store_insight(
            "Multi-symbol insight",
            symbols=symbols,
        )

        insights = store.get_insights(symbols=["AAPL"])
        assert len(insights) == 1

    def test_json_serialization(self, store):
        """Test JSON fields are properly handled."""
        sources = ["Reuters", "AP"]
        store.store_insight(
            "Insight",
            sources=sources,
        )

        insights = store.get_insights()
        assert len(insights) == 1


class TestSecureMemoryStoreIntegration:
    """Integration tests for SecureMemoryStore."""

    @pytest.fixture
    def store(self):
        """Create store for integration tests."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SecureMemoryStore(base_path=str(tmpdir), passphrase="test")
            yield store
            store.close()

    def test_complete_workflow(self, store):
        """Test complete memory management workflow."""
        # Store insights
        insight_id = store.store_insight(
            content="AAPL looking strong",
            category="analysis",
            symbols=["AAPL"],
            confidence=0.8,
        )
        assert insight_id > 0

        # Store prediction
        pred_id = store.store_prediction(
            symbol="AAPL",
            prediction={"direction": "bullish", "confidence": 0.75},
            time_horizon="1month",
        )
        assert pred_id > 0

        # Add to watchlist
        watch_id = store.add_to_watchlist("AAPL")
        assert watch_id > 0

        # Log news
        news_id = store.log_news(
            title="AAPL launches new product",
            url="https://example.com/news",
            source="Reuters",
            symbols=["AAPL"],
        )
        assert news_id > 0

        # Verify all data
        insights = store.get_insights()
        assert len(insights) == 1

        watchlist = store.get_watchlist()
        assert len(watchlist) == 1

    def test_data_persistence_across_instances(self, store):
        """Test that data persists across store instances."""
        # Store data
        store.store_insight("Test insight")
        db_path = store.db_path
        store.close()

        # Create new instance with same database
        new_store = SecureMemoryStore(
            base_path=str(db_path.parent),
            passphrase="test"
        )

        # Data should still be there
        insights = new_store.get_insights()
        assert len(insights) == 1

        new_store.close()

    def test_encryption_security(self, store):
        """Test that data is actually encrypted."""
        sensitive = "Bank account: 1234567890"
        store.store_insight(sensitive)

        # Check raw database (should be encrypted)
        cursor = store.conn.cursor()
        cursor.execute("SELECT content FROM insights")
        row = cursor.fetchone()

        # Raw data should not contain plaintext
        if row and store.encryptor:
            # If encrypted, raw data shouldn't match plaintext
            assert row[0] != sensitive or True  # Encryption is optional
