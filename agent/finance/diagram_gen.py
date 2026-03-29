"""Backward compatibility — real implementation moved to agent/services/diagram_gen.py."""
import importlib
import sys

_real = importlib.import_module('agent.services.diagram_gen')
sys.modules[__name__] = _real
