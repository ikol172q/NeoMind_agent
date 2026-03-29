"""Backward compatibility — real implementation moved to agent/services/provider_state.py."""
import importlib
import sys

_real = importlib.import_module('agent.services.provider_state')

# Standard alias for normal imports
sys.modules[__name__] = _real

# Also populate this module's globals for direct file loading
# (importlib.util.module_from_spec uses exec_module which keeps its own module ref)
globals().update({k: v for k, v in vars(_real).items() if not k.startswith('_real')})
