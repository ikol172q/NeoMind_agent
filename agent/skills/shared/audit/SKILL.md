---
name: audit
description: Multi-pass quality + security audit — iterative cycles with expanding scope (core → edge → security → integration → adversarial)
modes: [chat, coding, fin]
allowed-tools: [Bash, Read, Edit, Grep, WebSearch]
version: 2.0.0
---

# Audit — Iterative Quality & Security Assurance

You are running NeoMind's self-audit. This is a core trait — the ability to
systematically find and fix its own problems across quality AND security dimensions.

## Workflow: N-Cycle Audit

Given a **core goal** and **number of cycles N**, execute:

```
For each cycle i = 1..N:
  1. SCAN    — search for problems (expanding scope each cycle)
  2. CHECK   — verify against expected behavior
  3. REVIEW  — assess severity and root cause
  4. FIX     — fix issues (code, config, docs)
  5. VERIFY  — run tests, confirm fix doesn't break anything
  6. RECORD  — log findings + fixes to audit trail
  7. EXPAND  — widen scope for next cycle
```

## Scope Expansion Strategy

| Cycle | Focus |
|-------|-------|
| 1 | **Core functionality** — main features work? Run tests, check imports |
| 2 | **Edge cases** — empty inputs, timeouts, missing env vars, fallback paths |
| 3 | **Security (per-mode)** — see Mode-Specific Security below |
| 4 | **Cross-module integration** — do modules compose correctly? Data flow? |
| 5 | **Docs & consistency** — README matches reality? Config examples? Naming? |
| 6+ | **Adversarial** — what breaks if Ollama is down? DeepSeek times out? SQLite locked? |

## Mode-Specific Security (Cycle 3)

### Coding Mode
- **OWASP Top 10**: SQL injection, XSS, CSRF, auth, authorization, data exposure
- **Dependency scan**: `pip audit` / `npm audit` — flag known vulnerabilities
- **Secrets detection**: hardcoded API keys, passwords, tokens in code or git history
- **STRIDE threat model**: Spoofing, Tampering, Repudiation, Info Disclosure, DoS, Privilege Escalation

### Finance Mode
- **API key safety**: stored in secrets manager? Rotated? Minimal permissions? Access logged?
- **Position limits**: single ≤ 20% of portfolio? Sector ≤ 30%? Daily loss limit enforced?
- **Wash sale detection**: securities sold at loss within 30 days? Flag for review
- **PII in logs**: account numbers, SSN, passwords logged anywhere?

### Chat Mode
- **PII scan**: usernames, emails, phone numbers shared unnecessarily?
- **Data retention**: how long is conversation data retained? PII purged?
- **Log access**: restricted to authorized users only?

## Output Format

Each cycle produces: `plans/audit/audit-YYYY-MM-DD-cycle-N.md`

```markdown
# Audit Cycle N — YYYY-MM-DD

## Scope: [what was checked]

## Findings

| # | Severity | Module | Issue | Status |
|---|----------|--------|-------|--------|
| 1 | 🔴 CRITICAL | ... | ... | FIXED |
| 2 | 🟠 HIGH | ... | ... | DEFERRED |
| 3 | 🟡 MEDIUM | ... | ... | FIXED |
| 4 | 🟢 LOW | ... | ... | NOTED |

## Fixes Applied

| Finding | Fix | Test |
|---------|-----|------|
| #1 | Changed X to Y | test_foo passed |

## Tests Run

- pytest tests/ → X passed, Y failed
- Security scan → [result]

## Next Cycle Scope

- [what to check next]
```

## Rules

1. **Skip already-audited items** — read `plans/audit/` logs first. Don't re-check unless final regression.
2. **Every finding must be recorded** — no silent fixes.
3. **Every fix must be tested** — no "I think this is fixed."
4. **Final cycle = full regression** — re-run ALL tests.
5. **CRITICAL findings block release** — HIGH findings require sprint inclusion.
6. **Evidence required** — screenshot or code excerpt for each finding.

## Integration

- CLI: `/audit <goal> <cycles>`
- Telegram: `/audit` (quick 1-cycle)
- Automated: startup check + nightly audits via AutoEvolve
- Evidence trail logs every audit action.
