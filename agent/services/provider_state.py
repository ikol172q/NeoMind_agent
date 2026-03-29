# agent/finance/provider_state.py
"""
ProviderStateManager — Single Source of Truth for LLM provider configuration.

Enables bidirectional sync between:
- xbar (macOS menu bar) → writes provider-state.json
- Telegram bot (Docker)  → reads/writes provider-state.json
- Future bots            → each gets independent config under bots.<name>

Design principles:
- state file manages MODE (litellm vs direct), .env manages API KEYS
- Atomic writes (write .tmp → rename) prevent partial reads
- mtime cache avoids re-reading file on every request
- Schema versioning with migration framework
- API keys NEVER written to state file
"""

import os
import json
import time
import logging
from datetime import datetime, timezone, timedelta

# US Pacific Time (UTC-7 PDT / UTC-8 PST)
try:
    from zoneinfo import ZoneInfo
    _PACIFIC = ZoneInfo("America/Los_Angeles")
except ImportError:
    # Python < 3.9 fallback — use fixed UTC-7 (PDT)
    _PACIFIC = timezone(timedelta(hours=-7))
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger("neomind.provider_state")

# ── Schema ────────────────────────────────────────────────────────────

CURRENT_SCHEMA_VERSION = 1

DEFAULT_STATE = {
    "schema_version": CURRENT_SCHEMA_VERSION,
    "updated_at": "",
    "updated_by": "system",
    "bots": {},
    "litellm": {
        "base_url": "http://host.docker.internal:4000/v1",
        "health_ok": False,
        "last_health_check": "",
    },
}

DEFAULT_BOT_CONFIG = {
    "provider_mode": "direct",       # "litellm" or "direct"
    "litellm_model": "local",        # model name when using litellm
    "direct_model": "deepseek-chat", # model name when using direct
    "thinking_model": "deepseek-reasoner",
    "updated_at": "",
    "updated_by": "system",
    # Per-mode model routing (written by bot on startup, read by xbar)
    "mode_models": {},
    # Available cloud providers (written by bot on startup)
    "available_providers": [],
}


# ── Migration Framework ───────────────────────────────────────────────

def _migrate_v0_to_v1(state: dict) -> dict:
    """Migrate from env-only (no state file) to schema v1."""
    state.setdefault("schema_version", 1)
    state.setdefault("bots", {})
    state.setdefault("litellm", DEFAULT_STATE["litellm"].copy())
    state.setdefault("updated_at", _now_iso())
    state.setdefault("updated_by", "migration")
    return state


_MIGRATIONS = {
    (0, 1): _migrate_v0_to_v1,
}


# ── Helpers ───────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(_PACIFIC).strftime("%Y-%m-%d %H:%M:%S PT")


# ── Main Class ────────────────────────────────────────────────────────

