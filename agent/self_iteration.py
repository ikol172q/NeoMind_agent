"""Backward compatibility — real implementation moved to agent/coding/self_iteration.py."""
import importlib
import sys

_real = importlib.import_module('agent.coding.self_iteration')
sys.modules[__name__] = _real
