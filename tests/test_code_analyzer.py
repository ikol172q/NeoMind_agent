#!/usr/bin/env python3
"""
Comprehensive unit tests for CodeAnalyzer.
Tests file analysis, codebase scanning, safety integration, and file operations.
"""
import os
import sys
import tempfile
import shutil
import unittest
from unittest.mock import Mock, patch, MagicMock, call

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.code_analyzer import CodeAnalyzer


class TestCodeAnalyzerInitialization(unittest.TestCase):
    """Test CodeAnalyzer initialization and basic properties."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up after tests."""
        shutil.rmtree(self.test_dir)

    def test_initialization_with_default_root(self):
        """Test initialization with default root path (current directory)."""
        with patch('os.getcwd', return_value=self.test_dir):
            analyzer = CodeAnalyzer()
            self.assertEqual(analyzer.root_path, self.test_dir)
            self.assertIsNone(analyzer.safety_manager)
            self.assertEqual(analyzer.file_cache, {})
            self.assertEqual(analyzer.file_metadata, {})
            self.assertIsInstance(analyzer.ignore_patterns, list)
            self.assertIn('__pycache__', analyzer.ignore_patterns)
            self.assertIn('.git', analyzer.ignore_patterns)
            self.assertEqual(analyzer.max_files_before_warning, 500)
            self.assertEqual(analyzer.read_files_count, 0)
            self.assertEqual(analyzer.permission_errors, [])

    def test_initialization_with_custom_root(self):
        """Test initialization with custom root path."""
        custom_root = os.path.join(self.test_dir, "custom")
        os.makedirs(custom_root, exist_ok=True)

        analyzer = CodeAnalyzer(root_path=custom_root)
        self.assertEqual(analyzer.root_path, custom_root)

    def test_initialization_with_safety_manager(self):
        """Test initialization with safety manager."""
        mock_safety = Mock()
        analyzer = CodeAnalyzer(safety_manager=mock_safety)
        self.assertEqual(analyzer.safety_manager, mock_safety)


