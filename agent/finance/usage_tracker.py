"""Backward compatibility — real implementation moved to agent/services/usage_tracker.py."""
import importlib
import sys

_real = importlib.import_module('agent.services.usage_tracker')
sys.modules[__name__] = _real
