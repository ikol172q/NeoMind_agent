"""
Comprehensive help system for ikol1729-agent.
Provides command documentation and usage examples.
"""
from typing import Dict, Optional
from .formatter import Formatter


class HelpSystem:
    """Help system for CLI commands."""

    def __init__(self, formatter: Optional[Formatter] = None):
        self.formatter = formatter or Formatter()
        self.help_texts = self._build_help_texts()

    def _build_help_texts(self) -> Dict[str, str]:
        """Build the dictionary of help texts."""
        return {
            "write": self.formatter.command_help(
                command="/write",
                description="Write content to a file.",
                usage="/write <file_path> [content]\n/write --interactive <file_path>",
                examples="/write hello.txt \"Hello World\"\n/write script.py \"print('hello')\""
            ),
            "edit": self.formatter.command_help(
                command="/edit",
                description="Replace old code with new code in a file.",
                usage="/edit <file_path> \"<old_code>\" \"<new_code>\"",
                examples="/edit script.py \"print('old')\" \"print('new')\""
            ),
            "read": self.formatter.command_help(
                command="/read",
                description="Read webpage content or local file.",
                usage="/read <url>\n/read <file_path> [line_range]\n/read --debug <url>\n/read --strategy <n> <url>",
                examples="/read https://example.com\n/read file.py:10-20"
            ),
            "run": self.formatter.command_help(
                command="/run",
                description="Execute a shell command safely.",
                usage="/run <command> [args...]",
                examples="/run ls -la\n/run python --version"
            ),
            "git": self.formatter.command_help(
                command="/git",
                description="Execute git command safely.",
                usage="/git <subcommand> [args...]",
                examples="/git status\n/git log --oneline -5"
            ),
            "code": self.formatter.command_help(
                command="/code",
                description="Code analysis and refactoring commands.",
                usage="/code scan [path]\n/code summary\n/code find <pattern>\n/code read <file_path>\n/code analyze <file_path>\n/code search <text>\n/code changes\n/code apply\n/code clear\n/code self-scan\n/code self-improve <feature>\n/code self-apply",
                examples="/code scan .\n/code find *.py\n/code analyze agent/core.py"
            ),
            "search": self.formatter.command_help(
                command="/search",
                description="Search the web using DuckDuckGo.",
                usage="/search <query>",
                examples="/search Python documentation"
            ),
            "models": self.formatter.command_help(
                command="/models",
                description="List and switch DeepSeek models.",
                usage="/models list\n/models switch <model>",
                examples="/models list\n/models switch deepseek-reasoner"
            ),
            "fix": self.formatter.command_help(
                command="/fix",
                description="Automatically fix code issues.",
                usage="/fix <file_path> [description]",
                examples="/fix agent/core.py 'fix error handling'"
            ),
            "analyze": self.formatter.command_help(
                command="/analyze",
                description="Analyze code for issues and suggest improvements.",
                usage="/analyze <file_path>",
                examples="/analyze agent/core.py"
            ),
            "diff": self.formatter.command_help(
                command="/diff",
                description="Compare files or versions.",
                usage="/diff <file1> <file2>\n/diff --git <file>\n/diff --backup <file>",
                examples="/diff old.py new.py\n/diff --git agent/core.py"
            ),
            "browse": self.formatter.command_help(
                command="/browse",
                description="Browse directory structure.",
                usage="/browse [path]\n/browse --details [path]\n/browse --filter <ext>",
                examples="/browse\n/browse agent/\n/browse --details src/"
            ),
            "undo": self.formatter.command_help(
                command="/undo",
                description="Revert recent changes.",
                usage="/undo list [n]\n/undo last\n/undo <change_id>",
                examples="/undo list\n/undo last\n/undo 2"
            ),
            "test": self.formatter.command_help(
                command="/test",
                description="Run tests.",
                usage="/test\n/test unit\n/test all",
                examples="/test\n/test unit"
            ),
            "apply": self.formatter.command_help(
                command="/apply",
                description="Apply pending changes (alias for /code apply).",
                usage="/apply\n/apply force\n/apply confirm",
                examples="/apply\n/apply force"
            ),
            "auto": self.formatter.command_help(
                command="/auto",
                description="Control auto-features (auto-search, natural language interpretation).",
                usage="/auto search on|off\n/auto interpret on|off\n/auto status\n/auto help",
                examples="/auto search on\n/auto interpret off\n/auto status"
            ),
        }

    def get_help(self, command: str = "") -> str:
        """
        Get help for a command or list all commands.

        Args:
            command: Command name without leading slash, or empty string for all commands.

        Returns:
            Formatted help text.
        """
        if not command:
            # Show all commands
            result = self.formatter.header("Available Commands", level=2) + "\n\n"
            for cmd in sorted(self.help_texts.keys()):
                # Extract first line of each help text (command header)
                lines = self.help_texts[cmd].strip().split('\n')
                if lines:
                    result += lines[0] + "\n"
            result += "\n" + self.formatter.info("Use /help <command> for detailed usage.")
            return result

        cmd = command.strip().lower()
        if cmd in self.help_texts:
            return self.help_texts[cmd]
        else:
            return self.formatter.error(f"No help available for '{command}'. Available commands: {', '.join(sorted(self.help_texts.keys()))}")


# Global default instance
_default_help_system = HelpSystem()

# Convenience functions
def get_help(command: str = "") -> str:
    return _default_help_system.get_help(command)