"""PII Sanitizer for NeoMind

Detects and masks sensitive information before logging:
- Phone numbers (US, CN, international)
- Email addresses
- Credit card numbers
- SSN / ID numbers
- API keys (sk-*, key_*, etc.)
- Passwords in URLs or config
- IP addresses (optional)

Two modes:
- strict: Replace all PII with [REDACTED_TYPE]
- normal: Only warn, don't replace
"""

import re
from typing import Dict, List, Tuple, Any


class PIISanitizer:
    """Sanitize PII from logs and text."""

    # Compiled regex patterns for each PII type
    PATTERNS = {
        'email': re.compile(
            r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
            re.IGNORECASE
        ),
        'phone_us': re.compile(
            r'\b(?:\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}\b'
        ),
        'phone_cn': re.compile(
            r'(?:\+?86[-.\s]?)?1[3-9]\d[-.\s]?\d{3}[-.\s]?\d{4}|1[3-9]\d{9}'
        ),
        'phone_intl': re.compile(
            r'\+[0-9]{1,3}[-.\s]?(?:[0-9][-.\s]?){5,13}[0-9]'
        ),
        'credit_card': re.compile(
            r'\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12})\b'
        ),
        'ssn': re.compile(
            r'\b\d{3}[-.]?\d{2}[-.]?\d{4}\b'
        ),
        'api_key': re.compile(
            r'(?:sk_|sk-|key_|token_|api_|secret_|apikey|api-key)[A-Za-z0-9_\-]{8,}',
            re.IGNORECASE
        ),
        'password_in_url': re.compile(
            r'://[^:/@\s]+:([^@\s]+)@|://[^\s/:]+:[^\s@]+@'
        ),
        'ipv4': re.compile(
            r'\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b'
        ),
    }

    # Redaction tokens by PII type
    REDACTION_TOKENS = {
        'email': '[REDACTED_EMAIL]',
        'phone_us': '[REDACTED_PHONE]',
        'phone_cn': '[REDACTED_PHONE]',
        'phone_intl': '[REDACTED_PHONE]',
        'credit_card': '[REDACTED_CC]',
        'ssn': '[REDACTED_SSN]',
        'api_key': '[REDACTED_KEY]',
        'password_in_url': '[REDACTED_PASSWORD]',
        'ipv4': '[REDACTED_IP]',
    }

    def __init__(self, mode: str = "strict"):
        """
        Initialize sanitizer.

        Args:
            mode: "strict" (replace PII) or "normal" (warn only)
        """
        self.mode = mode

    def sanitize(self, text: str) -> str:
        """Replace PII in text with redaction tokens.

        Args:
            text: Text to sanitize

        Returns:
            Sanitized text with PII replaced
        """
        if not isinstance(text, str):
            return text

        if self.mode != "strict":
            return text

        result = text
        for pii_type, pattern in self.PATTERNS.items():
            token = self.REDACTION_TOKENS.get(pii_type, '[REDACTED]')
            result = pattern.sub(token, result)

        return result

    def sanitize_dict(self, d: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively sanitize all string values in a dict.

        Args:
            d: Dictionary to sanitize

        Returns:
            New dictionary with sanitized string values
        """
        if not isinstance(d, dict):
            return d

        result = {}
        for key, value in d.items():
            if isinstance(value, str):
                result[key] = self.sanitize(value)
            elif isinstance(value, dict):
                result[key] = self.sanitize_dict(value)
            elif isinstance(value, (list, tuple)):
                result[key] = [
                    self.sanitize_dict(v) if isinstance(v, dict)
                    else self.sanitize(v) if isinstance(v, str)
                    else v
                    for v in value
                ]
            else:
                result[key] = value

        return result

    def detect(self, text: str) -> List[Tuple[str, str]]:
        """Return list of (pii_type, match) found.

        Args:
            text: Text to scan

        Returns:
            List of tuples (pii_type, matched_text)
        """
        if not isinstance(text, str):
            return []

        findings = []
        for pii_type, pattern in self.PATTERNS.items():
            matches = pattern.findall(text)
            for match in matches:
                findings.append((pii_type, match))

        return findings

    def scan_message(self, text: str) -> Tuple[bool, List[str]]:
        """Check if message contains PII.

        Args:
            text: Text to scan

        Returns:
            Tuple of (has_pii: bool, warnings: List[str])
        """
        if not isinstance(text, str):
            return False, []

        findings = self.detect(text)
        has_pii = len(findings) > 0
        warnings = []

        if has_pii:
            pii_types = {}
            for pii_type, match in findings:
                pii_types[pii_type] = pii_types.get(pii_type, 0) + 1

            for pii_type, count in pii_types.items():
                warnings.append(f"Found {count} potential {pii_type}")

        return has_pii, warnings

    def get_stats(self, text: str) -> Dict[str, int]:
        """Get statistics about PII found in text.

        Args:
            text: Text to analyze

        Returns:
            Dictionary mapping PII type to count
        """
        findings = self.detect(text)
        stats = {}
        for pii_type, _ in findings:
            stats[pii_type] = stats.get(pii_type, 0) + 1
        return stats
