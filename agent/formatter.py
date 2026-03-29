"""Backward compatibility — real implementation moved to agent/services/formatter.py.

This stub installs the real module into sys.modules under both paths,
so mock.patch('agent.formatter.X') patches the same object as
mock.patch('agent.services.formatter.X').
"""
import importlib
import sys

# Import the real module
_real = importlib.import_module('agent.services.formatter')

# Make this module an alias: agent.formatter IS agent.services.formatter
sys.modules[__name__] = _real
