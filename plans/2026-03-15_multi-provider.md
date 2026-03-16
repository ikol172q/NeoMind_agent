# Multi-Provider Support — DeepSeek + z.ai (GLM)

**Date:** 2026-03-15
**Status:** Done
**Goal:** Allow ikol1729 to use models from multiple API providers (DeepSeek, z.ai) with seamless switching via `/switch`.

---

## Problem

ikol1729 was hardcoded to DeepSeek — single API key, single base URL, single set of model limits. Adding z.ai's GLM-5 (or any future provider) required touching dozens of places.

## Solution: Provider Registry + Per-Model Specs

### Provider Registry (`_PROVIDERS`)

A class-level dict on `DeepSeekChat` that maps provider names to their config:

```python
_PROVIDERS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/chat/completions",
        "models_url": "https://api.deepseek.com/models",
        "env_key": "DEEPSEEK_API_KEY",
        "model_prefixes": ["deepseek-"],
        "fallback_models": [...],
    },
    "zai": {
        "base_url": "https://api.z.ai/api/paas/v4/chat/completions",
        "models_url": "https://api.z.ai/api/paas/v4/models",
        "env_key": "ZAI_API_KEY",
        "model_prefixes": ["glm-"],
        "fallback_models": [...],
    },
}
```

### Provider Resolution (`_resolve_provider`)

Auto-detects provider from model name prefix:
- `deepseek-chat` → DeepSeek provider
- `glm-5` → z.ai provider
- Unknown prefix → falls back to DeepSeek

Returns a dict with `name`, `base_url`, `models_url`, `api_key`.

### Per-Model Specs (`_MODEL_SPECS`)

Each model has its own limits. These are used automatically in `stream_response` and `generate_completion`:

| Model | Context | Max Output | Default max_tokens |
|-------|---------|------------|-------------------|
| deepseek-chat | 128K | 8K | 8K |
| deepseek-coder | 128K | 8K | 8K |
| deepseek-reasoner | 128K | 64K | 16K |
| glm-5 | 205K | 128K | 16K |
| glm-4.7 | 200K | 32K | 8K |
| glm-4.7-flash | 200K | 32K | 8K |
| glm-4.5 | 128K | 16K | 8K |
| glm-4.5-flash | 128K | 16K | 4K |

Unknown models fall back to 128K/8K/8K defaults.

### Provider-Specific Payload Handling

- **`thinking` parameter:** Only sent for DeepSeek models. z.ai's API doesn't support it.
- **API key:** Resolved per-request from environment variables (`DEEPSEEK_API_KEY`, `ZAI_API_KEY`).
- **Base URL:** Resolved per-request, not cached on `self`.

---

## Files Modified

| File | Changes |
|------|---------|
| `agent/core.py` | Added `_PROVIDERS`, `_MODEL_SPECS`, `_DEFAULT_SPEC`, `_get_model_spec()`, `_resolve_provider()`. Updated `__init__`, `set_model`, `print_models`, `generate_completion`, `stream_response`. |
| `.env` | Added `ZAI_API_KEY` |
| `.env.example` | Added `ZAI_API_KEY` placeholder |

## How to Add a New Provider

1. Add entry to `_PROVIDERS` with `base_url`, `models_url`, `env_key`, `model_prefixes`, `fallback_models`
2. Add model entries to `_MODEL_SPECS` with `max_context`, `max_output`, `default_max`
3. Add `NEW_PROVIDER_API_KEY` to `.env` and `.env.example`
4. If the provider has API quirks (like z.ai not supporting `thinking`), add a provider name check in the payload construction

## Usage

```
/models              # Shows all providers with specs
/switch glm-5        # Switch to z.ai GLM-5
/switch deepseek-chat # Switch back to DeepSeek
/models current      # Show current model + provider
```