class TestShouldIgnore(unittest.TestCase):
    """Test file/directory ignore logic."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.analyzer = CodeAnalyzer(root_path=self.test_dir)

    def tearDown(self):
        """Clean up after tests."""
        shutil.rmtree(self.test_dir)

    def test_ignore_by_pattern(self):
        """Test ignoring files/directories matching patterns."""
        # Directory patterns
        self.assertTrue(self.analyzer.should_ignore(os.path.join(self.test_dir, "__pycache__")))
        self.assertTrue(self.analyzer.should_ignore(os.path.join(self.test_dir, ".git")))
        self.assertTrue(self.analyzer.should_ignore(os.path.join(self.test_dir, "node_modules")))
        self.assertTrue(self.analyzer.should_ignore(os.path.join(self.test_dir, ".env")))

        # File patterns
        self.assertTrue(self.analyzer.should_ignore(os.path.join(self.test_dir, "file.pyc")))
        self.assertTrue(self.analyzer.should_ignore(os.path.join(self.test_dir, "file.pyo")))

    def test_ignore_binary_extensions(self):
        """Test ignoring binary file extensions."""
        self.assertTrue(self.analyzer.should_ignore(os.path.join(self.test_dir, "file.exe")))
        self.assertTrue(self.analyzer.should_ignore(os.path.join(self.test_dir, "file.dll")))
        self.assertTrue(self.analyzer.should_ignore(os.path.join(self.test_dir, "file.bin")))
        self.assertTrue(self.analyzer.should_ignore(os.path.join(self.test_dir, "image.jpg")))
        self.assertTrue(self.analyzer.should_ignore(os.path.join(self.test_dir, "archive.zip")))

    def test_do_not_ignore_code_files(self):
        """Test not ignoring code/text files."""
        self.assertFalse(self.analyzer.should_ignore(os.path.join(self.test_dir, "script.py")))
        self.assertFalse(self.analyzer.should_ignore(os.path.join(self.test_dir, "file.js")))
        self.assertFalse(self.analyzer.should_ignore(os.path.join(self.test_dir, "README.md")))
        self.assertFalse(self.analyzer.should_ignore(os.path.join(self.test_dir, "config.yaml")))

    def test_ignore_pattern_in_path(self):
        """Test ignoring when pattern appears anywhere in path."""
        self.assertTrue(self.analyzer.should_ignore(os.path.join(self.test_dir, "some", "__pycache__", "file.py")))
        self.assertTrue(self.analyzer.should_ignore(os.path.join(self.test_dir, ".git", "config")))


class TestCountFiles(unittest.TestCase):
    """Test file and directory counting."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.analyzer = CodeAnalyzer(root_path=self.test_dir)

        # Create test directory structure
        os.makedirs(os.path.join(self.test_dir, "src", "utils"), exist_ok=True)
        os.makedirs(os.path.join(self.test_dir, "tests"), exist_ok=True)

        # Create some files
        with open(os.path.join(self.test_dir, "src", "main.py"), "w") as f:
            f.write("print('hello')")
        with open(os.path.join(self.test_dir, "src", "utils", "helper.py"), "w") as f:
            f.write("def help(): pass")
        with open(os.path.join(self.test_dir, "tests", "test_main.py"), "w") as f:
            f.write("import unittest")
        # Create a file that should be ignored
        with open(os.path.join(self.test_dir, ".gitignore"), "w") as f:
            f.write("*.pyc")

    def tearDown(self):
        """Clean up after tests."""
        shutil.rmtree(self.test_dir)

    def test_count_files_in_root(self):
        """Test counting files and directories in root."""
        total_files, total_dirs = self.analyzer.count_files()

        # Should count non-ignored files and directories
        # Directories: src, tests, src/utils (3)
        # Files: main.py, helper.py, test_main.py, .gitignore (ignored) -> 3
        self.assertEqual(total_files, 3)
        self.assertEqual(total_dirs, 3)

    def test_count_files_in_subdirectory(self):
        """Test counting files and directories in subdirectory."""
        total_files, total_dirs = self.analyzer.count_files(os.path.join(self.test_dir, "src"))

        # Directories: utils (1)
        # Files: main.py, helper.py (2)
        self.assertEqual(total_files, 2)
        self.assertEqual(total_dirs, 1)

    def test_count_files_permission_error(self):
        """Test counting files with permission error."""
        # Mock os.walk to raise PermissionError
        with patch('os.walk', side_effect=PermissionError("No permission")):
            total_files, total_dirs = self.analyzer.count_files()

            # Should return zeros without raising exception
            self.assertEqual(total_files, 0)
            self.assertEqual(total_dirs, 0)


