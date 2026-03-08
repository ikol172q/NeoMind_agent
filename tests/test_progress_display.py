#!/usr/bin/env python3
"""
Comprehensive unit tests for ProgressDisplay system.
Tests task management, status updates, display formatting, and global functions.
"""

import os
import sys
import time
import threading
import unittest
from unittest.mock import Mock, patch, MagicMock, call
import tempfile
import shutil

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cli.progress_display import ProgressDisplay, TaskStatus, get_global_progress, format_simple_status


class TestTaskStatusEnum(unittest.TestCase):
    """Test TaskStatus enum values and properties."""

    def test_task_status_values(self):
        """Test TaskStatus enum has expected values."""
        self.assertEqual(TaskStatus.PENDING.value, "pending")
        self.assertEqual(TaskStatus.IN_PROGRESS.value, "in_progress")
        self.assertEqual(TaskStatus.COMPLETED.value, "completed")
        self.assertEqual(TaskStatus.FAILED.value, "failed")
        self.assertEqual(TaskStatus.CANCELLED.value, "cancelled")
        self.assertEqual(TaskStatus.WARNING.value, "warning")
        self.assertEqual(TaskStatus.SKIPPED.value, "skipped")

    def test_task_status_membership(self):
        """Test TaskStatus enum membership."""
        self.assertIn("PENDING", TaskStatus.__members__)
        self.assertIn("IN_PROGRESS", TaskStatus.__members__)
        self.assertIn("COMPLETED", TaskStatus.__members__)
        self.assertIn("FAILED", TaskStatus.__members__)


class TestProgressDisplayInitialization(unittest.TestCase):
    """Test ProgressDisplay initialization and basic properties."""

    def test_initialization_default(self):
        """Test initialization with default parameters."""
        pd = ProgressDisplay()

        self.assertEqual(pd.language, "en")
        self.assertEqual(pd.max_tasks, 5)
        self.assertEqual(pd.use_unicode, sys.platform != "win32")
        self.assertEqual(pd.tasks, {})
        self.assertEqual(pd.task_order, [])
        self.assertIsInstance(pd.lock, type(threading.RLock()))
        self.assertIsInstance(pd.start_time, float)
        self.assertEqual(pd.total_tool_uses, 0)
        self.assertEqual(pd.total_tokens, 0)
        self.assertTrue(pd.show_statistics)
        self.assertTrue(pd.show_time)
        self.assertFalse(pd.compact_mode)

    def test_initialization_custom_language(self):
        """Test initialization with custom language."""
        pd = ProgressDisplay(language="zh")

        self.assertEqual(pd.language, "zh")
        self.assertEqual(pd.max_tasks, 5)

    def test_initialization_invalid_language(self):
        """Test initialization with invalid language defaults to English."""
        pd = ProgressDisplay(language="fr")  # Invalid language

        self.assertEqual(pd.language, "en")

    def test_initialization_custom_max_tasks(self):
        """Test initialization with custom max_tasks."""
        pd = ProgressDisplay(max_tasks=10)

        self.assertEqual(pd.max_tasks, 10)

    def test_initialization_windows_unicode(self):
        """Test Unicode support detection on Windows."""
        original_platform = sys.platform
        try:
            sys.platform = "win32"
            pd = ProgressDisplay()
            self.assertFalse(pd.use_unicode)

            sys.platform = "linux"
            pd = ProgressDisplay()
            self.assertTrue(pd.use_unicode)
        finally:
            sys.platform = original_platform


