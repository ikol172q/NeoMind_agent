# Never print API keys in Bash output

**Date**: 2026-04-12
**Category**: security / secrets

## Symptom
Debugging env propagation — I echo `$DEEPSEEK_API_KEY` or `env | grep
API_KEY` to "see what's set", exposing real keys to session transcript.
User has to rotate keys after the leak.

## WRONG
```bash
echo $DEEPSEEK_API_KEY                          # prints real key
env | grep API_KEY                              # prints ALL keys
docker exec container env | grep API            # same
echo "Key: $DEEPSEEK_API_KEY"                   # same
```

## RIGHT
```bash
# Presence + length check (no value)
echo "DEEPSEEK_API_KEY: ${DEEPSEEK_API_KEY:+set (${#DEEPSEEK_API_KEY} chars)}${DEEPSEEK_API_KEY:-MISSING}"

# Just presence
test -n "$DEEPSEEK_API_KEY" && echo "DEEPSEEK_API_KEY set" || echo "DEEPSEEK_API_KEY MISSING"

# Just length  
echo "DEEPSEEK_API_KEY length: ${#DEEPSEEK_API_KEY}"

# First/last few chars (if you need to identify which key, cautious)
echo "DEEPSEEK_API_KEY: ${DEEPSEEK_API_KEY:0:8}...${DEEPSEEK_API_KEY: -4}"
```

## WHY
Bash output goes to:
1. The user's terminal (visible immediately)
2. The Claude Code session transcript (persisted)
3. Anthropic's debug logs (may be retained)

Even if the user rotates immediately, the old key remains in the
transcript forever. Keys rotated once are easier to compromise if the
transcript is ever leaked.

For env propagation debugging, presence + length is enough. You don't
need the value to verify it's set.

## Exception
If you truly need the value (e.g. passing it to a specific subprocess
that can't read env), write it to a file with `umask 077` first, then
reference the file:
```bash
umask 077
printf '%s' "$DEEPSEEK_API_KEY" > /tmp/_dk
# use /tmp/_dk
shred -u /tmp/_dk 2>/dev/null || rm /tmp/_dk
```