class TestFindCodeFiles(unittest.TestCase):
    """Test finding code files."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.analyzer = CodeAnalyzer(root_path=self.test_dir)

        # Create test files
        os.makedirs(os.path.join(self.test_dir, "src"), exist_ok=True)
        with open(os.path.join(self.test_dir, "src", "main.py"), "w") as f:
            f.write("print('hello')")
        with open(os.path.join(self.test_dir, "src", "utils.py"), "w") as f:
            f.write("def util(): pass")
        with open(os.path.join(self.test_dir, "README.md"), "w") as f:
            f.write("# Project")
        with open(os.path.join(self.test_dir, "config.yaml"), "w") as f:
            f.write("key: value")
        # Create ignored file
        with open(os.path.join(self.test_dir, "temp.pyc"), "w") as f:
            f.write("binary")

    def tearDown(self):
        """Clean up after tests."""
        shutil.rmtree(self.test_dir)

    def test_find_all_code_files(self):
        """Test finding all code files without pattern."""
        files = self.analyzer.find_code_files()

        # Should find .py, .md, .yaml files (3 files)
        # temp.pyc should be ignored
        file_names = [os.path.basename(f) for f in files]
        self.assertIn("main.py", file_names)
        self.assertIn("utils.py", file_names)
        self.assertIn("README.md", file_names)
        self.assertIn("config.yaml", file_names)
        self.assertEqual(len(files), 4)  # main.py, utils.py, README.md, config.yaml

    def test_find_code_files_with_pattern(self):
        """Test finding code files with pattern."""
        files = self.analyzer.find_code_files(pattern="*.py")
        print(f"Files found: {files}")

        # Should only find Python files
        for f in files:
            self.assertTrue(f.endswith('.py'), f"File {f} does not end with .py")

        file_names = [os.path.basename(f) for f in files]
        self.assertIn("main.py", file_names)
        self.assertIn("utils.py", file_names)
        self.assertNotIn("README.md", file_names)

    def test_find_code_files_with_limit(self):
        """Test finding code files with limit."""
        files = self.analyzer.find_code_files(limit=2)

        # Should return at most 2 files
        self.assertLessEqual(len(files), 2)

    def test_find_code_files_permission_error(self):
        """Test finding code files with permission error."""
        # Mock os.walk to raise PermissionError
        with patch('os.walk', side_effect=PermissionError("No permission")):
            files = self.analyzer.find_code_files()

            # Should return empty list and record error
            self.assertEqual(files, [])
            self.assertGreater(len(self.analyzer.permission_errors), 0)


class TestSmartFindFiles(unittest.TestCase):
    """Test intelligent file search."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.analyzer = CodeAnalyzer(root_path=self.test_dir)

        # Create test files
        os.makedirs(os.path.join(self.test_dir, "src"), exist_ok=True)
        with open(os.path.join(self.test_dir, "src", "main.py"), "w") as f:
            f.write("print('hello')")
        with open(os.path.join(self.test_dir, "src", "utils.py"), "w") as f:
            f.write("def util(): pass")
        with open(os.path.join(self.test_dir, "README.md"), "w") as f:
            f.write("# Project")
        with open(os.path.join(self.test_dir, "main_test.py"), "w") as f:
            f.write("import unittest")

    def tearDown(self):
        """Clean up after tests."""
        shutil.rmtree(self.test_dir)

    def test_smart_find_exact_filename(self):
        """Test smart find with exact filename match."""
        results = self.analyzer.smart_find_files("main.py", max_results=5)

        # Should find main.py with high score
        self.assertGreater(len(results), 0)
        self.assertEqual(results[0]['name'], "main.py")
        self.assertEqual(results[0]['relative'], os.path.join("src", "main.py"))

    def test_smart_find_filename_contains(self):
        """Test smart find with partial filename match."""
        results = self.analyzer.smart_find_files("main", max_results=5)

        # Should find main.py and main_test.py
        file_names = [r['name'] for r in results]
        self.assertIn("main.py", file_names)
        self.assertIn("main_test.py", file_names)

    def test_smart_find_path_contains(self):
        """Test smart find with path contains."""
        results = self.analyzer.smart_find_files("src", max_results=5)

        # Should find files in src directory
        for r in results:
            self.assertIn("src", r['path'])

    def test_smart_find_with_limit(self):
        """Test smart find with result limit."""
        results = self.analyzer.smart_find_files("main", max_results=1)

        # Should return at most 1 result
        self.assertLessEqual(len(results), 1)

    def test_smart_find_no_matches(self):
        """Test smart find with no matches."""
        results = self.analyzer.smart_find_files("nonexistent", max_results=5)

        # Should return empty list
        self.assertEqual(results, [])


