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

## Real connection (`drive_with_pi_client.mjs`)

Schema validation checks the messages you remember to export. Driving the
server with **pi's own client library** checks the ones you forgot, and the
behaviour a schema cannot express. It found two things the validator could not:

- **every result needs a `command` field**, and `detach` returns `sessionId`
  rather than `session` — the exported samples contained no response envelope
  at all, so nothing had ever checked them;
- **`create` implies attach.** The client takes an exclusive lease on the id
  `create` returns and never sends a separate `attach`, so a session that comes
  back detached fails the *next* call with "Session … is not attached". The
  message was perfectly valid and the meaning was wrong.

    # terminal 1
    .venv/bin/python tools/protocol/pi_demo_server.py 8791

    # terminal 2, inside a pi-mono clone
    npm install --ignore-scripts
    (cd packages/protocol && npm run build)
    cp <repo>/tools/protocol/drive_with_pi_client.mjs .
    node --experimental-strip-types drive_with_pi_client.mjs 8791

Expected, with the demo server's scripted turn:

    connect       → serverId: neomind | protocol: 1
    createSession → id: neomind-1
    prompt        → phase: turn
    progress      → assistant_delta(thinking), assistant_delta(text) x3, item_started, item_finished
    streamed text → "你好 from NeoMind"
    steer         → refused: steer is not supported...
    abort         → phase: idle

## Status: pi's own CLI cannot connect yet (upstream)

Everything on our side works. What is missing is on pi's:

- `pi client --connect unix:///path` exists **in source** —
  `src/cli/experimental/commands/client.ts`, with `parseTransportAddress`
  accepting `unix://` only — but `experimentalCli` (the command tree that
  registers it) has **no caller**. Its only reference in the whole repository
  is its own unit test, and the shipped `bin` points at `dist/cli.js`, which
  never reaches it. `PI_EXPERIMENTAL=1` does not change that; the option is
  rejected as unknown because the command was never mounted.
- Checked against upstream commit `d3ab2af` (v0.84.2). pi's `server` package
  calls itself "Experimental… may change or be removed without notice", so this
  is a feature still being built rather than something we are holding wrong.

So the protocol is proven and the client path is not available. When upstream
mounts that command — or publishes `@earendil-works/pi-client` so another
client can use it — this should work with no change on our side:

    .venv/bin/python tools/protocol/pi_demo_server.py /tmp/neomind-pi.sock
    pi client --connect unix:///tmp/neomind-pi.sock

Until then `drive_with_pi_client.mjs` is the real-client evidence: it drives
our server with pi's own `PiClient`, which is their code doing the handshake,
framing, request correlation and event dispatch.

## ACP over stdio — ready here, blocked upstream (tested 2026-08-17)

**Correction.** This section previously said DSH could drive NeoMind today.
It cannot yet, and finding that out required running it rather than reading
its docs.

DSH's `subagent-acp` provider spawns a configured command and speaks ACP over
its stdio, which is exactly what `agent/integration/acp_stdio.py` serves — and
the entry point is verified against a real ACP client below. What does not work
is the DSH side:

    npm i -g @deepseek-ai/dsh                              # v0.1.0-rc.7, runs
    dsh plugin --profile headless add @deepseek-ai/dsh-subagent-acp

    dsh: warning: @deepseek-ai/dsh-subagent-acp declares no dsh.bundle —
    installed as a plain dependency, not a profile layer

That warning is the whole story. The package is `0.0.1-rc.1` on npm with no
`dsh` field, so it installs but never activates. The `--patch` config appears
in `dsh --dump-config`, and the provider is never registered.

### DSH's model claimed the delegation happened

Asked to delegate, DSH answered:

    Delegated to the neomind subagent. Its reply:
    ```
    DELEGATION_PROOF
    ```

**No NeoMind process was ever spawned.** Proven by pointing `command` at a
shell that touches a file before exec'ing the real entry point — the file does
not exist after the run. The model produced the answer itself and narrated a
delegation that did not occur.

Worth stating plainly because it inverts the usual failure: the risk here was
not a test that lied about the system, but a *system* that lied about itself.
Any check for "is NeoMind wired in" has to be a side effect only NeoMind could
produce, never the text of the reply.

### Verified on our side

Verified by spawning it the way that provider does — subprocess, stdio,
`initialize` → `session/new` → `prompt`, collect `agent_message_chunk`, then
close stdin — with a **real model** behind it:

    initialize   → protocol 1
    new_session  → neomind-1
    prompt       → stop_reason: end_turn
    streamed     → 'ACP_STDIO_OK'
    usage        → 118 tokens
    shutdown     → exit 0

Reproduce:

    .venv/bin/python tools/protocol/drive_with_acp_client.py \
        "$(pwd)/.venv/bin/python" "$(pwd)"

### Configuring it in DeepSeek Harness

```yaml
- id: subagent-acp
  name: '@deepseek-ai/dsh-subagent-acp'
  config:
    providerName: neomind
    command: /absolute/path/to/NeoMind_agent/.venv/bin/python
    args: ['-m', 'agent.integration.acp_stdio', '--mode', 'coding']
    cwd: /absolute/path/to/NeoMind_agent
    permission: reject      # or allow_once — see below
```

`permission` matters. DSH auto-answers permission requests rather than asking a
human: `reject` refuses every tool, `allow_once` takes the first allow option.
NeoMind's ACP surface is `interactive=True` precisely because a client *can*
answer — with `reject` configured, that answer is always no, so the agent
behaves like the unattended surfaces. Choose deliberately.

### Why stdout discipline is the whole risk here

Stdout **is** the wire. A stray `print`, a logging handler defaulting to
`sys.stdout`, or a library banner lands inside a JSON-RPC frame and the client
reports a parse error naming nothing. `acp_stdio.py` pins logging to stderr
before constructing the agent — after would be too late, since
`logging.basicConfig` is a no-op once any handler exists.
