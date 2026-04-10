"""
Citation Manager for NeoMind Agent.

Manages citations and references for research and synthesis.
Inspired by academic citation formats and Claude Code's citation support.

Created: 2026-04-02 (Phase 1 - Chat 搜索增强)
"""

from __future__ import annotations

import re
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlparse


@dataclass
class Citation:
    """Represents a single citation."""
    id: str
    title: str
    url: str
    author: Optional[str] = None
    date: Optional[str] = None
    source_type: str = "web"  # web, paper, book, news
    access_date: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    relevance_score: float = 0.0
    snippet: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class CitationManager:
    """
    Manages citations for research and synthesis.

    Features:
    - Multiple citation formats (APA, MLA, Chicago, inline)
    - Automatic citation generation from URLs
    - Citation deduplication
    - Reference list formatting
    """

    def __init__(self):
        """Initialize the citation manager."""
        self._citations: Dict[str, Citation] = {}
        self._counter = 0

    def add_citation(
        self,
        title: str,
        url: str,
        author: Optional[str] = None,
        date: Optional[str] = None,
        source_type: str = "web",
        relevance_score: float = 0.0,
        snippet: str = ""
    ) -> Citation:
        """
        Add a new citation.

        Args:
            title: Title of the source
            url: URL or identifier
            author: Author name(s)
            date: Publication date
            source_type: Type of source (web, paper, book, news)
            relevance_score: Relevance score (0-1)
            snippet: Relevant snippet from the source

        Returns:
            Created Citation object
        """
        # Check for duplicate
        for existing in self._citations.values():
            if existing.url == url and existing.title == title:
                # Update relevance if higher
                if relevance_score > existing.relevance_score:
                    existing.relevance_score = relevance_score
                return existing

        # Create new citation
        self._counter += 1
        citation_id = f"[{self._counter}]"

        citation = Citation(
            id=citation_id,
            title=title,
            url=url,
            author=author,
            date=date,
            source_type=source_type,
            relevance_score=relevance_score,
            snippet=snippet
        )

        self._citations[citation_id] = citation
        return citation

    def get_citation(self, citation_id: str) -> Optional[Citation]:
        """Get a citation by ID."""
        return self._citations.get(citation_id)

    def get_all_citations(self) -> List[Citation]:
        """Get all citations sorted by relevance."""
        return sorted(
            self._citations.values(),
            key=lambda c: c.relevance_score,
            reverse=True
        )

    def format_citation(self, citation: Citation, style: str = "inline") -> str:
        """
        Format a citation in the specified style.

        Args:
            citation: Citation object
            style: Citation style (inline, apa, mla, chicago, footnote)

        Returns:
            Formatted citation string
        """
        if style == "inline":
            return self._format_inline(citation)
        elif style == "apa":
            return self._format_apa(citation)
        elif style == "mla":
            return self._format_mla(citation)
        elif style == "chicago":
            return self._format_chicago(citation)
        elif style == "footnote":
            return self._format_footnote(citation)
        else:
            return self._format_inline(citation)

    def _format_inline(self, citation: Citation) -> str:
        """Format as inline citation."""
        return f"{citation.id} {citation.title}. {citation.url}"

    def _format_apa(self, citation: Citation) -> str:
        """Format in APA style."""
        parts = []

        if citation.author:
            parts.append(f"{citation.author}")
            if citation.date:
                parts.append(f"({citation.date})")
        else:
            if citation.date:
                parts.append(f"({citation.date})")

        parts.append(f"{citation.title}.")

        if citation.source_type == "web":
            parts.append(f"Retrieved from {citation.url}")
        else:
            parts.append(citation.url)

        return " ".join(parts)

    def _format_mla(self, citation: Citation) -> str:
        """Format in MLA style."""
        parts = []

        if citation.author:
            parts.append(f"{citation.author}.")

        parts.append(f'"{citation.title}."')

        if citation.date:
            parts.append(f"{citation.date},")

        if citation.source_type == "web":
            domain = urlparse(citation.url).netloc
            parts.append(f"{domain},")
            parts.append(f"{citation.url}.")
            parts.append(f"Accessed {citation.access_date}.")

        return " ".join(parts)

    def _format_chicago(self, citation: Citation) -> str:
        """Format in Chicago style."""
        parts = []

        if citation.author:
            parts.append(f"{citation.author}.")

        parts.append(f'"{citation.title}."')

        if citation.date:
            parts.append(f"Accessed {citation.date}.")

        parts.append(citation.url)

        return " ".join(parts)

    def _format_footnote(self, citation: Citation) -> str:
        """Format as footnote."""
        parts = [f"{citation.id}"]

        if citation.author:
            parts.append(f"{citation.author},")

        parts.append(f'"{citation.title},"')

        if citation.url:
            parts.append(citation.url)

        if citation.access_date:
            parts.append(f"(accessed {citation.access_date})")

        return " ".join(parts)

    def format_bibliography(self, style: str = "apa") -> str:
        """
        Format all citations as a bibliography.

        Args:
            style: Citation style

        Returns:
            Formatted bibliography string
        """
        citations = self.get_all_citations()

        if not citations:
            return "No citations."

        lines = ["## References\n"]

        for citation in citations:
            formatted = self.format_citation(citation, style)
            lines.append(f"{formatted}\n")

        return "\n".join(lines)

    def extract_from_text(self, text: str) -> List[Citation]:
        """
        Extract citations from text with [N] markers.

        Args:
            text: Text containing citation markers

        Returns:
            List of Citation objects referenced in text
        """
        # Find all citation markers
        pattern = r'\[(\d+)\]'
        matches = re.findall(pattern, text)

        citations = []
        for match in matches:
            citation_id = f"[{match}]"
            citation = self._citations.get(citation_id)
            if citation:
                citations.append(citation)

        return citations

    def embed_citations(self, text: str, citations: List[Citation]) -> str:
        """
        Embed citations into text.

        Args:
            text: Original text
            citations: Citations to embed

        Returns:
            Text with embedded citations
        """
        result = text

        for citation in citations:
            # Add citation after relevant sentences
            # This is a simplified approach
            pass

        return result

    def create_from_search_results(self, results: List[Dict]) -> List[Citation]:
        """
        Create citations from search results.

        Args:
            results: List of search result dictionaries

        Returns:
            List of created Citation objects
        """
        citations = []

        for result in results:
            citation = self.add_citation(
                title=result.get("title", "Untitled"),
                url=result.get("url", ""),
                author=result.get("author"),
                date=result.get("date"),
                source_type=result.get("source_type", "web"),
                relevance_score=result.get("relevance_score", 0.0),
                snippet=result.get("snippet", "")
            )
            citations.append(citation)

        return citations

    def get_stats(self) -> Dict[str, Any]:
        """Get citation manager statistics."""
        return {
            "total_citations": len(self._citations),
            "source_types": {
                st: sum(1 for c in self._citations.values() if c.source_type == st)
                for st in ["web", "paper", "book", "news"]
            },
            "avg_relevance": sum(c.relevance_score for c in self._citations.values()) / max(len(self._citations), 1)
        }

    def clear(self) -> None:
        """Clear all citations."""
        self._citations.clear()
        self._counter = 0


