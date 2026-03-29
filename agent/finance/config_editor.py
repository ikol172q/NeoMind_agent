"""Backward compatibility — real implementation moved to agent/services/config_editor.py."""
import importlib
import sys

_real = importlib.import_module('agent.services.config_editor')
sys.modules[__name__] = _real
