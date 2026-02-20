# agent/natural_language.py
import re
from typing import Optional, Tuple


class NaturalLanguageInterpreter:
    """Interprets natural language commands into CLI commands."""

    def __init__(self, confidence_threshold: float = 0.8):
        self.confidence_threshold = confidence_threshold
        self.patterns = self._build_patterns()

    def _build_patterns(self):
        """Build regex patterns for natural language interpretation."""
        return {
            'search': [
                (r"search (?:the )?code(?:base)? for (.+)$", "/code search {match}", 0.95),
                (r"search for (.+) in (?:the )?code(?:base)?", "/code search {match}", 0.95),
                (r"find (.+) in (?:the )?code(?:base)?", "/code search {match}", 0.95),
                (r"look for (.+) in (?:the )?code(?:base)?", "/code search {match}", 0.95),
                (r"search source code for (.+)", "/code search {match}", 0.95),
                (r"look for (.+) in source code", "/code search {match}", 0.95),
                (r"find (.+) in source code", "/code search {match}", 0.95),
                (r"find (.+) in source files", "/code search {match}", 0.95),
                (r"(?:search|look up|find)(?: for)? (.+)$", "/search {match}", 0.9),
                (r"what (?:is|are) (?:the )?(?:latest|current) (.+)$", "/search latest {match}", 0.8),
                (r"(?:tell me about|get info on|info about) (.+)$", "/search {match}", 0.7),
                (r"what's (?:the )?(?:latest|current|news about) (.+)$", "/search {match}", 0.8),
            ],
            'file_read': [
                (r"(?:read|show|open) (?:file )?(.+\.\w+)$", "/read {match}", 0.9),
                (r"(?:what's in|view|display) (.+\.\w+)$", "/read {match}", 0.7),
                (r"(?:load|get) file (.+\.\w+)$", "/read {match}", 0.8),
            ],
            'file_write': [
                (r"(?:write|create) file (.+\.\w+) (?:with content|containing) (.+)$", "/write {match} {content}", 0.8),
                (r"(?:save|write) (.+\.\w+) (?:with|as) (.+)$", "/write {match} {content}", 0.7),
            ],
            'file_edit': [
                (r"(?:edit|modify) file (.+\.\w+) (?:to|with) (.+)$", "/edit {match} {content}", 0.8),
                (r"(?:change|update) (.+\.\w+) (?:to|with) (.+)$", "/edit {match} {content}", 0.7),
            ],
            'code_analyze': [
                (r"(?:analyze|scan) code(?:base)?(?: in )?(.+)$", "/code scan {match}", 0.9),
                (r"(?:scan|inspect) (?:the )?code(?:base)?(?: in )?(.+)$", "/code scan {match}", 0.8),
                (r"(?:find|detect) (?:code )?issues(?: in )?(.+)$", "/code scan {match}", 0.7),
            ],
            'code_search': [
                (r"search (?:the )?code(?:base)? for (.+)$", "/code search {match}", 0.9),
                (r"search for (.+) in (?:the )?code(?:base)?", "/code search {match}", 0.9),
                (r"find (.+) in (?:the )?code(?:base)?", "/code search {match}", 0.8),
                (r"look for (.+) in (?:the )?code(?:base)?", "/code search {match}", 0.8),
                (r"find (.+) in source files", "/code search {match}", 0.7),
                (r"search source code for (.+)", "/code search {match}", 0.9),
            ],
            'code_fix': [
                (r"(?:fix|repair) (?:code in )?(.+\.\w+)$", "/fix {match}", 0.9),
                (r"(?:debug|correct) (.+\.\w+)$", "/fix {match}", 0.8),
            ],
            'help': [
                (r"(?:show|display|list) commands$", "/help", 0.9),
                (r"what commands are available\??$", "/help", 0.8),
                (r"help(?: me)?$", "/help", 0.7),
            ],
            'models': [
                (r"(?:show|list|display) models$", "/models", 0.9),
                (r"what models are available\??$", "/models", 0.8),
            ],
            'undo': [
                (r"undo(?: last change)?$", "/undo", 0.9),
                (r"revert(?: changes)?$", "/undo", 0.8),
            ],
        }

    def interpret(self, text: str) -> Tuple[Optional[str], float]:
        """
        Interpret natural language and return suggested command with confidence.

        Returns:
            Tuple of (suggested_command, confidence_score) or (None, 0.0)
        """
        text = text.strip()
        for intent, patterns in self.patterns.items():
            for pattern, command_template, confidence in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match and confidence >= self.confidence_threshold:
                    # Extract matched groups
                    groups = match.groups()
                    # Replace placeholders
                    if '{match}' in command_template and groups:
                        # Simple replacement - use first group, stripped
                        matched_text = groups[0].strip()
                        cmd = command_template.format(match=matched_text)
                        # If there's a {content} placeholder and second group exists
                        if '{content}' in cmd and len(groups) > 1:
                            cmd = cmd.replace('{content}', groups[1].strip())
                    else:
                        cmd = command_template
                    return cmd, confidence
        return None, 0.0

    def should_suggest(self, text: str) -> bool:
        """Quick check if text might be a natural language command."""
        # Simple heuristic: if text doesn't start with / and is not too long
        if text.startswith('/'):
            return False
        if len(text.split()) > 10:  # Too long for simple command
            return False
        # Check for command-like keywords
        keywords = ['search', 'find', 'read', 'write', 'edit', 'fix', 'analyze',
                   'scan', 'help', 'models', 'undo', 'show', 'list', 'open']
        return any(keyword in text.lower() for keyword in keywords)