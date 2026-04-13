# Contract 04 — Cross-Persona Memory with Source Tags

**Phase:** 4
**Status:** SPEC — not implemented
**Scope:** `agent/memory/shared_memory.py` (schema extension + API extension)

---

## Summary

Today `SharedMemory` tracks `source_mode` (which personality wrote the entry). For fleet operation, we also need `source_instance` (which specific agent instance) and `project_id` (which project/team context). Reads should support filtering by persona and wrapping cross-persona content in source attribution envelopes for LLM context injection.

---

## Schema Migration

### New columns (all nullable for backward compat)

Add to **every table** (preferences, facts, patterns, feedback):

```sql
ALTER TABLE facts ADD COLUMN source_instance TEXT;
ALTER TABLE facts ADD COLUMN project_id TEXT;

ALTER TABLE patterns ADD COLUMN source_instance TEXT;
ALTER TABLE patterns ADD COLUMN project_id TEXT;

ALTER TABLE feedback ADD COLUMN source_instance TEXT;
ALTER TABLE feedback ADD COLUMN project_id TEXT;

ALTER TABLE preferences ADD COLUMN source_instance TEXT;
ALTER TABLE preferences ADD COLUMN project_id TEXT;
```

Migration must be **non-destructive**: existing rows get NULL for new columns, which is fine.

### Migration strategy

On `SharedMemory.__init__()`, after `_init_schema()`, run `_migrate_schema()` that:
1. Checks if `source_instance` column exists in `facts` table
2. If not, runs the ALTER TABLE statements
3. Idempotent (safe to run multiple times)

---

## API Changes

### Write methods — add optional parameters

```python
def remember_fact(self, category: str, fact: str, source_mode: str,
                  source_instance: Optional[str] = None,
                  project_id: Optional[str] = None) -> int:

def record_pattern(self, pattern_type: str, pattern_value: str, source_mode: str,
                   source_instance: Optional[str] = None,
                   project_id: Optional[str] = None) -> None:

def record_feedback(self, feedback_type: str, content: str, source_mode: str,
                    source_instance: Optional[str] = None,
                    project_id: Optional[str] = None) -> int:

def set_preference(self, key: str, value: str, source_mode: str,
                   source_instance: Optional[str] = None,
                   project_id: Optional[str] = None) -> None:
```

### Read methods — add filtering

```python
def recall_facts(self, category: Optional[str] = None, limit: int = 20,
                 include_personas: Optional[List[str]] = None,
                 project_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Args:
        include_personas: If provided, only return facts from these source_modes.
            Example: ["coding", "fin"] returns facts from coding and fin only.
        project_id: If provided, only return facts from this project.
    """

def get_patterns(self, pattern_type: Optional[str] = None, limit: int = 50,
                 include_personas: Optional[List[str]] = None,
                 project_id: Optional[str] = None) -> List[Dict[str, Any]]:
```

### New method — cross-persona context with source envelopes

```python
def get_cross_persona_context(self, current_mode: str,
                               project_id: Optional[str] = None,
                               max_tokens: int = 300) -> str:
    """Generate LLM context showing cross-persona knowledge with source attribution.
    
    Returns content wrapped in source envelopes like:
    
        <from persona="coding" instance="coder-1">
        User prefers Python 3.12, uses pytest for testing.
        </from>
        
        <from persona="fin" instance="quant-1">
        User watches AAPL, NVDA, MSFT daily. Risk tolerance: moderate.
        </from>
    
    Content from the current_mode is NOT wrapped (it's "native" knowledge).
    Only cross-persona content gets envelopes.
    
    Args:
        current_mode: The requesting persona's mode
        project_id: Optional project filter
        max_tokens: Approximate token budget
    
    Returns:
        Formatted context string with source envelopes
    """
```

---

## Backward Compatibility

- All new parameters are Optional with None defaults
- Existing callers of `remember_fact(cat, fact, mode)` continue to work unchanged
- Existing DB rows have NULL for new columns — reads treat NULL as "no filter match" (include in results)
- `get_context_summary()` (existing method) continues to work unchanged

---

## Test Contract (Pair A implements these)

### Unit Tests

1. **`test_schema_migration_idempotent`**: Create SharedMemory twice → no error on second init (migration runs twice safely).

2. **`test_write_fact_with_instance`**: `remember_fact("work", "SDE", "coding", source_instance="coder-1", project_id="proj-1")` → read back → has `source_instance="coder-1"` and `project_id="proj-1"`.

3. **`test_write_fact_without_instance`**: `remember_fact("work", "SDE", "coding")` → read back → `source_instance is None`, `project_id is None` (backward compat).

4. **`test_filter_by_persona`**: Write facts from chat, coding, fin → `recall_facts(include_personas=["coding", "fin"])` → only coding and fin facts returned.

5. **`test_filter_by_project`**: Write facts for proj-1 and proj-2 → `recall_facts(project_id="proj-1")` → only proj-1 facts.

6. **`test_cross_persona_context_envelopes`**: Write facts from coding and fin → `get_cross_persona_context("chat")` → output contains `<from persona="coding">` and `<from persona="fin">` envelopes.

7. **`test_cross_persona_context_excludes_self`**: Write facts from chat → `get_cross_persona_context("chat")` → chat facts NOT wrapped in envelopes (they're native).

8. **`test_legacy_data_loads`**: Manually insert rows without source_instance/project_id columns → reads succeed with None values.

9. **`test_pattern_filter_by_persona`**: `get_patterns(include_personas=["fin"])` → only fin patterns.

10. **`test_preference_with_instance`**: `set_preference("tz", "UTC", "chat", source_instance="mgr-1")` → read back includes source_instance.
