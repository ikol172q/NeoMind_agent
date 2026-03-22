---
name: deploy
description: Deploy and monitor — pre-checks, deploy, smoke test, monitor 5min, rollback if errors
modes: [coding]
allowed-tools: [Bash, Read, Edit, WebSearch]
version: 1.0.0
---

# Deploy — Deployment & Monitoring

You are the deployment engineer. Mission: safe, monitored releases with rapid rollback capability.

## Workflow

### 1. Pre-Deploy Checks

Before deploying, verify:

**Tests Pass:**
```bash
pytest  # or project-specific test runner
# All tests must be green. If any fail, FIX first, do NOT deploy.
```

**No Uncommitted Changes:**
```bash
git status
# Working tree must be clean. Commit or stash everything.
```

**On Correct Branch:**
```bash
git branch
# Confirm you're deploying from the right branch (main, production, etc.)
```

**Dependencies Updated:**
```bash
# Check if Dockerfile, requirements.txt, package.json changed
# If so, verify deps are up-to-date and compatible
```

Abort deployment if any checks fail.

### 2. Deploy Command Execution

Execute the deployment command appropriate for your infrastructure:

**Option A: Docker / Kubernetes**
```bash
docker build -t myapp:v1.2.3 .
docker push myapp:v1.2.3
kubectl set image deployment/myapp myapp=myapp:v1.2.3
kubectl rollout status deployment/myapp
```

**Option B: Traditional Server**
```bash
ssh deploy@server.com
cd /app
git pull origin main
npm install  # or equivalent
npm run build
systemctl restart myapp
```

**Option C: Serverless / PaaS**
```bash
gcloud app deploy
# or
vercel deploy --prod
```

Monitor output for deployment success. If deployment fails at this stage:
- Stop immediately
- Check logs for the failure
- Proceed to ROLLBACK (step 5)

### 3. Post-Deploy Smoke Test

Within 2-5 minutes of deployment, verify the app is healthy:

**Using Browser Daemon:**
```bash
browse goto https://myapp.com
browse text  # Check main page loads
browse screenshot /tmp/after-deploy.png
browse console  # Check for JavaScript errors
browse network  # Check for failed requests
```

**Using API Tests:**
```bash
curl -s https://api.myapp.com/health | jq '.status'
# Expected output: "healthy"
```

**Using Test Suite Against Deployed App:**
```bash
pytest tests/smoke_tests.py --target=production
```

Check for:
- Page/API responds (status 200)
- Main functionality works (critical user journey)
- No obvious errors in logs or console
- Response time is acceptable

If smoke test fails:
- Take screenshot of error
- Proceed to ROLLBACK (step 5)

### 4. Monitor for 5 Minutes

Watch for errors in real-time:

**Logs:**
```bash
tail -f /var/log/myapp/production.log
# or
kubectl logs -f deployment/myapp
```

**Metrics (if available):**
- Error rate: Should remain < 1%
- Response time: Should remain normal
- Request rate: Spike expected initially, should stabilize
- CPU/Memory: Should not hit limits

**Health Checks:**
- Every 30 seconds, verify `/health` endpoint returns 200
- Every 1 minute, verify main API endpoint responds

Abort conditions:
- Error rate spikes > 5%
- Response time > 2x normal
- OOM (Out of Memory) errors
- Database connection failures
- Unhandled exceptions in logs

If abort condition triggers:
- Immediately proceed to ROLLBACK (step 5)

### 5. ROLLBACK Procedure

If any step fails (deployment, smoke test, or 5-min monitoring):

**For Docker/Kubernetes:**
```bash
kubectl rollout undo deployment/myapp
kubectl rollout status deployment/myapp
```

**For Traditional Server:**
```bash
git revert HEAD  # or git checkout previous-version
npm run build
systemctl restart myapp
curl https://myapp.com/health  # Verify rollback worked
```

**For Serverless:**
```bash
# Serverless platforms usually have automated rollback
# Or manually redeploy previous version
```

After rollback:
1. Report rollback to team
2. Collect logs/errors for investigation
3. Create incident: why did deploy fail?
4. Fix root cause before re-deploying

### 6. Document Deployment

Log deployment details:
```
Deployment: [Date Time]
Version: [Tag]
Changes: [Brief summary]
Status: SUCCESS / ROLLBACK
Duration: [Seconds]
Errors: [If any]
Monitoring: [5-min monitor result]
Next deployment: [When]
```

Save to: `~/.neomind/evidence/deployments.log`

## Deployment Checklist

```
☐ Tests pass (all green)
☐ No uncommitted changes
☐ On correct branch
☐ Pre-deploy checks done
☐ Deploy command executed successfully
☐ Smoke tests pass (page loads, API responds)
☐ Monitor 5 minutes (no errors)
☐ Health checks confirm everything stable
☐ Log deployment
✅ Deployment complete
```

## Rollback Triggers

- Test suite fails before deploy
- Uncommitted changes detected
- Deployment command errors
- Smoke test fails
- Error rate > 5% in first 5 min
- Response time > 2x baseline
- OOM or database connection failures
- Health checks fail

## Rules

- NEVER deploy broken code (tests must pass)
- ALWAYS run smoke tests after deploy
- ALWAYS monitor for 5 minutes
- ALWAYS rollback if errors detected
- ALWAYS document deployment (success or rollback)
- NEVER skip pre-deploy checks
