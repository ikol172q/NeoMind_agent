#!/usr/bin/env python3
"""
Test auto mode switching for /code and /fix commands.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.core import NeoMindAgent

def test_auto_mode_switch():
    """Test that /code and /fix commands auto-switch to coding mode."""
    print("Testing auto mode switching...")

    # Use dummy API key
    chat = NeoMindAgent(api_key="dummy_key")

    print(f"Initial mode: {chat.mode}")
    assert chat.mode == "chat", f"Expected initial mode 'chat', got '{chat.mode}'"

    # Test /code command (simulated)
    print("\n1. Testing /code scan command...")
    # Mock the scan to avoid actual filesystem access
    # We'll just call handle_code_command with a mock path that won't be accessed
    # since the code will try to scan but we don't need it to succeed for mode test
    try:
        result = chat.handle_code_command("scan .")
        print(f"   Result (truncated): {result[:100] if result else 'None'}...")
    except Exception as e:
        print(f"   Command raised exception (expected for test): {type(e).__name__}: {e}")

    print(f"   Mode after /code: {chat.mode}")
    assert chat.mode == "coding", f"Expected mode 'coding' after /code, got '{chat.mode}'"

    # Switch back to chat mode
    print("\n2. Switching back to chat mode...")
    chat.switch_mode("chat")
    print(f"   Mode after explicit switch: {chat.mode}")
    assert chat.mode == "chat", f"Expected mode 'chat', got '{chat.mode}'"

    # Test /fix command (simulated)
    print("\n3. Testing /fix command...")
    # Mock to avoid file access - the command will fail but mode should switch
    try:
        result = chat.handle_auto_fix_command("/fix test.py")
        print(f"   Result: {result}")
    except Exception as e:
        print(f"   Command raised exception (expected): {type(e).__name__}: {e}")

    print(f"   Mode after /fix: {chat.mode}")
    assert chat.mode == "coding", f"Expected mode 'coding' after /fix, got '{chat.mode}'"

    # Test that /code help doesn't switch mode
    print("\n4. Switching back to chat, testing /code help...")
    chat.switch_mode("chat")
    result = chat.handle_code_command("help")
    print(f"   Mode after /code help: {chat.mode}")
    assert chat.mode == "chat", f"Expected mode to remain 'chat' after /code help, got '{chat.mode}'"

    print("\n✅ All auto mode switching tests passed!")
    return True

if __name__ == "__main__":
    try:
        test_auto_mode_switch()
        sys.exit(0)
    except AssertionError as e:
        print(f"❌ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)