class TestReadFileSafe(unittest.TestCase):
    """Test safe file reading."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.analyzer = CodeAnalyzer(root_path=self.test_dir)

        # Create a test file
        self.test_file = os.path.join(self.test_dir, "test.txt")
        with open(self.test_file, "w", encoding="utf-8") as f:
            f.write("Line 1\nLine 2\nLine 3")

    def tearDown(self):
        """Clean up after tests."""
        shutil.rmtree(self.test_dir)

    def test_read_file_safe_with_safety_manager(self):
        """Test reading file with safety manager."""
        mock_safety = Mock()
        mock_safety.safe_read_file.return_value = (True, "Success", "File content")
        analyzer = CodeAnalyzer(safety_manager=mock_safety, root_path=self.test_dir)

        success, message, content = analyzer.read_file_safe(self.test_file)

        # Should delegate to safety manager
        self.assertTrue(success)
        self.assertEqual(message, "Success")
        self.assertEqual(content, "File content")
        mock_safety.safe_read_file.assert_called_once_with(self.test_file, max_lines=1000000)

        # Should cache content
        self.assertIn(self.test_file, analyzer.file_cache)
        self.assertEqual(analyzer.file_cache[self.test_file], "File content")

    def test_read_file_safe_success(self):
        """Test successful file read without safety manager."""
        success, message, content = self.analyzer.read_file_safe(self.test_file)

        self.assertTrue(success)
        self.assertEqual(message, "Success")
        self.assertEqual(content, "Line 1\nLine 2\nLine 3")

        # Should cache content and metadata
        self.assertIn(self.test_file, self.analyzer.file_cache)
        self.assertIn(self.test_file, self.analyzer.file_metadata)
        metadata = self.analyzer.file_metadata[self.test_file]
        self.assertEqual(metadata['lines'], 3)
        self.assertEqual(metadata['ext'], '.txt')

    def test_read_file_safe_nonexistent(self):
        """Test reading non-existent file."""
        success, message, content = self.analyzer.read_file_safe(os.path.join(self.test_dir, "nonexistent.txt"))

        self.assertFalse(success)
        self.assertIn("not found", message)
        self.assertEqual(content, "")

    def test_read_file_safe_directory(self):
        """Test reading a directory."""
        success, message, content = self.analyzer.read_file_safe(self.test_dir)

        self.assertFalse(success)
        self.assertIn("Not a file", message)

    def test_read_file_safe_no_permission(self):
        """Test reading file without permission."""
        # Mock os.access to return False
        with patch('os.access', return_value=False):
            success, message, content = self.analyzer.read_file_safe(self.test_file)

            self.assertFalse(success)
            self.assertIn("No read permission", message)

    def test_read_file_safe_too_large(self):
        """Test reading file that exceeds size limit."""
        # Mock os.path.getsize to return large size
        with patch('os.path.getsize', return_value=11 * 1024 * 1024):  # 11MB
            success, message, content = self.analyzer.read_file_safe(self.test_file)

            self.assertFalse(success)
            self.assertIn("too large", message)

    def test_read_file_safe_encoding_fallback(self):
        """Test reading file with encoding fallback."""
        # Create a file with non-UTF-8 encoding
        latin_file = os.path.join(self.test_dir, "latin.txt")
        with open(latin_file, "w", encoding="latin-1") as f:
            f.write("café")  # Contains non-ASCII character

        # Mock UTF-8 read to raise UnicodeDecodeError, then succeed with latin-1
        original_open = open
        def mock_open(file, mode='r', encoding=None, **kwargs):
            if encoding == 'utf-8':
                raise UnicodeDecodeError('utf-8', b'', 0, 1, 'test')
            return original_open(file, mode, encoding=encoding or 'utf-8', **kwargs)

        with patch('builtins.open', side_effect=mock_open):
            success, message, content = self.analyzer.read_file_safe(latin_file)

            # Should eventually succeed with fallback encoding
            self.assertTrue(success)
            self.assertEqual(content, "café")


class TestAnalyzeFile(unittest.TestCase):
    """Test file analysis."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.analyzer = CodeAnalyzer(root_path=self.test_dir)

        # Create a Python file for analysis
        self.python_file = os.path.join(self.test_dir, "test.py")
        content = '''"""
Module docstring.
"""
import os
import sys

def hello(name):
    """Say hello."""
    return f"Hello, {name}!"

class Calculator:
    """Simple calculator."""

    def add(self, a, b):
        return a + b
'''
        with open(self.python_file, "w", encoding="utf-8") as f:
            f.write(content)

    def tearDown(self):
        """Clean up after tests."""
        shutil.rmtree(self.test_dir)

    def test_analyze_file_success(self):
        """Test successful file analysis."""
        analysis = self.analyzer.analyze_file(self.python_file)

        self.assertTrue(analysis['success'])
        self.assertEqual(analysis['path'], self.python_file)
        self.assertGreater(analysis['size'], 0)
        self.assertGreater(analysis['lines'], 0)

        # Should detect imports
        self.assertEqual(len(analysis['imports']), 2)
        import_contents = [i['content'] for i in analysis['imports']]
        self.assertIn('import os', import_contents)
        self.assertIn('import sys', import_contents)

        # Should detect functions (including methods)
        self.assertEqual(len(analysis['functions']), 2)
        function_names = [f['name'] for f in analysis['functions']]
        self.assertIn('hello', function_names)
        self.assertIn('add', function_names)

        # Should detect classes
        self.assertEqual(len(analysis['classes']), 1)
        self.assertEqual(analysis['classes'][0]['name'], 'Calculator')

        # Should include preview
        self.assertIn('content_preview', analysis)
        self.assertIn('Module docstring', analysis['content_preview'])

    def test_analyze_file_read_failure(self):
        """Test analysis when file read fails."""
        analysis = self.analyzer.analyze_file(os.path.join(self.test_dir, "nonexistent.py"))

        self.assertFalse(analysis['success'])
        self.assertIn('error', analysis)

    def test_analyze_non_python_file(self):
        """Test analysis of non-Python file."""
        text_file = os.path.join(self.test_dir, "readme.txt")
        with open(text_file, "w") as f:
            f.write("Just text")

        analysis = self.analyzer.analyze_file(text_file)

        # Should succeed but have empty imports/functions/classes
        self.assertTrue(analysis['success'])
        self.assertEqual(analysis['imports'], [])
        self.assertEqual(analysis['functions'], [])
        self.assertEqual(analysis['classes'], [])


