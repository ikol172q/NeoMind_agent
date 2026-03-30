"""
NeoMind LLM-Agnostic Abstraction Layer
数据驱动的个人能力延伸系统 — LLM 无关抽象层

Ensures NeoMind works with ANY LLM backend:
- Unified OpenAI-compatible tool format
- Context Budget Manager (75% input budget)
- Selective tool schema injection (max 8)
- Smart model routing
- Fallback for models without function calling
"""

from agent.llm.context_budget import ContextBudgetManager
from agent.llm.tool_translator import ToolSchemaTranslator, ToolCallFallback

__all__ = [
    "ContextBudgetManager",
    "ToolSchemaTranslator",
    "ToolCallFallback",
]
