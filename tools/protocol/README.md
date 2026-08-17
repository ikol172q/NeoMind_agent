# Protocol conformance

`validate_pi_messages.mjs` checks messages produced by
`agent/integration/pi_server.py` against **pi's own TypeBox schemas**, in a
clone of `badlogic/pi-mono`.

This is not redundant with `tests/test_pi_server.py`. Those assert what we
believe the protocol requires; this asserts what pi requires. On the first run
they disagreed on five points, and every disagreement would have reached a real
client:

| we produced | pi requires |
|---|---|
| one shape for session metadata and snapshot | two different ones, with `sessionName` on the smaller |
| `{type, name, status}` for a tool | a transcript item: `role`, `toolCallId`, `content`, `timestamp`, `isError` |
| no `queuedSteer` / `queuedSteerCount` | both required — without them a client cannot attach at all |
| `model: "deepseek-v4-flash"` | `{provider, id}` |
| `phase: "busy"` | `idle \| turn \| compaction \| branch_summary \| retry` |

The last one only appears *after* a prompt, so the session would have looked
fine until the user said something.

## Running it

    git clone --depth 1 https://github.com/badlogic/pi-mono.git /tmp/pi-mono
    cd /tmp/pi-mono && npm install --no-save typebox@1.3.7
    cp <repo>/tools/protocol/validate_pi_messages.mjs .
    <repo>/.venv/bin/python <repo>/tools/protocol/emit_pi_samples.py > /tmp/pi_samples.json
    node --experimental-strip-types validate_pi_messages.mjs /tmp/pi_samples.json

Re-run it when `pi_server.py` changes shape, and when pi releases a new
protocol version. pi's `server` package calls itself experimental and "may
change or be removed without notice", so a break here is expected eventually —
better found by this script than by a client that silently stops attaching.
