# user_agent

A CLI coding agent powered by multiple LLM providers (DeepSeek, z.ai). Features an agentic tool loop, streaming responses, thinking mode, web search, and self-improvement capabilities.

## Features

- **Multi-Provider Support**: Switch between DeepSeek and z.ai (GLM) models with `/switch`
- **Per-Model Specs**: Context window, output limits, and defaults auto-adjust per model
- **Agentic Tool Loop**: Model generates bash commands → agent executes → feeds results back → model continues
- **Two Modes**: Chat mode (conversational) and Coding mode (agent with tool execution, permissions, spinner)
- **Streaming Chat**: Real-time streaming with thinking process visualization
- **Web Search**: `/search` command for DuckDuckGo integration
- **Code Analysis & Self-Iteration**: Analyze, improve, and safely modify the agent's own code
- **Permission Model**: Read-only tools auto-approve; write/execute tools ask for confirmation
- **Persistent Bash**: Shell state carries across commands (`cd`, `export`, env vars persist)

## Quick Start

```bash
# Clone and install
git clone <repository-url>
cd user_agent
python3 -m venv .venv --system-site-packages
source .venv/bin/activate
pip install -e .

# Set up API keys
cp .env.example .env
# Edit .env — add your DEEPSEEK_API_KEY and/or ZAI_API_KEY

# Run
python3 main.py
```

## Configuration

### Environment Variables (`.env`)

```env
DEEPSEEK_API_KEY=your_deepseek_api_key_here
ZAI_API_KEY=your_zai_api_key_here
```

At least one provider key is required. Get keys from:
- DeepSeek: https://platform.deepseek.com/api_keys
- z.ai: https://open.z.ai

### Config Files

```
agent/config/
  base.yaml     # Shared: model, temperature, max_tokens, stream, timeout
  chat.yaml     # Chat mode: system prompt, auto-search triggers
  coding.yaml   # Coding mode: system prompt with tool instructions
```

Default model is `deepseek-chat`. Change with `/switch <model>` or edit `base.yaml`.

### Supported Models

| Model | Provider | Context | Max Output | Default |
|-------|----------|---------|------------|---------|
| deepseek-chat | DeepSeek | 128K | 8K | 8K |
| deepseek-coder | DeepSeek | 128K | 8K | 8K |
| deepseek-reasoner | DeepSeek | 128K | 64K | 16K |
| glm-5 | z.ai | 205K | 128K | 16K |
| glm-4.7 | z.ai | 200K | 32K | 8K |
| glm-4.7-flash | z.ai | 200K | 32K | 8K |
| glm-4.5 | z.ai | 128K | 16K | 8K |
| glm-4.5-flash | z.ai | 128K | 16K | 4K |

Limits auto-adjust when switching models. Run `/models` to see all available models with their specs.

## Commands

### Core

| Command | Description |
|---------|-------------|
| `/switch <model>` | Switch model (e.g., `/switch glm-5`) |
| `/models` | Show all available models with specs |
| `/think` | Toggle thinking mode |
| `/search <query>` | Web search via DuckDuckGo |
| `/clear` | Clear conversation history |
| `/history` | Show conversation history |
| `/debug` | Toggle verbose debug output |
| `/permissions [auto\|normal\|plan]` | Set permission mode |
| `/quit` | Exit |

### Coding Mode

| Command | Description |
|---------|-------------|
| `/run <cmd>` | Execute shell command in persistent bash |
| `/grep <pattern> [path]` | Search text across files (uses ripgrep if available) |
| `/find <pattern> [path]` | Find files matching pattern |
| `/read <file>` | Read and display a file |
| `/code scan [path]` | Scan a codebase for analysis |
| `/code reason <file>` | Deep analysis using reasoning model |
| `/code self-improve` | Suggest improvements to agent's own code |
| `/transcript` | Show full conversation transcript |
| `/expand [n]` | Show thinking content from turn N |

### Model Management

