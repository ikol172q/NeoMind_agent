# NeoMind Architecture

A multi-personality CLI agent with a three-tier architecture: **Slim Core → Shared Services → Personality Modes**.

## High-Level Overview

```
┌─────────────────────────────────────────────────────┐
│                    Frontends                         │
│         CLI  ·  Telegram Bot  ·  (future)           │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│                  Slim Core                           │
│   LLM routing · History · Streaming · Mode switch   │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│              Shared Services                         │
│  ServiceRegistry (lazy-init, 20+ services)           │
│  Search · Memory · Vault · LLM Provider · Logging   │
└──────────┬───────────┬───────────┬──────────────────┘
           │           │           │
     ┌─────▼──┐  ┌─────▼──┐  ┌────▼───┐
     │  Chat  │  │ Coding │  │Finance │
     │  类人   │  │ 工程师  │  │  赚钱   │
     └────────┘  └────────┘  └────────┘
     Personality Modes (unique behaviors + shared base)
```

## Directory Structure

```
agent/
├── core.py              # Slim core — LLM calls, history, streaming, routing
├── base_personality.py  # Abstract base for personality modes
├── modes/               # Three personalities: chat, coding, finance
├── services/            # ServiceRegistry + shared service modules
├── agentic/             # Canonical agentic loop (tool parse → execute → feedback)
├── coding/              # Tool system: parser, schema, executor, persistent bash
├── config/              # YAML configs per mode (system prompts, model settings)
├── integration/         # Telegram bot, OpenClaw bridge
├── evolution/           # Self-improvement: reflection, skill forge, drift detection
├── search/              # Multi-source search engine
├── web/                 # Web extraction and content processing
├── data/                # Data collection and compliance
├── finance/             # Finance-specific components
├── llm/                 # LLM provider abstraction
├── memory/              # Shared memory system
├── vault/               # Obsidian-compatible long-term storage
├── workflow/            # Sprint, guard, freeze workflow commands
└── utils/               # Common utilities
```

## Core Concepts

### Three-Tier Architecture

The codebase follows strict layering: **Core** handles LLM communication and routing, **Services** provide shared capabilities (search, memory, vault), and **Personalities** define mode-specific behavior. Each personality has its own system prompt, activation logic, and unique commands while sharing common infrastructure.

### Agentic Tool Loop

The coding personality includes a tool execution system. When the LLM generates a tool call, the agentic loop parses it, executes the tool, feeds the result back, and lets the LLM continue. This loop is frontend-agnostic — both CLI and Telegram consume the same generator-based event stream (`tool_start`, `tool_result`, `llm_response`, `done`).

### Multi-Provider LLM Routing

NeoMind supports multiple LLM providers (DeepSeek, z.ai/GLM, Moonshot/Kimi) with automatic fallback. Each mode can specify preferred models. Provider chain tries each in order until one succeeds.

### Self-Evolution

The evolution subsystem enables NeoMind to improve itself over time: prompt tuning, skill crystallization (SkillForge), drift detection, cost optimization, and reflective learning. Changes are applied via volume-mounted code and hot-reload.

## Frontends

### CLI

Interactive terminal interface with streaming output, thinking mode visualization, and command palette.

### Telegram Bot

Full-featured Telegram integration with streaming message edits, foldable tool results (`<blockquote expandable>`), live execution status indicators, and multi-mode switching via `/mode`.

## Tool System

Tools are defined via a schema registry. Each tool declares its name, parameters (with types and defaults), and an executor function. The parser tolerates LLM quirks like mismatched closing tags and hallucinated parameters.

Available tool categories: file I/O (Read, Write, Edit, Glob, Grep), shell execution (Bash), directory listing (LS), and self-modification (SelfEditor).

## Deployment

Docker Compose with bind-mounted source code. Supervisord manages the agent process, health monitor, watchdog, and data collector inside the container.

```bash
# Start
docker compose up -d --build neomind-telegram

# Logs
docker compose logs -f neomind-telegram
```

## Regenerating This Diagram

The interactive HTML architecture visualization can be regenerated from the live codebase:

```bash
python scripts/gen_architecture.py
# Outputs: plans/architecture_data.json (rendered by web dashboard → Settings → Codebase architecture)
```
