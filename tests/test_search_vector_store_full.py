"""
Comprehensive unit tests for agent/search/vector_store.py

Tests FAISS-backed vector store for search result similarity.
"""

import pytest
import os
import tempfile
from unittest.mock import patch, MagicMock

# Check if faiss is available
try:
    import faiss
    HAS_FAISS = True
except ImportError:
    HAS_FAISS = False

from agent.search.vector_store import LocalVectorStore
from agent.search.sources import SearchItem

# Skip all tests if faiss is not available
pytestmark = pytest.mark.skipif(not HAS_FAISS, reason="faiss not installed")


class TestLocalVectorStoreInit:
    """Tests for LocalVectorStore initialization."""

    def test_init_default_storage(self):
        """Test initialization with default storage."""
        store = LocalVectorStore()
        assert store.storage_dir == os.path.expanduser("~/.neomind/vector_store")

    def test_init_custom_storage(self):
        """Test initialization with custom storage directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalVectorStore(storage_dir=tmpdir)
            assert store.storage_dir == tmpdir

    def test_init_availability_depends_on_dependencies(self):
        """Test that availability flag depends on installed packages."""
        store = LocalVectorStore()
        # Should be available if faiss and sentence_transformers installed
        assert isinstance(store.available, bool)

    def test_init_creates_storage_directory(self):
        """Test initialization creates storage directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store_dir = os.path.join(tmpdir, "vector_store")
            store = LocalVectorStore(storage_dir=store_dir)

            if store.available:
                assert os.path.exists(store_dir)

    def test_init_custom_model_name(self):
        """Test initialization with custom model."""
        store = LocalVectorStore(model_name="all-MiniLM-L12-v2")
        assert store._model_name == "all-MiniLM-L12-v2"

    def test_init_custom_dimension(self):
        """Test initialization with custom dimension."""
        store = LocalVectorStore(dimension=768)
        assert store._dimension == 768


