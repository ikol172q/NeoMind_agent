#!/usr/bin/env python3
"""
Test runner for comprehensive unit tests.
Run all tests or specific test modules.
"""
import os
import sys
import unittest
import argparse

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def run_all_tests():
    """Run all tests in the tests directory."""
    loader = unittest.TestLoader()
    start_dir = os.path.dirname(os.path.abspath(__file__))
    suite = loader.discover(start_dir, pattern="test_*.py")

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()

def run_module_tests(module_name):
    """Run tests for a specific module."""
    # Remove .py extension if present
    if module_name.endswith('.py'):
        module_name = module_name[:-3]

    # Import the test module
    import importlib
    try:
        module = importlib.import_module(f"tests.{module_name}")
    except ImportError:
        print(f"Error: Test module '{module_name}' not found.")
        return False

    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(module)

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()

def list_test_modules():
    """List all available test modules."""
    test_dir = os.path.dirname(os.path.abspath(__file__))
    test_files = []

    for file in os.listdir(test_dir):
        if file.startswith("test_") and file.endswith(".py"):
            test_files.append(file)

    print("Available test modules:")
    for test_file in sorted(test_files):
        print(f"  {test_file}")

    return test_files

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Run comprehensive unit tests")
    parser.add_argument("--module", "-m", help="Run specific test module (without .py extension)")
    parser.add_argument("--list", "-l", action="store_true", help="List all test modules")
    parser.add_argument("--all", "-a", action="store_true", help="Run all tests (default)")

    args = parser.parse_args()

    if args.list:
        list_test_modules()
        return 0

    if args.module:
        success = run_module_tests(args.module)
    else:
        # Default: run all tests
        success = run_all_tests()

    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())