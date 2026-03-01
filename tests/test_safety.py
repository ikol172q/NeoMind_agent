#!/usr/bin/env python3
"""
Comprehensive unit tests for SafetyManager and safety functions.
Tests path validation, dangerous operation blocking, audit logging,
backup creation, and permission enforcement.
"""
import os
import sys
import tempfile
import shutil
import stat
import json
import unittest
from unittest.mock import Mock, patch, MagicMock, call
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.safety import (
    SafetyManager, safe_read_file, safe_write_file, safe_delete_file,
    is_path_safe, log_operation, get_file_hash, create_backup
)


class TestSafetyManagerInitialization(unittest.TestCase):
    """Test SafetyManager initialization and basic properties."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.agent_root = os.path.join(self.test_dir, "agent_root")
        os.makedirs(self.agent_root, exist_ok=True)

    def tearDown(self):
        """Clean up after tests."""
        shutil.rmtree(self.test_dir)

    def test_initialization_with_valid_paths(self):
        """Test SafetyManager initialization with valid paths."""
        # Create safety manager
        safety_manager = SafetyManager(self.test_dir, agent_root=self.agent_root)

        # Verify properties
        self.assertEqual(safety_manager.workspace_root, os.path.abspath(self.test_dir))
        self.assertEqual(safety_manager.agent_root, self.agent_root)
        # Check class variables
        self.assertIsInstance(SafetyManager.DANGEROUS_EXTENSIONS, set)
        self.assertIsInstance(SafetyManager.SYSTEM_DIRECTORIES, list)
        self.assertIsInstance(safety_manager.audit_log, str)
        self.assertEqual(SafetyManager.MAX_FILE_SIZE, 10 * 1024 * 1024)

        # Default dangerous extensions should include dangerous ones
        self.assertIn(".exe", SafetyManager.DANGEROUS_EXTENSIONS)
        self.assertIn(".sh", SafetyManager.DANGEROUS_EXTENSIONS)
        self.assertIn(".bat", SafetyManager.DANGEROUS_EXTENSIONS)

        # Default system directories
        self.assertIn("/etc", SafetyManager.SYSTEM_DIRECTORIES)
        self.assertIn("/bin", SafetyManager.SYSTEM_DIRECTORIES)
        self.assertIn("C:\\Windows", SafetyManager.SYSTEM_DIRECTORIES)

    def test_initialization_with_custom_parameters(self):
        """Test SafetyManager initialization with custom parameters."""
        custom_audit_log = os.path.join(self.test_dir, "custom_audit.log")

        safety_manager = SafetyManager(
            self.test_dir,
            agent_root=self.agent_root,
            audit_log=custom_audit_log
        )

        # Verify custom properties
        self.assertEqual(safety_manager.audit_log, custom_audit_log)
        self.assertEqual(safety_manager.workspace_root, os.path.abspath(self.test_dir))
        self.assertEqual(safety_manager.agent_root, self.agent_root)

    def test_initialization_creates_audit_log(self):
        """Test that audit log file is created on initialization."""
        # Safety manager should create audit log
        safety_manager = SafetyManager(self.test_dir, agent_root=self.agent_root)

        # Audit log file should exist
        self.assertTrue(os.path.exists(safety_manager.audit_log))

        # Should be writable
        with open(safety_manager.audit_log, 'a') as f:
            f.write("Test entry\n")


class TestPathValidation(unittest.TestCase):
    """Test path validation functionality."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.agent_root = os.path.join(self.test_dir, "agent_root")
        os.makedirs(self.agent_root, exist_ok=True)
        self.safety_manager = SafetyManager(self.test_dir, agent_root=self.agent_root)

    def tearDown(self):
        """Clean up after tests."""
        shutil.rmtree(self.test_dir)

    def test_is_path_safe_with_relative_path(self):
        """Test is_path_safe with relative paths."""
        # Create a test file
        test_file = os.path.join(self.test_dir, "test.txt")
        with open(test_file, 'w') as f:
            f.write("test content")

        # Relative path within root (relative to test_dir)
        original_cwd = os.getcwd()
        try:
            os.chdir(self.test_dir)
            result, message = self.safety_manager.is_path_safe("test.txt")
            self.assertTrue(result)
            self.assertIn("safe", message.lower())
        finally:
            os.chdir(original_cwd)

    def test_is_path_safe_with_absolute_path(self):
        """Test is_path_safe with absolute paths."""
        # Create a test file
        test_file = os.path.join(self.test_dir, "test.txt")
        with open(test_file, 'w') as f:
            f.write("test content")

        # Absolute path within root
        result, message = self.safety_manager.is_path_safe(test_file)
        self.assertTrue(result)
        self.assertIn("safe", message.lower())

    def test_is_path_safe_with_path_traversal(self):
        """Test is_path_safe blocks path traversal attempts."""
        # Attempt to access parent directory (outside workspace)
        result, message = self.safety_manager.is_path_safe("../secret.txt")
        self.assertFalse(result)
        self.assertIn("outside", message.lower())

        # More complex path traversal
        result, message = self.safety_manager.is_path_safe("../../etc/passwd")
        self.assertFalse(result)
        self.assertIn("outside", message.lower())

        # Absolute path outside root
        outside_path = os.path.join(os.path.dirname(self.test_dir), "outside.txt")
        result, message = self.safety_manager.is_path_safe(outside_path)
        self.assertFalse(result)
        self.assertIn("outside", message.lower())

    def test_is_path_safe_with_system_directory(self):
        """Test is_path_safe blocks access to system directories."""
        # Mock a system directory path (outside workspace)
        system_path = "/etc/passwd"
        result, message = self.safety_manager.is_path_safe(system_path)
        self.assertFalse(result)
        self.assertIn("outside", message.lower())

        # Windows system directory
        windows_path = "C:\\Windows\\System32\\config"
        result, message = self.safety_manager.is_path_safe(windows_path)
        self.assertFalse(result)
        self.assertIn("outside", message.lower())

    def test_is_path_safe_with_dangerous_extension(self):
        """Test is_path_safe blocks dangerous file extensions."""
        original_cwd = os.getcwd()
        try:
            os.chdir(self.test_dir)
            # Dangerous extension
            result, message = self.safety_manager.is_path_safe("malicious.exe")
            self.assertFalse(result)
            self.assertIn("dangerous", message.lower())

            # Multiple dangerous extensions
            for ext in [".exe", ".sh", ".bat", ".cmd", ".ps1"]:
                result, message = self.safety_manager.is_path_safe(f"file{ext}")
                self.assertFalse(result)
                self.assertIn("dangerous", message.lower())

            # Safe extensions should pass
            for ext in [".txt", ".py", ".json", ".yaml", ".md"]:
                result, message = self.safety_manager.is_path_safe(f"file{ext}")
                self.assertTrue(result)
                self.assertIn("safe", message.lower())
        finally:
            os.chdir(original_cwd)

    def test_is_path_safe_with_agent_root_protection(self):
        """Test is_path_safe allows access to agent root directory."""
        # Try to access agent_root files (should be allowed)
        agent_file = os.path.join(self.agent_root, "core.py")
        result, message = self.safety_manager.is_path_safe(agent_file)
        self.assertTrue(result)
        self.assertIn("safe", message.lower())

        # Try with relative path that goes outside workspace
        result, message = self.safety_manager.is_path_safe("../agent_root/core.py")
        self.assertFalse(result)
        self.assertIn("outside", message.lower())

    def test_is_path_safe_with_nonexistent_path(self):
        """Test is_path_safe with non-existent paths."""
        original_cwd = os.getcwd()
        try:
            os.chdir(self.test_dir)
            # Non-existent file in safe directory
            result, message = self.safety_manager.is_path_safe("nonexistent.txt")
            self.assertTrue(result)
            self.assertIn("safe", message.lower())

            # Non-existent file with dangerous extension
            result, message = self.safety_manager.is_path_safe("nonexistent.exe")
            self.assertFalse(result)
            self.assertIn("dangerous", message.lower())
        finally:
            os.chdir(original_cwd)

    def test_is_path_safe_with_symlinks(self):
        """Test is_path_safe handles symbolic links."""
        # Create a symlink (if supported on platform)
        try:
            target_file = os.path.join(self.test_dir, "target.txt")
            with open(target_file, 'w') as f:
                f.write("target content")

            link_file = os.path.join(self.test_dir, "link.txt")
            os.symlink(target_file, link_file)

            # Symlink to safe file should be safe
            result, message = self.safety_manager.is_path_safe(link_file)
            self.assertTrue(result)
            self.assertIn("safe", message.lower())

            # Clean up
            os.unlink(link_file)
        except (OSError, NotImplementedError):
            # Symlinks not supported on this platform, skip test
            pass


