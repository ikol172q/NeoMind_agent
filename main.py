#!/usr/bin/env python3
# main.py - Entry point for neomind Agent

import sys
import os

# Fix for Windows terminal detection in MINGW/Cygwin before any prompt_toolkit imports
if sys.platform == "win32" and "xterm" in os.environ.get("TERM", ""):
    os.environ["PROMPT_TOOLKIT_NO_WIN32_CONSOLE"] = "1"
    os.environ["PROMPT_TOOLKIT_FORCE_VT100_OUTPUT"] = "1"

import argparse
from dotenv import load_dotenv

# Load environment variables FIRST
load_dotenv()

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def interactive_main(mode: str = "chat"):
    """Launch interactive session in the specified mode.

    Args:
        mode: 'chat' or 'coding' — determines config, commands, and behavior
    """
    # Set mode on config before anything else
    from agent_config import agent_config
    if mode != agent_config.mode:
        agent_config.switch_mode(mode)

    # Try Claude-like interface first (preferred)
    try:
        from cli.claude_interface import interactive_chat_claude_interface
        interactive_chat_claude_interface(mode)
        return
    except Exception as e:
        print(f"Note: Claude interface unavailable ({e}), falling back to standard interface")

    # Fallback chain
    try:
        from prompt_toolkit import PromptSession
        from cli.interface import interactive_chat_with_prompt_toolkit
        interactive_chat_with_prompt_toolkit(mode)
    except ImportError:
        print("Note: For better experience, install prompt_toolkit: pip install prompt_toolkit")
        from cli.interface import interactive_chat_fallback
        interactive_chat_fallback(mode)


def test_main():
    """Run development tests"""
    try:
        import dev_test
        success = dev_test.run_tests()
        sys.exit(0 if success else 1)
    except ImportError:
        print("Error: dev_test.py not found")
        sys.exit(1)


def main():
    """Main entry point with argument parsing"""
    parser = argparse.ArgumentParser(
        description="neomind AI Agent — Chat or Coding mode",
        epilog="Examples:\n"
               "  python main.py --mode chat     # General conversation\n"
               "  python main.py --mode coding   # Claude CLI-like coding assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        'run_mode',
        nargs='?',
        default='interactive',
        choices=['interactive', 'test'],
        help="Run mode: interactive session or development tests"
    )
    parser.add_argument(
        '--mode',
        default='chat',
        choices=['chat', 'coding'],
        help="Session mode: chat (conversation) or coding (Claude CLI-like). Default: chat"
    )
    parser.add_argument(
        '--version',
        action='store_true',
        help="Show version information"
    )

    args = parser.parse_args()

    if args.version:
        try:
            from neomind import __version__
            print(f"neomind-agent version {__version__}")
        except ImportError:
            print("neomind-agent version 0.1.0")
        return

    if args.run_mode == 'test':
        test_main()
    else:
        interactive_main(args.mode)


if __name__ == "__main__":
    main()
