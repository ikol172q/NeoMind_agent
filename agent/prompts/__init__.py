"""
Modular Prompt Composition System for NeoMind.

Builds the system prompt from composable, cacheable sections with
priority-based override chain:

  override → coordinator → agent → custom → default

Each section can be independently tested and cached.
"""
