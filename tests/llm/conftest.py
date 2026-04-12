"""
Configuration for LLM simulation tests.

These tests require a real LLM API key and make actual API calls.
They are NOT optional — they must run as part of the full test suite
to verify NeoMind's features work end-to-end with real LLM responses.

If no API key is available, tests are SKIPPED (not failed) with a
clear message explaining what's needed.
"""

import os
import sys
import pytest

# Add project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def pytest_collection_modifyitems(config, items):
    """Add 'llm' marker to all tests in this directory."""
    for item in items:
        if 'llm' in str(item.fspath):
            item.add_marker(pytest.mark.llm)


def pytest_configure(config):
    """Register the 'llm' marker."""
    config.addinivalue_line(
        "markers",
        "llm: tests that require real LLM API calls (always run if API key available)"
    )
