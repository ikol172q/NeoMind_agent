"""Backward compatibility — real implementation moved to agent/services/search_legacy.py."""
import importlib
import sys

_real = importlib.import_module('agent.services.search_legacy')
sys.modules[__name__] = _real
