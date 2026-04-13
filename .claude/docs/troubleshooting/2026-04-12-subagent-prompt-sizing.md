# Subagent prompts: self-contained + surgical + sized right

**Date**: 2026-04-12
**Category**: subagent orchestration

## Symptom
Fixer subagent produces wrong output because prompt was too vague, too
verbose, or missing critical context (file paths, line numbers, syntax
check command).

## WRONG (too vague)
> "fix the duplicate_lines bug in agentic_loop"

Subagent has no idea which function, which specific duplicate pattern,
or what the current code looks like. Result: random edit to the wrong
helper function.

## WRONG (too verbose)
> "Here's the full history of the duplicate_lines bug. First we tried
> approach A on 2026-04-12 at 14:30 but it didn't work because... Then
> we tried approach B but ... [500 words] ... so consider the tradeoffs
> and write something clever that handles all the edge cases."

Subagent over-engineers, produces 200 lines of speculative code, misses
the point.

## RIGHT (self-contained + surgical)
```
Bug: `_dedup_consecutive_paragraphs` in
agent/agentic/agentic_loop.py line ~190-210 deduplicates paragraphs
(split on \n\n) but misses duplicates WITHIN a paragraph — the same
sentence repeated 3 times on consecutive lines without \n\n between.

Symptom from dump: "现在编辑文件" appears on 3 consecutive lines with
only \n (not \n\n) between them; current dedup doesn't catch.

Fix: in _dedup_consecutive_paragraphs, BEFORE the paragraph-level
dedup, add a line-level dedup:
1. split on \n
2. skip consecutive identical non-blank lines (excluding lines that
   look like XML markup: starting with `<` or containing `tool_call`)
3. rejoin with \n

Constraints:
- only agent/agentic/agentic_loop.py, no other files
- syntax check: `.venv/bin/python -c "import ast; ast.parse(open('agent/agentic/agentic_loop.py').read())"`
- no refactoring surrounding code
- DO NOT close iTerm2 windows
- report under 150 words: lines changed, what you did, syntax result
```

## Required elements
Every fixer subagent prompt must contain:
1. **Exact file path** (e.g. `agent/services/code_commands.py` not "the sanitizer file")
2. **Exact line range** (e.g. "line ~190-210" or better, grepped line numbers)
3. **Exact symptom** with a code/output snippet if possible
4. **Exact fix steps** — not goals, steps
5. **Constraint list**: which files NOT to touch, what NOT to close,
   what NOT to refactor
6. **Syntax check command** with the right venv
7. **Report format** with word count target

## WHY
Subagents have:
- **Zero conversation context** — they don't know what came before
- **Narrow tool scope** — typically Read, Edit, Bash, maybe a few others
- **Strong incentive to over-explain** — verbose output is rewarded by
  standard RLHF so they'll fill space if the prompt allows

Vague prompts lead to vague fixes on wrong files. Verbose prompts lead
to over-engineering. The right size is "a stranger onboarding in 30
seconds" — enough context to do exactly one thing right.

## 200-word report target
Why enforce report word count? Because agents default to verbose, and
a manager (me) reading 10 verbose fixer reports accumulates 3000+ words
of context bloat. 200 words each × 10 fixers = 2000 words, still a lot
but manageable. The word count is both a constraint and a signal —
if the fixer can't describe its work in 200 words, either the fix is
too big (should have been split) or the report is padding (reject + retry).
