"""Redact secrets from log records before they reach any handler.

Why this exists
---------------
On 2026-08-07 an audit found the live Telegram bot token in plaintext on
248,596 lines of ``/data/neomind/agent.log*``. Nothing in NeoMind logged it:
``httpx`` logs every request line at INFO level, and the Telegram polling URL
carries the token in its path::

    HTTP Request: POST https://api.telegram.org/bot<TOKEN>/getUpdates "HTTP/1.1 200 OK"

``agent/integration/telegram_bot.py`` calls ``logging.basicConfig(level=INFO)``,
supervisord captures stdout, and the bot polls every ~10s — so the token was
written roughly six times a minute, forever.

Two layers are installed here, deliberately:

1. Noisy HTTP client loggers drop to WARNING. This removes the known source.
2. A redaction filter sits on every root handler. This survives the next
   library that decides to log a URL. Silencing one logger fixes today's leak;
   the filter is what makes it not come back through a different door.

The filter is attached to *handlers*, not to loggers: a filter on a logger is
not consulted for records propagated up from child loggers, which is exactly
the path ``httpx`` records travel.
"""

from __future__ import annotations

import logging
import re
from typing import Iterable, List, Pattern, Tuple

# Loggers that emit full request URLs at INFO. Their WARNING+ records still
# flow, so real failures remain visible.
NOISY_HTTP_LOGGERS = (
    "httpx",
    "httpcore",
    "urllib3",
    "telegram.request",
    "telegram.bot",
)

# (pattern, replacement) — each keeps enough non-secret context to stay
# debuggable. A redacted line must still tell you which endpoint was called.
SECRET_PATTERNS: Tuple[Tuple[Pattern[str], str], ...] = (
    # Telegram bot token inside an API URL: .../bot123456789:AAH...xyz/getUpdates
    (re.compile(r"/bot\d{6,12}:[A-Za-z0-9_-]{20,}"), "/bot[REDACTED_TG_TOKEN]"),
    # Bare Telegram bot token anywhere else (env dumps, tracebacks, reprs).
    (re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b"), "[REDACTED_TG_TOKEN]"),
    # Vendor-style API keys (DeepSeek, OpenAI-compatible, Anthropic, ...).
    (re.compile(r"\b(sk-[A-Za-z0-9_-]{16,}|sk_[A-Za-z0-9_-]{16,})"), "[REDACTED_API_KEY]"),
    # Secrets passed as query parameters.
    (
        re.compile(
            r"([?&](?:api[_-]?key|access[_-]?token|token|key|secret)=)[^&\s\"']+",
            re.IGNORECASE,
        ),
        r"\1[REDACTED]",
    ),
    # Authorization headers, however they were stringified.
    (
        re.compile(r"(Authorization\W{0,4}\s*(?:Bearer|Basic)\s+)\S+", re.IGNORECASE),
        r"\1[REDACTED]",
    ),
)


def redact_secrets(text: str) -> str:
    """Return ``text`` with every known secret shape replaced.

    Safe on non-strings and never raises: redaction failing closed (dropping a
    log line) is worse than the line being written, but redaction raising would
    break logging itself.
    """
    if not isinstance(text, str) or not text:
        return text
    try:
        for pattern, replacement in SECRET_PATTERNS:
            text = pattern.sub(replacement, text)
    except Exception:  # pragma: no cover — defensive; logging must not break
        return text
    return text


class SecretRedactingFilter(logging.Filter):
    """Rewrite log records in place so no handler ever sees a secret.

    Formats the record once, and only rewrites when the formatted text actually
    changed — so the common case (no secret present) leaves ``record.args``
    untouched and costs one regex sweep.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        try:
            original = record.getMessage()
        except Exception:  # pragma: no cover — malformed record; let it through
            return True

        redacted = redact_secrets(original)
        if redacted != original:
            # Collapse msg+args into the already-formatted, redacted string;
            # otherwise the handler would re-apply args and re-expose the secret.
            record.msg = redacted
            record.args = ()

        return True


def install_secret_redaction(
    quiet_http_loggers: Iterable[str] = NOISY_HTTP_LOGGERS,
    logger: logging.Logger | None = None,
) -> List[logging.Handler]:
    """Install redaction on ``logger`` (default: root) and quiet HTTP clients.

    Idempotent: calling it twice does not stack duplicate filters. Returns the
    handlers that received the filter, so callers can assert on it in tests.

    Call this *after* ``logging.basicConfig()`` / any handler setup. Handlers
    added later are not covered — call again if you add one.
    """
    target = logger if logger is not None else logging.getLogger()

    for name in quiet_http_loggers:
        # WARNING keeps genuine transport failures visible while dropping the
        # per-request INFO lines that carried the token.
        logging.getLogger(name).setLevel(logging.WARNING)

    patched: List[logging.Handler] = []
    for handler in target.handlers:
        if any(isinstance(f, SecretRedactingFilter) for f in handler.filters):
            patched.append(handler)
            continue
        handler.addFilter(SecretRedactingFilter())
        patched.append(handler)

    return patched
