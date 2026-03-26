# agent/search/reranker.py
"""
Search result reranking — semantic + structural reranking after RRF merge.

Two-stage ranking:
  Stage 1: RRF Merge (structural, always runs)
  Stage 2: FlashRank (semantic, optional, ~4MB model, CPU-only)

FlashRank is a lightweight cross-encoder reranker (~4MB) that runs on CPU.
It provides 15-25% relevance improvement over RRF alone.
"""

import hashlib
from collections import defaultdict
from typing import Dict, List, Optional
from urllib.parse import urlparse

from .sources import SearchItem


# ── Optional imports ─────────────────────────────────────────────────

try:
    from flashrank import Ranker, RerankRequest
    HAS_FLASHRANK = True
except ImportError:
    HAS_FLASHRANK = False
    Ranker = None
    RerankRequest = None


# ── RRF Merger ───────────────────────────────────────────────────────

class RRFMerger:
    """Reciprocal Rank Fusion — merges results from multiple search sources.

    Formula: score(d) = SUM(1 / (k + rank_i(d))) for each source i

    Enhanced with:
    - Trust-weighted scoring
    - Multi-source appearance bonus (3+ sources → 20% boost)
    - Relevance score integration (from TF-IDF / Tavily scores)
    """

    def __init__(self, k: int = 60, trust_scores: Optional[Dict[str, float]] = None):
        self.k = k
        self.trust_scores = trust_scores or {}

    def merge(self, results_by_source: Dict[str, List[SearchItem]]) -> List[SearchItem]:
        """Merge results from multiple sources using RRF.

        Args:
            results_by_source: {source_name: [SearchItem, ...]}

        Returns:
            Deduplicated, RRF-scored items sorted by relevance.
        """
        url_scores: Dict[str, float] = defaultdict(float)
        url_items: Dict[str, SearchItem] = {}
        url_source_count: Dict[str, int] = defaultdict(int)

        for source_name, items in results_by_source.items():
            for rank, item in enumerate(items):
                key = self._dedup_key(item.url)
                rrf_score = 1.0 / (self.k + rank)

                # Trust weighting
                trust = self.trust_scores.get(source_name, 0.5)
                rrf_score *= (0.5 + trust)  # maps trust [0,1] → multiplier [0.5, 1.5]

                # Integrate existing relevance score (from Tavily, TF-IDF, etc.)
                if item.relevance_score > 0:
                    rrf_score *= (1.0 + item.relevance_score * 0.5)

                url_scores[key] += rrf_score
                url_source_count[key] += 1

                # Keep the item with the richest content
                if key not in url_items or len(item.best_content) > len(url_items[key].best_content):
                    url_items[key] = item

        # Cross-source bonus
        for key in url_scores:
            count = url_source_count[key]
            if count >= 3:
                url_scores[key] *= 1.2
            elif count >= 2:
                url_scores[key] *= 1.1

        # Sort by RRF score
        sorted_keys = sorted(url_scores.keys(), key=lambda k: -url_scores[k])

        results = []
        for key in sorted_keys:
            item = url_items[key]
            item.rrf_score = url_scores[key]
            results.append(item)

        return results

    def _dedup_key(self, url: str) -> str:
        """Normalize URL for deduplication."""
        try:
            parsed = urlparse(url.lower().strip().rstrip("/"))
            clean = f"{parsed.netloc}{parsed.path}"
            return hashlib.md5(clean.encode()).hexdigest()
        except Exception:
            return hashlib.md5(url.encode()).hexdigest()


# ── FlashRank Semantic Reranker ──────────────────────────────────────

