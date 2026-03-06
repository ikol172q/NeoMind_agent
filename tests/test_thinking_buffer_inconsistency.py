#!/usr/bin/env python3
"""
Test for thinking buffer inconsistency bug.
Scenario: is_thinking_displayed=False but thinking_buffer_lines>0
This could cause _clear_thinking_buffer(force=True) to emit ANSI sequences
even when buffer is not displayed, potentially wiping response.
"""
import sys
import os
import io

# Mock dependencies before importing
sys.modules['requests'] = type(sys)('requests')
sys.modules['anthropic'] = type(sys)('anthropic')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.core import DeepSeekStreamingChat

def test_inconsistent_state_lines_gt_zero():
    """Test _clear_thinking_buffer with is_thinking_displayed=False, thinking_buffer_lines>0"""
    print("\n" + "=" * 70)
    print("TEST: Inconsistent state - not displayed but lines>0")
    print("=" * 70)

    chat = DeepSeekStreamingChat(api_key="test_key")

    # Set inconsistent state: not displayed but line count > 0
    # This could happen due to race conditions or bugs elsewhere
    chat.is_thinking_displayed = False
    chat.thinking_buffer_lines = 5  # Should be 0 if not displayed!
    chat.thinking_buffer_content = "Some thinking content"

    # Capture stdout
    old_stdout = sys.stdout
    captured = io.StringIO()
    sys.stdout = captured

    try:
        # Print some response text first
        print("Agent: This is the response.")
        print("It should remain visible.")
        response_pos = captured.tell()

        # Call _clear_thinking_buffer as Ctrl+O would (force=True)
        chat._clear_thinking_buffer(force=True)

        output = captured.getvalue()
        ansi_sequences = output.count('\033[')

        # Count ANSI sequences after response started
        output_after = output[response_pos:]
        ansi_after = output_after.count('\033[')

        print(f"State before: is_thinking_displayed=False, thinking_buffer_lines=5")
        print(f"Total ANSI sequences: {ansi_sequences}")
        print(f"ANSI sequences after response: {ansi_after}")

        # Check final state
        print(f"State after: is_thinking_displayed={chat.is_thinking_displayed}, thinking_buffer_lines={chat.thinking_buffer_lines}")

        if ansi_after > 0:
            print("[FAIL] ANSI sequences emitted despite buffer not displayed!")
            print(f"Output after response: {repr(output_after[:200])}")
            return False
        else:
            print("[OK] No ANSI sequences after response")

            # Also check that state was corrected
            if chat.thinking_buffer_lines == 0:
                print("[OK] State corrected: thinking_buffer_lines reset to 0")
                return True
            else:
                print("[FAIL] State not corrected: thinking_buffer_lines still {chat.thinking_buffer_lines}")
                return False

    finally:
        sys.stdout = old_stdout

def test_displayed_with_lines_zero():
    """Test _clear_thinking_buffer with is_thinking_displayed=True, thinking_buffer_lines=0"""
    print("\n" + "=" * 70)
    print("TEST: Inconsistent state - displayed but lines=0")
    print("=" * 70)

    chat = DeepSeekStreamingChat(api_key="test_key")

    # Another inconsistent state: displayed but line count = 0
    chat.is_thinking_displayed = True
    chat.thinking_buffer_lines = 0  # Should be >0 if displayed!
    chat.thinking_buffer_content = "Thinking content"

    old_stdout = sys.stdout
    captured = io.StringIO()
    sys.stdout = captured

    try:
        print("Response before clear")
        response_pos = captured.tell()

        chat._clear_thinking_buffer(force=False)

        output = captured.getvalue()
        ansi_sequences = output.count('\033[')
        output_after = output[response_pos:]
        ansi_after = output_after.count('\033[')

        print(f"State before: is_thinking_displayed=True, thinking_buffer_lines=0")
        print(f"ANSI sequences after response: {ansi_after}")
        print(f"State after: is_thinking_displayed={chat.is_thinking_displayed}, thinking_buffer_lines={chat.thinking_buffer_lines}")

        if ansi_after > 0:
            print("[FAIL] ANSI sequences emitted with lines=0!")
            return False
        else:
            print("[OK] No ANSI sequences (early return due to inconsistency)")
            return True

    finally:
        sys.stdout = old_stdout

