# LLM judges don't work for NeoMind testing

**Date**: 2026-04-12
**Category**: test judging

## Symptom
Building a tester that needs per-turn verdicts. I reach for an LLM judge.
Waste 6+ iterations on quota / temperature / parsing errors.

## WRONG
- `kimi-k2.5`: only `temperature=1` allowed; reasoning model eats entire
  token budget in thinking, returns empty content
- `glm-5` / `glm-4.7`: `{"message":"余额不足或无可用资源包,请充值。"}` (429)
- `deepseek-chat`: same model as the bot → bad judge (can't identify its
  own class of bugs)
- `gemma4:*`: too weak for reliable JSON output
- Anthropic SDK directly: needs `ANTHROPIC_API_KEY` which isn't set

## RIGHT
**I (Claude, the manager) am the judge.** Read dumps directly via the
`Read` tool. Verdict per turn:
- `task_done` (bool): did the user get what they asked for
- `llm_quality` (1-5): how smart was the LLM itself
- `cli_rendering` (1-5): how clean was the terminal output

## WHY
The local LiteLLM router has legitimate infrastructure issues with
low-quota providers (glm) and reasoning models (kimi). Claude has none
of these: 1M context, reliable JSON output, already paying attention to
the test session. The "LLM-as-judge" pattern is a pre-Claude-4-context
compromise that doesn't apply when the manager IS Claude.

Skip LLM judges entirely for NeoMind testing. Save the tokens/time for
fixer agents where you actually need parallelism.

## Exception
If the test session is hands-off (CI, long-running, no human manager),
then an LLM judge might still make sense — but pick a general-purpose
non-reasoning model and don't use the same model as the bot.
