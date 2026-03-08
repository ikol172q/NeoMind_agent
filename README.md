# user_agent - DeepSeek AI Agent

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
- **Code Analysis & Self-Iteration**: Full suite of code analysis commands with safe self-modification capabilities
- **Configuration Management**: Hydra-based configuration with YAML file and environment variable overrides
- **Package Distribution**: Installable via `pip` with optional dependencies

## Installation

### From Local Source (Development)
```bash
# Clone the repository
git clone <repository-url>
cd user_agent

# Install in development mode
pip install -e .

# Install with all optional dependencies
pip install "user-agent[full]"
```

### As a Package
```bash
# Install from PyPI (when published)
pip install user-agent

# Install with full features
pip install "user-agent[full]"
```

### Usage
```bash
# Interactive chat (default)
user-agent

# Alternative: run as a module
python -m user_agent

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

### Task Management Commands
- `/task create <description>` - Create a new task
- `/task list [status]` - List tasks (optional status filter: todo, in_progress, done)
- `/task update <id> <status>` - Update task status
- `/task delete <id>` - Delete task
- `/task clear` - Delete all tasks
- `/task help` - Show task command help

### Planning System Commands
- `/plan <goal>` - Generate a plan for achieving a goal
- `/plan list [status]` - List plans (optional status filter)
- `/plan delete <id>` - Delete plan
- `/plan show <id>` - Show plan details
- `/plan help` - Show plan command help
- `/execute <plan_id>` - Execute a plan step by step

### Advanced Analysis Commands
- `/summarize <text>` - Summarize text or code
- `/translate <text> [to <language>]` - Translate text to another language
- `/generate <prompt>` - Generate content based on prompt
- `/reason <problem>` - Use chain-of-thought reasoning to solve problems
- `/debug <file_path>` - Debug code for bugs and issues
- `/explain <file_path>` - Explain code functionality
- `/refactor <file_path>` - Suggest refactoring improvements for code
- `/grep <pattern> [path]` - Search for text across files
- `/find <pattern> [path]` - Find files matching pattern
- `/switch <model_id>` - Switch to a different model (alternative to `/models switch`)

### Code Analysis & Self-Iteration Commands
- `/code scan [path]` - Scan a codebase for analysis
- `/code summary` - Show codebase summary (size, file types)
- `/code find <pattern>` - Find files matching pattern
- `/code read <file_path>` - Read and display a file
- `/code analyze <file_path>` - Analyze file structure (imports, functions, classes)
- `/code reason <file_path>` - Deep analysis using reasoning model (chain-of-thought)
- `/code search <text>` - Search for text in code files
- `/code changes` - Show pending code changes
- `/code apply` - Apply pending changes (requires confirmation)
- `/code clear` - Clear pending changes
- `/code self-scan` - Scan agent's own codebase
- `/code self-improve [target]` - Suggest improvements to agent's own code
- `/code self-apply` - Apply vetted self-improvements with safety checks

*Note:* The `/code reason` command automatically switches to the `deepseek-reasoner` model for chain-of-thought analysis (temporarily), providing deeper insights into code structure and potential improvements.

### Development Commands
- `python main.py test` - Run development tests from command line
- `python dev_test.py` - Standalone development test script
- `python main.py --version` - Show version information

## Self-Iteration Example

The agent can analyze and improve its own code safely:

1. Scan the agent's own codebase:
   ```
   /code self-scan
   ```

2. Suggest improvements (e.g., add docstrings, fix style):
   ```
   /code self-improve
   ```

3. Review proposed changes:
   ```
   /code changes
   ```

4. Apply changes with safety checks:
   ```
   /code self-apply
   ```

The self-iteration framework includes backups, validation, and rollback mechanisms.

## Self-Iteration Tutorial

This tutorial walks through using the agent's self-modification capabilities to improve its own code.

### Step 1: Scan Your Agent's Codebase
```
/code self-scan
```
This scans the agent's own directory and provides a summary of files and structure.

### Step 2: Suggest Improvements
```
/code self-improve
```
The agent analyzes its own Python files for common improvements: missing docstrings, style issues, potential bugs, and optimization opportunities. Suggestions are added to the pending changes list.

### Step 3: Review Proposed Changes
```
/code changes
```
View all pending changes with descriptions and previews. Each change includes the old and new code snippets.

### Step 4: Apply Changes with Safety Checks
```
/code self-apply
```
Applies all pending changes with comprehensive safety validation:
1. Runs pre‑modification test suite
2. Creates backups of each file
3. Applies changes in dependency order (using the planner)
4. Validates syntax and imports after each change
5. Runs post‑modification tests
6. Logs the change to the journal

If any step fails, the rollback plan is executed and all changes are reverted.

### Step 5: Verify and Iterate
After applying changes, run the agent's test suite to ensure nothing is broken:
```
/test
```
You can repeat the cycle to iteratively improve the codebase.

For more detailed examples and tutorials, see [EXAMPLES.md](EXAMPLES.md).

## Safety Mechanisms

The agent incorporates multiple safety layers to prevent accidental or malicious damage:

### File System Safety
- **Path Validation**: All file operations are checked against a safe workspace; attempts to access system directories or paths outside the workspace are blocked.
- **Sandboxing**: Write operations are restricted to user-approved directories; critical system files are protected.
- **Backup System**: Before modifying any file, a timestamped backup is created automatically.
- **Audit Logging**: All safety-relevant events are logged to `.safety_audit.log` for review.

### Command Safety
- **Shell Command Validation**: The `/run` command validates commands against a allowlist of safe operations; dangerous commands (rm, mv, etc.) are blocked.
- **Code Execution Sandbox**: Python code execution is limited to isolated subprocesses with resource constraints.

### Self-Modification Safety
- **Pre/Post Validation**: Each self-modification is validated for syntax, import integrity, and test suite compliance.
- **Rollback Plans**: The planner automatically generates rollback steps that can revert changes if validation fails.
- **Change Journal**: All modifications are logged with timestamps, descriptions, and backup paths.

## DeepSeek-Reasoner Integration

The agent can leverage DeepSeek's reasoning model (`deepseek-reasoner`) for complex analysis tasks:

- **Automatic Model Switching**: The `/code reason` command automatically switches to `deepseek-reasoner` (temporarily) to perform chain‑of‑thought analysis of code files.
- **Temporary Switching Utility**: The `with_model()` method allows any operation to be run with a different model without affecting the global configuration.
- **Fallback Handling**: If the requested model is unavailable, the agent falls back to the current model gracefully.

This integration enables deeper code understanding, multi‑step reasoning for refactoring suggestions, and more accurate analysis of complex codebases.

## Package Structure

```
user_agent/
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
├── user_agent/    # Package module
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