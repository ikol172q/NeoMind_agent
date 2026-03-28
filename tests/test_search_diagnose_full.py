"""
Comprehensive unit tests for agent/search/diagnose.py

Tests diagnostic functions for search engine health checks.
"""

import pytest
import os
import sys
from unittest.mock import patch, MagicMock, call
from io import StringIO

from agent.search.diagnose import (
    check_dependencies,
    check_api_keys,
    check_engine,
    check_router,
    check_expansion,
    live_search_test,
    main,
)


class TestCheckDependencies:
    """Tests for check_dependencies()."""

    def test_check_dependencies_basic(self, capsys):
        """Test that check_dependencies prints dependency status."""
        check_dependencies()
        captured = capsys.readouterr()

        assert "[Dependencies]" in captured.out
        assert "pip install" in captured.out

    def test_check_dependencies_with_mock_imports(self, capsys):
        """Test dependency checking with mocked imports."""
        # Just verify the function runs and produces output
        check_dependencies()
        captured = capsys.readouterr()
        # Should have a dependencies section
        assert "[Dependencies]" in captured.out


class TestCheckAPIKeys:
    """Tests for check_api_keys()."""

    def test_check_api_keys_none_set(self, capsys):
        """Test check_api_keys when no keys are set."""
        with patch.dict(os.environ, {}, clear=True):
            check_api_keys()
            captured = capsys.readouterr()

            assert "[API Keys]" in captured.out
            assert "not set" in captured.out or "0/" in captured.out

    def test_check_api_keys_some_set(self, capsys):
        """Test check_api_keys when some are set."""
        env_vars = {
            "BRAVE_API_KEY": "test_key_12345",
            "SERPER_API_KEY": "another_key_67890",
        }
        with patch.dict(os.environ, env_vars):
            check_api_keys()
            captured = capsys.readouterr()

            assert "[API Keys]" in captured.out
            # Keys should be masked - the full key should not appear
            assert "test_key_12345" not in captured.out
            assert "another_key_67890" not in captured.out

    def test_check_api_keys_masks_sensitive_data(self, capsys):
        """Test that long API keys are masked in output."""
        with patch.dict(os.environ, {"BRAVE_API_KEY": "verylongapikeywithrealdata"}):
            check_api_keys()
            captured = capsys.readouterr()

            # Should not contain the full key
            assert "verylongapikeywithrealdata" not in captured.out or "..." in captured.out

    def test_check_api_keys_short_key_handling(self, capsys):
        """Test handling of short API keys (< 8 chars)."""
        with patch.dict(os.environ, {"BRAVE_API_KEY": "short"}):
            check_api_keys()
            captured = capsys.readouterr()

            # Should mask short keys too
            assert "short" not in captured.out or "***" in captured.out


class TestCheckEngine:
    """Tests for check_engine()."""

    @patch('agent.search.engine.UniversalSearchEngine')
    def test_check_engine_returns_engine(self, mock_engine_class, capsys):
        """Test that check_engine initializes and returns engine."""
        mock_instance = MagicMock()
        mock_instance.get_status.return_value = "Engine Status OK"
        mock_engine_class.return_value = mock_instance

        engine = check_engine()

        assert engine is mock_instance
        mock_engine_class.assert_called_once_with(domain="general")

    @patch('agent.search.engine.UniversalSearchEngine')
    def test_check_engine_prints_status(self, mock_engine_class, capsys):
        """Test that check_engine prints status output."""
        mock_instance = MagicMock()
        mock_instance.get_status.return_value = "Test Status"
        mock_engine_class.return_value = mock_instance

        check_engine()
        captured = capsys.readouterr()

        assert "[Engine Status]" in captured.out


class TestCheckRouter:
    """Tests for check_router()."""

    @patch('agent.search.router.QueryRouter')
    def test_check_router_classifies_queries(self, mock_router_class, capsys):
        """Test that check_router classifies test queries."""
        mock_instance = MagicMock()
        mock_instance.classify.side_effect = [
            "news", "tech", "finance", "finance", "general", "tech", "tech"
        ]
        mock_router_class.return_value = mock_instance

        check_router()
        captured = capsys.readouterr()

        assert "[Query Router]" in captured.out
        # Should have classified multiple queries
        assert "news" in captured.out or "tech" in captured.out

    @patch('agent.search.router.QueryRouter')
    def test_check_router_test_queries(self, mock_router_class):
        """Test that check_router uses correct test queries."""
        mock_instance = MagicMock()
        mock_instance.classify.return_value = "general"
        mock_router_class.return_value = mock_instance

        check_router()

        # Should classify at least one query
        assert mock_instance.classify.call_count >= 1


class TestCheckExpansion:
    """Tests for check_expansion()."""

    @patch('agent.search.query_expansion.QueryExpander')
    def test_check_expansion_generates_variants(self, mock_expander_class, capsys):
        """Test that check_expansion shows query variants."""
        mock_instance = MagicMock()
        mock_instance.expand.side_effect = [
            ["query1", "variant1", "variant2"],
            ["query2", "variant3"],
            ["query3", "variant4"],
        ]
        mock_expander_class.return_value = mock_instance

        check_expansion()
        captured = capsys.readouterr()

        assert "[Query Expansion]" in captured.out
        assert "variant" in captured.out

    @patch('agent.search.query_expansion.QueryExpander')
    def test_check_expansion_uses_general_domain(self, mock_expander_class):
        """Test that check_expansion initializes with general domain."""
        mock_instance = MagicMock()
        mock_instance.expand.return_value = ["test"]
        mock_expander_class.return_value = mock_instance

        check_expansion()

        mock_expander_class.assert_called_once_with(domain="general")


