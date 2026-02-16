#!/usr/bin/env python3
"""
Dev test script for user-agent.
Quickly verify agent functionality without full installation.
"""

import sys
import os
import importlib.util

def check_import(module_name, package_name=None, required=True):
    """Check if a module can be imported."""
    try:
        if package_name:
            mod = importlib.import_module(module_name, package=package_name)
        else:
            mod = importlib.import_module(module_name)
        print(f"[OK] {module_name} imported successfully")
        return True, mod
    except ImportError as e:
        if required:
            print(f"[FAIL] Failed to import required module {module_name}: {e}")
            return False, None
        else:
            print(f"[WARN] Failed to import optional module {module_name}: {e}")
            return True, None  # Treat as success for optional dependencies

def test_configuration():
    """Test configuration system."""
    print("\n=== Testing Configuration ===")

    success, agent_config = check_import("agent_config")
    if not success:
        return False

    try:
        config = agent_config.agent_config
        print(f"  Config path: {config.config_path}")
        print(f"  Model: {config.model}")
        print(f"  Temperature: {config.temperature}")
        print(f"  Max tokens: {config.max_tokens}")
        print(f"  Thinking enabled: {config.thinking_enabled}")
        print(f"  System prompt: {'Set' if config.system_prompt else 'Not set'}")

        # Test config update
        test_key = "agent.temperature"
        original = config.temperature
        success = config.update_value(test_key, original)
        if success:
            print(f"  Config update test: OK")
        else:
            print(f"  Config update test: FAILED")
            return False

        return True
    except Exception as e:
        print(f"  Configuration test error: {e}")
        return False

def test_agent_core():
    """Test agent core module imports."""
    print("\n=== Testing Agent Core ===")

    # Check agent module (optional - depends on html2text etc.)
    success, agent_module = check_import("agent", required=False)
    if not success:
        print("  Note: Agent core requires optional dependencies")
        print("  Install with: pip install -e .[full]")
        return True  # Not required for basic functionality

    # Check specific classes
    try:
        from agent.core import DeepSeekStreamingChat
        print("[OK] DeepSeekStreamingChat class available")
    except ImportError as e:
        print(f"[WARN] DeepSeekStreamingChat import failed: {e}")
        print("  Note: Agent functionality limited")

    try:
        from agent.search import OptimizedDuckDuckGoSearch
        print("[OK] OptimizedDuckDuckGoSearch class available")
    except ImportError as e:
        print(f"[WARN] OptimizedDuckDuckGoSearch import failed: {e}")
        print("  (Note: search module may require additional dependencies)")

    return True

def test_cli():
    """Test CLI module."""
    print("\n=== Testing CLI ===")

    # CLI depends on agent, so it's also optional
    success, cli_module = check_import("cli.interface", required=False)
    if not success:
        print("  Note: CLI requires optional dependencies")
        print("  Install with: pip install -e .[full]")
        return True  # Not required for basic functionality

    try:
        from cli.interface import interactive_chat_fallback, handle_command
        print("[OK] CLI functions available")
        return True
    except ImportError as e:
        print(f"[WARN] CLI function import failed: {e}")
        return True  # Optional

def test_api_key():
    """Check if API key is set."""
    print("\n=== Testing API Key ===")

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if api_key:
        print(f"[OK] DEEPSEEK_API_KEY is set ({len(api_key)} chars)")
        return True
    else:
        print("[WARN] DEEPSEEK_API_KEY not set in environment")
        print("  Note: Agent will need API key to function")
        return True  # Warning only

def run_tests():
    """Run all tests and return True if all required tests passed."""
    print("user-agent Development Test")
    print("=" * 60)

    required_ok = True
    optional_ok = True

    # Test 1: Configuration (required)
    print("\n1. Required Tests:")
    if not test_configuration():
        required_ok = False

    # Test 2: API key (warning only)
    test_api_key()

    # Test 3: Optional components
    print("\n2. Optional Tests (full installation):")
    if not test_agent_core():
        optional_ok = False
    if not test_cli():
        optional_ok = False

    print("\n" + "=" * 60)
    if required_ok:
        print("[OK] All required tests passed!")
        if not optional_ok:
            print("[WARN] Some optional components missing")
            print("  For full functionality: pip install -e .[full]")
        print("\nYou can run the agent using:")
        print("  python main.py                     # Interactive chat")
        print("  user-agent                    # If installed")
        print("  python -m user_agent          # Module execution")
        print("\nUse /models list to see available models")
        print("Use /think to toggle thinking mode")
        print("Use /test to run these tests from within the agent")
        return True
    else:
        print("[FAIL] Required tests failed.")
        print("Check dependencies: pip install -e .[full]")
        return False

def main():
    """Entry point for standalone execution."""
    success = run_tests()
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()