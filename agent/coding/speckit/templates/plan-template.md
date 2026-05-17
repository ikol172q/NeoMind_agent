---
feature: [FEATURE_NAME]
spec: [PATH_TO_SPEC_MD]
constitution_version: [CONSTITUTION_VERSION]
plan_version: 1.0
created: [CREATED_DATE]
---

# Implementation Plan: [FEATURE_NAME]

## Summary

[Extracted from the feature spec — one paragraph on what this feature does and why.]

## Technical Context

- **Language / Runtime**: [e.g., Python 3.11, TypeScript 5.x]
- **Primary Dependencies**: [e.g., FastAPI, React 19, SQLAlchemy]
- **Storage**: [e.g., SQLite, PostgreSQL, filesystem]
- **Testing Framework**: [e.g., pytest, vitest]
- **Target Platform**: [e.g., Linux server, Web (Vite), CLI]
- **Project Type**: [single | web-app | mobile+api | library]
- **Performance Goals**: [e.g., 100ms p95, 10k req/s]
- **Constraints**: [e.g., no new dependencies, backwards-compatible]
- **Scale / Scope**: [e.g., 3 files changed, 1 new module]

## Constitution Check

Each constitutional principle from `.specify/memory/constitution.md` is checked against this plan. Violations MUST be justified.

| Principle | Status | Notes |
|-----------|--------|-------|
| [PRINCIPLE_1] | [PASS / VIOLATION] | [Justification if violation] |
| [PRINCIPLE_2] | [PASS / VIOLATION] | [Justification if violation] |
| [PRINCIPLE_3] | [PASS / VIOLATION] | [Justification if violation] |

## Source Graph

Files affected by this change, ordered by dependency (least-dependent first, from Planner topological sort):

```
[MODIFIED]   path/to/file_a.py  — [what changes]
[MODIFIED]   path/to/file_b.py  — [what changes, depends on file_a]
[NEW]        path/to/new_file.py — [new module]
[DELETED]    path/to/old_file.py — [removed, replaced by new_file]
```

## Architecture Overview

[How this feature fits into the existing codebase. Diagrams preferred (ASCII).]

```
Before:                     After:
┌──────────┐               ┌──────────┐
│ Module A │               │ Module A │
└──────────┘               └────┬─────┘
                                │
                          ┌─────┴─────┐
                          │ New Module│
                          └───────────┘
```

## Implementation Steps

### Step 1: [STEP_NAME]
- **File(s)**: `path/to/file.py`
- **Change**: [What specifically changes]
- **Rollback**: [How to revert if this step fails]
- **Test**: [How to verify this step works]

### Step 2: [STEP_NAME]
- **File(s)**: `path/to/file.py`
- **Change**: [What specifically changes]
- **Rollback**: [How to revert]
- **Test**: [How to verify]

## Verification Plan

1. **Unit Tests**: [Which tests cover this change]
2. **Integration Tests**: [Which integration scenarios to verify]
3. **Manual Verification**: [Steps to manually confirm correctness]
4. **Regression Check**: [What existing behavior must not break]

## Complexity Tracking

Any constitutional violations that were justified:

| Violation | Justification | Risk Mitigation |
|-----------|---------------|-----------------|
| [e.g., skipped test for legacy code] | [Why] | [What prevents regression] |