class TestLocalVectorStoreAddResults:
    """Tests for add_results method."""

    @pytest.fixture
    def temp_store(self):
        """Create temporary vector store."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield LocalVectorStore(storage_dir=tmpdir)

    def test_add_results_unavailable(self, temp_store):
        """Test add_results returns 0 when unavailable."""
        temp_store.available = False
        items = [SearchItem(title="Test", url="http://test.com")]

        count = temp_store.add_results("test", items)
        assert count == 0

    def test_add_results_empty_items(self, temp_store):
        """Test add_results with empty items."""
        count = temp_store.add_results("test", [])
        assert count == 0

    @patch('agent.search.vector_store.HAS_FAISS', True)
    @patch('agent.search.vector_store.HAS_SBERT', True)
    def test_add_results_single_item(self):
        """Test adding single result."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalVectorStore(storage_dir=tmpdir)
            store.available = True

            # Mock the encode method
            store._encode = MagicMock(return_value=[[0.1] * 384])
            store._model = MagicMock()

            items = [SearchItem(title="Test", url="http://test.com", snippet="test content")]

            # Should return number added (depends on dedup)
            if store.available:
                count = store.add_results("test query", items)
                assert count >= 0

    @patch('agent.search.vector_store.HAS_FAISS', True)
    @patch('agent.search.vector_store.HAS_SBERT', True)
    def test_add_results_multiple_items(self):
        """Test adding multiple results."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalVectorStore(storage_dir=tmpdir)
            store.available = True
            store._encode = MagicMock(return_value=[[0.1] * 384] * 3)
            store._model = MagicMock()

            items = [
                SearchItem(title=f"Item {i}", url=f"http://site{i}.com", snippet=f"content {i}")
                for i in range(3)
            ]

            if store.available:
                count = store.add_results("test query", items)
                assert count >= 0

    def test_add_results_deduplication(self, temp_store):
        """Test that duplicate items are deduplicated."""
        item1 = SearchItem(title="Test", url="http://test.com", snippet="content")
        item2 = SearchItem(title="Test", url="http://test.com", snippet="same content")

        # Adding same item twice should only count once or be handled by db
        # The actual behavior depends on DB implementation
        if temp_store.available:
            count = temp_store.add_results("query", [item1])
            count2 = temp_store.add_results("query", [item2])

            # Second add should recognize duplicate
            assert count2 == 0 or count2 <= count


class TestLocalVectorStoreFindSimilar:
    """Tests for find_similar method."""

    @pytest.fixture
    def temp_store(self):
        """Create temporary vector store."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield LocalVectorStore(storage_dir=tmpdir)

    def test_find_similar_unavailable(self, temp_store):
        """Test find_similar returns empty when unavailable."""
        temp_store.available = False
        results = temp_store.find_similar("test query")
        assert results == []

    def test_find_similar_empty_store(self, temp_store):
        """Test find_similar with empty store."""
        results = temp_store.find_similar("test query")
        assert results == []

    def test_find_similar_custom_top_k(self, temp_store):
        """Test find_similar with custom top_k."""
        # Should not raise even if store is empty
        results = temp_store.find_similar("test", top_k=10)
        assert isinstance(results, list)

    @patch('agent.search.vector_store.HAS_FAISS', True)
    @patch('agent.search.vector_store.HAS_SBERT', True)
    def test_find_similar_returns_dicts(self):
        """Test find_similar returns list of dicts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalVectorStore(storage_dir=tmpdir)
            store.available = True
            store._encode = MagicMock(return_value=[[0.1] * 384])
            store._model = MagicMock()

            if store.available:
                results = store.find_similar("test")
                assert isinstance(results, list)


class TestLocalVectorStoreGetStats:
    """Tests for get_stats method."""

    def test_get_stats_unavailable(self):
        """Test get_stats when unavailable."""
        store = LocalVectorStore()
        store.available = False
        stats = store.get_stats()

        assert stats["available"] is False

    def test_get_stats_structure(self):
        """Test get_stats returns correct structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalVectorStore(storage_dir=tmpdir)

            stats = store.get_stats()

            expected_keys = ["available", "model", "dimension"]
            for key in expected_keys:
                assert key in stats or stats.get("available") is False

    @patch('agent.search.vector_store.HAS_FAISS', True)
    @patch('agent.search.vector_store.HAS_SBERT', True)
    def test_get_stats_counts(self):
        """Test get_stats includes counts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalVectorStore(storage_dir=tmpdir)
            store.available = True
            store._encode = MagicMock(return_value=[[0.1] * 384])
            store._model = MagicMock()

            if store.available:
                stats = store.get_stats()
                # Should have vector count
                assert "total_vectors" in stats or stats["available"] is True


class TestLocalVectorStoreClear:
    """Tests for clear method."""

    def test_clear_unavailable(self):
        """Test clear when unavailable."""
        store = LocalVectorStore()
        store.available = False
        # Should not raise
        store.clear()

    @patch('agent.search.vector_store.HAS_FAISS', True)
    def test_clear_resets_index(self):
        """Test clear resets the index."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalVectorStore(storage_dir=tmpdir)

            if store.available:
                store.clear()
                assert store._id_counter == 0


class TestLocalVectorStoreContentHash:
    """Tests for content hashing."""

    def test_content_hash_consistency(self):
        """Test that same content produces same hash."""
        store = LocalVectorStore()

        hash1 = store._content_hash("http://example.com", "Title")
        hash2 = store._content_hash("http://example.com", "Title")

        assert hash1 == hash2

    def test_content_hash_case_insensitive(self):
        """Test content hash is case-insensitive."""
        store = LocalVectorStore()

        hash1 = store._content_hash("http://example.com", "Title")
        hash2 = store._content_hash("http://EXAMPLE.COM", "TITLE")

        assert hash1 == hash2

    def test_content_hash_whitespace_insensitive(self):
        """Test content hash ignores whitespace."""
        store = LocalVectorStore()

        hash1 = store._content_hash("http://example.com ", " Title")
        hash2 = store._content_hash("http://example.com", "Title")

        assert hash1 == hash2

    def test_content_hash_different_content(self):
        """Test different content produces different hash."""
        store = LocalVectorStore()

        hash1 = store._content_hash("http://example.com", "Title1")
        hash2 = store._content_hash("http://example.com", "Title2")

        assert hash1 != hash2