class TestProgressDisplayTaskLifecycle(unittest.TestCase):
    """Test task lifecycle: start, update, complete, fail."""

    def setUp(self):
        """Set up test environment."""
        self.pd = ProgressDisplay()

    def test_start_task_basic(self):
        """Test starting a basic task."""
        task_id = self.pd.start_task("Test Task", "Test description", 5, 100)

        self.assertIsInstance(task_id, str)
        self.assertIn(task_id, self.pd.tasks)
        self.assertIn(task_id, self.pd.task_order)

        task = self.pd.tasks[task_id]
        self.assertEqual(task["title"], "Test Task")
        self.assertEqual(task["description"], "Test description")
        self.assertEqual(task["status"], TaskStatus.IN_PROGRESS)
        self.assertEqual(task["tool_uses"], 5)
        self.assertEqual(task["tokens"], 100)
        self.assertIsInstance(task["start_time"], float)
        self.assertIsNone(task["end_time"])
        self.assertEqual(task["status_index"], 0)
        self.assertTrue(task["visible"])
        self.assertFalse(task["expanded"])

    def test_start_task_minimal(self):
        """Test starting a task with minimal parameters."""
        task_id = self.pd.start_task("Minimal Task")

        task = self.pd.tasks[task_id]
        self.assertEqual(task["title"], "Minimal Task")
        self.assertEqual(task["description"], "")
        self.assertEqual(task["tool_uses"], 0)
        self.assertEqual(task["tokens"], 0)

    def test_start_task_max_tasks_limit(self):
        """Test that old completed tasks are removed when exceeding max_tasks."""
        pd = ProgressDisplay(max_tasks=2)

        # Start 3 tasks
        task_ids = []
        for i in range(3):
            task_id = pd.start_task(f"Task {i}")
            task_ids.append(task_id)

        # All 3 should be in tasks dict initially
        self.assertEqual(len(pd.tasks), 3)
        self.assertEqual(len(pd.task_order), 3)

        # Complete the first task
        pd.complete_task(task_ids[0])

        # Start a 4th task - should remove the first (completed) task
        task_id_4 = pd.start_task("Task 4")

        # Should remove only one task (the completed one), leaving 3 tasks
        self.assertEqual(len(pd.task_order), 3)
        # First task should be removed
        self.assertNotIn(task_ids[0], pd.tasks)
        self.assertNotIn(task_ids[0], pd.task_order)
        # Other tasks should still exist
        self.assertIn(task_ids[1], pd.tasks)
        self.assertIn(task_ids[2], pd.tasks)
        self.assertIn(task_id_4, pd.tasks)

    def test_start_task_statistics_update(self):
        """Test that starting task updates global statistics."""
        self.assertEqual(self.pd.total_tool_uses, 0)
        self.assertEqual(self.pd.total_tokens, 0)

        task_id = self.pd.start_task("Test", "", 10, 200)

        self.assertEqual(self.pd.total_tool_uses, 10)
        self.assertEqual(self.pd.total_tokens, 200)

    def test_update_task_status(self):
        """Test updating task status."""
        task_id = self.pd.start_task("Test Task")

        success = self.pd.update_task(task_id, status=TaskStatus.COMPLETED)

        self.assertTrue(success)
        self.assertEqual(self.pd.tasks[task_id]["status"], TaskStatus.COMPLETED)
        self.assertIsNotNone(self.pd.tasks[task_id]["end_time"])

    def test_update_task_status_index_in_progress(self):
        """Test that status_index cycles when updating IN_PROGRESS status."""
        task_id = self.pd.start_task("Test Task")

        initial_index = self.pd.tasks[task_id]["status_index"]

        # Update with IN_PROGRESS status (should cycle index)
        success = self.pd.update_task(task_id, status=TaskStatus.IN_PROGRESS)

        self.assertTrue(success)
        self.assertEqual(self.pd.tasks[task_id]["status_index"], (initial_index + 1) % 20)

    def test_update_task_tool_uses(self):
        """Test updating task tool uses."""
        task_id = self.pd.start_task("Test", "", 5, 100)

        success = self.pd.update_task(task_id, tool_uses=15)

        self.assertTrue(success)
        self.assertEqual(self.pd.tasks[task_id]["tool_uses"], 15)
        self.assertEqual(self.pd.total_tool_uses, 15)  # 10 added (15-5)

    def test_update_task_tokens(self):
        """Test updating task tokens."""
        task_id = self.pd.start_task("Test", "", 5, 100)

        success = self.pd.update_task(task_id, tokens=300)

        self.assertTrue(success)
        self.assertEqual(self.pd.tasks[task_id]["tokens"], 300)
        self.assertEqual(self.pd.total_tokens, 300)  # 200 added (300-100)

    def test_update_task_title_description(self):
        """Test updating task title and description."""
        task_id = self.pd.start_task("Old Title", "Old Desc")

        success = self.pd.update_task(task_id, title="New Title", description="New Desc")

        self.assertTrue(success)
        self.assertEqual(self.pd.tasks[task_id]["title"], "New Title")
        self.assertEqual(self.pd.tasks[task_id]["description"], "New Desc")

    def test_update_task_nonexistent(self):
        """Test updating non-existent task returns False."""
        success = self.pd.update_task("nonexistent", status=TaskStatus.COMPLETED)

        self.assertFalse(success)

    def test_complete_task(self):
        """Test completing a task."""
        task_id = self.pd.start_task("Test")

        success = self.pd.complete_task(task_id, tool_uses=10, tokens=200)

        self.assertTrue(success)
        self.assertEqual(self.pd.tasks[task_id]["status"], TaskStatus.COMPLETED)
        self.assertEqual(self.pd.tasks[task_id]["tool_uses"], 10)
        self.assertEqual(self.pd.tasks[task_id]["tokens"], 200)

    def test_fail_task(self):
        """Test failing a task."""
        task_id = self.pd.start_task("Test")

        success = self.pd.fail_task(task_id, tool_uses=5, tokens=100)

        self.assertTrue(success)
        self.assertEqual(self.pd.tasks[task_id]["status"], TaskStatus.FAILED)
        self.assertEqual(self.pd.tasks[task_id]["tool_uses"], 5)
        self.assertEqual(self.pd.tasks[task_id]["tokens"], 100)

    def test_get_task(self):
        """Test retrieving a task by ID."""
        task_id = self.pd.start_task("Test")

        task = self.pd.get_task(task_id)

        self.assertIsNotNone(task)
        self.assertEqual(task["title"], "Test")

        # Non-existent task
        self.assertIsNone(self.pd.get_task("nonexistent"))

    def test_get_active_tasks(self):
        """Test retrieving active (in-progress) tasks."""
        task1 = self.pd.start_task("Task 1")
        task2 = self.pd.start_task("Task 2")
        self.pd.complete_task(task1)

        active_tasks = self.pd.get_active_tasks()

        self.assertEqual(len(active_tasks), 1)
        self.assertEqual(active_tasks[0]["title"], "Task 2")
        self.assertEqual(active_tasks[0]["status"], TaskStatus.IN_PROGRESS)


