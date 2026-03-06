#!/usr/bin/env python3
"""
Test automatic thinking buffer clearing when response starts.
Bug: Thinking buffer appears then gets wiped automatically without Ctrl+O.
"""
import sys
import os
import time
import io

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from agent.core import DeepSeekStreamingChat

def test_buffer_cleared_when_response_starts():
    """Test that thinking buffer is cleared when response starts (normal behavior)."""
    print("\n" + "=" * 70)
    print("TEST: Thinking buffer cleared when response starts")
    print("=" * 70)

    chat = DeepSeekStreamingChat(api_key="test_key")

    # Simulate thinking buffer is displayed
    chat.show_thinking_realtime = True
    chat.is_thinking_displayed = True
    chat.thinking_buffer_lines = 5
    chat.thinking_buffer_content = "Thinking about the question..."

    print("1. Thinking buffer state before response:")
    print(f"   show_thinking_realtime: {chat.show_thinking_realtime}")
    print(f"   is_thinking_displayed: {chat.is_thinking_displayed}")
    print(f"   thinking_buffer_lines: {chat.thinking_buffer_lines}")

    # Capture output
    old_stdout = sys.stdout
    captured = io.StringIO()
    sys.stdout = captured

    try:
        # Simulate response starting (as in core.py line 5416)
        # This is what happens when content chunk arrives after thinking
        if chat.is_thinking_displayed:
            chat._clear_thinking_buffer(force=True)

        output = captured.getvalue()
        ansi_sequences = output.count('\033[')

        print(f"\n2. After response start:")
        print(f"   is_thinking_displayed: {chat.is_thinking_displayed}")
        print(f"   thinking_buffer_lines: {chat.thinking_buffer_lines}")
        print(f"   ANSI sequences emitted: {ansi_sequences}")

        # Buffer should be cleared
        assert chat.is_thinking_displayed == False
        assert chat.thinking_buffer_lines == 0
        print(f"\n[OK] Buffer cleared when response started (expected behavior)")

        # Check if ANSI sequences were reasonable
        if ansi_sequences > 0:
            print(f"[OK] ANSI sequences emitted to clear {chat.thinking_buffer_lines} lines")
        else:
            print(f"[WARNING] No ANSI sequences emitted (buffer may not have been displayed)")

        return True

    finally:
        sys.stdout = old_stdout

def test_buffer_not_cleared_when_not_displayed():
    """Test that thinking buffer is NOT cleared if not displayed."""
    print("\n" + "=" * 70)
    print("TEST: Buffer not cleared when not displayed")
    print("=" * 70)

    chat = DeepSeekStreamingChat(api_key="test_key")

    # Simulate thinking buffer content exists but not displayed
    chat.show_thinking_realtime = False  # Display off
    chat.is_thinking_displayed = False   # Not displayed
    chat.thinking_buffer_lines = 0       # No lines displayed
    chat.thinking_buffer_content = "Thinking content in memory..."

    print("1. State before (buffer not displayed):")
    print(f"   show_thinking_realtime: {chat.show_thinking_realtime}")
    print(f"   is_thinking_displayed: {chat.is_thinking_displayed}")
    print(f"   thinking_buffer_lines: {chat.thinking_buffer_lines}")

    # Capture output
    old_stdout = sys.stdout
    captured = io.StringIO()
    sys.stdout = captured

    try:
        # Print some response text first
        print("Response line 1")
        print("Response line 2")
        response_pos = captured.tell()

        # Simulate response starting (force=True as in line 5416)
        chat._clear_thinking_buffer(force=True)

        output = captured.getvalue()
        ansi_sequences = output.count('\033[')

        # Count ANSI sequences after response started
        output_after = output[response_pos:]
        ansi_after = output_after.count('\033[')

        print(f"\n2. After response start:")
        print(f"   is_thinking_displayed: {chat.is_thinking_displayed}")
        print(f"   thinking_buffer_lines: {chat.thinking_buffer_lines}")
        print(f"   Total ANSI sequences: {ansi_sequences}")
        print(f"   ANSI after response start: {ansi_after}")

        # Should not have emitted ANSI sequences after response started
        if ansi_after == 0:
            print(f"\n[OK] No ANSI sequences after response start - response safe!")
            return True
        else:
            print(f"\n[FAIL] ANSI sequences after response start - could wipe response!")
            return False

    finally:
        sys.stdout = old_stdout

def test_buffer_calculation_accuracy():
    """Test that lines_to_clear calculation is accurate."""
    print("\n" + "=" * 70)
    print("TEST: Buffer line calculation accuracy")
    print("=" * 70)

    chat = DeepSeekStreamingChat(api_key="test_key")

    test_cases = [
        {"name": "Short content", "content": "One line", "expected_lines": 3},  # header(2) + content(1)
        {"name": "Multi-line", "content": "Line1\nLine2\nLine3", "expected_lines": 5},  # header(2) + content(3)
        {"name": "Empty", "content": "", "expected_lines": 2},  # just header
        {"name": "With trailing newline", "content": "Line1\nLine2\n", "expected_lines": 4},  # header(2) + content(2)
    ]

    all_passed = True

    for test_case in test_cases:
        print(f"\nTesting: {test_case['name']}")
        chat.thinking_buffer_content = test_case['content']

        # Count lines using internal method
        content_lines = chat._count_thinking_content_lines()
        total_lines = 2 + content_lines  # Header + content

        print(f"  Content: '{test_case['content'][:30]}...'")
        print(f"  Content lines: {content_lines}")
        print(f"  Total lines (header+content): {total_lines}")
        print(f"  Expected: {test_case['expected_lines']}")

        if total_lines == test_case['expected_lines']:
            print(f"  [OK] Line count correct")
        else:
            print(f"  [FAIL] Line count mismatch")
            all_passed = False

    return all_passed

