"""Backward compatibility — real implementation moved to agent/coding/tool_schema.py."""
import importlib
import sys

_real = importlib.import_module('agent.coding.tool_schema')
sys.modules[__name__] = _real
