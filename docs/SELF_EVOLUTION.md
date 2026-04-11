# NeoMind Self-Evolution — Safe In-Process Code Modification

## Goal

NeoMind can add new features to itself based on user requests like:

> "把 https://github.com/remorses/playwriter 里的功能加进来"

…without going offline, without losing user state, with automatic rollback if anything breaks. Works in Docker now, ready for other environments later.

## Hard requirements (user-stated, non-negotiable)

These shape every design decision below. If you change one, the design changes.

| # | Requirement | Implication |
|---|---|---|
| 1 | New features must NEVER break old features | Full unit test suite is a mandatory pre-commit gate. Public API contract check on every commit. |
| 2 | Telegram bot must NEVER crash during self-modification | Validation runs in subprocess (shadow), the live process is untouched until validation passes. |
| 3 | Old version keeps serving until new version is fully validated | "Atomic switch": pre-restart shadow validation + post-restart in-process verify *before* polling starts. |
| 4 | Auto-rollback on any failure | Two rollback paths: pre-restart `git reset --hard tag`, post-restart same + recovery restart. |
| 5 | Detailed logging traces every change | Per-stage timing, JSONL audit log, restart history, intent file lifecycle. |
| 6 | The evolution machinery itself must be testable in CI | Unit tests for EvolutionTransaction lifecycle. Subprocess gates use real `pytest` so they catch real bugs. |

## Audit of existing infrastructure

NeoMind already has substantial self-modification machinery. This doc inventories what exists, identifies gaps for the use case above, and describes the additions needed.

### Already in place

| File | Purpose |
|---|---|
| `agent/evolution/self_edit.py` | `SelfEditor` — single-file edit pipeline: AST safety check, syntax validation, fork-process unit test, git commit, hot-reload, daily 10-edit limit, constitutional AI review (no removed try/except, no removed logging, no new non-allowlisted network calls) |
| `agent/evolution/self_restart.py` | `request_restart()` — graceful agent process restart via `supervisorctl restart neomind-agent`. Writes restart-intent file so the new process knows it was a self-restart |
| `agent/evolution/health_monitor.py` | HTTP health endpoint on :18791, periodic SQLite health checks, restart counter |
| `agent/evolution/watchdog.py` | Last-resort hang detection, forced restart |
| `agent/evolution/auto_evolve.py` | Scheduled health/audit/retro reports |
| `agent/evolution/integration_hooks.py` | AgentSpec + debate-consensus gate before edits land |
| `agent/evolution/skill_forge.py` | Generate new SKILL.md files |
| `agent/evolution/upgrade.py` | Higher-level upgrade orchestration |
| `agent/evolution/meta_evolve.py` | Meta-learning over evolution history |
| `Dockerfile` | git installed in image |
| `docker-compose.yml` | Live source mount `- .:/app` (host changes are immediate in container) |
| `supervisord.conf` | autorestart=true, startretries=5, separate processes for agent / health-monitor / watchdog / data-collector |

### Gaps for the playwright use case

