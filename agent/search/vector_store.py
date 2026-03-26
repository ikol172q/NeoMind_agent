# agent/search/vector_store.py
"""
Local Vector Search — index and retrieve past search results using FAISS.

Stores embeddings of search results for semantic similarity retrieval.
Useful for "have I searched this before?" and related-topic discovery.

Dependencies:
    pip install faiss-cpu sentence-transformers

Design:
  - Uses sentence-transformers for embeddings (MiniLM-L6-v2, ~80MB)
  - FAISS for fast similarity search (CPU, no GPU needed)
  - SQLite metadata store alongside FAISS index
  - Automatic background indexing of search results
"""

import os
import json
import time
import sqlite3
import hashlib
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

# ── Optional imports ─────────────────────────────────────────────────

try:
    import faiss
    import numpy as np
    HAS_FAISS = True
except ImportError:
    HAS_FAISS = False
    faiss = None
    np = None

try:
    from sentence_transformers import SentenceTransformer
    HAS_SBERT = True
except ImportError:
    HAS_SBERT = False
    SentenceTransformer = None


class LocalVectorStore:
    """FAISS-backed vector store for search result history.

    Usage:
        store = LocalVectorStore()
        if store.available:
            store.add_results(query, items)
            similar = store.find_similar("related topic", top_k=5)
    """

    def __init__(
        self,
        storage_dir: Optional[str] = None,
        model_name: str = "all-MiniLM-L6-v2",
        dimension: int = 384,
    ):
        self.storage_dir = storage_dir or os.path.expanduser("~/.neomind/vector_store")
        self._model_name = model_name
        self._dimension = dimension
        self._model = None
        self._index = None
        self._id_counter = 0
        self.available = HAS_FAISS and HAS_SBERT

        if self.available:
            os.makedirs(self.storage_dir, exist_ok=True)
            self._db_path = os.path.join(self.storage_dir, "metadata.db")
            self._index_path = os.path.join(self.storage_dir, "faiss.index")
            self._init_db()
            self._load_index()

    def _init_db(self):
        """Initialize SQLite metadata store."""
        conn = sqlite3.connect(self._db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS search_vectors (
                id INTEGER PRIMARY KEY,
                query TEXT NOT NULL,
                title TEXT,
                url TEXT,
                snippet TEXT,
                source TEXT,
                indexed_at TEXT NOT NULL,
                content_hash TEXT UNIQUE
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_content_hash ON search_vectors(content_hash)
        """)
        conn.commit()
        conn.close()

    def _load_index(self):
        """Load existing FAISS index or create new one."""
        if os.path.exists(self._index_path):
            try:
                self._index = faiss.read_index(self._index_path)
                self._id_counter = self._index.ntotal
            except Exception:
                self._index = faiss.IndexFlatIP(self._dimension)  # Inner product (cosine after normalization)
                self._id_counter = 0
        else:
            self._index = faiss.IndexFlatIP(self._dimension)
            self._id_counter = 0

    def _ensure_model(self):
        """Lazy-load the embedding model."""
        if self._model is None and self.available:
            try:
                self._model = SentenceTransformer(self._model_name)
            except Exception:
                self.available = False

    def _encode(self, texts: List[str]) -> "np.ndarray":
        """Encode texts to normalized embeddings."""
        self._ensure_model()
        if self._model is None:
            return np.array([])
        embeddings = self._model.encode(texts, normalize_embeddings=True)
        return np.array(embeddings, dtype=np.float32)

    def _content_hash(self, url: str, title: str) -> str:
        """Generate dedup hash from URL + title."""
        content = f"{url.lower().strip()}|{title.lower().strip()}"
        return hashlib.md5(content.encode()).hexdigest()

    def add_results(self, query: str, items: list) -> int:
        """Index search results into the vector store.

        Args:
            query: The original search query
            items: List of SearchItem objects

        Returns:
            Number of items actually added (after dedup).
        """
        if not self.available or not items:
            return 0

        texts = []
        metadata = []
        conn = sqlite3.connect(self._db_path)

        for item in items:
            content_hash = self._content_hash(item.url, item.title)

            # Skip duplicates
            existing = conn.execute(
                "SELECT id FROM search_vectors WHERE content_hash = ?",
                (content_hash,)
            ).fetchone()
            if existing:
                continue

            # Build text for embedding
            text = f"{query} {item.title} {item.snippet[:300]}"
            texts.append(text)
            metadata.append({
                "query": query,
                "title": item.title,
                "url": item.url,
                "snippet": item.snippet[:500],
                "source": item.source,
                "content_hash": content_hash,
            })

        if not texts:
            conn.close()
            return 0

        # Encode and add to FAISS
        embeddings = self._encode(texts)
        if embeddings.size == 0:
            conn.close()
            return 0

        self._index.add(embeddings)

        # Store metadata
        now = datetime.now(timezone.utc).isoformat()
        for meta in metadata:
            conn.execute(
                """INSERT OR IGNORE INTO search_vectors
                   (id, query, title, url, snippet, source, indexed_at, content_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    self._id_counter,
                    meta["query"], meta["title"], meta["url"],
                    meta["snippet"], meta["source"], now, meta["content_hash"],
                ),
            )
            self._id_counter += 1

        conn.commit()
        conn.close()

        # Save index to disk
        self._save_index()

        return len(texts)

    def find_similar(self, query: str, top_k: int = 5) -> List[Dict]:
        """Find previously indexed results similar to a query.

        Args:
            query: The search query
            top_k: Number of results to return

        Returns:
            List of dicts with keys: query, title, url, snippet, source, score
        """
        if not self.available or self._index is None or self._index.ntotal == 0:
            return []

        embedding = self._encode([query])
        if embedding.size == 0:
            return []

        k = min(top_k, self._index.ntotal)
        scores, indices = self._index.search(embedding, k)

        results = []
        conn = sqlite3.connect(self._db_path)
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            row = conn.execute(
                "SELECT query, title, url, snippet, source FROM search_vectors WHERE id = ?",
                (int(idx),)
            ).fetchone()
            if row:
                results.append({
                    "query": row[0],
                    "title": row[1],
                    "url": row[2],
                    "snippet": row[3],
                    "source": row[4],
                    "score": float(score),
                })
        conn.close()
        return results

    def _save_index(self):
        """Persist FAISS index to disk."""
        if self._index is not None:
            try:
                faiss.write_index(self._index, self._index_path)
            except Exception:
                pass

    def get_stats(self) -> Dict:
        """Get vector store statistics."""
        if not self.available:
            return {"available": False, "reason": "faiss-cpu or sentence-transformers not installed"}

        conn = sqlite3.connect(self._db_path)
        total = conn.execute("SELECT COUNT(*) FROM search_vectors").fetchone()[0]
        unique_queries = conn.execute("SELECT COUNT(DISTINCT query) FROM search_vectors").fetchone()[0]
        conn.close()

        return {
            "available": True,
            "total_vectors": self._index.ntotal if self._index else 0,
            "total_metadata": total,
            "unique_queries": unique_queries,
            "model": self._model_name,
            "dimension": self._dimension,
            "index_path": self._index_path,
        }

    def clear(self):
        """Clear all stored vectors and metadata."""
        if not self.available:
            return
        self._index = faiss.IndexFlatIP(self._dimension)
        self._id_counter = 0
        self._save_index()
        conn = sqlite3.connect(self._db_path)
        conn.execute("DELETE FROM search_vectors")
        conn.commit()
        conn.close()
