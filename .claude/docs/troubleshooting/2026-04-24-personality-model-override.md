# Per-personality model overrides break the router single-source-of-truth

**WHEN**: building a multi-persona agent that talks to a model router.

## Wrong design

Per-personality YAML carries its own `model:` and `routing.primary_model:`
fields, e.g.:

```yaml
# agent/config/chat.yaml
routing:
  primary_model: mlx-community/Qwen3-30B-A3B-Instruct-2507-4bit  # MLX free

# agent/config/fin.yaml
routing:
  primary_model: kimi-k2.5  # long context for finance reasoning

# agent/config/coding.yaml
routing:
  primary_model: deepseek-v4-flash  # tool-call reliability
```

User runs `/model deepseek-v4-flash` to set the global model. Then
`/mode fin` to switch persona. Bot silently swaps to `kimi-k2.5`. User
sees "current model: kimi-k2.5" in `/model` output. Confusion.

## Why it's wrong

The whole point of having a router is that **the router holds the
"currently selected model" as a single piece of state**. All personas
should read from that one state. Personas decide *prompt + tools + UI*,
not *which LLM to call*.

When per-persona YAML carries a model field, you have N+1 disagreeing
state stores:

1. yaml `model:` field
2. yaml `routing.primary_model:` field
3. yaml `routing.thinking_model:` field
4. `~/.neomind/provider-state.json :: bots.<bot>.direct_model`
5. (in the bot's own DB) per-chat manual override

The five can drift. The user thinks they set the model; some other
state's value wins. Every silent surprise becomes a bug report.

## Right design

Single source of truth = `~/.neomind/provider-state.json ::
bots.<bot>.direct_model`. Personality YAML carries **no** model field.

```python
# agent/constants/models.py
def get_active_model(bot_name: str = "neomind") -> str:
    from agent.services.provider_state import ProviderStateManager
    return ProviderStateManager().get_active_model(bot_name) or DEFAULT_MODEL
```

Every caller — Telegram bot, CLI, fin/chat/coding — reads via
`get_active_model()` at request time. Switching `/mode chat` does NOT
touch the model; the bot just prints "🤖 当前模型（不变）: X".

## Tradeoff to accept

You **lose** "this persona prefers this model" auto-routing. Some teams
want chat to default to free local MLX, fin to long-context Kimi, coding
to thinking-capable v4-pro. With single-source-of-truth that's gone —
the user has to switch globally before/after the task.

This trade is worth it. The cost of losing the per-persona bias is one
extra `/model` switch when the user wants to. The cost of keeping the
bias is a permanent class of "why is my model X when I set Y" bugs that
multiply with every state store added (xbar, Telegram per-chat override,
CLI saved state, ...).

## Where this hits

- `agent/config/{chat,coding,fin}.yaml` — must NOT have `model:` /
  `routing.*` fields. Only prompt / tools / search / UI.
- `agent/integration/telegram_bot.py` — `_routing_for_mode(mode)` returns
  the same global state for every mode. `_ROUTER_DEFAULT_MODELS` /
  `_ROUTER_THINKING_MODEL` / `_ROUTER_RATE_LIMIT_FALLBACK` per-mode dicts
  must not exist.
- `agent_config.py :: AgentConfigManager.model` property — reads
  `get_active_model()`, ignores any per-mode YAML model field.

## See also

- [2026-04-24-router-auto-discover-strips-deprecated-names.md](2026-04-24-router-auto-discover-strips-deprecated-names.md)
- The architectural fix commit: `ee8f9ee` (refactor(model-state): single
  source of truth + Telegram /model picker)
