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
            'task': [
                (r"create task (.+)$", "/task create {match}", 0.9),
                (r"add task (.+)$", "/task create {match}", 0.9),
                (r"list tasks$", "/task list", 0.9),
                (r"show tasks$", "/task list", 0.9),
                (r"what tasks are pending\??$", "/task list todo", 0.8),
                (r"update task (\w+) to (\w+)$", "/task update {match} {content}", 0.8),
                (r"mark task (\w+) as (\w+)$", "/task update {match} {content}", 0.8),
                (r"delete task (\w+)$", "/task delete {match}", 0.9),
                (r"remove task (\w+)$", "/task delete {match}", 0.9),
                (r"clear all tasks$", "/task clear", 0.9),
            ],
            'plan': [
                (r"create plan for (.+)$", "/plan {match}", 0.9),
                (r"generate plan for (.+)$", "/plan {match}", 0.9),
                (r"make a plan to (.+)$", "/plan {match}", 0.8),
                (r"how can I (.+)$", "/plan {match}", 0.7),
                (r"list plans$", "/plan list", 0.9),
                (r"show plans$", "/plan list", 0.9),
                (r"what plans are there\??$", "/plan list", 0.8),
                (r"delete plan (\w+)$", "/plan delete {match}", 0.9),
                (r"show plan (\w+)$", "/plan show {match}", 0.9),
            ],
            'execute': [
                (r"execute plan (\w+)$", "/execute {match}", 0.9),
                (r"run plan (\w+)$", "/execute {match}", 0.9),
                (r"start plan (\w+)$", "/execute {match}", 0.8),
                (r"continue plan (\w+)$", "/execute {match}", 0.8),
                (r"next step for plan (\w+)$", "/execute {match}", 0.8),
            ],
            'switch': [
                (r"switch model to (.+)$", "/switch {match}", 0.9),
                (r"use model (.+)$", "/switch {match}", 0.9),
                (r"change model to (.+)$", "/switch {match}", 0.8),
                (r"set model to (.+)$", "/switch {match}", 0.8),
            ],
            'summarize': [
                (r"summarize (.+)$", "/summarize {match}", 0.9),
                (r"brief summary of (.+)$", "/summarize {match}", 0.8),
                (r"sum up (.+)$", "/summarize {match}", 0.7),
            ],
            'translate': [
                (r"translate (.+?) to (.+)$", "/translate {match} to {content}", 0.9),
                (r"translate (.+)$", "/translate {match}", 0.8),
                (r"how do you say (.+?) in (.+)$", "/translate {match} to {content}", 0.8),
            ],
            'generate': [
                (r"generate (.+)$", "/generate {match}", 0.9),
                (r"create (.+)$", "/generate {match}", 0.8),
                (r"write (.+)$", "/generate {match}", 0.8),
            ],
            'reason': [
                (r"reason about (.+)$", "/reason {match}", 0.9),
                (r"solve (.+)$", "/reason {match}", 0.8),
                (r"think through (.+)$", "/reason {match}", 0.7),
            ],
            'debug': [
                (r"debug (.+\.\w+)$", "/debug {match}", 0.9),
                (r"find bugs in (.+)$", "/debug {match}", 0.8),
                (r"fix errors in (.+)$", "/debug {match}", 0.8),
            ],
            'explain': [
                (r"explain (.+\.\w+)$", "/explain {match}", 0.9),
                (r"explain code in (.+)$", "/explain {match}", 0.8),
                (r"what does this code do\?? (.+)$", "/explain {match}", 0.7),
            ],
            'refactor': [
                (r"refactor (.+\.\w+)$", "/refactor {match}", 0.9),
                (r"improve code in (.+)$", "/refactor {match}", 0.8),
                (r"clean up code in (.+)$", "/refactor {match}", 0.7),
            ],
            'grep': [
                (r"search for (.+) in files$", "/grep {match}", 0.9),
                (r"find text (.+) in code$", "/grep {match}", 0.8),
                (r"grep for (.+)$", "/grep {match}", 0.9),
            ],
            'find': [
                (r"find files matching (.+)$", "/find {match}", 0.9),
                (r"locate files with pattern (.+)$", "/find {match}", 0.8),
                (r"search for files named (.+)$", "/find {match}", 0.8),
            ],
            'clear': [
                (r"clear history$", "/clear", 0.9),
                (r"clear chat$", "/clear", 0.9),
                (r"reset conversation$", "/clear", 0.8),
            ],
            'history': [
                (r"show history$", "/history", 0.9),
                (r"view history$", "/history", 0.9),
                (r"chat history$", "/history", 0.8),
            ],
            'think': [
                (r"toggle thinking$", "/think", 0.9),
                (r"enable thinking mode$", "/think", 0.8),
                (r"disable thinking mode$", "/think", 0.8),
            ],
            'quit': [
                (r"quit$", "/quit", 0.9),
                (r"exit$", "/exit", 0.9),
                (r"bye$", "/quit", 0.7),
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
                   'scan', 'help', 'models', 'undo', 'show', 'list', 'open',
                   'task', 'create', 'update', 'delete', 'clear', 'add', 'remove', 'mark',
                   'plan', 'execute', 'goal', 'generate', 'run', 'start', 'continue', 'next',
                   'switch', 'model', 'use', 'change', 'set',
                   'summarize', 'translate', 'reason', 'debug', 'explain', 'refactor', 'grep',
                   'brief', 'summary', 'solve', 'bugs', 'errors', 'improve', 'clean', 'locate',
                   'history', 'think', 'quit', 'exit', 'reset', 'toggle', 'enable', 'disable', 'bye']
        return any(keyword in text.lower() for keyword in keywords)