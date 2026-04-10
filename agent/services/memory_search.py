"""
Memory Semantic Search for NeoMind Agent.

Provides semantic search over memory entries using TF-IDF similarity.
No external dependencies (uses stdlib math).

Created: 2026-04-02
"""

from __future__ import annotations
import math, re
from collections import Counter
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Tuple

__all__ = ["MemoryEntry", "SearchHit", "MemorySearchIndex"]


@dataclass
class MemoryEntry:
    id: str
    content: str
    memory_type: str  # user, feedback, project, reference
    created_at: str
    importance: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchHit:
    entry: MemoryEntry
    score: float  # 0-1 relevance
    matched_terms: List[str]


class MemorySearchIndex:
    """TF-IDF based semantic search over memory entries."""

    STOPWORDS = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "being", "have", "has", "had", "do", "does", "did", "will",
        "would", "could", "should", "may", "might", "can", "shall",
        "to", "of", "in", "for", "on", "with", "at", "by", "from",
        "as", "into", "through", "during", "before", "after", "and",
        "but", "or", "nor", "not", "so", "yet", "both", "either",
        "neither", "each", "every", "all", "any", "few", "more",
        "most", "other", "some", "such", "no", "only", "own", "same",
        "than", "too", "very", "just", "it", "its", "this", "that",
        "these", "those", "i", "me", "my", "we", "our", "you", "your",
        "he", "him", "his", "she", "her", "they", "them", "their",
    }

    _SPLIT_RE = re.compile(r"[^a-z0-9]+")

    def __init__(self):
        self._entries: Dict[str, MemoryEntry] = {}
        self._tf_idf: Dict[str, Dict[str, float]] = {}  # doc_id -> {term: tfidf}
        self._idf: Dict[str, float] = {}
        self._dirty = True

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def add(self, entry: MemoryEntry) -> None:
        """Add an entry to the index and mark the index as dirty."""
        self._entries[entry.id] = entry
        self._dirty = True

    def remove(self, entry_id: str) -> bool:
        """Remove an entry from the index. Returns *True* if it existed."""
        if entry_id in self._entries:
            del self._entries[entry_id]
            self._tf_idf.pop(entry_id, None)
            self._dirty = True
            return True
        return False

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        top_k: int = 10,
        type_filter: Optional[str] = None,
        min_score: float = 0.01,
    ) -> List[SearchHit]:
        """Search the index and return up to *top_k* results.

        Rebuilds the TF-IDF index if it is dirty, computes the query
        vector, then ranks every document by cosine similarity.
        """
        if self._dirty:
            self._rebuild_index()

        query_vec = self._compute_query_tfidf(query)
        if not query_vec:
            return []

        query_terms = set(query_vec.keys())
        hits: List[SearchHit] = []

        for doc_id, doc_vec in self._tf_idf.items():
            entry = self._entries[doc_id]

            # Optional type filter
            if type_filter is not None and entry.memory_type != type_filter:
                continue

            score = self._cosine_similarity(query_vec, doc_vec)

            # Boost by importance
            score *= entry.importance

            if score < min_score:
                continue

            matched = sorted(query_terms & set(doc_vec.keys()))
            hits.append(SearchHit(entry=entry, score=score, matched_terms=matched))

        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top_k]

    # ------------------------------------------------------------------
    # Index building
    # ------------------------------------------------------------------

    def _rebuild_index(self) -> None:
        """Recompute TF-IDF vectors for every document."""
        # Tokenize all documents
        doc_terms: Dict[str, List[str]] = {}
        for doc_id, entry in self._entries.items():
            doc_terms[doc_id] = self._tokenize(entry.content)

        n_docs = len(doc_terms)
        if n_docs == 0:
            self._idf = {}
            self._tf_idf = {}
            self._dirty = False
            return

        # Document frequency for each term
        df: Counter = Counter()
        for terms in doc_terms.values():
            df.update(set(terms))

        # IDF: log(N / df) — standard formulation
        self._idf = {
            term: math.log(n_docs / count)
            for term, count in df.items()
            if count > 0
        }

        # Per-document TF-IDF
        self._tf_idf = {}
        for doc_id, terms in doc_terms.items():
            tf = self._compute_tf(terms)
            self._tf_idf[doc_id] = {
                term: freq * self._idf.get(term, 0.0)
                for term, freq in tf.items()
            }

        self._dirty = False

    # ------------------------------------------------------------------
    # Tokenisation & math helpers
    # ------------------------------------------------------------------

    def _tokenize(self, text: str) -> List[str]:
        """Lowercase, split on non-alphanumeric, remove stopwords and
        single-character tokens."""
        tokens = self._SPLIT_RE.split(text.lower())
        return [t for t in tokens if t and len(t) > 1 and t not in self.STOPWORDS]

    @staticmethod
    def _cosine_similarity(vec_a: Dict[str, float], vec_b: Dict[str, float]) -> float:
        """Standard cosine similarity between two sparse vectors."""
        # Iterate over the smaller vector for efficiency
        if len(vec_a) > len(vec_b):
            vec_a, vec_b = vec_b, vec_a

        dot = 0.0
        for term, weight in vec_a.items():
            if term in vec_b:
                dot += weight * vec_b[term]

        if dot == 0.0:
            return 0.0

        mag_a = math.sqrt(sum(v * v for v in vec_a.values()))
        mag_b = math.sqrt(sum(v * v for v in vec_b.values()))

        if mag_a == 0.0 or mag_b == 0.0:
            return 0.0

        return dot / (mag_a * mag_b)

    @staticmethod
    def _compute_tf(terms: List[str]) -> Dict[str, float]:
        """Term frequency: count / total terms."""
        if not terms:
            return {}
        counts = Counter(terms)
        total = len(terms)
        return {term: count / total for term, count in counts.items()}

    def _compute_query_tfidf(self, query: str) -> Dict[str, float]:
        """Build a TF-IDF vector for the query using the corpus IDF values."""
        terms = self._tokenize(query)
        if not terms:
            return {}
        tf = self._compute_tf(terms)
        return {
            term: freq * self._idf[term]
            for term, freq in tf.items()
            if term in self._idf
        }
