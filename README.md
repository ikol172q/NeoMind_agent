# user_agent
llm based agent to enhance personal usage. This is the readme that's used for testing for now.
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
Command Parser (/search, /think, /clear, etc.)
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
2. **If it's a command** (/search, /think, etc.) → CLI handles it
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