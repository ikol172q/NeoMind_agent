---
name: real-terminal-fidelity-testing
description: Test NeoMind CLI/bot agents with maximum user-behavior fidelity. Use real iTerm2 windows (not tmux/expect/pty), capture FULL terminal context per turn via continuous polling-based recording, verify cross-surface (CLI + Telegram bot via Telethon). Required when user says "100% 用户使用情形模拟" or any request implying real-client validation.
---

# real-terminal-fidelity-testing

## When to invoke
- Testing NeoMind CLI bot behavior end-to-end
- Bug only reproduces in actual terminal (not in unit tests / mocks)
- Cross-surface validation required (CLI + Telegram client)
- User requests "real client / real terminal" testing
- Format/rendering bugs (markdown, ANSI, emoji width, duplicate lines, fence breaks)
- Validating per-mode behavior (coding/chat/fin) where mode-specific code paths matter

## Hard requirements (non-negotiable)

1. **Real terminal — iTerm2 Python API (`iterm2` package)**
   - NOT tmux send-keys (no bracketed paste, no real key events)
   - NOT pty/expect (no real cocoa input layer)
   - NOT mocked (defeats the purpose)

2. **Real LLM provider routing**
   - Use the SAME router config the user uses daily: `LLM_ROUTER_BASE_URL=http://127.0.0.1:8000/v1` + `LLM_ROUTER_API_KEY=dummy`
   - Don't substitute different provider — bug paths may differ

3. **Real client for cross-surface verification**
   - CLI tested via iTerm2 (this skill)
   - Telegram bot tested via Telethon (`tests/integration/telegram_tester.py`) — separate runner
   - Run the SAME scenarios on both surfaces when possible
   - A bug fix that only works on one surface is NOT done

4. **Full terminal capture per turn — not keyword matching**
   - Every visible line, indexed by absolute scrollback position
   - Manager (Claude) reads the actual dump via Read tool
   - Keyword-based judging is INSUFFICIENT — it misses formatting/duplication/rendering bugs

5. **Per-mode env propagation**
   - Always launch with `NEOMIND_AUTO_ACCEPT=1` (bypasses permission gate for tests)
   - Always pass `--mode <coding|chat|fin>` explicitly
   - Add `NEOMIND_MODE=coding` env var as belt-and-braces (some code paths read env over config)

## Architecture (current implementation)

### Tester base class
Lives at `tests/integration/cli_tester_iterm2.py`. Key API added 2026-04-12:

```python
async with ITerm2CliTester(config) as tester:
    await tester.start_neomind()
    await tester.wait_for_prompt(timeout=30)

    for scenario in scenarios:
        for turn in scenario.turns:
            tester.start_recording()        # begin abs-index accumulation
            await tester.send(turn.input)
            await wait_for_response(tester, turn.wait_sec)
            screen = tester.stop_recording()  # full content seen during this turn
            save_dump(screen)               # judge reads later
```

### Recording mechanism
- `capture()` extended to populate `_recording: dict[int, str]` keyed by `number_of_lines_above_screen + line_index_in_visible_screen`
- Across many polls, the dict accumulates ALL visible lines that ever appeared during the recording window
- `stop_recording()` returns content sorted by absolute index = chronological reconstruction
- Avoids the iTerm2 limitation that `async_get_screen_contents()` returns ONLY the visible window (no scrollback access)

### Wait-for-response with stability + spinner filter
- Polls every 0.3s (not 1s — fast bots scroll content off in 1s)
- Detects "bot done" by counting `>` prompts in the last 30 lines
- **Filters out** lines containing `Thinking` / `Thought for` / spinner braille chars (`⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏`) — these falsely matched the prompt regex
- Stability check: tail50 must remain identical across a 3s gap before declaring done
- Hard cap at `max_wait + 30s`

### Window geometry
- cols=120, rows=60-80 (sweet spot)
- Larger rows (200) breaks prompt detection because cursor sits far from bottom
- Smaller rows (40) loses content to scroll-off

### Cross-surface (Telegram)
- Run the same scenarios via Telethon-driven Telegram bot
- Verify a bug fixed in one surface is also fixed in the other
- Example: auto_search hijack fix required SEPARATE patches in `telegram_bot._should_search` AND `code_commands.prepare_prompt` AND `core.search_sync` AND `nl_interpreter` (4 code paths)

