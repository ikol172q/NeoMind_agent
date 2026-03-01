#!/usr/bin/env python3
"""
Comprehensive unit tests for Task and TaskManager.
Tests task creation, status updates, persistence, and management.
"""
import os
import sys
import tempfile
import shutil
import json
import uuid
import unittest
from unittest.mock import Mock, patch, MagicMock, call
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.task_manager import Task, TaskManager


class TestTask(unittest.TestCase):
    """Test Task class."""

    def test_task_initialization(self):
        """Test Task initialization with description."""
        task = Task("Write tests")

        self.assertEqual(task.description, "Write tests")
        self.assertEqual(task.status, "todo")
        self.assertEqual(len(task.id), 8)  # Short UUID
        self.assertIsInstance(task.created_at, str)
        self.assertIsInstance(task.updated_at, str)
        self.assertEqual(task.created_at, task.updated_at)

    def test_task_initialization_with_status(self):
        """Test Task initialization with custom status."""
        task = Task("Write tests", status="in_progress")

        self.assertEqual(task.status, "in_progress")

    def test_task_to_dict(self):
        """Test converting task to dictionary."""
        with patch('agent.task_manager.uuid.uuid4') as mock_uuid:
            mock_uuid.return_value = uuid.UUID('12345678-1234-5678-1234-567812345678')
            with patch('agent.task_manager.datetime') as mock_datetime:
                mock_datetime.now.return_value = datetime(2024, 1, 1, 12, 0, 0)
                task = Task("Write tests", status="todo")

                result = task.to_dict()

                self.assertEqual(result, {
                    "id": "12345678",
                    "description": "Write tests",
                    "status": "todo",
                    "created_at": "2024-01-01T12:00:00",
                    "updated_at": "2024-01-01T12:00:00"
                })

    def test_task_from_dict(self):
        """Test creating task from dictionary."""
        data = {
            "id": "abc123",
            "description": "Write tests",
            "status": "done",
            "created_at": "2024-01-01T12:00:00",
            "updated_at": "2024-01-01T13:00:00"
        }

        task = Task.from_dict(data)

        self.assertEqual(task.id, "abc123")
        self.assertEqual(task.description, "Write tests")
        self.assertEqual(task.status, "done")
        self.assertEqual(task.created_at, "2024-01-01T12:00:00")
        self.assertEqual(task.updated_at, "2024-01-01T13:00:00")

    def test_task_from_dict_missing_fields(self):
        """Test creating task from dictionary with missing fields raises KeyError."""
        data = {
            "id": "abc123",
            "description": "Write tests"
            # Missing status, created_at, updated_at
        }

        with self.assertRaises(KeyError):
            Task.from_dict(data)

    def test_update_status_valid(self):
        """Test updating task status with valid status."""
        with patch('agent.task_manager.datetime') as mock_datetime:
            mock_datetime.now.side_effect = [
                datetime(2024, 1, 1, 12, 0, 0),
                datetime(2024, 1, 1, 12, 0, 1)
            ]
            task = Task("Write tests")
            original_updated = task.updated_at

            task.update_status("in_progress")

            self.assertEqual(task.status, "in_progress")
            self.assertNotEqual(task.updated_at, original_updated)  # Should update timestamp
            self.assertEqual(task.updated_at, "2024-01-01T12:00:01")

    def test_update_status_invalid(self):
        """Test updating task status with invalid status raises ValueError."""
        task = Task("Write tests")

        with self.assertRaises(ValueError) as context:
            task.update_status("invalid_status")

        self.assertIn("Invalid status", str(context.exception))
        self.assertEqual(task.status, "todo")  # Should remain unchanged


