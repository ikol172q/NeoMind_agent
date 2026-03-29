"""Backward compatibility — real implementation moved to agent/services/secure_memory.py."""
import importlib
import sys

_real = importlib.import_module('agent.services.secure_memory')
sys.modules[__name__] = _real
globals().update({k: v for k, v in vars(_real).items() if not k.startswith('_real')})
