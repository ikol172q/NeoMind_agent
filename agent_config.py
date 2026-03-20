import os
from pathlib import Path
from typing import Any, Optional, List
import yaml


class AgentConfigManager:
    """Manages agent configuration with split config files.

    Config structure:
        agent/config/base.yaml    — shared settings (model, temperature, context, etc.)
        agent/config/chat.yaml    — chat mode settings
        agent/config/coding.yaml  — coding mode settings (Claude CLI-like)

    The active mode determines which mode config is loaded on top of base.
    """

    def __init__(self, mode: Optional[str] = None):
        self.base_dir = Path(__file__).parent
        self.config_dir = self.base_dir / "agent" / "config"

        # Load base config
        self._base = self._load_yaml(self.config_dir / "base.yaml")
        self._agent_base = self._base.get("agent", {})

        # Load all mode configs
        self._chat_cfg = self._load_yaml(self.config_dir / "chat.yaml")
        self._coding_cfg = self._load_yaml(self.config_dir / "coding.yaml")
        self._fin_cfg = self._load_yaml(self.config_dir / "fin.yaml")

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
        return self._agent.get("model", "deepseek-chat")

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


# Global instance — single point of access
agent_config = AgentConfigManager()
