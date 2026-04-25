# Reference: 第一性原理 (First Principles thinking)

**Source**: classical (Aristotle), modern revival via Elon Musk;
recurring theme in Karpathy's work.

## What it is

Reasoning from foundational truths — atoms, not analogies.

> "Boil things down to the most fundamental truths and reason up from
> there." — paraphrased Musk on rocket-cost reasoning.

The opposite is **reasoning by analogy**: "this is similar to X, so
treat it like X." Analogy is fast but inherits X's hidden assumptions.

## The procedure (3 moves)

### 1. Identify the question's substrate

What's the actual question, stripped of how it was phrased?

- "Why is rocket fuel expensive?" → "What does rocket fuel actually
  cost as raw materials?"
- "How do I fix this auth bug?" → "What is the exact failure mode and
  what behavior would be correct?"
- "Why is the model hallucinating AAPL price?" → "Did the model
  actually NOT call the tool, or did my detector miss the call?"
  *(The 2026-04-25 anti-hallucination session — answer was the
  detector, not the model.)*

### 2. Identify load-bearing assumptions

What is being TAKEN AS GIVEN in the question or its accepted framing?

- "Standard practice is to..." — is the standard actually based on
  current constraints?
- "We've always done it this way..." — what changed since "always"?
- "The model must be hallucinating because..." — what data would
  distinguish a real hallucination from a detection failure?

### 3. Build up from what's left

After stripping assumptions, what's the minimal correct path?

- Cheaper rocket fuel: source raw materials directly, skip the
  vendor markup. (Musk's actual move with SpaceX.)
- Auth bug fix: read the failure log, identify the exact assertion
  that fails, fix that line. Skip "best-practice" rewrites.
- Hallucination diagnosis: query the ground-truth backend
  (chat_history.db) to see if the tool was actually called, before
  blaming the model.

## Why it matters for prompt design

LLMs are **analogy machines by default**. Their training is
"this looks like a million similar things, so respond like the
average of them." This is FAST and OFTEN RIGHT — but it's the wrong
mode for:

- **Diagnostic questions** — where what looks similar may be the
  trap. (My 6 rounds chasing AAPL hallucination.)
- **Novel system constraints** — where the "best practice" was set
  for different conditions.
- **Verification** — where pattern-matching is exactly the failure
  mode.

A first-principles habit in the agent's prompt:

> Before answering anything that depends on a fact about a specific
> system / data / state — query the substrate. Don't pattern-match
> to similar questions you've seen.

## Counterpart: when NOT to use first principles

First principles is expensive. For routine work — formatting code,
writing boilerplate, answering "how do I print to stdout in Python"
— pattern matching is correct and faster. The judgment call:

- **Pattern matching**: routine, well-bounded, low-stakes-if-wrong
- **First principles**: novel, ambiguous, high-stakes-if-wrong, or
  pattern-matching has already failed once

For NeoMind: most user chats are routine. But ANY claim about agent
state, system internals, or live data should drop into first-
principles mode — query the substrate, don't analogize.
