"""Backward compatibility — real implementation moved to agent/coding/tools.py."""
import importlib
import sys

_real = importlib.import_module('agent.coding.tools')
sys.modules[__name__] = _real
