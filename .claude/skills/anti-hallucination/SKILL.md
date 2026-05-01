---
name: anti-hallucination
description: Use when filling structured data (yaml/json) with research, citing sources, or when the task involves "compress LLM training knowledge into facts". Triggers on research, fill yaml, cite sources, strategies, web research, training knowledge, fact-heavy data.
---

# Anti-hallucination rules for any agent filling fact-heavy data

This skill exists because of a real failure mode that already happened
in this codebase: a Phase 3 research subagent was asked to "research 36
investment strategies and fill docs/strategies/strategies.yaml".  It
generated 108 plausible-but-fake URLs and dozens of plausible-but-
unverifiable numeric claims (~70-80% expire worthless, max drawdown
~55%).  All deleted 2026-04-27.

The failure was structural: LLMs cannot distinguish "fact retrieved
from training" from "plausible token continuation".  No prompt
instruction like "be accurate" fixes this.  What fixes it is **never
asking an LLM to generate facts in the first place**.

## Hard rules

When you receive a task that involves filling structured data:

### 1. URLs in any source / citation field

MUST be either:
  - empty `[]`, OR
  - `raw://<sha256>` references to a RawStore blob the agent has
    actually fetched (via WebFetch / WebSearch tools, body stored
    via `agent.finance.raw_store.RawStore.add_blob()`).

NEVER paste a general-web URL you "remember from training".  Even if
it looks correct, it might 404 or have changed content.  An LLM
inventing a URL is the #1 hallucination failure mode.

### 2. Numeric claims in any free-text field

typical_win_rate, max_loss, feasible_at_10k_reason, narratives,
key_risks, and similar fields:

MUST be either:
  - qualitative only ("most expire worthless under typical
    conditions", "drawdowns can be severe"), OR
  - quoted with a `*_source` companion field pointing to a
    raw://<sha256> where the exact number appears verbatim.

NEVER invent a specific percentage, dollar value, or historical
number unless you have just fetched a source containing it.  A
plausible "~70-80%" with no citation is a trust violation.

### 3. Empty is honest

If you cannot cite a source for a claim, leave the field blank.
A blank field is a correct, honest signal; an invented number is
silent corruption that destroys downstream trust.

### 4. The "extract not generate" pattern

When LLM assistance is genuinely needed for a fact-heavy task, the
correct framing is:

  "Here are these specific bytes from RawStore (sha256 verified).
   Extract / summarise / classify the content of THESE BYTES."

NOT:

  "Tell me about quadruple witching" / "What's the typical win rate
   of a covered call strategy?"

The first lets the LLM transform real bytes; the second invites
training-knowledge regurgitation, which is hallucination by design.

## Operational checklist before submitting any structured-data PR

Before you commit:

- [ ] Every URL in the diff is either raw://<sha256> or empty list
- [ ] Every numeric claim in the diff is either qualitative or has
      a `*_source` companion pointing at a raw://blob
- [ ] You can locally re-derive every numeric claim from its cited
      blob's bytes (literal substring match works)
- [ ] If unsure about any specific cell, you left it blank rather
      than filled it with "best guess"
- [ ] You have run agent.finance.strategies.auditor.audit_strategy()
      on at least one entry and seen state=verified to confirm the
      auditor accepts your work

## Where the structural enforcement lives

Even if you ignore this skill, downstream guards will catch you:

- agent/finance/strategies_catalog.py:_normalise_provenance() —
  any entry without provenance.state is treated as unverified.
- agent/finance/strategies_catalog.py:is_trusted() — unverified
  entries are filtered out of L3-call prompts.
- agent/finance/lattice/strategy_matcher.py — refuses to attach
  strategy_match chips for unverified strategies.
- agent/finance/strategies/auditor.py — for any strategy claiming
  a numeric fact, the auditor cross-checks against the cited
  RawStore bytes via literal substring match.  LLM cannot fake it.

This skill exists so you don't trip those guards in the first place.

## Reference

- Failure case study:
  .claude/docs/troubleshooting/2026-04-27-strategies-yaml-hallucination.md
- Provenance state vocabulary:
  agent/finance/strategies_catalog.py (constant PROVENANCE_STATES)
