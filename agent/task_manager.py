"""Backward compatibility — real implementation moved to agent/services/task_manager.py."""
import importlib
import sys

_real = importlib.import_module('agent.services.task_manager')
sys.modules[__name__] = _real
