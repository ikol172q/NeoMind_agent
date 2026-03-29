"""Backward compatibility — real implementation moved to agent/coding/tool_parser.py."""
import importlib
import sys

_real = importlib.import_module('agent.coding.tool_parser')
sys.modules[__name__] = _real
