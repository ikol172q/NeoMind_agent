# TODO: Zero-downtime self-evolution + 100% fidelity CLI automation

**Status:** Design doc / future work — not implemented in this session.
**Priority:** High for the NeoMind self-evolution vision, but complexity exceeds the current session's scope. Requires user action (new Telegram bot token) and docker/supervisord config changes.

**Related:**
- `docs/SELF_TEST.md` — CLI tester+fixer methodology
- `docs/TELEGRAM_SELF_TEST.md` — Telegram tester+fixer methodology
- `agent/skills/shared/selftest/SKILL.md` — CLI skill
- `agent/skills/shared/telegram-selftest/SKILL.md` — Telegram skill
- `agent/evolution/transaction.py` — current EvolutionTransaction (restart-based)
- `agent/evolution/post_restart_verify.py` — post-restart verifier
- `plans/2026-04-10_slash-command-taxonomy-v5-with-validation.md` — validation framework

---

## Part 1 — Zero-downtime self-evolution (canary bot architecture)

### Problem

Currently, `EvolutionTransaction.commit()` + `supervisorctl restart neomind-agent` takes the production bot offline for ~5-10 seconds while the new code loads. During this window:

1. Users' messages land in Telegram's polling buffer (not lost, but unanswered).
2. The bot cannot respond, leading to "bot is silent" user experience.
3. If `verify_pending_evolution()` in the new process FAILS, the rollback triggers **another** ~5-10s restart before the original code is back. Net downtime: 10-20s.
4. Worst case (verification AND rollback both fail): the bot is stuck in a loop of bad restarts until a human intervenes.

User constraint from 2026-04-10 session:
> "必须具备自己测试自己功能然后改 code 然后 deploy 的能力，但注意：**不可以导致正在运行的 neomind 实例宕机**"

Translation: NeoMind must be able to self-evolve Telegram features, but **the production bot cannot go down** during the process.

### Solution — Canary bot + blue/green deployment

Architecture:

```
┌─────────────────────────────────────────────────┐
│         @neomindagent_bot (production)          │
│  Container: neomind-telegram                    │
│  Token: TELEGRAM_BOT_TOKEN                      │
│  Always serves real users                       │
│  Only restarts AFTER canary validates new code  │
└─────────────────────────────────────────────────┘
                       ↑
                       │ (restart only after canary PASS)
                       │
┌─────────────────────────────────────────────────┐
│       @neomindagent_test_bot (canary)            │
│  Container: neomind-canary                      │
│  Token: TELEGRAM_TEST_BOT_TOKEN                 │
│  Restarts FIRST on every evolution              │
│  Evolution tester hits this, not production    │
│  Production stays untouched until canary PASS   │
└─────────────────────────────────────────────────┘
```

### Implementation checklist

#### Prerequisites (user action required)

- [ ] **User creates a second bot via @BotFather** → `@neomindagent_test_bot` or similar
- [ ] **User adds `TELEGRAM_TEST_BOT_TOKEN=...` to `.env`** (note: NOT the production token)
- [ ] **User creates a separate Telegram account or uses the same account** for the canary tester (can reuse existing tester credentials)

#### Infrastructure changes

- [ ] **docker-compose.yml**: add a new service `neomind-canary` with:
  - Same image as `neomind-telegram`
  - Same mounts (live-mount `/app`, `/data/neomind`)
  - Different env: `TELEGRAM_BOT_TOKEN=${TELEGRAM_TEST_BOT_TOKEN}`
  - Different container name so they don't collide
  - Resource limits: half the CPU / memory of production (it only needs to handle tester traffic)

- [ ] **supervisord.conf inside both containers**: separate `neomind-agent` program per container (already the case if using separate containers)

- [ ] **Ensure the canary container's state directory is isolated**: `/data/neomind-canary/` instead of `/data/neomind/` so canary state (chat history, provider state, evolution intent) doesn't pollute production

- [ ] **Update `agent/services/provider_state.py`**: if `NEOMIND_CANARY=1` env is set, use a different state file path (`~/.neomind/canary-provider-state.json`) so canary edits don't leak into production state

#### Evolution pipeline changes

- [ ] **`agent/evolution/transaction.py`**: add `stage` field to `TransactionRecord`:
  ```python
  stage: Literal["canary", "prod"] = "canary"
  ```

- [ ] **New method `EvolutionTransaction.canary_deploy_and_verify()`**:
  1. Write intent file to `/data/neomind-canary/evolution/`
  2. Restart only the canary container: `docker exec neomind-canary supervisorctl restart neomind-agent`
  3. Wait for canary to boot and run `verify_pending_evolution`
  4. Run the **Telethon tester against the canary bot token**
  5. Use the `gate_b3` or `gate_final` subset from `2026-04-10_telegram_validation_v1.py`
  6. If PASS: proceed to `prod_deploy()`, which restarts the production container with the same intent file
  7. If FAIL: git reset the canary, don't touch production

