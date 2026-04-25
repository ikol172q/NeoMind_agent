# LLM pipelines: "validate-then-ship" is the only safe pattern

**Session:** 2026-04-23, Insight Lattice integrity self-check

## The pattern

In any pipeline where an LLM produces a structured artifact consumed
downstream, the LLM output MUST be gated by a deterministic validator
BEFORE anything else reads it. User-facing code never sees raw LLM
output; it sees (LLM output that passed the check) OR (deterministic
fallback).

Concretely for the Insight Lattice L2/L3:

```
  L2 narrative pipeline:
    LLM proposes → validator checks "narrative cites ≥1 number
                   present verbatim in member obs text" → if pass,
                   ship; if fail, fall back to deterministic template
                   and stamp `narrative_source = "template_fallback"`.

  L3 Toulmin call pipeline:
    LLM proposes up to N candidates → validator checks
      (a) required fields present
      (b) grounds reference existing theme_ids (no phantom)
      (c) warrant is not a tautology of the claim
      → if fail, drop with drop_reason ∈ spec.DROP_REASONS
      → MMR selects top-k from survivors
```

The invariant: the user never reads text the LLM chose to emit that
didn't clear a specific check. When there's nothing valid to ship,
ship nothing, not bullshit.

## WRONG

Accepting LLM output directly because "DeepSeek is pretty good":

```python
narrative = llm_call(prompt)["narrative"]
theme.narrative = narrative   # shipped as-is
```

Failure modes you WILL hit in production:
- LLM cites a number not in the evidence ("AAPL fell 42% yesterday" —
  but no member obs said 42). User believes it.
- LLM invents a theme_id in `grounds`. Downstream graph builder
  renders a broken edge pointing to nothing, or silently drops it.
- LLM writes "the thesis holds because the thesis holds". Looks
  profound; says nothing.
- LLM hallucinates a confidence/horizon enum value (`"maybe"`).
  Downstream type check crashes on the wire.

The "DeepSeek is pretty good" baseline catches ~95% of these. The
5% it misses are the exact ones that embarrass the product.

## RIGHT

```python
reply = llm_call(prompt)
sanitised, drop_reason, drop_detail = validator(reply, valid_theme_ids)
if sanitised is None:
    # Do not ship. Record why in trace for the UI to show.
    drop_trace(drop_reason, drop_detail)
    return deterministic_fallback()
return sanitised
```

Every drop reason is a bounded enum (`spec.DROP_REASONS` in this
codebase). The trace UI can list them alongside kept candidates.

## Three additional properties this pattern gives you

1. **Self-check over the live output is cheap.**
   Because every LLM field passed a deterministic check at generation
   time, you can re-run the same checks over stored output and
   always expect them to pass. Any failure means state has drifted
   (cache got stale, schema changed mid-deploy, spec constant was
   re-edited). A `/api/lattice/selfcheck` endpoint that runs each
   invariant live is a 20-line exercise, and the user can press
   a button in the UI to confirm "we haven't silently drifted".

2. **Snapshots are trustworthy without re-validating.**
   Archiving today's /calls payload to
   `<project>/lattice_snapshots/YYYY-MM-DD.json` is just a file
   write — no need to re-run validators at read time. Any stored
   snapshot is, by construction, a validated one.

3. **A bad LLM day doesn't silently corrupt the graph.**
   DeepSeek 503 / rate-limit / format drift → every candidate is
   dropped → L3 ships zero calls. The user sees "no high-conviction
   call today" instead of garbage.

## Tell — are you doing this?

Grep your LLM-adjacent code for:

- "Reply JSON only" style prompts followed by direct `reply["field"]`
  access with no intermediary parser + check.
- `try/except: return {}` around json.loads — silently passing
  malformed output.
- Narratives / summaries / claims that contain numbers, written by
  an LLM, shipped without a check that those numbers exist in the
  inputs.

Any of these is the same class of bug. Fix by inserting the
validator + fallback + drop_reason trace.

## Related entries

- `2026-04-23-ui-bug-ship-without-browser-test.md` —
  reproduce UI bugs with a real browser before editing.

## This codebase

Everywhere the lattice uses LLM output:
- `agent/finance/lattice/themes.py::_validate_llm_narrative`
- `agent/finance/lattice/calls.py::_validate_candidate` (returns
  `(sanitised, drop_reason, drop_detail)` tuple)
- `agent/finance/lattice/selfcheck.py` — live invariants re-run
  against stored output; UI shows pass/fail badge.

Any new LLM producer in this project MUST follow the same shape.
