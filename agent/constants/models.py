"""Single source of truth for DeepSeek model names.

When DeepSeek releases a new generation, edit this file and most of NeoMind
follows automatically. Per-mode YAML overrides
(`agent/config/{chat,coding,fin}.yaml :: model`) still take precedence at
runtime — those are deliberate per-persona choices, not duplicated defaults.
"""

DEFAULT_MODEL = "deepseek-v4-flash"
THINKING_MODEL = "deepseek-v4-flash"
PREMIUM_MODEL = "deepseek-v4-pro"
