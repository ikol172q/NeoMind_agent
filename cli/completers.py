# cli/completers.py
"""Command auto-completion system for ikol1729 agent."""

from prompt_toolkit.completion import Completer, Completion
from typing import Dict, List, Optional, Iterable
import os
import fnmatch


class CommandCompleter(Completer):
    """Command auto-completer for CLI commands and file paths."""

    def __init__(self, help_system, workspace_manager=None):
        """
        Initialize the completer.

        Args:
            help_system: Instance of HelpSystem to get command list
            workspace_manager: Optional WorkspaceManager for file path completion
        """
        self.help_system = help_system
        self.workspace_manager = workspace_manager
        self.commands = self._extract_commands()
        self.param_suggestions = self._build_param_suggestions()

    def _extract_commands(self) -> List[str]:
        """Extract command list from help system."""
        # HelpSystem has help_texts dictionary with command names as keys
        if hasattr(self.help_system, 'help_texts'):
            return list(self.help_system.help_texts.keys())
        # Fallback: hardcoded command list from help_system.py
        return [
            "write", "edit", "read", "run", "git", "code", "search", "models",
            "mode", "fix", "analyze", "diff", "browse", "undo", "test", "apply",
            "auto", "task", "plan", "execute", "switch", "summarize", "translate",
            "generate", "reason", "debug", "explain", "refactor", "grep", "find",
            "clear", "history", "context", "compact", "think", "quit", "exit", "help"
        ]

    def _build_param_suggestions(self) -> Dict[str, List[str]]:
        """Build parameter suggestions for commands."""
        return {
            "mode": ["chat", "coding", "status", "help"],
            "auto": ["search", "interpret", "status", "help"],
            "code": [
                "scan", "summary", "find", "read", "analyze", "search",
                "changes", "apply", "clear", "self-scan", "self-improve", "self-apply"
            ],
            "task": ["create", "list", "update", "delete", "clear", "help"],
            "plan": ["list", "delete", "show", "help"],
            "context": ["status", "compress", "clear", "help"],
            "models": ["list", "switch"],
        }

    def get_completions(self, document, complete_event) -> Iterable[Completion]:
        """Generate completions for current input."""
        text = document.text_before_cursor
        words = text.split()

        # Empty input - no completions
        if not text.strip():
            return

        # Command completion (starts with /)
        if text.startswith('/'):
            if len(words) == 1:
                # Command name completion
                partial_cmd = text[1:].lower()
                for cmd in self.commands:
                    if cmd.startswith(partial_cmd):
                        yield Completion(
                            f'/{cmd}',
                            start_position=-len(partial_cmd),
                            display=cmd,
                            display_meta=f"Command: {cmd}"
                        )
            elif len(words) >= 2:
                # Parameter completion for specific commands
                cmd_name = words[0][1:].lower()
                if cmd_name in self.param_suggestions:
                    last_word = words[-1]
                    for param in self.param_suggestions[cmd_name]:
                        if param.startswith(last_word):
                            yield Completion(
                                param,
                                start_position=-len(last_word),
                                display=param,
                                display_meta=f"Parameter for /{cmd_name}"
                            )

        # File path completion (when not a command and workspace manager available)
        elif '/' not in text and self.workspace_manager:
            # Only suggest file paths if not already in a command
            last_word = words[-1] if words else ""

            # Get files from workspace
            try:
                files = self.workspace_manager.scan()
                for file_path in files:
                    if last_word.lower() in file_path.lower():
                        # Simple completion - just the file name
                        display_name = os.path.basename(file_path)
                        yield Completion(
                            file_path,
                            start_position=-len(last_word),
                            display=display_name,
                            display_meta=f"File: {file_path}"
                        )
            except Exception:
                # If workspace scan fails, skip file completions
                pass

        # Natural language suggestions (optional)
        # Could be enhanced later


class FilePathCompleter(Completer):
    """Simple file path completer for local filesystem."""

    def __init__(self, base_dir=None):
        self.base_dir = base_dir or os.getcwd()

    def get_completions(self, document, complete_event) -> Iterable[Completion]:
        text = document.text_before_cursor
        words = text.split()

        if not words:
            return

        last_word = words[-1]

        # Always attempt file path completion for the last word
        dir_part = os.path.dirname(last_word) or '.'
        file_part = os.path.basename(last_word)

        abs_dir = os.path.join(self.base_dir, dir_part)
        if not os.path.exists(abs_dir):
            return

        try:
            for item in os.listdir(abs_dir):
                if item.startswith(file_part):
                    # Determine the completion text
                    if dir_part == '.' and '/' not in last_word:
                        # User typed a plain filename without path indicators
                        # Return just the filename, not './filename'
                        full_path = item
                    else:
                        full_path = os.path.join(dir_part, item)

                    if os.path.isdir(os.path.join(abs_dir, item)):
                        full_path += '/'
                    yield Completion(
                        full_path,
                        start_position=-len(file_part),
                        display=item,
                        display_meta="Directory" if item.endswith('/') else "File"
                    )
        except OSError:
            pass