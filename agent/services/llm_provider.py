"""LLM Provider Service — model specs, provider routing, model management.

Extracted from core.py (Tier 2B of architecture redesign).
Centralizes all provider/model logic so core.py delegates to this service.

Usage:
    provider = LLMProviderService(api_key="...", model="deepseek-chat")
    resolved = provider.resolve_provider()
    models = provider.list_models()
    provider.set_model("glm-5")

Created: 2026-03-28 (Tier 2B)
"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, List, Optional

try:
    import requests
except ImportError:
    requests = None  # type: ignore


# ── Per-model specs ────────────────────────────────────────────────
# max_context  = total context window (input + output)
# max_output   = hard cap on completion tokens the API will return
# default_max  = sensible default for max_tokens in normal requests
MODEL_SPECS: Dict[str, Dict[str, int]] = {
    # DeepSeek models
    "deepseek-chat": {
        "max_context": 131072,   # 128K
        "max_output": 8192,      # 8K
        "default_max": 8192,
    },
    "deepseek-coder": {
        "max_context": 131072,
        "max_output": 8192,
        "default_max": 8192,
    },
    "deepseek-reasoner": {
        "max_context": 131072,   # 128K
        "max_output": 65536,     # 64K (thinking mode)
        "default_max": 16384,
    },
    # z.ai GLM models
    "glm-5": {
        "max_context": 205000,   # ~200K
        "max_output": 128000,    # 128K
        "default_max": 16384,
    },
    "glm-4.7": {
        "max_context": 200000,   # 200K
        "max_output": 32000,     # 32K
        "default_max": 8192,
    },
    "glm-4.7-flash": {
        "max_context": 200000,   # 200K
        "max_output": 32000,     # 32K
        "default_max": 8192,
    },
    "glm-4.5": {
        "max_context": 128000,   # 128K
        "max_output": 16000,     # 16K
        "default_max": 8192,
    },
    "glm-4.5-flash": {
        "max_context": 128000,   # 128K
        "max_output": 16000,     # 16K
        "default_max": 4096,
    },
    # Moonshot / Kimi models
    "moonshot-v1-128k": {
        "max_context": 131072,   # 128K
        "max_output": 8192,      # 8K
        "default_max": 8192,
    },
    "kimi-k2.5": {
        "max_context": 131072,   # 128K
        "max_output": 65536,     # 64K (thinking mode)
        "default_max": 16384,
        "fixed_temperature": 1,  # Kimi K2.5 only accepts temperature=1
    },
    # Qwen models (local via LiteLLM/Ollama)
    "qwen3.5": {
        "max_context": 131072,   # 128K
        "max_output": 8192,      # 8K
        "default_max": 8192,
    },
    "qwen-plus": {
        "max_context": 1048576,  # 1M
        "max_output": 16384,     # 16K
        "default_max": 8192,
    },
}

DEFAULT_SPEC: Dict[str, int] = {
    "max_context": 131072,
    "max_output": 8192,
    "default_max": 8192,
}

# ── Model aliases ────────────────────────────────────────────────
# Maps friendly/short names to actual model IDs.
# Allows `/switch opus` or `--model sonnet` style usage.
MODEL_ALIASES: Dict[str, str] = {
    # Claude-style aliases → DeepSeek equivalents
    "opus": "deepseek-reasoner",
    "sonnet": "deepseek-chat",
    "haiku": "deepseek-chat",
    # Short aliases
    "reasoner": "deepseek-reasoner",
    "coder": "deepseek-coder",
    "chat": "deepseek-chat",
    # GLM aliases
    "glm": "glm-5",
    "flash": "glm-4.5-flash",
    # Moonshot aliases
    "kimi": "kimi-k2.5",
    "moonshot": "moonshot-v1-128k",
}


def resolve_model_alias(model_id: str) -> str:
    """Resolve a model alias to its actual model ID.

    Returns the original model_id if no alias matches.
    """
    return MODEL_ALIASES.get(model_id.lower(), model_id)

# ── TokenSight proxy support ─────────────────────────────────────
_TOKENSIGHT_PROXY_URL = os.getenv("TOKENSIGHT_PROXY_URL", "").rstrip("/")
_TOKENSIGHT_ROUTES = {
    "deepseek": "/deepseek",
    "zai": "/zai",
    "moonshot": "/moonshot",
}

# ── Provider registry ────────────────────────────────────────────
# Resolve the local LLM router base URL from env. Preferred env var is
# LLM_ROUTER_BASE_URL (what the rest of NeoMind uses); LITELLM_BASE_URL
# is kept as a legacy fallback. Default is port 8000 — matches the
# user's Desktop/LLM-Router. The old port 4000 (~/.llm-gateway, litellm
# proxy) was decommissioned in 2026-04 when the setup moved to the
# custom router + local MLX backend.
_ROUTER_BASE = (
    os.getenv("LLM_ROUTER_BASE_URL")
    or os.getenv("LITELLM_BASE_URL")
    or "http://localhost:8000/v1"
).rstrip("/")

PROVIDERS: Dict[str, Dict[str, Any]] = {
    # "litellm" is a historical name — this entry actually proxies to
    # the LLM-Router at Desktop/LLM-Router/ (port 8000), which in turn
    # fans out to DeepSeek/ZAI/Moonshot cloud + local MLX (:8100).
    # The name is preserved so existing chat-history / user preferences
    # keyed by provider="litellm" keep working.
    #
    # Role: "primary" — this is the ONLY provider the user-facing model
    # list (Telegram /model, CLI /model) should show when it's healthy.
    # The vendor providers below (deepseek/zai/moonshot) are
    # "fallback" role — they stay configured so HTTP calls still work
    # if the router crashes, but they are HIDDEN from the /model UI
    # while the router is up to avoid duplicate entries.
    "litellm": {
        "role": "primary",
        "base_url": f"{_ROUTER_BASE}/chat/completions",
        "models_url": f"{_ROUTER_BASE}/models",
        "env_key": "LLM_ROUTER_API_KEY",
        "model_prefixes": ["mlx-community/", "local"],
        "fallback_models": [
            # Local MLX (replaces Ollama) — Qwen3-30B-A3B MoE trio
            {"id": "mlx-community/Qwen3-30B-A3B-Instruct-2507-4bit",
             "owned_by": "mlx-local"},
            {"id": "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit",
             "owned_by": "mlx-local"},
            {"id": "mlx-community/Qwen3-30B-A3B-Thinking-2507-4bit",
             "owned_by": "mlx-local"},
            # Cloud via router
            {"id": "deepseek-chat",     "owned_by": "deepseek-via-router"},
            {"id": "deepseek-reasoner", "owned_by": "deepseek-via-router"},
            {"id": "glm-5",             "owned_by": "zai-via-router"},
            {"id": "glm-4.7",           "owned_by": "zai-via-router"},
            {"id": "glm-4.7-flash",     "owned_by": "zai-via-router"},
            {"id": "glm-4.7-flashx",    "owned_by": "zai-via-router"},
            {"id": "kimi-k2.5",         "owned_by": "moonshot-via-router"},
        ],
    },
    # Direct vendor providers — role: "fallback". Only surface in the
    # /model UI when the primary (router) is unhealthy. Still used at
    # HTTP-call time for resilience when the router is down.
    "deepseek": {
        "role": "fallback",
        "base_url": "https://api.deepseek.com/chat/completions",
        "models_url": "https://api.deepseek.com/models",
        "env_key": "DEEPSEEK_API_KEY",
        "model_prefixes": ["deepseek-"],
        "fallback_models": [
            {"id": "deepseek-chat", "owned_by": "deepseek"},
            {"id": "deepseek-coder", "owned_by": "deepseek"},
            {"id": "deepseek-reasoner", "owned_by": "deepseek"},
        ],
    },
    "zai": {
        "role": "fallback",
        "base_url": "https://api.z.ai/api/paas/v4/chat/completions",
        "models_url": "https://api.z.ai/api/paas/v4/models",
        "env_key": "ZAI_API_KEY",
        "model_prefixes": ["glm-"],
        "fallback_models": [
            {"id": "glm-5", "owned_by": "z.ai"},
            {"id": "glm-4.7", "owned_by": "z.ai"},
            {"id": "glm-4.7-flash", "owned_by": "z.ai"},
            {"id": "glm-4.5", "owned_by": "z.ai"},
            {"id": "glm-4.5-flash", "owned_by": "z.ai"},
        ],
    },
    "moonshot": {
        "role": "fallback",
        "base_url": os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.ai/v1") + "/chat/completions",
        "models_url": os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.ai/v1") + "/models",
        "env_key": "MOONSHOT_API_KEY",
        "model_prefixes": ["moonshot-", "kimi-"],
        "fallback_models": [
            {"id": "moonshot-v1-128k", "owned_by": "moonshot"},
            {"id": "kimi-k2.5", "owned_by": "moonshot"},
        ],
    },
}


def check_primary_healthy(timeout: float = 2.0) -> bool:
    """Return True if any primary-role provider responds to /v1/models
    within ``timeout`` seconds. Used by UI code (Telegram /model, CLI
    /model) to decide whether to show only primary's live list or to
    expand the full chain including fallbacks.

    HTTP failure, timeout, and missing ``requests`` module all yield
    False — UI then falls through to the expanded-with-fallbacks view.
    """
    if requests is None:
        return False
    for pname, pconf in PROVIDERS.items():
        if pconf.get("role") != "primary":
            continue
        models_url = pconf.get("models_url")
        if not models_url:
            continue
        env_key = pconf.get("env_key", "")
        headers = {}
        if env_key:
            api_key = os.getenv(env_key, "")
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
        try:
            r = requests.get(models_url, headers=headers, timeout=timeout)
            if r.ok:
                return True
        except Exception:
            continue
    return False


def get_model_spec(model: str) -> Dict[str, int]:
    """Return the spec dict for a model, falling back to defaults."""
    return MODEL_SPECS.get(model, DEFAULT_SPEC)


def proxy_url(provider_name: str, path: str) -> str:
    """Build URL, routing through TokenSight proxy if configured."""
    if _TOKENSIGHT_PROXY_URL and provider_name in _TOKENSIGHT_ROUTES:
        return f"{_TOKENSIGHT_PROXY_URL}{_TOKENSIGHT_ROUTES[provider_name]}/{path}"
    return ""


class LLMProviderService:
    """Service for managing LLM providers, model resolution, and model switching.

    Owns:
      - Provider registry (PROVIDERS)
      - Model specs (MODEL_SPECS)
      - TokenSight proxy routing
      - Model listing, switching, and temporary switching
      - /models command handler

    Does NOT own:
      - Actual API calls to LLMs (that stays in core.py's stream_response)
      - Conversation history management
    """

    def __init__(
        self,
        api_key: str = "",
        model: str = "deepseek-chat",
        config: Any = None,
        status_print: Optional[Callable] = None,
    ):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY", "")
        self.model = model
        self.available_models_cache: Optional[List[Dict[str, Any]]] = None
        self._config = config
        self._status_print = status_print or (lambda msg, level="debug": None)

        # Resolve initial provider
        resolved = self.resolve_provider(model)
        self.base_url = resolved["base_url"]
        self.models_url = resolved["models_url"]
        self.provider_name = resolved["name"]

    # ── Provider Resolution ────────────────────────────────────────

    def resolve_provider(self, model: str = None) -> Dict[str, str]:
        """Resolve which provider config to use for a given model.

        Returns a dict with keys: base_url, models_url, api_key, name.
        """
        model = model or self.model
        litellm_enabled = os.getenv("LITELLM_ENABLED", "").lower() in ("true", "1", "yes")

        # If litellm is enabled and model is routable through it
        if litellm_enabled:
            litellm_key = os.getenv("LITELLM_API_KEY", "")
            if litellm_key:
                litellm_models = ["local", "deepseek-chat", "deepseek-reasoner", "qwen3.5", "qwen-plus"]
                if model in litellm_models or model.startswith("local") or model.startswith("qwen"):
                    base = os.getenv("LITELLM_BASE_URL", "http://localhost:4000/v1")
                    return {
                        "name": "litellm",
                        "base_url": f"{base}/chat/completions",
                        "models_url": f"{base}/models",
                        "api_key": litellm_key,
                    }

        # Standard provider matching (with optional TokenSight proxy)
        for name, prov in PROVIDERS.items():
            if name == "litellm":
                continue
            for prefix in prov["model_prefixes"]:
                if model.startswith(prefix):
                    api_key = os.getenv(prov["env_key"], "")
                    proxy_base = proxy_url(name, "chat/completions")
                    proxy_models = proxy_url(name, "models")
                    return {
                        "name": name,
                        "base_url": proxy_base or prov["base_url"],
                        "models_url": proxy_models or prov["models_url"],
                        "api_key": api_key,
                    }

        # Default: deepseek
        prov = PROVIDERS["deepseek"]
        proxy_base = proxy_url("deepseek", "chat/completions")
        proxy_models = proxy_url("deepseek", "models")
        return {
            "name": "deepseek",
            "base_url": proxy_base or prov["base_url"],
            "models_url": proxy_models or prov["models_url"],
            "api_key": self.api_key,
        }

    # ── Provider Fallback Chain ──────────────────────────────────

    def resolve_with_fallback(self, model: str = None) -> Dict[str, str]:
        """Resolve provider with automatic fallback on failure.

        Tries the primary provider first. If it fails (no API key, connection error),
        falls back to the next available provider.

        Fallback order: primary → secondary env key → deepseek (default)
        """
        model = model or self.model

        # Define fallback chain based on available API keys
        candidates = []

        # Primary: model-matched provider
        primary = self.resolve_provider(model)
        if primary.get('api_key'):
            candidates.append(primary)

        # Secondary options: any provider with a configured API key
        for name, prov in PROVIDERS.items():
            api_key = os.getenv(prov.get('env_key', ''), '')
            if api_key and name != primary.get('name'):
                proxy_base = proxy_url(name, "chat/completions")
                candidates.append({
                    'name': name,
                    'base_url': proxy_base or prov['base_url'],
                    'models_url': prov['models_url'],
                    'api_key': api_key,
                })

        if not candidates:
            return primary  # Return anyway, will fail at API call

        return candidates[0]  # Return best candidate

    _provider_health: Dict[str, Dict[str, Any]] = {}

    def mark_provider_unhealthy(self, provider_name: str):
        """Mark a provider as unhealthy after repeated failures."""
        import time
        self._provider_health[provider_name] = {
            'healthy': False,
            'unhealthy_since': time.time(),
            'retry_after': time.time() + 300,  # 5 min cooldown
        }

    def is_provider_healthy(self, provider_name: str) -> bool:
        """Check if a provider is healthy (or cooldown has expired)."""
        import time
        status = self._provider_health.get(provider_name)
        if status is None:
            return True
        if not status['healthy'] and time.time() > status['retry_after']:
            # Cooldown expired, try again
            del self._provider_health[provider_name]
            return True
        return status.get('healthy', True)

    # ── Model Listing ──────────────────────────────────────────────

    def list_models(
        self, force_refresh: bool = False, provider: str = None
    ) -> List[Dict[str, Any]]:
        """List available models from the current provider (or a specific one)."""
        if not force_refresh and self.available_models_cache:
            return self.available_models_cache

        if provider:
            prov = PROVIDERS.get(provider, {})
            models_url = prov.get("models_url", self.models_url)
            api_key = os.getenv(prov.get("env_key", ""), self.api_key)
        else:
            resolved = self.resolve_provider()
            models_url = resolved["models_url"]
            api_key = resolved["api_key"] or self.api_key

        headers = {"Authorization": f"Bearer {api_key}"}

        if requests is None:
            return self._get_fallback_models(provider)

        try:
            response = requests.get(models_url, headers=headers, timeout=10)
            response.raise_for_status()
            models_data = response.json()
            if isinstance(models_data, dict) and "data" in models_data:
                self.available_models_cache = models_data["data"]
                return self.available_models_cache
            elif isinstance(models_data, list):
                self.available_models_cache = models_data
                return self.available_models_cache
            else:
                return self._get_fallback_models(provider)
        except requests.exceptions.RequestException as e:
            self._status_print(f"Error fetching models from {models_url}: {e}", "debug")
            return self._get_fallback_models(provider)

    def _get_fallback_models(self, provider: str = None) -> List[Dict[str, Any]]:
        """Return fallback models when API call fails."""
        if provider and provider in PROVIDERS:
            return list(PROVIDERS[provider]["fallback_models"])
        resolved = self.resolve_provider()
        prov = PROVIDERS.get(resolved["name"], {})
        return list(prov.get("fallback_models", []))

    # ── Model Display ──────────────────────────────────────────────

    def print_models(self, force_refresh: bool = False) -> None:
        """Print available models from ALL configured providers."""
        current_provider = self.resolve_provider()["name"]

        print("\n" + "=" * 60)
        print("AVAILABLE MODELS")
        print("=" * 60)

        total = 0
        for prov_name, prov_config in PROVIDERS.items():
            api_key = os.getenv(prov_config["env_key"], "")
            has_key = bool(api_key)
            status = "✓" if has_key else "✗ (no API key)"

            label = prov_name.upper()
            print(f"\n{'🟢' if has_key else '🔴'} {label} {status}")

            if has_key:
                models = self.list_models(force_refresh=force_refresh, provider=prov_name)
            else:
                models = prov_config["fallback_models"]

            for m in models:
                model_id = m.get("id", m) if isinstance(m, dict) else m
                marker = " ◀ current" if model_id == self.model else ""
                s = get_model_spec(model_id)
                ctx_k = s["max_context"] // 1000
                out_k = s["max_output"] // 1000
                print(f"  • {model_id:<24} {ctx_k}K ctx / {out_k}K out{marker}")
            total += len(models)

        print("\n" + "-" * 60)
        spec = get_model_spec(self.model)
        print(
            f"Current: {self.model} [{current_provider}]  "
            f"(ctx {spec['max_context']//1000}K, out {spec['max_output']//1000}K, "
            f"default {spec['default_max']//1000}K)"
        )
        print(f"Switch:  /switch <model_id>  (e.g. /switch glm-5)")
        # Show aliases
        alias_groups: Dict[str, List[str]] = {}
        for alias, target in MODEL_ALIASES.items():
            alias_groups.setdefault(target, []).append(alias)
        if alias_groups:
            alias_strs = [
                f"{', '.join(aliases)}→{target}"
                for target, aliases in sorted(alias_groups.items())
            ]
            print(f"Aliases: {' | '.join(alias_strs)}")
        print("=" * 60 + "\n")

    # ── Model Switching ────────────────────────────────────────────

    def set_model(self, model_id: str) -> bool:
        """Switch to a different model (may change provider).

        Supports aliases: 'opus' → 'deepseek-reasoner', 'sonnet' → 'deepseek-chat', etc.
        Returns True if model was switched successfully, False otherwise.
        """
        original_id = model_id
        model_id = resolve_model_alias(model_id)
        if model_id != original_id:
            self._status_print(f"Resolved alias '{original_id}' → '{model_id}'", "info")
        new_provider = self.resolve_provider(model_id)

        if not new_provider["api_key"]:
            env_key = PROVIDERS.get(new_provider["name"], {}).get("env_key", "???")
            print(f"✗ No API key for provider '{new_provider['name']}'. Set {env_key} in your .env file.")
            return False

        # Check if model is in the available list
        models = self.list_models()
        available_ids = [m["id"] for m in models]

        target_prov = PROVIDERS.get(new_provider["name"], {})
        fallback_ids = [m["id"] for m in target_prov.get("fallback_models", [])]
        all_known = set(available_ids) | set(fallback_ids)

        if model_id not in all_known:
            print(f"⚠ Model '{model_id}' not in known model lists — trying anyway.")

        old_model = self.model
        old_provider_name = self.resolve_provider(old_model)["name"]
        self.model = model_id

        # Update provider URLs if provider changed
        self.base_url = new_provider["base_url"]
        self.models_url = new_provider["models_url"]
        self.provider_name = new_provider["name"]

        if new_provider["name"] != old_provider_name:
            self.available_models_cache = None

        spec = get_model_spec(model_id)
        spec_info = f"ctx {spec['max_context']//1000}K, out {spec['max_output']//1000}K"

        # Update configuration file
        try:
            if self._config:
                success = self._config.update_value("agent.model", model_id)
            else:
                from agent_config import agent_config
                success = agent_config.update_value("agent.model", model_id)
            provider_label = (
                f" [{new_provider['name']}]"
                if new_provider["name"] != "deepseek"
                else ""
            )
            if success:
                print(f"✓ Model switched: '{old_model}' → '{model_id}'{provider_label} ({spec_info}) (saved)")
            else:
                print(f"✓ Model switched: '{old_model}' → '{model_id}'{provider_label} ({spec_info}) (not saved)")
        except ImportError:
            print(f"✓ Model switched: '{old_model}' → '{model_id}' ({spec_info})")

        return True

    def with_model(self, model_id: str, func: Callable, *args, **kwargs):
        """Temporarily switch to a model, execute a function, then restore original.

        Does NOT update configuration file.
        """
        models = self.list_models()
        available_ids = [m["id"] for m in models]
        if model_id not in available_ids:
            raise ValueError(f"Model '{model_id}' not available")

        original_model = self.model
        try:
            if self.model != model_id:
                self.model = model_id
                print(f"[Model] Temporarily switched to '{model_id}' for this task")
            result = func(*args, **kwargs)
        finally:
            if self.model != original_model:
                self.model = original_model
                print(f"[Model] Restored model to '{original_model}'")
        return result

    # ── Command Handler ────────────────────────────────────────────

    def handle_models_command(self, command: str) -> Optional[str]:
        """Handle /models command with various subcommands."""
        parts = command.split()

        if len(parts) == 1:  # Just "/models"
            self.print_models()
            return None
        elif len(parts) >= 2:
            subcommand = parts[1].lower()

            if subcommand in ["list", "show", "ls"]:
                self.print_models(
                    force_refresh=len(parts) > 2 and parts[2] == "--refresh"
                )
                return None
            elif subcommand in ["switch", "use", "set"]:
                if len(parts) == 3:
                    model_id = parts[2]
                    success = self.set_model(model_id)
                    return (
                        "Model switched successfully."
                        if success
                        else "Failed to switch model."
                    )
                elif len(parts) == 4:
                    target = parts[2].lower()
                    model_id = parts[3]
                    if target in ["agent", "a"]:
                        success = self.set_model(model_id)
                        return (
                            "Model switched successfully."
                            if success
                            else "Failed to switch model."
                        )
                    else:
                        print(f"Unknown target: {target}. Use 'agent'.")
                        print("Usage: /models switch [agent] <model_id>")
                        return None
                else:
                    print("Usage: /models switch [agent] <model_id>")
                    print("Examples:")
                    print(
                        "  /models switch deepseek-reasoner          # Switch to DeepSeek model"
                    )
                    print(
                        "  /models switch glm-5                      # Switch to z.ai model"
                    )
                    print(
                        "  /models switch agent deepseek-reasoner    # Switch model (explicit)"
                    )
                    return None
            elif subcommand in ["current", "active"]:
                print(f"\nCurrent model: {self.model}")
                return None
            elif subcommand in ["help", "?"]:
                print(
                    """
/models commands:
  /models                    - Show available models
  /models list              - List all available models
  /models list --refresh    - Force refresh model list
  /models switch <model>    - Switch agent model (backward compatible)
  /models switch agent <model> - Switch agent model
  /models current           - Show current agent model
  /models help              - Show this help
                """.strip()
                )
                return None
            else:
                print(f"Unknown subcommand: {subcommand}")
                print("Try: /models help")
                return None

        return None
