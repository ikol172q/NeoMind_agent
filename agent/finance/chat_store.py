"""Backward compatibility — real implementation moved to agent/services/chat_store.py."""
import importlib
import sys

_real = importlib.import_module('agent.services.chat_store')
sys.modules[__name__] = _real