- [ ] **New method `EvolutionTransaction.prod_deploy()`**:
  1. Only callable AFTER `canary_deploy_and_verify()` returned PASS
  2. Write intent file to `/data/neomind/evolution/`
  3. Restart production container: `supervisorctl restart neomind-agent`
  4. Production's `verify_pending_evolution()` re-imports modules (fast path, already validated by canary)
  5. Production starts serving users with new code

- [ ] **Rollback path**: if production's `verify_pending_evolution()` still fails (unlikely after canary PASS), standard rollback applies. Canary has already validated so this should be near-zero probability.

#### Telethon tester changes

- [ ] **`tests/integration/telegram_tester.py`**: add env-driven bot username selection:
  ```python
  BOT_USERNAME = env.get("TG_CANARY_BOT_USERNAME") or env.get("TG_BOT_USERNAME")
  ```
  so the same tester code can target either the production or canary bot by env.

- [ ] **`~/.config/neomind-tester/telethon.env`**: add `TG_CANARY_BOT_USERNAME=@neomindagent_test_bot`

- [ ] **`tests/qa_archive/plans/2026-04-10_telegram_validation_v1.py`**: no changes required — scenarios are bot-agnostic.

#### Skill changes

- [ ] **`agent/skills/shared/telegram-selftest/SKILL.md`**: add a new section "Canary-mode operation":
  - When invoked with `--target=canary`, the tester hits the canary bot
  - When invoked with `--target=prod`, it hits production (read-only scenarios only!)
  - Default: canary (safe mode)

- [ ] **New skill `agent/skills/shared/canary-evolve/SKILL.md`**: coordinator skill that:
  1. Proposes a change
  2. Calls `EvolutionTransaction.canary_deploy_and_verify()`
  3. Spawns `telegram-selftest` tester against canary
  4. Reads report
  5. If PASS, calls `EvolutionTransaction.prod_deploy()`
  6. If FAIL, rolls back canary only

### Estimated scope

- Prerequisites (user action): ~15 min
- Docker/supervisord changes: ~1 hour
- EvolutionTransaction refactor: ~2-3 hours
- Canary tester wiring: ~1 hour
- Skill files + docs: ~30 min
- Full integration test (end-to-end canary evolution run): ~2 hours

**Total: ~6-8 hours of focused work, best split across 2 sessions.**

---

## Part 2 — 100% fidelity CLI automation (iTerm2 AppleScript)

### Problem

The tmux-based CLI tester (`agent/skills/shared/selftest/SKILL.md`) covers **~90-95%** of real user experience in the CLI surface. The remaining **5-10% gap** includes:

1. **Chinese IME composition** — tmux `send-keys` sends UTF-8 bytes directly, skipping Pinyin/Wubi composition events. If prompt_toolkit has a bug with IME composition (e.g. midstream cursor movement), tmux won't catch it.
2. **Bracketed paste mode** — `send-keys` doesn't emit the `\e[200~…\e[201~` wrapper that real terminals use. Paste-specific bugs (multi-line paste handling) are invisible.
3. **Terminal resize events** — tmux uses fixed `-x 120 -y 40`, never resizing mid-session.
4. **Focus in/out events** — `\e[I` / `\e[O` sequences not propagated.
5. **Terminal-emulator rendering quirks** — iTerm2's truecolor, emoji width math, font fallback, ligatures. tmux has its own screen buffer.
6. **macOS-native keyboard shortcuts** — Cmd+K, Cmd+C, Cmd+T all intercepted by iTerm2.
7. **Scrollback buffer behavior** — tmux has its own, not iTerm2's.
8. **OSC sequences** — OSC 52 clipboard, OSC 7 CWD reporting, terminal-specific.

User constraint from 2026-04-10 session:
> "方案 2 放进 todo，**必须要实现和 telegram 一样的 100% 用户行为模拟**"

Translation: CLI automation must match Telethon's 100% fidelity for the Telegram surface. Currently tmux is ~95%. Close the last 5% by driving a real iTerm2 window programmatically.

### Solution — iTerm2 AppleScript / Python API automation

iTerm2 has **two** automation surfaces:

1. **AppleScript** (legacy, partial coverage)
2. **Python API** (modern, full coverage, requires `iTerm2 Python API` package)

