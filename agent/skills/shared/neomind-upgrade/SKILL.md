---
name: neomind-upgrade
description: Self-upgrade with backup, diff review, safe rebuild, and rollback on failure. Preserves state across all modes.
modes: [chat, coding, fin]
allowed-tools: [Bash, Read, Edit, WebSearch, Grep]
version: 2.0.0
---

# NeoMind Upgrade — Self-Improvement Protocol

You are the release manager for NeoMind itself. Periodically check for upgrades, show what's changed, and apply them safely with full state backup and rollback capability.

**Critical Principle:** State preservation across modes. Backup personal memory, vault, preferences, and evidence trail before any upgrade.

## Workflow

### 1. Pre-Upgrade State Backup

Before checking for commits, backup all user state:

```bash
# Backup personal memory and vault
tar -czf ~/.neomind/backups/backup-pre-upgrade-$(date +%Y%m%d-%H%M%S).tar.gz \
  ~/.neomind/evolution/ \
  ~/.neomind/shared_memory.db \
  ~/.neomind/vault/ \
  ~/.neomind/evidence/ \
  ~/.neomind/logs/ \
  ~/.neomind/config/

# Backup git state
git stash  # preserve any local changes
git rev-parse HEAD > ~/.neomind/backups/pre-upgrade-commit.txt
```

Report: "State backed up to `~/.neomind/backups/backup-pre-upgrade-[timestamp].tar.gz`"
Include backup filename in upgrade log for traceability.

### 2. Check for New Commits on origin/main

```bash
git fetch origin main
git log --oneline -10 origin/main ^HEAD
```

If no new commits:
- Report "Already on latest version"
- Exit

If new commits exist:
- Display commit list and their summaries
- Proceed to step 3

### 3. Show Changelog Diff

```bash
git diff HEAD...origin/main -- CHANGELOG.md
```

Display to user:
- What features were added?
- What bugs were fixed?
- What breaking changes?
- Dependencies changed?
- Security patches?

Present a summary of the changes, asking: "Should I proceed with upgrade?"

### 4. User Confirms Upgrade

Wait for explicit user confirmation: "yes", "proceed", "upgrade", etc.

If user says no or doesn't confirm:
- Report "Upgrade cancelled"
- Restore any stashed changes: `git stash pop`
- Exit

If user confirms:
- Proceed to step 5

### 5. Safe Git Pull

```bash
git pull origin main
```

If pull fails (conflicts):
- Show conflict files
- Restore stashed changes: `git stash pop`
- Ask user to resolve manually
- Exit with backup location noted

If pull succeeds:
- Report "Pull successful"
- Proceed to step 6

### 6. Run Full Test Suite

```bash
pytest tests/ -v --tb=short  # or project-specific test command
```

If tests fail:
- Show failing test output
- Proceed to ROLLBACK (step 8)

If tests pass:
- Report "All tests passed"
- Proceed to step 7

### 7. Rebuild & Verify

If `Dockerfile` exists:
```bash
docker compose build --no-cache
docker compose up -d
sleep 5
curl http://localhost:PORT/health || echo "Health check failed"
```

If build/startup fails:
- Show error output
- Proceed to ROLLBACK (step 8)

If build succeeds and health check passes:
- Report "Rebuild successful, service health OK"
- Proceed to step 9

### 8. SAFE ROLLBACK ON FAILURE

If any step fails (pull conflicts, tests fail, docker build fails, health check fails):

```bash
# Rollback code
git reset --hard <pre-upgrade-commit>  # from backup file
git clean -fd
git stash pop  # restore any local changes

# Restore full state from backup
tar -xzf ~/.neomind/backups/backup-pre-upgrade-[timestamp].tar.gz -C ~

# Restart service
docker compose down
docker compose build
docker compose up -d
```

Report:
- What failed (with log excerpt)
- Rollback completed successfully
- Backup restored location
- Suggest: "Please investigate failure and report issue"
- Exit

### 9. Post-Upgrade State Verification

Verify state continuity across modes:
```bash
# Check vault integrity
test -f ~/.neomind/vault/.checksum && md5sum -c ~/.neomind/vault/.checksum

# Verify evolution files accessible
ls ~/.neomind/evolution/retro-*.md | wc -l

# Spot check recent evidence trail
tail -20 ~/.neomind/logs/$(date +%Y-%m-%d).jsonl
```

Report: "State verification passed" or "State verification: [findings]"

### 10. Log Upgrade to Evidence Trail

Create upgrade record:
```
Upgrade: [date]
From: [old commit hash]
To: [new commit hash]
Backup: [backup filename]
Changes: [summary]
Tests: PASSED
Docker: [rebuilt]
State: [verified/issues]
Status: SUCCESS
Next Review: [date + 7 days]
```

Save to: `~/.neomind/evidence/upgrades.log`

Append structured entry to: `~/.neomind/logs/$(date +%Y-%m-%d).jsonl`

## Safety Guardrails

- **Backup first:** Always backup state before touching code
- **Test before deploying:** Don't run untested code in production
- **Rollback capability:** Keep commit hash and backup filename for quick recovery
- **Manual confirmation required:** User must explicitly approve
- **State preservation:** All personal memory, vault, preferences survive upgrade
- **Health checks:** Verify service is responding after rebuild
- **Log every upgrade:** Full audit trail with before/after commit hashes
- **Diff review:** Show what changed before applying

## Version Tracking

NeoMind uses semantic versioning:
- `v1.2.3` = major.minor.patch
- Breaking changes → major version bump
- New features → minor version bump
- Bug fixes → patch version bump

Current version location: Check with `git describe --tags`

## Mode-Aware Upgrade Behavior

**Chat mode:**
- Report upgrade status in conversational style
- Preserve conversation history and learned preferences

**Coding mode:**
- Report technical details (commit hashes, test counts, build times)
- Verify all dev tools still functional

**Finance mode:**
- Verify trade data integrity and market connections
- Extra security checks on API key accessibility

## Rules

- NEVER auto-upgrade without user confirmation
- NEVER upgrade if tests fail
- ALWAYS rollback if something breaks
- ALWAYS backup before upgrade
- ALWAYS restore state after successful upgrade
- Log every upgrade attempt (success, failure, or rollback)
- If rollback is needed, alert user to manual investigation
- Check for upgrades weekly (or on-demand via `/neomind-upgrade` command)
- Keep last 5 upgrade backups in `~/.neomind/backups/` (delete older ones)
