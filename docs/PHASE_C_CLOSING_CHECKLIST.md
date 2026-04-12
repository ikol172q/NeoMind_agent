# Phase C — iTerm2 Driver Activation Closing Checklist

**Status:** Ready to run. Requires exactly two user actions below, then one single command.
**Prerequisites:** Session `feat/major-tool-system-update` at HEAD `cd0b081` or later. Canary bot + closed-loop already validated (Phase B + D PASS).

---

## What Phase C proves

The iTerm2 driver in `tests/integration/cli_tester_iterm2.py` can drive a real iTerm2 window through the Python API with 100% fidelity (IME composition, bracketed paste, real SIGWINCH, focus events, native emoji rendering, Cmd shortcuts, OSC 52 clipboard). This is the CLI-side counterpart of the Telethon validator that proved the canary loop works for Telegram.

Without Phase C, the CLI surface is tested via tmux (~95% fidelity) which is good enough for most regressions but misses the 8 gaps enumerated in `docs/CLI_SELF_TEST_ITERM2.md`.

---

## Step 1 (user) — Quit + re-open iTerm2

This current Claude Code session is running INSIDE iTerm2, so `⌘Q` will kill our conversation. **Do NOT restart iTerm2 until you're ready to end this session.**

When you're ready:

1. `⌘Q` — fully quit iTerm2 (not just close window)
2. Launch iTerm2 again from Spotlight / Applications / Dock
3. On first launch with `EnableAPIServer=1` (already set via `defaults write`), iTerm2 shows a one-time permission dialog:
   > "An application wants to control iTerm2 using the Python API. Allow?"
4. Click **Allow**. If a checkbox "Don't ask again" is offered, tick it.

**Quick verification (from a new terminal):**
```
lsof -i :1912
```
Should show an `iTerm2` process listening on `127.0.0.1:1912`. If empty, iTerm2 didn't pick up the preference — try `defaults read com.googlecode.iterm2 EnableAPIServer` (should be 1) and relaunch.

---

## Step 2 (user) — Re-open Claude Code

In the newly-launched iTerm2:

```
cd $REPO_ROOT
claude
```

Resume this same session so you can paste context back into the conversation. The branch state (HEAD `cd0b081+`), canary container (`neomind-canary` still running), and production bot (pid 25942+) are all preserved because they live outside iTerm2.

---

## Step 3 (user) — Paste this into Claude Code

Once Claude Code is back up, paste this exact message so I know iTerm2 is ready and can run Phase C:

```
iTerm2 restarted, Python API Allow clicked. Run Phase C now.
```

That single sentence is your "run command". I'll then execute:

```bash
# Assistant will run — no user action beyond the message above
lsof -i :1912                              # verify listener
.venv/bin/python tests/integration/cli_tester_iterm2.py  # smoke test
.venv/bin/python tests/integration/cli_iterm2_phase_c_runner.py  # 5 scenarios
```

Expected outcome:
1. `_smoke()` opens a real iTerm2 window, runs `python -m agent`, sends `/status`, captures output — exit 0
2. 5-scenario runner opens another window, runs `/status` + `/mode fin` + `AAPL 现价` + `/tune status` + `/clear` — prints `PASS: 5/5 PASS` and exits 0
3. I write the Phase C evidence file and mark Phase E complete

Total runtime once you paste: ~3-5 min.

---

## If something goes wrong

### `ITerm2APIUnavailable: Connect call failed`
The Python API listener didn't come up. Check `defaults read com.googlecode.iterm2 EnableAPIServer` — should be `1`. If yes, try:
1. Quit iTerm2 again (`⌘Q`)
2. Run `defaults write com.googlecode.iterm2 EnableAPIServer -bool true`
3. Launch iTerm2 fresh
4. Accept the permission dialog

### `ITerm2APIUnavailable: App returned None`
iTerm2 is listening but reports no active windows. Open any iTerm2 window manually (`⌘N`), then retry the Phase C runner — it opens its own window.

### Phase C runner scenario FAILs
Scenario replies are sent to a live iTerm2 window — you can visually inspect what happened. Share the captured tail from `/tmp/cli_iterm2_phase_c_runner.log` with me and I'll triage.

---

## What's already been done this session (context for the next one)

- **Canary pipeline**: proved end-to-end on both Telegram (forward + revert). Production stayed healthy at ~99% uptime, only 12.1s total downtime from the 2 planned restart windows.
- **9 plan commits**: Phase B taxonomy → Final Gate PASS → TODO Part 1 & 2 code → activation plan → closed-loop evidence
- **Tasks #68 + #66 + #65 complete**, #67 pending (this), #69 in progress (records + cron stub)
- **Evidence**: `tests/qa_archive/results/2026-04-11_closed_loop_pass.md` + `tests/qa_archive/results/2026-04-11_pre_activation_smoke.md` + `plans/2026-04-11_todo_activation_closed_loop.md`
- **Memory updates**: `reference_canary_pipeline.md` + `feedback_canary_orchestrator_gotchas.md` added to MEMORY.md index

The canary bot (`@your_canary_bot_example`, container `neomind-canary`) is still running in the background. You can leave it running between sessions — it only consumes ~1GB memory and uses the test bot token (no production impact).
