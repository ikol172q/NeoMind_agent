# agent/finance/fin_rag.py
"""
Financial Document RAG — Retrieval-Augmented Generation for earnings reports,
SEC filings, annual reports, and research notes.

Stores document chunks as embeddings in a local FAISS index, enabling
semantic search over your personal financial document library.

Architecture:
    PDF/text → chunk → embed (sentence-transformers) → FAISS index
    Query → embed → FAISS search → top-K chunks → LLM context

References:
    - FinRobot Financial CoT: https://github.com/AI4Finance-Foundation/FinRobot
    - KG-RAG (SEC 10-Q multi-hop): https://github.com/VectorInstitute/kg-rag
    - FinanceRAG benchmark: https://github.com/nik2401/FinanceRAG-Investment-Research-Assistant
    - LlamaIndex SEC filings: https://docs.llamaindex.ai
    - SEC-EDGAR GraphRAG: https://github.com/neo4j-examples/sec-edgar-notebooks

Dependencies (optional — graceful degradation if missing):
    pip install faiss-cpu sentence-transformers PyPDF2
"""

import os
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any

# ── Optional imports with graceful fallback ─────────────────────────

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    np = None

try:
    import faiss
    HAS_FAISS = True
except ImportError:
    HAS_FAISS = False
    faiss = None

try:
    from sentence_transformers import SentenceTransformer
    HAS_SBERT = True
except ImportError:
    HAS_SBERT = False
    SentenceTransformer = None

try:
    import PyPDF2
    HAS_PYPDF2 = True
except ImportError:
    HAS_PYPDF2 = False
    PyPDF2 = None


# ── Data Classes ────────────────────────────────────────────────────

@dataclass
class DocumentChunk:
    """A chunk of text from a financial document."""
    doc_id: str           # hash of source file
    chunk_idx: int        # position within document
    text: str             # chunk content
    metadata: Dict = field(default_factory=dict)
    # metadata may include: source_file, page_number, section, date, symbol, doc_type

    def to_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "chunk_idx": self.chunk_idx,
            "text": self.text,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DocumentChunk":
        return cls(
            doc_id=d["doc_id"],
            chunk_idx=d["chunk_idx"],
            text=d["text"],
            metadata=d.get("metadata", {}),
        )


@dataclass
class RAGResult:
    """A single retrieval result."""
    chunk: DocumentChunk
    score: float          # similarity score (lower = more similar for L2)
    rank: int


# ── Chunking ────────────────────────────────────────────────────────

def chunk_text(
    text: str,
    chunk_size: int = 512,
    overlap: int = 64,
) -> List[str]:
    """Split text into overlapping chunks.

    Uses paragraph boundaries where possible, falls back to sentence/word.
    Optimized for financial documents (tables, bullet points, headers).
    """
    if not text.strip():
        return []

    # First pass: split by paragraphs
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    if not paragraphs:
        return []

    chunks = []

    for para in paragraphs:
        # If single paragraph is very large, split it first
        if len(para) > chunk_size:
            # Need to split this paragraph - try sentences first, then fall back to words
            import re
            sentences = re.split(r'(?<=[.!?])\s+', para)

            # If we got only one sentence (no sentence-ending punctuation), split by words
            if len(sentences) == 1:
                sentences = para.split()

            # Build chunks from sentences/words
            sub_chunk = ""
            for sent in sentences:
                sent = sent.strip() if isinstance(sent, str) else str(sent)
                if not sent:
                    continue

                # Try to add to current sub_chunk
                test_chunk = (sub_chunk + " " + sent) if sub_chunk else sent
                # Use more aggressive limit to keep chunks under 1.5x chunk_size
                limit = int(chunk_size * 1.4)
                if len(test_chunk) > limit and sub_chunk:
                    # Current chunk is full, save it and start new one
                    chunks.append(sub_chunk.strip())
                    sub_chunk = sent
                else:
                    sub_chunk = test_chunk

            # Don't forget the last sub_chunk
            if sub_chunk.strip():
                chunks.append(sub_chunk.strip())
        else:
            # Paragraph fits in chunk_size, add it as-is
            chunks.append(para)

    # Apply overlap if requested, but don't exceed size limits
    if overlap > 0 and len(chunks) > 1:
        final_chunks = []
        max_size = int(chunk_size * 1.5)  # Don't exceed this even with overlap
        for i, chunk in enumerate(chunks):
            if i == 0:
                final_chunks.append(chunk)
            else:
                # Add overlap from previous chunk, but carefully to not exceed max_size
                prev_words = chunks[i-1].split()
                overlap_count = overlap // 5 if len(prev_words) > overlap // 5 else len(prev_words)

                # Only add overlap if it doesn't exceed our max size
                if overlap_count > 0:
                    overlap_words = prev_words[-overlap_count:]
                    overlap_str = " ".join(overlap_words)
                    overlapped = overlap_str + " " + chunk
                    if len(overlapped) <= max_size:
                        final_chunks.append(overlapped)
                    else:
                        # Skip overlap if it would make chunk too large
                        final_chunks.append(chunk)
                else:
                    final_chunks.append(chunk)
        return final_chunks

    return chunks