def test_lines_calculation_accuracy():
    """Test that thinking_buffer_lines accurately reflects displayed content"""
    print("\n" + "=" * 70)
    print("TEST: thinking_buffer_lines calculation accuracy")
    print("=" * 70)

    chat = DeepSeekStreamingChat(api_key="test_key")

    # Simulate thinking display
    chat.is_thinking_displayed = False  # Will become True after first chunk
    chat.thinking_buffer_content = ""

    old_stdout = sys.stdout
    captured = io.StringIO()
    sys.stdout = captured

    try:
        # Simulate displaying thinking chunks
        chunks = [
            "First line of thinking\n",
            "Second line\n",
            "Third line without newline"
        ]

        for i, chunk in enumerate(chunks):
            chat.thinking_buffer_content += chunk
            chat._display_thinking_chunk(chunk, colors_enabled=False)

            print(f"After chunk {i+1}: lines={chat.thinking_buffer_lines}, displayed={chat.is_thinking_displayed}")

            # Check consistency
            if chat.is_thinking_displayed and chat.thinking_buffer_lines <= 2:
                print(f"[WARNING] Displayed but lines={chat.thinking_buffer_lines} (expected >2)")

        # Now clear
        print(f"\nBefore clear: lines={chat.thinking_buffer_lines}, displayed={chat.is_thinking_displayed}")
        chat._clear_thinking_buffer(force=False)
        print(f"After clear: lines={chat.thinking_buffer_lines}, displayed={chat.is_thinking_displayed}")

        # Call clear again (should early return)
        chat._clear_thinking_buffer(force=True)

        output = captured.getvalue()
        ansi_count = output.count('\033[')

        print(f"Total ANSI sequences: {ansi_count}")

        # Check final state
        if chat.thinking_buffer_lines == 0 and not chat.is_thinking_displayed:
            print("[OK] Final state consistent")
            return True
        else:
            print(f"[FAIL] Inconsistent final state: lines={chat.thinking_buffer_lines}, displayed={chat.is_thinking_displayed}")
            return False

    finally:
        sys.stdout = old_stdout

def test_simulate_ctrl_o_after_response():
    """Simulate exact Ctrl+O scenario after response starts"""
    print("\n" + "=" * 70)
    print("TEST: Simulate Ctrl+O after response with inconsistent state")
    print("=" * 70)

    chat = DeepSeekStreamingChat(api_key="test_key")

    # Simulate state after thinking stops and response started
    # But with inconsistency: lines > 0 (bug!)
    chat.is_thinking_displayed = False
    chat.thinking_buffer_lines = 3  # BUG: Should be 0!
    chat.thinking_buffer_content = "Thinking content from before"
    chat.is_reasoning_active = False
    chat.show_thinking_realtime = True  # Display was ON during thinking

    old_stdout = sys.stdout
    captured = io.StringIO()
    sys.stdout = captured

    try:
        # Print response
        print("🤖 Assistant: Here is my answer to your question.")
        print("The answer has multiple lines.")
        print("All lines should remain visible.")

        response_pos = captured.tell()

        # Simulate Ctrl+O press turning OFF thinking display
        # This is what happens in default branch:
        # was_enabled = chat.show_thinking_realtime (True)
        # chat.toggle_thinking_display() -> becomes False
        # is_enabled = chat.show_thinking_realtime (False)
        # was_enabled and not is_enabled -> True
        # chat._clear_thinking_buffer(force=True)

        was_enabled = chat.show_thinking_realtime
        chat.toggle_thinking_display()
        is_enabled = chat.show_thinking_realtime

        print(f"\nToggle: {was_enabled} -> {is_enabled}")

        if was_enabled and not is_enabled:
            print("Calling _clear_thinking_buffer(force=True)...")
            chat._clear_thinking_buffer(force=True)

        output = captured.getvalue()
        ansi_after = output[response_pos:].count('\033[')

        print(f"\nANSI sequences after response: {ansi_after}")
        print(f"Final state: lines={chat.thinking_buffer_lines}, displayed={chat.is_thinking_displayed}")

        if ansi_after > 0:
            print("[FAIL] ANSI sequences emitted - could wipe response!")
            # Show what was emitted
            output_after = output[response_pos:]
            lines = output_after.split('\n')
            for i, line in enumerate(lines):
                if '\033[' in line:
                    print(f"  Line {i}: {repr(line[:100])}")
            return False
        else:
            print("[OK] No ANSI sequences - response safe")
            return True

    finally:
        sys.stdout = old_stdout

def main():
    """Run all inconsistency tests."""
    print("=" * 70)
    print("THINKING BUFFER INCONSISTENCY TESTS")
    print("Testing edge cases that could cause response wiping")
    print("=" * 70)

    tests = [
        ("Not displayed but lines>0", test_inconsistent_state_lines_gt_zero),
        ("Displayed but lines=0", test_displayed_with_lines_zero),
        ("Lines calculation accuracy", test_lines_calculation_accuracy),
        ("Simulate Ctrl+O after response", test_simulate_ctrl_o_after_response),
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
        print("\n[OK] All inconsistency tests passed!")
        print("The _clear_thinking_buffer method handles inconsistent states correctly.")
        return True
    else:
        print(f"\n[FAIL] {failed} test(s) failed")
        print("There may be bugs in thinking buffer state management.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)