# Tool dispatch crashes the whole turn on LLM-hallucinated kwargs

**Discovered**: 2026-06-02, Fin Harness Evolution Loop Phase 1 live verification.

## Symptom

A normal fin-agent question (`"META 现在股价多少"`) crashed mid-turn with:

```
TypeError: get_recent_signals() got an unexpected keyword argument 'ticker'
```

The exception propagated out of `asyncio.gather` in `dashboard_agent/agent.py`
`answer()` and killed the entire turn — the user got nothing.

## Root cause

The LLM (correctly) decided to call a tool, but hallucinated an argument the
tool's Python signature doesn't accept (`get_recent_signals` has
`since_iso/scanner/limit`, no `ticker`). `dispatch()` called the function with
`**args` unguarded:

```python
# WRONG — agent/finance/dashboard_agent/tools.py
async def dispatch(name, args):
    fn = TOOL_FUNCTIONS.get(name)
    if fn is None:
        return {"error": f"unknown tool: {name}"}
    result = await fn(**(args or {}))   # TypeError on extra/bad kwarg → crashes turn
    return _redact(result, _privacy_mode())
```

LLMs **will** pass wrong args — this is not an edge case, it's the expected
failure mode of function-calling. A harness must never let it crash the loop.

## Fix

Filter unknown kwargs (so an over-specified-but-otherwise-valid call still
runs), then catch any residual `TypeError` (e.g. a genuinely missing required
arg) and return it as `{"error": ...}`. The agent loop already knows how to
recover from the error shape and self-corrects on its next iteration.

```python
# RIGHT
import inspect
async def dispatch(name, args):
    fn = TOOL_FUNCTIONS.get(name)
    if fn is None:
        return {"error": f"unknown tool: {name}"}
    args = args or {}
    try:
        params = inspect.signature(fn).parameters
        if not any(p.kind == p.VAR_KEYWORD for p in params.values()):
            args = {k: v for k, v in args.items() if k in params}
    except (TypeError, ValueError):
        pass
    try:
        result = await fn(**args)
    except TypeError as exc:
        return {"error": f"bad arguments for {name}: {exc}"}
    return _redact(result, _privacy_mode())
```

## Why it matters / general rule

Any place that turns LLM-emitted JSON into a real call (`fn(**args)`,
`obj[key]`, `enum(value)`) is an injection point for model mistakes. Validate
or sandbox the boundary and convert failures into a structured error the agent
can see — never an uncaught exception that aborts the turn. Returning the error
(vs silently dropping the arg) lets the model fix itself; dropping unknown
kwargs first lets harmless over-specification succeed.