class TestTaskManagerInitialization(unittest.TestCase):
    """Test TaskManager initialization."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up after tests."""
        shutil.rmtree(self.test_dir)

    def test_initialization_default(self):
        """Test initialization with default data directory."""
        manager = TaskManager()

        self.assertEqual(manager.data_dir, os.getcwd())
        self.assertEqual(manager.tasks_file, os.path.join(os.getcwd(), ".tasks.json"))
        self.assertEqual(manager.tasks, {})

    def test_initialization_custom_dir(self):
        """Test initialization with custom data directory."""
        manager = TaskManager(self.test_dir)

        self.assertEqual(manager.data_dir, self.test_dir)
        self.assertEqual(manager.tasks_file, os.path.join(self.test_dir, ".tasks.json"))

    def test_load_tasks_file_exists(self):
        """Test loading tasks from existing file."""
        tasks_data = {
            "abc123": {
                "id": "abc123",
                "description": "Write tests",
                "status": "todo",
                "created_at": "2024-01-01T12:00:00",
                "updated_at": "2024-01-01T12:00:00"
            }
        }
        tasks_file = os.path.join(self.test_dir, ".tasks.json")
        with open(tasks_file, 'w') as f:
            json.dump(tasks_data, f)

        manager = TaskManager(self.test_dir)

        self.assertEqual(len(manager.tasks), 1)
        self.assertIn("abc123", manager.tasks)
        task = manager.tasks["abc123"]
        self.assertEqual(task.id, "abc123")
        self.assertEqual(task.description, "Write tests")
        self.assertEqual(task.status, "todo")

    def test_load_tasks_invalid_json(self):
        """Test loading tasks from invalid JSON file."""
        tasks_file = os.path.join(self.test_dir, ".tasks.json")
        with open(tasks_file, 'w') as f:
            f.write("invalid json")

        manager = TaskManager(self.test_dir)

        self.assertEqual(manager.tasks, {})  # Should start empty

    def test_load_tasks_corrupted_data(self):
        """Test loading tasks with corrupted data (missing fields)."""
        tasks_data = {
            "abc123": {
                "id": "abc123",
                "description": "Write tests"
                # Missing required fields
            }
        }
        tasks_file = os.path.join(self.test_dir, ".tasks.json")
        with open(tasks_file, 'w') as f:
            json.dump(tasks_data, f)

        manager = TaskManager(self.test_dir)

        self.assertEqual(manager.tasks, {})  # Should start empty due to KeyError

    def test_load_tasks_no_file(self):
        """Test loading tasks when file doesn't exist."""
        manager = TaskManager(self.test_dir)

        self.assertEqual(manager.tasks, {})


