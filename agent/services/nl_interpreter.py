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
                (r"(?:search|look up|find)(?: for)? (.+)$", "/search {match}", 0.9),
                (r"what (?:is|are) (?:the )?(?:latest|current) (.+)$", "/search latest {match}", 0.8),
                (r"(?:tell me about|get info on|info about) (.+)$", "/search {match}", 0.7),
                (r"what's (?:the )?(?:latest|current(?: news about)?|news about) (.+)$", "/search {match}", 0.8),
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
                (r"(?:analyze|scan) code(?:base)?(?: in )?(.+)$", "/code scan {match}", 0.95),
                (r"(?:scan|inspect) (?:the )?code(?:base)?(?: in )?(.+)$", "/code scan {match}", 0.9),
                (r"(?:find|detect) (?:code )?issues(?: in )?(.+)$", "/code scan {match}", 0.95),
            ],
            'code_search': [
                (r"search (?:the )?code(?:base)? for (.+)$", "/code search {match}", 0.95),
                (r"search for (.+) in (?:the )?code(?:base)?", "/code search {match}", 0.95),
                (r"find (.+) in (?:the )?code(?:base)?", "/code search {match}", 0.95),
                (r"look for (.+) in (?:the )?code(?:base)?", "/code search {match}", 0.95),
                (r"look for (.+) in source code", "/code search {match}", 0.95),
                (r"find (.+) in source code", "/code search {match}", 0.95),
                (r"find (.+) in source files", "/code search {match}", 0.7),
                (r"search source code for (.+)", "/code search {match}", 0.95),
            ],
            'code_fix': [
                (r"(?:fix|repair) (?:code in |errors in )?(.+\.\w+)$", "/fix {match}", 0.9),
                (r"(?:debug|correct) (?:errors in )?(.+\.\w+)$", "/fix {match}", 0.8),
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
                (r"debug (.+\.\w+)$", "/debug {match}", 0.7),
                (r"find bugs in (.+)$", "/debug {match}", 0.7),
                (r"fix errors in (.+)$", "/debug {match}", 0.7),
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
            # ── Web access patterns ─────────────────────────────────
            'web_read': [
                (r"(?:read|open|fetch|get|visit|访问|打开|读取)\s+(?:the\s+)?(?:webpage|page|site|url|网页|页面)?\s*(https?://[^\s]+)$", "/read {match}", 0.95),
                (r"(?:read|open|fetch|get|visit|访问|打开|读取)\s+(https?://[^\s]+)$", "/read {match}", 0.95),
                (r"(?:what's|what is)\s+(?:on|at|in)\s+(https?://[^\s]+)$", "/read {match}", 0.9),
                (r"(?:summarize|sum up|摘要|总结)\s+(?:the\s+)?(?:webpage|page|site|url|网页)?\s*(https?://[^\s]+)$", "/read {match}", 0.9),
                (r"帮我(?:读|看|打开|访问)\s*(https?://[^\s]+)$", "/read {match}", 0.95),
            ],
            'web_links': [
                (r"(?:show|list|get|extract|find|提取|列出)\s+(?:all\s+)?links?\s+(?:from|on|in|of)\s+(https?://[^\s]+)$", "/links {match}", 0.95),
                (r"(?:what|which)\s+links?\s+(?:are|does)\s+(?:on|in)\s+(https?://[^\s]+)$", "/links {match}", 0.9),
                (r"(?:这个|那个)?(?:页面|网页|网站)(?:里|上|中)?(?:有什么|有哪些)链接\s*(https?://[^\s]+)?$", "/links {match}", 0.9),
            ],
            'web_crawl': [
                (r"(?:crawl|scrape|spider|爬取|抓取)\s+(https?://[^\s]+)$", "/crawl {match}", 0.95),
                (r"(?:crawl|scrape|爬取|抓取)\s+(?:the\s+)?(?:site|website|网站)\s+(https?://[^\s]+)$", "/crawl {match}", 0.95),
                (r"(?:read|get|fetch)\s+(?:all|every|multiple)\s+pages?\s+(?:from|on|of)\s+(https?://[^\s]+)$", "/crawl {match}", 0.9),
                (r"(?:深度|全面)?(?:读取|阅读|爬取)\s+(?:整个|全部)?(?:网站|站点)\s*(https?://[^\s]+)$", "/crawl {match}", 0.95),
            ],
        }

    def _build_coding_patterns(self):
        """Build coding-specific patterns for natural language interpretation."""
        return {
            'file_read_coding': [
                (r"show me (?:the )?file (.+)$", "/read {match}", 0.9),
                (r"open (?:the )?file (.+)$", "/read {match}", 0.9),
                (r"display (?:the )?file (.+)$", "/read {match}", 0.8),
                (r"what's in (?:the )?file (.+)$", "/read {match}", 0.8),
                (r"look at (?:the )?file (.+)$", "/read {match}", 0.7),
                (r"view (?:the )?file (.+)$", "/read {match}", 0.7),
            ],
            'file_list_coding': [
                (r"list files(?: in (?:the )?project)?$", "/browse", 0.9),
                (r"show files(?: in (?:the )?project)?$", "/browse", 0.9),
                (r"what files are in (?:the )?project\??$", "/browse", 0.8),
                (r"directory structure$", "/browse", 0.8),
                (r"project structure$", "/browse", 0.8),
                (r"browse project$", "/browse", 0.9),
            ],
            'code_navigation': [
                (r"find definition of (.+)$", "/code search {match}", 0.95),
                (r"where is (.+) defined\??$", "/code search {match}", 0.95),
                (r"search for definition of (.+)$", "/code search {match}", 0.95),
                (r"go to (.+)$", "/code search {match}", 0.9),
            ],
            'code_analysis': [
                (r"analyze (?:the )?code(?:base)?$", "/code scan .", 0.9),
                (r"scan (?:the )?code(?:base)?$", "/code scan .", 0.9),
                (r"inspect (?:the )?code(?:base)?$", "/code scan .", 0.8),
                (r"review code$", "/code scan .", 0.7),
            ],
            'file_search': [
                (r"find file (?:named )?(.+)$", "/find {match}", 0.9),
                (r"search for file (?:named )?(.+)$", "/find {match}", 0.9),
                (r"locate file (?:named )?(.+)$", "/find {match}", 0.8),
                (r"where is file (?:named )?(.+)\??$", "/find {match}", 0.8),
            ],
        }

    def interpret(self, text: str, mode: str = "chat") -> Tuple[Optional[str], float]:
        """
        Interpret natural language and return suggested command with confidence.

        Args:
            text: User input text
            mode: Operation mode ("chat" or "coding")

        Returns:
            Tuple of (suggested_command, confidence_score) or (None, 0.0)
        """
        text = text.strip()

        # ── BUG-008 guard: reject conversational / polite inputs ────────
        # Inputs like "Show me the first 5 lines of main.py" are natural
        # language requests that must reach the LLM, not be rewritten into
        # a bare /read command.  The should_suggest() heuristic already
        # detects these; honour it here too.
        if not self.should_suggest(text):
            return None, 0.0

        # Adjust confidence threshold based on mode
        threshold = self.confidence_threshold
        if mode == "coding":
            # Lower threshold for coding mode (more aggressive interpretation)
            threshold = max(0.5, threshold - 0.1)  # At least 0.5

        best_cmd = None
        best_confidence = 0.0

        # Check coding-specific patterns first if mode is coding
        if mode == "coding":
            coding_patterns = self._build_coding_patterns()
            for intent, patterns in coding_patterns.items():
                for pattern, command_template, confidence in patterns:
                    match = re.search(pattern, text, re.IGNORECASE)
                    if match and confidence >= threshold:
                        if confidence > best_confidence:
                            cmd = self._format_command(command_template, match.groups())
                            best_cmd = cmd
                            best_confidence = confidence

        for intent, patterns in self.patterns.items():
            # In coding mode: skip web-search-routing intents. The bot uses
            # Grep/Read/Bash for codebase search, never web search.
            if mode == "coding" and intent in ("search", "code_search"):
                continue
            for pattern, command_template, confidence in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match and confidence >= threshold:
                    if confidence > best_confidence:
                        cmd = self._format_command(command_template, match.groups())
                        best_cmd = cmd
                        best_confidence = confidence

        if best_cmd is not None:
            return best_cmd, best_confidence
        return None, 0.0

    def _format_command(self, command_template: str, groups: tuple) -> str:
        """Format command template with matched groups."""
        if '{match}' in command_template and groups:
            # Replace {match} with first group
            cmd = command_template.replace('{match}', groups[0].strip())
            # If there's a {content} placeholder and second group exists
            if '{content}' in cmd and len(groups) > 1:
                cmd = cmd.replace('{content}', groups[1].strip())
            return cmd
        else:
            return command_template

    def should_suggest(self, text: str) -> bool:
        """Quick check if text might be a natural language command."""
        # Simple heuristic: if text doesn't start with / and is not too long
        if text.startswith('/'):
            return False
        if len(text.split()) > 10:  # Too long for simple command
            return False
        # Filter out polite requests that aren't commands
        polite_prefixes = ['can you', 'could you', 'would you', 'please', 'i need', 'i want', 'tell me', 'show me', 'give me']
        lower_text = text.lower()
        for prefix in polite_prefixes:
            if lower_text.startswith(prefix):
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
        pattern = r'\b(' + '|'.join(keywords) + r')\b'
        return re.search(pattern, lower_text) is not None