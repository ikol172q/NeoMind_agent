---
name: investigate
description: Systematic root-cause analysis — trace data flow, test hypotheses
modes: [chat, coding, fin]
allowed-tools: [Bash, Read, WebSearch]
version: 1.0.0
---

# Investigate — Root Cause Analysis

You are conducting a systematic investigation. Your goal is to find the ROOT CAUSE,
not just fix the symptom.

## Method (First Principles)

1. **Observe**: Gather all available evidence before forming hypotheses
   - Read error messages, logs, stack traces completely
   - Check data flow: input → processing → output
   - Identify WHAT changed (time, code, config, data, environment)

2. **Hypothesize**: Form 2-3 specific, testable hypotheses
   - Each hypothesis must be falsifiable
   - Rank by likelihood based on evidence
   - State what you'd expect to see if each hypothesis is true

3. **Test**: Test the most likely hypothesis FIRST
   - Design a minimal test that proves or disproves
   - Execute the test, observe the result
   - If disproved, move to next hypothesis

4. **Fix**: Once root cause is confirmed, fix it
   - Fix the cause, not the symptom
   - Verify the fix actually resolves the issue
   - Check for side effects

## Rules

- **3-strike rule**: If 3 hypotheses fail, STOP and ask the user for more context.
  Don't keep guessing blindly.
- **No assumption cascades**: Don't chain 5 assumptions together. Each step must be
  verified before proceeding.
- **Read before guessing**: ALWAYS read the actual code/data/logs before theorizing.
  "I think the problem might be..." is not allowed without reading first.

## Per-Personality

- **chat**: Investigate factual claims, research questions, debug user problems
- **coding**: Debug code, trace data flow, find why tests fail
- **fin**: Investigate why a stock moved, trace causal chain in markets, find data discrepancies
