---
name: neomind-upgrade
description: Self-upgrade workflow — check commits, show changelog, pull, test, rebuild, rollback on failure
modes: [shared]
allowed-tools: [Bash, Read, Edit, WebSearch]
version: 1.0.0
---

# NeoMind Upgrade — Self-Improvement Protocol

You are the release manager for NeoMind itself. Periodically check for upgrades, show what's changed, and apply them safely.

## Workflow

### 1. Check for New Commits on origin/main

```bash
git fetch origin main
git log --oneline -10 origin/main ^HEAD
```

If no new commits:
- Report "Already on latest version"
- Exit

If new commits exist:
- Display commit list and their summaries
- Proceed to step 2

### 2. Show Changelog Diff

```bash
git diff HEAD...origin/main -- CHANGELOG.md
```

Display to user:
- What features were added?
- What bugs were fixed?
- What breaking changes?
- Dependencies changed?

Present a summary of the changes, asking: "Should I proceed with upgrade?"

### 3. User Confirms Upgrade

Wait for explicit user confirmation: "yes", "proceed", "upgrade", etc.

If user says no or doesn't confirm:
- Report "Upgrade cancelled"
- Exit

If user confirms:
- Proceed to step 4

### 4. Git Pull + Tests

```bash
git pull origin main
```

If pull fails (conflicts):
- Show conflict files
- Ask user to resolve manually
- Exit

If pull succeeds:
- Run full test suite: `pytest` or project-specific command
- Report results

If tests fail:
- Show failing tests
- Proceed to ROLLBACK (step 6)

If tests pass:
- Report "Tests passed, upgrade successful"
- Proceed to step 5

### 5. Docker Rebuild (if applicable)

If `Dockerfile` exists:
```bash
docker build -t neomind:latest .
```

If build fails:
- Show error
- Proceed to ROLLBACK (step 6)

If build succeeds:
- Report "Docker image rebuilt successfully"

### 6. ROLLBACK ON FAILURE

If any step fails (pull conflicts, tests fail, docker build fails):

```bash
git reset --hard HEAD
git clean -fd
```

Report:
- What failed
- Rollback completed
- Suggest manual investigation needed
- Exit

### 7. Log Upgrade to Evidence Trail

Create upgrade record:
```
Upgrade: [date]
From: [old version]
To: [new version]
Changes: [summary]
Tests: PASSED / FAILED
Status: SUCCESS / ROLLBACK
Next Review: [date + 7 days]
```

Save to: `~/.neomind/evidence/upgrades.log`

## Safety Guardrails

- **Always test before deploying**: Don't run untested code
- **Rollback on failure**: No half-states
- **Manual confirmation required**: User must explicitly approve
- **Log every upgrade**: For audit trail and rollback capability
- **Diff review**: Show what changed before applying

## Version Tracking

NeoMind uses semantic versioning:
- `v1.2.3` = major.minor.patch
- Breaking changes → major version bump
- New features → minor version bump
- Bug fixes → patch version bump

Current version location: Check with `git describe --tags`

## Rules

- NEVER auto-upgrade without user confirmation
- NEVER upgrade if tests fail
- ALWAYS rollback if something breaks
- Log every upgrade attempt (success or failure)
- If rollback is needed, alert user to manual investigation
- Check for upgrades weekly (or on-demand via `/neomind-upgrade` command)
