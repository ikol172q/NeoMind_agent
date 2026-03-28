---
name: retro
description: Weekly self-retrospective — mode-specific sprint analysis with dialogue patterns and operational metrics. Write results to vault via write_retro.
modes: [chat, coding, fin]
allowed-tools: [Bash, Read, Edit, WebSearch, Grep]
version: 2.0.0
---

# Retro — Weekly Self-Retrospective

You are conducting a weekly retrospective on YOUR OWN performance as an agent in the current mode.
Goal: identify patterns, improve decision-making, evolve system prompts, and persist learnings to vault.

**Current Mode Context:** This retro focuses on [chat/coding/fin] mode performance, but cross-mode patterns are noted.

## Workflow

### 1. Gather This Week's Evidence Trail (Mode-Specific)

**For all modes:**
- Review all sessions from the past 7 days in this mode
- Sprint statistics:
  - Number of sprints completed
  - Total tasks attempted / completed / failed
  - Success rate (% completed successfully)
  - Average task duration
  - Tools used most frequently
  - Errors/blockers encountered
  - User satisfaction signals (explicit feedback, task complexity, rework needed)

**Chat Mode specific:**
- Dialogue patterns: response length, tone, question-asking style
- Search usage: frequency and effectiveness
- User preferences learned (language, format, depth)
- Engagement metrics: user follow-ups, satisfaction signals

**Coding Mode specific:**
- Sprints completed (count, average duration)
- Code review effectiveness: issues found per review
- Test coverage changes
- Performance metrics: build time, test run time
- Deployment frequency and success rate

**Finance Mode specific:**
- Trade analysis quality: prediction accuracy vs actual
- Risk management: positions held, compliance with limits
- Research depth: sources consulted, analysis rigor
- Decision speed: time from analysis to decision
- Operational security: any credential or PII risks detected

- Look for patterns: recurring mistakes, successful strategies, bottlenecks

### 2. Analyze: What Went Well / What Failed

**What Went Well:**
- Which task types completed fastest?
- Which tools were most effective?
- What prompting strategies worked?
- Which decisions were correct?

**What Failed:**
- Which tasks took too long?
- Which tool combinations didn't work?
- What misunderstandings occurred?
- What decisions were wrong?

**Patterns:**
- Is there a category of tasks I handle poorly?
- Am I over-using certain tools?
- Are there decision-making blind spots?
- Is performance degrading/improving?

### 3. Compare with Last Retro
- Read last week's retro file: `~/.neomind/evolution/retro-*.md`
- What improvements were targeted last week?
- Did I actually improve on them?
- Which targets are still not met?
- Did new problems emerge?

### 4. Generate 3 Concrete Improvement Actions
Format for each:
```
Goal: [What to improve]
Current: [Current behavior]
Target: [Desired behavior]
Metric: [How to measure success]
Action: [Specific change to make]
Timeline: [By when]
```

Example:
```
Goal: Reduce task completion time by 20%
Current: Average 45 minutes per medium task
Target: Average 36 minutes per medium task
Metric: Weekly average task duration
Action: Pre-load 3 most-common file paths; improve search patterns
Timeline: Next week
```

### 5. Save to Evolution File & Vault

**Local file:**
- Create: `~/.neomind/evolution/retro-YYYY-MM-DD-[mode].md`
- Include: summary, patterns, 3 improvements, metrics from last retro
- Keep previous retros (don't overwrite)

**Vault persistence:**
- Call `write_retro(mode, summary, patterns, improvements)` to persist to vault
- This makes the retro accessible to all modes for cross-mode learning
- Vault stores encrypted, timestamped entries with mode context

### 6. Update System Prompt Based on Learnings
If there are learnings that should affect how I operate:
- Better tool selection strategy?
- New mental models to apply?
- Common pitfalls to avoid?
- Decision-making heuristics to adopt?

These inform future system prompt updates.

## Retro File Format

```markdown
# Weekly Retro — [Date Range]

## Stats
- Sessions: X
- Tasks: Y completed / Z attempted
- Success rate: X%
- Average task time: M minutes
- Most-used tools: [list]

## What Went Well
- [Pattern 1]: [evidence]
- [Pattern 2]: [evidence]

## What Failed
- [Issue 1]: [evidence]
- [Issue 2]: [evidence]

## Comparison with Last Retro
- Last week targeted: [improvement 1], [improvement 2]
- Progress: [yes/no/partial] for each
- New blockers: [list]

## 3 Improvement Targets

### 1. [Goal]
Current: ... → Target: ...
Action: ...
Metric: ...
Timeline: ...

### 2. [Goal]
Current: ... → Target: ...
Action: ...
Metric: ...
Timeline: ...

### 3. [Goal]
Current: ... → Target: ...
Action: ...
Metric: ...
Timeline: ...

## System Prompt Learnings
- [Insight 1]: affects how I should [behavior]
- [Insight 2]: affects how I should [behavior]
```

## Rules

- Retro is HONEST: admit mistakes, don't rationalize
- Focus on PATTERNS, not individual failures
- Improvements are SPECIFIC and MEASURABLE
- Compare WEEK-TO-WEEK: are we trending up or down?
- Update system prompts based on learnings (within safety constraints)
- Save all retro files for long-term pattern analysis
- **Mode-aware:** track mode-specific metrics separately, but note cross-mode learnings
- **Vault always:** every retro must be written to vault via `write_retro()` for institutional memory
- **Sprint context:** reference specific sprints by ID and outcomes
- **Dialogue analysis:** chat mode should include samples of successful vs unsuccessful interactions
- **Cross-mode sharing:** improvements in one mode inform other modes (e.g., efficiency in coding → chat response speed)
