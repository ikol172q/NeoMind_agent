---
name: teach
description: User teaches NeoMind — explicitly store facts, preferences, corrections into SharedMemory
modes: [shared]
allowed-tools: [Read]
version: 1.0.0
---

# Teach — User-Driven Learning

The user wants to explicitly teach NeoMind something. Store it reliably in
SharedMemory so all modes can benefit.

## Triggers

User says things like:
- "记住：我的券商是 Schwab" → fact (category: finance)
- "Remember: I work at Google" → fact (category: work)
- "以后用中文回复" → preference (language: zh)
- "Don't use bullet points" → preference (format: no-bullets)
- "My timezone is Pacific" → preference (timezone: America/Los_Angeles)
- "I prefer short answers" → preference (verbosity: concise)
- "That's wrong, the correct answer is..." → feedback (correction)

## Storage Mapping

| User intent | SharedMemory method | Example |
|---|---|---|
| Personal fact | `remember_fact(category, fact, mode)` | "I work at Google" → category=work |
| Preference | `set_preference(key, value, mode)` | "用中文" → language=zh |
| Correction | `record_feedback("correction", content, mode)` | "不对，应该是..." |
| Interest | `record_pattern("interest", topic, mode)` | Repeated finance questions → interest=finance |

## Categories for Facts

- `work` — job, company, role, team
- `finance` — broker, accounts, goals, risk tolerance
- `personal` — name, timezone, location, language
- `project` — current projects, repos, tech stack
- `health` — exercise, diet preferences (if shared)
- `other` — anything else

## Process

1. **Parse intent**: What is the user teaching? (fact / preference / correction)
2. **Classify**: Which category or preference key?
3. **Store**: Call appropriate SharedMemory method
4. **Confirm**: "已记住: [summary]. 所有模式都可以使用这个信息。"
5. **Verify**: If ambiguous, ask: "你是说 [interpretation]?"

## Context Injection

Stored knowledge is automatically injected into LLM system prompts via
`SharedMemory.get_context_summary()`. The user doesn't need to repeat themselves.

Example: After teaching "我的券商是 Schwab", when user later asks about trading,
the system prompt already includes "User's broker: Schwab".

## Rules

- ALWAYS confirm what was stored
- If ambiguous, ask before storing (don't guess wrong)
- Sensitive data (passwords, SSN, keys) → REFUSE to store, explain why
- Corrections override previous facts (update, don't duplicate)
- Preferences apply globally across all modes
- User can say "forget X" to remove stored info
