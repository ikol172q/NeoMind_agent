# Phase 3: Three-Personality Differentiation & Cross-Personality Shared Memory

## Overview

Phase 3 implements a cross-personality memory system that allows NeoMind's three distinct personalities (chat, coding, finance) to share and build upon user context while maintaining their individual behavioral patterns.

### Key Features

✓ **Shared User Context**: All three modes can read and write to a unified memory system
✓ **Behavioral Differentiation**: Each personality has distinct communication style and priorities
✓ **Continuous Learning**: User preferences, facts, patterns, and feedback accumulate over time
✓ **Production-Ready**: Minimal dependencies, thread-safe, works in CLI and Docker
✓ **Backward Compatible**: Existing modes unchanged, only enhanced with memory access

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    User Input                            │
└────┬────────────────────┬────────────────────┬───────────┘
     │                    │                    │
     ▼                    ▼                    ▼
  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
  │ CHAT MODE    │   │ CODING MODE  │   │ FINANCE MODE │
  │              │   │              │   │              │
  │ • Convo tone │   │ • Structured │   │ • Cautious   │
  │ • Remember   │   │ • Sprint mgmt│   │ • Trade rev  │
  │   prefs      │   │ • Guards ON  │   │ • Sources    │
  │ • Mode hints │   │ • Auto-revw  │   │ • Backtests  │
  └──────┬───────┘   └──────┬───────┘   └──────┬───────┘
         │                  │                  │
         │   Shared Memory  │                  │
         └──────────────────┼──────────────────┘
                            ▼
          ┌────────────────────────────────┐
          │    SharedMemory (SQLite)       │
          │                                │
          │ • Preferences                  │
          │ • Facts (categories)           │
          │ • Patterns (frequency counts)  │
          │ • Feedback (corrections)       │
          │                                │
          │ ~/.neomind/shared_memory.db    │
          └────────────────────────────────┘
```

## Components

### 1. `agent/memory/shared_memory.py`

The core SharedMemory class that manages cross-personality data persistence.

**Supported Data Types**:

- **Preferences**: User settings (timezone, language, name, etc.)
- **Facts**: Semantic knowledge about the user (work, education, interests)
- **Patterns**: Behavioral patterns with frequency counts
- **Feedback**: User corrections and preferences

**Key Methods**:

```python
# Preferences
memory.set_preference(key, value, source_mode)
memory.get_preference(key, default=None)
memory.get_all_preferences()

# Facts
memory.remember_fact(category, fact, source_mode)
memory.recall_facts(category=None, limit=20)

# Patterns
memory.record_pattern(pattern_type, pattern_value, source_mode)
memory.get_patterns(pattern_type=None, limit=50)

# Feedback
memory.record_feedback(feedback_type, content, source_mode)
memory.get_recent_feedback(limit=10)

# Context for LLM
context = memory.get_context_summary(mode=None, max_tokens=500)

# Utilities
export = memory.export_json()
memory.import_json(export)
memory.clear_all()
stats = memory.get_stats()
```

### 2. Configuration Updates

#### `agent/config/chat.yaml`
New behavioral directives:
- Conversational tone (avoid bullet points)
- Auto-remember user preferences
- Mode-switch suggestions
- New commands: `/remember`, `/recall`, `/preferences`

#### `agent/config/coding.yaml`
New behavioral directives:
- Structured output (code blocks, diffs)
- Sprint auto-activation
- Guards (safety checks) ON by default
- Auto-review before commits
- New commands: `/perf`, `/deploy`, `/ship`, `/remember`, `/recall`

#### `agent/config/fin.yaml`
New behavioral directives:
- Cautious tone for financial decisions
- Mandatory trade-review workflow
- Data sources always cited
- Paper trading emphasis
- New commands: `/backtest`, `/allocation`, `/remember`, `/recall`

### 3. Tests

**File**: `tests/test_shared_memory.py`

Comprehensive test coverage (44 tests):

- ✓ Preference CRUD operations
- ✓ Fact storage and categorization
- ✓ Pattern frequency tracking
- ✓ Feedback recording
- ✓ Context summary generation
- ✓ SQLite persistence across instances
- ✓ Concurrent access safety (threading)
- ✓ JSON export/import
- ✓ Edge cases (Unicode, special chars, long values)
- ✓ Integration across three modes

Run tests:
```bash
pytest tests/test_shared_memory.py -v
```

All tests pass: ✓ 44/44

## Usage Examples

### Example 1: Basic Three-Mode Collaboration

```python
from agent.memory import SharedMemory

memory = SharedMemory()

# CHAT MODE: learns user info
memory.set_preference("timezone", "UTC", "chat")
memory.remember_fact("work", "SDE at Google", "chat")

# CODING MODE: reads and adds patterns
tz = memory.get_preference("timezone")  # Can access chat's preference
memory.record_pattern("language", "Python", "coding")

# FINANCE MODE: reads all and makes decisions
facts = memory.recall_facts("work")  # Can access chat's facts
patterns = memory.get_patterns("language")  # Can see coding's patterns

