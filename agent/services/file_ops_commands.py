"""
File Operation Commands — read, write, edit.

Extracted from core.py (Tier 2G). Each function takes the core agent reference
and command string, returning formatted output.

Created: 2026-04-01 (Phase 0 - Infrastructure Refactoring)
"""

from __future__ import annotations

import os
import sys
import shlex
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from agent.core import NeoMindAgent

# Optional dependencies
try:
    import trafilatura
    HAS_TRAFILATURA = True
except ImportError:
    HAS_TRAFILATURA = False

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False
    BeautifulSoup = None

try:
    import html2text
    HAS_HTML2TEXT = True
except ImportError:
    HAS_HTML2TEXT = False
    html2text = None

try:
    from requests_html import HTMLSession
    HAS_REQUESTS_HTML = True
except ImportError:
    HAS_REQUESTS_HTML = False
    HTMLSession = None


def handle_read_command(core: "NeoMindAgent", url_or_command: str) -> str:
    """
    Handle /read command for webpage reading with enhanced capabilities.
    Automatically adds content to conversation history for AI awareness.

    Args:
        core: NeoMind agent instance
        url_or_command: URL or file path to read

    Returns:
        Formatted content or error message
    """
    if not url_or_command or url_or_command.strip() == "":
        help_text = """
📚 /read Command Usage:
/read <url>                     - Read webpage content and make AI aware of it
/read <file_path>               - Read local file (supports line ranges: file.py:10-20)
/read --debug <url>            - Show debugging info (doesn't add to AI memory)
/read --strategy <n> <url>     - Use specific strategy (0-4)
/read --no-ai <url|file>       - Read without adding to AI memory

Strategies (for webpages only):
0: trafilatura (best for articles)
1: beautifulsoup (smart extraction)
2: html2text (markdown conversion)
3: requests-html (JavaScript sites)
4: fallback (basic extraction)

Note: By default, all content is added to AI memory so you can ask questions about it.
        """.strip()
        return help_text

    parts = url_or_command.split()

    # Parse flags
    debug = False
    strategy = None
    no_ai = False
    url = None

    i = 0
    while i < len(parts):
        if parts[i] == '--debug':
            debug = True
            parts.pop(i)
        elif parts[i] == '--strategy':
            if i + 1 < len(parts):
                try:
                    strategy = int(parts[i + 1])
                    parts.pop(i)
                    parts.pop(i)
                except ValueError:
                    return core.formatter.error(f"Invalid strategy number. Must be 0-4.")
            else:
                return core.formatter.error("Missing strategy number. Use: /read --strategy <0-4> <url>")
        elif parts[i] == '--no-ai':
            no_ai = True
            parts.pop(i)
        else:
            i += 1

    if not parts:
        return core.formatter.error("Please provide a URL")

    url = ' '.join(parts)

    # Follow-up from /links: "/read 3" reads link #3
    if url.isdigit() and hasattr(core, '_last_links') and core._last_links:
        link_num = int(url)
        if link_num in core._last_links:
            url = core._last_links[link_num]
            print(f"🔗 Following link #{link_num}: {url}")
        else:
            return core.formatter.error(
                f"Link #{link_num} not found. Available: {min(core._last_links)}–{max(core._last_links)}"
            )

    # Check if this is a local file path
    if _is_likely_file_path(url):
        return _handle_file_read(core, url, no_ai)

    print(f"🌐 Processing: {url}")

    if debug:
        return _debug_read(core, url)
    elif strategy is not None:
        return _strategy_read(core, url, strategy, no_ai)
    else:
        content = core.read_webpage(url)
        if not no_ai:
            _add_webpage_to_memory(core, url, content)
        return content


