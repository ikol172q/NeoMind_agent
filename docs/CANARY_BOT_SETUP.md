# Canary Bot Setup — Zero-Downtime Self-Evolution

**Status:** Infrastructure landed. Requires a one-time user setup
(create a second Telegram bot, add its token to `.env`, start the
canary container) before the pipeline can run end-to-end.

**Design doc:** `plans/TODO_zero_downtime_self_evolution.md`
**Orchestrator module:** `agent/evolution/canary_deploy.py`
**Compose service:** `neomind-canary` (profile `canary`)

---

## Why a canary bot

Today, `EvolutionTransaction.commit()` + `supervisorctl restart` takes
the production bot offline for 5-15 seconds. During that window real
users see silence, and if the new code fails `verify_pending_evolution`
on reboot the downtime can compound.

With a canary bot:

1. The proposed change deploys to **@neomindagent_test_bot first** (a
   completely separate Telegram bot you create via @BotFather).
2. The Telethon validator (see `tests/qa_archive/plans/2026-04-10_telegram_validation_v1.py`)
   runs the `gate_b3` or `gate_final` subset against the canary bot.
3. Only after the validator reports PASS does the production container
   restart. Production users never see a broken build.

If the canary FAILs, production is never touched — the orchestrator
rolls back the canary only.

---

## One-time setup

### 1. Create the test bot

1. Open Telegram and DM **@BotFather**.
2. Send `/newbot`.
3. Pick a display name (e.g. `NeoMind Canary`).
4. Pick a username ending in `bot` (e.g. `neomindagent_test_bot`).
5. Copy the token BotFather hands back — looks like `1234567890:AbCdEf...`.

### 2. Add the token to `.env`

Open `/Users/paomian_kong/Desktop/NeoMind_agent/.env` and add:

```
# Second Telegram bot used by the canary deployment pipeline.
# DO NOT reuse your production TELEGRAM_BOT_TOKEN here.
TELEGRAM_TEST_BOT_TOKEN=<paste the new token from @BotFather>
```

**Important:** keep this separate from `TELEGRAM_BOT_TOKEN`. The canary
container reads `TELEGRAM_TEST_BOT_TOKEN` and maps it into its own
`TELEGRAM_BOT_TOKEN` env inside the container.

### 3. Tell the validator which bot to hit

Edit `~/.config/neomind-tester/telethon.env` and add:

```
TG_CANARY_BOT_USERNAME=@neomindagent_test_bot
```

(Keep `TG_BOT_USERNAME=@neomindagent_bot` as-is — that's your
production bot and the tester still defaults to it. Only the canary
flow flips to the test bot via the env variable
`NEOMIND_TESTER_TARGET=canary`.)

### 4. Start the canary container

```
cd /Users/paomian_kong/Desktop/NeoMind_agent
docker compose --profile canary up -d neomind-canary
```

The container:
- Mounts the same live source tree as production (so self-edits
  propagate instantly to both).
- Uses an **isolated** `neomind-canary-data` volume for
  `/data/neomind`, so canary chat history / SQLite state doesn't
  leak into production.
- Sets `NEOMIND_CANARY=1` in env — application code already branches
  on this to use `provider-state.canary.json` instead of the shared
  production state file.

Verify:

```
docker ps --filter name=neomind-canary
docker exec neomind-canary supervisorctl status neomind-agent
```

Should show RUNNING.

### 5. Smoke-test the preflight check

```
cd /Users/paomian_kong/Desktop/NeoMind_agent
.venv/bin/python -c "
from agent.evolution.canary_deploy import CanaryDeployer
d = CanaryDeployer()
ok, msg = d.preflight()
print('preflight:', ok, msg)
"
```

Should print `preflight: True preflight ok`. If it reports the canary
container is not running, re-check step 4. If it reports the token is
empty, re-check step 2 and recreate the container with
`docker compose --profile canary up -d --force-recreate neomind-canary`.

---

## End-to-end pipeline (programmatic)

Once preflight passes, any self-evolution can use the canary
orchestrator:

```python
from agent.evolution.transaction import EvolutionTransaction
from agent.evolution.canary_deploy import CanaryDeployer

with EvolutionTransaction(reason="add /foo command") as txn:
    txn.apply("agent/integration/telegram_bot.py", new_content)
    ok, msg = txn.smoke_test()
    if not ok:
        raise RuntimeError(msg)

    deployer = CanaryDeployer()
    ok, msg = deployer.preflight()
    if not ok:
        raise RuntimeError(f"canary preflight: {msg}")

    canary = deployer.deploy_and_verify(txn, validator_subset="gate_b3")
    if not canary.ok:
        # Production is untouched. Rollback the canary-side change
        # via the transaction.
        raise RuntimeError(f"canary FAIL at {canary.stage}: {canary.message}")

    txn.commit()
    prod = deployer.promote_to_prod(txn)
    if not prod.ok:
        raise RuntimeError(f"prod deploy FAIL: {prod.message}")
```

The `validator_subset` argument picks which Telethon scenario set
the canary runs. Available subsets live in
`tests/qa_archive/plans/2026-04-10_telegram_validation_v1.py` and
include `gate_0`, `gate_b3`, `gate_b5`, `gate_b6`, `gate_final`.

- **Small changes** (one file, low risk): `gate_b3` (~20 min).
- **Large changes** (multi-file, slash-command surface): `gate_final`
  (~45 min).

---

## Trouble-shooting

- **`canary container not running`**: run step 4 again. If docker
  reports the service name is unknown, re-check that your
  `docker-compose.yml` contains the `neomind-canary` service (it was
  added in commit `TBD` in the canary-bot-setup series).

- **Canary bot never joins Telegram**: check the token with a direct
  curl:
  ```
  curl https://api.telegram.org/bot<TELEGRAM_TEST_BOT_TOKEN>/getMe
  ```
  Should return JSON with `"ok":true` and the bot's username.

- **Validator FAIL on gate_b3 right after starting canary**: the
  canary bot history is empty, so scenarios that depend on prior
  state (e.g. `/history` showing N messages) will fail. Use
  `NEOMIND_VALIDATOR_SKIP_HISTORY_PROBES=1` or start the canary with
  a short warm-up conversation first.

- **Production restarted unexpectedly**: the `promote_to_prod` path
  only runs `docker exec neomind-telegram supervisorctl restart
  neomind-agent`. If you see unexpected restarts check
  `restart: unless-stopped` on `neomind-telegram` and look at
  supervisord's own log for the trigger.

---

## Rollback criteria

If the canary pipeline reaches `promote_to_prod()` and production
then fails `verify_pending_evolution()`, the existing post-restart
rollback path applies — `EvolutionTransaction.rollback()` resets the
git state to the pre-transaction tag and the production container
auto-restarts a clean version. This is the same path used before
the canary existed, so it's battle-tested.

For canary-only failures (the happy path for catching bugs), the
deployer returns a failure `CanaryResult` and leaves cleanup to the
caller — typically `txn.rollback(reason=canary.message)`.
