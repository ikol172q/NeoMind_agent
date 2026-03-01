#!/usr/bin/env python3
# main.py - Entry point for Advanced AI Agent

import sys
import os
# Fix for Windows terminal detection in MINGW/Cygwin before any prompt_toolkit imports
if sys.platform == "win32" and "xterm" in os.environ.get("TERM", ""):
    # Force prompt_toolkit to use VT100 output instead of Win32 console API
    os.environ["PROMPT_TOOLKIT_NO_WIN32_CONSOLE"] = "1"
    os.environ["PROMPT_TOOLKIT_FORCE_VT100_OUTPUT"] = "1"
import argparse
from dotenv import load_dotenv

# Load environment variables FIRST
load_dotenv()

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def interactive_main(mode: str = "chat"):
    """Interactive chat mode

    Args:
        mode: Operation mode ('chat' or 'coding')
    """
    # Fix for Windows terminal detection in MINGW/Cygwin
    import sys
    import os
    if sys.platform == "win32" and "xterm" in os.environ.get("TERM", ""):
        # Force prompt_toolkit to use VT100 output instead of Win32 console API
        os.environ["PROMPT_TOOLKIT_NO_WIN32_CONSOLE"] = "1"

    # Update agent config mode if different from default
    from agent_config import agent_config
    if mode != agent_config.mode:
        success = agent_config.update_mode(mode)
        if success:
            print(f"Mode set to: {mode}")
        else:
            print(f"Warning: Failed to set mode to {mode}, using current mode: {agent_config.mode}")

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
        interactive_chat_with_prompt_toolkit(mode)
    else:
        from cli.interface import interactive_chat_fallback
        interactive_chat_fallback(mode)


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
        description="Advanced AI Agent",
        epilog="Use 'user-agent' without arguments for interactive chat."
    )
    parser.add_argument(
        'run_mode',
        nargs='?',
        default='interactive',
        choices=['interactive', 'test'],
        help="Run mode: interactive chat or development tests"
    )
    parser.add_argument(
        '--mode',
        default='chat',
        choices=['chat', 'coding'],
        help="Operation mode: chat or coding (default: chat)"
    )
    parser.add_argument(
        '--version',
        action='store_true',
        help="Show version information"
    )

    args = parser.parse_args()

    if args.version:
        from user_agent import __version__
        print(f"user-agent version {__version__}")
        return

    if args.run_mode == 'test':
        test_main()
    else:
        interactive_main(args.mode)


if __name__ == "__main__":
    main()