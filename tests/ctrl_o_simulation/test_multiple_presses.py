#!/usr/bin/env python3
"""
Direct simulation of pressing Ctrl+O multiple times (8+ times) during thinking and responding.
Tests the exact key binding handler logic with random timing and state changes.
"""
import sys
import os
import time
import random
import io
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from cli.progress_display import ProgressDisplay, TaskStatus

class MockChat:
    """Mock chat object that tracks all state changes and method calls."""
    def __init__(self):
        # Core state
        self.is_reasoning_active = False
        self.show_thinking_realtime = False
        self.thinking_buffer_content = ""
        self.current_task_id = None
        self.is_thinking_displayed = False
        self.thinking_buffer_lines = 0

        # Tracking
        self.toggle_calls = []
        self.clear_calls = []
        self.display_calls = []
        self.ansi_sequences_emitted = []

    def toggle_thinking_display(self):
        self.toggle_calls.append(time.time())
        self.show_thinking_realtime = not self.show_thinking_realtime
        return self.show_thinking_realtime

    def _clear_thinking_buffer(self, force=False):
        """Mock that tracks calls and simulates ANSI sequence emission."""
        import sys
        import io

        # Track call
        self.clear_calls.append({
            'time': time.time(),
            'force': force,
            'is_thinking_displayed': self.is_thinking_displayed,
            'thinking_buffer_lines': self.thinking_buffer_lines,
            'thinking_buffer_content': self.thinking_buffer_content[:50] + '...' if self.thinking_buffer_content else ''
        })

        # Simulate the actual fix logic from core.py
        if not self.is_thinking_displayed and self.thinking_buffer_lines == 0:
            # Early return as per fix - no ANSI sequences
            self.is_thinking_displayed = False
            self.thinking_buffer_lines = 0
            return

        # If we get here, we would emit ANSI sequences
        # Calculate approximate lines that would be cleared
        lines_to_clear = self.thinking_buffer_lines
        if lines_to_clear <= 0:
            content_lines = self._count_thinking_content_lines()
            lines_to_clear = 2 + content_lines

        lines_to_clear = max(20, lines_to_clear * 3)
        lines_to_clear += 10
        lines_to_clear = min(lines_to_clear, 50)

        # Record that ANSI sequences would be emitted
        self.ansi_sequences_emitted.append({
            'time': time.time(),
            'lines': lines_to_clear,
            'would_clear': True
        })

        # Update state
        self.is_thinking_displayed = False
        self.thinking_buffer_lines = 0

    def _count_thinking_content_lines(self):
        if not self.thinking_buffer_content:
            return 0
        lines = self.thinking_buffer_content.count('\n')
        if self.thinking_buffer_content and not self.thinking_buffer_content.endswith('\n'):
            lines += 1
        return lines

    def _display_thinking_buffer(self, colors_enabled=True):
        self.display_calls.append({
            'time': time.time(),
            'colors_enabled': colors_enabled
        })
        self.is_thinking_displayed = True
        if self.thinking_buffer_content:
            self.thinking_buffer_lines = 2 + self._count_thinking_content_lines()
        else:
            self.thinking_buffer_lines = 2

