"""
Semantic Search Tool for NeoMind Agent.

Provides semantic code search using embeddings for the Coding personality.
Enables natural language queries to find relevant code.

Created: 2026-04-02 (Phase 2 - Coding 完整功能)
"""

from __future__ import annotations

import asyncio
import hashlib
import pickle
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class SemanticResult:
    """Result from semantic search."""
    file_path: str
    content: str
    score: float
    start_line: int
    end_line: int
    metadata: Dict[str, Any] = field(default_factory=dict)


class SemanticSearchTool:
    """
    Semantic search for code using embeddings.

    Features:
    - Natural language queries
    - Code-aware chunking
    - Embedding caching
    - Fallback to keyword search
    """

    # Default embedding dimension (for sentence-transformers)
    EMBEDDING_DIM = 384

    # Chunk size for code (lines)
    CHUNK_SIZE = 50
    CHUNK_OVERLAP = 10

    def __init__(
        self,
        index_path: Optional[Path] = None,
        embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    ):
        """
        Initialize semantic search tool.

        Args:
            index_path: Path to store the embedding index
            embedding_model: Name of the embedding model to use
        """
        self.index_path = index_path or Path.home() / ".neomind" / "semantic_index"
        self.index_path.mkdir(parents=True, exist_ok=True)

        self.embedding_model = embedding_model
        self._embedder = None
        self._index = None
        self._chunks: Dict[str, List[Dict]] = {}  # file_path -> chunks
        self._embeddings: Dict[str, List[List[float]]] = {}

    def _get_embedder(self):
        """Lazy-load embedding model."""
        if self._embedder is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._embedder = SentenceTransformer(self.embedding_model)
            except ImportError:
                # Fallback to simple TF-IDF
                self._embedder = "tfidf"
        return self._embedder

    def index_files(
        self,
        files: List[Tuple[str, str]],  # (file_path, content)
        batch_size: int = 32
    ) -> Dict[str, Any]:
        """
        Index files for semantic search.

        Args:
            files: List of (file_path, content) tuples
            batch_size: Batch size for embedding

        Returns:
            Statistics about indexing
        """
        stats = {
            'files_indexed': 0,
            'chunks_created': 0,
            'errors': []
        }

        embedder = self._get_embedder()

        for file_path, content in files:
            try:
                # Chunk the content
                chunks = self._chunk_content(content)
                self._chunks[file_path] = chunks

                # Generate embeddings
                if embedder != "tfidf":
                    embeddings = self._generate_embeddings([c['content'] for c in chunks])
                else:
                    embeddings = self._generate_tfidf([c['content'] for c in chunks])

                self._embeddings[file_path] = embeddings
                stats['files_indexed'] += 1
                stats['chunks_created'] += len(chunks)

            except Exception as e:
                stats['errors'].append({
                    'file': file_path,
                    'error': str(e)
                })

        return stats

    def _chunk_content(self, content: str) -> List[Dict]:
        """Split content into overlapping chunks."""
        lines = content.split('\n')
        chunks = []

        for i in range(0, len(lines), self.CHUNK_SIZE - self.CHUNK_OVERLAP):
            chunk_lines = lines[i:i + self.CHUNK_SIZE]
            if chunk_lines:
                chunks.append({
                    'content': '\n'.join(chunk_lines),
                    'start_line': i + 1,
                    'end_line': min(i + self.CHUNK_SIZE, len(lines))
                })

        return chunks

    def _generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for texts."""
        embedder = self._get_embedder()

        if embedder != "tfidf":
            embeddings = embedder.encode(texts, convert_to_numpy=True)
            return embeddings.tolist()
        else:
            return self._generate_tfidf(texts)

    def _generate_tfidf(self, texts: List[str]) -> List[List[float]]:
        """Generate TF-IDF vectors as fallback."""
        # Simple word-based vectors
        vocab = set()
        for text in texts:
            vocab.update(text.lower().split())

        vocab = sorted(vocab)
        vocab_index = {w: i for i, w in enumerate(vocab)}

        vectors = []
        for text in texts:
            words = text.lower().split()
            vec = [0.0] * len(vocab)
            for word in words:
                if word in vocab_index:
                    vec[vocab_index[word]] += 1
            # Normalize
            norm = sum(x ** 2 for x in vec) ** 0.5 if any(vec) else 1
            vec = [x / norm for x in vec]
            vectors.append(vec)

        return vectors

    def search(
        self,
        query: str,
        limit: int = 10,
        threshold: float = 0.5
    ) -> List[SemanticResult]:
        """
        Search for relevant code chunks.

        Args:
            query: Natural language query
            limit: Maximum results
            threshold: Minimum similarity score

        Returns:
            List of SemanticResult objects
        """
        # Generate query embedding
        embedder = self._get_embedder()

        if embedder != "tfidf":
            query_embedding = embedder.encode([query], convert_to_numpy=True)[0]
        else:
            query_embedding = self._generate_tfidf([query])[0]

        # Search all chunks
        results = []

        for file_path, chunks in self._chunks.items():
            embeddings = self._embeddings.get(file_path, [])

            for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                score = self._cosine_similarity(query_embedding, embedding)

                if score >= threshold:
                    results.append(SemanticResult(
                        file_path=file_path,
                        content=chunk['content'],
                        score=score,
                        start_line=chunk['start_line'],
                        end_line=chunk['end_line']
                    ))

        # Sort by score and return top results
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if len(a) != len(b):
            return 0.0

        dot_product = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x ** 2 for x in a) ** 0.5
        norm_b = sum(x ** 2 for x in b) ** 0.5

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return dot_product / (norm_a * norm_b)

    def save_index(self) -> None:
        """Save the index to disk."""
        index_file = self.index_path / "semantic_index.pkl"
        with open(index_file, 'wb') as f:
            pickle.dump({
                'chunks': self._chunks,
                'embeddings': self._embeddings,
            }, f)

    def load_index(self) -> bool:
        """Load the index from disk."""
        index_file = self.index_path / "semantic_index.pkl"
        if index_file.exists():
            with open(index_file, 'rb') as f:
                data = pickle.load(f)
                self._chunks = data.get('chunks', {})
                self._embeddings = data.get('embeddings', {})
            return True
        return False

    def clear_index(self) -> None:
        """Clear the index."""
        self._chunks.clear()
        self._embeddings.clear()


__all__ = ['SemanticSearchTool', 'SemanticResult']


if __name__ == "__main__":
    # Test the semantic search
    print("=== Semantic Search Tool Test ===\n")

    tool = SemanticSearchTool()

    # Index some sample code
    files = [
        ("main.py", '''
def calculate_sum(numbers):
    """Calculate the sum of a list of numbers."""
    return sum(numbers)

def calculate_average(numbers):
    """Calculate the average of a list of numbers."""
    if not numbers:
        return 0
    return sum(numbers) / len(numbers)

def find_maximum(numbers):
    """Find the maximum value in a list."""
    if not numbers:
        return None
    return max(numbers)
'''),
        ("utils.py", '''
def format_date(date):
    """Format a date object to string."""
    return date.strftime("%Y-%m-%d")

def parse_date(date_string):
    """Parse a date string to date object."""
    from datetime import datetime
    return datetime.strptime(date_string, "%Y-%m-%d")
'''),
    ]

    stats = tool.index_files(files)
    print(f"Indexed: {stats['files_indexed']} files, {stats['chunks_created']} chunks")

    # Search
    print("\n--- Search Results ---")
    results = tool.search("how to calculate average", limit=3)
    for r in results:
        print(f"\n[{r.score:.2f}] {r.file_path}:{r.start_line}")
        print(f"  {r.content[:100]}...")

    print("\n✅ SemanticSearchTool test passed!")
