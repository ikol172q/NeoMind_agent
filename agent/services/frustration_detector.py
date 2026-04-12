"""
Frustration Signal Detection — Detect negative keywords indicating user frustration.

Monitors user messages for signals of dissatisfaction:
- Explicit corrections ("that's wrong", "no not that")
- Frustration expressions ("this is broken", "doesn't work", "waste of time")
- Repeated requests ("I already told you", "again")

When detected, adjusts agent behavior:
- More careful, less assumptions
- Acknowledge the issue explicitly
- Offer to change approach
"""

import re
from typing import List, Dict, Tuple

# Negative signal patterns with severity
FRUSTRATION_PATTERNS = {
    # Corrections
    'explicit_correction': {
        'patterns': [
            r"\bthat'?s?\s+wrong\b", r"\bno,?\s+not\s+that\b",
            r"\bincorrect\b", r"\bthat'?s?\s+not\s+what\s+I\b",
            r"\bwrong\s+(file|answer|approach|direction)\b",
        ],
        'severity': 'correction',
        'signal': 'User is correcting an error',
    },
    'frustration': {
        'patterns': [
            r"\bdoesn'?t\s+work\b", r"\bnot\s+working\b",
            r"\bstill\s+(broken|wrong|failing)\b",
            r"\bwaste\s+of\s+time\b", r"\buseless\b",
            r"\b(this|that)\s+is\s+(terrible|awful|horrible|bad)\b",
            r"\bfed\s+up\b", r"\bgive\s+up\b",
        ],
        'severity': 'frustrated',
        'signal': 'User is expressing frustration',
    },
    'repetition': {
        'patterns': [
            r"\bI\s+(already|just)\s+told\s+you\b",
            r"\bagain\??\s*$", r"\bfor\s+the\s+\w+\s+time\b",
            r"\bhow\s+many\s+times\b", r"\brepeat(ing)?\b",
            r"\bstop\s+(doing|saying|repeating)\b",
        ],
        'severity': 'repetition',
        'signal': 'User is repeating themselves',
    },
    'confusion': {
        'patterns': [
            r"\bI\s+don'?t\s+understand\b",
            r"\bwhat\s+are\s+you\s+(doing|talking\s+about)\b",
            r"\bmakes?\s+no\s+sense\b", r"\bconfus(ed|ing)\b",
        ],
        'severity': 'confused',
        'signal': 'User is confused by the response',
    },
    # Chinese patterns
    'zh_correction': {
        'patterns': [
            r'不对', r'错了', r'不是这样', r'搞错了',
            r'你说得不对', r'这是错的',
        ],
        'severity': 'correction',
        'signal': 'User is correcting (Chinese)',
    },
    'zh_frustration': {
        'patterns': [
            r'不行', r'没用', r'还是不对', r'烦死了',
            r'浪费时间', r'太慢了', r'算了',
        ],
        'severity': 'frustrated',
        'signal': 'User is frustrated (Chinese)',
    },
}


def detect_frustration(message: str) -> List[Dict[str, str]]:
    """Detect frustration signals in a user message.

    Returns list of {category, severity, signal} for each match.
    """
    if not message:
        return []

    findings = []
    message_lower = message.lower()

    for category, info in FRUSTRATION_PATTERNS.items():
        for pattern in info['patterns']:
            if re.search(pattern, message_lower if not pattern[0].isascii() or pattern[0] == '\\' else message,
                         re.IGNORECASE):
                findings.append({
                    'category': category,
                    'severity': info['severity'],
                    'signal': info['signal'],
                })
                break  # One match per category is enough

    return findings


def get_frustration_guidance(findings: List[Dict[str, str]]) -> str:
    """Generate guidance text for the agent based on detected frustration.

    This can be injected into the system prompt or used internally.
    """
    if not findings:
        return ""

    severities = {f['severity'] for f in findings}

    parts = ["[User Signal Detected] "]

    if 'frustrated' in severities:
        parts.append(
            "The user appears frustrated. Be more careful and precise. "
            "Acknowledge the issue directly. Offer to change approach."
        )
    elif 'correction' in severities:
        parts.append(
            "The user has corrected you. Accept the correction gracefully. "
            "Don't repeat the mistake. Adjust your approach."
        )
    elif 'repetition' in severities:
        parts.append(
            "The user is repeating a request. Pay close attention to what "
            "was already asked. Don't make assumptions."
        )
    elif 'confused' in severities:
        parts.append(
            "The user seems confused. Explain more clearly. "
            "Use simpler terms. Check if they want a different approach."
        )

    return " ".join(parts)
