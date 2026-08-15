# Reasoning tokens are billed against `max_tokens`, so a budget sized for the answer starves the answer

**Symptom.** An LLM call that used to work returns truncated JSON. The parse
fails with something like:

```
json.decoder.JSONDecodeError: Unterminated string starting at: line 1 column 15 (char 14)
```

Char 14 is barely past `{"narrative": "`, so it reads like the model returned
nothing useful — or like the API is broken. If the call site catches broadly
and falls back (as `themes.generate_narrative` does, to an English template),
**nothing surfaces at all**: no error, no alert, just output that is quietly
never what was configured. The bug here lived in production undetected until
one test asserted the narrative was in Chinese.

## Wrong

```python
resp = client.post(url, json={
    "model": DEFAULT_MODEL,          # deepseek-v4-flash — a REASONING model
    "messages": [...],
    "max_tokens": 200,               # sized for the ~50-80 token answer
    "response_format": {"type": "json_object"},
})
content = resp.json()["choices"][0]["message"]["content"]
return json.loads(content)           # boom, intermittently
```

The reasoning pass runs *before* the answer and its tokens count against the
same `max_tokens` ceiling. When reasoning alone reaches the ceiling, the
answer never starts, `finish_reason` comes back `"length"`, and `content` is
a truncated fragment.

Measured on `deepseek-v4-flash`, same prompt, 6 samples at `max_tokens=200`:

```
#1 finish=length completion=200 reasoning=200 json_complete=False
#2 finish=length completion=200 reasoning=200 json_complete=False
#3 finish=length completion=200 reasoning=200 json_complete=False
#4 finish=length completion=200 reasoning=200 json_complete=False
#5 finish=length completion=200 reasoning=200 json_complete=False
#6 finish=stop   completion=183 reasoning=135 json_complete=True
```

Five of six. Note it is *intermittent* — sample #6 fits — which is why this
reads as flakiness rather than a deterministic bug, and why a single manual
retry "proves" the code works.

## Right

Budget for reasoning **plus** answer, and verify by sampling rather than by
one lucky call:

```python
    # DEFAULT_MODEL is a reasoning model and its reasoning tokens are billed
    # against max_tokens, so a budget sized for the answer alone starves the
    # answer. Measured: reasoning alone hit the old 200 ceiling in 5 of 6
    # samples. The narrative itself is only ~50-80 tokens; the headroom here
    # is for the reasoning pass.
    "max_tokens": 800,
```

Same probe at 800: 6/6 complete, reasoning peaking at **408** tokens — so 800
is headroom, not a new cliff. Picking 500 off intuition would have left a
cliff just past the observed peak.

## How to diagnose it in one step

Do not infer truncation from the parse error. Ask the API — `finish_reason`
and `usage` say it outright:

```python
d = resp.json()
ch = d["choices"][0]
print(ch["finish_reason"])                                       # "length" == truncated
print(d["usage"]["completion_tokens"])                           # == max_tokens when truncated
print(d["usage"]["completion_tokens_details"]["reasoning_tokens"])  # where it all went
```

`finish_reason="length"` with `reasoning_tokens ≈ max_tokens` is the
signature. Sample it 5-6 times; one call tells you nothing about an
intermittent ceiling.

## Why it bites

- The ceiling is only reached when reasoning runs long, and reasoning length
  varies with prompt content. Switching a taxonomy to `zh-CN-mixed` was enough
  to push it over.
- A broad `except Exception` around the call converts a hard failure into a
  silent fallback, so the blast radius is "wrong output forever" rather than
  "loud error once".
- Non-reasoning models never showed this, so a `max_tokens` that was correct
  when written silently became wrong when `DEFAULT_MODEL` was repointed.

## Rule

When a call site names a reasoning model, `max_tokens` is a *combined* budget.
Size it against measured `reasoning_tokens` peaks, not against the length of
the answer you want — and if the call has a fallback path, log loudly enough
that a truncation can never masquerade as a normal result.
