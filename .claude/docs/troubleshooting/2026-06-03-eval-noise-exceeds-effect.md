# A self-improvement gate needs statistical power, or it optimizes noise

**Discovered**: 2026-06-03, Fin Harness Evolution Loop — `fin_evolve.gated_apply`.

## Symptom

The reward-delta gate (baseline rollout → apply change → verification rollout
→ keep iff reward didn't regress) gave contradictory verdicts on the *same*
change across two runs:

- gate1: before **0.05** → after **0.15** (Δ +0.1, kept)
- gate2: before **−0.125** → after **−0.225** (Δ −0.1, kept on the boundary)

The **baseline alone** moved from +0.05 to −0.125 between runs. The
run-to-run noise was larger than the effect being measured.

## Root cause

The eval used `runs_per_intent=2` (4 samples) over a **bimodal** per-turn
reward (a turn scores ~1.0 if it complies, −0.5 if it fails a rule). With so
few samples from a high-variance, bimodal distribution, the sample mean is
dominated by which bin the few draws landed in — not by the prompt change.
Two extra noise sources compounded it:

- rollout `answer()` calls run at `temperature=0.3` (stochastic) — the same
  query gives different replies/rewards each run.
- `min_delta=-0.1` with `delta >= min_delta` kept a change at exactly the
  boundary, so a non-improvement read as "kept."

Net: the gate had **no statistical power** — it was making keep/revert
decisions on noise. A loop like this will "learn" toward randomness.

## Fix (direction, not yet fully implemented)

Reduce measurement variance before trusting the gate:

1. **Deterministic eval** — run measurement rollouts at `temperature=0`
   (greedy) so the same query is reproducible.
2. **Paired comparison** — score the *same* query under old vs new prompt and
   compare per-query deltas (the seed builder already emits identical queries
   per run; pair them explicitly instead of comparing means of separate runs).
3. **More samples / repeats per query**, and a `min_delta` band wider than the
   measured noise floor (estimate noise from repeated identical runs first).
4. Consider a **less bimodal reward** for gating (e.g. fraction of rules
   passed, 0..1) so small improvements are visible.

## Why it matters / general rule

**Before a metric is allowed to gate self-modification, measure its noise
floor and make sure the effect you're gating on is bigger than it.** An
automated improvement loop with an underpowered evaluator doesn't just fail to
help — it actively drifts toward whatever the noise favors. Mechanical
correctness of a change (here: the prompt block was correctly placed in the
body, `block_before_begin=True`) is separate from, and must not be confused
with, a measured improvement.
