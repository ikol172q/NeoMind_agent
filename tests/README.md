# Comprehensive Unit Test Suite

This directory contains comprehensive unit tests for the DeepSeek Agent codebase. The tests cover all major functionalities and components identified in the codebase analysis.

## Test Structure

The test suite is organized into comprehensive test files for each major component:

### Core Components
- **`test_core.py`** - Tests for `DeepSeekStreamingChat` class
  - Initialization and configuration
  - Mode switching (chat ↔ coding)
  - Conversation history management
  - Status buffer and debug messages
  - Thinking mode toggling
  - Workspace manager lazy initialization

- **`test_config.py`** - Tests for `AgentConfigManager` configuration system
  - Configuration loading from YAML
  - Environment variable overrides
  - Value updates and persistence
  - Mode switching functionality
  - Auto-features configuration
  - Property accessors with defaults

### Safety System
- **`test_safety.py`** - Tests for `SafetyManager` and safety functions
  - Path validation and traversal prevention
  - Dangerous file extension blocking
  - System directory protection
  - Safe file operations (read/write/delete)
  - Backup creation and restoration
  - Audit logging
  - File size limits (10MB)
  - Permission handling

### Search Functionality
- **`test_search.py`** - Tests for `OptimizedDuckDuckGoSearch` and search
  - Auto-search trigger detection
  - Time-sensitive query identification
  - Search result caching (5-minute TTL)
  - Synchronous and asynchronous search
  - Result cleaning and formatting
  - HTML content extraction
  - Error handling and fallbacks

### Workspace Management
- **`test_workspace.py`** - Tests for `WorkspaceManager`
  - Project structure scanning
  - File caching with persistence
  - Recent file access tracking
  - Project tree generation
  - Ignore patterns (.git, __pycache__, node_modules)
  - File metadata tracking
  - Integration with code analyzer

## Test Design Principles

### Isolation
- Each test is isolated using `setUp()` and `tearDown()` methods
- Temporary directories are created for file system tests
- External dependencies are mocked using `unittest.mock`

### Comprehensiveness
- Tests cover normal operation paths
- Tests cover edge cases and error conditions
- Tests validate both success and failure scenarios
- Tests verify proper error messages and handling

### Mocking Strategy
- **API Calls**: Mock `requests` and `aiohttp` for HTTP requests
- **File System**: Use `tempfile.TemporaryDirectory` for isolated file operations
- **External Libraries**: Mock imports for optional dependencies
- **Configuration**: Mock `agent_config` for controlled test environments

### Assertions
- Clear, descriptive assertion messages
- Verification of method calls with correct arguments
- Validation of return values and side effects
- Error condition testing with appropriate exceptions

## Running Tests

### Using pytest (Recommended)
```bash
# Run all tests
python -m pytest tests/

# Run specific test module
python -m pytest tests/test_core.py

# Run with verbose output
python -m pytest tests/ -v

# Run with coverage report
python -m pytest tests/ --cov=agent --cov-report=html
```

### Using the Test Runner
```bash
# Run all tests
python tests/run_tests.py

# List available test modules
python tests/run_tests.py --list

# Run specific test module
python tests/run_tests.py --module test_core
```

### Using unittest Directly
```bash
# Run all tests
python -m unittest discover tests

# Run specific test module
python -m unittest tests.test_core
```

## Test Coverage Areas

### API Integration
- DeepSeek API communication (mocked)
- Streaming responses with thinking mode
- Model listing and switching
- Error handling and retries

### Safety Features
- Path traversal prevention
- Dangerous command blocking
- File size limits and validation
- Backup creation and audit logging
- System directory protection

### Auto-Features
- Natural language command interpretation
- Auto-search for time-sensitive queries
- Mode-aware behavior (chat vs coding)
- Confidence threshold filtering

### Workspace Awareness
- Project structure scanning
- File caching and metadata tracking
- Recent file access tracking
- Auto-file operations in coding mode

## Adding New Tests

When adding tests for new functionality:

1. **Follow existing patterns**: Use the same structure and mocking approach
2. **Test isolation**: Ensure tests don't depend on external state
3. **Comprehensive coverage**: Test success, failure, and edge cases
4. **Descriptive names**: Use clear test method names
5. **Assertion messages**: Include helpful failure messages

Example test structure:
```python
class TestNewComponent(unittest.TestCase):
    def setUp(self):
        # Setup test environment
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        # Cleanup
        shutil.rmtree(self.test_dir)

    def test_feature_success(self):
        # Test normal operation
        pass

    def test_feature_failure(self):
        # Test error handling
        pass

    def test_feature_edge_case(self):
        # Test edge cases
        pass
```

## Dependencies for Running Tests

The tests require the same dependencies as the main project:
- `unittest` (standard library)
- `pytest` (for pytest runner)
- `unittest.mock` (standard library)

Optional dependencies are mocked in tests:
- `html2text`, `trafilatura`, `requests-html`, `chardet`

## Test Results Interpretation

- **Passing tests**: Functionality works as expected
- **Failing tests**: Indicate bugs or regressions
- **Skipped tests**: Missing optional dependencies
- **Error tests**: Unhandled exceptions or setup issues

## Integration with CI/CD

These tests can be integrated into CI/CD pipelines:
- Run on every commit
- Block deployment on test failures
- Generate coverage reports
- Parallel test execution for speed

## Future Test Expansion Areas

Based on codebase analysis, additional test modules could cover:

1. **Code Analyzer** (`test_code_analyzer.py`)
2. **Self-Iteration Framework** (`test_self_iteration.py`)
3. **Task Management** (`test_task_manager.py`)
4. **Planning System** (`test_planner.py`)
5. **Command Execution** (`test_command_executor.py`)
6. **Context Management** (`test_context_manager.py`)
7. **Help System** (`test_help_system.py`)
8. **Formatter** (`test_formatter.py`)
9. **CLI Interface** (`test_cli_interface.py`)
10. **Natural Language Processing** (enhance existing tests)

## Notes

- Existing tests in the project root (`test_*.py`) are not included in this directory
- These tests are more comprehensive and follow a consistent structure
- The test suite is designed to be extensible as new features are added
- Mocking ensures tests run without external dependencies or network access