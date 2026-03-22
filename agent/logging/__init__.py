"""NeoMind Unified Logging System

Provides centralized logging with PII sanitization for all operations.

Example usage:
    from agent.logging import get_unified_logger

    logger = get_unified_logger()
    logger.log_llm_call("gpt-4", 100, 50, 1200.5, mode="chat")
    logger.log_command("ls -la", 0, 45.2, mode="cli")
    logger.log_error("FileNotFound", "file.txt not found", severity="warning")

    # Query logs
    today_stats = logger.get_daily_stats()
    week_stats = logger.get_weekly_stats()
    results = logger.query(log_type="error", limit=10)
    matches = logger.search("API", limit=5)
"""

from .unified_logger import UnifiedLogger, get_unified_logger
from .pii_sanitizer import PIISanitizer

__all__ = [
    'UnifiedLogger',
    'get_unified_logger',
    'PIISanitizer',
]
