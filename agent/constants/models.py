"""Single source of truth for DeepSeek model names + runtime active-model accessor.

Static constants (DEFAULT_MODEL / PREMIUM_MODEL / THINKING_MODEL) are the
fallback defaults when no global state is set. The actual *currently
selected* model lives in `~/.neomind/provider-state.json :: bots.<name>.
direct_model` and is read via get_active_model() at call time.

Personality (chat/coding/fin) does NOT decide model — the user picks the
model globally via /model, switching personality just changes prompt and
tools. Single source of truth eliminates the surprise where switching to
fin mode silently swapped you onto Kimi.
"""

DEFAULT_MODEL = "deepseek-v4-flash"
THINKING_MODEL = "deepseek-v4-flash"
PREMIUM_MODEL = "deepseek-v4-pro"

# Cross-vendor backup when the primary 429s. Static — same for all modes.
RATE_LIMIT_FALLBACK = "kimi-k2.5"


def get_active_model(bot_name: str = "neomind") -> str:
    """Read the currently selected model from provider-state.

    Falls back to DEFAULT_MODEL if state file is missing/corrupt or the
    bot hasn't registered yet.
    """
    try:
        from agent.services.provider_state import ProviderStateManager
        return ProviderStateManager().get_active_model(bot_name)
    except Exception:
        return DEFAULT_MODEL


def get_active_personality(bot_name: str = "neomind") -> str:
    """Read the currently active personality (chat/coding/fin)."""
    try:
        from agent.services.provider_state import ProviderStateManager
        return ProviderStateManager().get_active_personality(bot_name)
    except Exception:
        return "fin"


def get_active_max_context(bot_name: str = "neomind") -> int:
    """Return the max context window (tokens) for the currently active model.

    Pulls from agent.services.llm_provider.MODEL_SPECS so the value
    automatically tracks whichever model the user has selected — switching
    `/model deepseek-v4-pro` and `/model kimi-k2.5` should give different
    budgets without touching any config file. Falls back to a conservative
    128K when the registry can't be loaded.
    """
    try:
        from agent.services.llm_provider import MODEL_SPECS, DEFAULT_SPEC
        active = get_active_model(bot_name)
        spec = MODEL_SPECS.get(active, DEFAULT_SPEC)
        return spec.get("max_context", 131072)
    except Exception:
        return 131072


def get_active_max_output(bot_name: str = "neomind") -> int:
    """Return the max output tokens for the currently active model."""
    try:
        from agent.services.llm_provider import MODEL_SPECS, DEFAULT_SPEC
        active = get_active_model(bot_name)
        spec = MODEL_SPECS.get(active, DEFAULT_SPEC)
        return spec.get("max_output", 8192)
    except Exception:
        return 8192
