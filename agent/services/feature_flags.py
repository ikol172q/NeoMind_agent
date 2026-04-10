"""
Feature Flag Service — Runtime feature gating for NeoMind.

Inspired by Claude Code's GrowthBook-style feature gating. Supports:
- Config-file-based flags (persistent)
- Runtime flags (session-scoped)
- Environment variable overrides
- Default values with fallback chain

Usage:
    from agent.services.feature_flags import feature_flags

    if feature_flags.is_enabled('AUTO_DREAM'):
        ...

    value = feature_flags.get_value('MAX_SEARCH_RESULTS', default=10)
"""

import os
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Default flag definitions with their default states
DEFAULT_FLAGS: Dict[str, Dict[str, Any]] = {
    # Core features
    'AUTO_DREAM': {
        'default': True,
        'description': 'Background memory consolidation',
    },
    'SANDBOX': {
        'default': True,
        'description': 'Sandboxed command execution',
    },
    'COORDINATOR_MODE': {
        'default': True,
        'description': 'Multi-agent orchestration',
    },
    'EVOLUTION': {
        'default': True,
        'description': 'Self-evolution system',
    },

    # Security features
    'PATH_TRAVERSAL_PREVENTION': {
        'default': True,
        'description': 'Advanced path traversal prevention checks',
    },
    'BINARY_DETECTION': {
        'default': True,
        'description': 'Content-based binary file detection',
    },
    'PROTECTED_FILES': {
        'default': True,
        'description': 'Protected config/credential file blocking',
    },

    # Experimental features
    'SCRATCHPAD': {
        'default': True,
        'description': 'Coordinator scratchpad for cross-worker sharing',
    },
    'RISK_CLASSIFICATION': {
        'default': True,
        'description': 'Three-tier risk classification for permissions',
    },
    'SESSION_CHECKPOINT': {
        'default': True,
        'description': 'Session checkpoint and rewind',
    },

    # Finance features
    'PAPER_TRADING': {
        'default': True,
        'description': 'Simulated paper trading',
    },
    'BACKTEST': {
        'default': True,
        'description': 'Strategy backtesting',
    },

    # Optional features (disabled by default)
    'VOICE_INPUT': {
        'default': False,
        'description': 'Voice input via microphone',
    },
    'COMPUTER_USE': {
        'default': False,
        'description': 'Screenshot capture and keyboard/mouse control',
    },
}


class FeatureFlagService:
    """Runtime feature flag management.

    Flag resolution order (first wins):
    1. Environment variable: NEOMIND_FLAG_{NAME}=1|0|true|false
    2. Runtime override (set during session)
    3. Config file (~/.neomind/feature_flags.json)
    4. Default value from DEFAULT_FLAGS
    """

    def __init__(self, config_path: str = None):
        self._config_path = Path(
            config_path or os.path.expanduser('~/.neomind/feature_flags.json')
        )
        self._runtime_overrides: Dict[str, Any] = {}
        self._file_flags: Dict[str, Any] = {}
        self._load_config()

    def _load_config(self):
        """Load flags from config file."""
        try:
            if self._config_path.exists():
                with open(self._config_path) as f:
                    self._file_flags = json.load(f)
        except Exception as e:
            logger.debug(f"FeatureFlags: failed to load config: {e}")

    def _save_config(self):
        """Save current file flags to disk."""
        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._config_path, 'w') as f:
                json.dump(self._file_flags, f, indent=2)
        except Exception as e:
            logger.debug(f"FeatureFlags: failed to save config: {e}")

    def is_enabled(self, flag_name: str) -> bool:
        """Check if a feature flag is enabled.

        Args:
            flag_name: Flag name (e.g. 'AUTO_DREAM')

        Returns:
            True if enabled
        """
        value = self.get_value(flag_name)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ('1', 'true', 'yes', 'on')
        if isinstance(value, (int, float)):
            return bool(value)
        return False

    def get_value(self, flag_name: str, default: Any = None) -> Any:
        """Get a feature flag value with full resolution chain.

        Args:
            flag_name: Flag name
            default: Fallback if flag is not defined anywhere

        Returns:
            Flag value
        """
        # 1. Environment variable
        env_key = f"NEOMIND_FLAG_{flag_name.upper()}"
        env_val = os.environ.get(env_key)
        if env_val is not None:
            if env_val.lower() in ('true', '1', 'yes', 'on'):
                return True
            if env_val.lower() in ('false', '0', 'no', 'off'):
                return False
            return env_val

        # 2. Runtime override
        if flag_name in self._runtime_overrides:
            return self._runtime_overrides[flag_name]

        # 3. Config file
        if flag_name in self._file_flags:
            return self._file_flags[flag_name]

        # 4. Default flags
        if flag_name in DEFAULT_FLAGS:
            return DEFAULT_FLAGS[flag_name]['default']

        return default

    def set_flag(self, flag_name: str, value: Any, persist: bool = False):
        """Set a feature flag value.

        Args:
            flag_name: Flag name
            value: Flag value
            persist: If True, save to config file; otherwise session-only
        """
        if persist:
            self._file_flags[flag_name] = value
            self._save_config()
        else:
            self._runtime_overrides[flag_name] = value

    def clear_override(self, flag_name: str):
        """Clear a runtime override."""
        self._runtime_overrides.pop(flag_name, None)

    def list_flags(self) -> Dict[str, Dict[str, Any]]:
        """List all known flags with their current values and sources."""
        result = {}
        all_names = set(DEFAULT_FLAGS.keys()) | set(self._file_flags.keys()) | set(self._runtime_overrides.keys())

        for name in sorted(all_names):
            desc = DEFAULT_FLAGS.get(name, {}).get('description', '')
            default = DEFAULT_FLAGS.get(name, {}).get('default', None)

            # Determine source
            env_key = f"NEOMIND_FLAG_{name.upper()}"
            if os.environ.get(env_key) is not None:
                source = 'environment'
            elif name in self._runtime_overrides:
                source = 'runtime'
            elif name in self._file_flags:
                source = 'config_file'
            else:
                source = 'default'

            result[name] = {
                'enabled': self.is_enabled(name),
                'value': self.get_value(name),
                'default': default,
                'source': source,
                'description': desc,
            }

        return result


# Global singleton
_instance: Optional[FeatureFlagService] = None


def get_feature_flags() -> FeatureFlagService:
    """Get the global FeatureFlagService singleton."""
    global _instance
    if _instance is None:
        _instance = FeatureFlagService()
    return _instance


# Convenience shortcut
feature_flags = get_feature_flags()
