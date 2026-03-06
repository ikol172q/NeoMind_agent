#!/usr/bin/env python3
"""
Direct verification that the fix in _clear_thinking_buffer works.
Tests the actual method with the fix applied.
"""
import sys
import os
import io
import time

# Mock dependencies before importing
sys.modules['requests'] = type(sys)('requests')
sys.modules['anthropic'] = type(sys)('anthropic')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from agent.core import DeepSeekStreamingChat

def test_fix_scenario_1():
    """
    Scenario: Buffer not displayed, lines=0 (state after thinking cleared).
    Ctrl+O pressed - should NOT emit ANSI sequences.
    """
    print("Test 1: Buffer not displayed, lines=0 (after thinking cleared)")

    chat = DeepSeekStreamingChat(api_key="test_key")

    # Set state as it would be after thinking stops and buffer cleared
    chat.is_thinking_displayed = False
    chat.thinking_buffer_lines = 0
    chat.thinking_buffer_content = ""  # May have content in memory

    # Capture stdout
    old_stdout = sys.stdout
    captured = io.StringIO()
    sys.stdout = captured

    try:
        # Simulate some output (like response)
        print("Response line 1")
        print("Response line 2")
        response_pos = captured.tell()

        # Call _clear_thinking_buffer as Ctrl+O would
        chat._clear_thinking_buffer(force=True)

        output = captured.getvalue()
        ansi_sequences = output.count('\033[')

        print(f"ANSI sequences emitted: {ansi_sequences}")

        if ansi_sequences == 0:
            print("[OK] No ANSI sequences - response safe!")
            return True
        else:
            print("[FAIL] ANSI sequences emitted - could wipe response!")
            return False

    finally:
        sys.stdout = old_stdout

def test_fix_scenario_2():
    """
    Scenario: Buffer displayed with content.
    Ctrl+O pressed - SHOULD emit ANSI sequences to clear.
    """
    print("\nTest 2: Buffer displayed with content (should clear)")

    chat = DeepSeekStreamingChat(api_key="test_key")

    # Set state: thinking is being displayed
    chat.is_thinking_displayed = True
    chat.thinking_buffer_lines = 5
    chat.thinking_buffer_content = "Thinking\nlines\n"

    old_stdout = sys.stdout
    captured = io.StringIO()
    sys.stdout = captured

    try:
        chat._clear_thinking_buffer(force=False)
        output = captured.getvalue()
        ansi_sequences = output.count('\033[')

        print(f"ANSI sequences emitted: {ansi_sequences}")

        if ansi_sequences > 0:
            print("[OK] ANSI sequences emitted to clear displayed buffer")
            return True
        else:
            print("[FAIL] No ANSI sequences despite displayed buffer")
            return False

    finally:
        sys.stdout = old_stdout

def test_fix_scenario_3():
    """
    Scenario: Content in memory but not displayed (lines=0).
    Should early return without ANSI sequences.
    """
    print("\nTest 3: Content in memory but not displayed (lines=0)")

    chat = DeepSeekStreamingChat(api_key="test_key")

    # Content exists but was cleared from screen
    chat.is_thinking_displayed = False
    chat.thinking_buffer_lines = 0
    chat.thinking_buffer_content = "Thinking content that was cleared"

    old_stdout = sys.stdout
    captured = io.StringIO()
    sys.stdout = captured

    try:
        chat._clear_thinking_buffer(force=True)
        output = captured.getvalue()
        ansi_sequences = output.count('\033[')

        print(f"ANSI sequences emitted: {ansi_sequences}")

        if ansi_sequences == 0:
            print("[OK] Early return prevented clearing")
            return True
        else:
            print("[FAIL] ANSI sequences emitted despite not displayed")
            return False

    finally:
        sys.stdout = old_stdout

