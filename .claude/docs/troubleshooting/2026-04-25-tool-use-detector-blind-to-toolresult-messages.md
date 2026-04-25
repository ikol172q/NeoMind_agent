# Tool-use detector that only checks visible reply text is blind by design

**WHEN**: writing an automated suite that checks "did the agent invoke a tool?"
to validate anti-hallucination prompts. Specifically, when working with
NeoMind's agentic loop where tool results are persisted as
`role=user` messages with `<tool_result>` envelopes.

## Wrong assumption

> "If the bot really called `finance_get_stock`, its Telegram reply will
> be prefixed with `✅ **finance_get_stock**` (the same way `WebSearch`
> results show up with `✅ **WebSearch**`). So I can detect tool use by
> regex-matching the reply text."

## What actually happens

`finance_get_stock` (and most `finance_*` tools registered via
`register_finance_tools()`) get their results injected back into the
conversation as `role=user` messages with this shape:

```
<tool_result>
tool: finance_get_stock
status: OK
output: |
  AAPL Apple Inc. $271.06 (-0.87%) via yfinance
metadata: {"ok": true, "symbol": "AAPL", "price": 271.06, ...}
```

These messages are **persisted in `chat_history.db :: messages`** (so
the LLM sees them on its next turn and can use the data) but are
**invisible in the Telegram UI**. The bot's user-facing reply digests
the data into a clean prose answer:

```
AAPL 现价 $271.06 (-0.87%, -2.37)
- 今日区间: $269.65 – $273.06
- 市值: $3.98T | PE: 34.35
```

There is **no `✅ **finance_get_stock**` prefix** in the visible reply.
Reply-text-only detectors think no tool was called.

## Why this matters

The 2026-04-25 anti-hallucination tuning session looked at this exact
output and concluded the bot was hallucinating $271.06 from training
memory. Multiple iterations of prompt tightening (TRAINING-DATA NUMBER
LOCKDOWN, STOP-READ-FIRST opener, /think on) all failed to fix it.
The "model-level limit" was attributed to deepseek-v4-flash.

**That diagnosis was wrong.** The bot was correctly calling the tool
the whole time. `chat_history.db` had 22 messages with
`<tool_result>` + `tool: finance_get_stock` + the exact $271.06 from
yfinance. The price was real (Friday close), the call was real, the
tool was wired correctly.

The detector blindspot wasted 6 rounds of prompt engineering on a
non-existent problem.

## Right approach

Detect tool use from THREE sources, not one:

1. **Reply-text markers** — covers WebSearch, Bash, Read, etc. that
   surface `✅ **ToolName**` in the user-facing reply.
2. **Docker logs** — sometimes captures `[agentic_loop] tool_call ...`
   traces, but unreliable (depends on supervisord stdout routing).
3. **`chat_history.db`** ground truth — query messages with
   `content LIKE '<tool_result>%'` and `created_at` within the test
   window. If a `<tool_result>` row exists for the right time, the
   tool was called. Period.

Implementation in `tools/eval/anti_hallucination/suite.py`:

```python
def _query_recent_tool_calls(max_age_seconds: int = 120) -> list[str]:
    """Read chat_history.db for recent <tool_result> entries — ground truth."""
    cmd = ["docker", "exec", "neomind-telegram", "python", "-c", f'''
        import sqlite3
        conn = sqlite3.connect("/data/neomind/db/chat_history.db")
        rows = conn.execute("""
            SELECT content FROM messages
            WHERE content LIKE '<tool_result>%'
            AND datetime(created_at) > datetime('now', '-{max_age_seconds} seconds')
            ORDER BY id DESC LIMIT 5
        """).fetchall()
        for r in rows: print(r[0][:300])
    ''']
    ...
```

After this fix, fin suite went from 8/9 (with aapl-price stuck) to
**9/9 stable**.

## Generalized lesson

When validating agent behavior:

- **The visible reply is a digested artifact**, not a record of work
  done. The agent may call tools, query DBs, run sub-agents — none of
  which need to appear in the reply text.
- **Backend state is ground truth**: SQLite tables, log files,
  filesystem changes, network captures.
- **Reply-only detectors over-attribute "hallucination"**: when the
  test says "no tool used" but the bot's answer is too specific to be
  confabulated, suspect the detector before suspecting the model.

Cost of skipping this lesson: 6 rounds of prompt engineering, 1 plan
doc with a wrong "model-level limit" conclusion, and a lingering
suspicion that deepseek-v4-flash can't follow instructions.

## See also

- Original anti-hallucination tuning plan: `plans/2026-04-25_anti-hallucination-tuning.md`
- Suite code: `tools/eval/anti_hallucination/suite.py`
- chat_history schema: `agent/services/chat_store.py`
- Tool registration: `agent/tools/finance_tools.py :: register_finance_tools()`