| Command | Description |
|---------|-------------|
| `/models` | List all models from all providers |
| `/models list --refresh` | Force refresh model list from API |
| `/models switch <model>` | Switch model (same as `/switch`) |
| `/models current` | Show current model + provider + specs |

## Architecture

```
User Input
    |
CLI Layer (main.py -> interface.py)
    |
    +-- Command? --> Command handler (/search, /models, /run, etc.)
    |
    +-- Chat? --> Agent Core (core.py)
                    |
                    +-- _resolve_provider() --> picks DeepSeek or z.ai
                    +-- _get_model_spec() --> applies model-specific limits
                    +-- stream_response() --> API call with streaming
                    |
                    +-- Agentic Loop (coding mode):
                        1. Model generates ```bash block
                        2. tool_parser.py extracts command
                        3. Permission check (auto-approve reads, ask for writes)
                        4. Execute in persistent bash session
                        5. Feed result back as tool_result message
                        6. Re-prompt model --> repeat until done or max iterations
```

### Key Files

```
user_agent/
├── agent/
│   ├── core.py            # Main agent: providers, model specs, streaming, history
│   ├── tool_parser.py     # Extracts tool calls from LLM output (bash + python fallback)
│   ├── tools.py           # Tool implementations (read, write, edit, glob, grep, bash)
│   ├── search.py          # DuckDuckGo web search
│   ├── context_manager.py # Token counting, compression, context management
│   └── config/
│       ├── base.yaml      # Shared settings
│       ├── chat.yaml      # Chat mode config + system prompt
│       └── coding.yaml    # Coding mode config + system prompt (bash-centric tools)
├── cli/
│   ├── interface.py       # Chat session, agentic loop, spinner, content filter
│   └── input_handlers.py  # User input, multi-line, keyboard handling
├── tests/
│   ├── test_tool_parser.py
│   ├── test_claude_interface.py
│   └── test_integration_live.py  # Live API tests (skip when offline)
├── plans/                 # Architecture decisions and implementation plans
├── agent_config.py        # YAML config loader (plain PyYAML, no Hydra)
├── main.py                # Entry point
├── .env                   # API keys (not committed)
└── .env.example           # Template for .env
```

## Tool System

The agent uses a **bash-centric** approach for tool execution in coding mode. The system prompt instructs the model to use ` ```bash ` code blocks for all operations:

```
cat -n src/main.py          # Read a file
grep -rn "def main" .       # Search code
python3 -m pytest tests/ -v # Run tests
```

A **python block fallback** handles cases where the model outputs ` ```python ` blocks — these are automatically wrapped in `python3 << 'PYEOF'` heredocs.

The content filter suppresses tool blocks from terminal display, so you only see the model's reasoning text and the tool execution results.

## Adding a New Provider

1. Add entry to `_PROVIDERS` in `agent/core.py`:
   ```python
   "new_provider": {
       "base_url": "https://api.example.com/chat/completions",
       "models_url": "https://api.example.com/models",
       "env_key": "NEW_PROVIDER_API_KEY",
       "model_prefixes": ["newmodel-"],
       "fallback_models": [{"id": "newmodel-v1", "owned_by": "example"}],
   }
   ```
2. Add model specs to `_MODEL_SPECS`:
   ```python
   "newmodel-v1": {"max_context": 128000, "max_output": 8192, "default_max": 8192}
   ```
3. Add `NEW_PROVIDER_API_KEY` to `.env` and `.env.example`
4. If the provider has API quirks, add provider-name checks in payload construction

## Safety

- **Path validation**: File operations restricted to workspace
- **Permission model**: Read-only tools auto-approve; write/execute tools require confirmation
- **Backup system**: Automatic backups before file modifications
- **Audit logging**: Safety events logged to `.safety_audit.log`
- **Agentic loop limits**: Soft limit at iteration 8 (model told to wrap up), hard limit at 15

## Troubleshooting

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for common issues and fixes.

## Plans & Architecture Decisions

See [plans/](plans/) for implementation plans and architecture decisions.
