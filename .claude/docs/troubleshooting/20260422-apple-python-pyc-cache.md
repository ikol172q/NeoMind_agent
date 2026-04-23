# macOS `com.apple.python` pyc cache hijacks imports

**Date**: 2026-04-22
**Slug**: apple-python-pyc-cache

## Symptom

You edit a Python file, confirm the changes on disk with `xxd`, but
`python -c "from mypkg import mod; print(mod.CONSTANT)"` still
returns the OLD value. Clearing the local `__pycache__/` doesn't
help.

## Root cause

macOS maintains a user-level bytecode cache at:
```
~/Library/Caches/com.apple.python/<absolute-path-to-project>/.../*.cpython-39.pyc
```
Python loads this stale `.pyc` instead of recompiling the edited
`.py`, even when modification times should trigger recompilation.

Found because `importlib.util.find_spec(...).cached` pointed at:
```
/Users/user/Library/Caches/com.apple.python/...agent/finance/lattice/spec.cpython-39.pyc
```

## Detection

```python
.venv/bin/python -c "
import importlib.util
s = importlib.util.find_spec('agent.finance.lattice.spec')
print('origin:', s.origin)
print('cached:', s.cached)
"
```
If `cached` is under `~/Library/Caches/com.apple.python/`, this is
the bug.

## Fix

```bash
rm -rf "$HOME/Library/Caches/com.apple.python"
```
Or target the specific file:
```bash
rm -f "$HOME/Library/Caches/com.apple.python/$(pwd)/path/to/module.cpython-39.pyc"
```

## Prevention

- `PYTHONDONTWRITEBYTECODE=1` (in `.envrc` / shell profile) prevents
  future stale bytecode.
- For tests with hot-reloaded modules (importlib.reload), clear the
  Apple cache between runs as a CI step.

## Why this matters for Insight Lattice V4

V4's drift tests rely on `from agent.finance.lattice import spec`
to pick up post-edit spec values. If the Apple pyc cache is stale,
drift tests could give a FALSE GREEN (pinned values still pass
because the "new" spec values aren't actually loaded). The fix
above restores the integrity contract.