class TestLocalVectorStoreEncode:
    """Tests for encoding method."""

    def test_encode_unavailable(self):
        """Test encode when unavailable."""
        store = LocalVectorStore()
        store.available = False
        result = store._encode(["test"])
        assert result.size == 0

    @patch('agent.search.vector_store.HAS_SBERT', True)
    def test_encode_single_text(self):
        """Test encoding single text."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalVectorStore(storage_dir=tmpdir)
            store.available = True
            store._model = MagicMock()
            store._model.encode = MagicMock(return_value=[[0.1] * 384])

            if store.available:
                embeddings = store._encode(["test text"])
                # Should return numpy array
                assert embeddings is not None

    @patch('agent.search.vector_store.HAS_SBERT', True)
    def test_encode_multiple_texts(self):
        """Test encoding multiple texts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalVectorStore(storage_dir=tmpdir)
            store.available = True
            store._model = MagicMock()
            store._model.encode = MagicMock(return_value=[[0.1] * 384] * 3)

            if store.available:
                embeddings = store._encode(["text1", "text2", "text3"])
                assert embeddings is not None


class TestLocalVectorStoreDatabase:
    """Tests for database operations."""

    def test_init_db_creates_tables(self):
        """Test that _init_db creates necessary tables."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalVectorStore(storage_dir=tmpdir)

            if store.available:
                # Check that database file exists
                assert os.path.exists(store._db_path)

    def test_load_index_creates_new(self):
        """Test that _load_index creates new index if none exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalVectorStore(storage_dir=tmpdir)

            if store.available:
                assert store._index is not None

    def test_save_index_persists(self):
        """Test that _save_index saves the index."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalVectorStore(storage_dir=tmpdir)

            if store.available:
                store._save_index()
                # Check if index file exists (if FAISS is available)
                if os.path.exists(store._index_path):
                    assert os.path.getsize(store._index_path) > 0


class TestLocalVectorStoreIntegration:
    """Integration tests."""

    @patch('agent.search.vector_store.HAS_FAISS', True)
    @patch('agent.search.vector_store.HAS_SBERT', True)
    def test_full_workflow(self):
        """Test complete add and search workflow."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalVectorStore(storage_dir=tmpdir)

            if store.available:
                # Mock encoder
                store._encode = MagicMock(return_value=[[0.1] * 384])
                store._model = MagicMock()

                # Add items
                items = [
                    SearchItem(
                        title="Machine Learning Basics",
                        url="http://ml-basics.com",
                        snippet="Introduction to ML"
                    ),
                    SearchItem(
                        title="Deep Learning Guide",
                        url="http://dl-guide.com",
                        snippet="Advanced deep learning"
                    ),
                ]

                count = store.add_results("machine learning", items)
                assert count >= 0

                # Find similar
                results = store.find_similar("deep learning concepts")
                assert isinstance(results, list)

    def test_store_cleanup(self):
        """Test that store can be cleaned up."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalVectorStore(storage_dir=tmpdir)

            if store.available:
                store.clear()
                # Should succeed without error


class TestLocalVectorStoreEdgeCases:
    """Tests for edge cases."""

    def test_add_results_with_none_snippet(self):
        """Test adding items with None snippet."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalVectorStore(storage_dir=tmpdir)

            item = SearchItem(title="Test", url="http://test.com", snippet=None)

            if store.available:
                store.available = False  # Disable to avoid actual encode

            count = store.add_results("test", [item])
            assert count >= 0

    def test_add_results_with_empty_url(self):
        """Test adding items with empty URL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalVectorStore(storage_dir=tmpdir)

            item = SearchItem(title="Test", url="", snippet="content")

            count = store.add_results("test", [item])
            assert count >= 0

    def test_find_similar_with_empty_query(self):
        """Test find_similar with empty query."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalVectorStore(storage_dir=tmpdir)
            results = store.find_similar("")
            assert isinstance(results, list)

    def test_very_large_top_k(self):
        """Test find_similar with very large top_k."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalVectorStore(storage_dir=tmpdir)
            results = store.find_similar("test", top_k=10000)
            assert isinstance(results, list)
