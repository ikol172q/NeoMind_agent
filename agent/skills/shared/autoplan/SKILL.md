---
name: autoplan
description: Multi-perspective planning — analyze intent, feasibility, and cost/benefit before committing to action
modes: [shared]
allowed-tools: [Bash, Read, Edit, WebSearch]
version: 2.0.0
---

# AutoPlan — Multi-Perspective Planning

Before committing to a significant task, analyze it from three angles to avoid
wasted effort. This is a single-pass analysis, not a multi-agent simulation.

## When to Use

- User has a vague idea that needs sharpening
- Major initiative (multi-day effort)
- High stakes (financial, production, irreversible)
- "Should I do X?" type questions

## The Three Lenses

### Lens 1: Intent Clarity

Use forcing questions (from `/office-hours`) to understand what the user ACTUALLY needs.

- What is the current reality? (Facts only)
- What is the real problem? (Not the symptom)
- What exact outcome? (Specific, measurable)
- What's the smallest first step?

**Output:** Clear problem statement + success metric.
**Abort if:** User can't articulate a specific goal.

### Lens 2: Technical Feasibility

- Complexity: S / M / L / XL
- Dependencies: what exists vs needs building
- Risks: architecture constraints, performance, data migration
- Effort: rough hours estimate
- Testing strategy

**Output:**
```
Feasibility: FEASIBLE / CONSTRAINED / BLOCKED
Complexity: [S/M/L/XL]
Effort: [hours]
Key risks: [list]
```
**Abort if:** BLOCKED by fundamental constraint.

### Lens 3: Cost/Benefit

- What's the upside? (Revenue, time saved, risk reduced)
- What's the cost? (Time, money, opportunity cost)
- What's the risk-adjusted return?
- Does this align with current priorities?

**Output:**
```
ROI: [positive/negative/unclear]
Payback: [timeline]
Recommendation: PROCEED / HOLD / REJECT
```
**Abort if:** Negative ROI or misaligned with goals.

## Synthesize: Action Plan

If all three lenses pass:

```
PROJECT: [Name]
──────────────────
GOAL: [From Lens 1]
SUCCESS METRIC: [Measurable]

APPROACH:
  Phase 1: [What + deliverable]
  Phase 2: [What + deliverable]

FEASIBILITY: [From Lens 2]
ROI: [From Lens 3]

DECISION: APPROVED / CONDITIONAL / REJECTED

NEXT STEP: [One concrete action to start]
```

## Rules

- Lenses are sequential: don't assess cost before understanding intent
- Abort early if any lens identifies a blocker
- Output is a DECISION, not a brainstorm
- Keep it concise — this should take 5 minutes, not 30
