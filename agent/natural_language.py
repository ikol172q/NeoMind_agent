"""Backward compatibility — real implementation moved to agent/services/nl_interpreter.py."""
import importlib
import sys

_real = importlib.import_module('agent.services.nl_interpreter')
sys.modules[__name__] = _real