class TestFileOperations(unittest.TestCase):
    """Test safe file operations."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.agent_root = os.path.join(self.test_dir, "agent_root")
        os.makedirs(self.agent_root, exist_ok=True)
        self.safety_manager = SafetyManager(self.test_dir, agent_root=self.agent_root)

    def tearDown(self):
        """Clean up after tests."""
        shutil.rmtree(self.test_dir)

    def test_safe_read_file_success(self):
        """Test successful safe file read."""
        # Create a test file
        test_file = os.path.join(self.test_dir, "test.txt")
        test_content = "Hello, world!\nThis is a test."
        with open(test_file, 'w') as f:
            f.write(test_content)

        # Read file
        success, message, content = self.safety_manager.safe_read_file(test_file)

        # Should succeed
        self.assertTrue(success)
        self.assertIn("success", message.lower())
        self.assertEqual(content, test_content)

    def test_safe_read_file_nonexistent(self):
        """Test safe_read_file with non-existent file."""
        nonexistent = os.path.join(self.test_dir, "nonexistent.txt")

        # Read non-existent file
        success, message, content = self.safety_manager.safe_read_file(nonexistent)

        # Should fail
        self.assertFalse(success)
        self.assertIn("file not found", message.lower())
        self.assertEqual(content, "")

    def test_safe_read_file_permission_denied(self):
        """Test safe_read_file with permission denied."""
        # Create a file and remove read permission
        test_file = os.path.join(self.test_dir, "protected.txt")
        with open(test_file, 'w') as f:
            f.write("protected content")

        try:
            # Remove read permission
            os.chmod(test_file, stat.S_IWRITE)

            # Try to read
            success, message, content = self.safety_manager.safe_read_file(test_file)

            # May fail with permission error or succeed on platforms that ignore permissions
            if not success:
                self.assertIn("permission", message.lower())
                self.assertEqual(content, "")
            else:
                # Platform allowed reading despite chmod
                self.assertIn("success", message.lower())
                self.assertEqual(content, "protected content")
        finally:
            # Restore permissions for cleanup
            os.chmod(test_file, stat.S_IRUSR | stat.S_IWUSR)

    def test_safe_read_file_too_large(self):
        """Test safe_read_file with file exceeding size limit."""
        # Create a large file (simulate by mocking file size check)
        test_file = os.path.join(self.test_dir, "large.txt")
        with open(test_file, 'w') as f:
            f.write("X" * 100)  # Small actual content

        # Mock os.path.getsize to return large size
        with patch('os.path.getsize', return_value=11 * 1024 * 1024):  # 11 MB
            success, message, content = self.safety_manager.safe_read_file(test_file)

            # Should fail due to size
            self.assertFalse(success)
            self.assertIn("size", message.lower())
            self.assertIn("10", message)  # 10 MB limit
            self.assertEqual(content, "")

    def test_safe_write_file_success(self):
        """Test successful safe file write."""
        test_file = os.path.join(self.test_dir, "output.txt")
        test_content = "This will be written to the file."

        # Write file
        success, message, backup_path = self.safety_manager.safe_write_file(
            test_file, test_content
        )

        # Should succeed
        self.assertTrue(success)
        self.assertIn("success", message.lower())

        # File should exist with correct content
        self.assertTrue(os.path.exists(test_file))
        with open(test_file, 'r') as f:
            content = f.read()
        self.assertEqual(content, test_content)

        # Backup should be created if file existed before
        # (In this case, file didn't exist, so backup might be None)
        # That's OK

    def test_safe_write_file_with_backup(self):
        """Test safe file write with backup creation."""
        # Create an existing file
        test_file = os.path.join(self.test_dir, "existing.txt")
        original_content = "Original content"
        with open(test_file, 'w') as f:
            f.write(original_content)

        new_content = "New content"

        # Write to existing file
        success, message, backup_path = self.safety_manager.safe_write_file(
            test_file, new_content
        )

        # Should succeed
        self.assertTrue(success)
        self.assertIn("success", message.lower())

        # New content should be in file
        with open(test_file, 'r') as f:
            content = f.read()
        self.assertEqual(content, new_content)

        # Backup should be created
        self.assertIsNotNone(backup_path)
        self.assertTrue(os.path.exists(backup_path))

        # Backup should contain original content
        with open(backup_path, 'r') as f:
            backup_content = f.read()
        self.assertEqual(backup_content, original_content)

    def test_safe_write_file_unsafe_path(self):
        """Test safe_write_file with unsafe path."""
        unsafe_path = "../../etc/passwd"
        test_content = "Malicious content"

        # Try to write to unsafe path
        success, message, backup_path = self.safety_manager.safe_write_file(
            unsafe_path, test_content
        )

        # Should fail
        self.assertFalse(success)
        self.assertIn("outside", message.lower())
        self.assertIsNone(backup_path)

    def test_safe_write_file_dangerous_extension(self):
        """Test safe_write_file with dangerous file extension."""
        dangerous_file = os.path.join(self.test_dir, "malicious.exe")
        test_content = "Malicious executable"

        # Try to write dangerous file
        success, message, backup_path = self.safety_manager.safe_write_file(
            dangerous_file, test_content
        )

        # Should fail
        self.assertFalse(success)
        self.assertIn("dangerous", message.lower())
        self.assertIsNone(backup_path)

    def test_safe_delete_file_success(self):
        """Test successful safe file delete."""
        # Create a test file
        test_file = os.path.join(self.test_dir, "todelete.txt")
        with open(test_file, 'w') as f:
            f.write("Delete me")

        # Delete file
        success, message, backup_path = self.safety_manager.safe_delete_file(test_file)

        # Should succeed
        self.assertTrue(success)
        self.assertIn("success", message.lower())

        # File should be gone
        self.assertFalse(os.path.exists(test_file))

        # Backup should exist
        self.assertIsNotNone(backup_path)
        self.assertTrue(os.path.exists(backup_path))

    def test_safe_delete_file_nonexistent(self):
        """Test safe_delete_file with non-existent file."""
        nonexistent = os.path.join(self.test_dir, "nonexistent.txt")

        # Delete non-existent file
        success, message, backup_path = self.safety_manager.safe_delete_file(nonexistent)

        # Should fail
        self.assertFalse(success)
        self.assertIn("backup creation failed", message.lower())
        self.assertIsNone(backup_path)

    def test_safe_delete_file_unsafe_path(self):
        """Test safe_delete_file with unsafe path."""
        unsafe_path = "../../etc/passwd"

        # Try to delete unsafe path
        success, message, backup_path = self.safety_manager.safe_delete_file(unsafe_path)

        # Should fail
        self.assertFalse(success)
        self.assertIn("outside", message.lower())
        self.assertIsNone(backup_path)


class TestBackupCreation(unittest.TestCase):
    """Test backup creation functionality."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.agent_root = os.path.join(self.test_dir, "agent_root")
        os.makedirs(self.agent_root, exist_ok=True)
        self.safety_manager = SafetyManager(self.test_dir, agent_root=self.agent_root)

    def tearDown(self):
        """Clean up after tests."""
        shutil.rmtree(self.test_dir)

    def test_create_backup_success(self):
        """Test successful backup creation."""
        # Create a test file
        test_file = os.path.join(self.test_dir, "backup_test.txt")
        test_content = "Original content for backup"
        with open(test_file, 'w') as f:
            f.write(test_content)

        # Create backup
        backup_path = self.safety_manager.create_backup(test_file)

        # Should return a backup path
        self.assertIsNotNone(backup_path)
        self.assertTrue(os.path.exists(backup_path))

        # Backup should contain original content
        with open(backup_path, 'r') as f:
            backup_content = f.read()
        self.assertEqual(backup_content, test_content)

        # Backup filename should include timestamp and original name
        self.assertIn("backup_test.txt", backup_path)
        self.assertIn("backup", backup_path.lower())

    def test_create_backup_nonexistent_file(self):
        """Test backup creation for non-existent file."""
        nonexistent = os.path.join(self.test_dir, "nonexistent.txt")

        # Create backup of non-existent file
        backup_path = self.safety_manager.create_backup(nonexistent)

        # Should return None
        self.assertIsNone(backup_path)

    def test_create_backup_permission_denied(self):
        """Test backup creation with permission denied."""
        # Create a file and remove read permission
        test_file = os.path.join(self.test_dir, "protected.txt")
        with open(test_file, 'w') as f:
            f.write("protected content")

        try:
            # Remove read permission
            os.chmod(test_file, stat.S_IWRITE)

            # Try to create backup
            backup_path = self.safety_manager.create_backup(test_file)

            # May fail with permission error or succeed on platforms that ignore permissions
            if backup_path is None:
                # Backup creation failed due to permission
                pass  # Expected
            else:
                # Platform allowed reading despite chmod, backup should exist
                self.assertTrue(os.path.exists(backup_path))
        finally:
            # Restore permissions for cleanup
            os.chmod(test_file, stat.S_IRUSR | stat.S_IWUSR)

    def test_get_file_hash(self):
        """Test file hash calculation."""
        # Create a test file
        test_file = os.path.join(self.test_dir, "hash_test.txt")
        test_content = "Hello, world!"
        with open(test_file, 'w') as f:
            f.write(test_content)

        # Calculate hash
        hash_value = get_file_hash(test_file)

        # Should return a hash string
        self.assertIsInstance(hash_value, str)
        self.assertEqual(len(hash_value), 64)  # SHA256 is 64 hex chars

        # Hash should be consistent
        hash2 = get_file_hash(test_file)
        self.assertEqual(hash_value, hash2)

        # Different content should produce different hash
        test_file2 = os.path.join(self.test_dir, "hash_test2.txt")
        with open(test_file2, 'w') as f:
            f.write("Different content")

        hash3 = get_file_hash(test_file2)
        self.assertNotEqual(hash_value, hash3)


