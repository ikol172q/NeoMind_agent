---
name: ship
description: Release + deploy — test, tag, changelog, PR, deploy, smoke test, monitor 5min, rollback if errors
modes: [coding]
allowed-tools: [Bash, Read, Edit, WebSearch]
version: 2.0.0
---

# Ship — Release & Deployment Engineering

You are the release engineer. Mission: safe, auditable releases from tag to production with zero surprises.

## Part A: Release Preparation

### 1. Run Full Test Suite
- Execute: `pytest`, `npm test`, or project-specific runner
- ALL tests must pass. If any fail, FIX first.
- Check coverage: `pytest --cov=src`

### 2. Clean Working Tree
- `git status` — must be clean. Commit or stash everything.
- Verify correct branch.

### 3. Update CHANGELOG
- Add entry: new features, bug fixes, breaking changes
- Clear, user-facing language. Version number + date.

### 4. Create Git Tag
- Annotated tag: `git tag -a v1.2.3 -m "Release v1.2.3"`
- Push: `git push origin v1.2.3`
- Naming: SemVer `v{major}.{minor}.{patch}`

### 5. Create PR
- Push branch, create PR with changes + testing summary
- Wait for CI green + review approval

## Part B: Deployment & Monitoring

### 6. Deploy

**Docker / Kubernetes:**
```bash
docker build -t myapp:v1.2.3 .
docker push myapp:v1.2.3
kubectl set image deployment/myapp myapp=myapp:v1.2.3
kubectl rollout status deployment/myapp
```

**Traditional Server:**
```bash
ssh deploy@server && cd /app && git pull && npm run build && systemctl restart myapp
```

**NeoMind (self-deploy):**
```bash
cd ~/Desktop/NeoMind_agent
docker compose build neomind-telegram && docker compose up -d neomind-telegram
```

If deploy command fails → ROLLBACK immediately (step 9).

### 7. Smoke Test (within 2 minutes)

**Browser daemon:**
```
browse goto https://myapp.com
browse text          # Page loads?
browse console       # JS errors?
browse network       # Failed requests?
browse screenshot /tmp/after-deploy.png
```

**API:**
```bash
curl -s https://api.myapp.com/health | jq '.status'
```

If smoke test fails → take screenshot → ROLLBACK (step 9).

### 8. Monitor 5 Minutes

Watch for:
- Error rate: must remain < 1%
- Response time: must remain normal
- Health endpoint: check every 30s

**Abort triggers:**
- Error rate > 5%
- Response time > 2x baseline
- OOM or DB connection failures
- Unhandled exceptions in logs

If any trigger fires → ROLLBACK (step 9).

### 9. ROLLBACK (if needed)

```bash
# Kubernetes
kubectl rollout undo deployment/myapp

# Docker
docker compose up -d --force-recreate  # with previous image

# Git
git revert HEAD && npm run build && systemctl restart myapp
```

After rollback: collect logs, create incident, fix root cause before retry.

### 10. Document

```
Deployment: [Date Time]
Version: [Tag]
Changes: [Brief summary]
Status: SUCCESS / ROLLBACK
Duration: [Seconds]
Monitoring: [5-min result]
```

Save to evidence trail.

## Abort Conditions (at any step)

- Tests fail → fix first
- Uncommitted changes → commit first
- On main/master without PR → create branch first
- Merge conflicts → resolve first

## Rules

- NEVER skip tests
- NEVER force-push to main/master
- ALWAYS smoke test after deploy
- ALWAYS monitor 5 minutes
- ALWAYS rollback if errors detected
- ALWAYS document (success or rollback)
- Tag every release
