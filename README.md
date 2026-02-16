# ikol1729_agent - DeepSeek AI Agent

A Python package for interacting with DeepSeek AI models through a CLI interface with web search capabilities, thinking mode, and conversation history.

## Features

- **Streaming Chat**: Real-time streaming of AI responses with thinking process visualization
- **Web Search Integration**: `/search` command for DuckDuckGo web searches
- **Thinking Mode**: Toggle thinking process streaming with `/think` command (saves to config)
- **Model Management**: Switch between DeepSeek models (`/models switch <model>`) with config persistence
- **Development Testing**: Built-in test suite with `/test` command or `python main.py test`
- **Conversation History**: Maintains context across conversations with `/history` view
- **Multi-line Input**: Support for continuation lines with `\` at end of line
- **Enhanced CLI**: Optional `prompt_toolkit` support for better user experience
- **Configuration Management**: Hydra-based configuration with YAML file and environment variable overrides
- **Package Distribution**: Installable via `pip` with optional dependencies

## Installation

### From Local Source (Development)
```bash
# Clone the repository
git clone <repository-url>
cd ikol1729_agent

# Install in development mode
pip install -e .

# Install with all optional dependencies
pip install "ikol1729-agent[full]"
```

### As a Package
```bash
# Install from PyPI (when published)
pip install ikol1729-agent

# Install with full features
pip install "ikol1729-agent[full]"
```

### Usage
```bash
# Interactive chat (default)
ikol1729-agent

# Alternative: run as a module
python -m ikol1729_agent

# Run development tests
python main.py test

# Show version information
python main.py --version

# Standalone development test script
python dev_test.py
```

## Configuration

### Environment Variables
Create a `.env` file with your API key:
```env
DEEPSEEK_API_KEY=your_api_key_here
```
Copy from `.env.example` as a template.

### Configuration File
`agent/config.yaml` contains all agent settings:

```yaml
agent:
  model: deepseek-chat           # Model to use (deepseek-chat, deepseek-reasoner, etc.)
  temperature: 0.7               # Creativity level (0.0 to 1.0)
  max_tokens: 8192               # Maximum response length
  thinking_enabled: false        # Whether to show thinking process
  stream: true                   # Stream responses
  timeout: 30                    # API timeout in seconds
  max_retries: 3                 # API retry attempts
  system_prompt: |               # System instructions for the agent
    You are DeepSeek AI...
```

### Configuration Management
- **Model Switching**: Use `/models switch <model>` to change models (saves to config)
- **Thinking Mode**: Use `/think` to toggle thinking mode (saves to config)
- **Environment Overrides**: Set `DEEPSEEK_MODEL` or `DEEPSEEK_TEMPERATURE` env vars to override config
- **Persistent Changes**: All configuration changes are saved to `agent/config.yaml`

## Commands

### Interactive Chat Commands
- `/clear` - Clear conversation history
- `/history` - Show conversation history
- `/think` - Toggle thinking mode (saves to config)
- `/test` - Run development tests
- `/search <query>` - Search DuckDuckGo for information
- `/quit` - Exit the chat

### Model Management Commands
- `/models` or `/models list` - Show available models
- `/models switch <model>` - Switch agent model (saves to config)
- `/models current` - Show current model
- `/models help` - Show model command help

### Development Commands
- `python main.py test` - Run development tests from command line
- `python dev_test.py` - Standalone development test script
- `python main.py --version` - Show version information

## Package Structure

```
ikol1729_agent/
├── agent/              # Core agent logic
│   ├── __init__.py
│   ├── core.py        # DeepSeek API client with streaming
│   ├── search.py      # DuckDuckGo web search
│   ├── code_analyzer.py
│   └── config.yaml    # Configuration file
├── cli/               # Command-line interface
│   ├── __init__.py
│   ├── interface.py   # Chat session management
│   └── input_handlers.py # User input handling
├── ikol1729_agent/    # Package module
│   ├── __init__.py
│   └── __main__.py    # Module entry point
├── agent_config.py    # Hydra-based configuration manager
├── dev_test.py        # Development test suite
├── main.py            # Main entry point with argument parsing
├── pyproject.toml     # Package configuration
└── test_config.py     # Configuration test script
```

## Overview

DeepSeek Agent v0 - Simple Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    DeepSeek Agent v0                         │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                    CLI Layer                         │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │   │
│  │  │   main.py   │  │ interface.py│  │input_handlers│ │   │
│  │  │  (Entry)    │◄─┤ (UI Logic)  │◄─┤ (User Input) │ │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘ │   │
│  └─────────────────────────────────────────────────────┘   │
│                            │                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                    Agent Layer                       │   │
│  │  ┌─────────────┐  ┌─────────────┐                   │   │
│  │  │   core.py   │  │  search.py  │                   │   │
│  │  │ (DeepSeek   │◄─┤ (Web Search)│                   │   │
│  │  │   Chat)     │  │             │                   │   │
│  │  └─────────────┘  └─────────────┘                   │   │
│  └─────────────────────────────────────────────────────┘   │
│                            │                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                 External Services                    │   │
│  │  ┌─────────────┐          ┌─────────────┐          │   │
│  │  │ DeepSeek API│          │ DuckDuckGo  │          │   │
│  │  │   (Chat)    │          │   (Search)  │          │   │
│  │  └─────────────┘          └─────────────┘          │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Simplified Data Flow:

```
User Input
    ↓
