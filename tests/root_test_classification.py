#!/usr/bin/env python3
"""
Quick test for input classification.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.core import DeepSeekStreamingChat

def test_classification():
    # Create instance with dummy API key
    agent = DeepSeekStreamingChat(api_key="dummy_key")

    test_cases = [
        ("https://example.com", "/read https://example.com"),
        ("https://example.com/page", "/read https://example.com/page"),
        ("http://localhost:8000", "/read http://localhost:8000"),
        ("main.py", "/read main.py"),
        ("agent/core.py", "/read agent/core.py"),
        ("agent/core.py:15", "/read agent/core.py:15"),
        ("agent/core.py:10-20", "/read agent/core.py:10-20"),
        ("C:\\Users\\test\\file.py", "/read C:\\Users\\test\\file.py"),
        ("/home/user/file.py", "/read /home/user/file.py"),
        ("file.txt", "/read file.txt"),
        ("search for something", None),  # Should not classify
        ("what is the weather", None),   # Should not classify
        ("/read already_command", None), # Already a command
        ("function_name()", None),       # Code reference - might return None
    ]

    print("Testing input classification:")
    print("-" * 60)

    for input_text, expected in test_cases:
        result = agent.classify_and_enhance_input(input_text)
        status = "[OK]" if result == expected else "[FAIL]"
        print(f"{status} '{input_text}' -> {result} (expected: {expected})")

    print("-" * 60)
    print(f"Tests completed.")

if __name__ == "__main__":
    test_classification()