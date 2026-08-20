# Passing your tests and passing theirs are different claims

**2026-08-16, Phase 7 (protocol adapters for ACP and pi).**

## What happened

Two adapters, written against schemas I had read. Both had complete unit test
suites. Both suites passed.

Then I ran the messages through **the other side's validator** — pi's own
TypeBox schemas, in a clone of its repo — and 4 of 7 message shapes were
rejected.

```
  ✓ ServerHello
  ✗ ServerSnapshot            must not have additional properties
  ✗ SessionSnapshot           must have required properties queuedSteer, queuedSteerCount
  ✓ TranscriptProgress_text
  ✗ TranscriptProgress_started    must have required properties role, content, timestamp
  ✗ TranscriptProgress_finished   must be equal to constant
```

Five distinct mistakes, every one of which would have reached a real client:

| I produced | the protocol requires |
|---|---|
| one shape for session metadata and snapshot | two different ones; the smaller calls the name `sessionName` |
| `{type, name, status}` for a tool | a transcript item: `role`, `toolCallId`, `content`, `timestamp`, `isError` |
| no `queuedSteer` / `queuedSteerCount` | both required — **a client cannot attach at all without them** |
| `model: "deepseek-v4-flash"` | `{provider, id}` |
| `phase: "busy"` | `idle \| turn \| compaction \| branch_summary \| retry` |

**The last one is the reason this entry exists.** `busy` is only set *after* a
prompt. A session would create fine, list fine, attach fine — and then every
snapshot sent from the moment the user typed something would be rejected. And
the error names no field, because the failure is inside a nested union:

```
  path=undefined value=undefined → must be object
```

## The rule

**For any cross-process or cross-language protocol, validate with the other
side's validator.** Your tests encode your reading of their schema. That is
precisely the thing in question.

Make it reproducible rather than a one-off:

```
tools/protocol/
  emit_pi_samples.py          # one sample of every message shape we emit
  validate_pi_messages.mjs    # checked against THEIR schemas, in THEIR repo
  README.md                   # what disagreed the first time, and why
```

Re-run it when your side changes shape and when they release a version. pi's
server package calls itself "Experimental… may change or be removed without
notice", so a break is expected eventually — better found by a script than by
a client that quietly stops attaching.

## The same failure in a different language

The ACP adapter had no foreign validator to run, so the equivalent discipline
was **constructing every model for real** and letting pydantic check it. Eight
guesses were wrong. Two mattered:

```python
# WRONG — pydantic drops a field whose type does not validate, and does not raise.
# The response looks perfect and reports zero tokens spent, forever.
schema.PromptResponse(stop_reason="end_turn", usage=usage_update(usage))

# RIGHT — PromptResponse wants Usage; UsageUpdate is the session-update type.
schema.PromptResponse(stop_reason="end_turn", usage=turn_usage(usage))
```

```python
# WRONG — right by accident. A denial is DeniedOutcome, which has no
# option_id at all, so the comparison happens to fail. It means nothing.
chosen = getattr(getattr(answer, "outcome", None), "option_id", None)
if chosen not in ("allow", "allow_always"): return None

# RIGHT — check the discriminator, then the option.
outcome = getattr(answer, "outcome", None)
if getattr(outcome, "outcome", None) != "selected": return None
```

## Discriminators are never hand-typed

Five `session_update` literals written by hand, one wrong (`"usage"` where the
schema says `"usage_update"`). Nothing catches that but a constructed object.

```python
def _tag(model):
    """The discriminator a model requires, read from its own schema."""
    args = typing.get_args(model.model_fields["session_update"].annotation)
    if not args:
        raise TypeError(f"{model.__name__}.session_update is not a Literal")
    return args[0]
```

A boundary test fails the build if a literal one reappears.

## Related

- `20260816-fixture-encoded-assumption.md` — the same family: a test that
  passes while measuring your own belief rather than the behaviour.
