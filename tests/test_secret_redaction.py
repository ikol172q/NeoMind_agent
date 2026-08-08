"""Regression tests for log secret redaction.

Anchored to a real incident: on 2026-08-07 the live Telegram bot token was
found on 248,596 lines of /data/neomind/agent.log*, written by httpx's INFO
request logging of the getUpdates URL. These tests fail against the pre-fix
code and are the reason the leak cannot silently return.
"""

import io
import logging
import unittest

from agent.logging.pii_sanitizer import PIISanitizer
from agent.logging.secret_redaction import (
    NOISY_HTTP_LOGGERS,
    SecretRedactingFilter,
    install_secret_redaction,
    redact_secrets,
)

# Structurally valid but fabricated — never a real credential. Assembled at
# runtime on purpose: a literal token-shaped string in the file would trip
# gitleaks and the repo's pre-commit hook forever, on every unrelated commit.
FAKE_TOKEN = "123456789" + ":" + "AAH" + "fake" * 8 + "1"
TELEGRAM_LOG_LINE = (
    f'HTTP Request: POST https://api.telegram.org/bot{FAKE_TOKEN}/getUpdates '
    f'"HTTP/1.1 200 OK"'
)


class TestRedactSecrets(unittest.TestCase):
    def test_redacts_telegram_token_in_url(self):
        out = redact_secrets(TELEGRAM_LOG_LINE)
        self.assertNotIn(FAKE_TOKEN, out)
        self.assertIn("[REDACTED_TG_TOKEN]", out)

    def test_keeps_endpoint_context(self):
        """A redacted line must still say which endpoint was called."""
        out = redact_secrets(TELEGRAM_LOG_LINE)
        self.assertIn("getUpdates", out)
        self.assertIn("api.telegram.org", out)
        self.assertIn("200 OK", out)

    def test_redacts_bare_token(self):
        out = redact_secrets(f"TELEGRAM_BOT_TOKEN={FAKE_TOKEN}")
        self.assertNotIn(FAKE_TOKEN, out)

    def test_redacts_vendor_api_keys(self):
        out = redact_secrets("Using key sk-abcdefghijklmnopqrstuvwxyz123456")
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz123456", out)
        self.assertIn("[REDACTED_API_KEY]", out)

    def test_redacts_query_param_secrets(self):
        out = redact_secrets("GET /v1/models?api_key=supersecretvalue123&limit=10")
        self.assertNotIn("supersecretvalue123", out)
        self.assertIn("limit=10", out)

    def test_redacts_authorization_header(self):
        out = redact_secrets("headers={'Authorization': 'Bearer abc123def456ghi'}")
        self.assertNotIn("abc123def456ghi", out)

    def test_leaves_ordinary_text_untouched(self):
        text = "Fetched 12 candles for AAPL in 0.42s (ratio 3:1)"
        self.assertEqual(redact_secrets(text), text)

    def test_non_string_passthrough(self):
        self.assertEqual(redact_secrets(None), None)
        self.assertEqual(redact_secrets(42), 42)


class TestSecretRedactingFilter(unittest.TestCase):
    def _record(self, msg, args=()):
        return logging.LogRecord(
            name="httpx", level=logging.INFO, pathname=__file__, lineno=1,
            msg=msg, args=args, exc_info=None,
        )

    def test_filter_rewrites_record(self):
        record = self._record(TELEGRAM_LOG_LINE)
        self.assertTrue(SecretRedactingFilter().filter(record))
        self.assertNotIn(FAKE_TOKEN, record.getMessage())

    def test_filter_handles_lazy_args(self):
        """The token arriving via %-args must not survive re-formatting."""
        record = self._record("HTTP Request: POST %s", (f"https://api.telegram.org/bot{FAKE_TOKEN}/getUpdates",))
        self.assertTrue(SecretRedactingFilter().filter(record))
        self.assertNotIn(FAKE_TOKEN, record.getMessage())

    def test_filter_returns_true_always(self):
        """Redaction must never drop a log line."""
        record = self._record("nothing secret here")
        self.assertTrue(SecretRedactingFilter().filter(record))


class TestInstallSecretRedaction(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger("test.secret.install")
        self.logger.handlers.clear()
        self.logger.propagate = False
        self.stream = io.StringIO()
        handler = logging.StreamHandler(self.stream)
        handler.setFormatter(logging.Formatter("%(message)s"))
        self.logger.addHandler(handler)
        self.logger.setLevel(logging.INFO)

    def tearDown(self):
        self.logger.handlers.clear()

    def test_handler_output_is_redacted(self):
        install_secret_redaction(quiet_http_loggers=(), logger=self.logger)
        self.logger.info(TELEGRAM_LOG_LINE)
        self.assertNotIn(FAKE_TOKEN, self.stream.getvalue())
        self.assertIn("[REDACTED_TG_TOKEN]", self.stream.getvalue())

    def test_idempotent(self):
        install_secret_redaction(quiet_http_loggers=(), logger=self.logger)
        install_secret_redaction(quiet_http_loggers=(), logger=self.logger)
        filters = self.logger.handlers[0].filters
        secret_filters = [f for f in filters if isinstance(f, SecretRedactingFilter)]
        self.assertEqual(len(secret_filters), 1)

    def test_quiets_http_loggers(self):
        install_secret_redaction(logger=self.logger)
        for name in NOISY_HTTP_LOGGERS:
            self.assertGreaterEqual(logging.getLogger(name).level, logging.WARNING)

    def test_child_logger_records_are_redacted(self):
        """Records propagated from a child logger must hit the filter too —
        a filter installed on the logger (not its handlers) would miss these,
        which is exactly the path httpx records travel."""
        install_secret_redaction(quiet_http_loggers=(), logger=self.logger)
        child = logging.getLogger("test.secret.install.child")
        child.setLevel(logging.INFO)
        child.info(TELEGRAM_LOG_LINE)
        self.assertNotIn(FAKE_TOKEN, self.stream.getvalue())


class TestPIISanitizerCoversTelegramToken(unittest.TestCase):
    def test_sanitizer_now_matches_bot_token(self):
        """The pre-existing 'api_key' pattern requires a vendor prefix
        (sk-/token_/...), which a Telegram token does not have."""
        out = PIISanitizer(mode="strict").sanitize(f"token is {FAKE_TOKEN}")
        self.assertNotIn(FAKE_TOKEN, out)
        self.assertIn("[REDACTED_TG_TOKEN]", out)


if __name__ == "__main__":
    unittest.main()