class FlashReranker:
    """Lightweight semantic reranker using FlashRank (~4MB, CPU-only).

    Install: pip install flashrank
    Model: ms-marco-MiniLM-L-12-v2 (~4MB, downloads on first use)

    Reranks search results using cross-encoder semantic similarity.
    Provides 15-25% relevance improvement over RRF alone.
    """

    def __init__(self, model_name: str = "ms-marco-MiniLM-L-12-v2", max_length: int = 512):
        self.available = HAS_FLASHRANK
        self._ranker = None
        self._model_name = model_name
        self._max_length = max_length

    def _ensure_ranker(self):
        """Lazy-load the ranker model on first use."""
        if self._ranker is None and self.available:
            try:
                self._ranker = Ranker(model_name=self._model_name, max_length=self._max_length)
            except Exception:
                self.available = False

    def rerank(self, query: str, items: List[SearchItem], top_n: int = 20) -> List[SearchItem]:
        """Rerank search items using semantic similarity to the query.

        Args:
            query: The original search query
            items: SearchItem list (already RRF-merged)
            top_n: Number of items to rerank (pass-through for the rest)

        Returns:
            Reranked list of SearchItems with rerank_score set.
        """
        if not self.available or not items:
            return items

        self._ensure_ranker()
        if self._ranker is None:
            return items

        # Only rerank the top N (to keep latency low)
        to_rerank = items[:top_n]
        passthrough = items[top_n:]

        try:
            # Build passages for FlashRank
            passages = []
            for item in to_rerank:
                text = item.best_content[:self._max_length]
                passages.append({"id": id(item), "text": text, "meta": {"item": item}})

            rerank_request = RerankRequest(query=query, passages=passages)
            results = self._ranker.rerank(rerank_request)

            # Map rerank scores back to items
            reranked = []
            for r in results:
                item = r["meta"]["item"]
                item.rerank_score = r["score"]
                # Blend: 60% semantic + 40% structural (RRF)
                # Normalize RRF to [0, 1] range using softmax-like scaling
                max_rrf = max(i.rrf_score for i in to_rerank) or 1.0
                norm_rrf = item.rrf_score / max_rrf
                item.rrf_score = 0.6 * r["score"] + 0.4 * norm_rrf
                reranked.append(item)

            # Sort by blended score
            reranked.sort(key=lambda x: x.rrf_score, reverse=True)
            return reranked + passthrough

        except Exception:
            # If reranking fails, return original order
            return items

    def is_available(self) -> bool:
        """Check if FlashRank is installed and loadable."""
        if not self.available:
            return False
        self._ensure_ranker()
        return self._ranker is not None


# ── Cohere Reranker (PAID — placeholder) ─────────────────────────────

try:
    import cohere as _cohere_module
    HAS_COHERE = True
except ImportError:
    HAS_COHERE = False
    _cohere_module = None


class CohereReranker:
    """Cohere Rerank 3.5 — high-accuracy commercial reranker (PAID).

    Provides 20-35% accuracy improvement over lightweight rerankers.
    Adds ~200-500ms latency per request.

    Free tier: limited usage.
    Install: pip install cohere
    Set COHERE_API_KEY in environment.

    Usage:
        reranker = CohereReranker()
        if reranker.available:
            reranked = reranker.rerank(query, items, top_n=20)
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "rerank-v3.5"):
        import os
        self.api_key = api_key or os.getenv("COHERE_API_KEY")
        self._model = model
        self._client = None
        self.available = False
        if self.api_key and HAS_COHERE:
            try:
                self._client = _cohere_module.ClientV2(self.api_key)
                self.available = True
            except Exception:
                pass

    def rerank(self, query: str, items: List[SearchItem], top_n: int = 20) -> List[SearchItem]:
        """Rerank search items using Cohere Rerank API.

        Args:
            query: The original search query
            items: SearchItem list (already RRF-merged)
            top_n: Number of top items to return

        Returns:
            Reranked list of SearchItems with rerank_score set.
        """
        if not self.available or not self._client or not items:
            return items

        to_rerank = items[:top_n]
        passthrough = items[top_n:]

        try:
            documents = [item.best_content[:4096] for item in to_rerank]

            response = self._client.rerank(
                model=self._model,
                query=query,
                documents=documents,
                top_n=top_n,
            )

            reranked = []
            for r in response.results:
                item = to_rerank[r.index]
                item.rerank_score = r.relevance_score
                # Blend: 70% Cohere semantic + 30% structural (RRF)
                max_rrf = max(i.rrf_score for i in to_rerank) or 1.0
                norm_rrf = item.rrf_score / max_rrf
                item.rrf_score = 0.7 * r.relevance_score + 0.3 * norm_rrf
                reranked.append(item)

            reranked.sort(key=lambda x: x.rrf_score, reverse=True)
            return reranked + passthrough

        except Exception:
            return items
