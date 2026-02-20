#!/usr/bin/env python3
"""
Quick test of command router refactoring.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

from agent.core import DeepSeekStreamingChat

def test_command_router():
    # Create agent with dummy API key (won't be used for commands)
    agent = DeepSeekStreamingChat(api_key="dummy_key")

    # Test /help command
    print("Testing /help command...")
    result = agent.stream_response("/help")
    if result is None:
        print("✓ /help command handled (returned None as expected)")
    else:
        print(f"✗ Unexpected return: {result}")

    # Test /help write
    print("\nTesting /help write command...")
    result = agent.stream_response("/help write")
    if result is None:
        print("✓ /help write command handled")
    else:
        print(f"✗ Unexpected return: {result}")

    # Test /models list (should print models and return None)
    print("\nTesting /models list command...")
    result = agent.stream_response("/models list")
    if result is None:
        print("✓ /models list command handled")
    else:
        print(f"✗ Unexpected return: {result}")

    # Test unknown command (should skip_user_add = False and proceed to API)
    print("\nTesting unknown command...")
    result = agent.stream_response("hello world")
    if result is not None:
        print("✓ Unknown command proceeded to API (response returned)")
    else:
        print("✗ Unexpected None return")

    print("\nAll tests completed.")

if __name__ == "__main__":
    test_command_router()