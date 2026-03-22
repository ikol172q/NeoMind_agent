---
name: self-audit
description: Multi-pass self-audit workflow — search, check, review, fix, verify in iterative cycles
modes: [chat, coding, fin]
allowed-tools: [Bash, Read, Edit, WebSearch]
version: 1.0.0
---

# Self-Audit — Iterative Quality Assurance Workflow

You are running NeoMind's self-audit cycle. This is a core trait of the agent —
the ability to systematically find and fix its own problems.

## Workflow: N-Cycle Audit

Given a **core goal** and **number of cycles N**, execute:

```
For each cycle i = 1..N:
  1. SCAN    — search for problems (expanding scope each cycle)
  2. CHECK   — verify what was found against expected behavior
  3. REVIEW  — assess severity and root cause
  4. FIX     — fix issues found (code, config, docs)
  5. VERIFY  — run tests, confirm fix doesn't break anything
  6. RECORD  — log findings + fixes to audit trail
  7. EXPAND  — widen the audit scope for next cycle
```

## Scope Expansion Strategy

Each cycle widens the lens to avoid repeating the same checks:

| Cycle | Focus |
|-------|-------|
| 1 | **Core functionality** — do the main features work? Run tests, check imports |
| 2 | **Edge cases** — empty inputs, timeouts, missing env vars, fallback paths |
| 3 | **Security** — API keys exposed? Sensitive data in tracked files? Permissions? |
| 4 | **Cross-module integration** — do modules compose correctly? Data flow between them? |
| 5 | **Docs & consistency** — README matches reality? Config examples correct? Naming consistent? |
| 6+ | **Adversarial** — what breaks if Ollama is down? If DeepSeek times out? If SQLite is locked? |

## Rules

1. **Skip already-audited items** — read `plans/audit/` logs to see what was checked before.
   Don't re-verify things that passed unless doing a full regression (final cycle).
2. **Every finding must be recorded** — append to `plans/audit/audit-{date}-cycle-{N}.md`
3. **Every fix must be tested** — no "I think this is fixed." Run the test.
4. **Final cycle = full regression** — re-run ALL tests to ensure no new breakage.
5. **Back-compatibility check** — verify existing features still work after fixes.

## Audit Record Format

Each cycle produces a file: `plans/audit/audit-YYYY-MM-DD-cycle-N.md`

```markdown
# Audit Cycle N — YYYY-MM-DD

## Scope: [what was checked this cycle]

## Findings

| # | Severity | Module | Issue | Status |
|---|----------|--------|-------|--------|
| 1 | 🔴 HIGH | telegram_bot.py | ... | FIXED |
| 2 | 🟡 MED | guards.py | ... | DEFERRED |

## Fixes Applied

| Finding | Fix | Test |
|---------|-----|------|
| #1 | Changed X to Y | test_foo passed |

## Tests Run

- pytest tests/ → X passed, Y failed
- Import check → 29/29 OK
- Security scan → clean

## Skipped (already audited)

- [list of items checked in previous cycles]

## Next Cycle Scope Expansion

- [what to check in cycle N+1]
```

## Integration with NeoMind

This workflow is also available as:
- CLI: `/audit <goal> <cycles>` — runs the full audit loop
- Telegram: `/audit` — runs a quick 1-cycle audit
- Automated: scheduled task can run nightly audits

The evidence trail (`agent/workflow/evidence.py`) logs every audit action.
Sprint framework can wrap an audit as a structured task.