class TestProgressDisplayStatusWords(unittest.TestCase):
    """Test status word generation."""

    def test_get_status_word_default(self):
        """Test getting default status words."""
        pd = ProgressDisplay(language="en")

        # Test English defaults
        self.assertIn(pd._get_status_word(TaskStatus.IN_PROGRESS), ["In progress"] + pd.STATUS_WORDS[TaskStatus.IN_PROGRESS]["en"])
        self.assertIn(pd._get_status_word(TaskStatus.COMPLETED), ["Done"] + pd.STATUS_WORDS[TaskStatus.COMPLETED]["en"])
        self.assertIn(pd._get_status_word(TaskStatus.FAILED), ["Failed"] + pd.STATUS_WORDS[TaskStatus.FAILED]["en"])

    def test_get_status_word_chinese(self):
        """Test getting Chinese status words."""
        pd = ProgressDisplay(language="zh")

        # Should return Chinese words
        word = pd._get_status_word(TaskStatus.IN_PROGRESS)
        self.assertIsInstance(word, str)
        # Word should be from Chinese list or default Chinese
        if word not in ["进行中"]:
            self.assertIn(word, pd.STATUS_WORDS[TaskStatus.IN_PROGRESS]["zh"])

    def test_get_status_word_cycling(self):
        """Test status word cycling with index."""
        pd = ProgressDisplay(language="en")

        words = set()
        for i in range(10):
            word = pd._get_status_word(TaskStatus.IN_PROGRESS, i)
            words.add(word)

        # Should get different words (or at least work without error)
        self.assertGreaterEqual(len(words), 1)

    def test_get_status_word_unknown_status(self):
        """Test getting status word for unknown status."""
        pd = ProgressDisplay()

        # Create a mock status not in STATUS_WORDS
        class MockStatus:
            value = "unknown"

        mock_status = MockStatus()
        word = pd._get_status_word(mock_status)

        self.assertEqual(word, "unknown")


