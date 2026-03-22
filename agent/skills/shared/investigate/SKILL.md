---
name: investigate
description: Systematic root-cause debugging — reproduce, bisect, test hypotheses, fix with confidence
modes: [chat, coding, fin]
allowed-tools: [Bash, Read, WebSearch, Edit]
version: 1.1.0
---

# Investigate — Root Cause Analysis

You are the investigator. Your mission: find the ROOT CAUSE, not just fix the symptom.

## Workflow

### 1. Reproduce the Bug
- Gather complete description: symptoms, timing, affected users/code paths
- For CLI bugs: write command that triggers it
- For UI bugs: open browser with `/browse` and follow exact reproduction steps
- For data bugs: dump the actual values, don't assume
- Take evidence (screenshots, logs, error traces)

### 2. Bisect: Narrow Down to Minimal Failing Case
- If code change triggered it: `git bisect` to find the exact commit
- If intermittent: collect multiple reproductions — is there a pattern?
- Create minimal reproducible example: smallest code/data that shows the bug
- Eliminate confounds: isolate the single failing component

### 3. Read Source Code + Logs
- Read the ENTIRE stack trace from top to bottom
- Read the function that failed + its callers
- Check error logs, console output, network requests
- Track data flow: where does it come from? Where should it go?
- Look for recent changes in that area

### 4. Form Hypothesis → Test It
- Based on evidence, form 2-3 testable hypotheses
- Rank by likelihood
- For each hypothesis, state: "If this is true, I'd see..."
- Design a minimal test that proves/disproves it
- Run the test and observe result (don't guess)

### 5. Fix + Verify + Add Regression Test
- Fix the cause (not the symptom)
- Verify the fix resolves the original reproduction
- Run related tests to check for side effects
- Write a regression test that would catch this bug in the future

## Rules

- **Read before guessing**: Always read code/logs/traces first. Never theorize without evidence.
- **3-hypothesis limit**: If 3 hypotheses fail, stop and ask for more context.
- **No assumption cascades**: Each step must be verified before proceeding.
- **Evidence always**: Screenshots, logs, console output — show your work.

## Per-Personality

- **chat**: Investigate factual claims, fact-check research, debug user problems
- **coding**: Debug code, trace data flow, bisect regressions, write regression tests
- **fin**: Investigate why prices moved, trace data discrepancies, backtest failures
