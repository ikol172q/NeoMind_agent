# Verify env completeness BEFORE docker compose recreate

**Date**: 2026-04-12
**Category**: docker / production safety

## Symptom
`docker compose up -d --force-recreate <service>` crashes the recreated
container because `.env` on disk has different (or missing) values vs
the running container's in-memory env. Production breakage.

## WRONG (2026-04-12)
```bash
docker compose build neomind-telegram       # new image
docker compose up -d neomind-telegram        # recreate with current .env
# → container crashes: "TELEGRAM_BOT_TOKEN not set!"
# because .env had the token commented out at some point, but the
# running container had it from the shell env at start time
```
This took production Telegram bot down for minutes until user provided
the real token.

## RIGHT
Before ANY recreate or rebuild:
```bash
# Snapshot the current container's env (ground truth)
docker exec <service> env | grep -E "TOKEN|API_KEY|PASSWORD|SECRET" | sort > /tmp/pre-env.txt

# Snapshot what will be loaded on recreate
grep -E "TOKEN|API_KEY|PASSWORD|SECRET" .env | grep -v "^#" | sort > /tmp/disk-env.txt
docker compose config | grep -A 2 "environment:" | head -30 >> /tmp/disk-env.txt

# Diff
diff /tmp/pre-env.txt /tmp/disk-env.txt
```

If anything in `pre-env.txt` is missing from `disk-env.txt`, you're
about to break production. Fix the source (`.env`, `docker-compose.yml`
`environment:` block, or shell env) BEFORE recreate.

## Better long-term fix
Put keys in `~/.zshrc` as shell env vars, reference them in
`docker-compose.yml` `environment:` block without values:
```yaml
environment:
  - DEEPSEEK_API_KEY    # inherits from shell env
  - ZAI_API_KEY
  - TELEGRAM_BOT_TOKEN
```
This avoids writing secrets to `.env` at all. When running
`docker compose`, `source ~/.zshrc` first if Claude's bash env needs refresh.

## WHY
Live containers have a snapshot env captured at start time. Between
start and recreate:
- `.env` may have been edited (comments added, values removed)
- The shell that started the container may have had env vars no longer
  in any file
- Docker compose env inheritance may have changed

Recreate loads CURRENT state, not preserved state. If current state is
incomplete, the new container is broken.

## Recovery
If you break production this way and can't find the original values:
- Check `~/.zshrc` for exported vars
- Check `~/.config/<app>/` for app-specific credential files
- Check git history of `.env` (if tracked)
- Ask the user — they usually have the real values somewhere
