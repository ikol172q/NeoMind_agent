# A fixture that encodes your assumption is worse than no test

**2026-08-16, Phase 5 (Telegram migration).**

## What happened

`ToolFinished` had no field saying a tool call was *refused* rather than
*failed*. Both renderers recovered it by matching on prose:

```python
# WRONG — cli/session_renderer.py and telegram_renderer.py both did this
reason = (event.error or "").strip()
if reason.lower().startswith("permission denied"):
    return f"[yellow]  ⊘ {event.tool_name}: {reason}[/yellow]\n"
return f"[red]  ✗ {event.tool_name}: {reason or 'failed'}[/red]\n"
```

The session sets `error` to the policy's own `denied_reason`:

```
tool not in session capability snapshot
```

No prefix. The check never matched. **Every denial on every surface drew as a
red ✗ crash for an entire phase**, and the model was shown a refusal styled as
an error — which is the difference between "you are not allowed" and "that
broke, try again".

Nineteen renderer tests passed the whole time, because every one of them was
written by the same person who wrote the check:

```python
# WRONG — the fixture asserts the assumption, not the behaviour
ev(ToolFinished, 0, tool_name="Write", success=False,
   error="Permission denied: tool not in session capability snapshot"),
```

That string is not produced anywhere in the runtime. The test proved the
renderer could format a string the renderer's author invented.

It surfaced only when a real Telegram client asked the bot to read a file and
the reply came back `🔧 Read ✗`.

## The rule

**When a test constructs the input to the thing under test, the fixture is a
claim about production that nothing has checked.** It is most dangerous exactly
where it feels safest: small, obvious-looking value objects.

Two defences, in order of strength:

1. **Make the distinction a field, not a string to parse.** `denied: bool` on
   the event. A renderer should never recover semantics by pattern-matching
   prose that another layer is free to reword.

   ```python
   # RIGHT
   if event.denied:
       return f"[yellow]  ⊘ {event.tool_name}: {reason}[/yellow]\n"
   ```

2. **For at least one test per contract, get the object from the real
   producer.** Drive the actual executor with the actual policy and assert on
   what comes out:

   ```python
   # RIGHT — the fixture cannot encode the assumption, because there is no fixture
   events = asyncio.run(collect(session.run_turn("run ls")))
   event = [e for e in events if isinstance(e, ToolFinished)][0]
   assert event.denied is True
   assert not event.error.lower().startswith("permission denied")  # pin the wording
   ```

   The second assertion matters: it pins that the *old* check would still fail,
   so if someone later reworks the message to begin with "Permission denied",
   the string check silently starts working again and hides that the field is
   the contract.

## Smell test

Before trusting a passing test, ask: **where did this input come from?**

- Copied from a real log or a real run → fine.
- Written from memory of what the producer emits → suspect. Go read the
  producer, or better, call it.
- Written to make the assertion pass → this entry.

## Related

- `20260807-*` — the same shape in the capability snapshot: `permission_level`
  was trusted without checking what the tools actually declare.
- Phase 5 also found that a whole Telethon test plan was green while exercising
  a code path the change never touched (`_handle_message` routes private DMs to
  `_handle_dashboard_agent` and returns). Same family: verify you are measuring
  the thing you changed, by looking for a marker only the new code emits.
