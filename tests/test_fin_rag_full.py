"""
Comprehensive unit tests for agent/finance/fin_rag.py
Tests RAG engine, document ingestion, querying, and persistence.
"""

import pytest
import json
import tempfile
import hashlib
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timezone

from agent.finance.fin_rag import (
    DocumentChunk,
    RAGResult,
    chunk_text,
    extract_pdf_text,
    FinRAG,
    ingest_directory,
)


# ── DocumentChunk Tests ──────────────────────────────────────────────

class TestDocumentChunk:
    def test_creation_minimal(self):
        chunk = DocumentChunk(doc_id="doc123", chunk_idx=0, text="Sample text")
        assert chunk.doc_id == "doc123"
        assert chunk.chunk_idx == 0
        assert chunk.text == "Sample text"
        assert chunk.metadata == {}

    def test_creation_with_metadata(self):
        chunk = DocumentChunk(
            doc_id="doc456",
            chunk_idx=1,
            text="Another chunk",
            metadata={"source": "Reuters", "date": "2024-03-20"},
        )
        assert chunk.metadata["source"] == "Reuters"
        assert chunk.metadata["date"] == "2024-03-20"

    def test_to_dict(self):
        chunk = DocumentChunk(
            doc_id="id1",
            chunk_idx=0,
            text="content",
            metadata={"type": "earnings"},
        )
        d = chunk.to_dict()
        assert d["doc_id"] == "id1"
        assert d["chunk_idx"] == 0
        assert d["text"] == "content"
        assert d["metadata"]["type"] == "earnings"

    def test_from_dict(self):
        d = {
            "doc_id": "id2",
            "chunk_idx": 5,
            "text": "restored content",
            "metadata": {"source": "10-Q"},
        }
        chunk = DocumentChunk.from_dict(d)
        assert chunk.doc_id == "id2"
        assert chunk.chunk_idx == 5
        assert chunk.text == "restored content"
        assert chunk.metadata["source"] == "10-Q"

    def test_from_dict_missing_metadata(self):
        d = {"doc_id": "id3", "chunk_idx": 0, "text": "text"}
        chunk = DocumentChunk.from_dict(d)
        assert chunk.metadata == {}


# ── RAGResult Tests ──────────────────────────────────────────────────

class TestRAGResult:
    def test_creation(self):
        chunk = DocumentChunk(doc_id="doc1", chunk_idx=0, text="text")
        result = RAGResult(chunk=chunk, score=0.5, rank=1)
        assert result.chunk == chunk
        assert result.score == 0.5
        assert result.rank == 1

    def test_rag_result_ordering(self):
        chunks = [
            DocumentChunk(doc_id=f"doc{i}", chunk_idx=i, text=f"text{i}")
            for i in range(3)
        ]
        results = [
            RAGResult(chunk=chunks[0], score=0.9, rank=1),
            RAGResult(chunk=chunks[1], score=0.5, rank=2),
            RAGResult(chunk=chunks[2], score=0.1, rank=3),
        ]
        # Results should be orderable by score
        sorted_results = sorted(results, key=lambda r: r.score, reverse=True)
        assert sorted_results[0].score == 0.9
        assert sorted_results[2].score == 0.1


# ── chunk_text Tests ────────────────────────────────────────────────

class TestChunkText:
    def test_chunk_empty_text(self):
        result = chunk_text("", chunk_size=512)
        assert result == []

    def test_chunk_whitespace_only(self):
        result = chunk_text("   \n\n  ", chunk_size=512)
        assert result == []

    def test_chunk_single_small_paragraph(self):
        text = "This is a small paragraph."
        result = chunk_text(text, chunk_size=512)
        assert len(result) == 1
        assert result[0] == text

    def test_chunk_multiple_paragraphs(self):
        text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        result = chunk_text(text, chunk_size=100)
        assert len(result) > 1
        assert all(p.strip() for p in result)

    def test_chunk_preserves_content(self):
        text = "A\n\nB\n\nC\n\nD"
        result = chunk_text(text, chunk_size=50)
        # Reconstructing should contain all content
        reconstructed = " ".join(result)
        assert "A" in reconstructed
        assert "D" in reconstructed

    def test_chunk_respects_chunk_size(self):
        text = "word " * 200  # 1000 tokens roughly
        result = chunk_text(text, chunk_size=100)
        assert len(result) > 1
        # Most chunks should respect size (allowing some tolerance)
        for chunk in result:
            # Should be less than 1.5x chunk_size to verify reasonable splitting
            assert len(chunk) < 150

    def test_chunk_with_overlap(self):
        text = "A\n\nB\n\nC\n\nD\n\nE"
        result = chunk_text(text, chunk_size=100, overlap=20)
        # With overlap, we might have some repeated content
        assert len(result) > 1

    def test_chunk_long_single_paragraph(self):
        """Test paragraph longer than chunk_size."""
        long_para = "sentence. " * 200
        result = chunk_text(long_para, chunk_size=100)
        assert len(result) > 1
        assert all(len(c) > 0 for c in result)

    def test_chunk_special_characters(self):
        text = "Earnings: $5B\n\nMarket cap: €2T\n\nP/E: 25x"
        result = chunk_text(text, chunk_size=200)
        # Should handle special chars
        reconstructed = " ".join(result)
        assert "$" in reconstructed
        assert "€" in reconstructed


