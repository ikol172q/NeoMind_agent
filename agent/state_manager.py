"""NeoMind State Manager — Centralized Session State

Extracted from core.py's scattered state attributes.
Mirrors Claude Code's state/AppState.tsx pattern:
centralized, observable state with clear lifecycle.

Responsibilities:
    - Session identity (id, start time, mode)
    - Model state (current model, thinking, temperature)
    - UI state (status bar, verbose, current_status)
    - Feature flags (runtime-togglable features)
    - Session persistence (save/resume)
"""

import os
import json
import time
import uuid
import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Set, Callable
from pathlib import Path

from agent.constants.models import DEFAULT_MODEL

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Feature Flags — mirrors Claude Code's feature gating system
# ─────────────────────────────────────────────────────────────────────

class FeatureFlags:
    """Runtime feature flag manager.

    Mirrors Claude Code's GrowthBook + Bun feature() pattern.
    Supports:
    - Static flags from config (compile-time equivalent)
    - Runtime toggles
    - Caching with TTL

    Usage:
        flags = FeatureFlags()
        flags.set("COORDINATOR_MODE", True)
        if flags.is_enabled("COORDINATOR_MODE"):
            ...
    """

    def __init__(self, config_path: Optional[str] = None):
        self._flags: Dict[str, bool] = {}
        self._overrides: Dict[str, bool] = {}  # Runtime overrides
        self._listeners: Dict[str, List[Callable]] = {}
        self._config_path = config_path or os.path.expanduser("~/.neomind/flags.json")
        self._load_from_file()

    def _load_from_file(self):
        """Load flags from persistent config."""
        try:
            if os.path.exists(self._config_path):
                with open(self._config_path, "r") as f:
                    self._flags = json.load(f)
        except Exception as e:
            logger.debug(f"Could not load feature flags: {e}")

    def _save_to_file(self):
        """Persist flags to disk."""
        try:
            os.makedirs(os.path.dirname(self._config_path), exist_ok=True)
            with open(self._config_path, "w") as f:
                json.dump({**self._flags, **self._overrides}, f, indent=2)
        except Exception as e:
            logger.debug(f"Could not save feature flags: {e}")

    def is_enabled(self, flag: str, default: bool = False) -> bool:
        """Check if a feature flag is enabled."""
        if flag in self._overrides:
            return self._overrides[flag]
        return self._flags.get(flag, default)

    def set(self, flag: str, value: bool, persist: bool = False):
        """Set a feature flag."""
        old = self.is_enabled(flag)
        self._overrides[flag] = value
        if persist:
            self._flags[flag] = value
            self._save_to_file()
        if old != value and flag in self._listeners:
            for cb in self._listeners[flag]:
                try:
                    cb(flag, value)
                except Exception:
                    pass

    def on_change(self, flag: str, callback: Callable):
        """Register a listener for flag changes."""
        self._listeners.setdefault(flag, []).append(callback)

    def get_all(self) -> Dict[str, bool]:
        """Get all flags with overrides applied."""
        merged = {**self._flags}
        merged.update(self._overrides)
        return merged


# ─────────────────────────────────────────────────────────────────────
# Session State — the single source of truth
# ─────────────────────────────────────────────────────────────────────

@dataclass
class SessionState:
    """Complete session state.

    Single source of truth for all mutable state.
    Replaces scattered self.* attributes in core.py.
    """

    # Identity
    session_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    start_time: float = field(default_factory=time.time)
    mode: str = "chat"

    # Model
    model: str = field(default_factory=lambda: DEFAULT_MODEL)
    fallback_model: Optional[str] = None
    thinking_enabled: bool = True
    temperature: float = 0.7

    # UI
    show_status_bar: bool = True
    verbose_mode: bool = False
    current_status: str = ""

    # Session
    turn_count: int = 0
    total_cost_usd: float = 0.0
    is_active: bool = True

    # Features
    search_enabled: bool = True
    auto_search_enabled: bool = False
    natural_language_enabled: bool = True
    mcp_enabled: bool = True
    compact_enabled: bool = True

    def elapsed_seconds(self) -> float:
        return time.time() - self.start_time

    def elapsed_display(self) -> str:
        elapsed = self.elapsed_seconds()
        if elapsed < 60:
            return f"{elapsed:.0f}s"
        elif elapsed < 3600:
            return f"{elapsed / 60:.0f}m"
        else:
            return f"{elapsed / 3600:.1f}h"