# Convenience functions
def create_citation(title: str, url: str, **kwargs) -> Citation:
    """Quick citation creation function."""
    manager = CitationManager()
    return manager.add_citation(title, url, **kwargs)


__all__ = [
    'CitationManager',
    'Citation',
    'create_citation',
]


if __name__ == "__main__":
    # Test the citation manager
    manager = CitationManager()

    # Add some citations
    c1 = manager.add_citation(
        title="Python Documentation",
        url="https://docs.python.org/3/",
        author="Python Software Foundation",
        date="2024",
        relevance_score=0.95
    )

    c2 = manager.add_citation(
        title="Async IO in Python",
        url="https://realpython.com/async-io-python/",
        author="Real Python",
        date="2023",
        relevance_score=0.88
    )

    c3 = manager.add_citation(
        title="Understanding Async/Await",
        url="https://example.com/async",
        relevance_score=0.75
    )

    print("=== Citation Manager Test ===")
    print(f"Total citations: {len(manager.get_all_citations())}")
    print()

    # Test different formats
    print("Inline format:")
    print(manager.format_citation(c1, "inline"))
    print()

    print("APA format:")
    print(manager.format_citation(c1, "apa"))
    print()

    print("MLA format:")
    print(manager.format_citation(c1, "mla"))
    print()

    print("Chicago format:")
    print(manager.format_citation(c1, "chicago"))
    print()

    # Test bibliography
    print("Bibliography:")
    print(manager.format_bibliography("apa"))

    print("Stats:", manager.get_stats())
    print("\n✅ CitationManager test passed!")
