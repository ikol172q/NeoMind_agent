#!/usr/bin/env python3
"""
NeoMind Infrastructure Tests Runner

Runs all Phase 0 infrastructure tests and provides a summary.
"""

import sys
import subprocess
from pathlib import Path


def run_test_file(test_file: Path) -> bool:
    """Run a single test file and return success status."""
"
    try:
        result = subprocess.run(
            ["python3", "-m", "pytest", str(test_file), "-v"],
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.returncode == 0
    except Exception as e:
        print(f"❌ Error running {test_file}: {e}")
        return False


def main():
    """Run all infrastructure tests."""
    print("=" * 60)
    print("NeoMind Infrastructure Tests Runner")
    print("=" * 60)
    print()

    test_dir = Path(__file__).parent / "tests"
    test_files = [
        "test_token_budget.py",
        "test_context_builder.py",
        "test_utility_commands.py",
    ]

    results = {}
    for test_file in test_files:
        test_path = test_dir / test_file
        if test_path.exists():
            print(f"\n🔍 Running {test_file}...")
            success = run_test_file(test_path)
            results[test_file] = success
        else:
            print(f"⚠️ {test_file} not found, skipping...")
            results[test_file] = None

    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)

    passed = sum(1 for r in results.values() if r is True)
    failed = sum(1 for r in results.values() if r is False)
    skipped = sum(1 for r in results.values() if r is None)

    for test_file, test_files:
        if results[test_file] is True:
            status = "✅ PASSED"
        elif results[test_file] is False:
            status = "❌ FAILED"
        else:
            status = "⏭️ SKIPPED"
        print(f"  {test_file}: {status}")

    print(f"\nTotal: {passed} passed, {failed} failed, {skipped} skipped")

    if failed > 0:
        print("\n❌ Some tests failed!")
        sys.exit(1)
    else:
        print("\n✅ All infrastructure tests passed!")
        sys.exit(0)


if __name__ == "__main__":
    main()
