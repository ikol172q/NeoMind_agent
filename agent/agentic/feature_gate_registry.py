"""
Feature Gate Registry — Unified runtime feature gating for NeoMind.

Replaces the two separate implementations (FeatureFlagService + FeatureFlags)
with a single registry supporting:
- Gate tier classification (STABLE / BETA / EXPERIMENTAL / INTERNAL)
- Four-layer resolution chain (env → runtime → config file → default)
- Experiment tracking (variant assignment, A/B testing)
- YAML config integration
- Change listeners

Inspired by Claude Code's GrowthBook + feature() pattern.

Usage:
    from agent.agentic.feature_gate_registry import gates

    if gates.is_enabled('COORDINATOR_MODE'):
        ...

    gate = gates.get('COORDINATOR_MODE')
    print(gate.tier)  # GateTier.BETA
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


class GateTier(Enum):
    """Classification tier for feature gates."""
    STABLE = "stable"           # GA — on by default, safe to depend on
    BETA = "beta"               # Opt-in preview, may have rough edges
    EXPERIMENTAL = "experimental"  # A/B testing, high risk, short-lived
    INTERNAL = "internal"       # Dev/debug only, never in production


@dataclass
class FeatureGate:
    """Definition of a single feature gate.

    Attributes:
        name: Unique gate identifier (e.g. 'COORDINATOR_MODE')
        description: Human-readable description
        tier: Stability classification
        default: Default value when no override exists
        env_var: Environment variable name for override (auto-derived if None)
        experiment_id: If set, this gate is part of an experiment
        experiment_variant: Variant name for experiment tracking
        owner: Team or person responsible for this gate
        deprecation_date: When this gate should be removed (YYYY-MM-DD)
    """
    name: str
    description: str = ""
    tier: GateTier = GateTier.STABLE
    default: Any = False
    env_var: Optional[str] = None
    experiment_id: Optional[str] = None
    experiment_variant: Optional[str] = None
    owner: str = ""
    deprecation_date: Optional[str] = None

    def __post_init__(self):
        if self.env_var is None:
            self.env_var = f"NEOMIND_GATE_{self.name.upper()}"


# ── Default gate definitions ──────────────────────────────────────────

DEFAULT_GATES: Dict[str, FeatureGate] = {
    # ── STABLE (GA) gates ──────────────────────────────────────────
    'AUTO_DREAM': FeatureGate(
        name='AUTO_DREAM',
        description='Background memory consolidation',
        tier=GateTier.STABLE, default=True, owner='core',
    ),
    'SANDBOX': FeatureGate(
        name='SANDBOX',
        description='Sandboxed command execution',
        tier=GateTier.STABLE, default=True, owner='security',
    ),
    'PATH_TRAVERSAL_PREVENTION': FeatureGate(
        name='PATH_TRAVERSAL_PREVENTION',
        description='Advanced path traversal prevention checks',
        tier=GateTier.STABLE, default=True, owner='security',
    ),
    'BINARY_DETECTION': FeatureGate(
        name='BINARY_DETECTION',
        description='Content-based binary file detection',
        tier=GateTier.STABLE, default=True, owner='security',
    ),
    'PROTECTED_FILES': FeatureGate(
        name='PROTECTED_FILES',
        description='Protected config/credential file blocking',
        tier=GateTier.STABLE, default=True, owner='security',
    ),
    'RISK_CLASSIFICATION': FeatureGate(
        name='RISK_CLASSIFICATION',
        description='Three-tier risk classification for permissions',
        tier=GateTier.STABLE, default=True, owner='security',
    ),

    # ── BETA gates ─────────────────────────────────────────────────
    'COORDINATOR_MODE': FeatureGate(
        name='COORDINATOR_MODE',
        description='Multi-agent orchestration via Coordinator',
        tier=GateTier.BETA, default=True, owner='agent',
    ),
    'EVOLUTION': FeatureGate(
        name='EVOLUTION',
        description='Self-evolution system (canary deploy, auto-upgrade)',
        tier=GateTier.BETA, default=True, owner='evolution',
    ),
    'SCRATCHPAD': FeatureGate(
        name='SCRATCHPAD',
        description='Coordinator scratchpad for cross-worker sharing',
        tier=GateTier.BETA, default=True, owner='agent',
    ),
    'SESSION_CHECKPOINT': FeatureGate(
        name='SESSION_CHECKPOINT',
        description='Session checkpoint and rewind',
        tier=GateTier.BETA, default=True, owner='session',
    ),
    'DEFERRED_TOOL_LOADING': FeatureGate(
        name='DEFERRED_TOOL_LOADING',
        description='Deferred tool loading when pool exceeds threshold',
        tier=GateTier.BETA, default=True, owner='tools',
    ),
    'DENIAL_TRACKING': FeatureGate(
        name='DENIAL_TRACKING',
        description='Circuit breaker for repeatedly denied tools',
        tier=GateTier.BETA, default=True, owner='tools',
    ),

    # ── EXPERIMENTAL gates ─────────────────────────────────────────
    'COMPACT_CACHE_PREFIX': FeatureGate(
        name='COMPACT_CACHE_PREFIX',
        description='Use cache prefix optimization for compaction',
        tier=GateTier.EXPERIMENTAL, default=False, owner='compact',
    ),
    'SESSION_MEMORY_COMPACT': FeatureGate(
        name='SESSION_MEMORY_COMPACT',
        description='Use session memory instead of LLM for compaction',
        tier=GateTier.EXPERIMENTAL, default=False, owner='compact',
    ),
    'BUILTIN_AGENTS': FeatureGate(
        name='BUILTIN_AGENTS',
        description='Built-in agent types (Explore, Plan, Verify)',
        tier=GateTier.EXPERIMENTAL, default=True, owner='agent',
    ),

    # ── INTERNAL gates ─────────────────────────────────────────────
    'VERBOSE_TOOL_TRACING': FeatureGate(
        name='VERBOSE_TOOL_TRACING',
        description='Log every tool call with full parameters',
        tier=GateTier.INTERNAL, default=False, owner='dev',
    ),
    'BYPASS_DENY_RULES': FeatureGate(
        name='BYPASS_DENY_RULES',
        description='Bypass all tool deny rules (debug only)',
        tier=GateTier.INTERNAL, default=False, owner='dev',
    ),

    # ── Finance gates ──────────────────────────────────────────────
    'PAPER_TRADING': FeatureGate(
        name='PAPER_TRADING',
        description='Simulated paper trading',
        tier=GateTier.STABLE, default=True, owner='finance',
    ),
    'BACKTEST': FeatureGate(
        name='BACKTEST',
        description='Strategy backtesting',
        tier=GateTier.STABLE, default=True, owner='finance',
    ),

    # ── Optional (disabled by default) ─────────────────────────────
    'VOICE_INPUT': FeatureGate(
        name='VOICE_INPUT',
        description='Voice input via microphone',
        tier=GateTier.EXPERIMENTAL, default=False, owner='ui',
    ),
    'COMPUTER_USE': FeatureGate(
        name='COMPUTER_USE',
        description='Screenshot capture and keyboard/mouse control',
        tier=GateTier.EXPERIMENTAL, default=False, owner='ui',
    ),
}


class FeatureGateRegistry:
    """Unified feature gate registry.

    Resolution chain (first wins):
    1. Environment variable: NEOMIND_GATE_{NAME}=1|0|true|false
    2. Runtime override (set during session via set_gate)
    3. Config file (~/.neomind/gates.json)
    4. Default value from DEFAULT_GATES

    Supports change listeners and experiment tracking.
    """

    def __init__(self, config_path: Optional[str] = None):
        self._config_path = Path(
            config_path or os.path.expanduser('~/.neomind/gates.json')
        )
        self._gates: Dict[str, FeatureGate] = dict(DEFAULT_GATES)
        self._runtime_overrides: Dict[str, Any] = {}
        self._file_values: Dict[str, Any] = {}
        self._listeners: Dict[str, List[Callable[[str, Any, Any], None]]] = {}
        self._load_config()

    # ── Persistence ──────────────────────────────────────────────────

    def _load_config(self):
        try:
            if self._config_path.exists():
                with open(self._config_path) as f:
                    data = json.load(f)
                    self._file_values = data.get('values', {})
                    # Restore registered experiments
                    for exp_data in data.get('experiments', []):
                        gate_name = exp_data.get('gate')
                        if gate_name and gate_name in self._gates:
                            self._gates[gate_name].experiment_id = exp_data.get('id')
                            self._gates[gate_name].experiment_variant = exp_data.get('variant')
        except Exception:
            pass

    def _save_config(self):
        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._config_path, 'w') as f:
                json.dump({
                    'values': self._file_values,
                    'experiments': [
                        {
                            'gate': g.name,
                            'id': g.experiment_id,
                            'variant': g.experiment_variant,
                        }
                        for g in self._gates.values()
                        if g.experiment_id
                    ],
                }, f, indent=2)
        except Exception:
            pass

    # ── Registration ─────────────────────────────────────────────────

    def register(self, gate: FeatureGate) -> None:
        """Register a new feature gate definition."""
        if gate.name in self._gates:
            existing = self._gates[gate.name]
            # Preserve existing experiment state
            gate.experiment_id = gate.experiment_id or existing.experiment_id
            gate.experiment_variant = gate.experiment_variant or existing.experiment_variant
        self._gates[gate.name] = gate

    def register_experiment(
        self, gate_name: str, experiment_id: str,
        variants: List[str], traffic_split: Optional[List[float]] = None,
    ) -> str:
        """Register an A/B experiment for a gate and assign a variant.

        Returns the assigned variant name.
        """
        if gate_name not in self._gates:
            raise KeyError(f"Unknown gate: {gate_name}")

        gate = self._gates[gate_name]
        gate.tier = GateTier.EXPERIMENTAL
        gate.experiment_id = experiment_id

        # Deterministic variant assignment based on a random seed
        # stored in the config file — stable within a session
        if gate.experiment_variant is None:
            seed = uuid.uuid4().int
            idx = seed % len(variants)
            gate.experiment_variant = variants[idx]

        self._save_config()
        return gate.experiment_variant

    # ── Resolution ───────────────────────────────────────────────────

    def get(self, gate_name: str, default: Any = None) -> FeatureGate:
        """Get a gate definition by name."""
        return self._gates.get(gate_name, FeatureGate(
            name=gate_name, default=default, tier=GateTier.STABLE,
        ))

    def get_value(self, gate_name: str, default: Any = None) -> Any:
        """Resolve a gate's current value through the full chain."""
        gate = self._gates.get(gate_name)

        # 1. Environment variable
        env_var = gate.env_var if gate else f"NEOMIND_GATE_{gate_name.upper()}"
        env_val = os.environ.get(env_var)
        if env_val is not None:
            return _parse_env_value(env_val)

        # 2. Runtime override
        if gate_name in self._runtime_overrides:
            return self._runtime_overrides[gate_name]

        # 3. Config file
        if gate_name in self._file_values:
            return self._file_values[gate_name]

        # 4. YAML config (agent_config)
        try:
            from agent_config import agent_config
            yaml_val = agent_config.get(f"features.{gate_name}")
            if yaml_val is not None:
                return yaml_val
        except ImportError:
            pass

        # 5. Default
        if gate is not None:
            return gate.default

        return default

    def is_enabled(self, gate_name: str, default: bool = False) -> bool:
        """Check if a gate is enabled (truthiness check)."""
        value = self.get_value(gate_name, default=default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ('1', 'true', 'yes', 'on')
        if isinstance(value, (int, float)):
            return bool(value)
        return bool(value)

    # ── Mutation ─────────────────────────────────────────────────────

    def set_value(self, gate_name: str, value: Any, persist: bool = False):
        """Override a gate's value.

        Args:
            gate_name: Gate name
            value: New value
            persist: If True, save to config file (survives restart)
        """
        old = self.get_value(gate_name)
        if persist:
            self._file_values[gate_name] = value
            self._save_config()
        else:
            self._runtime_overrides[gate_name] = value

        new = self.get_value(gate_name)
        if old != new and gate_name in self._listeners:
            for cb in self._listeners[gate_name]:
                try:
                    cb(gate_name, new, old)
                except Exception:
                    pass

    def clear_override(self, gate_name: str):
        """Clear a runtime override, restoring file/default value."""
        old = self.get_value(gate_name)
        self._runtime_overrides.pop(gate_name, None)
        new = self.get_value(gate_name)
        if old != new and gate_name in self._listeners:
            for cb in self._listeners[gate_name]:
                try:
                    cb(gate_name, new, old)
                except Exception:
                    pass

    def reset_all(self):
        """Clear all runtime overrides."""
        changed = list(self._runtime_overrides.keys())
        self._runtime_overrides.clear()
        for gate_name in changed:
            if gate_name in self._listeners:
                new = self.get_value(gate_name)
                for cb in self._listeners[gate_name]:
                    try:
                        cb(gate_name, new, None)
                    except Exception:
                        pass

    # ── Listeners ────────────────────────────────────────────────────

    def on_change(self, gate_name: str, callback: Callable[[str, Any, Any], None]):
        """Register a listener for gate value changes.

        Callback signature: (gate_name: str, new_value: Any, old_value: Any) -> None
        """
        self._listeners.setdefault(gate_name, []).append(callback)

    # ── Query ────────────────────────────────────────────────────────

    def list_by_tier(self, tier: Optional[GateTier] = None) -> Dict[str, FeatureGate]:
        """List all gates, optionally filtered by tier."""
        result = {}
        for name, gate in sorted(self._gates.items()):
            if tier is None or gate.tier == tier:
                result[name] = gate
        return result

    def list_by_tier_str(self, tier_str: str) -> Dict[str, FeatureGate]:
        """List gates filtered by tier string ('stable', 'beta', etc.)."""
        try:
            t = GateTier(tier_str)
            return self.list_by_tier(t)
        except ValueError:
            return {}

    def list_all(self) -> Dict[str, Dict[str, Any]]:
        """List all gates with current values and resolution source."""
        result = {}
        for name, gate in sorted(self._gates.items()):
            env_var = gate.env_var or f"NEOMIND_GATE_{name.upper()}"
            if os.environ.get(env_var) is not None:
                source = 'environment'
            elif name in self._runtime_overrides:
                source = 'runtime'
            elif name in self._file_values:
                source = 'config_file'
            else:
                source = 'default'

            result[name] = {
                'enabled': self.is_enabled(name),
                'value': self.get_value(name),
                'default': gate.default,
                'tier': gate.tier.value,
                'source': source,
                'description': gate.description,
                'owner': gate.owner,
                'experiment_id': gate.experiment_id,
                'experiment_variant': gate.experiment_variant,
            }
        return result

    def get_experiment_gates(self) -> Dict[str, FeatureGate]:
        """Get all gates that are part of active experiments."""
        return {
            name: gate for name, gate in self._gates.items()
            if gate.experiment_id is not None
        }


def _parse_env_value(raw: str) -> Any:
    """Parse an environment variable value."""
    v = raw.lower().strip()
    if v in ('true', '1', 'yes', 'on'):
        return True
    if v in ('false', '0', 'no', 'off'):
        return False
    # Try numeric
    try:
        if '.' in v:
            return float(v)
        return int(v)
    except ValueError:
        pass
    return raw


# ── Global singleton ─────────────────────────────────────────────────

_instance: Optional[FeatureGateRegistry] = None


def get_gate_registry() -> FeatureGateRegistry:
    global _instance
    if _instance is None:
        _instance = FeatureGateRegistry()
    return _instance


gates = get_gate_registry()


# ── Backward compat: migrate from old FeatureFlagService ─────────────

def migrate_from_legacy():
    """One-time migration from ~/.neomind/feature_flags.json to ~/.neomind/gates.json."""
    old_path = Path(os.path.expanduser('~/.neomind/feature_flags.json'))
    new_path = Path(os.path.expanduser('~/.neomind/gates.json'))
    if old_path.exists() and not new_path.exists():
        try:
            with open(old_path) as f:
                old_data = json.load(f)
            new_path.parent.mkdir(parents=True, exist_ok=True)
            with open(new_path, 'w') as f:
                json.dump({'values': old_data, 'experiments': []}, f, indent=2)
        except Exception:
            pass