def handle_write_command(core: "NeoMindAgent", command: str) -> str:
    """
    Handle /write command for creating or overwriting files.

    Usage:
      /write <file_path> [content]   - Write content to file (content optional)
      /write --interactive <file_path> - Enter content interactively

    Args:
        core: NeoMind agent instance
        command: Command string

    Returns:
        Success or error message
    """
    if not command or command.strip() == "":
        help_text = """
📝 /write Command Usage:
  /write <file_path> [content]   - Write content to file
  /write --interactive <file_path> - Enter content interactively (end with EOF)

Examples:
  /write hello.txt "Hello World"
  /write script.py "print('hello')"
  /write --interactive notes.md
        """.strip()
        return help_text

    # Auto-switch to coding mode for write command
    if core.mode != 'coding':
        core.switch_mode('coding', persist=False)

    # Parse flags
    interactive = False
    parts = command.split()
    if parts[0] == '--interactive':
        interactive = True
        parts.pop(0)

    if not parts:
        return core.formatter.error("Please provide a file path")

    file_path = parts[0]
    content = ' '.join(parts[1:]) if len(parts) > 1 else ""

    # If interactive mode or no content provided, read from stdin
    if interactive or not content:
        content = _read_interactive_content()
        if not content:
            return core.formatter.warning("No content provided. File not written.")

    # Guard check
    is_allowed, guard_warning = core._check_file_guards(file_path)
    if not is_allowed:
        core._log_evidence("file_edit", file_path, guard_warning, severity="warning")
        return core.formatter.warning(f"🧊 FROZEN: {guard_warning}")

    # Ensure code analyzer is initialized
    if not core.code_analyzer:
        from agent.code_analyzer import CodeAnalyzer
        core.code_analyzer = CodeAnalyzer(os.getcwd(), safety_manager=core.safety_manager)

    # Write file
    success, message = core.code_analyzer.write_file_safe(file_path, content)
    if success:
        core._log_evidence("file_edit", file_path, f"write_success, {len(content)} bytes", severity="info")
        return core.formatter.success(message)
    else:
        core._log_evidence("file_edit", file_path, f"write_failed: {message}", severity="warning")
        return core.formatter.error(message)


def handle_edit_command(core: "NeoMindAgent", command: str) -> str:
    """
    Handle /edit command for editing files with code changes.

    Usage:
      /edit <file_path> "<old_code>" "<new_code>" [--description "desc"]
      /edit --help

    Args:
        core: NeoMind agent instance
        command: Command string

    Returns:
        Success or error message
    """
    if not command or command.strip() == "":
        help_text = """
📝 /edit Command Usage:
  /edit <file_path> "<old_code>" "<new_code>"   - Replace old code with new code
  /edit --help                                  - Show this help

Examples:
  /edit script.py "print('old')" "print('new')"
  /edit script.py "def old():" "def new():"
        """.strip()
        return help_text

    # Auto-switch to coding mode for edit command
    if core.mode != 'coding':
        core.switch_mode('coding', persist=False)

    # Parse flags
    try:
        parts = shlex.split(command)
    except ValueError as e:
        return core.formatter.error(f"Invalid command syntax: {e}")

    if not parts:
        return core.formatter.error("Please provide a file path")

    file_path = parts[0]
    description = "Manual edit via /edit command"
    line = None
    old_code = ""
    new_code = ""

    # Parse flags
    i = 1
    while i < len(parts):
        if parts[i] == '--description':
            if i + 1 < len(parts):
                description = parts[i + 1]
                i += 2
            else:
                return core.formatter.error("Missing description after --description")
        else:
            if i + 1 < len(parts):
                old_code = parts[i]
                new_code = parts[i + 1]
                i += 2
            else:
                return core.formatter.error("Need both old_code and new_code arguments")
            break

    if not old_code or not new_code:
        return core.formatter.error("Missing old_code or new_code")

    # Initialize code analyzer if needed
    if not core.code_analyzer:
        from agent.code_analyzer import CodeAnalyzer
        core.code_analyzer = CodeAnalyzer(os.getcwd(), safety_manager=core.safety_manager)

    # Validate change
    is_valid, error_msg = core.validate_proposed_change(old_code, new_code, file_path)
    if not is_valid:
        return core.formatter.error(f"Change validation failed: {error_msg}")

    # Propose change
    result = core.propose_code_change(file_path, old_code, new_code, description, line)
    return result


# ── Helper Functions ───────────────────────────────────────────────────────

def _is_likely_file_path(path: str) -> bool:
    """Check if a string is likely a local file path."""
    # Check for common file path patterns
    if path.startswith(('./', '../', '/', '~')):
        return True
    # Check for file extension
    if '.' in path and not path.startswith('http'):
        # Common file extensions
        extensions = ['.py', '.js', '.ts', '.txt', '.md', '.json', '.yaml', '.yml',
                      '.html', '.css', '.sh', '.bash', '.zsh', '.cfg', '.ini',
                      '.toml', '.xml', '.csv', '.log', '.env', '.example']
        for ext in extensions:
            if path.endswith(ext):
                return True
    # Check for line range syntax
    if ':' in path and any(c.isdigit() for c in path):
        return True
    return False


