"""Backward compatibility — real implementation moved to agent/services/help_system.py."""
import importlib
import sys

_real = importlib.import_module('agent.services.help_system')
sys.modules[__name__] = _real
