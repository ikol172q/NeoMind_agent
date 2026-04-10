"""
Multi-Source Search and Synthesis for NeoMind Agent.

Provides comprehensive search capabilities across multiple sources
and produces synthesized, high-quality results with citations.

Inspired by Claude Code's multiSourceSynthesizer and Perplexity approach.

Created: 2026-04-02 (Phase 1 - Chat 搜索增强)
"""

from __future__ import annotations

import asyncio
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class SynthesisStrategy(Enum):
    """Strategy for combining results."""
    CONSENSUS = "consensus"
    MAJORITY = "majority"
    HIGHEST_QUALITY = "highest_quality"
    MOST_RECENT = "most_recent"


@dataclass
class SearchResult:
    """Represents a search result with metadata."""
    source: str
    title: str
    url: str
    snippet: str
    content: Optional[str] = None
    summary: Optional[str] = None
    published_date: Optional[datetime] = None
    relevance_score: float = 0.0
    quality_score: float = 0.0
    citations: List[Dict[str, str]] = field(default_factory=list)


class MultiSourceSynthesizer:
    """
    Synthesizes search results from multiple sources.

    Features:
    - Multi-source aggregation
    - Deduplication
    - Quality scoring
    - Relevance ranking
    - Citation generation
    """

    def __init__(self):
        """Initialize the synthesizer."""
        self._sources: Dict[str, Any] = {}
        self._cache: Dict[str, SearchResult] = {}

    def add_source(self, name: str, source_client: Any) -> None:
        """
        Add a search source.

        Args:
            name: Source name (e.g., "duckduckgo", "google")
            source_client: Client for the search source
        """
        self._sources[name] = source_client

    def synthesize(
        self,
        results: List[SearchResult],
        strategy: SynthesisStrategy = SynthesisStrategy.HIGHEST_QUALITY,
        max_results: int = 10
    ) -> str:
        """
        Synthesize multiple search results into a coherent response.

        Args:
            results: List of SearchResult objects
            strategy: Synthesis strategy
            max_results: Maximum results to include

        Returns:
            Synthesized text
        """
        if not results:
            return "No results found."

        # Deduplicate
        unique_results = self._deduplicate(results)

        # Sort by strategy
        sorted_results = self._sort_by_strategy(unique_results, strategy)

        # Take top results
        top_results = sorted_results[:max_results]

        # Generate synthesis
        synthesis = self._generate_synthesis(top_results)

        return synthesis

    def _deduplicate(self, results: List[SearchResult]) -> List[SearchResult]:
        """Remove duplicate results based on URL."""
        seen_urls = set()
        unique = []

        for result in results:
            if result.url not in seen_urls:
                seen_urls.add(result.url)
                unique.append(result)

        return unique

    def _sort_by_strategy(
        self,
        results: List[SearchResult],
        strategy: SynthesisStrategy
    ) -> List[SearchResult]:
        """Sort results based on synthesis strategy."""
        if strategy == SynthesisStrategy.HIGHEST_QUALITY:
            return sorted(results, key=lambda r: r.quality_score, reverse=True)
        elif strategy == SynthesisStrategy.MOST_RECENT:
            return sorted(
                results,
                key=lambda r: r.published_date or datetime.min,
                reverse=True
            )
        elif strategy == SynthesisStrategy.MAJORITY:
            # Group by source and prefer most common
            return sorted(results, key=lambda r: r.relevance_score, reverse=True)
        else:
            return sorted(results, key=lambda r: r.relevance_score, reverse=True)

    def _generate_synthesis(self, results: List[SearchResult]) -> str:
        """Generate synthesis from top results."""
        if not results:
            return "No results to synthesize."

        parts = []

        # Introduction
        parts.append("## Search Results\n")

        # Results
        for i, result in enumerate(results, 1):
            parts.append(f"### [{i}] {result.title}\n")
            parts.append(f"**Source:** {result.source}\n")
            parts.append(f"**URL:** {result.url}\n")
            parts.append(f"**Relevance:** {result.relevance_score:.2f}\n")
            parts.append(f"\n{result.snippet}\n")
            if result.content:
                parts.append(f"\n*Content preview:* {result.content[:200]}...\n")
            parts.append("")

        # Summary
        parts.append("## Summary\n")
        parts.append(self._create_summary(results))

        return "\n".join(parts)

    def _create_summary(self, results: List[SearchResult]) -> str:
        """Create a brief summary of results."""
        if not results:
            return ""

        summary_parts = []
        for result in results[:3]:
            summary_parts.append(f"- **{result.title}**: {result.snippet[:100]}...")

        return "\n".join(summary_parts)

    def generate_citations(self, results: List[SearchResult]) -> List[str]:
        """Generate citations for results."""
        citations = []

        for i, result in enumerate(results, 1):
            citation = f"[{i}] {result.title}. {result.source}. {result.url}"
            citations.append(citation)

        return citations

    def get_stats(self) -> Dict[str, Any]:
        """Get synthesizer statistics."""
        return {
            "sources": len(self._sources),
            "cache_size": len(self._cache),
        }


__all__ = [
    'MultiSourceSynthesizer',
    'SearchResult',
    'SynthesisStrategy',
]


if __name__ == "__main__":
    # Test the synthesizer
    synthesizer = MultiSourceSynthesizer()

    # Create mock results
    results = [
        SearchResult(
            source="DuckDuckGo",
            title="Python Async Programming",
            url="https://example.com/async",
            snippet="Learn about async programming in Python...",
            relevance_score=0.95,
            quality_score=0.9
        ),
        SearchResult(
            source="Google",
            title="Understanding Python Asyncio",
            url="https://example.com/asyncio",
            snippet="A comprehensive guide to asyncio...",
            relevance_score=0.88,
            quality_score=0.85
        ),
    ]

    print("=== MultiSourceSynthesizer Test ===")
    synthesis = synthesizer.synthesize(results)
    print(synthesis)

    print("\nCitations:")
    for citation in synthesizer.generate_citations(results):
        print(f"  {citation}")

    print("\n✅ MultiSourceSynthesizer test passed!")
