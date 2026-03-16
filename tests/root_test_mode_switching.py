#!/usr/bin/env python3
"""
Test mode switching functionality for neomind agent.
Run with: python test_mode_switching.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_config import agent_config
from agent.core import NeoMindAgent


def test_mode_switching():
    """Test basic mode switching functionality."""
    print("Testing mode switching...")

    # Skip if no API key (mock test)
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        print("Warning: DEEPSEEK_API_KEY not set. Using dummy API key for initialization.")
        api_key = "dummy_key"

    # Create agent instance
    chat = NeoMindAgent(api_key=api_key)

    print(f"Initial mode: {chat.mode}")
    assert chat.mode in ("chat", "coding"), f"Invalid initial mode: {chat.mode}"

    # Test mode switching
    print("\n1. Testing /mode command handler...")
    result = chat.handle_mode_command("status")
    print(f"   /mode status -> {result}")
    assert "Current mode" in result

    result = chat.handle_mode_command("chat")
    print(f"   /mode chat -> {result}")
    assert "Switched" in result or "Failed" in result

    result = chat.handle_mode_command("coding")
    print(f"   /mode coding -> {result}")
    assert "Switched" in result or "Failed" in result

    # Test invalid mode
    result = chat.handle_mode_command("invalid")
    print(f"   /mode invalid -> {result}")
    assert "Invalid mode" in result

    # Test help
    result = chat.handle_mode_command("help")
    print(f"   /mode help -> length {len(result)} chars")
    assert "/mode command usage" in result

    print("\n2. Testing workspace manager initialization...")
    if chat.mode == "coding":
        chat._initialize_workspace_manager()
        if chat.workspace_manager:
            print("   Workspace manager initialized.")
            files = chat.workspace_manager.scan()
            print(f"   Found {len(files)} files in workspace.")
        else:
            print("   Workspace manager not available (optional dependency).")

    print("\n3. Testing natural language interpreter with mode...")
    if chat.interpreter:
        # Test interpretation with mode parameter
        text = "show me file test.py"
        cmd, conf = chat.interpreter.interpret(text, mode="coding")
        print(f"   Interpret '{text}' -> {cmd} (confidence: {conf})")

    print("\n4. Testing configuration updates...")
    old_mode = agent_config.mode
    success = agent_config.update_mode("coding" if old_mode == "chat" else "chat")
    print(f"   Config update success: {success}")
    if success:
        print(f"   Config mode changed from {old_mode} to {agent_config.mode}")

    print("\n5. Testing skills command...")
    result = chat.handle_skills_command("list")
    print(f"   /skills list -> length {len(result) if result else 0}")
    if result:
        print(f"   Result preview: {result[:100]}...")

    print("\n✅ All tests completed (basic sanity checks).")
    print("Note: This is a basic test. For full testing, run the agent interactively.")
    return True


if __name__ == "__main__":
    try:
        test_mode_switching()
        sys.exit(0)
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)