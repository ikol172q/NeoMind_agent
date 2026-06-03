# Validate the reward verifier before trusting it to drive evolution

**Discovered**: 2026-06-02, Fin Harness Evolution Loop Phase 2b first mining run.

## Symptom

Every reward-labeled episode (real + synthetic rollouts) floored at **0.2**.
The miner ranked validator **Rule 3** ("价格缺少来源标注") as the #1 reward
drag — 11 occurrences across 3/3 episodes. It looked like the agent
systematically failed to cite price sources.

## Root cause — the verifier was wrong, not the agent

Reading the actual replies showed the flagged "prices" were not prices:

- `$40` extracted from **`$40T`** (Jensen's robot-market TAM)
- `$150` from **`$150B`** (NVDA Taiwan annual spend)
- `$100` / `$250` from **`$100k-$250k`** (a senator's *disclosed trade range*)

Two bugs in `response_validator.py`:

1. `PRICE_PATTERNS[0] = r'\$[\d,]+\.?\d*'` matched the numeric prefix and
   ignored magnitude/scale suffixes (T/B/M/k) and ranges — reading a bogus
   "$40" out of "$40T".
2. `SOURCE_PATTERNS` didn't include the agents' own inline citation format
   `[ev:<id>]` / `[fact:<id>]` (defined in `dashboard_agent/system.md`), so
   lines that *were* correctly cited still flagged as unsourced.

The agent was doing the right thing; the reward function lied about it.

## Fix

- Price regex negative lookahead to drop suffixed magnitudes:
  `r'\$[\d,]+\.?\d*(?![\d,.]*[KkMmBbTt%])'` ("$195.42 close" still matches —
  a space is not a suffix).
- Add `re.compile(r'\[(?:ev|fact):[^\]]+\]')` to `SOURCE_PATTERNS`.

Re-scoring the stored replies after the fix: Rule-3 warnings 4→0 / 3→0 / 4→0;
lookup reward 0.2→1.0, decision 0.2→0.4.

## Why it matters / general rule

**A reward signal is only as good as its verifier. Before letting a reward
function drive any self-improvement loop, validate the verifier itself —
otherwise the loop optimizes toward the verifier's bugs (reward hacking in
reverse: the model gets punished for being correct).** The loop's very first
job here was to prove the agent was right and the *reward* was wrong. The
miner's design helped: it flagged the ambiguous, highest-frequency pattern as
`investigate` rather than auto-drafting a prompt "fix" — which would have made
the agent worse to satisfy a broken metric.
