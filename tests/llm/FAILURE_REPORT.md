# Failure Report — 2026-04-03

## Failures Found:

### From `test_conversation_scenarios.py` (standalone script run):

1. **Scenario 8: Code Generation (Real LLM)**
   - Test: `LLM generates code`
   - Error: `Response length: 0`
   - Details: The LLM appeared to generate a valid Python code block (`def add(a, b): return a + b`) as shown in the "Generated content" output, but the test assertion measured the response length as 0. This suggests the code extraction/parsing logic is not capturing the generated code correctly, even though the LLM did produce output.

### From `pytest tests/llm/ -v --tb=short`:

No failures. All 58 tests passed.

Note: The pytest wrapper for `test_scenario_code_generation` (Scenario 8) PASSED in pytest, which means the pytest version of this test has different assertions or thresholds than the standalone script version.

## Summary:
- **Standalone script:** 71/72 passed, 1 failed
- **pytest:** 58/58 passed, 0 failed

### Standalone script breakdown by scenario:
| Scenario | Passed | Failed |
|---|---|---|
| 1. Basic Conversation | 2/2 | 0 |
| 2. Context Memory | 2/2 | 0 |
| 3. Slash Commands | 9/9 | 0 |
| 4. Session Save/Resume | 9/9 | 0 |
| 5. Security Enforcement | 18/18 | 0 |
| 6. Permission System | 11/11 | 0 |
| 7. Service Registry | 11/11 | 0 |
| 8. Code Generation (Real LLM) | 0/1 | 1 |
| 9. Frustration Detection | 4/4 | 0 |
| 10. Feature Flags | 5/5 | 0 |

## Each failure details:

### Failure 1: Scenario 8 — Code Generation (Real LLM) — "LLM generates code"

**Exact error output:**
```
  ❌ LLM generates code
     → Response length: 0
```

**Context:** The test printed generated content showing a valid Python snippet:
```python
def add(a, b):
    return a + b
```

Despite the LLM producing this code, the test reported `Response length: 0`, indicating the variable capturing the response was empty. The root cause is likely in how the test extracts or stores the LLM response -- the code block was rendered to stdout but not captured into the variable being asserted on.

## Additional Notes:
- 1 pytest warning: `PytestCollectionWarning: cannot collect test class 'TestReport' because it has a __init__ constructor` (non-fatal, informational only).
- A "Permission denial fallback activated" message appeared during Scenario 4, but it did not cause a test failure.
