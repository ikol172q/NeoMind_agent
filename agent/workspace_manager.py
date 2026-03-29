"""Backward compatibility — real implementation moved to agent/coding/workspace_manager.py."""
import importlib
import sys

_real = importlib.import_module('agent.coding.workspace_manager')
sys.modules[__name__] = _real
