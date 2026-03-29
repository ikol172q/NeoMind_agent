"""Backward compatibility — real implementation moved to agent/coding/persistent_bash.py."""
import importlib
import sys

_real = importlib.import_module('agent.coding.persistent_bash')
sys.modules[__name__] = _real