def extract_pdf_text(filepath: str) -> str:
    """Extract text from a PDF file.

    For financial PDFs: earnings reports, 10-K, 10-Q, annual reports.
    """
    if not HAS_PYPDF2:
        raise ImportError("PyPDF2 is required for PDF extraction. pip install PyPDF2")

    text_parts = []
    with open(filepath, "rb") as f:
        reader = PyPDF2.PdfReader(f)
        for page_num, page in enumerate(reader.pages):
            page_text = page.extract_text() or ""
            if page_text.strip():
                text_parts.append(f"[Page {page_num + 1}]\n{page_text}")

    return "\n\n".join(text_parts)


# ── FinRAG Engine ───────────────────────────────────────────────────

class FinRAG:
    """Financial document RAG engine.

    Minimal, local-first design for a personal investment assistant.
    No cloud dependencies — everything runs on your machine.

    Usage:
        rag = FinRAG()
        rag.ingest_file("earnings/AAPL_Q4_2025.pdf", symbol="AAPL", doc_type="earnings")
        rag.ingest_text("The Fed raised rates by 25bp...", source="Reuters", doc_type="news")
        results = rag.query("What was Apple's revenue guidance?", top_k=5)
    """

    # Default embedding model — good balance of quality vs speed
    DEFAULT_MODEL = "all-MiniLM-L6-v2"  # 384-dim, ~80MB, fast

    def __init__(
        self,
        storage_dir: Optional[str] = None,
        model_name: Optional[str] = None,
        chunk_size: int = 512,
    ):
        self.storage_dir = Path(storage_dir or os.path.expanduser("~/.neomind/finance/rag"))
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.chunk_size = chunk_size

        # Embedding model (lazy-loaded)
        self._model_name = model_name or self.DEFAULT_MODEL
        self._model = None

        # FAISS index (lazy-loaded)
        self._index = None
        self._dimension = None

        # Chunk metadata store (maps FAISS vector ID → DocumentChunk)
        self._chunks: List[DocumentChunk] = []
        self._doc_registry: Dict[str, Dict] = {}  # doc_id → metadata

        # Try to load existing index
        self._load_state()

    @property
    def model(self):
        """Lazy-load the embedding model."""
        if self._model is None:
            if not HAS_SBERT:
                raise ImportError(
                    "sentence-transformers required for FinRAG. "
                    "pip install sentence-transformers"
                )
            try:
                self._model = SentenceTransformer(self._model_name)
                self._dimension = self._model.get_sentence_embedding_dimension()
            except TypeError:
                # SentenceTransformer might be None if import failed
                raise ImportError(
                    "sentence-transformers required for FinRAG. "
                    "pip install sentence-transformers"
                )
        return self._model

    @property
    def index(self):
        """Lazy-load or create the FAISS index."""
        if self._index is None:
            if not HAS_FAISS or not HAS_NUMPY:
                raise ImportError(
                    "faiss-cpu and numpy required for FinRAG. "
                    "pip install faiss-cpu numpy"
                )
            dim = self._dimension or 384  # default for all-MiniLM-L6-v2
            self._index = faiss.IndexFlatL2(dim)
        return self._index

    # ── Ingestion ───────────────────────────────────────────────────

    def ingest_file(
        self,
        filepath: str,
        symbol: Optional[str] = None,
        doc_type: str = "unknown",
        metadata: Optional[Dict] = None,
    ) -> int:
        """Ingest a document file (PDF or text) into the RAG index.

        Args:
            filepath: Path to PDF or text file.
            symbol: Stock symbol this document relates to (e.g. "AAPL").
            doc_type: "earnings", "10-K", "10-Q", "annual", "research", "news".
            metadata: Additional metadata dict.

        Returns:
            Number of chunks indexed.
        """
        filepath = str(filepath)

        # Check if file exists
        if not os.path.exists(filepath):
            return 0

        # Generate doc_id from file hash
        with open(filepath, "rb") as f:
            doc_id = hashlib.sha256(f.read()).hexdigest()[:16]

        # Skip if already indexed
        if doc_id in self._doc_registry:
            return 0

        # Extract text
        if filepath.lower().endswith(".pdf"):
            text = extract_pdf_text(filepath)
        else:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()

        if not text.strip():
            return 0

        base_meta = {
            "source_file": os.path.basename(filepath),
            "symbol": symbol,
            "doc_type": doc_type,
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            **(metadata or {}),
        }

        return self._ingest_text_chunks(doc_id, text, base_meta)

    def ingest_text(
        self,
        text: str,
        source: str = "manual",
        symbol: Optional[str] = None,
        doc_type: str = "note",
        metadata: Optional[Dict] = None,
    ) -> int:
        """Ingest raw text into the RAG index.

        Useful for earnings call transcripts, research notes, news articles.

        Returns:
            Number of chunks indexed.
        """
        doc_id = hashlib.sha256(text.encode()).hexdigest()[:16]

        if doc_id in self._doc_registry:
            return 0

        base_meta = {
            "source": source,
            "symbol": symbol,
            "doc_type": doc_type,
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            **(metadata or {}),
        }

        return self._ingest_text_chunks(doc_id, text, base_meta)

    def _ingest_text_chunks(
        self,
        doc_id: str,
        text: str,
        base_meta: Dict,
    ) -> int:
        """Internal: chunk text, embed, add to FAISS index."""
        chunks_text = chunk_text(text, chunk_size=self.chunk_size)
        if not chunks_text:
            return 0

        # Create DocumentChunks
        new_chunks = []
        for i, ct in enumerate(chunks_text):
            chunk = DocumentChunk(
                doc_id=doc_id,
                chunk_idx=i,
                text=ct,
                metadata={**base_meta, "chunk_of": len(chunks_text)},
            )
            new_chunks.append(chunk)

        # Embed all chunks
        texts = [c.text for c in new_chunks]
        embeddings = self.model.encode(texts, show_progress_bar=False)
        embeddings = np.array(embeddings, dtype=np.float32)

        # Add to FAISS
        self.index.add(embeddings)

        # Register chunks (FAISS ID = position in self._chunks list)
        self._chunks.extend(new_chunks)

        # Register document
        self._doc_registry[doc_id] = {
            "num_chunks": len(new_chunks),
            **base_meta,
        }

        # Persist
        self._save_state()

        return len(new_chunks)

    # ── Query ───────────────────────────────────────────────────────

    def query(
        self,
        question: str,
        top_k: int = 5,
        symbol: Optional[str] = None,
        doc_type: Optional[str] = None,
    ) -> List[RAGResult]:
        """Semantic search over indexed financial documents.

        Args:
            question: Natural language query.
            top_k: Number of results to return.
            symbol: Filter to a specific stock symbol.
            doc_type: Filter to a specific document type.

        Returns:
            List of RAGResult sorted by relevance.
        """
        if not self._chunks or self.index.ntotal == 0:
            return []

        # Embed query
        query_vec = self.model.encode([question], show_progress_bar=False)
        query_vec = np.array(query_vec, dtype=np.float32)

        # Search (fetch more than top_k to allow for filtering)
        search_k = min(top_k * 3, self.index.ntotal)
        distances, indices = self.index.search(query_vec, search_k)

        results = []
        for rank, (dist, idx) in enumerate(zip(distances[0], indices[0])):
            if idx < 0 or idx >= len(self._chunks):
                continue

            chunk = self._chunks[idx]

            # Apply filters
            if symbol and chunk.metadata.get("symbol") != symbol:
                continue
            if doc_type and chunk.metadata.get("doc_type") != doc_type:
                continue

            results.append(RAGResult(
                chunk=chunk,
                score=float(dist),
                rank=len(results) + 1,
            ))

            if len(results) >= top_k:
                break

        return results

    def query_for_context(
        self,
        question: str,
        top_k: int = 5,
        max_tokens: int = 2000,
        symbol: Optional[str] = None,
    ) -> str:
        """Query and format results as context for LLM injection.

        Returns a formatted string ready to be injected into a prompt,
        with source attribution for each chunk.
        """
        results = self.query(question, top_k=top_k, symbol=symbol)
        if not results:
            return ""

        sections = []
        total_len = 0
        for r in results:
            meta = r.chunk.metadata
            header = f"[{meta.get('doc_type', '?')}] {meta.get('source_file', meta.get('source', '?'))}"
            if meta.get("symbol"):
                header += f" ({meta['symbol']})"
            section = f"--- {header} ---\n{r.chunk.text}"

            if total_len + len(section) > max_tokens * 4:  # rough char→token
                break

            sections.append(section)
            total_len += len(section)

        return "\n\n".join(sections)

    # ── Management ──────────────────────────────────────────────────

    def list_documents(self) -> List[Dict]:
        """List all indexed documents."""
        return [
            {"doc_id": did, **meta}
            for did, meta in self._doc_registry.items()
        ]

    def get_stats(self) -> Dict:
        """Get index statistics."""
        return {
            "total_chunks": len(self._chunks),
            "total_documents": len(self._doc_registry),
            "index_vectors": self._index.ntotal if self._index else 0,
            "storage_dir": str(self.storage_dir),
            "model": self._model_name,
            "doc_types": self._count_by_key("doc_type"),
            "symbols": self._count_by_key("symbol"),
        }

    def _count_by_key(self, key: str) -> Dict[str, int]:
        """Count documents by a metadata key."""
        counts: Dict[str, int] = {}
        for meta in self._doc_registry.values():
            val = meta.get(key, "unknown")
            counts[val] = counts.get(val, 0) + 1
        return counts

    def remove_document(self, doc_id: str) -> bool:
        """Remove a document from the index.

        Note: FAISS IndexFlatL2 doesn't support removal, so we rebuild.
        This is fine for personal use with <1000 documents.
        """
        if doc_id not in self._doc_registry:
            return False

        # Filter out chunks for this document
        remaining_chunks = [c for c in self._chunks if c.doc_id != doc_id]

        if len(remaining_chunks) == len(self._chunks):
            return False

        # Remove from registry
        del self._doc_registry[doc_id]

        # Rebuild index
        self._chunks = remaining_chunks
        if remaining_chunks and HAS_FAISS and HAS_NUMPY:
            texts = [c.text for c in remaining_chunks]
            embeddings = self.model.encode(texts, show_progress_bar=False)
            embeddings = np.array(embeddings, dtype=np.float32)

            dim = embeddings.shape[1]
            self._index = faiss.IndexFlatL2(dim)
            self._index.add(embeddings)
        else:
            self._index = None

        self._save_state()
        return True

    # ── Persistence ─────────────────────────────────────────────────

    def _save_state(self):
        """Save chunks metadata and FAISS index to disk."""
        try:
            # Save chunk metadata
            chunks_path = self.storage_dir / "chunks.json"
            with open(chunks_path, "w") as f:
                json.dump([c.to_dict() for c in self._chunks], f)

            # Save document registry
            registry_path = self.storage_dir / "doc_registry.json"
            with open(registry_path, "w") as f:
                json.dump(self._doc_registry, f, indent=2)

            # Save FAISS index
            if self._index and HAS_FAISS and self._index.ntotal > 0:
                index_path = str(self.storage_dir / "faiss.index")
                faiss.write_index(self._index, index_path)

        except Exception:
            pass  # non-critical for personal use

    def _load_state(self):
        """Load existing index and metadata from disk."""
        try:
            # Load chunks
            chunks_path = self.storage_dir / "chunks.json"
            if chunks_path.exists():
                with open(chunks_path) as f:
                    self._chunks = [DocumentChunk.from_dict(d) for d in json.load(f)]

            # Load registry
            registry_path = self.storage_dir / "doc_registry.json"
            if registry_path.exists():
                with open(registry_path) as f:
                    self._doc_registry = json.load(f)

            # Load FAISS index
            index_path = self.storage_dir / "faiss.index"
            if index_path.exists() and HAS_FAISS:
                self._index = faiss.read_index(str(index_path))

        except Exception:
            pass  # start fresh if anything fails


