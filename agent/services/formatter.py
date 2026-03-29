"""
Output formatting standardization for consistent CLI experience.
Provides methods for styled output with emojis, colors (optional), and consistent spacing.
"""

import os
import sys
from typing import Optional


class Formatter:
    """Standardized output formatting for CLI commands."""

    # Emoji prefixes for different message types
    EMOJI_SUCCESS = "✅"
    EMOJI_ERROR = "❌"
    EMOJI_WARNING = "⚠️ "
    EMOJI_INFO = "💡"
    EMOJI_PROGRESS = "⏳"
    EMOJI_FILE = "📄"
    EMOJI_DIR = "📁"
    EMOJI_CODE = "📝"
    EMOJI_SEARCH = "🔍"
    EMOJI_GIT = "🔄"
    EMOJI_TEST = "🧪"
    EMOJI_HELP = "🤖"

    # Color codes (ANSI) - only use if terminal supports it
    COLORS_ENABLED = sys.stdout.isatty() and os.getenv('TERM') not in ('dumb', '')
    COLOR_RESET = '\033[0m'
    COLOR_SUCCESS = '\033[92m'  # Green
    COLOR_ERROR = '\033[91m'    # Red
    COLOR_WARNING = '\033[93m'  # Yellow
    COLOR_INFO = '\033[94m'     # Blue
    COLOR_CODE = '\033[36m'     # Cyan
    COLOR_HEADER = '\033[1m'    # Bold

    def __init__(self, use_colors: Optional[bool] = None):
        """Initialize formatter.

        Args:
            use_colors: Override color detection. If None, auto-detect.
        """
        if use_colors is not None:
            self.COLORS_ENABLED = use_colors
        else:
            self.COLORS_ENABLED = sys.stdout.isatty() and os.getenv('TERM') not in ('dumb', '')

    def _apply_color(self, text: str, color_code: str) -> str:
        """Apply color if enabled."""
        if self.COLORS_ENABLED:
            return f"{color_code}{text}{self.COLOR_RESET}"
        return text

    def success(self, message: str) -> str:
        """Format success message."""
        colored_msg = self._apply_color(message, self.COLOR_SUCCESS)
        return f"{self.EMOJI_SUCCESS} {colored_msg}"

    def error(self, message: str) -> str:
        """Format error message."""
        colored_msg = self._apply_color(message, self.COLOR_ERROR)
        return f"{self.EMOJI_ERROR} {colored_msg}"

    def warning(self, message: str) -> str:
        """Format warning message."""
        colored_msg = self._apply_color(message, self.COLOR_WARNING)
        return f"{self.EMOJI_WARNING} {colored_msg}"

    def info(self, message: str) -> str:
        """Format info message."""
        colored_msg = self._apply_color(message, self.COLOR_INFO)
        return f"{self.EMOJI_INFO} {colored_msg}"

    def progress(self, message: str) -> str:
        """Format progress message."""
        return f"{self.EMOJI_PROGRESS} {message}"

    def file(self, message: str) -> str:
        """Format file-related message."""
        return f"{self.EMOJI_FILE} {message}"

    def directory(self, message: str) -> str:
        """Format directory-related message."""
        return f"{self.EMOJI_DIR} {message}"

    def code(self, message: str) -> str:
        """Format code-related message."""
        colored_msg = self._apply_color(message, self.COLOR_CODE)
        return f"{self.EMOJI_CODE} {colored_msg}"

    def header(self, text: str, level: int = 1) -> str:
        """Format header text."""
        if level == 1:
            line = "=" * 60
            return f"\n{self._apply_color(text, self.COLOR_HEADER)}\n{line}"
        elif level == 2:
            line = "-" * 40
            return f"\n{self._apply_color(text, self.COLOR_HEADER)}\n{line}"
        else:
            return f"\n{self._apply_color(text, self.COLOR_HEADER)}"

    def section(self, title: str, content: str) -> str:
        """Format a section with title and content."""
        return f"\n{self.header(title, level=2)}\n{content}"

    def code_block(self, code: str, language: str = "") -> str:
        """Format code block with optional language hint."""
        lang_tag = f"{language}\n" if language else ""
        return f"```{lang_tag}{code}\n```"

    def list_item(self, text: str, bullet: str = "•") -> str:
        """Format a list item."""
        return f"  {bullet} {text}"

    def key_value(self, key: str, value: str, indent: int = 2) -> str:
        """Format key-value pair."""
        spaces = " " * indent
        return f"{spaces}{key}: {value}"

    def command_help(self, command: str, description: str, usage: str, examples: str = "") -> str:
        """Format command help."""
        result = f"\n{self.header(command, level=2)}\n"
        result += f"{description}\n\n"
        result += f"Usage:\n{usage}\n"
        if examples:
            result += f"\nExamples:\n{examples}"
        return result

    def table(self, headers: list, rows: list, max_col_width: int = 30) -> str:
        """Format a simple table (basic alignment)."""
        if not rows:
            return ""

        # Calculate column widths
        col_widths = []
        for i in range(len(headers)):
            max_len = len(str(headers[i]))
            for row in rows:
                if i < len(row):
                    max_len = max(max_len, len(str(row[i])))
            max_len = min(max_len, max_col_width)
            col_widths.append(max_len)

        # Build table
        lines = []

        # Header
        header_parts = []
        for i, header in enumerate(headers):
            header_parts.append(str(header).ljust(col_widths[i]))
        lines.append("  ".join(header_parts))
        lines.append("-" * (sum(col_widths) + (len(headers) - 1) * 2))

        # Rows
        for row in rows:
            row_parts = []
            for i in range(len(headers)):
                cell = str(row[i]) if i < len(row) else ""
                if len(cell) > max_col_width:
                    cell = cell[:max_col_width-3] + "..."
                row_parts.append(cell.ljust(col_widths[i]))
            lines.append("  ".join(row_parts))

        return "\n".join(lines)


# Global default formatter instance
_default_formatter = Formatter()

# Convenience functions using default formatter
def success(message: str) -> str:
    return _default_formatter.success(message)

def error(message: str) -> str:
    return _default_formatter.error(message)

def warning(message: str) -> str:
    return _default_formatter.warning(message)

def info(message: str) -> str:
    return _default_formatter.info(message)

def header(text: str, level: int = 1) -> str:
    return _default_formatter.header(text, level)

def code_block(code: str, language: str = "") -> str:
    return _default_formatter.code_block(code, language)

def command_help(command: str, description: str, usage: str, examples: str = "") -> str:
    return _default_formatter.command_help(command, description, usage, examples)