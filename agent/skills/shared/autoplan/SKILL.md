---
name: autoplan
description: Three-personality collaborative planning — chat clarity, coding feasibility, fin cost/benefit → action plan
modes: [shared]
allowed-tools: [Bash, Read, Edit, WebSearch]
version: 1.0.0
---

# AutoPlan — Three-Personality Collaborative Planning

You are orchestrating a three-step planning session where different perspectives synthesize into a clear action plan.
Goal: understand intent (chat), validate feasibility (coding), assess cost-benefit (fin), then DECIDE.

## Workflow

### Phase 1: CHAT — Understand True Intent

Use `/office-hours` methodology to understand what the user ACTUALLY needs.

**Questions:**
1. What is the current reality? (Facts, not hopes)
2. What is the real problem? (Not the symptom)
3. What exact outcome are you trying to achieve? (Specific, measurable)
4. What's the narrowest wedge? (Smallest first step)
5. What evidence supports this is worth doing?
6. Does this align with your 6-month goal?

**Output:** DECISION DOC with clear problem statement, goal, success metric

**Abort if:** User can't articulate a specific goal or metric for success

### Phase 2: CODING — Technical Feasibility Assessment

Evaluate: Can this be built? How complex? What are the technical risks?

**Assessment:**
- Complexity estimate (S/M/L/XL)
- Technical dependencies (what exists, what needs building)
- Risks: architectural constraints, performance issues, data migration
- Effort: rough engineering hours
- Integration points: what does this connect to?
- Testing strategy: how will we know it works?

**Output:** Technical Feasibility Report
```
Component: [Name]
Complexity: [S/M/L/XL]
Effort: [Hours]
Risks: [List with severity]
Dependencies: [List]
Testing: [Strategy]
Status: FEASIBLE / CONSTRAINED / BLOCKED
```

**Abort if:** BLOCKED (fundamental architecture issue, breaking dependency, tech debt too high)

### Phase 3: FIN — Cost/Benefit Analysis

Evaluate: What's the financial/business impact?

**Assessment:**
- **Revenue impact**: Will this increase revenue? By how much? Timeline?
- **Cost impact**: Engineering hours, infrastructure, ongoing maintenance
- **Opportunity cost**: What else could those hours build? What's the ROI comparison?
- **Risk-adjusted return**: Probability of success × Expected benefit
- **Payback period**: How long until ROI is positive?
- **Alignment**: Does this support the business goal?

**Output:** Business Case
```
Initiative: [Name]
Revenue Impact: [$ and timeline]
Cost: [$ for build + maintenance]
ROI: [%]
Payback Period: [weeks/months]
Risk Factors: [What could go wrong]
Recommendation: PROCEED / HOLD / REJECT
```

**Abort if:** Negative ROI, misaligned with business goals, or blocking factors

### Phase 4: Synthesize into Action Plan

If all three phases pass, create an integrated action plan:

**Action Plan Format:**
```
PROJECT: [Name]
──────────────────

GOAL: [Clear statement from Phase 1]

SUCCESS METRICS:
  - [Metric 1 with target]
  - [Metric 2 with target]

PHASES (sprints):
  Phase 1 (Week 1-2): [Sprint goal] → [Deliverables]
  Phase 2 (Week 3-4): [Sprint goal] → [Deliverables]
  Phase 3 (Week 5+):  [Sprint goal] → [Deliverables]

TECHNICAL APPROACH:
  Architecture: [High-level design]
  Key Components: [List]
  Testing Strategy: [Approach]
  Risks & Mitigations: [Risk → Mitigation]

BUSINESS CASE:
  Revenue Impact: [$ and timeline]
  Cost: [Total]
  ROI: [%]
  Payback: [Timeline]

DECISION: APPROVED / CONDITIONAL / REJECTED
CONDITIONS (if conditional): [List]

NEXT STEPS:
  1. [Immediate action]
  2. [Immediate action]
  3. [Review timeline]
```

## Rules

- **Each phase is sequential**: Don't skip to Phase 3 without Phase 1 clarity
- **Abort early**: If any phase identifies a blocker, stop and surface it
- **Output is a decision**: Not a brainstorm, not a wish list — a go/no-go decision
- **Synthesize, don't rewrite**: Use Phase 1-3 output directly in the plan
- **Risk-aware**: Flag assumptions and unknowns that need validation

## When to Use AutoPlan

- User has a vague idea and needs clarity
- Major initiative (multiple weeks of work)
- Cross-functional decisions needed
- High financial impact
- Technical risk assessment needed