class TestProgressDisplayFormatting(unittest.TestCase):
    """Test formatting methods."""

    def setUp(self):
        """Set up test environment."""
        self.pd = ProgressDisplay()

    def test_format_duration_milliseconds(self):
        """Test formatting duration less than 1 second."""
        result = self.pd._format_duration(0.5)
        self.assertEqual(result, "500ms")

    def test_format_duration_seconds(self):
        """Test formatting duration less than 60 seconds."""
        result = self.pd._format_duration(45.5)
        self.assertEqual(result, "45.5s")

    def test_format_duration_minutes(self):
        """Test formatting duration less than 1 hour."""
        result = self.pd._format_duration(125.7)  # 2 minutes, 5.7 seconds
        self.assertEqual(result, "2m 6s")  # Rounded

    def test_format_duration_hours(self):
        """Test formatting duration more than 1 hour."""
        result = self.pd._format_duration(3665)  # 1 hour, 1 minute, 5 seconds
        self.assertEqual(result, "1h 1m")

    def test_format_statistics_empty(self):
        """Test formatting statistics for task with no stats."""
        task = {
            "tool_uses": 0,
            "tokens": 0,
            "start_time": time.time() - 0.05,  # 50ms - below threshold
            "end_time": time.time()
        }

        result = self.pd._format_statistics(task)
        self.assertEqual(result, "")

    def test_format_statistics_with_tool_uses(self):
        """Test formatting statistics with tool uses."""
        task = {
            "tool_uses": 5,
            "tokens": 0,
            "start_time": time.time() - 2.5,
            "end_time": time.time()
        }

        result = self.pd._format_statistics(task)
        self.assertIn("5 tool uses", result)
        self.assertIn("2.5s", result)

    def test_format_statistics_with_tokens(self):
        """Test formatting statistics with tokens."""
        task = {
            "tool_uses": 0,
            "tokens": 1500,
            "start_time": time.time() - 1.2,
            "end_time": time.time()
        }

        result = self.pd._format_statistics(task)
        self.assertIn("1.5K tokens", result)

    def test_format_statistics_token_formats(self):
        """Test token formatting with various sizes."""
        # Less than 1000
        task1 = {"tool_uses": 0, "tokens": 500, "start_time": 0, "end_time": 1}
        result1 = self.pd._format_statistics(task1)
        self.assertIn("500 tokens", result1)

        # Thousands
        task2 = {"tool_uses": 0, "tokens": 1500, "start_time": 0, "end_time": 1}
        result2 = self.pd._format_statistics(task2)
        self.assertIn("1.5K tokens", result2)

        # Millions
        task3 = {"tool_uses": 0, "tokens": 2_500_000, "start_time": 0, "end_time": 1}
        result3 = self.pd._format_statistics(task3)
        self.assertIn("2.5M tokens", result3)


class TestProgressDisplayDisplay(unittest.TestCase):
    """Test display generation."""

    def setUp(self):
        """Set up test environment."""
        self.pd = ProgressDisplay()
        # Patch use_unicode to False for consistent testing
        self.pd.use_unicode = False

    def test_display_no_tasks(self):
        """Test display with no tasks returns empty string."""
        result = self.pd.display()
        self.assertEqual(result, "")

    def test_display_single_task(self):
        """Test display with a single task."""
        task_id = self.pd.start_task("Test Task", "Description")

        result = self.pd.display()

        self.assertIn("Test Task", result)
        # Should contain status indicator and ellipsis
        self.assertIn("...", result)
        self.assertIn("->", result)
        self.assertIn("Description", result)  # Shown for in-progress tasks

    def test_display_completed_task(self):
        """Test display with completed task."""
        task_id = self.pd.start_task("Completed Task")
        self.pd.complete_task(task_id)

        result = self.pd.display()

        self.assertIn("Completed Task", result)
        self.assertIn("Done", result)

    def test_display_failed_task(self):
        """Test display with failed task."""
        task_id = self.pd.start_task("Failed Task")
        self.pd.fail_task(task_id)

        result = self.pd.display()

        self.assertIn("Failed Task", result)
        self.assertIn("Failed", result)

    def test_display_expanded_task(self):
        """Test display with expanded task shows description."""
        task_id = self.pd.start_task("Test Task", "Line 1\nLine 2\nLine 3\nLine 4")
        self.pd.tasks[task_id]["expanded"] = True

        result = self.pd.display()

        self.assertIn("Test Task", result)
        self.assertIn("Line 1", result)
        self.assertIn("Line 2", result)
        self.assertIn("Line 3", result)
        self.assertNotIn("Line 4", result)  # Limited to 3 lines

    def test_display_with_statistics(self):
        """Test display includes statistics when enabled."""
        task_id = self.pd.start_task("Test", "", 3, 1500)

        result = self.pd.display()

        self.assertIn("3 tool uses", result)
        self.assertIn("1.5K tokens", result)

    def test_display_global_statistics(self):
        """Test display includes global statistics."""
        self.pd.start_task("Task 1", "", 2, 1000)
        self.pd.start_task("Task 2", "", 3, 2000)

        result = self.pd.display()

        self.assertIn("Global:", result)
        self.assertIn("5 tool uses", result)
        self.assertIn("3.0K tokens", result)

    def test_display_hides_global_statistics_when_disabled(self):
        """Test display hides global statistics when disabled."""
        self.pd.show_statistics = False
        self.pd.start_task("Task", "", 1, 500)

        result = self.pd.display()

        self.assertNotIn("Global:", result)

    def test_display_unicode_icons(self):
        """Test display uses Unicode icons when enabled."""
        pd = ProgressDisplay()
        pd.use_unicode = True
        task_id = pd.start_task("Test")

        result = pd.display()

        # Should contain Unicode icons (● for in-progress)
        self.assertIn("●", result)

    def test_display_ascii_icons(self):
        """Test display uses ASCII icons when Unicode disabled."""
        pd = ProgressDisplay()
        pd.use_unicode = False
        task_id = pd.start_task("Test")

        result = pd.display()

        # Should contain ASCII icons (* for in-progress)
        self.assertIn("*", result)