def _handle_file_read(core: "NeoMindAgent", file_path: str, no_ai: bool = False) -> str:
    """Handle reading a local file."""
    try:
        # Expand path
        expanded_path = os.path.expanduser(file_path)

        # Check if file exists
        if not os.path.exists(expanded_path):
            return core.formatter.error(f"File not found: {file_path}")

        # Check for line range syntax (file.py:10-20)
        line_range = None
        if ':' in expanded_path:
            parts = expanded_path.rsplit(':', 1)
            if parts[1].replace('-', '').isdigit():
                expanded_path = parts[0]
                line_range = parts[1]

        # Read file content
        with open(expanded_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()

        # Apply line range if specified
        if line_range:
            lines = content.split('\n')
            if '-' in line_range:
                start, end = map(int, line_range.split('-'))
                content = '\n'.join(lines[start-1:end])
            else:
                line_num = int(line_range)
                content = lines[line_num-1] if line_num <= len(lines) else ""

        # Format result
        result = core.formatter.success(f"📄 File: {file_path}\n\n{content}")

        # Add to memory unless --no-ai
        if not no_ai:
            _add_webpage_to_memory(core, f"file://{expanded_path}", content)

        return result

    except Exception as e:
        return core.formatter.error(f"Error reading file: {e}")


def _debug_read(core: "NeoMindAgent", url: str) -> str:
    """Debug mode: run all strategies and show results."""
    strategies = []
    if HAS_TRAFILATURA:
        strategies.append(("trafilatura", core._try_trafilatura))
    strategies.append(("beautifulsoup", core._try_beautifulsoup))
    if HAS_HTML2TEXT:
        strategies.append(("html2text", core._try_html2text))
    if HAS_REQUESTS_HTML:
        strategies.append(("requests-html", core._try_requests_html))
    strategies.append(("fallback", core._try_fallback))

    results = []
    best_content = None
    best_score = 0

    for name, strategy_func in strategies:
        try:
            content = strategy_func(url, 5000)
            if content:
                score = core._score_content(content)
                results.append(f"{name}: {score}/100, {len(content)} chars")
                if score > best_score:
                    best_content = content
                    best_score = score
        except Exception as e:
            results.append(f"{name}: ERROR - {str(e)}")

    if best_content:
        debug_info = "\n".join(results)
        final_result = core._format_result(url, best_content, best_score)
        return f"🔍 Debug Results:\n{debug_info}\n\n{final_result}"
    else:
        return core.formatter.error(f"All strategies failed for {url}")


def _strategy_read(core: "NeoMindAgent", url: str, strategy: int, no_ai: bool) -> str:
    """Read using a specific strategy."""
    strategies = [
        core._try_trafilatura,
        core._try_beautifulsoup,
        core._try_html2text,
        core._try_requests_html,
        core._try_fallback,
    ]

    if 0 <= strategy < len(strategies):
        content = strategies[strategy](url, 20000)
        if content:
            score = core._score_content(content)
            formatted_content = core._format_result(url, content, score)

            if not no_ai:
                _add_webpage_to_memory(core, url, content)

            return formatted_content
        else:
            return core.formatter.error(f"Strategy {strategy} failed to extract content")
    else:
        return core.formatter.error(f"Invalid strategy number. Use 0-{len(strategies)-1}")


def _read_interactive_content(prompt: str = "Enter content (end with EOF: Ctrl+D on Unix, Ctrl+Z on Windows):") -> str:
    """Read multiline content from stdin until EOF."""
    lines = []
    if sys.stdin.isatty():
        print(prompt)
        print("Type your content line by line. Press Ctrl+D (Unix) or Ctrl+Z (Windows) when done.")
    try:
        for line in sys.stdin:
            lines.append(line)
    except KeyboardInterrupt:
        print("\nInput interrupted.")
        return ""
    return "".join(lines)


def _add_webpage_to_memory(core: "NeoMindAgent", url: str, content: str) -> None:
    """Add webpage content to conversation history for AI awareness."""
    # Truncate if too large
    max_len = 10000
    if len(content) > max_len:
        content = content[:max_len] + "\n\n[Content truncated...]"

    # Add to conversation history
    memory_msg = {
        "role": "system",
        "content": f"[Webpage Content from {url}]\n\n{content}"
    }
    core.conversation_history.append(memory_msg)


__all__ = [
    'handle_read_command',
    'handle_write_command',
    'handle_edit_command',
]
