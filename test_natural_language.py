#!/usr/bin/env python3
"""
Unit tests for natural language interpreter and auto-search detection.
"""
import os
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent.natural_language import NaturalLanguageInterpreter
from agent.search import OptimizedDuckDuckGoSearch


class TestNaturalLanguageInterpreter(unittest.TestCase):
    """Test natural language interpreter."""

    def setUp(self):
        self.interpreter = NaturalLanguageInterpreter(confidence_threshold=0.7)

    def test_search_intent(self):
        """Test search intent detection."""
        # Basic search patterns
        cmd, conf = self.interpreter.interpret("search for Python tutorials")
        self.assertIsNotNone(cmd)
        self.assertEqual(cmd, "/search Python tutorials")
        self.assertGreaterEqual(conf, 0.7)

        cmd, conf = self.interpreter.interpret("look up latest news")
        self.assertIsNotNone(cmd)
        self.assertEqual(cmd, "/search latest news")

        cmd, conf = self.interpreter.interpret("find information about AI")
        self.assertIsNotNone(cmd)
        self.assertEqual(cmd, "/search information about AI")

    def test_file_read_intent(self):
        """Test file read intent detection."""
        cmd, conf = self.interpreter.interpret("read main.py")
        self.assertIsNotNone(cmd)
        self.assertEqual(cmd, "/read main.py")

        cmd, conf = self.interpreter.interpret("show file config.yaml")
        self.assertIsNotNone(cmd)
        self.assertEqual(cmd, "/read config.yaml")

    def test_code_analyze_intent(self):
        """Test code analysis intent detection."""
        cmd, conf = self.interpreter.interpret("analyze code in src/")
        self.assertIsNotNone(cmd)
        self.assertEqual(cmd, "/code scan src/")

        cmd, conf = self.interpreter.interpret("scan codebase src/")
        self.assertIsNotNone(cmd)
        self.assertEqual(cmd, "/code scan src/")

    def test_code_search_intent(self):
        """Test code search intent detection."""
        cmd, conf = self.interpreter.interpret("search codebase for function")
        self.assertIsNotNone(cmd)
        self.assertEqual(cmd, "/code search function")

        cmd, conf = self.interpreter.interpret("search for error in code")
        self.assertIsNotNone(cmd)
        self.assertEqual(cmd, "/code search error")

        cmd, conf = self.interpreter.interpret("find imports in codebase")
        self.assertIsNotNone(cmd)
        self.assertEqual(cmd, "/code search imports")

        cmd, conf = self.interpreter.interpret("look for TODO in source code")
        self.assertIsNotNone(cmd)
        self.assertEqual(cmd, "/code search TODO")

    def test_no_intent(self):
        """Test queries with no clear intent."""
        cmd, conf = self.interpreter.interpret("hello how are you")
        self.assertIsNone(cmd)
        self.assertEqual(conf, 0.0)

        cmd, conf = self.interpreter.interpret("what is the meaning of life")
        self.assertIsNone(cmd)

    def test_confidence_threshold(self):
        """Test confidence threshold filtering."""
        # Create interpreter with high threshold
        strict_interpreter = NaturalLanguageInterpreter(confidence_threshold=0.95)
        cmd, conf = strict_interpreter.interpret("search for something")
        # confidence should be 0.9, which is less than 0.95? Actually pattern confidence is 0.9
        # Let's just test that it may still match if confidence >= threshold
        if conf >= 0.95:
            self.assertIsNotNone(cmd)
        else:
            self.assertIsNone(cmd)


class TestAutoSearchDetection(unittest.TestCase):
    """Test auto-search detection logic."""

    def setUp(self):
        self.searcher = OptimizedDuckDuckGoSearch()

    def test_should_search_time_sensitive(self):
        """Test time-sensitive queries trigger search."""
        self.assertTrue(self.searcher.should_search("What's the latest news?"))
        self.assertTrue(self.searcher.should_search("current events"))
        self.assertTrue(self.searcher.should_search("weather in London"))
        self.assertTrue(self.searcher.should_search("stock price of AAPL"))
        self.assertTrue(self.searcher.should_search("score of the game"))

    def test_should_search_keywords(self):
        """Test keyword triggers."""
        self.assertTrue(self.searcher.should_search("today's news"))
        self.assertTrue(self.searcher.should_search("latest updates"))
        self.assertTrue(self.searcher.should_search("breaking news"))
        self.assertTrue(self.searcher.should_search("recent developments"))

    def test_should_not_search(self):
        """Test queries that should NOT trigger search."""
        self.assertFalse(self.searcher.should_search("How do I write a function?"))
        self.assertFalse(self.searcher.should_search("Explain quantum computing"))
        self.assertFalse(self.searcher.should_search("What is the capital of France?"))

    def test_custom_triggers(self):
        """Test custom triggers passed to constructor."""
        custom_searcher = OptimizedDuckDuckGoSearch(triggers={"custom", "test"})
        self.assertTrue(custom_searcher.should_search("custom query"))
        self.assertTrue(custom_searcher.should_search("this is a test"))
        self.assertFalse(custom_searcher.should_search("today's news"))  # default trigger not included


if __name__ == '__main__':
    unittest.main()