class TestGetCodeSummary(unittest.TestCase):
    """Test codebase summary generation."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.analyzer = CodeAnalyzer(root_path=self.test_dir)

        # Create test codebase
        os.makedirs(os.path.join(self.test_dir, "src"), exist_ok=True)
        with open(os.path.join(self.test_dir, "src", "main.py"), "w") as f:
            f.write("print('hello')\n" * 5)  # 5 lines
        with open(os.path.join(self.test_dir, "README.md"), "w") as f:
            f.write("# Project\n" * 3)  # 3 lines
        with open(os.path.join(self.test_dir, "config.yaml"), "w") as f:
            f.write("key: value\n")  # 1 line

    def tearDown(self):
        """Clean up after tests."""
        shutil.rmtree(self.test_dir)

    def test_get_code_summary_small_codebase(self):
        """Test summary for small codebase."""
        summary = self.analyzer.get_code_summary()

        self.assertEqual(summary['total_files'], 3)
        self.assertIn('file_types', summary)

        # Should count file types
        file_types = summary['file_types']
        self.assertIn('.py', file_types)
        self.assertIn('.md', file_types)
        self.assertIn('.yaml', file_types)

        # Should count lines (for .py and .md files)
        self.assertGreater(summary['total_lines'], 0)

        # Should calculate total size
        self.assertIn('MB', summary['total_size'])

        # Should include root path
        self.assertEqual(summary['root_path'], self.test_dir)

    def test_get_code_summary_large_codebase_warning(self):
        """Test summary for large codebase triggers warning."""
        # Mock find_code_files to return many files
        mock_files = [f"file{i}.py" for i in range(1001)]
        with patch.object(self.analyzer, 'find_code_files', return_value=mock_files):
            summary = self.analyzer.get_code_summary()

            # Should include warning
            self.assertIn('warning', summary)
            self.assertIn('Large codebase', summary['warning'])
            self.assertIn('suggestion', summary)


class TestWriteFileSafe(unittest.TestCase):
    """Test safe file writing."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.analyzer = CodeAnalyzer(root_path=self.test_dir)

        # Create a test file to modify
        self.test_file = os.path.join(self.test_dir, "test.txt")
        with open(self.test_file, "w", encoding="utf-8") as f:
            f.write("Original content")

    def tearDown(self):
        """Clean up after tests."""
        shutil.rmtree(self.test_dir)

    def test_write_file_safe_with_safety_manager(self):
        """Test writing file with safety manager."""
        mock_safety = Mock()
        mock_safety.safe_write_file.return_value = (True, "Success", "/backup/path")
        analyzer = CodeAnalyzer(safety_manager=mock_safety, root_path=self.test_dir)

        success, message = analyzer.write_file_safe(self.test_file, "New content", backup=True)

        # Should delegate to safety manager
        self.assertTrue(success)
        self.assertEqual(message, "Success")
        mock_safety.safe_write_file.assert_called_once_with(
            self.test_file, "New content", create_backup=True
        )

        # Should update cache
        self.assertIn(self.test_file, analyzer.file_cache)
        self.assertEqual(analyzer.file_cache[self.test_file], "New content")

    def test_write_file_safe_success(self):
        """Test successful file write without safety manager."""
        success, message = self.analyzer.write_file_safe(self.test_file, "Updated content", backup=False)

        self.assertTrue(success)
        self.assertIn("written successfully", message)

        # Verify file content
        with open(self.test_file, "r") as f:
            self.assertEqual(f.read(), "Updated content")

        # Should update cache and metadata
        self.assertIn(self.test_file, self.analyzer.file_cache)
        self.assertEqual(self.analyzer.file_cache[self.test_file], "Updated content")
        metadata = self.analyzer.file_metadata[self.test_file]
        self.assertEqual(metadata['lines'], 1)  # Single line

    def test_write_file_safe_create_new(self):
        """Test writing new file."""
        new_file = os.path.join(self.test_dir, "new.txt")
        success, message = self.analyzer.write_file_safe(new_file, "New file content", backup=False)

        self.assertTrue(success)
        self.assertTrue(os.path.exists(new_file))

        with open(new_file, "r") as f:
            self.assertEqual(f.read(), "New file content")

    def test_write_file_safe_outside_root(self):
        """Test writing file outside codebase root."""
        outside_file = os.path.join(tempfile.gettempdir(), "outside.txt")
        success, message = self.analyzer.write_file_safe(outside_file, "Content", backup=False)

        # Should fail because file is outside root
        self.assertFalse(success)
        self.assertIn("outside codebase root", message)

    def test_write_file_safe_no_write_permission(self):
        """Test writing file without permission."""
        # Mock os.access to return False for write permission
        with patch('os.access', return_value=False):
            success, message = self.analyzer.write_file_safe(self.test_file, "Content", backup=False)

            self.assertFalse(success)
            self.assertIn("No write permission", message)

    def test_write_file_safe_content_too_large(self):
        """Test writing content that exceeds size limit."""
        large_content = "x" * (11 * 1024 * 1024)  # 11MB

        success, message = self.analyzer.write_file_safe(self.test_file, large_content, backup=False)

        self.assertFalse(success)
        self.assertIn("exceeds 10MB limit", message)

    def test_write_file_safe_backup_creation(self):
        """Test writing file with backup."""
        original_content = "Original content"

        success, message = self.analyzer.write_file_safe(self.test_file, "New content", backup=True)

        self.assertTrue(success)
        self.assertIn("backup", message)

        # Backup file should exist with timestamp pattern
        import glob
        backup_files = glob.glob(self.test_file + ".backup_*")
        self.assertGreater(len(backup_files), 0)

        # Verify backup content
        with open(backup_files[0], "r") as f:
            self.assertEqual(f.read(), original_content)

    def test_write_file_safe_parent_directory_creation(self):
        """Test writing file with non-existent parent directories."""
        nested_file = os.path.join(self.test_dir, "deeply", "nested", "file.txt")
        success, message = self.analyzer.write_file_safe(nested_file, "Nested content", backup=False)

        self.assertTrue(success)
        self.assertTrue(os.path.exists(nested_file))


if __name__ == '__main__':
    unittest.main()