# ── Convenience: auto-ingest a directory ────────────────────────────

def ingest_directory(
    rag: FinRAG,
    directory: str,
    symbol: Optional[str] = None,
    extensions: Tuple[str, ...] = (".pdf", ".txt", ".md"),
) -> Dict[str, int]:
    """Ingest all matching files in a directory.

    Returns dict of {filename: num_chunks}.
    """
    directory = Path(directory)
    results = {}

    for ext in extensions:
        for filepath in directory.glob(f"**/*{ext}"):
            try:
                # Guess doc_type from path/filename
                name_lower = filepath.name.lower()
                if "10-k" in name_lower or "10k" in name_lower:
                    doc_type = "10-K"
                elif "10-q" in name_lower or "10q" in name_lower:
                    doc_type = "10-Q"
                elif "earning" in name_lower:
                    doc_type = "earnings"
                elif "annual" in name_lower:
                    doc_type = "annual"
                elif "research" in name_lower or "analysis" in name_lower:
                    doc_type = "research"
                else:
                    doc_type = "document"

                n = rag.ingest_file(
                    str(filepath),
                    symbol=symbol,
                    doc_type=doc_type,
                    metadata={"directory": str(directory)},
                )
                if n > 0:
                    results[filepath.name] = n
            except Exception:
                results[filepath.name] = 0

    return results
