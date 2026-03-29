"""Backward compatibility — real implementation moved to agent/services/context_service.py."""
import importlib
import sys

_real = importlib.import_module('agent.services.context_service')
sys.modules[__name__] = _real