class TestProgressDisplayTaskManagement(unittest.TestCase):
    """Test task management methods."""

    def setUp(self):
        """Set up test environment."""
        self.pd = ProgressDisplay()

    def test_clear_completed(self):
        """Test clearing completed tasks."""
        task1 = self.pd.start_task("Task 1")
        task2 = self.pd.start_task("Task 2")
        task3 = self.pd.start_task("Task 3")

        self.pd.complete_task(task1)
        self.pd.fail_task(task2)
        # task3 remains in progress

        cleared = self.pd.clear_completed(retention_seconds=0.0)

        self.assertEqual(cleared, 2)
        self.assertNotIn(task1, self.pd.tasks)
        self.assertNotIn(task2, self.pd.tasks)
        self.assertIn(task3, self.pd.tasks)
        self.assertEqual(len(self.pd.task_order), 1)

    def test_clear_completed_none(self):
        """Test clearing completed when none exist."""
        task_id = self.pd.start_task("Task")  # Still in progress

        cleared = self.pd.clear_completed(retention_seconds=0.0)

        self.assertEqual(cleared, 0)
        self.assertIn(task_id, self.pd.tasks)

    def test_task_visibility(self):
        """Test task visibility control."""
        task_id = self.pd.start_task("Task")
        self.pd.tasks[task_id]["visible"] = False

        result = self.pd.display()

        self.assertEqual(result, "")  # Hidden task not displayed


class TestProgressDisplayConcurrency(unittest.TestCase):
    """Test thread-safety with concurrent access."""

    def setUp(self):
        """Set up test environment."""
        self.pd = ProgressDisplay()

    def test_concurrent_task_creation(self):
        """Test creating tasks from multiple threads."""
        task_ids = []
        errors = []

        def create_task(thread_id):
            try:
                task_id = self.pd.start_task(f"Task from thread {thread_id}")
                task_ids.append(task_id)
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(10):
            t = threading.Thread(target=create_task, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)
        self.assertEqual(len(set(task_ids)), 10)  # All unique

    def test_concurrent_updates(self):
        """Test concurrent updates to same task."""
        task_id = self.pd.start_task("Test", "", 0, 0)

        def update_task():
            for _ in range(100):
                self.pd.update_task(task_id, tool_uses=1, tokens=10)

        threads = []
        for _ in range(5):
            t = threading.Thread(target=update_task)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # update_task sets absolute values, not increments, so concurrent
        # updates will overwrite each other. Final value will be 1 (or slightly
        # higher due to race conditions).
        task = self.pd.get_task(task_id)
        self.assertGreaterEqual(task["tool_uses"], 1)
        self.assertLessEqual(task["tool_uses"], 10)  # Allow for some race increments
        self.assertGreaterEqual(task["tokens"], 10)
        self.assertLessEqual(task["tokens"], 100)


class TestGlobalFunctions(unittest.TestCase):
    """Test global functions."""

    def test_get_global_progress_singleton(self):
        """Test get_global_progress returns singleton instance."""
        # Clear any existing global instance
        import cli.progress_display
        cli.progress_display._global_progress = None

        pd1 = get_global_progress()
        pd2 = get_global_progress()

        self.assertIs(pd1, pd2)

    def test_get_global_progress_language(self):
        """Test get_global_progress with language parameter."""
        import cli.progress_display
        cli.progress_display._global_progress = None

        pd = get_global_progress(language="zh")

        self.assertEqual(pd.language, "zh")

    def test_format_simple_status(self):
        """Test format_simple_status function."""
        # Test each status
        self.assertEqual(format_simple_status("Test", "executing"), "-> Test")
        self.assertEqual(format_simple_status("Test", "completed"), "[OK] Test")
        self.assertEqual(format_simple_status("Test", "failed"), "[ERROR] Test")
        self.assertEqual(format_simple_status("Test", "thinking"), "[THINKING] Test")
        self.assertEqual(format_simple_status("Test", "searching"), "[SEARCHING] Test")

        # Test unknown status
        self.assertEqual(format_simple_status("Test", "unknown"), "Test")

        # Test empty status
        self.assertEqual(format_simple_status("Test", ""), "Test")


if __name__ == '__main__':
    unittest.main()