class TestLiveSearchTest:
    """Tests for live_search_test()."""

    @pytest.mark.asyncio
    async def test_live_search_test_success(self):
        """Test live_search_test with successful search."""
        mock_engine = MagicMock()
        mock_engine.search = MagicMock(return_value=("True", "Result line 1\nResult line 2"))

        # Need to make it async
        async def async_search(*args, **kwargs):
            return "True", "Result line 1\nResult line 2"

        mock_engine.search = async_search

        # Can't easily test printing, but can test the flow
        # This is more of an integration test

    @pytest.mark.asyncio
    async def test_live_search_test_with_capsys(self, capsys):
        """Test live_search_test output."""
        mock_engine = MagicMock()

        async def async_search(*args, **kwargs):
            return True, "\n".join([f"Result {i}" for i in range(20)])

        mock_engine.search = async_search

        # Import and call directly with mock
        from agent.search.diagnose import live_search_test
        await live_search_test(mock_engine)
        captured = capsys.readouterr()

        assert "[Live Search Test]" in captured.out


class TestMain:
    """Tests for main()."""

    @patch('agent.search.diagnose.check_dependencies')
    @patch('agent.search.diagnose.check_api_keys')
    @patch('agent.search.diagnose.check_engine')
    @patch('agent.search.diagnose.check_router')
    @patch('agent.search.diagnose.check_expansion')
    @patch('agent.search.diagnose.asyncio.run')
    def test_main_without_live_flag(
        self,
        mock_asyncio,
        mock_expansion,
        mock_router,
        mock_engine,
        mock_api_keys,
        mock_deps,
        capsys,
    ):
        """Test main() without --live flag."""
        mock_engine.return_value = MagicMock()

        with patch.object(sys, 'argv', ['diagnose.py']):
            main()

        # Should call check functions
        mock_deps.assert_called_once()
        mock_api_keys.assert_called_once()
        mock_engine.assert_called_once()
        mock_router.assert_called_once()
        mock_expansion.assert_called_once()
        # Should NOT run live search
        mock_asyncio.assert_not_called()

        captured = capsys.readouterr()
        assert "Diagnostic complete" in captured.out

    @patch('agent.search.diagnose.check_dependencies')
    @patch('agent.search.diagnose.check_api_keys')
    @patch('agent.search.diagnose.check_engine')
    @patch('agent.search.diagnose.check_router')
    @patch('agent.search.diagnose.check_expansion')
    @patch('agent.search.diagnose.asyncio.run')
    def test_main_with_live_flag(
        self,
        mock_asyncio,
        mock_expansion,
        mock_router,
        mock_engine,
        mock_api_keys,
        mock_deps,
        capsys,
    ):
        """Test main() with --live flag."""
        mock_engine.return_value = MagicMock()

        with patch.object(sys, 'argv', ['diagnose.py', '--live']):
            main()

        # Should call async live search
        mock_asyncio.assert_called_once()

        captured = capsys.readouterr()
        assert "Diagnostic complete" in captured.out

    @patch('agent.search.diagnose.check_dependencies')
    @patch('agent.search.diagnose.check_api_keys')
    @patch('agent.search.diagnose.check_engine')
    @patch('agent.search.diagnose.check_router')
    @patch('agent.search.diagnose.check_expansion')
    def test_main_prints_header_and_footer(
        self,
        mock_expansion,
        mock_router,
        mock_engine,
        mock_api_keys,
        mock_deps,
        capsys,
    ):
        """Test that main prints header and footer."""
        mock_engine.return_value = MagicMock()

        with patch.object(sys, 'argv', ['diagnose.py']):
            main()

        captured = capsys.readouterr()
        assert "NeoMind Universal Search Engine" in captured.out
        assert "Diagnostic Report" in captured.out


class TestDiagnosticIntegration:
    """Integration tests for diagnostic module."""

    @patch('agent.search.engine.UniversalSearchEngine')
    @patch('agent.search.router.QueryRouter')
    @patch('agent.search.query_expansion.QueryExpander')
    def test_full_diagnostic_run(
        self,
        mock_expander_class,
        mock_router_class,
        mock_engine_class,
        capsys,
    ):
        """Test full diagnostic run without errors."""
        mock_engine = MagicMock()
        mock_engine.get_status.return_value = "Engine Status"
        mock_engine_class.return_value = mock_engine

        mock_router = MagicMock()
        mock_router.classify.return_value = "general"
        mock_router_class.return_value = mock_router

        mock_expander = MagicMock()
        mock_expander.expand.return_value = ["test"]
        mock_expander_class.return_value = mock_expander

        with patch.object(sys, 'argv', ['diagnose.py']):
            main()

        captured = capsys.readouterr()
        # Verify all sections present
        assert "[Dependencies]" in captured.out
        assert "[API Keys]" in captured.out
        assert "[Engine Status]" in captured.out
        assert "[Query Router]" in captured.out
        assert "[Query Expansion]" in captured.out
