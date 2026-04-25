# LLM context-window numbers are decimal, not binary

**WHEN**: encoding a vendor's published context-window / max-output token
limits in a static lookup table.

## Wrong

```python
"deepseek-v4-flash": {
    "max_context": 1048576,  # "1M" in binary (2^20)
    "max_output":  393216,   # "384K" in binary (384 × 1024)
},
```

## Why it's wrong

Vendor docs usually publish "1M" / "128K" / "384K" as **decimal marketing
numbers**, not binary mebibytes. DeepSeek's docs at
https://api-docs.deepseek.com/quick_start/pricing literally say:

> CONTEXT LENGTH: 1M
> MAXIMUM: 384K

Decimal expansion of those is `1,000,000` and `384,000`. Binary expansion
(`1,048,576` / `393,216`) is **48k / 9k tokens too generous** — sending a
prompt at 1,048,000 tokens to a 1,000,000-cap model will 400. Also it
makes UI percentages display wrong (a 500K conversation shows as 47.7%
when the actual capacity says it should be 50%).

## Right

```python
"deepseek-v4-flash": {
    "max_context": 1000000,  # 1M, decimal — matches vendor docs verbatim
    "max_output":  384000,   # 384K, decimal
},
```

## How to verify quickly

Read the vendor docs and use the SAME notation. If they say "200K", it's
200,000 unless they explicitly say "204800" or "2^X". Don't translate
"K" to "kibi" or "M" to "mebi" — vendors are using SI, not IEC.

Counterexamples: Moonshot's `kimi-k2.5` is documented as 128K but the
API actually accepts up to 131,072 tokens — they used binary. Test with
a fence-sitter prompt to confirm. The defensive default is decimal.

## Where this hits in NeoMind

- `agent/services/llm_provider.py :: MODEL_SPECS` — primary table
- `agent/integration/telegram_bot.py :: _MODEL_CONTEXT` — should mirror
  MODEL_SPECS exactly (don't carry separate numbers)
- `~/Desktop/LLM-Router/llm-router.1m.py :: PRICING` — separate table for
  xbar; keep numbers consistent with MODEL_SPECS

Whenever you change one, grep for the other names and update both.

## See also

- DeepSeek pricing page: https://api-docs.deepseek.com/quick_start/pricing
- Fix commit: `d42295e` (fix(ctx): correct v4 context window numbers +
  auto-derive from active model)
