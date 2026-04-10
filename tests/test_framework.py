"""
Test Framework for NeoMind Agent

Comprehensive test utilities and fixtures for all phases.

Created: 2026-04-01 (Phase 0 - Infrastructure)
"""

import pytest
import asyncio
import tempfile
import shutil
from pathlib import Path
from typing import Generator, Dict, Any
from unittest.mock import MagicMock, patch


# ── Fixtures ────────────────────────────────────────────────────────

@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for tests."""
    dir_path = Path(tempfile.mkdtemp())
    yield dir_path
    shutil.rmtree(dir_path, ignore_errors=True)


@pytest.fixture
def temp_file(temp_dir: Path) -> Generator[Path, None, None]:
    """Create a temporary file for tests."""
    file_path = temp_dir / "test_file.txt"
    file_path.write_text("Test content\n")
    yield file_path


@pytest.fixture
def mock_agent() -> MagicMock:
    """Create a mock NeoMindAgent instance."""
    agent = MagicMock()
    agent.mode = "chat"
    agent.model = "deepseek-chat"
    agent.conversation_history = []
    agent.verbose_mode = False
    agent.status_buffer = []
    agent._code_changes = []
    return agent


@pytest.fixture
def mock_formatter() -> MagicMock:
    """Create a mock Formatter instance."""
    formatter = MagicMock()
    formatter.success = lambda x: f"✓ {x}"
    formatter.error = lambda x: f"✗ {x}"
    formatter.warning = lambda x: f"⚠ {x}"
    formatter.info = lambda x: f"ℹ {x}"
    return formatter


@pytest.fixture
def mock_token_budget() -> MagicMock:
    """Create a mock TokenBudget instance."""
    from agent.token_budget import TokenBudget
    return TokenBudget(100000)


@pytest.fixture
def sample_conversation() -> list:
    """Create a sample conversation history."""
    return [
        {"role": "system", "content": "You are NeoMind."},
        {"role": "user", "content": "Hello!"},
        {"role": "assistant", "content": "Hi there! How can I help you?"},
        {"role": "user", "content": "Tell me about yourself."},
    ]


@pytest.fixture
def sample_code_file(temp_dir: Path) -> Path:
    """Create a sample Python code file for testing."""
    code = '''
def hello_world():
    """A simple greeting function."""
    print("Hello, World!")
    return True

class Calculator:
    """A simple calculator class."""

    def add(self, a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    def multiply(self, a: int, b: int) -> int:
        """Multiply two numbers."""
        return a * b

if __name__ == "__main__":
    hello_world()
    calc = Calculator()
    print(calc.add(5, 3))
'''
    file_path = temp_dir / "sample.py"
    file_path.write_text(code)
    return file_path


@pytest.fixture
def sample_config() -> Dict[str, Any]:
    """Create a sample configuration."""
    return {
        "model": "deepseek-chat",
        "fallback_model": "deepseek-reasoner",
        "mode": "chat",
        "max_tokens": 100000,
        "temperature": 0.7,
        "show_status_bar": True,
    }


# ── Helper Functions ─────────────────────────────────────────────────

def assert_valid_response(response: str) -> None:
    """Assert that a response is valid (non-empty string)."""
    assert response is not None
    assert isinstance(response, str)
    assert len(response) > 0


def assert_command_format(result: str, prefix: str = None) -> None:
    """Assert that a command result has proper formatting."""
    assert_valid_response(result)
    if prefix:
        assert prefix in result


def create_mock_file(path: Path, content: str) -> Path:
    """Create a mock file with given content."""
    path.write_text(content)
    return path


def create_mock_directory(base: Path, structure: Dict[str, Any]) -> Path:
    """Create a mock directory structure."""
    for name, content in structure.items():
        item_path = base / name
        if isinstance(content, dict):
            item_path.mkdir(exist_ok=True)
            create_mock_directory(item_path, content)
        else:
            item_path.write_text(content)
    return base


# ── Async Test Helpers ───────────────────────────────────────────────

@pytest.fixture
def event_loop():
    """Create an event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


async def async_test_wrapper(coro):
    """Wrapper for running async tests."""
    return await coro


# ── Test Categories ───────────────────────────────────────────────────

class TestCategory:
    """Test category markers for pytest."""

    INFRASTRUCTURE = "infrastructure"
    COMMANDS = "commands"
    LLM = "llm"
    MEMORY = "memory"
    INTEGRATION = "integration"
    PERFORMANCE = "performance"


# ── Assertion Helpers ────────────────────────────────────────────────

class AssertionHelpers:
    """Collection of assertion helpers for common checks."""

    @staticmethod
    def assert_file_exists(path: Path) -> None:
        """Assert that a file exists."""
        assert path.exists(), f"File {path} does not exist"
        assert path.is_file(), f"{path} is not a file"

    @staticmethod
    def assert_file_contains(path: Path, content: str) -> None:
        """Assert that a file contains specific content."""
        AssertionHelpers.assert_file_exists(path)
        file_content = path.read_text()
        assert content in file_content, f"Content '{content}' not found in {path}"

    @staticmethod
    def assert_json_valid(data: str) -> None:
        """Assert that a string is valid JSON."""
        import json
        try:
            json.loads(data)
        except json.JSONDecodeError as e:
            pytest.fail(f"Invalid JSON: {e}")

    @staticmethod
    def assert_token_count(response: str, min_tokens: int = 1, max_tokens: int = 10000) -> None:
        """Assert that response has reasonable token count."""
        # Rough approximation: 1 token ≈ 4 characters
        approx_tokens = len(response) // 4
        assert min_tokens <= approx_tokens <= max_tokens, \
            f"Token count {approx_tokens} outside range [{min_tokens}, {max_tokens}]"


# ── Mock Factories ────────────────────────────────────────────────────

class MockFactory:
    """Factory for creating mock objects."""

    @staticmethod
    def create_mock_response(content: str, role: str = "assistant") -> Dict[str, Any]:
        """Create a mock LLM response."""
        return {
            "role": role,
            "content": content,
            "finish_reason": "stop",
        }

    @staticmethod
    def create_mock_tool_call(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Create a mock tool call."""
        import json
        return {
            "id": f"call_{name}",
            "type": "function",
            "function": {
                "name": name,
                "arguments": json.dumps(arguments),
            }
        }

    @staticmethod
    def create_mock_search_result(query: str, results: list) -> Dict[str, Any]:
        """Create a mock search result."""
        return {
            "query": query,
            "results": results,
            "total": len(results),
        }


# ── Pytest Configuration ─────────────────────────────────────────────

def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "infrastructure: mark test as infrastructure test"
    )
    config.addinivalue_line(
        "markers", "commands: mark test as command handler test"
    )
    config.addinivalue_line(
        "markers", "llm: mark test as LLM integration test"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow running"
    )


__all__ = [
    # Fixtures
    'temp_dir',
    'temp_file',
    'mock_agent',
    'mock_formatter',
    'mock_token_budget',
    'sample_conversation',
    'sample_code_file',
    'sample_config',
    # Helpers
    'assert_valid_response',
    'assert_command_format',
    'create_mock_file',
    'create_mock_directory',
    'TestCategory',
    'AssertionHelpers',
    'MockFactory',
]