# All modes get personalized context
context = memory.get_context_summary("coding")
# Use in system prompt: f"User context:\n{context}\n\nRespond accordingly..."
```

### Example 2: Preference Tracking Across Sessions

```python
# Session 1: Chat mode
memory = SharedMemory()
memory.set_preference("coffee", "oat latte", "chat")
memory.close()

# Session 2: Coding mode (next day)
memory = SharedMemory()
coffee = memory.get_preference("coffee")  # Returns "oat latte"
# Coding mode can say: "Starting a session. I remember you like oat latte!"
memory.close()
```

### Example 3: Pattern Recognition for Recommendations

```python
# Over many sessions, finance learns patterns
memory.record_pattern("frequent_stock", "AAPL", "fin")
memory.record_pattern("frequent_stock", "AAPL", "fin")
memory.record_pattern("frequent_stock", "MSFT", "fin")

# Later, can make informed recommendations
patterns = memory.get_patterns("frequent_stock")
# Returns: [AAPL (count=2), MSFT (count=1)]
# Finance can say: "You've been interested in AAPL and MSFT recently..."
```

### Example 4: User Feedback Integration

```python
# User corrects a mistake
memory.record_feedback("correction", "AAPL not APPL", "chat")

# Later modes see the feedback in context summary
context = memory.get_context_summary("fin")
# Context includes: "Recent Corrections: AAPL not APPL"
# Fin mode won't make the same mistake again
```

## Integration with Core Agent

### In `agent/core.py` (Initialization)

```python
from agent.memory import SharedMemory

class NeoMindAgent:
    def __init__(self, mode="chat"):
        self.mode = mode
        self.memory = SharedMemory()  # Initialize shared memory
        # ... rest of init
```

### In Mode Detection (After User Input)

```python
def process_input(self, user_input):
    # Detect preferences in natural text
    if "timezone" in user_input and "is" in user_input:
        # Extract and store
        tz = extract_timezone(user_input)
        self.memory.set_preference("timezone", tz, self.mode)

    # Pattern tracking
    if self.mode == "coding":
        lang = detect_language(user_input)
        self.memory.record_pattern("language", lang, "coding")
```

### Before LLM Calls (System Prompt Injection)

```python
def get_system_prompt(self):
    base_prompt = self.load_config()[self.mode]["system_prompt"]

    # Inject user context
    context = self.memory.get_context_summary(self.mode, max_tokens=500)

    if context:
        base_prompt += f"\n\n## User Context (Learned from previous interactions):\n{context}"

    return base_prompt
```

### New Commands Integration

```python
def handle_command(self, cmd):
    if cmd == "remember":
        # Explicit memory save
        fact = input("What should I remember? ")
        category = input("Category (work/education/interests)? ")
        self.memory.remember_fact(category, fact, self.mode)
        print(f"✓ Remembered: {fact}")

    elif cmd == "recall":
        # Retrieve memories
        facts = self.memory.recall_facts(limit=10)
        for fact in facts:
            print(f"  - [{fact['category']}] {fact['fact']}")

    elif cmd == "preferences":
        # Show user preferences
        prefs = self.memory.get_all_preferences()
        for key, data in prefs.items():
            print(f"  - {key}: {data['value']}")
```

## Storage Details

### Database Location

- **Default**: `~/.neomind/shared_memory.db`
- **Env override**: `NEOMIND_MEMORY_DIR` (will use `$NEOMIND_MEMORY_DIR/shared_memory.db`)
- **Docker**: `/data/neomind/db/shared_memory.db` (if available)

### Schema

Four tables:

1. **preferences**
   ```sql
   key TEXT PRIMARY KEY
   value TEXT NOT NULL
   source_mode TEXT NOT NULL
   updated_at TEXT NOT NULL
   ```

2. **facts**
   ```sql
   id INTEGER PRIMARY KEY
   category TEXT NOT NULL
   fact TEXT NOT NULL
   source_mode TEXT NOT NULL
   created_at TEXT NOT NULL
   ```

3. **patterns**
   ```sql
   id INTEGER PRIMARY KEY
   pattern_type TEXT NOT NULL
   pattern_value TEXT NOT NULL
   count INTEGER DEFAULT 1
   source_mode TEXT NOT NULL
   updated_at TEXT NOT NULL
   ```

4. **feedback**
   ```sql
   id INTEGER PRIMARY KEY
   feedback_type TEXT NOT NULL
   content TEXT NOT NULL
   source_mode TEXT NOT NULL
   created_at TEXT NOT NULL
   ```

### Concurrency & Safety

- **WAL Mode**: Enabled for safe concurrent access
- **Thread-Local Connections**: Each thread gets its own SQLite connection
- **Atomic Writes**: All operations committed immediately
- **Timeout**: 5-second lock timeout for contention
- **No External Dependencies**: Uses only Python stdlib + sqlite3

## Testing

All 44 tests pass with excellent coverage:

```
Test Categories:
  • Preferences: 5 tests
  • Facts: 5 tests
  • Patterns: 5 tests
  • Feedback: 4 tests
  • Context Summary: 7 tests
  • Persistence: 4 tests
  • Concurrency: 2 tests
  • Utilities: 4 tests
  • Edge Cases: 6 tests
  • Integration: 2 tests
