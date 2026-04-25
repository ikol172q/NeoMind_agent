# Router auto_discover silently 404s deprecated model names

**WHEN**: any time a vendor deprecates an old model id in their `/v1/models`
listing while keeping the deprecated name as a server-side alias.

## Wrong assumption

> "DeepSeek says `deepseek-chat` and `deepseek-reasoner` will be deprecated
> in the future. Currently they still work as aliases for v4-flash. Safe to
> keep using them as defaults until the actual deprecation date."

## What actually happened (2026-04-24)

DeepSeek removed `deepseek-chat` / `deepseek-reasoner` from
`https://api.deepseek.com/v1/models` *before* announcing a hard deprecation
date. The names still resolve at the **direct vendor API** (cache-aliased
to `deepseek-v4-flash`).

But `Desktop/LLM-Router/config.yaml` had `auto_discover: true` for the
deepseek provider. The router polls the vendor's `/v1/models` every
10 minutes and **replaces the hardcoded fallback list** with what the
vendor returned. So the router's *valid model set* dropped the deprecated
names. Any client request with `model="deepseek-chat"` to the router got:

```
{"detail": "Model 'deepseek-chat' not found. Available: ['deepseek-v4-flash', ...]"}
```

→ 404, not a silent route to the alias. NeoMind's per-personality
`routing.primary_model: deepseek-reasoner` (chat / coding / fin yamls all
had legacy defaults) silently broke. Direct-vendor fallback path still
worked, so things half-worked, hiding the issue.

## Right approach

When migrating a model id from a vendor that has both:

1. **Trust the vendor's `/v1/models` as the source of truth** for what the
   router will accept. Hit it directly:
   ```
   curl -sS https://api.deepseek.com/v1/models \
     -H "Authorization: Bearer $DEEPSEEK_API_KEY" | jq '.data[].id'
   ```
   If a name isn't there, the router can't route it — **no matter what
   the vendor's docs say about aliases**.

2. **Test through the router** before declaring migration done:
   ```
   curl -X POST http://127.0.0.1:8000/v1/chat/completions \
     -H 'Content-Type: application/json' \
     -d '{"model":"<old-name>","messages":[{"role":"user","content":"x"}]}'
   ```
   404 → migrate every default away from `<old-name>` immediately.

3. **Either** add the deprecated names to the router's hardcoded `models:`
   list as a floor (works for some routers; in our LLM-Router config the
   floor IS the fallback), **or** switch all defaults to the new names
   and add a migration map (`agent/migrations/__init__.py ::
   _migrate_007_deprecated_model_aliases`) that auto-upgrades any
   persisted reference on next boot.

## How NeoMind handled it

`agent/migrations/__init__.py`'s `deprecated_models` dict catches old
names in `~/.neomind/config.json` and rewrites them to
`deepseek-v4-flash` on next start. Combined with the hard removal of
legacy entries from `MODEL_SPECS` / `MODEL_ALIASES` / `_MODEL_CONTEXT`
/ pricing tables, there is no production code path left that can route
`deepseek-chat` or `deepseek-reasoner` to the router (they reject as
"unknown model" at `/model` switch time).

## Cost of the mistake

~30 minutes of confusing user reports ("model is kimi but I set
v4-flash") before tracing the chain back to `routing.primary_model`
silently overriding the global state.

## See also

- [2026-04-24-personality-model-override.md](2026-04-24-personality-model-override.md)
  — the parallel architectural mistake that hid this for an extra round
- DeepSeek pricing docs: https://api-docs.deepseek.com/quick_start/pricing
- LLM-Router config: `~/Desktop/LLM-Router/config.yaml`
