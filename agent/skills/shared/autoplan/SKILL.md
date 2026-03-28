---
name: autoplan
description: 3-lens single-pass analysis — intent (chat lens), feasibility (coding lens), cost/benefit (fin lens). NOT multi-agent orchestration.
modes: [chat, coding, fin]
allowed-tools: [Bash, Read, Edit, WebSearch, Grep]
version: 3.0.0
---

# AutoPlan — 3-Lens Single-Pass Planning

Before committing to a significant task, analyze it from three angles in a single pass.
This is a deterministic analysis, not multi-agent orchestration or fake parallelization.

**CRITICAL:** You are one agent analyzing from three perspectives in sequence.
You are NOT simulating three separate agents or calling external APIs.
All three lenses use your reasoning capability applied to different decision frameworks.

## When to Use

- User has a vague idea that needs sharpening
- Major initiative (multi-day effort)
- High stakes (financial, production, irreversible)
- "Should I do X?" type questions

## The Three Lenses (Single-Pass Sequential Analysis)

### Lens 1: Intent Clarity (Chat Lens)
**Perspective:** What does the user actually need?

Use forcing questions to cut through vagueness:
- What is the current reality? (Facts only, no assumptions)
- What is the real problem? (Not the symptom, not what they asked for)
- What exact outcome? (Specific, measurable, time-bound)
- What's the smallest first step?
- Who benefits? Who pays the cost?

**Output:** Clear problem statement + success metric.
**Abort if:** User can't articulate a specific goal → RECOMMENDATION: REJECTED (gather more info first).

### Lens 2: Technical Feasibility (Coding Lens)
**Perspective:** Can we actually build/deliver this?

- Complexity: S (hours) / M (days) / L (weeks) / XL (months)
- Dependencies: what exists vs needs building
- Risks: architecture constraints, performance, data migration, security
- Effort: rough hours estimate with confidence level (high/medium/low)
- Testing strategy: how do we verify it works?
- Integration points: how does this connect to existing systems?

**Output:**
```
Feasibility: FEASIBLE / CONSTRAINED / BLOCKED
Complexity: [S/M/L/XL]
Effort: [hours]
Confidence: [high/medium/low]
Key risks: [list + mitigation for top 2]
```
**Abort if:** BLOCKED by fundamental constraint (e.g., "requires 10 years of R&D") → RECOMMENDATION: REJECTED.

### Lens 3: Cost/Benefit (Finance Lens)
**Perspective:** Is this worth doing?

- Upside: revenue, time saved, risk reduced, learning value
- Cost: time, money, opportunity cost, attention drain
- Risk-adjusted return: upside × probability - cost × probability
- Alignment: does this match current priorities and strategy?
- Alternatives: is there a cheaper way to achieve the same outcome?

**Output:**
```
ROI: POSITIVE / NEUTRAL / NEGATIVE
Payback: [timeline or N/A]
Priority: [High/Medium/Low relative to other initiatives]
Recommendation: PROCEED / HOLD / REJECT
```
**Abort if:** Negative ROI with no strategic justification → RECOMMENDATION: REJECTED.

## Synthesis & Decision

After analyzing all three lenses sequentially, generate a decision:

```
═══════════════════════════════════════════════════════
PROJECT: [Name]
═══════════════════════════════════════════════════════

FROM LENS 1 (Intent):
  GOAL: [From Lens 1]
  SUCCESS METRIC: [Measurable]
  REASON USER NEEDS THIS: [Key insight]

FROM LENS 2 (Feasibility):
  Feasibility: FEASIBLE / CONSTRAINED / BLOCKED
  Complexity: [S/M/L/XL]
  Effort: [hours] (confidence: [high/medium/low])
  Key risks: [top 2 + brief mitigation]

FROM LENS 3 (Cost/Benefit):
  ROI: POSITIVE / NEUTRAL / NEGATIVE
  Payback period: [timeline or N/A]
  Strategic alignment: [High/Medium/Low]

FINAL DECISION: APPROVED / CONDITIONAL / REJECTED

IF APPROVED:
  Success criteria: [clear, measurable definition of done]
  Phase 1: [What + deliverable] — estimate X hours
  Phase 2: [What + deliverable] — estimate Y hours
  Next step: [One concrete action to start NOW]
  Checkpoint: [When to assess progress]

IF CONDITIONAL:
  Condition: [What must happen for approval]
  Action: [How to remove the blocker]
  Re-assess: [When]

IF REJECTED:
  Reason: [Why it fails one or more lenses]
  Alternative: [What to do instead, if anything]
═══════════════════════════════════════════════════════
```

## Rules

- **Sequential, not parallel:** Lens 1 → Lens 2 → Lens 3. Don't skip ahead.
- **Abort early:** If any lens identifies a blocker, stop and recommend REJECTED or CONDITIONAL.
- **No multi-agent faking:** You analyze from three perspectives, you don't simulate three agents.
- **Concise and decisive:** This should take 5-10 minutes, not 30. Output is a DECISION, not brainstorm.
- **Mode context matters:** In fin mode, emphasize ROI; in coding mode, emphasize feasibility; in chat mode, emphasize user need clarity.
- **Write once, decide once:** Each lens is evaluated once, not revisited. Trust your analysis.
