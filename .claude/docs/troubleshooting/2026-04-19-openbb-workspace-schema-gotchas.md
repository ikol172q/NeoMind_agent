# OpenBB Workspace custom-backend schema gotchas

**Date**: 2026-04-19
**Category**: OpenBB integration / HTTP contracts
**Severity**: silent UI failure — backend looks green, Workspace just doesn't render

## Context

During the 2026-04-19 session I built the `agent/finance/openbb_adapter.py`
layer so NeoMind speaks OpenBB Workspace's widget + Copilot protocols.
Docs at `docs.openbb.co/workspace/developers/*` are **incomplete** —
they show examples but don't strictly define the JSON Schemas. The
source of truth is the working code in
`github.com/OpenBB-finance/backends-for-openbb` (widgets) and
`github.com/OpenBB-finance/copilot-for-openbb` (agents).

Three distinct schema gotchas bit in one afternoon. Each produced a
different failure mode. None surfaced a useful error on the Workspace
side — they either rejected silently or showed a generic "Invalid
schema" / "An error has occurred" with no hint at which field.

---

## Gotcha 1 — `apps.json` is a JSON ARRAY, not a dict

### Symptom
Connecting the backend in Workspace → Connections page shows:
```
App errors: Unknown App
  [name]: Required
  [tabs]: Required
```

### WRONG
```python
@app.get("/apps.json")
def get_apps():
    return {
        "neomind_research": {"name": "…", "tabs": {…}},
        "neomind_paper_trading": {"name": "…", "tabs": {…}},
    }
```

### RIGHT
```python
@app.get("/apps.json")
def get_apps():
    return [
        {"name": "NeoMind · Research", "tabs": {…}, "groups": []},
        {"name": "NeoMind · Paper Trading", "tabs": {…}, "groups": []},
    ]
```

### Why
`widgets.json` IS dict-keyed (widget_id → definition), and it's natural
to extrapolate to apps. But apps.json in the canonical hello-world
template (`backends-for-openbb/getting-started/hello-world/apps.json`)
is a top-level array. Workspace iterates it as a list; when you pass a
dict, it iterates the keys as app objects and complains that strings
like `"neomind_research"` don't have `name` or `tabs`.

---

## Gotcha 2 — `agents.json` endpoints.query must be RELATIVE, not absolute

### Symptom
Copilot shows "An error has occurred. I couldn't process your
request at the moment." Server log reveals:
```
POST /openbb/openbb/query HTTP/1.1 404 Not Found
```
Double-prefix. Workspace is string-concatenating `base + query`, not
doing proper URL join.

### WRONG
```python
{
    "neomind_fin": {
        "endpoints": {"query": "/openbb/query"},  # absolute from host
        …
    }
}
```
When the user enters `http://127.0.0.1:8001/openbb` as the agent base,
Workspace produces `http://127.0.0.1:8001/openbb` + `/openbb/query`
= `http://127.0.0.1:8001/openbb/openbb/query` → 404.

### RIGHT
```python
{
    "neomind_fin": {
        "endpoints": {"query": "/query"},  # relative to agent base
        …
    }
}
```
Workspace concatenates to `http://127.0.0.1:8001/openbb/query` → hits
your `@router.post("/query")` under prefix `/openbb`. ✓

### Why
HTTP URL joining rules say a path starting with `/` is absolute-from-
host. OpenBB Workspace doesn't follow that — it's just
`base_url.rstrip('/') + query_path`. Treat `endpoints.query` as a path
fragment the frontend appends, and write it relative to your agent
base.

---

## Gotcha 3 — SSE event MUST be `copilotMessageChunk` with `{"delta": …}`

### Symptom
Chat request lands perfectly on the backend:
- `POST /openbb/query 200`
- `Worker 'fin-rt' claimed task task_…`
- Task completes with a real reply
But the Copilot UI shows **nothing** — not an error, just an empty
assistant bubble. Server-side everything is green, client just drops
the stream.

### WRONG
```python
yield {
    "event": "message",
    "data": json.dumps({"content": reply_text}),
}
```

### RIGHT
```python
yield {
    "event": "copilotMessageChunk",
    "data": json.dumps({"delta": reply_text}),
}
```

Or use the official helper (Python 3.10+ only):
```python
from openbb_ai import message_chunk
yield message_chunk(reply_text).model_dump()
```

### Why
`openbb_ai.models.MessageChunkSSE` hard-codes
`event = const("copilotMessageChunk")` and `data = {"delta": str}`.
Workspace's stream reader filters events by that exact literal name
and parses `data.delta`. Anything else is silently discarded — no
console error, no UI indicator. This failure mode is especially evil
because the HTTP 200 + full SSE body + server logs all look correct,
but the user sees nothing.

### Lesson
Any time Workspace accepts our HTTP response but shows no data, the
first suspect is an **event-name or JSON-key schema mismatch**, not
our logic. Pin the expected shape against openbb_ai's Pydantic
schemas:
```bash
pip install openbb-ai
python -c "from openbb_ai.models import MessageChunkSSE;
  print(MessageChunkSSE.model_json_schema())"
```

---

## Meta-lesson

OpenBB's docs describe *capabilities* but not *schemas*. For any new
OpenBB integration work:

1. **Clone the reference repos** first:
   - `OpenBB-finance/backends-for-openbb` — widget + app contracts
   - `OpenBB-finance/copilot-for-openbb` — agent contracts
2. **Copy verbatim** from a vanilla example, then mutate.
3. **Verify via Pydantic schemas** in the `openbb_ai` package if
   unsure about a shape.
4. When Workspace swallows responses silently, the bug is almost
   certainly an event-name or key-name mismatch, not your business
   logic.

All three failures cost roughly 15-45 minutes each of round-tripping
"why doesn't it render?" with the user. Total ~2 hours. Avoid next
time by reading the reference repos first.
