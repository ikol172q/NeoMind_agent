# Flipping a default silently retargets every test that mocked the old one

**2026-08-16, Phase 6B (fleet worker turn migration).**

## What happened

`fleet/worker_turn.py` injects its LLM call so tests can replace it:

```python
call = llm_call or _default_llm_call        # before
call = llm_call or _resolve_llm_call()      # after
```

Existing tests take the second branch and patch the function by name:

```python
# tests/test_fleet_session.py, tests/test_fleet_fin_end_to_end.py
monkeypatch.setattr(worker_turn, "_default_llm_call", mock)
```

That worked while `_resolve_llm_call()` returned `_default_llm_call`. Then the
default flipped:

```python
# WRONG to do without checking who patches the old symbol
return os.getenv("NEOMIND_FLEET", "session").strip().lower() == "session"
```

`_resolve_llm_call()` now returns the session-backed call, so **the mock is
never consulted**. The tests kept passing — and started making real provider
calls, and writing fabricated rows into the user's production audit log at
`~/Desktop/Investment/_audit/YYYY-MM-DD.jsonl`, with the same `endpoint` and
`agent_id` as a genuine fleet turn. Nothing distinguishes them afterwards.

Nothing failed. The suite quietly changed what it was testing.

## Why it is easy to miss

A default is not a value, it is **every call site that did not specify one** —
including the ones inside tests. The switch was added carefully (D8 rollback,
env-controlled, read per call), verified with a real fleet run, and checked
against an audit marker to prove the new path ran. All of that was about
production. None of it looked at what the *suite* would now resolve to.

## Rules

1. **Before flipping a default, grep for who patches the symbol it used to
   resolve to.**

   ```bash
   git grep -n "setattr(.*_default_llm_call\|patch.*_default_llm_call"
   ```

   Every hit is a test whose mock is about to become decorative.

2. **Pin switch-style env vars in `conftest.py`, autouse, at the old value.**
   Tests that want the new path opt in explicitly, so the migration cannot
   move the suite underneath itself.

   ```python
   @pytest.fixture(autouse=True)
   def _fleet_stays_on_the_injectable_path(monkeypatch):
       if "NEOMIND_FLEET" not in os.environ:
           monkeypatch.setenv("NEOMIND_FLEET", "legacy")
   ```

3. **Redirect production data roots for the whole test session**, so no test
   can reach real user data whatever it resolves to. `agent_audit` already
   honoured `NEOMIND_INVESTMENT_ROOT` and its docstring even said "(tests)" —
   nothing had ever set it.

   ```python
   @pytest.fixture(autouse=True, scope="session")
   def _never_write_the_real_audit_log(tmp_path_factory):
       os.environ["NEOMIND_INVESTMENT_ROOT"] = str(tmp_path_factory.mktemp("inv"))
       agent_audit._default = None      # the logger caches its path
   ```

   An existing escape hatch nobody uses is not protection.

4. **A test that reaches the network or the user's disk is a bug even when it
   passes.** Assert it: capture the line count of the real log before and
   after a run and require it unchanged.

## Related finding, same session

`fleet/launch_project.py` called `self._task_queue.complete_task(...)`
unconditionally, and `complete_task` hardcoded `task['status'] = 'completed'`.
A worker turn that failed was recorded in the queue as **completed**, with the
error text sitting where the result summary belongs — while the leader
notification, built two lines later from the same dict, correctly reported
`failed`. Anything consulting the queue to ask "did this work?" got the wrong
answer. Fixed by threading through the status the caller already had.

## Related

- `20260816-fixture-encoded-assumption.md` — the same family: a test that
  passes while measuring the wrong thing.