class StateManager:
    """Manage session state with persistence and observation.

    Centralizes all state that was scattered across core.py,
    neomind_interface.py, and various services.

    Mirrors Claude Code's AppState.tsx React context pattern,
    adapted for Python (no React, but same observable state idea).
    """

    def __init__(self, config=None):
        from agent_config import agent_config
        self.config = config or agent_config

        # Primary state
        self.session = SessionState(
            mode=self.config.mode,
            model=self.config.model,
            fallback_model=self.config.fallback_model,
            thinking_enabled=self.config.thinking_enabled,
            temperature=self.config.get("temperature", 0.7),
            show_status_bar=self.config.show_status_bar,
            search_enabled=self.config.search_enabled,
            auto_search_enabled=self.config.auto_search_enabled,
            natural_language_enabled=self.config.natural_language_enabled,
            mcp_enabled=self.config.get("enable_mcp_support", True),
            compact_enabled=self.config.get("compact.enabled", True),
        )

        # Feature gates — unified registry (replaces FeatureFlags + FeatureFlagService)
        from agent.agentic.feature_gate_registry import get_gate_registry
        self.gates = get_gate_registry()
        # Backward compat: old code referencing self.features.is_enabled()
        self.features = self.gates

        # State change listeners
        self._listeners: List[Callable[[str, Any], None]] = []

        # Sessions directory for persistence
        self._sessions_dir = os.path.expanduser("~/.neomind/sessions")

    def update(self, key: str, value: Any):
        """Update a state field and notify listeners."""
        if hasattr(self.session, key):
            old = getattr(self.session, key)
            setattr(self.session, key, value)
            self._notify(key, value)
            logger.debug(f"State updated: {key} = {value} (was {old})")
        else:
            logger.warning(f"Unknown state key: {key}")

    def _notify(self, key: str, value: Any):
        """Notify all listeners of a state change."""
        for listener in self._listeners:
            try:
                listener(key, value)
            except Exception as e:
                logger.debug(f"State listener error: {e}")

    def on_change(self, callback: Callable[[str, Any], None]):
        """Register a state change listener."""
        self._listeners.append(callback)

    # ── Persistence (session save/resume) ──────────────────────────

    def save_session(self, messages: List[Dict[str, Any]]) -> str:
        """Save session state to disk for later resume.

        Mirrors Claude Code's /resume command.

        Returns:
            Path to saved session file
        """
        os.makedirs(self._sessions_dir, exist_ok=True)
        session_file = os.path.join(
            self._sessions_dir,
            f"{self.session.session_id}.json",
        )

        data = {
            "session_id": self.session.session_id,
            "mode": self.session.mode,
            "model": self.session.model,
            "start_time": self.session.start_time,
            "turn_count": self.session.turn_count,
            "total_cost_usd": self.session.total_cost_usd,
            "messages": messages,
            "saved_at": time.time(),
        }

        with open(session_file, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info(f"Session saved: {session_file}")
        return session_file

    def load_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Load a saved session.

        Returns:
            Session data dict or None if not found
        """
        session_file = os.path.join(self._sessions_dir, f"{session_id}.json")
        if not os.path.exists(session_file):
            return None
        try:
            with open(session_file, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load session: {e}")
            return None

    def list_sessions(self, limit: int = 10) -> List[Dict[str, Any]]:
        """List recent saved sessions."""
        if not os.path.exists(self._sessions_dir):
            return []
        sessions = []
        for fname in sorted(os.listdir(self._sessions_dir), reverse=True):
            if fname.endswith(".json"):
                try:
                    with open(os.path.join(self._sessions_dir, fname), "r") as f:
                        data = json.load(f)
                        sessions.append({
                            "id": data.get("session_id", fname[:-5]),
                            "mode": data.get("mode", "?"),
                            "turns": data.get("turn_count", 0),
                            "saved_at": data.get("saved_at", 0),
                        })
                except Exception:
                    continue
                if len(sessions) >= limit:
                    break
        return sessions

    def get_snapshot(self) -> Dict[str, Any]:
        """Get a complete state snapshot for debugging."""
        return {
            "session": {
                "id": self.session.session_id,
                "mode": self.session.mode,
                "model": self.session.model,
                "turns": self.session.turn_count,
                "elapsed": self.session.elapsed_display(),
                "cost": f"${self.session.total_cost_usd:.4f}",
            },
            "features": self.gates.list_all(),
        }