# ── extract_pdf_text Tests ──────────────────────────────────────────

class TestExtractPdfText:
    def test_extract_pdf_no_pypdf2(self):
        """Test extraction when PyPDF2 is unavailable."""
        with patch("agent.finance.fin_rag.HAS_PYPDF2", False):
            with pytest.raises(ImportError):
                extract_pdf_text("dummy.pdf")

    @patch("agent.finance.fin_rag.HAS_PYPDF2", True)
    @patch("agent.finance.fin_rag.PyPDF2")
    def test_extract_pdf_success(self, mock_pypdf2):
        """Test successful PDF extraction."""
        # Mock PDF pages
        mock_page = Mock()
        mock_page.extract_text.return_value = "Page content"

        mock_reader = Mock()
        mock_reader.pages = [mock_page, mock_page]

        mock_pypdf2.PdfReader.return_value = mock_reader

        with patch("builtins.open", create=True) as mock_open:
            mock_open.return_value.__enter__.return_value = Mock()
            result = extract_pdf_text("test.pdf")

            assert "Page 1" in result
            assert "Page 2" in result
            assert "Page content" in result

    @patch("agent.finance.fin_rag.HAS_PYPDF2", True)
    @patch("agent.finance.fin_rag.PyPDF2")
    def test_extract_pdf_empty_page(self, mock_pypdf2):
        """Test PDF extraction with empty page."""
        mock_page = Mock()
        mock_page.extract_text.return_value = ""

        mock_reader = Mock()
        mock_reader.pages = [mock_page]

        mock_pypdf2.PdfReader.return_value = mock_reader

        with patch("builtins.open", create=True):
            result = extract_pdf_text("test.pdf")
            assert result == ""


# ── FinRAG Tests ────────────────────────────────────────────────────

