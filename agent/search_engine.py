"""Backward compatibility — real implementation moved to agent/services/search_engine.py."""
import importlib
import sys

_real = importlib.import_module('agent.services.search_engine')
sys.modules[__name__] = _real
