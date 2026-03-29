"""Backward compatibility — real implementation moved to agent/services/command_executor.py."""
import importlib
import sys

_real = importlib.import_module('agent.services.command_executor')
sys.modules[__name__] = _real