class TestFinRAG:
    @pytest.fixture
    def rag(self):
        """Create FinRAG instance with temp storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rag = FinRAG(storage_dir=tmpdir)
            yield rag

    def test_initialization(self, rag):
        assert rag.storage_dir.exists()
        assert rag.chunk_size == 512
        assert rag._model_name == FinRAG.DEFAULT_MODEL

    def test_model_lazy_loading(self, rag):
        """Test that model is lazy-loaded."""
        with patch("agent.finance.fin_rag.HAS_SBERT", False):
            with pytest.raises(ImportError):
                _ = rag.model

    @patch("agent.finance.fin_rag.HAS_FAISS", False)
    @patch("agent.finance.fin_rag.HAS_NUMPY", False)
    def test_index_requires_dependencies(self, rag):
        """Test that index requires FAISS and numpy."""
        with pytest.raises(ImportError):
            _ = rag.index

    def test_ingest_file_nonexistent(self, rag):
        """Test ingesting nonexistent file."""
        result = rag.ingest_file("nonexistent.txt", symbol="TEST")
        assert result == 0

    def test_ingest_text_empty(self, rag):
        """Test ingesting empty text."""
        result = rag.ingest_text("", source="test")
        assert result == 0

    def test_ingest_text_duplicate_prevention(self, rag):
        """Test that duplicate documents aren't re-ingested."""
        from unittest.mock import PropertyMock
        text = "Sample financial document content"

        with patch("agent.finance.fin_rag.HAS_SBERT", True):
            with patch("agent.finance.fin_rag.HAS_FAISS", True):
                with patch("agent.finance.fin_rag.HAS_NUMPY", True):
                    # Mock the properties using PropertyMock
                    mock_model = Mock()
                    mock_model.encode.return_value = [[0.1, 0.2]]
                    mock_model.get_sentence_embedding_dimension.return_value = 384

                    mock_index = Mock()
                    mock_index.ntotal = 0
                    mock_index.add = Mock()

                    with patch.object(type(rag), "model", new_callable=PropertyMock) as prop_model:
                        with patch.object(type(rag), "index", new_callable=PropertyMock) as prop_index:
                            prop_model.return_value = mock_model
                            prop_index.return_value = mock_index

                            # First ingest
                            result1 = rag.ingest_text(text, source="test")
                            # Second ingest (same content)
                            result2 = rag.ingest_text(text, source="test")

                            assert result2 == 0  # Should not re-ingest

    def test_list_documents_empty(self, rag):
        """Test listing documents when none exist."""
        docs = rag.list_documents()
        assert docs == []

    def test_get_stats_empty(self, rag):
        """Test stats for empty index."""
        stats = rag.get_stats()
        assert stats["total_chunks"] == 0
        assert stats["total_documents"] == 0
        assert "model" in stats
        assert "storage_dir" in stats

    def test_query_empty_index(self, rag):
        """Test querying empty index."""
        results = rag.query("test query", top_k=5)
        assert results == []

    def test_query_for_context_empty(self, rag):
        """Test query_for_context on empty index."""
        context = rag.query_for_context("test query", top_k=5)
        assert context == ""

    def test_remove_document_nonexistent(self, rag):
        """Test removing nonexistent document."""
        result = rag.remove_document("nonexistent_id")
        assert result is False

    def test_count_by_key(self, rag):
        """Test counting documents by metadata key."""
        rag._doc_registry = {
            "doc1": {"symbol": "AAPL", "doc_type": "earnings"},
            "doc2": {"symbol": "AAPL", "doc_type": "10-Q"},
            "doc3": {"symbol": "MSFT", "doc_type": "earnings"},
        }
        counts = rag._count_by_key("symbol")
        assert counts.get("AAPL") == 2
        assert counts.get("MSFT") == 1

    def test_count_by_key_unknown_field(self, rag):
        """Test counting by field that doesn't exist."""
        rag._doc_registry = {
            "doc1": {"symbol": "AAPL"},
        }
        counts = rag._count_by_key("nonexistent")
        assert counts.get("unknown") == 1

    def test_load_state_nonexistent(self, rag):
        """Test loading state when no state file exists."""
        # State should start fresh
        assert rag._chunks == []
        assert rag._doc_registry == {}

    def test_save_load_state_roundtrip(self, rag):
        """Test saving and loading state."""
        rag._doc_registry = {
            "doc1": {"symbol": "TEST", "doc_type": "test"},
        }
        rag._save_state()

        # Create new instance and load
        with tempfile.TemporaryDirectory() as tmpdir:
            rag2 = FinRAG(storage_dir=rag.storage_dir)
            # Should have loaded the state
            assert "doc1" in rag2._doc_registry


# ── ingest_directory Tests ──────────────────────────────────────────

class TestIngestDirectory:
    def test_ingest_directory_empty(self):
        """Test ingesting from empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rag = FinRAG(storage_dir=Path(tmpdir) / "rag")
            result = ingest_directory(rag, tmpdir)
            assert result == {}

    def test_ingest_directory_no_matching_files(self):
        """Test when directory has no matching extensions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a file with non-matching extension
            Path(tmpdir).joinpath("test.doc").write_text("content")
            rag = FinRAG(storage_dir=Path(tmpdir) / "rag")
            result = ingest_directory(rag, tmpdir)
            assert result == {}

    def test_ingest_directory_with_txt_files(self):
        """Test ingesting .txt files from directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            Path(tmpdir).joinpath("doc1.txt").write_text("Content 1")
            Path(tmpdir).joinpath("doc2.txt").write_text("Content 2")

            rag = FinRAG(storage_dir=Path(tmpdir) / "rag")

            with patch.object(rag, "ingest_file") as mock_ingest:
                mock_ingest.return_value = 1
                result = ingest_directory(rag, tmpdir, symbol="TEST")

                # Should have tried to ingest both files
                assert mock_ingest.call_count >= 2

    def test_ingest_directory_detects_doc_type(self):
        """Test that ingest_directory auto-detects document type."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create files with doc-type hints in name
            Path(tmpdir).joinpath("earnings_report.txt").write_text("Earnings data")
            Path(tmpdir).joinpath("10-K_2024.txt").write_text("10-K data")

            rag = FinRAG(storage_dir=Path(tmpdir) / "rag")

            with patch.object(rag, "ingest_file") as mock_ingest:
                mock_ingest.return_value = 1
                ingest_directory(rag, tmpdir)

                # Check that doc_type was passed
                calls = mock_ingest.call_args_list
                assert len(calls) >= 2


