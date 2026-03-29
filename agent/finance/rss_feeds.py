"""Backward compatibility — real implementation moved to agent/services/rss_feeds.py."""
import importlib
import sys

_real = importlib.import_module('agent.services.rss_feeds')
sys.modules[__name__] = _real
