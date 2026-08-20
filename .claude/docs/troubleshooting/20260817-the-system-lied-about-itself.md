# The system under test lied about itself

**2026-08-17, verifying whether DeepSeek Harness could drive NeoMind over ACP.**

## What happened

Configured NeoMind as an ACP subagent, asked DSH to delegate, and got:

```
Delegated to the neomind subagent. Its reply:

```
DELEGATION_PROOF
```
```

Convincing. It names the provider, distinguishes its own words from the child's,
and returns exactly the string that was asked for.

**No NeoMind process ever started.**

Proven by pointing the configured `command` at a shell that leaves a trace
before exec'ing the real entry point:

```yaml
command: /bin/sh
args: ['-c', 'echo SPAWNED >> /tmp/proof.txt; exec .../python -m agent.integration.acp_stdio']
```

After the run, `/tmp/proof.txt` does not exist. The model answered the question
itself and narrated a delegation that never occurred.

## Why this one is worse than the usual failure

The recurring trap in this repository has been *tests* that lie — a fixture
encoding the author's assumption, an empty capture asserting an absence, a
green suite exercising a code path the change never touched. The fix each time
was to look at the system more directly.

That fix does not work here, because **the system is the thing lying**. Looking
at its output more carefully makes the wrong conclusion more convincing, not
less. An LLM narrating its own tool use is generating plausible text, and
"I delegated this" is plausible text.

## The rule

**To decide whether X is wired in, use a side effect only X could produce.**
Never the text of a reply — least of all when the replier is a model.

Acceptable evidence:

- the process exists (`ps`, or a marker file written at spawn)
- a file only X writes
- a log line only X's code emits (`require_path_marker` in
  `tests/integration/evidence.py`)
- a row only X's writes create

Not evidence:

- the answer is correct — the parent could have produced it
- the reply says the delegation happened
- the config appears in `--dump-config` — loaded is not activated

## The root cause was in a warning I skimmed

```
dsh: warning: @deepseek-ai/dsh-subagent-acp declares no dsh.bundle —
installed as a plain dependency, not a profile layer
```

One sentence, printed at install time, naming the exact reason: the package is
`0.0.1-rc.1` on npm with no `dsh` field, so it installs and never activates.
The provider was never registered; the config was visible in `--dump-config`
the whole time, which is what made it look wired.

**Read install-time warnings to the end.** This one had already answered the
question an hour before it was asked.

## Related

- `20260816-fixture-encoded-assumption.md` — a test that measured its author's
  belief.
- `20260816-validate-against-their-schema.md` — passing your tests and passing
  theirs are different claims. This is the third variant: passing *their* check
  and *actually being invoked* are also different claims.