| Gap | Why it matters |
|---|---|
| **Multi-file atomic apply** | Adding a feature like playwright touches 4-8 files (new module, registration, config, prompt, test). `SelfEditor` only does one file at a time with no transaction across them — if file 3 fails, files 1-2 are already committed |
| **Backward-compat regression gate** | `SelfEditor`'s subprocess test only runs the test file matching the changed module. It does NOT run the full suite, so a change that breaks an unrelated module's tests would pass through. Hard requirement #1 demands the full suite. |
| **Pre-restart shadow validation** | Right now: changes are applied to /app, then restart. The 10s gap during restart is exposed if the new code is broken (the bot can't come up). Need: spawn a parallel subprocess with the new code, run the FULL pre-restart gate there, only restart if all checks pass. The live process is untouched throughout. |
| **Telegram-bot dry-run validation** | The pre-restart smoke imports the changed file, but does NOT verify that `agent.integration.telegram_bot` still loads, that the Application class instantiates, or that one fake Update flows through a handler. A change to a peripheral file can break handler registration in non-obvious ways. |
| **Verify-before-polling gate** | After `supervisorctl restart`, the new process currently starts polling Telegram immediately. If the new code is broken, the broken bot consumes real user messages and produces garbage replies during the rollback window. Need: in-process smoke check BEFORE `application.run_polling()`. If the check fails, the broken process never serves any user. |
| **Auto-rollback after restart failure** | `SelfEditor` rolls back if the per-file test fails before commit. But if the test passes, restart happens, and the new code crashes after restart, we have no automatic "revert and restart again". |
| **External feature ingestion** | No pipeline for "read this GitHub repo → understand its API → port equivalent into NeoMind". Today the human must spec the changes |
| **Telegram-side UX** | No `/evolve` command. Self-edits happen silently (or via skill-forge). User has no way to say "add feature X" from their phone |
| **Conversation continuity** | Restart drops in-flight conversation context. Need to persist+rehydrate critical state across restarts |
| **Concurrent restart guard** | Two evolution requests in parallel could both trigger a restart and one would lose state |
| **Per-stage timing log** | Today there's a single APPLIED/ROLLBACK log line per file. Hard requirement #5 demands per-stage timing for audit ("how long did pytest take? did the canary actually run?"). |

## Architecture

### High-level flow (revised: atomic-switch design)

```
User (Telegram)                                                NeoMind (single live process)
─────────────                                                  ──────────────────────────────
  /evolve add playwright features from <github URL>
                                                         ───►  Acknowledge: "🛠 Researching, bot stays online"

                                                                ResearchPhase  (live process, async worker)
                                                                  • fetch the repo (read-only HTTP)
                                                                  • parse README + entry points
                                                                  • build a feature spec

                                                                PlanPhase  (live process)
                                                                  • diff current vs target
                                                                  • produce ordered file-edit list
                                                                  • emit dry-run summary

                                                                TransactionPhase  (live process)
                                                                  STAGE 1: git tag rollback-anchor
                                                                  STAGE 2: for each file: SelfEditor.propose_edit
                                                                            (per-file syntax+AST+constitutional gate)
                                                                            (any failure → rollback to STAGE 1 tag)

                                                                ValidationPhase  (subprocess SHADOW — live process untouched)
                                                                  STAGE 3: subprocess imports every changed module
                                                                  STAGE 4: subprocess runs FULL pytest tests/
                                                                            ⇒ catches regressions in OLD features
                                                                  STAGE 5: subprocess imports telegram_bot, instantiates
                                                                            Application, runs ONE fake Update through
                                                                            a handler (no real polling)
                                                                  STAGE 6: subprocess canary — call the new feature once
                                                                  → If ANY of 3..6 fail: rollback to STAGE 1 tag.
                                                                    The live bot is UNAFFECTED. No restart happened.
                                                                    User gets a "couldn't apply, here's why" reply.

                                                                CommitPhase  (live process)
                                                                  STAGE 7: write evolution_intent.json with notify_chat_id
                                                                  STAGE 8: git commit (audit trail)
                                                                  STAGE 9: send "🔄 Restarting in 3s..." to user

                                                                RestartPhase  (supervisord)
                                                                  STAGE 10: subprocess supervisorctl restart neomind-agent
                                                                  ── old process exits cleanly ──
                                                                  ── ~10s gap, Telegram queues messages ──

[NEW PROCESS BOOTS]                                             PostRestartPhase  (new process — verify BEFORE polling)
                                                                  STAGE 11: read evolution_intent.json
                                                                  STAGE 12: re-import every applied module IN-PROCESS
                                                                            (catches issues that subprocess missed —
                                                                             e.g. stale .pyc, sys.modules pollution)
                                                                  STAGE 13: run canary in-process
                                                                  STAGE 14: clear intent file
                                                                  ───────────────────────────────────────────────
                                                                  ⇒ If 12..13 PASS: start Telegram polling → bot online
                                                                  ⇒ If FAIL: do NOT start polling.
                                                                              git reset --hard <tag>
                                                                              schedule recovery restart
                                                                              old code comes back online ~10s later
                                                                              user notified of rollback

  ◄─── "✅ Added playwright. New tools: capture, scrape.
        Rollback: /evolve revert evolve-20260409-..."
```

**Atomic switch property:** the OLD code keeps serving the user until ALL of stages 1-6 (validation in subprocess) pass. The 10s restart gap is the ONLY window of unavailability, and even that gap only happens if validation passed — broken code never causes a restart.

### New module: `agent/evolution/transaction.py` (EvolutionTransaction)

```python
class EvolutionTransaction:
    """Multi-file atomic edit with snapshot/rollback.
    
    Wraps SelfEditor for safety guarantees but adds:
      - Git tag at start (rollback anchor)
      - Apply N files in order
      - Run cross-file smoke validation (not just per-file)
      - Spawn subprocess canary (test new code in isolation)
      - Persist a transaction record for post-restart verification
      - Auto-rollback if any phase fails
    """
    
    def __init__(self, reason: str, tag_prefix: str = "evolve"):
        self.reason = reason
        self.tag = f"{tag_prefix}-{datetime.now():%Y%m%d-%H%M%S}"
        self.editor = SelfEditor()
        self.applied_files: List[str] = []
        self.original_contents: Dict[str, Optional[str]] = {}
    
    def __enter__(self):
        # Snapshot: git tag the current HEAD as rollback anchor
        self._git_tag(self.tag)
        return self
    
    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None:
            self.rollback()
            return False  # propagate
    
    def apply(self, file_path: str, new_content: str) -> Tuple[bool, str]:
        """Apply one file. Records original for rollback."""
        path = self.editor.REPO_DIR / file_path
        original = path.read_text() if path.exists() else None
        ok, msg = self.editor.propose_edit(file_path, self.reason, new_content)
        if ok:
            self.applied_files.append(file_path)
            self.original_contents[file_path] = original
        return ok, msg
    
    def smoke_test(self) -> Tuple[bool, str]:
        """Cross-file smoke test:
        1. All applied modules import OK in subprocess
        2. ServiceRegistry instantiates
        3. NeoMindAgent imports
        """
        return _run_subprocess_smoke()
    
    def canary(self, importable_target: str) -> Tuple[bool, str]:
        """Spawn subprocess that imports + calls the new feature."""
        return _run_canary(importable_target)
    
    def commit(self) -> Tuple[bool, str]:
        """Final commit + write evolution-intent.json for post-restart verification."""
        intent = {
            "tag": self.tag,
            "reason": self.reason,
            "applied_files": self.applied_files,
            "smoke_test_target": getattr(self, '_smoke_target', None),
            "timestamp": _now_iso(),
        }
        EVOLUTION_INTENT_FILE.write_text(json.dumps(intent, indent=2))
        return self._git_commit_all()
    
    def rollback(self):
        """Reset working tree to the rollback tag."""
        subprocess.run(
            ["git", "reset", "--hard", self.tag],
            cwd=str(self.editor.REPO_DIR), check=False,
        )
        self.applied_files.clear()
```

### New module: `agent/evolution/post_restart_verify.py`

Runs in the **new** process right after `_check_restart_intent()` finds an evolution intent. Performs:

1. Import every file listed in `applied_files`
2. Call the smoke target if specified
3. Probe Telegram API connectivity (if in telegram mode)
4. If any step fails: `git reset --hard <rollback_tag>` + `request_restart()` again
5. If all pass: send Telegram notification to the originating chat (if recorded in the intent file)

### New Telegram command: `/evolve`

In `agent/integration/telegram_bot.py`:

```python
async def _cmd_evolve(self, update, context):
    """Handle /evolve — user-initiated self-improvement.
    
    Forms supported:
      /evolve list                       → show last 10 evolutions
      /evolve revert N                   → roll back to evolution tag N
      /evolve add <feature description>  → research + plan + apply
      /evolve from <github URL>          → ingest external repo
    """
```

The `add` and `from` forms are the **interesting** ones. They:

1. Acknowledge the request (immediate "🛠 working on it" reply)
2. Run the research+plan phases in a worker task (not blocking other Telegram traffic)
3. Open an `EvolutionTransaction`, apply the file edits
4. On commit, attach the user's `chat_id` to the evolution intent
5. Trigger restart
6. Post-restart verifier reads intent, validates, posts result back to user via the saved chat_id

### Concurrency guard

A single `~/.neomind/evolution.lock` file. `EvolutionTransaction.__enter__` tries to acquire it (atomic create with O_EXCL). If it exists, another evolution is in progress — reject with "another evolution is in progress, try again in 60s".

## Safety properties

| Property | How enforced |
|---|---|
| **Bot never goes offline > 30s** | Only the `neomind-agent` process restarts, not the container. Telegram polling resumes within ~10s |
| **Original code always usable** | Pre-edit: git tag. Mid-edit failure: git reset to tag. Post-restart failure: same |
| **No silent corruption** | Every edit goes through `SelfEditor`'s syntax+AST+constitutional checks. Multi-file goes through subprocess smoke + canary |
| **Rate limit** | `SelfEditor.MAX_EDITS_PER_DAY = 10` still applies. Each file in a transaction counts. |
| **No infinite restart loop** | If post-restart smoke fails after rollback, no further restart is attempted. User is notified, manual intervention required |
| **Forbidden files protected** | `SelfEditor.FORBIDDEN_PATHS` includes `self_edit.py`, `health_monitor.py`, `watchdog.py`, `Dockerfile`, `docker-compose.yml`, `supervisord.conf`. EvolutionTransaction inherits this |
| **Audit trail** | Every transaction = git tag + git commit + JSONL log entry |
| **User notified of every action** | Telegram messages at: research start, plan ready, apply start, restart pending, restart complete, rollback if needed |
| **No side-effects to user data** | Transactions only touch source files under `/app`. SQLite databases under `/data` are untouched (and survive process restart by design) |

## Phased rollout

### Phase 1 — Safety primitives (this PR)
- `agent/evolution/transaction.py` with `EvolutionTransaction` class
- `agent/evolution/post_restart_verify.py` with the post-restart smoke gate
- Concurrency lock file
- Unit tests for the transaction lifecycle (apply → smoke → commit OR rollback)
- Manual end-to-end test with a no-op evolution (modify a docstring, restart, verify)

### Phase 2 — `/evolve` command + research+plan
- New Telegram command handler
- Research phase: clone or HTTP-fetch the GitHub repo, extract README + key files, summarize
- Plan phase: LLM produces an ordered file-edit plan
- Apply phase: walk the plan through EvolutionTransaction
- End-to-end test: a tiny external feature (e.g., add a one-liner Python utility from a tiny repo)

### Phase 3 — Real demo: playwright integration
- Use `/evolve from https://github.com/remorses/playwriter`
- Verify NeoMind reads the source, identifies the screenshot/scrape API, ports it as new tools, registers them, restarts, and the new tools work via Telegram

### Phase 4 — Polish
- `/evolve revert N` for manual rollback
- Evolution dashboard (`/dashboard evolutions`)
- Auto-revert on user complaint detection (frustration_detector)
- Multi-step evolution with intermediate checkpoints (for very large changes)

## Deliberate non-goals

These are NOT addressed by this design:

- **Real-time hot reload of telegram_bot.py** — supervisord restart is the primary mechanism. Hot reload only applies to leaf modules.
- **Cross-host evolution** — only Docker or single-host. Multi-host k8s evolution is out of scope.
- **Self-modification of safety boundaries** — `SelfEditor.FORBIDDEN_PATHS` is hard-coded and intentionally cannot be edited by self_edit (it would block its own modification anyway).
- **LLM-driven decision to evolve** — only user requests trigger `/evolve`. NeoMind doesn't decide to add features on its own. (Auto-evolution from `auto_evolve.py` does run, but only for prompt tuning and config drift, NOT for code changes.)
- **Cross-service rollback** — if an evolution writes to `/data/neomind/foo.db`, that DB write is not rolled back. Source file rollback only.

## Telegram-tester driven test plan

Once Phase 1+2 are in, validate via Telethon:

```python
TESTS = [
    {"send": "/evolve list", "wait": 5, "expect_any": ["evolution", "(none yet)"]},
    {"send": "/evolve add a no-op utility function called noop_xyz that returns True",
     "wait": 60,
     "expect_any": ["✅", "applied", "added"]},
    {"send": "after restart", "delayed_check": True, "expect_any": ["restarted", "ready"]},
    {"send": "/evolve revert 1", "wait": 30,
     "expect_any": ["reverted", "rolled back"]},
]
```

## Open questions for the user

1. Should `/evolve` be **opt-in per chat** (i.e., user must `/evolve enable` first) or always available?
2. Do we want a **"dry-run" mode** (`/evolve add --dry-run ...`) that produces the plan without applying?
3. How aggressively should the post-restart smoke gate retry? Currently: 1 attempt, then auto-rollback.
4. Should evolution events be posted to a dedicated Telegram **channel** (audit trail) in addition to the requesting chat?
