"""Backward compatibility — real implementation moved to agent/coding/planner.py."""
import importlib
import sys

_real = importlib.import_module('agent.coding.planner')
sys.modules[__name__] = _real