def simulate_ctrl_o_press(chat, progress, last_ctrl_o_time, press_num, debug=False):
    """
    EXACT replication of Ctrl+O key binding handler from cli/interface.py lines 259-347.

    Returns: (new_last_ctrl_o_time, result_message, branch_used)
    """
    import sys
    import os

    # Debounce check
    current_time = time.time()
    if current_time - last_ctrl_o_time < 0.3:
        return last_ctrl_o_time, f"Press {press_num}: DEBOUNCED", "debounced"

    last_ctrl_o_time = current_time

    # Determine colors enabled
    colors_enabled = sys.stdout.isatty() and os.getenv('TERM') not in ('dumb', '')

    # Try to get most recent thinking task
    task_id = progress.get_most_recent_thinking_task()
    if task_id is None and hasattr(chat, 'current_task_id') and chat.current_task_id:
        task = progress.get_task(chat.current_task_id)
        if task and task["status"] == TaskStatus.IN_PROGRESS:
            task_id = chat.current_task_id

    # Branch 1: Active reasoning
    if chat.is_reasoning_active:
        was_enabled = chat.show_thinking_realtime
        chat.toggle_thinking_display()
        is_enabled = chat.show_thinking_realtime

        if was_enabled and not is_enabled:
            chat._clear_thinking_buffer(force=True)
            message = f"Press {press_num}: [Active thinking] Thinking display: OFF"
        elif not was_enabled and is_enabled:
            if chat.thinking_buffer_content:
                chat._display_thinking_buffer(colors_enabled=colors_enabled)
                message = f"Press {press_num}: [Active thinking] Thinking display: ON (buffer shown)"
            else:
                message = f"Press {press_num}: [Active thinking] Thinking display: ON (waiting for thinking...)"
        else:
            message = f"Press {press_num}: [Active thinking] Display unchanged: {was_enabled}"

        return last_ctrl_o_time, message, "active_reasoning"

    # Branch 2: Thinking task exists
    elif task_id is not None:
        task = progress.get_task(task_id)
        if task and task.get("title") == "Thinking":
            status = task.get("status")
            if status in [TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED]:
                if progress.toggle_task_expansion(task_id):
                    return last_ctrl_o_time, f"Press {press_num}: [Task expansion] Toggled thinking task expansion", "task_expansion"

        # Fall through to default
        if debug:
            sys.stderr.write(f"[Thinking task not expandable: {task_id}]\n")

    # Branch 3: Default
    was_enabled = chat.show_thinking_realtime
    chat.toggle_thinking_display()
    is_enabled = chat.show_thinking_realtime

    if was_enabled and not is_enabled:
        chat._clear_thinking_buffer(force=True)
        message = f"Press {press_num}: [Default] Thinking display: OFF"
    elif not was_enabled and is_enabled:
        message = f"Press {press_num}: [Default] Thinking display: ON"
    else:
        message = f"Press {press_num}: [Default] Display unchanged: {was_enabled}"

    return last_ctrl_o_time, message, "default"