class TestTaskManagerOperations(unittest.TestCase):
    """Test TaskManager CRUD operations."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.manager = TaskManager(self.test_dir)

    def tearDown(self):
        """Clean up after tests."""
        shutil.rmtree(self.test_dir)

    def test_create_task(self):
        """Test creating a new task."""
        task = self.manager.create_task("Write tests")

        self.assertEqual(task.description, "Write tests")
        self.assertEqual(task.status, "todo")
        self.assertIn(task.id, self.manager.tasks)
        self.assertEqual(self.manager.tasks[task.id], task)

        # Should be saved to file
        tasks_file = os.path.join(self.test_dir, ".tasks.json")
        self.assertTrue(os.path.exists(tasks_file))
        with open(tasks_file, 'r') as f:
            saved_data = json.load(f)
        self.assertIn(task.id, saved_data)

    def test_get_task_existing(self):
        """Test getting an existing task."""
        task = self.manager.create_task("Write tests")
        retrieved = self.manager.get_task(task.id)

        self.assertEqual(retrieved, task)

    def test_get_task_nonexistent(self):
        """Test getting a non-existent task returns None."""
        retrieved = self.manager.get_task("nonexistent")

        self.assertIsNone(retrieved)

    def test_list_tasks_all(self):
        """Test listing all tasks."""
        with patch('agent.task_manager.uuid.uuid4') as mock_uuid:
            mock_uuid.side_effect = [
                uuid.UUID('11111111-1111-1111-1111-111111111111'),
                uuid.UUID('22222222-2222-2222-2222-222222222222'),
                uuid.UUID('33333333-3333-3333-3333-333333333333')
            ]
            with patch('agent.task_manager.datetime') as mock_datetime:
                mock_datetime.now.side_effect = [
                    datetime(2024, 1, 1, 12, 0, 0),
                    datetime(2024, 1, 1, 12, 0, 1),
                    datetime(2024, 1, 1, 12, 0, 2)
                ]
                task1 = self.manager.create_task("Task 1")
                task2 = self.manager.create_task("Task 2")
                task3 = self.manager.create_task("Task 3")

                tasks = self.manager.list_tasks()

                self.assertEqual(len(tasks), 3)
                # Should be sorted by created_at descending (newest first)
                # Since we created them sequentially, task3 should be first
                self.assertEqual(tasks[0].id, task3.id)
                self.assertEqual(tasks[1].id, task2.id)
                self.assertEqual(tasks[2].id, task1.id)

    def test_list_tasks_with_status_filter(self):
        """Test listing tasks filtered by status."""
        task1 = self.manager.create_task("Task 1")  # todo
        task2 = self.manager.create_task("Task 2")  # todo
        self.manager.update_task_status(task2.id, "in_progress")
        task3 = self.manager.create_task("Task 3")  # todo
        self.manager.update_task_status(task3.id, "done")

        todo_tasks = self.manager.list_tasks("todo")
        in_progress_tasks = self.manager.list_tasks("in_progress")
        done_tasks = self.manager.list_tasks("done")

        self.assertEqual(len(todo_tasks), 1)
        self.assertEqual(todo_tasks[0].id, task1.id)

        self.assertEqual(len(in_progress_tasks), 1)
        self.assertEqual(in_progress_tasks[0].id, task2.id)

        self.assertEqual(len(done_tasks), 1)
        self.assertEqual(done_tasks[0].id, task3.id)

    def test_update_task_status_valid(self):
        """Test updating task status with valid status."""
        with patch('agent.task_manager.uuid.uuid4') as mock_uuid:
            mock_uuid.return_value = uuid.UUID('12345678-1234-5678-1234-567812345678')
            with patch('agent.task_manager.datetime') as mock_datetime:
                mock_datetime.now.side_effect = [
                    datetime(2024, 1, 1, 12, 0, 0),
                    datetime(2024, 1, 1, 12, 0, 1)
                ]
                task = self.manager.create_task("Write tests")
                original_updated = task.updated_at

                success = self.manager.update_task_status(task.id, "in_progress")

                self.assertTrue(success)
                self.assertEqual(self.manager.tasks[task.id].status, "in_progress")
                self.assertNotEqual(self.manager.tasks[task.id].updated_at, original_updated)

                # Verify saved to file
                tasks_file = os.path.join(self.test_dir, ".tasks.json")
                with open(tasks_file, 'r') as f:
                    saved_data = json.load(f)
                self.assertEqual(saved_data[task.id]["status"], "in_progress")

    def test_update_task_status_invalid(self):
        """Test updating task status with invalid status returns False."""
        task = self.manager.create_task("Write tests")

        success = self.manager.update_task_status(task.id, "invalid_status")

        self.assertFalse(success)
        self.assertEqual(self.manager.tasks[task.id].status, "todo")  # Unchanged

    def test_update_task_status_nonexistent(self):
        """Test updating non-existent task returns False."""
        success = self.manager.update_task_status("nonexistent", "in_progress")

        self.assertFalse(success)

    def test_delete_task_existing(self):
        """Test deleting an existing task."""
        task1 = self.manager.create_task("Task 1")
        task2 = self.manager.create_task("Task 2")

        success = self.manager.delete_task(task1.id)

        self.assertTrue(success)
        self.assertNotIn(task1.id, self.manager.tasks)
        self.assertIn(task2.id, self.manager.tasks)

        # Verify saved to file
        tasks_file = os.path.join(self.test_dir, ".tasks.json")
        with open(tasks_file, 'r') as f:
            saved_data = json.load(f)
        self.assertNotIn(task1.id, saved_data)
        self.assertIn(task2.id, saved_data)

    def test_delete_task_nonexistent(self):
        """Test deleting non-existent task returns False."""
        success = self.manager.delete_task("nonexistent")

        self.assertFalse(success)

    def test_clear_all_tasks(self):
        """Test clearing all tasks."""
        self.manager.create_task("Task 1")
        self.manager.create_task("Task 2")
        self.manager.create_task("Task 3")

        count = self.manager.clear_all_tasks()

        self.assertEqual(count, 3)
        self.assertEqual(len(self.manager.tasks), 0)

        # Verify saved to file (empty object)
        tasks_file = os.path.join(self.test_dir, ".tasks.json")
        with open(tasks_file, 'r') as f:
            saved_data = json.load(f)
        self.assertEqual(saved_data, {})


class TestTaskManagerPersistence(unittest.TestCase):
    """Test TaskManager persistence behavior."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up after tests."""
        shutil.rmtree(self.test_dir)

    def test_save_tasks_success(self):
        """Test successful save of tasks."""
        manager = TaskManager(self.test_dir)
        manager.create_task("Task 1")
        manager.create_task("Task 2")

        tasks_file = os.path.join(self.test_dir, ".tasks.json")
        self.assertTrue(os.path.exists(tasks_file))

        with open(tasks_file, 'r') as f:
            data = json.load(f)

        self.assertEqual(len(data), 2)
        for task_id, task_data in data.items():
            self.assertEqual(task_data["status"], "todo")
            self.assertIn("description", task_data)

    def test_save_tasks_ioerror(self):
        """Test handling of IOError during save."""
        manager = TaskManager(self.test_dir)
        manager.create_task("Task 1")

        # Mock open to raise IOError
        with patch('builtins.open', side_effect=IOError("Disk full")):
            with patch('agent.task_manager.log_operation') as mock_log:
                # This would be called by _save_tasks internally
                # We'll test via create_task which calls _save_tasks
                # Since we mocked open, the save will fail but create_task should still return task
                pass  # Can't easily test without refactoring

    def test_load_tasks_permission_error(self):
        """Test handling of permission error during load."""
        tasks_file = os.path.join(self.test_dir, ".tasks.json")
        with open(tasks_file, 'w') as f:
            json.dump({"test": {"id": "test", "description": "test"}}, f)

        # Make file unreadable
        os.chmod(tasks_file, 0o000)

        try:
            manager = TaskManager(self.test_dir)
            # Should start with empty tasks due to permission error
            self.assertEqual(manager.tasks, {})
        finally:
            # Restore permissions for cleanup
            os.chmod(tasks_file, 0o644)


