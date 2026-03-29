"""Backward compatibility — real implementation moved to agent/services/memory_bridge.py."""
import importlib
import sys

_real = importlib.import_module('agent.services.memory_bridge')
sys.modules[__name__] = _real
globals().update({k: v for k, v in vars(_real).items() if not k.startswith('_real')})
