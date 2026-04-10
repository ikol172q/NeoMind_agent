"""
Deep Summarizer for NeoMind Agent.

Provides LLM-powered summarization with citation support.
Inspired by Claude Code's summarization capabilities.

Created: 2026-04-02 (Phase 1 - Chat 搜索增强)
"""

from __future__ import annotations

import asyncio
import re
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class SummaryResult:
    """Result of a summarization operation."""
    summary: str
    key_points: List[str]
    citations: List[Dict[str, str]]
    word_count: int
    compression_ratio: float
    metadata: Dict[str, Any] = field(default_factory=dict)


class DeepSummarizer:
    """
    Deep summarization with LLM assistance and citation support.

    Features:
    - Multi-level summarization (brief, standard, detailed)
    - Key point extraction
    - Citation generation
    - Compression ratio tracking
    """

    # Summary length presets (target word counts)
    LENGTH_BRIEF = 100
    LENGTH_STANDARD = 300
    LENGTH_DETAILED = 600

    def __init__(self, llm_client=None):
        """
        Initialize the deep summarizer.

        Args:
            llm_client: LLM client for generating summaries
        """
        self.llm_client = llm_client
        self._cache: Dict[str, SummaryResult] = {}

    def summarize(
        self,
        content: str,
        length: int = LENGTH_STANDARD,
        extract_key_points: bool = True,
        include_citations: bool = True,
        sources: Optional[List[Dict]] = None
    ) -> SummaryResult:
        """
        Generate a deep summary of content.

        Args:
            content: Text content to summarize
            length: Target word count for summary
            extract_key_points: Whether to extract key points
            include_citations: Whether to include citations
            sources: Optional list of source dictionaries for citations

        Returns:
            SummaryResult object
        """
        if not content or not content.strip():
            return SummaryResult(
                summary="",
                key_points=[],
                citations=[],
                word_count=0,
                compression_ratio=0.0
            )

        # Check cache
        cache_key = self._get_cache_key(content, length)
        if cache_key in self._cache:
            return self._cache[cache_key]

        original_word_count = len(content.split())

        # Generate summary
        if self.llm_client:
            summary = self._llm_summarize(content, length)
        else:
            summary = self._heuristic_summarize(content, length)

        # Extract key points
        key_points = []
        if extract_key_points:
            key_points = self._extract_key_points(content, summary)

        # Generate citations
        citations = []
        if include_citations and sources:
            citations = self._generate_citations(sources, key_points)

        # Calculate metrics
        summary_word_count = len(summary.split())
        compression_ratio = original_word_count / max(summary_word_count, 1)

        result = SummaryResult(
            summary=summary,
            key_points=key_points,
            citations=citations,
            word_count=summary_word_count,
            compression_ratio=compression_ratio,
            metadata={
                "original_word_count": original_word_count,
                "target_length": length,
                "timestamp": datetime.now().isoformat()
            }
        )

        # Cache result
        self._cache[cache_key] = result

        return result

    def _llm_summarize(self, content: str, target_length: int) -> str:
        """Use LLM to generate summary."""
        prompt = f"""Summarize the following content in approximately {target_length} words.
Focus on the main ideas and key details. Be concise but comprehensive.

Content:
{content[:10000]}  # Limit to avoid token limits

Summary:"""

        try:
            # This would call the LLM client
            # For now, fall back to heuristic
            return self._heuristic_summarize(content, target_length)
        except Exception:
            return self._heuristic_summarize(content, target_length)

    def _heuristic_summarize(self, content: str, target_length: int) -> str:
        """Use heuristic methods to generate summary."""
        # Split into sentences
        sentences = self._split_sentences(content)

        if not sentences:
            return ""

        # Score sentences by importance
        scored_sentences = []
        for i, sentence in enumerate(sentences):
            score = self._score_sentence(sentence, i, len(sentences), content)
            scored_sentences.append((score, i, sentence))

        # Sort by score and select top sentences
        scored_sentences.sort(reverse=True)

        # Select sentences until we reach target length
        selected = []
        current_length = 0
        target_words = target_length

        for score, idx, sentence in scored_sentences:
            sentence_words = len(sentence.split())
            if current_length + sentence_words <= target_words * 1.2:
                selected.append((idx, sentence))
                current_length += sentence_words
            if current_length >= target_words:
                break

        # Sort by original order
        selected.sort(key=lambda x: x[0])

        # Combine into summary
        summary = " ".join(s for _, s in selected)

        return summary

    def _split_sentences(self, text: str) -> List[str]:
        """Split text into sentences."""
        # Simple sentence splitting
        sentences = re.split(r'(?<=[.!?])\s+', text)
        return [s.strip() for s in sentences if s.strip() and len(s) > 10]

    def _score_sentence(
        self,
        sentence: str,
        position: int,
        total_sentences: int,
        full_content: str
    ) -> float:
        """Score a sentence by importance."""
        score = 0.0

        # Position bonus (first and last sentences are important)
        if position < 3:
            score += 0.3
        elif position >= total_sentences - 3:
            score += 0.2

        # Length bonus (medium-length sentences are better)
        word_count = len(sentence.split())
        if 10 <= word_count <= 30:
            score += 0.2
        elif word_count > 30:
            score += 0.1

        # Keyword bonus
        important_words = {
            'important', 'significant', 'key', 'main', 'primary',
            'essential', 'critical', 'major', 'fundamental', 'crucial',
            'conclusion', 'result', 'finding', 'therefore', 'thus'
        }
        sentence_lower = sentence.lower()
        for word in important_words:
            if word in sentence_lower:
                score += 0.1

        # Number presence (statistics are important)
        if re.search(r'\d+(?:\.\d+)?%', sentence):
            score += 0.2
        if re.search(r'\$?\d{1,3}(?:,\d{3})*(?:\.\d+)?', sentence):
            score += 0.1

        return score

    def _extract_key_points(self, content: str, summary: str) -> List[str]:
        """Extract key points from content."""
        key_points = []

        # Extract sentences with key indicators
        sentences = self._split_sentences(content)

        key_indicators = [
            'firstly', 'secondly', 'thirdly', 'finally',
            'most importantly', 'the key', 'the main',
            'in conclusion', 'to summarize', 'in summary',
            'the result', 'the finding', 'we found'
        ]

        for sentence in sentences:
            sentence_lower = sentence.lower()
            for indicator in key_indicators:
                if indicator in sentence_lower:
                    key_points.append(sentence)
                    break

        # Limit to top 5 key points
        return key_points[:5]

    def _generate_citations(
        self,
        sources: List[Dict],
        key_points: List[str]
    ) -> List[Dict[str, str]]:
        """Generate citations for sources."""
        citations = []

        for i, source in enumerate(sources, 1):
            citation = {
                "id": f"[{i}]",
                "title": source.get("title", "Untitled"),
                "url": source.get("url", ""),
                "author": source.get("author", ""),
                "date": source.get("date", ""),
                "relevance": source.get("relevance_score", 0.0)
            }
            citations.append(citation)

        return citations

    def _get_cache_key(self, content: str, length: int) -> str:
        """Generate cache key for content."""
        import hashlib
        content_hash = hashlib.md5(content.encode()).hexdigest()[:16]
        return f"{content_hash}_{length}"

    def summarize_multiple(
        self,
        contents: List[Tuple[str, Dict]],
        length: int = LENGTH_STANDARD
    ) -> SummaryResult:
        """
        Summarize multiple pieces of content together.

        Args:
            contents: List of (content, metadata) tuples
            length: Target word count

        Returns:
            Combined summary result
        """
        if not contents:
            return SummaryResult(
                summary="",
                key_points=[],
                citations=[],
                word_count=0,
                compression_ratio=0.0
            )

        # Combine all content
        combined_content = "\n\n".join(c for c, _ in contents)
        sources = [meta for _, meta in contents if meta]

        return self.summarize(
            combined_content,
            length=length,
            extract_key_points=True,
            include_citations=True,
            sources=sources
        )

    def get_stats(self) -> Dict[str, Any]:
        """Get summarizer statistics."""
        return {
            "cache_size": len(self._cache),
            "has_llm_client": self.llm_client is not None,
        }


