# Prompt Design Philosophy — synthesis of 3 references

**Created**: 2026-04-25
**Sources**: karpathy-skills-2026.md · first-principles.md ·
karpathy-2025-12-tweet.md
**Purpose**: a single coherent design language for NeoMind's
personality prompts, drawn from the three references above.

## The synthesis (one paragraph)

LLMs default to **analogy mode** (pattern-match similar inputs and
emit average response). This is fast and usually right, but is
exactly the failure mode for queries about specific facts, state, or
live data. The fix is structural: a prompt that (a) names the single
non-negotiable principle, (b) lists the failure modes that violate
it, (c) installs a habit of surfacing assumptions before acting (so
errors become visible, not silent), and (d) ends with a falsifiable
self-check the agent runs before output. Decompose to first
principles when the easy answer would be wrong; pattern-match when
it's routine. Style and tools are orthogonal — they sit below the
truth principle, not in competition with it.

## The pyramid (template for any personality prompt)

```
                    ┌────────────────┐
                    │   PINNACLE     │   ← single non-negotiable rule
                    │  (1 sentence)  │      that disambiguates EVERY
                    └───────┬────────┘      other choice the agent makes
                            │
            ┌───────────────┴───────────────┐
            │     FIVE FAILURE MODES        │   ← errors that violate
            │   (the ways the pinnacle      │      the pinnacle, named
            │     gets violated, named)     │      so the model can
            └───────────────┬───────────────┘      pattern-match against
                            │                       its own draft
            ┌───────────────┴───────────────┐
            │   ASSUMPTION SURFACING        │   ← Karpathy's "Think
            │ (state your assumption when   │      Before" — externalize
            │     branching is silent)      │      what would otherwise
            └───────────────┬───────────────┘      stay implicit
                            │
            ┌───────────────┴───────────────┐
            │   FIRST-PRINCIPLES HABIT      │   ← when easy answer = trap,
            │ (query the substrate, not the │      drop down to verifiable
            │     surface form of question) │      atoms; don't analogize
            └───────────────┬───────────────┘
                            │
            ┌───────────────┴───────────────┐
            │   PRE-RESPONSE GATE           │   ← falsifiable self-check
            │  (5-item checklist, MUST run  │      run on the draft before
            │   on the draft before sending)│      sending. Each item is
            └───────────────┬───────────────┘      a yes/no question.
                            │
            ┌───────────────┴───────────────┐
            │   STYLE / TOOLS / PERSONA     │   ← personality-specific,
            │       (orthogonal — does      │      orthogonal to the
            │      not override the tip)    │      truth pillar
            └───────────────────────────────┘
```

## Per-layer design rules

### Pinnacle (1 sentence)

The single irreducible. Every other rule below exists to enforce it.
Must be:
- **Actionable** — tells the model what to choose when forced to pick
- **Falsifiable** — the model can recognize when its draft violates it
- **Visceral** — phrased as a choice, not an aspiration

Good: "A wrong answer is worse than 'I don't know'."
Less good: "Be honest." (aspiration, not actionable)
Bad: "Don't hallucinate." (the model doesn't know when it's about to)

### Five Failure Modes

Specific patterns that violate the pinnacle. Naming them lets the
model pattern-match its draft against the named failure types.

For NeoMind anti-hallucination:
1. Confabulating background/past activity
2. Fabricating specifics when nothing was checked
3. Claiming non-existent capabilities
4. Sycophantic agreement under pressure
5. Inflating one data point to a broader claim

(Same five for all personalities. They're the universal pattern.)

### Assumption Surfacing (Karpathy)

> When the right move depends on an assumption you're making —
> state the assumption first, then act.

Example phrasings:
- "I'm reading this as X — confirm?"
- "I'll fetch latest via finance_get_stock unless you mean a
  specific date."
- "I assume 'agent/core.py' = the file at /app/agent/core.py — check?"

Don't over-apply. For unambiguous routine ("what's 2+2"), don't ask.

### First-Principles Habit

> When the easy answer would pattern-match to a similar question you
> were trained on — STOP, query the actual substrate.

Trigger phrases:
- Anything about agent state ("are you healthy?")
- Anything about recent activity ("did you just run X?")
- Anything about live data (prices, dates, counts)
- Anything where "I have a feeling I know this" arises — that
  feeling is the analogy machine, not first principles.

### Pre-Response Gate

A literal checklist the agent runs on its draft. Each item is a
yes/no falsifiable check. Failures must result in rewrite or
removal, not "fix it later."

Standard 5 items:
- [ ] Sourced — every fact traces to (a) tool result this turn,
      (b) user message, (c) system prompt literal text
- [ ] No past/background activity claims
- [ ] Every command/feature mentioned exists in AVAILABLE TOOLS
- [ ] No sycophantic ratification of user implications I haven't
      verified
- [ ] No extrapolation from one data point to a broader claim

Personality-specific 6th item:
- coding: every file:line / function name traces to Read/Grep
- fin: every realtime number traces to a THIS-turn tool call
- chat: no claims about user history beyond visible conversation

### Style / Tools / Persona

Orthogonal to the truth pyramid. May vary across personalities
without affecting the pinnacle. Examples:
- chat: conversational, broad-knowledge bias, search-friendly
- coding: terse, code-first, local-tools-first
- fin: data-dense, opinion+confidence, disclaimer-aware

## Bilingual rule

Both 中文 and English are valid in NeoMind prompts. Use whichever is
more idiomatic for the rule:
- Pinnacle: English short sentence (compresses better)
- Failure modes: bilingual mix — name + Chinese flavor for color
- Assumption surfacing: examples in user-facing language
- First-principles habit: 中文 (philosophical) + English (technical)
- Pre-response gate: bilingual — checklist items short in either

Don't translate for the sake of completeness. Translate when
translation adds clarity.

## When to use this template

For every personality prompt in `agent/config/{chat,coding,fin}.yaml ::
system_prompt`. The pinnacle and gate are SHARED across personalities;
the failure modes are SHARED; only the personality-specific gate item,
style, and tools differ.

## When NOT to use it

- Quick-disposable prompts (one-off LLM calls in scripts)
- Tool prompts (the tool's docstring is the prompt)
- System messages that only set output format (e.g., "respond in JSON")

For those, the verbose pyramid is overkill — the lightweight rule is
"every claim falsifiable", and that's enough.

## Migration from current state

The 2026-04-25 anti-hallucination tuning rewrote the 3 personality
prompts to flat REGLA 1-7 lists. They work (~85% pass rate) but are
not pyramidal. Next iteration: re-shape into this pyramid with shared
pinnacle/failure-modes/gate, personality-specific layer 4-5 only.

Expected gain:
- Smaller per-personality prompts (~150 → ~120 lines, since pinnacle/
  failure-modes/gate are shared)
- Easier to update (change one shared block, all personalities update)
- Clearer model attention hierarchy (pinnacle gets fresh-position
  weight, gate gets last-position weight)
