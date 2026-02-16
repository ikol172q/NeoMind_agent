#!/usr/bin/env python3
# main.py - Entry point for DeepSeek Agent

import sys
import os
import argparse
from dotenv import load_dotenv

# Load environment variables FIRST
load_dotenv()

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def interactive_main():
    """Interactive chat mode"""
    # Check for prompt_toolkit availability
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import InMemoryHistory
        PROMPT_TOOLKIT_AVAILABLE = True
    except ImportError:
        PROMPT_TOOLKIT_AVAILABLE = False
        print("Note: For better experience, install prompt_toolkit: pip install prompt_toolkit")

    # Import based on availability
    if PROMPT_TOOLKIT_AVAILABLE:
        from cli.interface import interactive_chat_with_prompt_toolkit
        interactive_chat_with_prompt_toolkit()
    else:
        from cli.interface import interactive_chat_fallback
        interactive_chat_fallback()


def test_main():
    """Run development tests"""
    # Use the dev_test module
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
        description="DeepSeek AI Agent",
        epilog="Use 'ikol1729-agent' without arguments for interactive chat."
    )
    parser.add_argument(
        'mode',
        nargs='?',
        default='interactive',
        choices=['interactive', 'test'],
        help="Run mode: interactive chat or development tests"
    )
    parser.add_argument(
        '--version',
        action='store_true',
        help="Show version information"
    )

    args = parser.parse_args()

    if args.version:
        from ikol1729_agent import __version__
        print(f"ikol1729-agent version {__version__}")
        return

    if args.mode == 'test':
        test_main()
    else:
        interactive_main()


if __name__ == "__main__":
    main()