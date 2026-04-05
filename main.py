#!/usr/bin/env python3
# main.py - Entry point for neomind Agent

import sys
import os

# ── Fast-path dispatch ──────────────────────────────────────────
# Handle simple flags BEFORE loading any heavy modules.
# This avoids importing agent/, prompt_toolkit, openai, etc.
# for trivial operations like --version or --help.
def _fast_path():
    """Check for fast-path arguments that don't need full module loading."""
    args = sys.argv[1:]
    if '--version' in args or '-V' in args:
        # Read version from pyproject.toml without importing anything
        try:
            _root = os.path.dirname(os.path.abspath(__file__))
            with open(os.path.join(_root, 'pyproject.toml')) as f:
                for line in f:
                    if line.strip().startswith('version'):
                        ver = line.split('=')[1].strip().strip('"').strip("'")
                        print(f"neomind-agent version {ver}")
                        sys.exit(0)
        except Exception:
            pass
        print("neomind-agent version 0.3.0")
        sys.exit(0)

    if '--dump-system-prompt' in args:
        # Dump system prompt without loading the full agent
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        try:
            from agent_config import agent_config
            mode = 'coding' if '--mode' in args and 'coding' in args else 'chat'
            agent_config.switch_mode(mode)
            print(agent_config.system_prompt or "(no system prompt)")
        except Exception as e:
            print(f"Error: {e}")
        sys.exit(0)

    if '--help' in args or '-h' in args:
        return  # Let argparse handle it normally

_fast_path()

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
    # Run startup migrations
    try:
        from agent.migrations import run_startup_migrations
        run_startup_migrations()
    except Exception:
        pass  # Non-fatal

    # Set mode on config before anything else
    from agent_config import agent_config
    if mode != agent_config.mode:
        agent_config.switch_mode(mode)

    # Try NeoMind interface first (preferred)
    try:
        from cli.neomind_interface import interactive_chat
        interactive_chat(mode)
        return
    except Exception as e:
        print(f"Note: NeoMind interface unavailable ({e}), falling back to standard interface")

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
        description="neomind AI Agent — Chat, Coding, or Finance mode",
        epilog="Examples:\n"
               "  python main.py --mode chat     # General conversation\n"
               "  python main.py --mode coding   # NeoMind coding assistant\n"
               "  python main.py --mode fin      # Personal finance & investment intelligence",
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
        choices=['chat', 'coding', 'fin'],
        help="Session mode: chat (conversation), coding (NeoMind), or fin (finance intelligence). Default: chat"
    )
    parser.add_argument(
        '--version',
        action='store_true',
        help="Show version information"
    )

    args = parser.parse_args()

    if args.version:
        # Fast-path already handled this, but in case it gets here
        print("neomind-agent version 0.3.0")
        return

    if args.run_mode == 'test':
        test_main()
    else:
        interactive_main(args.mode)


if __name__ == "__main__":
    main()
