"""LLM provider adapters.

Adapters depend on the runtime; the runtime never depends on an adapter.
Anything provider-shaped — SSE framing quirks, vendor-only delta fields,
sentinel tokens — is confined to this package and does not reach
`agent/runtime/llm_stream.py`.
"""