CLI Layer (main.py → interface.py → input_handlers.py)
    ↓
Command Parser (/search, /think, /clear, /test, etc.)
    ↓
    ├── If /search → Search Engine (search.py) → DuckDuckGo
    │        ↓
    │    Display Results
    │
    └── If chat → Agent Core (core.py)
            ↓
       DeepSeek API
            ↓
       Stream Response
            ↓
       Display to User
```

## Core Components:

### 1. **Entry Point** (`main.py`)
```
┌─────────────┐
│   main.py   │ ← Starts the application
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ Choose CLI  │ ← prompt_toolkit or fallback
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ Run Chat    │ ← Start interactive session
└─────────────┘
```

### 2. **CLI Interface** (`cli/`)
```
┌─────────────────┐
│   interface.py  │ ← Manages the chat session
├─────────────────┤
│ • Display banner│
│ • Handle commands│
│ • Manage history│
└────────┬────────┘
         │
┌────────▼────────┐
│ input_handlers.py│ ← Get user input
├─────────────────┤
│ • Multi-line    │
│ • Keyboard handling│
│ • Continuation (\\)│
└─────────────────┘
```

### 3. **Agent Core** (`agent/core.py`)
```
┌─────────────────┐
│ DeepSeekChat    │
├─────────────────┤
│ • API calls     │
│ • Stream parsing│
│ • History       │
│ • Thinking mode │
└────────┬────────┘
         │
┌────────▼────────┐
│ Conversation    │ ← Stores chat history
│   History       │
└─────────────────┘
```

### 4. **Search Engine** (`agent/search.py`)
```
┌─────────────────┐
│ Search Engine   │
├─────────────────┤
│ • Async search  │
│ • HTML parsing  │
│ • Caching       │
│ • Rate limiting │
└────────┬────────┘
         │
┌────────▼────────┐
│ DuckDuckGo API  │ ← Web search
└─────────────────┘
```

## Key Interactions:

```
User → CLI → Command → Agent → API → Response → User
         │                    │
         └──→ Search → Web → Results
```

## File Dependencies:

```
main.py
├── cli.interface
│   ├── agent.core
│   │   └── agent.search
│   └── cli.input_handlers
└── dotenv (for .env loading)
```

## Simple Version (Even Simpler):

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│    User     │───▶│     CLI     │───▶│    Agent    │
│   (Input)   │    │  (Interface)│    │   (Brain)   │
└─────────────┘    └──────┬──────┘    └──────┬──────┘
                          │                   │
                    ┌─────▼─────┐       ┌─────▼─────┐
                    │  Commands │       │   Search  │
                    │  Parser   │       │  Engine   │
                    └───────────┘       └───────────┘
```

## In Plain English:

1. **You type something** → CLI captures it
2. **If it's a command** (/search, /think, /test, etc.) → CLI handles it
3. **If it's a question** → Agent sends to DeepSeek API
4. **Agent streams back** answer with thinking process
5. **If you type /search** → Agent searches web and shows results
6. **Everything is saved** in conversation history

## Visual Summary:

```
[You] → [CLI Shell] → [Agent Brain] → [DeepSeek AI]
                │              │
                ├→ [Commands]  ├→ [Web Search]
                │              │
                └→ [History]   └→ [Thinking Mode]
```

This architecture keeps things simple:
- **CLI Layer** talks to you
- **Agent Layer** talks to AI and web
- **Search Layer** finds information online
- **Everything flows** in a clear pipeline