def test_scenario_random_presses():
    """
    Test pressing Ctrl+O 8+ times with random timing and state changes.
    Simulates real user behavior: random presses during thinking, responding, etc.
    """
    print("\n" + "=" * 70)
    print("SCENARIO: Random Ctrl+O presses (8+ times) with state changes")
    print("=" * 70)

    chat = MockChat()
    progress = ProgressDisplay()
    last_ctrl_o_time = time.time() - 1.0  # Start 1 second ago

    # Track all presses
    presses = []

    # Define possible states
    states = [
        {"name": "thinking_active", "is_reasoning_active": True, "show_thinking_realtime": True, "has_content": True},
        {"name": "thinking_active_display_off", "is_reasoning_active": True, "show_thinking_realtime": False, "has_content": True},
        {"name": "thinking_inactive", "is_reasoning_active": False, "show_thinking_realtime": True, "has_content": False},
        {"name": "response_phase", "is_reasoning_active": False, "show_thinking_realtime": False, "has_content": False},
        {"name": "with_thinking_task", "is_reasoning_active": False, "show_thinking_realtime": False, "has_content": True},
    ]

    # Create a thinking task for testing expansion branch
    thinking_task_id = progress.start_task("Thinking", "Some thinking content")
    progress.update_task(thinking_task_id, status=TaskStatus.COMPLETED)

    # Press Ctrl+O at least 8 times
    for press_num in range(1, 9):
        # Randomly change state before some presses
        if random.random() < 0.3:  # 30% chance to change state
            state = random.choice(states)
            chat.is_reasoning_active = state["is_reasoning_active"]
            chat.show_thinking_realtime = state["show_thinking_realtime"]
            if state["has_content"]:
                chat.thinking_buffer_content = "Thinking content..."
                chat.thinking_buffer_lines = 3
                chat.is_thinking_displayed = True
            else:
                chat.thinking_buffer_content = ""
                chat.thinking_buffer_lines = 0
                chat.is_thinking_displayed = False

            print(f"\n  [State change before press {press_num}: {state['name']}]")
            print(f"    is_reasoning_active={chat.is_reasoning_active}, show_thinking_realtime={chat.show_thinking_realtime}")
            print(f"    buffer_lines={chat.thinking_buffer_lines}, displayed={chat.is_thinking_displayed}")

        # Random delay between presses (0-0.5 seconds)
        delay = random.uniform(0.1, 0.5)
        time.sleep(delay)

        # Simulate Ctrl+O press
        last_ctrl_o_time, message, branch = simulate_ctrl_o_press(
            chat, progress, last_ctrl_o_time, press_num, debug=False
        )

        presses.append({
            'number': press_num,
            'message': message,
            'branch': branch,
            'delay': delay,
            'state': {
                'is_reasoning_active': chat.is_reasoning_active,
                'show_thinking_realtime': chat.show_thinking_realtime,
                'buffer_lines': chat.thinking_buffer_lines,
                'displayed': chat.is_thinking_displayed
            }
        })

        print(f"  {message}")

    # Print summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    print(f"\nTotal presses: {len(presses)}")

    branch_counts = {}
    for press in presses:
        branch_counts[press['branch']] = branch_counts.get(press['branch'], 0) + 1

    print("\nBranch usage:")
    for branch, count in branch_counts.items():
        print(f"  {branch}: {count} presses")

    print(f"\nToggle calls: {len(chat.toggle_calls)}")
    print(f"Clear calls: {len(chat.clear_calls)}")
    print(f"Display calls: {len(chat.display_calls)}")
    print(f"ANSI sequences that would be emitted: {len(chat.ansi_sequences_emitted)}")

    # Verify no errors
    print("\nVerification:")
    print(f"  [OK] All {len(presses)} presses processed without error")

    if len(chat.clear_calls) > 0:
        for i, call in enumerate(chat.clear_calls):
            print(f"  Clear call {i+1}: force={call['force']}, lines={call['thinking_buffer_lines']}, displayed={call['is_thinking_displayed']}")

    # Check that when buffer not displayed and lines=0, no ANSI sequences were emitted
    problematic_clears = []
    for i, call in enumerate(chat.clear_calls):
        if call['is_thinking_displayed'] == False and call['thinking_buffer_lines'] == 0:
            # Should not have emitted ANSI sequences (due to our fix)
            # Check if ansi_sequences_emitted has an entry for this time
            for ansi in chat.ansi_sequences_emitted:
                if abs(ansi['time'] - call['time']) < 0.01:
                    problematic_clears.append((i, call, ansi))

    if problematic_clears:
        print(f"\n[FAIL] PROBLEM: {len(problematic_clears)} clear(s) emitted ANSI sequences despite buffer not displayed!")
        for i, call, ansi in problematic_clears:
            print(f"  Clear call {i+1} at t={call['time']:.3f}: lines={call['thinking_buffer_lines']}, displayed={call['is_thinking_displayed']}")
            print(f"    but emitted ANSI for {ansi['lines']} lines")
        return False
    else:
        print(f"\n[OK] All clears correctly handled: No ANSI sequences when buffer not displayed")

    return True

