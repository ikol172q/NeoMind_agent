"""NeoMind Structured Logging — JSON-format logs for observability.

Provides structured logging that outputs JSON lines for machine parsing
while keeping human-readable console output.

No external dependencies — stdlib only.
"""

import json
import logging
import logging.handlers
from pathlib import Path
from datetime import datetime, timezone
from contextlib import contextmanager
from typing import Optional, Dict, Any


class StructuredFormatter(logging.Formatter):
    """Format log records as JSON with structured fields."""

    def format(self, record: logging.LogRecord) -> str:
        """Convert log record to JSON line.

        Includes:
        - timestamp: ISO 8601 UTC
        - level: DEBUG, INFO, WARNING, ERROR, CRITICAL
        - module: logger name
        - message: the log message
        - extra: any additional context fields
        """
        log_data = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "module": record.name,
            "message": record.getMessage(),
        }

        # Extract any extra fields added via LogContext
        if hasattr(record, "extra_fields"):
            log_data.update(record.extra_fields)

        return json.dumps(log_data, default=str)


class HumanFormatter(logging.Formatter):
    """Format log records as human-readable text."""

    def format(self, record: logging.LogRecord) -> str:
        """Format: [LEVEL] module: message"""
        base = f"[{record.levelname:8}] {record.name}: {record.getMessage()}"

        # Append extra fields if present
        if hasattr(record, "extra_fields"):
            extras = " | ".join(
                f"{k}={v}" for k, v in record.extra_fields.items()
            )
            base += f" | {extras}"

        return base


def setup_logging(
    name: str,
    level: str = "INFO",
    json_file: Optional[Path] = None,
) -> logging.Logger:
    """Configure dual logging output: console (human) + JSON file.

    Args:
        name: Logger name
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_file: Path to write JSON logs. If None, only console logging.

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper()))

    # Remove existing handlers to avoid duplication
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Console handler — human readable
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(HumanFormatter())
    console_handler.setLevel(getattr(logging, level.upper()))
    logger.addHandler(console_handler)

    # JSON file handler — machine readable
    if json_file:
        json_file.parent.mkdir(parents=True, exist_ok=True)
        json_handler = logging.FileHandler(json_file)
        json_handler.setFormatter(StructuredFormatter())
        json_handler.setLevel(getattr(logging, level.upper()))
        logger.addHandler(json_handler)

    return logger


class LogContext:
    """Context manager for adding structured context to log records.

    Usage:
        with LogContext(request_id="req_123", user_id="user_456"):
            logger.info("Processing request")  # Will include request_id and user_id
    """

    _context_stack = []

    def __init__(self, **kwargs):
        """Initialize with context fields (mode, request_id, user_id, etc.)."""
        self.context = kwargs

    def __enter__(self):
        """Push context onto stack."""
        LogContext._context_stack.append(self.context)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Pop context from stack."""
        if LogContext._context_stack:
            LogContext._context_stack.pop()

    @classmethod
    def get_current(cls) -> Dict[str, Any]:
        """Get merged context from stack."""
        merged = {}
        for ctx in cls._context_stack:
            merged.update(ctx)
        return merged

    @classmethod
    def inject_into_record(cls, record: logging.LogRecord) -> None:
        """Inject current context into a log record."""
        record.extra_fields = cls.get_current()


# Monkey-patch logging to inject context
_original_makeRecord = logging.Logger.makeRecord


def _makeRecord_with_context(*args, **kwargs):
    """Wrapper to inject LogContext into records."""
    record = _original_makeRecord(*args, **kwargs)
    LogContext.inject_into_record(record)
    return record


logging.Logger.makeRecord = _makeRecord_with_context


def log_llm_call(
    logger: logging.Logger,
    model: str,
    purpose: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: float,
    cost: float,
) -> None:
    """Log an LLM API call with structured fields.

    Args:
        logger: Logger instance
        model: Model name (e.g., "deepseek-v4-flash")
        purpose: Purpose (user_chat, evolution, reflection, learning)
        input_tokens: Input token count
        output_tokens: Output token count
        latency_ms: Response latency in milliseconds
        cost: Cost in USD
    """
    with LogContext(
        event_type="llm_call",
        model=model,
        purpose=purpose,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=round(latency_ms, 2),
        cost_usd=round(cost, 6),
        total_tokens=input_tokens + output_tokens,
    ):
        logger.info(
            f"LLM call: {model} for {purpose} "
            f"({input_tokens}→{output_tokens} tokens, {latency_ms:.1f}ms, ${cost:.6f})"
        )


def log_evolution_event(
    logger: logging.Logger,
    event_type: str,
    module: str,
    detail: str,
    metrics: Optional[Dict[str, Any]] = None,
) -> None:
    """Log an agent evolution event (learning, behavior drift, etc.).

    Args:
        logger: Logger instance
        event_type: Type of event (learning, drift, recovery, anomaly, etc.)
        module: Module where event occurred
        detail: Human-readable description
        metrics: Optional metrics dict (accuracy, confidence, recovery_time, etc.)
    """
    context = {
        "event_type": f"evolution_{event_type}",
        "module": module,
    }
    if metrics:
        context.update(metrics)

    with LogContext(**context):
        logger.info(f"Evolution: {event_type} in {module}: {detail}")
