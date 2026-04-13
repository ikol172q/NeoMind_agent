import os
from contextvars import ContextVar, Token
from pathlib import Path
from typing import Any, Optional, List
import yaml


class AgentConfigManager:
    """Manages agent configuration with split config files.

    Config structure:
        agent/config/base.yaml    — shared settings (model, temperature, context, etc.)
        agent/config/chat.yaml    — chat mode settings
        agent/config/coding.yaml  — coding mode settings

    The active mode determines which mode config is loaded on top of base.
    """

    def __init__(self, mode: Optional[str] = None):
        self.base_dir = Path(__file__).parent
        self.config_dir = self.base_dir / "agent" / "config"

        # Load base config
        self._base = self._load_yaml(self.config_dir / "base.yaml") or {}
        self._agent_base = self._base.get("agent", {})

        # Load all mode configs
        self._chat_cfg = self._load_yaml(self.config_dir / "chat.yaml") or {}
        self._coding_cfg = self._load_yaml(self.config_dir / "coding.yaml") or {}
        self._fin_cfg = self._load_yaml(self.config_dir / "fin.yaml") or {}

        # Determine active mode
        self._mode = mode or os.getenv("IKOL_MODE", "chat")
        if self._mode not in ("chat", "coding", "fin"):
            self._mode = "chat"

        # Build merged config for active mode
        self._rebuild_active_config()

        # Apply environment overrides
        self._apply_env_overrides()

    def _load_yaml(self, path: Path) -> dict:
        """Load a YAML file, return empty dict on failure."""
        try:
            if path.exists():
                return yaml.safe_load(path.read_text()) or {}
        except Exception as e:
            print(f"Warning: Failed to load {path}: {e}")
        return {}

    def _rebuild_active_config(self):
        """Merge base + active mode config into a flat lookup."""
        if self._mode == "chat":
            mode_cfg = self._chat_cfg
        elif self._mode == "coding":
            mode_cfg = self._coding_cfg
        elif self._mode == "fin":
            mode_cfg = self._fin_cfg
        else:
            mode_cfg = self._chat_cfg
        # _active holds mode-specific settings
        self._active = mode_cfg
        # _agent holds base agent settings
        self._agent = dict(self._agent_base)

    def _apply_env_overrides(self):
        """Apply environment variable overrides."""
        env_mappings = {
            "DEEPSEEK_MODEL": ("agent", "model", str),
            "DEEPSEEK_TEMPERATURE": ("agent", "temperature", float),
            "DEEPSEEK_MAX_TOKENS": ("agent", "max_tokens", int),
            "DEEPSEEK_MAX_CONTEXT_TOKENS": ("agent.context", "max_context_tokens", int),
            "DEEPSEEK_DEBUG": ("agent", "debug", lambda v: v.lower() in ("true", "1", "yes")),
        }
        for env_var, (section, key, converter) in env_mappings.items():
            val = os.getenv(env_var)
            if val is not None:
                try:
                    converted = converter(val)
                    if section == "agent":
                        self._agent[key] = converted
                        # Also apply to active mode config to take priority
                        self._active[key] = converted
                    elif section == "agent.context":
                        ctx = self._agent.setdefault("context", {})
                        ctx[key] = converted
                except (ValueError, TypeError):
                    pass

    # ── Mode management ──────────────────────────────────────────────────

    @property
    def mode(self) -> str:
        return self._mode

    def switch_mode(self, mode: str) -> bool:
        """Switch active mode. Returns True on success."""
        if mode not in ("chat", "coding", "fin"):
            return False
        self._mode = mode
        self._rebuild_active_config()
        return True

    # Backward compat
    def update_mode(self, mode: str) -> bool:
        return self.switch_mode(mode)

    # ── Runtime Config Modification ──────────────────────────────────────

    def set_runtime(self, key: str, value: Any) -> bool:
        """Set a config value at runtime (in-memory only, not persisted to YAML).

        Supports dot notation: 'temperature', 'max_tokens', 'system_prompt', etc.
        The agent can call this to adjust its own behavior mid-session.

        Returns True on success.
        """
        if key.startswith("agent."):
            key = key[6:]

        # Set in the active merged config
        self._dot_set(self._active, key, value)

        # Also set in the agent base for global settings
        if key in ("model", "temperature", "max_tokens", "stream"):
            self._dot_set(self._agent, key, value)

        return True

    def get_runtime_overrides(self) -> dict:
        """Get all runtime-modified settings (for display / debugging)."""
        return dict(self._runtime_overrides) if hasattr(self, '_runtime_overrides') else {}

    def save_config(self, filepath: Optional[str] = None) -> str:
        """Save current active config to a YAML file.

        If no filepath given, saves to agent/config/{mode}.yaml.
        Returns the filepath written.
        """
        if filepath is None:
            filepath = str(self.config_dir / f"{self._mode}.yaml")

        with open(filepath, 'w', encoding='utf-8') as f:
            yaml.dump(self._active, f, default_flow_style=False, allow_unicode=True)

        return filepath

    @staticmethod
    def _dot_set(d: dict, key: str, value: Any):
        """Set a value in a nested dict using dot notation."""
        parts = key.split(".")
        current = d
        for part in parts[:-1]:
            if part not in current or not isinstance(current[part], dict):
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value

    # ── Generic getters ──────────────────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        """Get config value. Checks mode config first, then base agent config.

        Supports dot notation: 'context.max_context_tokens', 'safety.confirm_file_operations'
        Also supports legacy 'agent.' prefix (stripped automatically).
        """
        # Strip legacy prefix
        if key.startswith("agent."):
            key = key[6:]

        # Try mode-specific config first
        val = self._dot_get(self._active, key)
        if val is not None:
            return val

        # Then try base agent config
        val = self._dot_get(self._agent, key)
        if val is not None:
            return val

        return default

    def _dot_get(self, d: dict, key: str) -> Any:
        """Navigate a nested dict with dot notation."""
        parts = key.split(".")
        current = d
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        return current

    # ── Mode-specific config access ──────────────────────────────────────

    @property
    def mode_config(self) -> dict:
        """Get the full mode-specific config dict."""
        return dict(self._active)

    def get_mode_config(self, mode: str) -> dict:
        """Get config for a specific mode (without switching)."""
        if mode == "chat":
            return dict(self._chat_cfg)
        elif mode == "coding":
            return dict(self._coding_cfg)
        elif mode == "fin":
            return dict(self._fin_cfg)
        return {}

    @property
    def available_commands(self) -> List[str]:
        """Get list of commands available in the current mode."""
        return self._active.get("commands", [])

    # ── Base agent properties ────────────────────────────────────────────

    @property
    def model(self) -> str:
        # Mode-specific model takes priority over base config
        mode_model = self._active.get("model")
        if mode_model:
            return mode_model
        return self._agent.get("model", "deepseek-chat")

    @property
    def fallback_model(self) -> Optional[str]:
        """Fallback model for the current mode (e.g., simpler tasks)."""
        return self._active.get("fallback_model")

    @property
    def thinking_mode(self) -> bool:
        """Whether the current mode prefers thinking/reasoning mode."""
        return self._active.get("thinking_mode", False)

    @property
    def temperature(self) -> float:
        return self._agent.get("temperature", 0.7)

    @property
    def max_tokens(self) -> int:
        return self._agent.get("max_tokens", 8192)

    @property
    def debug(self) -> bool:
        return self._agent.get("debug", False)

    @property
    def thinking_enabled(self) -> bool:
        return self._agent.get("thinking_enabled", False)

    @property
    def stream(self) -> bool:
        return self._agent.get("stream", True)

    @property
    def timeout(self) -> int:
        return self._agent.get("timeout", 30)

    @property
    def max_retries(self) -> int:
        return self._agent.get("max_retries", 3)

    # ── Context properties ───────────────────────────────────────────────

    @property
    def max_context_tokens(self) -> int:
        return self.get("context.max_context_tokens", 131072)

    @property
    def context_warning_threshold(self) -> float:
        return self.get("context.warning_threshold", 0.61)

    @property
    def context_break_threshold(self) -> float:
        return self.get("context.break_threshold", 0.8)

    @property
    def compression_strategy(self) -> str:
        return self.get("context.compression_strategy", "truncate")

    @property
    def keep_system_messages(self) -> bool:
        return self.get("context.keep_system_messages", True)

    @property
    def keep_recent_messages(self) -> int:
        return self.get("context.keep_recent_messages", 5)

    # ── Mode-aware properties (read from active mode config) ─────────────

    @property
    def system_prompt(self) -> str:
        return self._active.get("system_prompt", "")

    @system_prompt.setter
    def system_prompt(self, value: str):
        self._active["system_prompt"] = value

    @property
    def search_enabled(self) -> bool:
        return self._active.get("search_enabled", True)

    @property
    def auto_search_enabled(self) -> bool:
        return self.get("auto_search.enabled", False)

    @property
    def auto_search_triggers(self) -> list:
        return self.get("auto_search.triggers", [])

    @property
    def natural_language_enabled(self) -> bool:
        return self.get("natural_language.enabled", False)

    @property
    def natural_language_confidence_threshold(self) -> float:
        return self.get("natural_language.confidence_threshold", 0.8)

    @property
    def safety_confirm_file_operations(self) -> bool:
        return self.get("safety.confirm_file_operations", True)

    @property
    def safety_confirm_code_changes(self) -> bool:
        return self.get("safety.confirm_code_changes", True)

    @property
    def show_status_bar(self) -> bool:
        return self._active.get("show_status_bar", True)

    @property
    def enable_auto_complete(self) -> bool:
        return self._active.get("enable_auto_complete", True)

    # ── Coding-mode specific properties ──────────────────────────────────

    @property
    def workspace_auto_scan(self) -> bool:
        return self.get("workspace.auto_scan", False)

    @property
    def workspace_auto_read_files(self) -> bool:
        return self.get("workspace.auto_read_files", False)

    @property
    def workspace_auto_analyze_references(self) -> bool:
        return self.get("workspace.auto_analyze_references", False)

    @property
    def workspace_exclude_patterns(self) -> list:
        return self.get("workspace.exclude_patterns", [])

    @property
    def permission_mode(self) -> str:
        # Environment variable override for non-interactive / CI contexts
        env_mode = os.environ.get("NEOMIND_AUTO_ACCEPT")
        if env_mode and env_mode.strip().lower() in ("1", "true", "yes"):
            return "auto_accept"
        return getattr(self, '_permission_mode_override', None) or self.get("permissions.mode", "normal")

    @permission_mode.setter
    def permission_mode(self, value: str):
        if value not in ("normal", "auto_accept", "plan"):
            raise ValueError(f"Invalid permission mode: {value}")
        self._permission_mode_override = value

    @property
    def enable_mcp_support(self) -> bool:
        return self._active.get("enable_mcp_support", False)

    @property
    def compact_enabled(self) -> bool:
        return self.get("compact.enabled", False)

    @property
    def compact_auto_trigger_threshold(self) -> float:
        return self.get("compact.auto_trigger_threshold", 0.95)

    # ── Backward-compatible properties (map old names → new lookups) ─────

    @property
    def auto_features_enabled(self) -> bool:
        return True  # always enabled, mode controls what's available

    @property
    def coding_mode_system_prompt(self) -> str:
        return self._coding_cfg.get("system_prompt", "")

    @property
    def coding_mode_auto_file_operations(self) -> bool:
        return not self._coding_cfg.get("safety", {}).get("confirm_file_operations", False)

    @property
    def coding_mode_workspace_scan(self) -> bool:
        return self._coding_cfg.get("workspace", {}).get("auto_scan", True)

    @property
    def coding_mode_natural_language_confidence_threshold(self) -> float:
        return self._coding_cfg.get("natural_language", {}).get("confidence_threshold", 0.7)

    @property
    def coding_mode_safety_confirm_file_operations(self) -> bool:
        return self._coding_cfg.get("safety", {}).get("confirm_file_operations", False)

    @property
    def coding_mode_auto_read_files(self) -> bool:
        return self._coding_cfg.get("workspace", {}).get("auto_read_files", True)

    @property
    def coding_mode_auto_analyze_references(self) -> bool:
        return self._coding_cfg.get("workspace", {}).get("auto_analyze_references", True)

    @property
    def coding_mode_show_status_bar(self) -> bool:
        return self._coding_cfg.get("show_status_bar", True)

    @property
    def coding_mode_enable_auto_complete(self) -> bool:
        return self._coding_cfg.get("enable_auto_complete", True)

    @property
    def coding_mode_enable_mcp_support(self) -> bool:
        return self._coding_cfg.get("enable_mcp_support", True)

    # ── Config persistence (simplified — no more Hydra) ──────────────────

    @property
    def config_path(self) -> Path:
        """Path to config directory."""
        return self.config_dir

    def update_value(self, key: str, value: Any) -> bool:
        """Update a value in the appropriate config file.
        Only updates in-memory for now (no file writes during runtime).
        """
        try:
            if key.startswith("agent."):
                subkey = key[6:]
                parts = subkey.split(".")
                d = self._agent
                for part in parts[:-1]:
                    d = d.setdefault(part, {})
                d[parts[-1]] = value
                # Also update _active so mode-specific doesn't override agent updates
                d_active = self._active
                for part in parts[:-1]:
                    d_active = d_active.setdefault(part, {})
                d_active[parts[-1]] = value
            else:
                parts = key.split(".")
                d = self._active
                for part in parts[:-1]:
                    d = d.setdefault(part, {})
                d[parts[-1]] = value
            return True
        except Exception:
            return False

    # save_config is defined above in "Runtime Config Modification" section


# ─────────────────────────────────────────────────────────────────────
# Per-task config isolation (Phase 4, Option E: ContextVar + proxy)
# ─────────────────────────────────────────────────────────────────────
#
# The module symbol `agent_config` used to be a single process-wide
# AgentConfigManager instance. Every caller that does
#     from agent_config import agent_config
# would read and write the same shared state. That was fine for the
# single-session CLI + Telegram bot, but it was incompatible with
# running a fleet of concurrent sub-agents where each member needs its
# own persona-specific config view.
#
# This section replaces the singleton with a ContextVar-backed proxy
# inspired by nirholas (`src/utils/agentContext.ts`) — JavaScript's
# AsyncLocalStorage pattern ported to Python. Key properties:
#
#   • asyncio.create_task() automatically copies the current context
#     into each new task, so every fleet worker starts with its own
#     independent snapshot.
#   • ContextVar.set() inside a task only mutates that task's copy —
#     sibling tasks running concurrently via asyncio.gather see their
#     own values with zero cross-contamination.
#   • Reads fall back to a process-wide default AgentConfigManager
#     when no worker has called set_current_config(), so legacy
#     callers (CLI, Telegram bot) behave exactly as before.
#   • The `_AgentConfigProxy` object forwards every attribute access
#     to whichever AgentConfigManager is currently bound in the
#     caller's task context. `@property` getters and setters on the
#     underlying class keep working because the proxy's __getattr__ /
#     __setattr__ go through the normal `getattr(obj, name)` path.
#
# Files that import `agent_config` (seven of them, verified 2026-04-12
# via grep) need zero changes. Phase 4 grep audit also confirms no
# isinstance(..., AgentConfigManager) checks exist, so the proxy's
# lack of class identity with AgentConfigManager is safe.
#
# Fleet workers call `set_current_config(AgentConfigManager(mode=persona))`
# at the top of their asyncio task body. From that point on, every
# read of `agent_config.<anything>` inside that task — including deep
# into agent/core.py, agent/modes/finance.py, etc. — returns the
# per-worker view.

_default_manager: "AgentConfigManager" = AgentConfigManager()

_current_config: ContextVar["AgentConfigManager"] = ContextVar(
    "neomind_current_agent_config",
    default=_default_manager,
)


def get_current_config() -> "AgentConfigManager":
    """Return the AgentConfigManager currently bound in this async task.

    Falls back to the process-wide default if no worker has set a
    per-task override. This is the single source of truth for "which
    config should this caller see".
    """
    return _current_config.get()


def set_current_config(cfg: "AgentConfigManager") -> Token:
    """Bind ``cfg`` as the current AgentConfigManager for this async task.

    Because asyncio.create_task() captures a context snapshot per task,
    this set() only affects the caller's task and any child tasks it
    spawns. Sibling tasks are unaffected. The returned Token can be
    passed to ``reset_current_config`` to undo the binding, but in most
    fleet scenarios it's simpler to let the task end — Python will
    discard the task's context copy automatically.

    Args:
        cfg: The AgentConfigManager instance to bind as "current".

    Returns:
        Token that can be used to reset the binding back to its
        previous value. Ignore it if the task will end naturally.
    """
    return _current_config.set(cfg)


def reset_current_config(token: Token) -> None:
    """Reset the current-task config binding to what it was before the
    matching ``set_current_config`` call."""
    _current_config.reset(token)


class _AgentConfigProxy:
    """Transparent forwarder to the current-context AgentConfigManager.

    Every attribute access goes through ``_current_config.get()``,
    which returns whichever instance is bound to the caller's asyncio
    task. Legacy callers that do ``from agent_config import agent_config``
    and then access ``agent_config.model`` / ``.system_prompt`` / etc.
    see the default instance when no worker has set an override, and
    see the worker's per-persona instance when running inside a fleet
    worker task.

    Deliberately NOT an ``AgentConfigManager`` subclass — the proxy is
    only an attribute forwarder. A grep of the NeoMind codebase
    (2026-04-12, Phase 4 pre-flight) confirmed nothing does
    ``isinstance(agent_config, AgentConfigManager)``, so the proxy's
    lack of class identity is invisible to every current caller.

    Not safe to pickle/deepcopy. If a future caller needs that,
    implement ``__reduce__`` to forward to the underlying instance.
    """

    __slots__ = ()  # no instance state — all state lives in the contextvar

    def __getattr__(self, name: str) -> Any:
        # __getattr__ is only called when normal lookup fails. Since
        # the proxy has no instance attributes, every attribute access
        # lands here and gets forwarded to the current config.
        return getattr(_current_config.get(), name)

    def __setattr__(self, name: str, value: Any) -> None:
        # Forward writes so that `agent_config.system_prompt = "..."`
        # invokes the property setter on the current task's instance,
        # not on the proxy.
        setattr(_current_config.get(), name, value)

    def __dir__(self):
        # Expose the underlying manager's attributes for debug tools
        # (autocomplete, dir(), etc.). Union with the proxy's own
        # methods so __class__ etc. are still visible.
        manager = _current_config.get()
        return sorted(set(dir(manager)) | set(type(self).__dict__))

    def __repr__(self) -> str:
        try:
            return f"<AgentConfigProxy → {_current_config.get()!r}>"
        except LookupError:
            return "<AgentConfigProxy → (no context)>"


# Global symbol — every existing caller keeps importing `agent_config`
# and gets the proxy. The proxy transparently dispatches to whichever
# AgentConfigManager is current in the caller's asyncio task context.
agent_config = _AgentConfigProxy()
