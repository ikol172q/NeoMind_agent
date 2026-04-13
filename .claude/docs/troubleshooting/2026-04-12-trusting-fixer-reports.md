# Verify fixer edits BEFORE running tests

**Date**: 2026-04-12
**Category**: subagent management

## Symptom
Dispatch fixer subagent → "done, line 230 patched, syntax OK" → run test
→ same bug persists → confusion / re-dispatch / waste cycles.

## WRONG
```
Dispatch fixer A → A reports success → run tester → fails →
dispatch fixer B for the same bug → B reports success → fails →
... spiral
```

## RIGHT
After ANY fixer reports done:
```bash
# Verify the edit is actually in place
grep -n "<new_string_substring>" <file_path>
# OR
Read <file_path> around the claimed line range
```
Only AFTER verifying, run the test.

## WHY
Fixers sometimes:
- edit the wrong file (similar name, different directory)
- edit the wrong location (same pattern exists in multiple places)
- the file being edited is not the one imported at runtime (`build/lib/`
  copies, stale .pyc cache, wrong virtualenv)
- the fix is logically wrong despite syntax-checking
- the fixer's report is optimistic but the actual edit failed silently

The subagent has narrow context and no runtime feedback. I (manager)
have Read and grep at essentially zero cost. 2 seconds of verification
saves 3 minutes of failed test + re-investigation.

## Stronger form
For high-stakes fixes (production, shared paths), don't just grep.
Actually run a tiny verification:
```python
# Import the patched function and assert the new behavior
.venv/bin/python -c "from agent.services.X import fn; assert fn(test_input) == expected"
```
Before running the full tester.