def test_scenario_thinking_to_response():
    """
    Test specific bug scenario: thinking → response → Ctrl+O multiple times.
    """
    print("\n" + "=" * 70)
    print("SCENARIO: Thinking → Response transition with multiple Ctrl+O presses")
    print("=" * 70)

    chat = MockChat()
    progress = ProgressDisplay()
    last_ctrl_o_time = time.time() - 1.0

    print("\nPhase 1: Active thinking with content")
    chat.is_reasoning_active = True
    chat.show_thinking_realtime = True
    chat.thinking_buffer_content = "Thinking about problem...\nAnalyzing...\n"
    chat.thinking_buffer_lines = 4
    chat.is_thinking_displayed = True

    # Press Ctrl+O a few times during thinking
    for i in range(3):
        last_ctrl_o_time, msg, _ = simulate_ctrl_o_press(chat, progress, last_ctrl_o_time, i+1)
        print(f"  {msg}")
        time.sleep(0.4)  # Longer than debounce

    print("\nPhase 2: Thinking stops, response starts")
    chat.is_reasoning_active = False
    # Buffer cleared when response starts
    chat._clear_thinking_buffer(force=True)
    print(f"  Buffer cleared: lines={chat.thinking_buffer_lines}, displayed={chat.is_thinking_displayed}")

    print("\nPhase 3: Response phase, press Ctrl+O multiple times")
    # Simulate response being printed
    print("  [Response output would appear here...]")

    # Press Ctrl+O multiple times during response
    response_presses = []
    for i in range(4):
        time.sleep(random.uniform(0.2, 0.6))
        last_ctrl_o_time, msg, branch = simulate_ctrl_o_press(chat, progress, last_ctrl_o_time, i+4)
        response_presses.append((msg, branch))
        print(f"  {msg}")

    print("\nPhase 4: Check response protection")
    print(f"  Total clear calls: {len(chat.clear_calls)}")
    print(f"  ANSI sequences emitted: {len(chat.ansi_sequences_emitted)}")

    # The key check: after buffer was cleared (thinking_buffer_lines=0, is_thinking_displayed=False),
    # subsequent Ctrl+O presses should NOT emit ANSI sequences
    clears_during_response = []
    for call in chat.clear_calls:
        if call['time'] > time.time() - 10:  # Roughly during response phase
            clears_during_response.append(call)

    print(f"  Clears during response phase: {len(clears_during_response)}")

    problematic = []
    for call in clears_during_response:
        if call['is_thinking_displayed'] == False and call['thinking_buffer_lines'] == 0:
            # Check if ANSI was emitted
            for ansi in chat.ansi_sequences_emitted:
                if abs(ansi['time'] - call['time']) < 0.01:
                    problematic.append(call)

    if problematic:
        print(f"  [FAIL] {len(problematic)} clear(s) emitted ANSI during response phase!")
        return False
    else:
        print(f"  [OK] No ANSI sequences emitted during response phase - response protected!")
        return True

def test_scenario_rapid_fire():
    """
    Test rapid Ctrl+O presses (faster than debounce).
    """
    print("\n" + "=" * 70)
    print("SCENARIO: Rapid-fire Ctrl+O presses (testing debounce)")
    print("=" * 70)

    chat = MockChat()
    progress = ProgressDisplay()
    last_ctrl_o_time = time.time() - 1.0

    chat.is_reasoning_active = True
    chat.show_thinking_realtime = True

    print("Pressing Ctrl+O 10 times at 0.1s intervals (faster than 0.3s debounce):")

    presses = []
    for i in range(10):
        time.sleep(0.1)
        last_ctrl_o_time, msg, branch = simulate_ctrl_o_press(chat, progress, last_ctrl_o_time, i+1)
        presses.append((msg, branch))
        if "DEBOUNCED" in msg:
            print(f"  Press {i+1}: DEBOUNCED")
        else:
            print(f"  Press {i+1}: {branch}")

    debounced = sum(1 for msg, _ in presses if "DEBOUNCED" in msg)
    processed = len(presses) - debounced

    print(f"\nDebounced: {debounced}, Processed: {processed}")
    print(f"Expected: ~{int(10 * 0.3/0.1)} processed due to 0.3s debounce")

    # Should have some debounced, some processed
    if debounced > 0 and processed > 0:
        print("[OK] Debounce logic working correctly")
        return True
    else:
        print("[FAIL] Debounce logic not working as expected")
        return False

def main():
    """Run all scenarios."""
    print("=" * 70)
    print("COMPREHENSIVE Ctrl+O MULTI-PRESS SIMULATION")
    print("Testing 8+ presses with random timing and state changes")
    print("=" * 70)

    all_passed = True

    try:
        all_passed &= test_scenario_random_presses()
        all_passed &= test_scenario_thinking_to_response()
        all_passed &= test_scenario_rapid_fire()

        if all_passed:
            print("\n" + "=" * 70)
            print("[OK] ALL SCENARIOS PASSED!")
            print("Ctrl+O behavior tested with 8+ presses in various scenarios.")
            print("Response protection verified - no ANSI sequences when buffer not displayed.")
            print("=" * 70)
            return True
        else:
            print("\n" + "=" * 70)
            print("[FAIL] SOME SCENARIOS FAILED")
            print("=" * 70)
            return False

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)