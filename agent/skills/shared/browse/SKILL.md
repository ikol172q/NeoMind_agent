---
name: browse
description: Persistent headless browser for web interaction, data extraction, and testing
modes: [chat, coding, fin]
allowed-tools: [Bash]
version: 1.0.0
---

# Browse — Headless Browser

You have access to a persistent headless Chromium browser via the `browse` command.
The browser maintains state (cookies, localStorage, sessions) across calls.

## Core Commands

### Navigation
- `browse goto <url>` — Navigate to URL
- `browse back` / `browse forward` — History navigation
- `browse reload` — Reload current page

### Reading
- `browse text` — Extract all visible text
- `browse snapshot` — ARIA accessibility tree (structured, with @ref IDs)
- `browse snapshot -i` — Interactive elements only
- `browse screenshot [path]` — Take screenshot
- `browse html [selector]` — Get HTML of element
- `browse links` — List all links on page
- `browse forms` — List all forms and inputs

### Interaction
- `browse click @ref` — Click an element (use ref from snapshot)
- `browse fill @ref "value"` — Fill an input field
- `browse select @ref "option"` — Select dropdown option
- `browse type "text"` — Type text into focused element
- `browse scroll down` / `browse scroll up` — Scroll page
- `browse press Enter` / `browse press Tab` — Press key

### Inspection
- `browse console` — View browser console logs
- `browse network [pattern]` — View network requests
- `browse cookies` — List cookies
- `browse js "expression"` — Execute JavaScript

## Usage Pattern

1. `browse goto <url>` — Navigate
2. `browse snapshot -i` — Find interactive elements (get @ref IDs)
3. `browse click @ref` or `browse fill @ref "value"` — Interact
4. `browse text` or `browse screenshot` — Extract result

## Per-Personality Usage

- **chat**: Browse websites to answer questions, extract information
- **coding**: Test web applications, verify UI behavior, screenshot bugs
- **fin**: Extract live financial data from Yahoo Finance, Bloomberg, TradingView; take evidence screenshots

## Rules

- ALWAYS use `snapshot` to find elements before clicking. Do NOT guess selectors.
- Use @ref IDs from snapshot, not CSS selectors, for reliability.
- Take screenshots as evidence when extracting important data.
- Browser state persists — if you logged in, you stay logged in.
