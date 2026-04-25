# Reference: Andrej Karpathy Skills Framework

**Source**: https://github.com/forrestchang/andrej-karpathy-skills
**Pulled**: 2026-04-25

A skill module repo packaging Karpathy's coding-with-LLMs philosophy
for Claude Code / Cursor. Four core principles:

## 1. Think Before Coding

**Purpose**: Eliminate silent assumptions and hidden confusion before
implementation begins.

**Karpathy's diagnosis** (from his Dec-2025 tweet): LLMs "make wrong
assumptions on your behalf and just run along with them without
checking" — exactly like junior developers. The fix: surface the
thinking, don't hide it.

**Pattern**:
- State assumptions explicitly
- Present multiple interpretations when ambiguity exists
- Push back on oversimplified approaches
- Name confusion rather than proceeding blindly

**Anti-pattern**: silently picking an interpretation and executing.

## 2. Simplicity First

**Purpose**: Combat overengineering by implementing only what was
explicitly requested.

**Pattern**: "Compression of context" — every line earns its place
through direct traceability to requirements.

- Minimum viable code solving the actual problem
- No speculative features, abstractions, or configurability
- No error handling for impossible scenarios
- Rewrite if 200 lines could be 50

**Anti-pattern**: adding flexibility, abstractions for single-use
code, or preemptive handling of theoretical issues.

## 3. Surgical Changes

**Purpose**: Ensure edits remain orthogonal to the request; avoid
"drive-by improvements."

**Pattern**: Falsifiability — every changed line traces directly to
the user's specific request.

- Touch only code directly related to the change
- Match existing style without "improving" adjacent code
- Remove only imports/variables YOUR changes orphaned
- Mention unrelated dead code without deleting it

**Anti-pattern**: refactoring unbroken code or touching adjacent
comments while you're "in there."

## 4. Goal-Driven Execution

**Purpose**: Transform imperative tasks into declarative goals with
verification loops.

**Pattern**: "Minimum viable answer" — strong success criteria enable
the LLM to loop independently.

| Imperative | Goal-Driven |
|---|---|
| "Add validation" | "Write tests for invalid inputs, then make them pass" |
| "Fix the bug" | "Write test reproducing it, then make it pass" |
| "Make it faster" | "Add a benchmark, run it, then improve until X" |

**Karpathy's quote**: "LLMs are exceptionally good at looping until
they meet specific goals... Don't tell it what to do, give it success
criteria."

## Synthesis — what this means for prompt design

The four principles converge on one move: **convert vague intent into
something verifiable, then loop**.

- "Think Before" surfaces the assumption (the spot where wrong-running
  starts)
- "Simplicity First" picks the minimum solution for the stated need
- "Surgical Changes" keeps the change checkable line-by-line
- "Goal-Driven Execution" gives the loop a stop condition

The hidden through-line: **falsifiability**. Every part of the work
should be either provably correct or provably wrong — no fog where
"it kind of works" hides.

For NeoMind, this maps directly to anti-hallucination: each factual
claim should be falsifiable (sourced to a tool result / user message /
system text). Where it isn't falsifiable, don't claim it.
