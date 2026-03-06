"""
Compression strategies for context management.

Provides various strategies for compressing conversation history:
- Truncation: Keep most recent and system messages
- Summarization: Use LLM to summarize old messages
- Relevance filtering: Use embeddings to keep most relevant messages
- Tool result compression: Compress large tool outputs
"""

from .base import CompressionStrategy, CompressionResult
from .truncation import TruncationStrategy
from .summarization import SummarizationStrategy
from .relevance import RelevanceFilteringStrategy
from .tool_result import ToolResultCompressionStrategy

__all__ = [
    "CompressionStrategy",
    "CompressionResult",
    "TruncationStrategy",
    "SummarizationStrategy",
    "RelevanceFilteringStrategy",
    "ToolResultCompressionStrategy",
]