def test_fix_scenario_4():
    """
    Scenario: Rapid successive calls (simulating multiple Ctrl+O presses).
    First call clears buffer, subsequent calls should early return.
    """
    print("\nTest 4: Rapid successive calls (multiple Ctrl+O)")

    chat = DeepSeekStreamingChat(api_key="test_key")

    # Start with displayed buffer
    chat.is_thinking_displayed = True
    chat.thinking_buffer_lines = 4
    chat.thinking_buffer_content = "Thinking"

    old_stdout = sys.stdout
    captured = io.StringIO()
    sys.stdout = captured

    try:
        # First call: should clear
        chat._clear_thinking_buffer(force=True)
        output1 = captured.getvalue()
        ansi1 = output1.count('\033[')

        print(f"First call: {ansi1} ANSI sequences")

        # Second call: buffer already cleared, should early return
        chat._clear_thinking_buffer(force=True)
        output2 = captured.getvalue()
        ansi2 = output2.count('\033[') - ansi1

        print(f"Second call: {ansi2} ANSI sequences")

        # Third call: still should early return
        chat._clear_thinking_buffer(force=True)
        output3 = captured.getvalue()
        ansi3 = output3.count('\033[') - ansi2 - ansi1

        print(f"Third call: {ansi3} ANSI sequences")

        if ansi1 > 0 and ansi2 == 0 and ansi3 == 0:
            print("[OK] Only first call emitted ANSI, subsequent early returns")
            return True
        else:
            print("[FAIL] Unexpected ANSI sequence pattern")
            return False

    finally:
        sys.stdout = old_stdout

def test_fix_scenario_5():
    """
    Scenario: Simulate exact bug - thinking stops, response printed, Ctrl+O.
    """
    print("\nTest 5: Exact bug scenario - thinking→response→Ctrl+O")

    chat = DeepSeekStreamingChat(api_key="test_key")

    # Simulate thinking was displayed, then cleared when response started
    chat.is_thinking_displayed = False
    chat.thinking_buffer_lines = 0
    chat.thinking_buffer_content = ""

    old_stdout = sys.stdout
    captured = io.StringIO()
    sys.stdout = captured

    try:
        # Print a response (as would happen in real usage)
        print("Agent: Here is my response to your question.")
        print("It has multiple lines of useful information.")
        print("You should see all of this clearly.")

        response_pos = captured.tell()

        # Simulate Ctrl+O press calling _clear_thinking_buffer
        # This is what happens in default branch when turning OFF
        chat._clear_thinking_buffer(force=True)

        output = captured.getvalue()
        total_ansi = output.count('\033[')

        # Count ANSI sequences after response started
        output_after = output[response_pos:]
        ansi_after = output_after.count('\033[')

        print(f"Total ANSI sequences: {total_ansi}")
        print(f"ANSI sequences after response started: {ansi_after}")

        if ansi_after == 0:
            print("[OK] No ANSI sequences after response started - response safe!")
            return True
        else:
            print("[FAIL] ANSI sequences after response - could wipe response!")
            return False

    finally:
        sys.stdout = old_stdout

def main():
    """Run all fix verification tests."""
    print("=" * 70)
    print("DIRECT VERIFICATION OF _clear_thinking_buffer FIX")
    print("Testing the actual method with the fix applied")
    print("=" * 70)

    tests = [
        ("Buffer not displayed, lines=0", test_fix_scenario_1),
        ("Buffer displayed with content", test_fix_scenario_2),
        ("Content in memory, not displayed", test_fix_scenario_3),
        ("Rapid successive calls", test_fix_scenario_4),
        ("Exact bug scenario", test_fix_scenario_5),
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        try:
            print(f"\n{'='*40}")
            print(f"Running: {name}")
            print(f"{'='*40}")
            if test_func():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"ERROR in test: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\n{'='*70}")
    print(f"RESULTS: {passed} passed, {failed} failed")
    print(f"{'='*70}")

    if failed == 0:
        print("\n[OK] ALL TESTS PASSED!")
        print("The fix correctly prevents response wiping.")
        return True
    else:
        print(f"\n[FAIL] {failed} test(s) failed")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)