## Pros (validated 2026-04-12)
- Caught bugs invisible to keyword matching: markdown fence rendering (` ```pythonprint `), repeated prose ("现在编辑文件" × 12), bash-self-execute, indentation collapse
- Confirmed real terminal escape behavior: braille spinner chars, prompt position, status bar layout
- Cross-surface validation found 4 separate auto_search call sites that needed independent fixes
- Forensic dumps allow retroactive judging — manager doesn't need to be present when test runs
- Manager (Claude) judging from raw dumps is far more accurate than LLM-as-judge
- Per-turn isolation simplifies attribution of bugs to specific user inputs

## Cons / known limitations
- **iTerm2 API has no scrollback access** — `async_get_screen_contents()` returns only the visible window. Recording dict workaround relies on continuous polling. If polling rate is too slow vs bot streaming speed, content scrolling off between polls is LOST. 0.3s seems adequate for deepseek-reasoner. Faster bots may need streamer-based subscription.
- **Polling vs scroll race** — fundamentally a sampling problem. Use ScreenStreamer (event-driven) if available in your iterm2 version, but it requires more setup.
- **Prompt detection is heuristic** — `>` regex matches mid-stream tool output and spinner-line ends. Filter: skip lines containing `Thinking` / `Thought for` / braille spinner chars. Still imperfect under reasoner output.
- **Window rows tradeoff** — too few = scroll-off; too many = prompt-at-top makes detection fail. 60-80 rows is the sweet spot for NeoMind's prompt_toolkit layout.
- **No keyboard-interval simulation** — `async_send_text` injects whole input at once. Real users type slowly; some prompt_toolkit features (autosuggestion, key bindings with timeout) may behave differently.
- **No IME composition** — Chinese characters arrive pre-composed via API. Real macOS IME path is not exercised. NeoMind hasn't shown bugs from this yet but it's a coverage gap.
- **No paste / Ctrl+C / Ctrl+D / window resize** — these methods exist on `ITerm2CliTester` but no scenarios exercise them.
- **Permission gate bypassed** — `NEOMIND_AUTO_ACCEPT=1` skips the real permission UX. If a bug only manifests when the gate is engaged, this won't catch it.
- **iTerm2 windows accumulate** — every test launches a new window. They pile up. NEVER batch close (see manager memory). User clears manually with ⌘W.
- **State persists across scenarios** — bot's conversation history leaks between turns within a runner session. Use `/clear` between scenarios or restart the runner per scenario.

## Reference files
- `tests/integration/cli_tester_iterm2.py` — base tester (recording API added 2026-04-12)
- `tests/integration/cli_iterm2_full_runner.py` — older runner with reply-extraction logic
- `tests/integration/telegram_tester.py` — Telethon-based Telegram surface tester
- `/tmp/coding_cli_judged_runner.py` — current judged runner (in /tmp; copy to repo if useful long-term)
- `/tmp/neomind_tester_fidelity_gaps.md` — known coverage gaps list

## How to evolve
- Each session that uses this skill should append to `## Recent learnings`
- If iTerm2 API gains real scrollback access, replace polling with event-driven subscription
- Add scenarios for the gap categories above (paste, IME, resize, Ctrl+C, etc.) as user requests demand them
- Update polling rate / window size if you find a better tradeoff for a specific model
- If new fidelity dimensions are discovered (e.g. mouse events, drag-drop), add them as separate hard requirements

## Recent learnings
- **2026-04-12** (NeoMind coding CLI session, 15 scenarios / 96 turns):
  - Continuous-polling recording mechanism added — solved the "dump is empty / dump is just last screen" problem
  - Cross-surface validation revealed 4 separate auto_search code paths (CLI + Telegram + nl_interpreter + core.search_sync). All needed independent fixes.
  - Spinner braille filter was the missing piece for reliable prompt detection under deepseek-reasoner streaming
  - Window rows=200 broke prompt detection (prompt at top, cursor 200 lines below). 60-80 rows is the right tradeoff.
  - LLM judge attempts (kimi-k2.5, glm-5) all failed for various reasons. Claude (manager) reading dumps is the most reliable judge.
  - 0 gnews_en hijack confirmed across 96 turns post-fix — cross-mode regression smoke (chat + fin) confirmed no breakage of other modes