The Python API is the right choice because:
- It covers every iTerm2 feature (sessions, tabs, windows, keystrokes, screen capture, color profiles, font changes, resize events)
- It's programmable from within our venv without jumping through AppleScript bridges
- It supports `session.async_send_text(text)` which emits bytes **as if typed on the real keyboard** — including IME composition events when the text contains precomposed characters
- It supports `session.async_get_screen_contents()` for screen capture
- It supports events (`session.async_subscribe_to_new_session_change_event`, `session.async_get_screen_streamer()`) for real-time observation

### Implementation checklist

#### Prerequisites

- [ ] **Install iTerm2** on the host (if not already — user likely has it)
- [ ] **Enable iTerm2 Python API**: iTerm2 → Preferences → General → Magic → Enable Python API
- [ ] **Install iTerm2 Python package in the neo venv**: `.venv/bin/pip install iterm2`

#### Core driver

- [ ] **Create `tests/integration/cli_tester_iterm2.py`**: parallel to `telegram_tester.py`, but drives iTerm2 instead of tmux. Public API:
  ```python
  class ITerm2CliTester:
      async def __aenter__(self) -> "ITerm2CliTester"
      async def start_neomind(self) -> None                # opens window, runs .venv/bin/python -m agent
      async def wait_for_prompt(self, timeout: float = 15) -> bool
      async def send(self, text: str, enter: bool = True) -> None
      async def capture(self, lines: int = 30) -> str      # returns rendered screen
      async def paste(self, text: str) -> None             # uses bracketed paste mode!
      async def resize(self, cols: int, rows: int) -> None # real resize event
      async def ctrl_c(self) -> None                       # real Ctrl+C sequence
      async def close(self) -> None                        # clean exit
  ```

- [ ] **Create `tests/qa_archive/plans/2026-04-10_cli_comprehensive_iterm2.md`**: extended CLI scenario library covering the 8 gaps above:
  - IME composition scenarios (send Chinese + measure cursor behavior)
  - Bracketed paste scenarios (multi-line Python code via `cli_tester.paste()`)
  - Resize scenarios (call `cli_tester.resize(80, 24)` mid-session)
  - Emoji width scenarios (🎉 🚀 ⚡ in table cells)
  - Focus event scenarios (simulate user switching away and back)
  - Cmd+K / Cmd+C handling (if prompt_toolkit responds to them)
  - OSC 52 clipboard (if any feature uses it)
  - Scrollback interaction (scroll up, search, scroll down)

- [ ] **Update `agent/skills/shared/selftest/SKILL.md`**: add a new section "High-fidelity mode (iTerm2)" that points to the iTerm2 driver. Default remains tmux for speed; users can opt in with `--driver=iterm2`.

- [ ] **Update `docs/SELF_TEST.md`**: document the two drivers (tmux: fast, ~95%; iTerm2: slow, 100%) and when to use each.

- [ ] **Create `docs/CLI_SELF_TEST_LIMITATIONS.md`**: explicitly enumerate the tmux gaps and how the iTerm2 driver closes each one.

#### Integration

- [ ] Wire the iTerm2 driver into the validation framework from `plans/2026-04-10_slash-command-taxonomy-v5-with-validation.md`: when running `gate_final`, the CLI portion should default to iTerm2 for 100% fidelity.

- [ ] **Fallback**: if iTerm2 isn't running, fall back to tmux with a loud warning so the user knows the run is only ~95% fidelity.

### Estimated scope

- iTerm2 setup + Python API install: ~15 min
- ITerm2CliTester driver: ~2-3 hours (the tricky parts are paste mode, resize events, Ctrl+C fidelity)
- Comprehensive scenario library: ~1-2 hours
- Documentation + integration: ~1 hour
- Smoke validation that the driver actually catches IME bugs: ~1 hour (need to find or inject a known IME bug to prove coverage)

**Total: ~5-7 hours, can be done in 1 session.**

---

## Ordering

Recommended ordering for a future session:

1. **Canary bot** (Part 1) — more critical because it removes the "self-evolution causes downtime" blocker. User needs to create a test bot token first; once done, everything else is code + config.

2. **iTerm2 driver** (Part 2) — after canary is working, closes the remaining automation gap. Less critical because the tmux-based 95% already catches most bugs, and the user's manual daily usage catches the rest.

Both can be done independently; they don't share code.

---

## Open questions for user

1. **Canary bot token**: willing to create `@neomindagent_test_bot` via @BotFather?
2. **Canary state isolation**: OK with a separate `/data/neomind-canary/` directory, or prefer the same directory with a `canary=true` flag?
3. **iTerm2 Python API**: already enabled on your machine, or needs setup?
4. **Which to prioritize**: canary first, iTerm2 first, or both in parallel (across 2 sessions)?

All four can wait until the current 11-step Phase B execution is done.