class ProviderStateManager:
    """
    Shared provider state — single source of truth for all bots.

    State file manages "which provider to use" (mode).
    .env manages "API keys and secrets" (never in state file).

    Usage:
        mgr = ProviderStateManager("/data/neomind/.neomind")
        mgr.register_bot("neomind")
        chain = mgr.get_provider_chain("neomind", thinking=False)
        mgr.set_provider_mode("neomind", "litellm", updated_by="telegram")
    """

    def __init__(self, state_dir: Optional[str] = None):
        if state_dir:
            self._state_dir = Path(state_dir)
        else:
            # Default: $HOME/.neomind (works both on macOS and in Docker)
            home = os.getenv("HOME", "/data")
            self._state_dir = Path(home) / ".neomind"

        self._state_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self._state_dir / "provider-state.json"

        # mtime cache
        self._cached_state: Optional[dict] = None
        self._cached_mtime: float = 0.0

        # Track last known mode per bot for change detection
        self._last_known_mode: Dict[str, str] = {}

    # ── Read ──────────────────────────────────────────────────────

    def _read_state(self) -> dict:
        """Read state file with mtime cache. Re-reads only if file changed."""
        if not self.state_file.exists():
            return self._default_state()

        try:
            mtime = self.state_file.stat().st_mtime
        except OSError:
            return self._cached_state or self._default_state()

        if self._cached_state is not None and mtime == self._cached_mtime:
            return self._cached_state

        # File changed (or first read) — reload
        try:
            raw = self.state_file.read_text(encoding="utf-8")
            state = json.loads(raw)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"State file corrupted or unreadable: {e}")
            # Backup corrupted file
            bak = self.state_file.with_suffix(".json.bak")
            try:
                if self.state_file.exists():
                    self.state_file.rename(bak)
                    logger.warning(f"Corrupted file backed up to {bak}")
            except OSError:
                pass
            state = self._default_state()
            self._atomic_write(state)

        # Run schema migrations if needed
        state = self._ensure_schema(state)

        self._cached_state = state
        self._cached_mtime = mtime
        return state

    def _default_state(self) -> dict:
        """Create a default state, optionally migrating from env vars."""
        state = json.loads(json.dumps(DEFAULT_STATE))  # deep copy
        state["updated_at"] = _now_iso()

        # Migrate from env if LITELLM_ENABLED is set (backward compat)
        litellm_enabled = os.getenv("LITELLM_ENABLED", "").lower() in ("true", "1", "yes")
        if litellm_enabled:
            # Will be applied when register_bot is called
            pass

        litellm_url = os.getenv("LITELLM_BASE_URL", "http://host.docker.internal:4000/v1")
        state["litellm"]["base_url"] = litellm_url

        return state

    # ── Write ─────────────────────────────────────────────────────

    def _atomic_write(self, data: dict):
        """Write state file atomically: write .tmp then rename."""
        # SAFETY: API keys must NEVER be in state file
        serialized = json.dumps(data, indent=2, ensure_ascii=False)
        assert "api_key" not in serialized.lower(), \
            "BUG: API key must never be written to state file"

        self._state_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_suffix(".json.tmp")
        tmp.write_text(serialized, encoding="utf-8")
        tmp.rename(self.state_file)  # atomic on same filesystem

        # Update cache
        self._cached_state = data
        try:
            self._cached_mtime = self.state_file.stat().st_mtime
        except OSError:
            self._cached_mtime = 0.0

    # ── Schema Migration ──────────────────────────────────────────

    def _ensure_schema(self, state: dict) -> dict:
        """Run migrations to bring state to current schema version."""
        current = state.get("schema_version", 0)
        if not isinstance(current, int):
            current = 0

        changed = False
        while current < CURRENT_SCHEMA_VERSION:
            migrator = _MIGRATIONS.get((current, current + 1))
            if migrator:
                state = migrator(state)
                logger.info(f"Migrated state schema v{current} → v{current+1}")
                changed = True
            current += 1

        state["schema_version"] = CURRENT_SCHEMA_VERSION

        if changed:
            self._atomic_write(state)

        return state

    # ── Bot Registration ──────────────────────────────────────────

    def register_bot(self, bot_name: str, defaults: Optional[dict] = None):
        """Register a bot. If already exists, preserve config (idempotent).

        Called once at bot startup. First-time registration also checks
        env vars for backward compatibility (LITELLM_ENABLED).
        """
        state = self._read_state()
        bots = state.setdefault("bots", {})

        if bot_name in bots:
            # Already registered — update last_known_mode and return
            self._last_known_mode[bot_name] = bots[bot_name].get("provider_mode", "direct")
            logger.info(f"Bot '{bot_name}' already registered, mode={self._last_known_mode[bot_name]}")
            return

        # New registration
        config = json.loads(json.dumps(DEFAULT_BOT_CONFIG))  # deep copy
        if defaults:
            config.update(defaults)

        # Migrate from env: if LITELLM_ENABLED=true, set mode to litellm
        litellm_enabled = os.getenv("LITELLM_ENABLED", "").lower() in ("true", "1", "yes")
        if litellm_enabled:
            config["provider_mode"] = "litellm"

        config["updated_at"] = _now_iso()
        config["updated_by"] = "registration"
        bots[bot_name] = config
        state["updated_at"] = _now_iso()
        state["updated_by"] = "registration"

        self._atomic_write(state)
        self._last_known_mode[bot_name] = config["provider_mode"]
        logger.info(f"Registered bot '{bot_name}', mode={config['provider_mode']}")

    # ── Provider Mode ─────────────────────────────────────────────

    def get_bot_config(self, bot_name: str) -> dict:
        """Get a bot's provider configuration."""
        state = self._read_state()
        return state.get("bots", {}).get(bot_name, DEFAULT_BOT_CONFIG.copy())

    def set_provider_mode(self, bot_name: str, mode: str,
                          updated_by: str = "unknown") -> dict:
        """Switch provider mode for a bot. Writes to state file.

        Args:
            bot_name: e.g. "neomind"
            mode: "litellm" or "direct"
            updated_by: "telegram", "xbar", "natural_language", etc.

        Returns:
            Updated bot config dict.
        """
        if mode not in ("litellm", "direct"):
            raise ValueError(f"Invalid mode: {mode}. Must be 'litellm' or 'direct'")

        state = self._read_state()
        bots = state.setdefault("bots", {})
        if bot_name not in bots:
            self.register_bot(bot_name)
            state = self._read_state()
            bots = state["bots"]

        now = _now_iso()
        bots[bot_name]["provider_mode"] = mode
        bots[bot_name]["updated_at"] = now
        bots[bot_name]["updated_by"] = updated_by
        state["updated_at"] = now
        state["updated_by"] = updated_by

        self._atomic_write(state)
        self._last_known_mode[bot_name] = mode
        logger.info(f"Set {bot_name} provider_mode={mode} by {updated_by}")

        return bots[bot_name]

    # ── Mode Models (for xbar display) ───────────────────────

    def update_mode_models(self, bot_name: str, mode_models: dict,
                           updated_by: str = "bot"):
        """Write per-mode model routing to state file (for xbar to read).

        Args:
            bot_name: e.g. "neomind"
            mode_models: e.g. {"fin": {"model": "kimi-k2.5", "provider": "moonshot"},
                               "chat": {"model": "deepseek-chat", "provider": "deepseek"}}
            updated_by: who triggered the update
        """
        state = self._read_state()
        bots = state.get("bots", {})
        if bot_name not in bots:
            self.register_bot(bot_name)
            state = self._read_state()
            bots = state["bots"]

        bots[bot_name]["mode_models"] = mode_models
        state["updated_at"] = _now_iso()
        self._atomic_write(state)
        logger.info(f"Updated mode_models for {bot_name}: {list(mode_models.keys())}")

    def update_available_providers(self, bot_name: str, providers: list):
        """Write list of available cloud providers to state file (for xbar).

        Args:
            bot_name: e.g. "neomind"
            providers: e.g. [{"name": "deepseek", "ok": True},
                             {"name": "moonshot", "ok": True}]
        """
        state = self._read_state()
        bots = state.get("bots", {})
        if bot_name in bots:
            bots[bot_name]["available_providers"] = providers
            self._atomic_write(state)

    # ── Provider Chain ────────────────────────────────────────────

    def get_provider_chain(self, bot_name: str, thinking: bool = False) -> list:
        """Build ordered list of providers to try (primary → fallback).

        Reads MODE from state file, reads API KEYS from os.environ.
        This is the core method that replaces _get_provider_chain() in telegram_bot.py.

        Returns:
            List of dicts, each with: name, api_key, base_url, model
        """
        config = self.get_bot_config(bot_name)
        mode = config.get("provider_mode", "direct")

        # Read API keys from environment (NEVER from state file)
        litellm_key = os.getenv("LITELLM_API_KEY", "")
        ds_key = os.getenv("DEEPSEEK_API_KEY", "")
        zai_key = os.getenv("ZAI_API_KEY", "")

        providers = []

        if mode == "litellm" and litellm_key:
            state = self._read_state()
            base = state.get("litellm", {}).get(
                "base_url",
                os.getenv("LITELLM_BASE_URL", "http://host.docker.internal:4000/v1")
            )
            litellm_model = config.get("litellm_model", "local")
            thinking_model = config.get("thinking_model", "deepseek-reasoner")
            providers.append({
                "name": "litellm",
                "api_key": litellm_key,
                "base_url": f"{base}/chat/completions" if "/chat/completions" not in base else base,
                "model": thinking_model if thinking else litellm_model,
            })

        # TokenSight proxy: route through proxy when configured for usage tracking
        ts_proxy = os.getenv("TOKENSIGHT_PROXY_URL", "").rstrip("/")

        def _url(provider_name: str, direct_url: str) -> str:
            """Use TokenSight proxy URL if configured, otherwise direct."""
            proxy_map = {"deepseek": "/deepseek", "zai": "/zai", "moonshot": "/moonshot"}
            if ts_proxy and provider_name in proxy_map:
                return f"{ts_proxy}{proxy_map[provider_name]}/chat/completions"
            return direct_url

        if ds_key:
            direct_model = config.get("direct_model", "deepseek-chat")
            thinking_model = config.get("thinking_model", "deepseek-reasoner")
            providers.append({
                "name": "deepseek",
                "api_key": ds_key,
                "base_url": _url("deepseek", "https://api.deepseek.com/chat/completions"),
                "model": thinking_model if thinking else direct_model,
            })

        if zai_key:
            providers.append({
                "name": "zai",
                "api_key": zai_key,
                "base_url": _url("zai", "https://api.z.ai/api/paas/v4/chat/completions"),
                "model": "glm-5" if thinking else "glm-4.5-flash",
            })

        moonshot_key = os.getenv("MOONSHOT_API_KEY", "")
        if moonshot_key:
            providers.append({
                "name": "moonshot",
                "api_key": moonshot_key,
                "base_url": _url("moonshot", os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.ai/v1") + "/chat/completions"),
                "model": "kimi-k2.5" if thinking else "moonshot-v1-128k",
            })

        return providers

    # ── Change Detection ──────────────────────────────────────────

    def detect_external_change(self, bot_name: str) -> Optional[str]:
        """Check if provider mode was changed externally (e.g., by xbar).

        Returns a notification string if changed, None otherwise.
        Called before each LLM request.

        Uses dual detection:
        1. mtime cache (detects file change)
        2. mode string comparison (catches VirtioFS mtime delays)
        """
        config = self.get_bot_config(bot_name)
        current_mode = config.get("provider_mode", "direct")
        last_mode = self._last_known_mode.get(bot_name)

        if last_mode is not None and current_mode != last_mode:
            updated_by = config.get("updated_by", "unknown")
            self._last_known_mode[bot_name] = current_mode
            return (
                f"🔄 Provider mode changed externally (by {updated_by}) "
                f"from <b>{last_mode}</b> to <b>{current_mode}</b>"
            )

        self._last_known_mode[bot_name] = current_mode
        return None

    # ── Health ────────────────────────────────────────────────────

    def update_health(self, litellm_ok: bool):
        """Update LiteLLM health status in state file."""
        state = self._read_state()
        litellm = state.setdefault("litellm", {})
        litellm["health_ok"] = litellm_ok
        litellm["last_health_check"] = _now_iso()
        self._atomic_write(state)

    def is_litellm_healthy(self) -> bool:
        """Check stored LiteLLM health status."""
        state = self._read_state()
        return state.get("litellm", {}).get("health_ok", False)

    # ── Query ─────────────────────────────────────────────────────

    def get_all_bots(self) -> dict:
        """Return all bot configs (for xbar display)."""
        state = self._read_state()
        return state.get("bots", {})

    def get_status_text(self, bot_name: str) -> str:
        """Get a formatted status string for display."""
        config = self.get_bot_config(bot_name)
        mode = config.get("provider_mode", "direct")
        chain = self.get_provider_chain(bot_name, thinking=False)

        lines = [f"🔌 <b>LLM Provider ({bot_name})</b>\n"]
        lines.append(f"Mode: <b>{mode}</b>")
        lines.append(f"Updated: {config.get('updated_at', '?')} by {config.get('updated_by', '?')}\n")

        lines.append("Provider chain:")
        for i, p in enumerate(chain):
            arrow = "▶" if i == 0 else "→"
            lines.append(f"  {arrow} {p['name']}: <code>{p['model']}</code>")

        state = self._read_state()
        litellm_info = state.get("litellm", {})
        health = "🟢" if litellm_info.get("health_ok") else "🔴"
        lines.append(f"\nLiteLLM: {health} {litellm_info.get('base_url', '?')}")

        lines.append(
            f"\n<code>/provider litellm</code> — 本地 Ollama\n"
            f"<code>/provider direct</code> — 直连 API"
        )

        return "\n".join(lines)
