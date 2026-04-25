# Reference: Karpathy "I really am mostly programming in English now" (Dec 2025)

**Source**: https://x.com/karpathy/status/2015883857489522876
**Date**: Dec 2025
**Pulled**: 2026-04-25 via threadreaderapp (X.com requires auth)

## Core observation

Workflow shift Nov→Dec 2025: from "80% manual+autocomplete coding,
20% agents" to the inverse. Karpathy describes it as "I really am
mostly programming in English now."

## The crucial diagnosis (one sentence that matters most)

> LLMs still make "subtle conceptual errors" similar to junior
> developers. They "make wrong assumptions on your behalf and just
> run along with them without checking."

This is the failure mode behind almost every LLM hallucination /
mis-execution incident. The model:

1. Receives a prompt with implicit assumptions
2. Picks ONE interpretation silently
3. Runs as if that interpretation is correct
4. Produces output that's confident and possibly wrong

The user typically only notices when the output is wrong AND
specific enough to trip the user's own check. When the output is
wrong in a way the user doesn't immediately notice, the error
propagates.

## What this means for prompt engineering

The fix is structural, not motivational:

- **Telling the model "be careful" doesn't work** — model doesn't
  know which step is the trap.
- **Telling the model "state assumptions first" works** — surfacing
  the assumption gives the user (or another check) a chance to
  intervene before the model commits.
- **Telling the model "tool-call before claiming"** also works for
  cases where the trap is "running on memory instead of fresh data".

## Other points from the thread (less actionable, recorded for context)

- "Coding feels more enjoyable because drudgery is removed and what
  remains is the creative part."
- Worry about manual-coding skill atrophy.
- Future of "10X engineers" — generalists with LLMs may catch up to
  specialists.
- 2026 will be "high energy year" as industry adapts to crossed
  thresholds in agent coherence.

## Two takeaways for NeoMind prompt design

**Takeaway 1**: The strongest single anti-hallucination move is
**externalize the assumption before acting**. NeoMind's prompts
should require the agent to surface its assumption when answering
anything that depends on agent state, recent events, or live data.

**Takeaway 2**: Programming in English requires *more* precision in
English, not less. The system prompt is itself a piece of English
"code" that describes the agent's behavior — its load-bearing rules
must be unambiguous, falsifiable, and free of implicit assumptions.
A prompt that says "don't hallucinate" is itself making a wrong
assumption (that the model knows when it's about to hallucinate).
A prompt that says "every fact must trace to a, b, or c" is
falsifiable — the model can self-check.
