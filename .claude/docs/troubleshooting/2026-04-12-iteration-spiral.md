# After 3 failed fix attempts, switch to diagnostic

**Date**: 2026-04-12
**Category**: fix-loop discipline

## Symptom
Test fails. I patch. Test fails again. I patch again. After 5+ iterations
I realize I've been spraying fixes without understanding the root cause.

## WRONG (2026-04-12 — S01 went through v1 → v17)
- v1: baseline fail
- v2: fix A
- v3: fix B (a different theory)
- v4: revert B, try C
- v5: C broke v2's fix, add both
- ...
- v10: lost track of what was changed vs baseline
- v17: eventually stumbled onto the real root cause

Each iteration:
- ~5 minutes of runner + capture + judge
- Context bloat (v1's output, v2's output, ...)
- Token cost

## RIGHT
After **3 failed fix attempts**:
1. **Stop** any further fix-execution agents
2. Dispatch a **diagnostic-only** agent with:
   - FULL failure history (all 3 attempts + their outputs)
   - Current file state (grep or Read relevant sections)
   - Explicit instruction: "Do not fix anything. Produce a root-cause
     analysis. List all hypotheses + which are ruled out by the
     failures so far."
3. Read the RCA carefully
4. Pick the hypothesis with highest evidence
5. Dispatch ONE more fix-execution agent targeting that hypothesis
6. If it fails too, that's iteration 5 — escalate to user

## WHY
Three failed fixes means the problem is not where I thought. Continuing
to patch without understanding becomes narrower and less informed each
iteration. The diagnostic step is essentially "step back and think" —
something subagents are better at than manager-in-the-loop debugging,
because subagents start fresh without accumulated bias.

Diagnostic agents are strictly cheaper than fix-spam because:
- They read files once, reason once, produce ONE report
- They don't run tests (which are the expensive part)
- Their output is ~300 words vs fix agents' edits + test cycles

## How to tell if you're in the spiral
- You can't remember what the previous iteration changed
- You're making changes based on "let's try X" not "X will fix Y because Z"
- The same FAIL pattern persists despite different fixes
- You catch yourself reverting previous changes

If any of these — STOP. Diagnostic agent.
