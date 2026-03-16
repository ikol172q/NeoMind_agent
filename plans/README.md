# Plans

Implementation plans and architecture decisions for neomind agent.

| Date | Plan | Status |
|------|------|--------|
| 2026-03-14 | [Mode Split](2026-03-14_mode-split.md) — Split agent into chat + coding modes with separate configs | **Done** |
| 2026-03-14 | [Tool Upgrade](2026-03-14_tool-upgrade.md) — Fix tool→LLM loop, persistent bash, ripgrep, output truncation | **Done** |
| 2026-03-15 | [Agentic UX](2026-03-15_agentic-ux.md) — Spinner, thinking display, agentic tool loop, code fence filter, /transcript, /expand | **Done** |
| 2026-03-15 | [Formalized Tool System](2026-03-15_formalized-tool-system.md) — Structured tool calls, bash-centric approach (pivoted from `<tool_call>` XML), python block fallback | **Done** (Phases 1-3; Phase 4 partial) |
| 2026-03-15 | [Multi-Provider](2026-03-15_multi-provider.md) — DeepSeek + z.ai (GLM) provider registry, per-model specs, `/switch` across providers | **Done** |
