#!/usr/bin/env python3
# main.py - Entry point for DeepSeek Agent

import sys
import os
from dotenv import load_dotenv

# Load environment variables FIRST
load_dotenv()

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    """Main entry point"""
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


if __name__ == "__main__":
    main()