```

Run the full test suite:
```bash
python -m pytest tests/test_shared_memory.py -v
```

## Behavioral Differentiation

### CHAT Personality
- Conversational, natural language responses
- Remembers user preferences (timezone, language, name)
- Suggests mode switches when appropriate
- Tracks communication patterns
- Provides context-aware responses

### CODING Personality
- Structured output with code blocks and diffs
- Activates sprint mode for multi-step tasks
- Guards (safety checks) ON by default
- Auto-reviews code before commits
- Tracks language/framework preferences
- Suggests performance optimizations

### FINANCE Personality
- Cautious tone in financial advice
- Mandatory review for trade recommendations
- Always cites data sources with timestamps
- Emphasizes paper trading before live trading
- Tracks investment patterns and preferences
- Maintains prediction accuracy metrics

## Example Output

### Chat Mode Context
```
**User Preferences:**
  - timezone: America/Los_Angeles
  - language: en
  - name: Alice
**About User:**
  - work: Senior Software Engineer at Google
  - education: BS Computer Science from MIT
**Patterns:**
  - language: Python (x3)
**Recent Corrections:**
  - AAPL not APPL
```

### Coding Mode Context (prioritizes coding patterns)
```
**User Preferences:**
  - timezone: America/Los_Angeles
**About User:**
  - work: Senior Software Engineer at Google [chat]
**Patterns:**
  - language: Python (x3)
  - framework: PyTorch (x1)
  - stock: AAPL (x2) [fin]
```

### Finance Mode Context (prioritizes finance patterns)
```
**User Preferences:**
  - timezone: America/Los_Angeles
**About User:**
  - education: BS Computer Science from MIT [chat]
**Patterns:**
  - frequent_stock: AAPL (x2)
  - risk_level: moderate (x1)
  - language: Python (x3) [coding]
```

## Performance Characteristics

- **Preference Lookup**: O(1) - direct key lookup
- **Fact Recall**: O(n) where n = facts in category (typically < 50)
- **Pattern Retrieval**: O(p log p) where p = patterns (sorted by frequency)
- **Context Summary**: O(data) - linear scan with truncation
- **Concurrent Access**: Lock-free reads, serialized writes (WAL mode)
- **Memory Footprint**: Minimal (SQLite overhead only)

## Backward Compatibility

✓ Existing modes work without changes
✓ Memory system is optional (graceful degradation)
✓ No breaking changes to core.py interface
✓ Config files only enhanced, not modified in breaking ways

## Future Extensions

Potential Phase 4+ features:

- [ ] Encryption for sensitive financial data
- [ ] Cross-device sync (cloud backup)
- [ ] Temporal context (remember when things happened)
- [ ] Semantic similarity search (find related facts)
- [ ] Prediction accuracy tracking
- [ ] User learning curves (adapt difficulty over time)
- [ ] Collaborative mode (multi-user memories)

## Files Modified/Created

**Created**:
- `agent/memory/shared_memory.py` - Core SharedMemory class
- `agent/memory/__init__.py` - Package initialization
- `agent/memory/example_usage.py` - Usage examples and demos
- `agent/memory/PHASE3_INTEGRATION.md` - This file
- `tests/test_shared_memory.py` - 44 comprehensive tests

**Modified**:
- `agent/config/chat.yaml` - Added behavioral directives and commands
- `agent/config/coding.yaml` - Added behavioral directives and commands
- `agent/config/fin.yaml` - Added behavioral directives and commands

## Getting Started

1. **Import in your code**:
   ```python
   from agent.memory import SharedMemory
   memory = SharedMemory()
   ```

2. **Store user data**:
   ```python
   memory.set_preference("timezone", "UTC", "chat")
   memory.remember_fact("work", "SDE at Google", "chat")
   ```

3. **Retrieve in other modes**:
   ```python
   tz = memory.get_preference("timezone")  # Works from any mode
   facts = memory.recall_facts("work")
   ```

4. **Get context for system prompt**:
   ```python
   context = memory.get_context_summary("coding")
   system_prompt = f"Base prompt...\n\n{context}"
   ```

5. **Run tests**:
   ```bash
   pytest tests/test_shared_memory.py -v
   ```

## Support & Debugging

**Check database health**:
```python
memory = SharedMemory()
stats = memory.get_stats()
print(stats)  # {"preferences": 3, "facts": 5, ...}
memory.close()
```

**Export for backup**:
```python
export = memory.export_json()
with open("memory_backup.json", "w") as f:
    json.dump(export, f)
```

**Restore from backup**:
```python
import json
with open("memory_backup.json") as f:
    data = json.load(f)
memory = SharedMemory()
memory.import_json(data)
memory.close()
```

**Clear everything** (development only):
```python
memory = SharedMemory()
memory.clear_all()
memory.close()
```

---

**Status**: ✓ Production Ready
**Test Coverage**: 44/44 tests passing
**Dependencies**: sqlite3 (stdlib only)
**Platforms**: Linux, macOS, Windows, Docker
