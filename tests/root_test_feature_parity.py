#!/usr/bin/env python3
"""
Quick test to verify feature parity implementation.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.core import NeoMindAgent

def test_instantiation():
    """Test that agent can be instantiated with new handlers."""
    try:
        agent = NeoMindAgent(api_key="dummy_key")
        print("OK - Agent instantiated successfully")

        # Check command handlers
        expected_commands = [
            "/search", "/auto", "/models", "/task", "/plan", "/execute",
            "/switch", "/summarize", "/translate", "/generate", "/reason",
            "/debug", "/explain", "/refactor", "/grep", "/find", "/clear",
            "/history", "/think", "/quit", "/exit", "/help", "/diff",
            "/browse", "/undo", "/test", "/apply", "/read", "/write",
            "/edit", "/run", "/git", "/code", "/fix", "/analyze",
            "/mode", "/skills", "/skill"
        ]
        missing = []
        for cmd in expected_commands:
            if cmd not in agent.command_handlers:
                missing.append(cmd)
        if missing:
            print(f"FAIL - Missing command handlers: {missing}")
            return False
        else:
            print(f"OK - All {len(expected_commands)} commands registered")

        # Check task manager
        if hasattr(agent, 'task_manager'):
            print("OK - Task manager present")
        else:
            print("FAIL - Task manager missing")
            return False

        # Check goal planner
        if hasattr(agent, 'goal_planner'):
            print("OK - Goal planner present")
        else:
            print("FAIL - Goal planner missing")
            return False

        # Test help system
        try:
            help_text = agent.help_system.get_help()
            if "Available Commands" in help_text:
                print("OK - Help system working")
            else:
                print("FAIL - Help system not returning expected text")
        except Exception as e:
            print(f"FAIL - Help system error: {e}")
            return False

        print("\nSUCCESS - Feature parity implementation appears successful!")
        return True

    except Exception as e:
        print(f"ERROR - Error during test: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_instantiation()
    sys.exit(0 if success else 1)