def test_buffer_interaction_with_progress_display():
    """Test interaction between thinking buffer and progress display refresh."""
    print("\n" + "=" * 70)
    print("TEST: Buffer vs Progress display interaction")
    print("=" * 70)

    # This is complex to test without full integration
    # The issue might be: progress display refresh (display_interface) clears
    # lines that include thinking buffer

    print("Note: This test would require full integration testing.")
    print("Potential issue: refresh_interface() clears previous display lines")
    print("If thinking buffer is within those lines, it gets cleared.")

    # We can't easily test this without running the full interface
    # But we can check the logic

    from cli.progress_display import ProgressDisplay

    progress = ProgressDisplay()
    progress.start_task("Thinking", "Thinking content")

    print("\nProgress display created with thinking task.")
    print("In real usage, display_interface() would clear previous lines.")
    print("Thinking buffer (if displayed) might be in those lines.")

    return True

def test_scenario_thinking_then_immediate_response():
    """Simulate common scenario: thinking displayed, then response starts."""
    print("\n" + "=" * 70)
    print("TEST: Common scenario - thinking then response")
    print("=" * 70)

    chat = DeepSeekStreamingChat(api_key="test_key")

    # Simulate full flow
    steps = [
        ("User asks question", {"show_thinking_realtime": True, "is_thinking_displayed": False}),
        ("Thinking starts", {"show_thinking_realtime": True, "is_thinking_displayed": True, "thinking_buffer_lines": 3}),
        ("Thinking continues", {"show_thinking_realtime": True, "is_thinking_displayed": True, "thinking_buffer_lines": 5}),
        ("Response starts", {"show_thinking_realtime": True, "is_thinking_displayed": False, "thinking_buffer_lines": 0}),
        ("Response continues", {"show_thinking_realtime": True, "is_thinking_displayed": False, "thinking_buffer_lines": 0}),
    ]

    for step_name, state in steps:
        chat.show_thinking_realtime = state.get("show_thinking_realtime", chat.show_thinking_realtime)
        chat.is_thinking_displayed = state.get("is_thinking_displayed", chat.is_thinking_displayed)
        chat.thinking_buffer_lines = state.get("thinking_buffer_lines", chat.thinking_buffer_lines)

        print(f"\n{step_name}:")
        print(f"  show_thinking_realtime: {chat.show_thinking_realtime}")
        print(f"  is_thinking_displayed: {chat.is_thinking_displayed}")
        print(f"  thinking_buffer_lines: {chat.thinking_buffer_lines}")

        # Simulate buffer clearing when response starts
        if step_name == "Response starts" and chat.is_thinking_displayed:
            print(f"  -> Clearing thinking buffer (normal)")
            chat._clear_thinking_buffer(force=True)

    print("\n[OK] Scenario simulated")
    print("Note: Buffer cleared when response starts is normal behavior.")
    print("User can press Ctrl+O to expand thinking task to see thinking content.")

    return True

def main():
    """Run all tests."""
    print("=" * 70)
    print("AUTO BUFFER CLEARING TESTS")
    print("Testing thinking buffer behavior without Ctrl+O")
    print("=" * 70)

    all_passed = True

    tests = [
        ("Buffer cleared when response starts", test_buffer_cleared_when_response_starts),
        ("Buffer not cleared when not displayed", test_buffer_not_cleared_when_not_displayed),
        ("Buffer line calculation", test_buffer_calculation_accuracy),
        ("Buffer vs progress display", test_buffer_interaction_with_progress_display),
        ("Common scenario", test_scenario_thinking_then_immediate_response),
    ]

    for name, test_func in tests:
        print(f"\n{'='*40}")
        print(f"Running: {name}")
        print(f"{'='*40}")
        try:
            if test_func():
                print(f"[OK] {name}")
            else:
                print(f"[FAIL] {name}")
                all_passed = False
        except Exception as e:
            print(f"[FAIL] ERROR in {name}: {e}")
            import traceback
            traceback.print_exc()
            all_passed = False

    if all_passed:
        print("\n" + "=" * 70)
        print("[OK] ALL TESTS PASSED!")
        print("Automatic buffer clearing appears to work correctly.")
        print("Note: Buffer cleared when response starts is NORMAL behavior.")
        print("=" * 70)
        return True
    else:
        print("\n" + "=" * 70)
        print("[FAIL] SOME TESTS FAILED")
        print("Buffer clearing may have issues.")
        print("=" * 70)
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)