# Long-running services bake the env they were started with

**Date**: 2026-04-19
**Tags**: env, launchd, llm-router, openclaw, moonshot

## Symptom

OpenClaw (`@your_bot`) returned `HTTP 401: incorrect_api_key_error`
on every message, model=kimi-k2.5 provider=moonshot. The exact same
moonshot key worked fine when curl'd directly. `~/.openclaw/agents/main/agent/auth-profiles.json`
had the correct key. `~/.zshrc` had the correct key. All visible state
looked right.

## Root cause — two layers

1. **OpenClaw routes moonshot through local router, not direct to vendor.**
   `~/.openclaw/agents/main/agent/models.json` has:
   ```json
   "moonshot": {
     "baseUrl": "http://host.docker.internal:8000/v1",
     "apiKey": "sk-any-key"
   }
   ```
   So OpenClaw's `auth-profiles.json` key is *never used* for LLM calls —
   the real authentication happens upstream at the LLM-Router.

2. **LLM-Router was started from a shell that had an earlier env bug.**
   `/Users/user/Desktop/LLM-Router/start.sh` snapshots
   `$MOONSHOT_API_KEY` into `.env.runtime` at startup, then sources it.
   The router was started when `.zshrc` had a concatenation bug that made
   `$MOONSHOT_API_KEY` empty, so `.env.runtime` never got the line. The
   running router process had `MOONSHOT_API_KEY=` (length 0) and forwarded
   moonshot requests with an empty `Authorization: Bearer ` header → 401.

## How to verify

```bash
# Does the running router actually have the key?
ps eww "$(cat /Users/user/Desktop/LLM-Router/.router.pid)" \
  | tr ' ' '\n' | awk -F= '/_API_KEY=/ {print $1, "<len="length($2)">"}'
# Expect: MOONSHOT_API_KEY <len=51>
# If len=0 → router was started with broken env; restart.
```

## Fix

```bash
# Fresh zsh re-sources .zshrc before running start.sh
zsh -c 'source ~/.zshrc; cd ~/Desktop/LLM-Router && ./start.sh restart'
```

No code edits. No env hardcoding. Just restart with the correct env.

## General lesson

When a long-running background service routes API calls, the debugging
surface is: `service's snapshotted env → service's forwarded auth → vendor`.
Fixing `.zshrc`, `auth-profiles.json`, or `models.json` does **not** fix a
service that was started before your fix landed. Always confirm the
**running process's** env (`ps eww <pid>`) — not just what your shell or
config files claim.

This applies to launchd services, nohup'd daemons, and `start.sh`-style
wrappers that write `.env.runtime` snapshots: all of them bake env at
start time and ignore later shell changes.
