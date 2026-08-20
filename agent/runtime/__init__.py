"""Frontend-agnostic agent runtime.

The boundary this package exists to create: one turn runtime that any surface
(prompt REPL, Textual, Telegram, headless, fleet worker) consumes through typed
events, and exactly one place where a tool can be executed.

Hard rule, enforced by tests/runtime/test_import_boundary.py: nothing in this
package may import a frontend (`cli`, `prompt_toolkit`, `rich`, `telegram`) or
call `print()` / `input()`. A runtime that renders is a runtime that only one
frontend can use.

See plans/2026-08-06_frontend-contract-cli-tui-decoupling-plan.md.
"""