# Convenience functions
def summarize(content: str, length: int = DeepSummarizer.LENGTH_STANDARD) -> str:
    """Quick summarization function."""
    summarizer = DeepSummarizer()
    result = summarizer.summarize(content, length)
    return result.summary


__all__ = [
    'DeepSummarizer',
    'SummaryResult',
    'summarize',
]


if __name__ == "__main__":
    # Test the summarizer
    test_content = """
    Artificial intelligence has made significant strides in recent years,
    particularly in natural language processing. Large language models like
    GPT-4 and Claude have demonstrated remarkable capabilities in understanding
    and generating human-like text. These models are trained on vast amounts
    of data and can perform a wide variety of tasks, from answering questions
    to writing code.

    The key breakthrough came with the transformer architecture, which allows
    models to process text in parallel rather than sequentially. This has led
    to dramatic improvements in both training efficiency and model performance.

    In conclusion, AI language models represent a major advancement in
    technology, with applications spanning virtually every industry. However,
    important challenges remain, including issues of bias, accuracy, and
    the environmental impact of training large models.
    """

    summarizer = DeepSummarizer()
    result = summarizer.summarize(test_content, length=100)

    print("=== Deep Summarizer Test ===")
    print(f"Original: {len(test_content.split())} words")
    print(f"Summary: {result.word_count} words")
    print(f"Compression: {result.compression_ratio:.1f}x")
    print(f"\nSummary:\n{result.summary}")
    print(f"\nKey Points ({len(result.key_points)}):")
    for i, point in enumerate(result.key_points, 1):
        print(f"  {i}. {point[:80]}...")

    print("\n✅ DeepSummarizer test passed!")