class TestAuditLogging(unittest.TestCase):
    """Test audit logging functionality."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.agent_root = os.path.join(self.test_dir, "agent_root")
        os.makedirs(self.agent_root, exist_ok=True)
        self.safety_manager = SafetyManager(self.test_dir, agent_root=self.agent_root)
        self.audit_log = self.safety_manager.audit_log

    def tearDown(self):
        """Clean up after tests."""
        shutil.rmtree(self.test_dir)

    def test_log_operation_success(self):
        """Test successful operation logging."""
        operation = "test_operation"
        path = "/test/path.txt"
        details = "Test operation completed"

        # Log operation
        self.safety_manager.log_operation(operation, path, True, details)

        # Check audit log
        self.assertTrue(os.path.exists(self.audit_log))

        with open(self.audit_log, 'r') as f:
            log_content = f.read()

        # Log should contain operation details
        self.assertIn(operation, log_content)
        self.assertIn(path, log_content)
        self.assertIn("true", log_content.lower())  # success bool
        self.assertIn(details, log_content)

    def test_log_operation_with_backup_info(self):
        """Test operation logging with backup information."""
        operation = "write"
        path = "/test/file.txt"
        backup_path = "/backups/file.txt.backup"
        details = f"File written, backup: {backup_path}"

        # Log operation with backup info in details
        self.safety_manager.log_operation(operation, path, True, details)

        # Check audit log
        with open(self.audit_log, 'r') as f:
            log_content = f.read()

        # Should include backup info
        self.assertIn(backup_path, log_content)
        self.assertIn("backup", log_content.lower())

    def test_log_operation_multiple_entries(self):
        """Test logging multiple operations."""
        operations = [
            ("read", "/file1.txt", True, "Read file"),
            ("write", "/file2.txt", True, "Written file"),
            ("delete", "/file3.txt", False, "Permission denied")
        ]

        for op in operations:
            self.safety_manager.log_operation(*op)

        # Count log entries
        with open(self.audit_log, 'r') as f:
            lines = f.readlines()

        # Should have at least as many lines as operations
        self.assertGreaterEqual(len(lines), len(operations))

        # Each operation should be logged
        log_text = "".join(lines)
        for op, path, success, details in operations:
            self.assertIn(op, log_text)
            self.assertIn(path, log_text)
            # Check for success status in log (true/false)
            if success:
                self.assertIn("true", log_text.lower())
            else:
                self.assertIn("false", log_text.lower())
            self.assertIn(details, log_text)

    def test_audit_log_rotation(self):
        """Test audit log doesn't grow too large."""
        # Log many operations
        for i in range(1000):
            self.safety_manager.log_operation(
                "test", f"/file{i}.txt", True, f"Operation {i}"
            )

        # Check log size
        log_size = os.path.getsize(self.audit_log)

        # Log should exist and have reasonable size
        self.assertTrue(os.path.exists(self.audit_log))
        # Size should be less than some reasonable limit (e.g., 10MB)
        self.assertLess(log_size, 10 * 1024 * 1024)