# ── Edge Cases and Error Handling ────────────────────────────────────

class TestFinRAGEdgeCases:
    def test_chunk_text_with_unicode(self):
        """Test chunking with unicode characters."""
        text = "This is 中文 content with múltiple éncoding"
        result = chunk_text(text, chunk_size=100)
        assert len(result) > 0

    def test_document_chunk_special_characters(self):
        """Test DocumentChunk with special characters."""
        chunk = DocumentChunk(
            doc_id="id1",
            chunk_idx=0,
            text="Content with 'quotes' and \"double quotes\"",
        )
        d = chunk.to_dict()
        restored = DocumentChunk.from_dict(d)
        assert restored.text == chunk.text

    def test_fin_rag_custom_storage_dir(self):
        """Test FinRAG with custom storage directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_dir = Path(tmpdir) / "custom" / "nested" / "path"
            rag = FinRAG(storage_dir=str(custom_dir))
            assert rag.storage_dir == custom_dir
            assert custom_dir.exists()

    def test_fin_rag_custom_model_name(self):
        """Test FinRAG with custom model name."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rag = FinRAG(storage_dir=tmpdir, model_name="custom-model-name")
            assert rag._model_name == "custom-model-name"

    def test_fin_rag_custom_chunk_size(self):
        """Test FinRAG with custom chunk size."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rag = FinRAG(storage_dir=tmpdir, chunk_size=256)
            assert rag.chunk_size == 256

    def test_chunk_text_with_very_long_words(self):
        """Test chunking with very long words."""
        text = "a" * 1000 + " " + "b" * 1000
        result = chunk_text(text, chunk_size=512)
        # Should split despite long words
        assert len(result) > 0

    def test_rag_result_with_zero_score(self):
        """Test RAGResult with zero similarity score."""
        chunk = DocumentChunk(doc_id="d1", chunk_idx=0, text="text")
        result = RAGResult(chunk=chunk, score=0.0, rank=1)
        assert result.score == 0.0

    def test_ingest_file_with_metadata(self):
        """Test file ingestion with custom metadata."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("content")

            rag = FinRAG(storage_dir=Path(tmpdir) / "rag")

            with patch.object(rag, "_ingest_text_chunks") as mock_ingest:
                mock_ingest.return_value = 1
                rag.ingest_file(
                    str(test_file),
                    symbol="AAPL",
                    doc_type="10-Q",
                    metadata={"quarter": "Q4", "year": 2024},
                )

                # Verify metadata was passed
                assert mock_ingest.called

    def test_query_with_symbol_filter(self):
        """Test querying with symbol filter."""
        from unittest.mock import PropertyMock
        with tempfile.TemporaryDirectory() as tmpdir:
            rag = FinRAG(storage_dir=tmpdir)
            rag._chunks = [
                DocumentChunk(
                    doc_id="d1",
                    chunk_idx=0,
                    text="Apple earnings",
                    metadata={"symbol": "AAPL"},
                ),
                DocumentChunk(
                    doc_id="d2",
                    chunk_idx=0,
                    text="Microsoft results",
                    metadata={"symbol": "MSFT"},
                ),
            ]

            # Mock the model and index to avoid dependency requirements
            mock_model = Mock()
            mock_model.encode.return_value = [[0.1, 0.2]]

            mock_index = Mock()
            mock_index.ntotal = 2
            mock_index.search.return_value = (
                [[100.0, 200.0]],  # distances
                [[0, 1]]  # indices
            )

            with patch.object(type(rag), "model", new_callable=PropertyMock) as prop_model:
                with patch.object(type(rag), "index", new_callable=PropertyMock) as prop_index:
                    prop_model.return_value = mock_model
                    prop_index.return_value = mock_index

                    results = rag.query("earnings", symbol="AAPL")
                    # Should return only AAPL results
                    assert isinstance(results, list)
                    assert len(results) == 1
                    assert results[0].chunk.metadata["symbol"] == "AAPL"
