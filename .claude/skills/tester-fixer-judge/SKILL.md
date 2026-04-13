---
name: tester-fixer-judge
description: Multi-agent test+fix orchestration pattern. Manager (Claude) coordinates without writing code, dispatches focused tester/fixer subagents, judges results from forensic dumps directly. Use when validating + auto-fixing a complex agent (especially NeoMind coding/chat/fin modes) where bugs are mixed across code, infra, LLM behavior, and test harness layers.
---

# tester-fixer-judge

## When to invoke
- User asks for comprehensive testing + auto-fix loop
- User explicitly says variations of "你别下场，你是 manager" / "until clean" / "tester+fixer"
- Bug source is unclear (could be code, infra, LLM behavior, or test harness)
- Multiple iterations expected (5+ fix attempts likely)
- Cross-cutting changes that affect multiple subsystems

## Roles (strict separation — never blur)

### Manager = you (Claude)
**NEVER:**
- Run scenarios in foreground (always background via `nohup ... & disown`)
- Edit source files when a fixer subagent could (preserves your context budget)
- Skip checking results between iterations (causes drift)
- Trust subagent reports without verifying outputs
- Auto-close iTerm2 windows (see `~/.claude/projects/.../memory/feedback_never_close_iterm2_windows.md`)

**ALWAYS:**
- Read forensic dumps directly via Read tool to judge per-turn
- Decide what's a real bug vs LLM-side flake
- Spawn focused fixer agents with tight scope + line numbers + constraints
- Use `ScheduleWakeup` to step away while tests run
- Track progress via task list updates
- Resume cleanly after wakeup by re-checking pid (it may be stale)

### Tester = background process
- Launched via `nohup .venv/bin/python -u <runner.py> > <log> 2>&1 & disown`
- One scenario at a time recommended (stop on first major fail to localize)
- Per-turn screen dumps written to disk for offline judging
- Includes health probe every N turns to detect bot hang

### Fixer = Agent subagent (general-purpose, surgical)
- ONE bug per fixer
- Provide exact file paths and line numbers
- State the constraint: surgical change only, no refactoring
- Require syntax check after edit
- Require report under 150-200 words
- Forbid closing iTerm2 windows or touching running tester
- Self-contained prompt (subagent has zero conversation context)

### Judge = preferably you (Claude)
- Read dumps directly via Read tool
- Trust your eyes more than keyword matching
- LLM judges (kimi/glm/deepseek) are unreliable — see Cons below
- Verdict dimensions: task_done (bool) + llm_quality (1-5) + cli_rendering (1-5)

## Procedure

```
1. Launch tester:
   nohup .venv/bin/python -u <runner.py> --scenario <ID> > <log> 2>&1 & disown
   pid=$(pgrep -f <runner>)

2. ScheduleWakeup delaySeconds=180-300, prompt="check ps $pid, read dumps, judge, decide"

3. On wakeup:
   a. ps -p $pid (it may be dead — that's fine, dumps still readable)
   b. tail log for completion
   c. Read /tmp/<dump_dir>/*.txt for each turn
   d. For each turn: judge task_done / llm_q / cli_q / detected_bugs

4. Decide:
   - PASS → next scenario, repeat
   - FAIL with NEW bug → spawn fixer (see template below)
   - FAIL with KNOWN LLM-side issue → log to bug queue, accept, move on
   - 5+ consecutive FAILs → root-cause investigation (don't keep patching)

5. Auto-loop: don't ask user permission between scenarios. Stop only when:
   - All scenarios PASS
   - User explicitly says stop
   - Hit a blocker requiring user decision (model swap, branch strategy)
```

## Fixer subagent prompt template

```
You are a fix-execution subagent. [bug name] in [file:line].

Symptom: [exact dump excerpt or error message]

Root cause (from diagnostic): [one sentence]

Fix:
1. [step 1 with file path]
2. [step 2]
3. Syntax check: `.venv/bin/python -c "import ast; ast.parse(open('<file>').read())"`

Constraints:
- Surgical change only, no refactoring
- DO NOT close iTerm2 windows
- DO NOT touch running tester pid <pid>
- Report under 150 words: lines changed, what you did, syntax check result
```

## Pros (validated 2026-04-12 NeoMind session — 96 turns, 4 commits merged)
- Strict role separation prevented manager context bloat
- Parallelized fixers when bugs were independent (3 concurrent during S08)
- Auto-loop kept progress moving without user input
- Wakeup-based scheduling let manager step away ~5 min cycles
- Forensic per-turn dumps allowed retroactive judging
- Could pause and resume cleanly mid-test
- Subagent isolation kept manager context lean across long sessions

## Cons / known issues
- **Stale wakeup pids** — by the time wakeup fires, the runner pid may have been replaced. ALWAYS re-fetch via `pgrep -f <runner>` before checking. Don't trust the pid in the wakeup prompt.
- **LLM judges unreliable** — quota limits (`glm-5: 余额不足`), temperature constraints (`kimi-k2.5: only temperature=1 allowed`), reasoning models eat tokens in thinking and return empty content. Use Claude (yourself) as judge.
- **Fixers patch symptom not root** — auto_search bug took 4 attempts because each fixer fixed only one code path. Always ask: "is this the only path?" Search for ALL call sites before declaring fixed.
- **5+ consecutive FAILs threshold is fragile** — sometimes the same root-cause hits 6+ in a row. Don't reset count too eagerly; 6+ means dispatch a diagnostic agent first, not a fix-execution agent.
- **Tester pacing is heuristic** — bot completion detection by prompt regex fails when streaming spinners contain `>` or "Thinking…" text. Mitigation: spinner-aware filter + 3s stability check. Still imperfect.
- **Subagent prompts must be self-contained** — agents have NO conversation context. Always include: file paths, line numbers, exact problem, exact fix steps, constraints, expected report format.
- **Token budget creep** — long sessions accumulate context fast. Use TaskCreate for state, prefer dumps to inline verbose tool output, dispatch heavy lookups to subagents.
- **iTerm2 window accumulation** — each test launches a new window. They pile up. NEVER batch close. User does `⌘W` manually.
- **Manager temptation to dive in** — when fixer is slow or frustrating, you'll want to fix things yourself. Don't. The user's intent is preserved by the role separation.

## How to evolve
After every session that uses this skill:
1. Append to `## Recent learnings` what surprised you, what failed, what you'd do differently
2. If a Pro/Con is no longer accurate, edit it (don't just append — keep current)
3. If a new role / pattern emerged, add it
4. Commit changes alongside the session's other work so the skill improves with use

## Recent learnings
- **2026-04-12** (NeoMind coding CLI session, 15 scenarios / 96 turns / 4 commits):
  - First version drafted from this session
  - The auto_search hijack bug took 5 fix iterations because the bug existed at 4 separate call sites (telegram_bot._should_search, code_commands.prepare_prompt, core.search_sync, nl_interpreter pattern). Lesson: when fixing a feature gate, grep for ALL invocations of the relevant function before declaring fixed.
  - LLM judges (kimi-k2.5, glm-5, deepseek-chat as judge) all failed. Claude as judge worked perfectly. Don't waste time on LLM judges for this workflow.
  - Fixers worked best with 100-200 word constraint. Fixers given >300 word prompts overcomplicated.
  - Manager check cycles of 270s (under prompt cache TTL) worked well. Don't go longer than 300s without reason.