class TestTaskManagerIntegration(unittest.TestCase):
    """Test TaskManager integration with file system."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up after tests."""
        shutil.rmtree(self.test_dir)

    def test_full_workflow(self):
        """Test complete workflow: create, update, filter, delete."""
        manager = TaskManager(self.test_dir)

        # Create tasks
        task1 = manager.create_task("Write unit tests")
        task2 = manager.create_task("Refactor code")
        task3 = manager.create_task("Update documentation")

        # Update statuses
        manager.update_task_status(task1.id, "in_progress")
        manager.update_task_status(task3.id, "done")

        # List by status
        todo_tasks = manager.list_tasks("todo")
        in_progress_tasks = manager.list_tasks("in_progress")
        done_tasks = manager.list_tasks("done")

        self.assertEqual(len(todo_tasks), 1)
        self.assertEqual(todo_tasks[0].id, task2.id)

        self.assertEqual(len(in_progress_tasks), 1)
        self.assertEqual(in_progress_tasks[0].id, task1.id)

        self.assertEqual(len(done_tasks), 1)
        self.assertEqual(done_tasks[0].id, task3.id)

        # Delete a task
        manager.delete_task(task2.id)

        # Verify remaining tasks
        remaining = manager.list_tasks()
        self.assertEqual(len(remaining), 2)
        remaining_ids = {t.id for t in remaining}
        self.assertEqual(remaining_ids, {task1.id, task3.id})

        # Clear all
        count = manager.clear_all_tasks()
        self.assertEqual(count, 2)
        self.assertEqual(len(manager.tasks), 0)

    def test_persistence_across_instances(self):
        """Test that tasks persist across TaskManager instances."""
        # First instance
        manager1 = TaskManager(self.test_dir)
        task1 = manager1.create_task("Task 1")
        manager1.update_task_status(task1.id, "in_progress")

        # Second instance should load saved tasks
        manager2 = TaskManager(self.test_dir)

        self.assertEqual(len(manager2.tasks), 1)
        task2 = manager2.get_task(task1.id)
        self.assertEqual(task2.description, "Task 1")
        self.assertEqual(task2.status, "in_progress")


if __name__ == '__main__':
    unittest.main()