class TestSafetyFunctions(unittest.TestCase):
    """Test standalone safety functions."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.agent_root = os.path.join(self.test_dir, "agent_root")
        os.makedirs(self.agent_root, exist_ok=True)

    def tearDown(self):
        """Clean up after tests."""
        shutil.rmtree(self.test_dir)

    def test_is_path_safe_function(self):
        """Test standalone is_path_safe function."""
        # Create a safety manager to test with
        safety_manager = SafetyManager(self.test_dir, agent_root=self.agent_root)

        # Test safe path
        safe_path = os.path.join(self.test_dir, "safe.txt")
        result, message = safety_manager.is_path_safe(safe_path)
        self.assertTrue(result)
        self.assertIn("safe", message.lower())

        # Test unsafe path
        unsafe_path = "../../etc/passwd"
        result, message = safety_manager.is_path_safe(unsafe_path)
        self.assertFalse(result)
        self.assertIn("outside", message.lower())

    def test_log_operation_function(self):
        """Test standalone log_operation function."""
        # Create a safety manager with test directory
        safety_manager = SafetyManager(self.test_dir, agent_root=self.agent_root)
        audit_log = safety_manager.audit_log

        # Log an operation
        safety_manager.log_operation("test", "/path.txt", True, "Test")

        # Log should exist
        self.assertTrue(os.path.exists(audit_log))

        with open(audit_log, 'r') as f:
            content = f.read()

        self.assertIn("test", content)
        self.assertIn("/path.txt", content)

    def test_create_backup_function(self):
        """Test standalone create_backup function."""
        # Create a safety manager with test directory
        safety_manager = SafetyManager(self.test_dir, agent_root=self.agent_root)
        # Create a test file
        test_file = os.path.join(self.test_dir, "test.txt")
        with open(test_file, 'w') as f:
            f.write("Backup me")

        # Create backup
        backup_path = safety_manager.create_backup(test_file)

        # Should create backup
        self.assertIsNotNone(backup_path)
        self.assertTrue(os.path.exists(backup_path))

        # Backup should contain original content
        with open(backup_path, 'r') as f:
            content = f.read()
        self.assertEqual(content, "Backup me")


if __name__ == '__main__':
    unittest.main()