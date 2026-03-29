"""Backward compatibility — real implementation moved to agent/coding/code_analyzer.py."""
import importlib
import sys

_real = importlib.import_module('agent.coding.code_analyzer')
sys.modules[__name__] = _real
