# NeoMind Feature Documentation

Complete module reference for the NeoMind agent project. Each module includes purpose, usage patterns, pros/cons, and optimization opportunities.

---

## Core Agent Modules

### Module: NeoMindAgent (core.py)
**File:** `/agent/core.py` (7,301 lines)
**Purpose:** Main agent orchestrator combining all subsystems (tools, safety, search, planning, evolution) into a unified multi-mode AI assistant (chat, coding, finance).
**Key Classes/Functions:**
- `NeoMindAgent` - Main class that initializes all components
- `run_interaction()` - Main loop handling user input
- `execute_tool_call()` - Execute parsed tool from LLM output
- `handle_context_limit()` - Context management with compression
- Mode switching: chat, coding, finance modes with different behaviors
- Integration with CodeAnalyzer, SelfIteration, TaskManager, Planner
- Safety checks before any operations

**Usage Example:**
```python
from agent.core import NeoMindAgent

agent = NeoMindAgent(
    workspace_root="/path/to/project",
    mode="coding"
)
# User query handling happens in run_interaction()
agent.run_interaction("Show me test results for app")
```

**Pros:**
- Unified interface for all agent capabilities (tools, safety, search, planning)
- Graceful degradation if optional modules not available (evolution, workflow, etc.)
- Multi-mode support allows different personalities for different tasks
- Context-aware tool suggestions based on current operation
- Built-in safety checks prevent dangerous operations

**Cons / Known Limitations:**
- Very large monolithic file (7,300+ lines) difficult to navigate
- Multiple import dependencies (15+ submodules) increase startup time
- No request cancellation mechanism mid-execution
- Limited rollback if multiple operations in sequence partially fail
- Context limit handling is reactive, not preventive

**Optimization Opportunities:**
- Split core.py into smaller focused modules (orchestrator, mode_handlers, tool_dispatcher)
- Lazy-load optional modules (evolution, workflow) only when explicitly enabled
- Implement operation batching for sequential tool calls
- Add predictive context monitoring to warn earlier
- Cache parsed imports and module discovery results

---

### Module: Tool Parser
**File:** `/agent/tool_parser.py` (283 lines)
**Purpose:** Parses LLM responses to extract tool calls in structured XML format or legacy bash blocks, with hallucination filtering.
**Key Classes/Functions:**
- `ToolCall` - Represents a parsed tool call with name, params, raw text
- `ToolCallParser` - Main parser supporting 3 formats: structured XML, bash blocks, python blocks
- `parse()` - Extract first tool call from response
- `_parse_structured()` - Parse `<tool_call>{"tool":"Name","params":{...}}</tool_call>`
- `_parse_legacy_bash()` - Parse ```bash ... ``` blocks
- `_parse_python_block()` - Parse ```python ... ``` blocks
- `format_tool_result()` - Format execution result back for LLM

**Usage Example:**
```python
parser = ToolCallParser()
response = "Let me read the file <tool_call>{\"tool\":\"Read\",\"params\":{\"path\":\"main.py\"}}</tool_call>"
tool_call = parser.parse(response)
if tool_call:
    print(f"Tool: {tool_call.tool_name}, Params: {tool_call.params}")
```

**Pros:**
- Supports both structured (preferred) and legacy formats for compatibility
- Filters hallucinated output (detects fake ``` blocks after output)
- Handles malformed JSON gracefully
- Only extracts first tool call (prevents accidental multi-execution)
- Low overhead, fast parsing

**Cons / Known Limitations:**
- Legacy bash parsing may miss complex shell syntax
- Python block wrapping could escape incorrectly with certain quotes
- No validation that params match tool schema at parse time
- Comments-only blocks are filtered but detection is simplistic

**Optimization Opportunities:**
- Pre-compile regex patterns at module level (currently done, good)
- Add streaming parser for large responses
- Validate params against schema during parsing phase
- Support for batch tool calls (multiple per response)

---

### Module: Tool Implementations
**File:** `/agent/tools.py` (730 lines)
**Purpose:** Implements built-in tools (Bash, Read, Write, Edit, Glob, Grep) with structured schemas and unified ToolResult output.
**Key Classes/Functions:**
- `ToolResult` - Standard result object with success, output, error, metadata
- `ToolRegistry` - Registry of all tools with schemas
- Tool implementations: `_exec_bash()`, `_exec_read()`, `_exec_write()`, `_exec_edit()`, `_exec_glob()`, `_exec_grep()`
- Persistent bash session with state preservation across calls

**Usage Example:**
```python
registry = ToolRegistry(working_dir="/project")
result = registry.execute_tool("Read", {"path": "src/main.py"})
if result.success:
    lines = result.metadata.get("lines_read", 0)
    print(f"Read {lines} lines from {result.output}")
```

**Pros:**
- Unified ToolResult format across all tools
- Persistent bash preserves state (cd, export, source)
- Metadata includes structured info (lines_read, files_matched, exit_code)
- Built-in timeouts prevent hanging
- Output auto-truncation (30K chars with middle-truncation)

**Cons / Known Limitations:**
- Bash redirection handling could be more robust
- Edit tool requires exact string match (line number editing not available)
- No async execution (tools are blocking)
- Glob performance degrades with very large directories
- Grep doesn't support some advanced ripgrep features

**Optimization Opportunities:**
- Async tool execution for parallel processing
- Implement line-number based editing in Edit tool
- Cache glob results for repeated patterns
- Add pipeline operator for chaining tools
- Implement Bash stdout buffer pooling for large outputs

---

### Module: Tool Schema
**File:** `/agent/tool_schema.py` (269 lines)
**Purpose:** Formalized tool definitions with typed parameters, permission levels, and auto-generated system prompt sections.
**Key Classes/Functions:**
- `ParamType` - Enum (STRING, INTEGER, BOOLEAN, FLOAT)
- `PermissionLevel` - Enum (READ_ONLY, WRITE, EXECUTE, DESTRUCTIVE)
- `ToolParam` - Single parameter definition
- `ToolDefinition` - Complete tool definition with schema and execute function
- `generate_tool_prompt()` - Auto-generate system prompt section from definitions

**Usage Example:**
```python
from agent.tool_schema import ToolDefinition, ToolParam, ParamType, PermissionLevel

my_tool = ToolDefinition(
    name="MyTool",
    description="Does something useful",
    parameters=[
        ToolParam("input", ParamType.STRING, "Input text", required=True),
        ToolParam("count", ParamType.INTEGER, "Number of times", required=False, default=1)
    ],
    permission_level=PermissionLevel.WRITE,
    execute=my_execute_function
)
```

**Pros:**
- Single source of truth for tool definitions
- Automatic system prompt generation prevents out-of-sync docs
- Type validation before execution
- Permission levels enable fine-grained access control
- Enum constraints enforced at parse time

**Cons / Known Limitations:**
- Limited to basic types (STRING, INTEGER, BOOLEAN, FLOAT)
- No support for complex nested parameter types
- Enum validation is shallow (no semantic validation)
- No support for tool dependencies or prerequisites
- Default values only work for optional parameters

**Optimization Opportunities:**
- Support complex types: List, Dict, Union types
- Add semantic validation callbacks (e.g., file path must exist)
- Implement tool dependency graph for automatic ordering
- Cache validation results for repeated params
- Add deprecation metadata for legacy tools

---

### Module: Persistent Bash
**File:** `/agent/persistent_bash.py` (265 lines)
**Purpose:** Maintains a single bash process across all shell commands, preserving cd, export, source state.
**Key Classes/Functions:**
- `PersistentBash` - Persistent bash session manager
- `execute()` - Run command in the session with timeout
- `get_cwd()` - Get current working directory
- `close()` - Cleanup bash process
- Sentinel pattern for detecting command completion
- Non-blocking stdout/stderr collection with threads

**Usage Example:**
```python
bash = PersistentBash(working_dir="/project", timeout=120)
bash.execute("cd src")
result = bash.execute("ls")  # Shows src/ contents (cd persisted)
result = bash.execute("export MY_VAR=value")
result = bash.execute("echo $MY_VAR")  # Prints "value"
bash.close()
```

**Pros:**
- True state persistence across commands (cd, export, source)
- Efficient - single process reused, no startup overhead
- Robust sentinel-based completion detection
- Non-blocking I/O with reader threads prevents deadlocks
- Graceful handling of process death (auto-restart on next call)

**Cons / Known Limitations:**
- Middle-truncation of large outputs loses end context
- No built-in command history or recall
- Timeout applies per-command, not cumulative
- SIGINT/SIGTERM may not always propagate cleanly
- No shell option persistence (set -e, etc.)

**Optimization Opportunities:**
- Implement circular buffer for partial history preservation
- Add readline integration for interactive commands
- Support multiple bash sessions (per-workspace)
- Cache working directory to avoid repeated pwd calls
- Implement command timeout with partial output recovery

---

### Module: Context Manager
**File:** `/agent/context_manager.py` (279 lines)
**Purpose:** Manages conversation token counting, context limits, and history compression strategies.
**Key Classes/Functions:**
- `ContextManager` - Main class for token/context management
- `count_tokens()` - Count tokens in text (uses tiktoken if available)
- `count_conversation_tokens()` - Total tokens in conversation
- `get_context_usage()` - Statistics on current usage
- `compress_history()` - Reduce history size (truncate or summarize)
- `interactive_context_management()` - Prompt user when limits approached

**Usage Example:**
```python
from agent.context_manager import ContextManager

context = ContextManager(conversation_history=messages)
usage = context.get_context_usage()
print(f"Using {usage['percent_used']:.1%} of context")

if usage['is_near_limit']:
    result = context.compress_history(strategy="truncate")
    print(f"Compressed to {result['compressed_tokens']} tokens")
```

**Pros:**
- Accurate token counting with tiktoken
- Fallback estimation (4 chars/token) when tiktoken unavailable
- Multiple compression strategies (truncate, summarize)
- System messages preserved during compression
- Interactive prompts let user decide on action

**Cons / Known Limitations:**
- Summarization strategy not implemented (falls back to truncation)
- No smart context prioritization (keeps recent messages equally weighted)
- No knowledge distillation to extract only essential info
- Token count estimation fallback is inaccurate (~25% error)
- Compression happens after limit reached, not predictively

**Optimization Opportunities:**
- Implement actual summarization with LLM
- Priority-weighted compression (keep important contexts)
- Predictive compression warnings with estimated tokens for next response
- Context window optimization per model (gpt-4 vs claude, etc.)
- Checkpointing strategy for very long conversations

---

### Module: Safety Manager
**File:** `/agent/safety.py` (414 lines)
**Purpose:** Enforces sandboxing, validates file operations, blocks dangerous patterns, and maintains audit logs.
**Key Classes/Functions:**
- `SafetyManager` - Main safety enforcement class
- `is_path_safe()` - Validate path for read/write/delete/execute
- `is_command_safe()` - Block dangerous command patterns
- `check_file_size()` - Enforce max file size limits
- `log_operation()` - Audit log entry creation
- Block lists: dangerous extensions, system directories, dangerous patterns

**Usage Example:**
```python
from agent.safety import SafetyManager

safety = SafetyManager(
    workspace_root="/project",
    audit_log="/project/.safety_audit.log"
)

# Check if operation is safe
safe, reason = safety.is_path_safe("/project/src/main.py", "read")
if safe:
    with open("/project/src/main.py") as f:
        content = f.read()
else:
    print(f"Operation blocked: {reason}")
```

**Pros:**
- Comprehensive blocking: 20+ dangerous extensions, key patterns
- Workspace boundary enforcement prevents escape
- File size limits prevent DoS attacks
- Audit log tracks all operations with timestamps
- Additional checks for delete (prevent bulk deletion)

**Cons / Known Limitations:**
- Hardcoded dangerous patterns may false-positive
- No per-file permission customization
- Audit log grows unbounded (no rotation)
- System directory list is Linux/Windows focused (incomplete for macOS)
- No support for file ACLs or SELinux contexts

**Optimization Opportunities:**
- Whitelist approach instead of blacklist (safer)
- Implement audit log rotation (daily, size-based)
- Add policy configuration file for customization
- Support for symbolic link following safety
- Rate limiting on audit log writes

---

### Module: Command Executor
**File:** `/agent/command_executor.py` (331 lines)
**Purpose:** Safe execution of shell commands with timeout, output limits, and dangerous pattern detection.
**Key Classes/Functions:**
- `CommandExecutor` - Safe command execution wrapper
- `is_command_safe()` - Check dangerous patterns
- `execute()` - Run command with safety checks
- `execute_safe()` - Standalone safe execution function
- `execute_git_safe()` - Git-specific safety (blocks reset --hard, etc.)
- Dangerous pattern lists: rm -rf, format, dd, fork bomb, sudo, curl, etc.

**Usage Example:**
```python
from agent.command_executor import CommandExecutor, execute_safe

executor = CommandExecutor(allowlist_mode=False, timeout=30)
result = executor.execute("ls -la /project")

# Or use standalone function
result = execute_safe("git status")
if result['success']:
    print(result['stdout'])
else:
    print(f"Error: {result['error_message']}")
```

**Pros:**
- Blocks 25+ dangerous patterns (rm -rf, format, dd, fork bombs)
- Git-specific safety (blocks force push, hard reset)
- Optional allowlist mode restricts to known commands
- Rate limiting prevents rapid command spam
- Output size limits prevent memory exhaustion

**Cons / Known Limitations:**
- Pattern matching is string-based, not semantic
- Complex shell tricks might bypass patterns
- No stdin/stdout piping support
- No job control (no suspend/background)
- Allowlist is hardcoded (no custom extension)

**Optimization Opportunities:**
- Parse command AST instead of string patterns
- Support safe piping with validated receivers
- Implement resource limits (CPU, memory)
- Add sandboxing with seccomp/AppArmor
- Configuration file for custom dangerous patterns

---

### Module: Code Analyzer
**File:** `/agent/code_analyzer.py` (397 lines)
**Purpose:** Analyzes codebases to understand structure, find files, detect patterns, and suggest fixes.
**Key Classes/Functions:**
- `CodeAnalyzer` - Main analysis class
- `count_files()` - Get file/directory count
- `find_code_files()` - Find files by pattern
- `analyze_file()` - Parse and analyze single file
- `find_pattern()` - Semantic search in code
- `suggest_fixes()` - AI-driven issue suggestions

**Usage Example:**
```python
from agent.code_analyzer import CodeAnalyzer

analyzer = CodeAnalyzer(root_path="/project")
files = analyzer.find_code_files(pattern="*.py")
print(f"Found {len(files)} Python files")

analysis = analyzer.analyze_file("src/main.py")
print(f"Complexity: {analysis['complexity']}")
```

**Pros:**
- Smart file filtering (ignores __pycache__, .git, etc.)
- Binary file detection by extension
- File metadata caching for performance
- Supports 40+ code file extensions
- Integration with SafetyManager for restricted reads

**Cons / Known Limitations:**
- Simple heuristic-based ignore patterns (not .gitignore aware)
- No actual semantic analysis (just file enumeration)
- Large codebase warning but no performance scaling
- Pattern matching is regex-only (no AST-based search)
- No support for compiled languages (jar, class files)

**Optimization Opportunities:**
- Respect .gitignore and .agentignore patterns
- Implement actual AST-based code analysis
- Incremental scanning with file hash tracking
- Parallel file analysis for large codebases
- Integration with language servers for semantic queries

---

### Module: Formatter
**File:** `/agent/formatter.py` (190 lines)
**Purpose:** Standardized output formatting with emojis, colors, and consistent spacing.
**Key Classes/Functions:**
- `Formatter` - Main formatting class
- `success()`, `error()`, `warning()`, `info()` - Message types
- `header()`, `section()` - Structural formatting
- `table()` - Simple tabular output
- `code_block()` - Code snippet formatting
- Global functions: `success()`, `error()`, `header()`, etc.

**Usage Example:**
```python
from agent.formatter import Formatter, success, error

fmt = Formatter()
print(fmt.success("Operation completed"))
print(fmt.warning("This might be risky"))
print(fmt.code_block("python\nprint('hello')", language="python"))

# Global functions
print(success("All tests passed"))
print(error("Something went wrong"))
```

**Pros:**
- Consistent visual feedback across all operations
- Auto-detects terminal capabilities (colors, emojis)
- ANSI color codes for colored output
- Simple table formatting with column alignment
- Low overhead, pure string operations

**Cons / Known Limitations:**
- Table formatting is basic (no cell wrapping)
- No progress bar support
- Limited emoji set (no customization)
- Colors depend on terminal support (fallback to no-color)
- No indentation level support

**Optimization Opportunities:**
- Add progress bar with percentage/ETA
- Rich table formatting with borders
- Custom emoji sets per theme
- Structured output (JSON, CSV options)
- Theme system for different preferences

---

### Module: Help System
**File:** `/agent/help_system.py` (269 lines)
**Purpose:** Comprehensive command documentation with usage patterns and examples.
**Key Classes/Functions:**
- `HelpSystem` - Main help documentation class
- `get_help()` - Retrieve help for specific command
- `_build_help_texts()` - Build comprehensive help dictionary
- Command help templates: write, edit, read, run, git, code, search, etc.

**Usage Example:**
```python
from agent.help_system import HelpSystem, get_help

help_system = HelpSystem()
help_text = help_system.get_help("code")
print(help_text)

# Or global function
print(get_help("write"))
```

**Pros:**
- 30+ commands documented with usage and examples
- Consistent format across all commands
- Integrated with Formatter for styled output
- Examples show actual usage patterns
- Easy to extend with new commands

**Cons / Known Limitations:**
- Help texts are hardcoded (not data-driven)
- No hierarchical help (subcommands not shown)
- Limited to basic text formatting
- No interactive help (drill-down)
- No search across help texts

**Optimization Opportunities:**
- Move help texts to YAML/JSON file
- Implement command hierarchy
- Add interactive help with fuzzy search
- Generate help from ToolDefinitions automatically
- Support multi-language help texts

---

### Module: Natural Language Interpreter
**File:** `/agent/natural_language.py` (308 lines)
**Purpose:** Interprets natural language commands into CLI commands with confidence scoring.
**Key Classes/Functions:**
- `NaturalLanguageInterpreter` - Main interpreter class
- `interpret()` - Convert natural language to CLI command
- `_build_patterns()` - Build regex patterns for command detection
- Pattern categories: search, file operations, code analysis, planning, etc.

**Usage Example:**
```python
from agent.natural_language import NaturalLanguageInterpreter

interpreter = NaturalLanguageInterpreter(confidence_threshold=0.8)
command, confidence = interpreter.interpret("Find all Python files")
print(f"Command: {command} (confidence: {confidence})")
# Output: ("/code scan *.py", 0.95)
```

**Pros:**
- 80+ patterns covering common natural language phrasing
- Confidence scores indicate reliability
- Supports variations of commands (synonyms)
- Category-based organization for maintainability
- Threshold filtering prevents false positives

**Cons / Known Limitations:**
- Pattern matching is regex-based (limited semantic understanding)
- Confidence scores are hardcoded (not learned)
- No context awareness (doesn't remember previous queries)
- Many patterns are strict (must match closely)
- No support for multi-step commands

**Optimization Opportunities:**
- Replace regex with transformer-based NLU
- Learn confidence scores from user feedback
- Implement context stack for multi-turn queries
- Add fuzzy matching for typos/variations
- Support for voice commands with ASR

---

### Module: Planner
**File:** `/agent/planner.py` (438 lines)
**Purpose:** Plans code modifications with dependency analysis and rollback capabilities.
**Key Classes/Functions:**
- `Planner` - Main planning class
- `extract_imports()` - Extract module imports from Python files
- `build_dependency_graph()` - Create dependency graph between files
- `plan_changes()` - Order modifications respecting dependencies
- `GoalPlanner` - Higher-level goal decomposition
- Change application and rollback support

**Usage Example:**
```python
from agent.planner import Planner

planner = Planner(root_path="/project")
files = ["src/main.py", "src/utils.py"]
deps = planner.build_dependency_graph(files)
# deps["src/main.py"] = {"utils"} (depends on utils)

plan = planner.plan_changes(files)
for step in plan:
    print(f"Step {step['order']}: Modify {step['file']}")
```

**Pros:**
- Respects import dependencies for safe modification order
- Supports rollback to previous state
- Change journaling for audit trail
- Handles circular dependencies gracefully
- Per-file backup before modifications

**Cons / Known Limitations:**
- Only works with Python (AST-based)
- No cross-language dependency tracking
- Module name to file mapping is simplistic
- Doesn't detect dynamic imports (importlib)
- No transaction atomicity (partial failure not handled)

**Optimization Opportunities:**
- Extend to JavaScript, Java, Go with language-specific parsers
- Detect dynamic imports with static analysis
- Implement transactional changes (all-or-nothing)
- Automatic diff generation for changes
- Dependency caching with file hash tracking

---

### Module: Search Engine (Legacy)
**File:** `/agent/search_legacy.py` (255 lines)
**Purpose:** Optimized DuckDuckGo search with caching, async support, and time-sensitivity detection.
**Key Classes/Functions:**
- `OptimizedDuckDuckGoSearch` - Main search class
- `should_search()` - Detect if query needs fresh results
- `cache_result()` - Cache results with timestamp
- `get_cached_result()` - Retrieve cached results
- `search()` - Async search with result extraction

**Usage Example:**
```python
from agent.search_legacy import OptimizedDuckDuckGoSearch

search = OptimizedDuckDuckGoSearch()
if search.should_search("What's the latest Bitcoin price?"):
    results = await search.search("Bitcoin price today")
    for result in results:
        print(f"{result['title']}: {result['snippet']}")
```

**Pros:**
- Smart time-sensitivity detection (news, prices, weather)
- Result caching with expiration
- Async execution prevents blocking
- 30+ trigger keywords for automatic searching
- Works without API keys

**Cons / Known Limitations:**
- Deprecated (replaced by UniversalSearchEngine)
- Single source only (DuckDuckGo)
- No reranking or deduplication
- Cache expiration is global (no per-query TTL)
- Limited metadata (title, snippet only)

**Optimization Opportunities:**
- Migrate queries to UniversalSearchEngine
- Implement per-domain cache expiration
- Add result quality scoring
- Support for image/video searches
- Integration with local caches

---

### Module: Search Engine (Universal)
**File:** `/agent/search/engine.py` (100+ lines, main orchestrator)
**Purpose:** Multi-source search engine aggregating results from 12+ sources with reranking, caching, and temporal scoring.
**Key Classes/Functions:**
- `UniversalSearchEngine` - Main orchestrator
- `compute_recency_boost()` - Domain-specific recency scoring
- `search()` - Execute multi-source search
- Parallel execution of all enabled sources
- Result merging with Reciprocal Rank Fusion
- Semantic reranking with FlashRank

**Usage Example:**
```python
from agent.search.engine import UniversalSearchEngine

engine = UniversalSearchEngine(domain="finance")
results = await engine.search("Apple stock price", limit=10)
for result in results:
    print(f"{result['title']} ({result['source']})")
```

**Pros:**
- 12+ parallel sources (DDG, Google News, NewsAPI, Brave, Serper, etc.)
- Graceful degradation without API keys
- Temporal ranking boosts recent results
- Semantic reranking with FlashRank
- Full-text extraction with Trafilatura
- Caching at multiple levels (cache, disk)

**Cons / Known Limitations:**
- Complex pipeline with many dependencies
- API rate limiting requires careful throttling
- Trafilatura extraction may timeout on slow sites
- Tier 2/3 sources require API keys
- Reranking adds latency (300-500ms)

**Optimization Opportunities:**
- Implement lazy loading of sources
- Cache reranking results
- Add result deduplication
- Progressive result streaming
- Query optimization per source

---

### Module: Self-Iteration
**File:** `/agent/self_iteration.py` (326 lines)
**Purpose:** Safe self-modification framework with backup, validation, rollback, and change journaling.
**Key Classes/Functions:**
- `SelfIteration` - Main self-modification coordinator
- `backup_file()` - Create timestamped backup
- `validate_syntax()` - Check Python syntax validity
- `validate_imports()` - Test imports in subprocess
- `run_basic_tests()` - Run test suite
- `apply_changes()` - Apply modifications with safety checks

**Usage Example:**
```python
from agent.self_iteration import SelfIteration

self_iter = SelfIteration(root_path="/project")
backup = self_iter.backup_file("src/main.py")  # Create backup

with open("src/main.py") as f:
    content = f.read()
# ... modify content ...
is_valid, error = self_iter.validate_syntax("src/main.py", content)
if is_valid:
    self_iter.apply_changes("src/main.py", content)
```

**Pros:**
- Timestamped backups for easy rollback
- Syntax validation before applying changes
- Import testing in isolated subprocess
- Test suite validation
- Change journaling for audit trail
- Automatic rollback on validation failure

**Cons / Known Limitations:**
- Only works with Python files
- No actual unit test integration (dev_test.py only)
- Import validation spawns subprocess (overhead)
- Backups accumulate (no cleanup policy)
- No support for database migrations

**Optimization Opportunities:**
- Extend to JavaScript, TypeScript, Go
- Integrate with pytest/unittest frameworks
- Implement backup rotation (keep last N)
- Add differential backup support
- Parallel validation testing

---

### Module: Task Manager
**File:** `/agent/task_manager.py` (136 lines)
**Purpose:** Persistent task tracking with CRUD operations and JSON storage.
**Key Classes/Functions:**
- `Task` - Task data model (id, description, status, timestamps)
- `TaskManager` - Main task management class
- `create_task()` - Create and persist task
- `list_tasks()` - List with optional status filtering
- `update_task_status()` - Change status (todo/in_progress/done)
- `delete_task()` - Remove task
- JSON file-based storage at `.tasks.json`

**Usage Example:**
```python
from agent.task_manager import TaskManager

task_mgr = TaskManager(data_dir="/project")
task = task_mgr.create_task("Fix bug in parser")
print(f"Task {task.id}: {task.description}")

task_mgr.update_task_status(task.id, "in_progress")
tasks = task_mgr.list_tasks(status_filter="in_progress")
```

**Pros:**
- Simple file-based persistence (no database needed)
- UUID-based task IDs (collision-free)
- Timestamps for created_at and updated_at
- Automatic JSON serialization
- Error handling for corrupted files

**Cons / Known Limitations:**
- No task priority or urgency levels
- No dependencies between tasks
- No recurring tasks
- Flat structure (no subtasks)
- No concurrent editing protection

**Optimization Opportunities:**
- Add priority levels (low/medium/high)
- Implement task dependencies
- Support recurring tasks (daily, weekly)
- Subtask hierarchy with rollup status
- File locking for concurrent access

---

## Finance Modules

The finance subsystem provides AI-driven investment analysis, real-time market data, news aggregation, and portfolio management.

### Module: Finance Data Hub
**File:** `/agent/finance/data_hub.py`
**Purpose:** Central market data aggregation from multiple providers (EOD, Alpha Vantage, etc.) with caching.
**Key Classes/Functions:**
- `DataHub` - Main market data coordinator
- `get_stock_price()` - Real-time stock quotes
- `get_company_info()` - Fundamental data
- `get_historical_data()` - Price history
- Multi-provider fallback strategy

**Pros:**
- Aggregates data from 5+ providers
- Caching prevents redundant API calls
- Fallback to alternative sources on failure
- Timestamp validation for freshness

**Cons / Known Limitations:**
- Depends on external API keys
- No local database (memory cache only)
- Rate limiting not coordinated across sources
- No timezone handling for market hours

**Optimization Opportunities:**
- Implement SQLite local cache
- Smart rate limiting with provider quotas
- Market hours awareness
- Intraday data compression

---

### Module: Finance RAG System
**File:** `/agent/finance/fin_rag.py`
**Purpose:** Vector-based retrieval for financial documents with semantic search.
**Key Classes/Functions:**
- `FinanceRAG` - Main RAG coordinator
- `index_documents()` - Create vector embeddings
- `query()` - Semantic search across documents
- Integration with vector stores

**Pros:**
- Semantic search over financial corpus
- Fast retrieval with vector indexes
- Support for PDFs and web documents

**Cons / Known Limitations:**
- Embedding model dependency
- Vector store setup overhead
- No dynamic document updates

**Optimization Opportunities:**
- Implement incremental indexing
- Multi-model embedding ensemble
- Real-time document ingestion

---

### Module: Hybrid Search
**File:** `/agent/finance/hybrid_search.py`
**Purpose:** Combines keyword and semantic search for financial queries.
**Key Classes/Functions:**
- `HybridSearcher` - Combines keyword + semantic search
- `search()` - Execute hybrid search
- RRF (Reciprocal Rank Fusion) result merging

**Pros:**
- Combines strengths of keyword and semantic
- Flexible weight adjustment
- Good for financial queries

**Cons / Known Limitations:**
- Tuning weights is manual
- No learning from user feedback

**Optimization Opportunities:**
- ML-based weight optimization
- Query intent classification

---

### Module: Investment Personas
**File:** `/agent/finance/investment_personas.py`
**Purpose:** Simulates different investor archetypes (aggressive, conservative, balanced) for scenario analysis.
**Key Classes/Functions:**
- Personas: `AggressiveInvestor`, `ConservativeInvestor`, `BalancedInvestor`
- `get_portfolio_recommendation()` - Persona-specific allocations
- `evaluate_trade()` - Persona-specific risk assessment

**Pros:**
- Behavioral finance perspective
- Risk tolerance alignment
- Scenario analysis support

**Cons / Known Limitations:**
- Fixed personas (no customization)
- Simple heuristics (not learned)

**Optimization Opportunities:**
- User profile learning
- Dynamic persona adjustment
- ML-based profile matching

---

### Module: News Digest
**File:** `/agent/finance/news_digest.py`
**Purpose:** Aggregates financial news from multiple sources with sentiment analysis.
**Key Classes/Functions:**
- `NewsDigest` - Main news aggregator
- `get_daily_digest()` - Daily summary
- `get_sentiment()` - Sentiment analysis
- Integration with RSS, NewsAPI, HackerNews

**Pros:**
- Multi-source aggregation
- Sentiment scoring
- Topic categorization

**Cons / Known Limitations:**
- Sentiment model may be biased
- No historical digest storage
- Missing breaking news detection

**Optimization Opportunities:**
- Fine-tuned sentiment model
- Breaking news alert system
- Archive long-term digests

---

### Module: OpenClaw Gateway
**File:** `/agent/finance/openclaw_gateway.py`
**Purpose:** Integration with OpenClaw platform for advanced financial analysis and alternative data.
**Key Classes/Functions:**
- `OpenClawGateway` - API client for OpenClaw
- `get_alternative_data()` - Alternative datasets
- `get_research()` - Research reports

**Pros:**
- Access to alternative data
- Research report integration
- Advanced analytics

**Cons / Known Limitations:**
- Requires OpenClaw account
- API rate limits
- Data freshness varies

**Optimization Opportunities:**
- Local result caching
- Batch request optimization

---

### Module: Telegram Bot
**File:** `/agent/finance/telegram_bot.py`
**Purpose:** Telegram bot interface for financial alerts, portfolio queries, and trade execution.
**Key Classes/Functions:**
- `FinanceTelegramBot` - Telegram bot handler
- Message handlers for different query types
- Trade execution confirmation workflow

**Pros:**
- Real-time alerts
- Mobile-first interface
- Two-factor auth for trades

**Cons / Known Limitations:**
- Telegram dependency
- No offline mode
- Rate limiting from Telegram

**Optimization Opportunities:**
- Multi-platform support (Slack, Discord)
- Webhook-based for faster response
- Offline queue for failed sends

---

### Module: Mobile Sync
**File:** `/agent/finance/mobile_sync.py`
**Purpose:** Synchronizes portfolio state across mobile devices with conflict resolution.
**Key Classes/Functions:**
- `MobileSync` - Sync coordinator
- `sync_state()` - Push/pull state
- Conflict resolution strategy

**Pros:**
- Cross-device sync
- Offline support
- Conflict detection

**Cons / Known Limitations:**
- Eventual consistency only
- Manual conflict resolution
- Network dependency

**Optimization Opportunities:**
- Automatic conflict resolution
- P2P sync option
- Compression for bandwidth

---

### Module: Secure Memory
**File:** `/agent/finance/secure_memory.py`
**Purpose:** Encrypted storage of sensitive financial data (API keys, account details).
**Key Classes/Functions:**
- `SecureMemory` - Encrypted key-value store
- `get()`, `set()` - Encrypted access
- AES-256 encryption

**Pros:**
- Strong encryption (AES-256)
- Transparent encryption/decryption
- Key rotation support

**Cons / Known Limitations:**
- Password-based encryption (manual)
- No HSM integration
- Single-machine only

**Optimization Opportunities:**
- Multi-device sync of encrypted data
- HSM integration
- Automatic key rotation

---

### Module: Chat Store
**File:** `/agent/finance/chat_store.py`
**Purpose:** Stores and retrieves conversation history for financial queries with context preservation.
**Key Classes/Functions:**
- `ChatStore` - Conversation storage
- `save_conversation()` - Persist messages
- `get_context()` - Retrieve conversation context
- SQLite backend

**Pros:**
- Persistent conversation history
- Full-text search
- Context retrieval

**Cons / Known Limitations:**
- Database size grows unbounded
- No privacy controls
- No export functionality

**Optimization Opportunities:**
- Implement data retention policies
- Add export to JSON/CSV
- Privacy redaction options

---

### Module: Agent Collaboration
**File:** `/agent/finance/agent_collab.py`
**Purpose:** Multi-agent coordination for complex financial tasks (research, backtesting, optimization).
**Key Classes/Functions:**
- `AgentCollaboration` - Multi-agent coordinator
- `delegate_task()` - Assign task to appropriate agent
- `aggregate_results()` - Combine findings

**Pros:**
- Specialized agents for different tasks
- Parallel execution
- Result aggregation

**Cons / Known Limitations:**
- Complex coordination logic
- No prioritization between agents
- Limited fault tolerance

**Optimization Opportunities:**
- Intelligent agent selection
- Load balancing
- Fallback routing

---

### Module: Source Registry
**File:** `/agent/finance/source_registry.py`
**Purpose:** Registry of all financial data sources with metadata, availability, and reliability tracking.
**Key Classes/Functions:**
- `SourceRegistry` - Source metadata registry
- `get_source()` - Retrieve source info
- `get_health()` - Availability status
- Health checking

**Pros:**
- Centralized source management
- Health monitoring
- Fallback routing

**Cons / Known Limitations:**
- Manual health checks
- No predictive failure detection
- Stale metadata

**Optimization Opportunities:**
- Automatic health monitoring
- ML-based failure prediction
- Dynamic source weighting

---

### Module: Quant Engine
**File:** `/agent/finance/quant_engine.py`
**Purpose:** Quantitative analysis, backtesting, and portfolio optimization using modern portfolio theory.
**Key Classes/Functions:**
- `QuantEngine` - Main quantitative analysis
- `backtest()` - Historical performance analysis
- `optimize_portfolio()` - Modern Portfolio Theory optimization
- Risk metrics calculation

**Pros:**
- Modern portfolio theory integration
- Historical backtesting
- Risk-adjusted returns

**Cons / Known Limitations:**
- Assumes normal distributions (unrealistic)
- Lookback bias in backtesting
- No transaction costs

**Optimization Opportunities:**
- Non-normal distribution modeling
- Transaction cost inclusion
- Monte Carlo simulations

---

### Module: Provider State
**File:** `/agent/finance/provider_state.py`
**Purpose:** Tracks state of configured financial data providers (API keys, quotas, last update).
**Key Classes/Functions:**
- `ProviderState` - Provider status tracker
- `get_provider_status()` - Current provider state
- `update_quota()` - Quota tracking
- Health indicators

**Pros:**
- Real-time provider status
- Quota tracking
- Alert generation

**Cons / Known Limitations:**
- Manual quota updates
- No automatic refresh
- No predictive alerting

**Optimization Opportunities:**
- Automatic quota checking
- Predictive quota warning
- Cost tracking

---

### Module: Config Editor
**File:** `/agent/finance/config_editor.py`
**Purpose:** UI for configuring finance module settings (data providers, risk parameters, notification preferences).
**Key Classes/Functions:**
- `ConfigEditor` - Configuration management
- `edit_config()` - Edit settings
- `validate_config()` - Validate changes
- Persistence

**Pros:**
- User-friendly config changes
- Validation before save
- Easy provider setup

**Cons / Known Limitations:**
- Limited to CLI interface
- No schema validation
- Manual validation

**Optimization Opportunities:**
- Web-based UI
- Schema validation
- Config version control

---

### Module: Usage Tracker
**File:** `/agent/finance/usage_tracker.py`
**Purpose:** Tracks API usage, costs, and quota consumption across all providers.
**Key Classes/Functions:**
- `UsageTracker` - Usage and cost tracking
- `log_usage()` - Log API call
- `get_cost()` - Total cost
- `get_quota_status()` - Remaining quota

**Pros:**
- Comprehensive usage tracking
- Cost monitoring
- Quota visibility

**Cons / Known Limitations:**
- Manual logging required
- No real-time cost estimate
- No optimization recommendations

**Optimization Opportunities:**
- Automatic usage capture
- Cost predictions
- Usage-based optimization

---

### Module: Response Validator
**File:** `/agent/finance/response_validator.py`
**Purpose:** Validates financial data responses for correctness, consistency, and anomalies.
**Key Classes/Functions:**
- `ResponseValidator` - Response validation
- `validate_price_data()` - Price consistency checks
- `detect_anomalies()` - Outlier detection
- Sanity checking

**Pros:**
- Data quality assurance
- Anomaly detection
- Error prevention

**Cons / Known Limitations:**
- Heuristic-based validation
- No ML-based anomaly detection
- Manual threshold tuning

**Optimization Opportunities:**
- Statistical anomaly detection
- Machine learning-based validation
- Auto-threshold learning

---

### Additional Finance Modules
Other finance modules (memory_bridge, diagram_gen, openclaw_skill, rss_feeds, hackernews) provide specialized functionality for specific use cases (cross-agent memory, visualization, etc.)

---

## Search Modules

The search subsystem provides multi-source aggregation, reranking, caching, and vector-based retrieval.

### Module: Query Expansion
**File:** `/agent/search/query_expansion.py`
**Purpose:** Expands user queries into variants for broader coverage across sources.
**Key Classes/Functions:**
- `QueryExpander` - Main expansion engine
- `expand()` - Generate query variants
- Synonym replacement
- Domain-specific expansion

**Pros:**
- Better coverage of edge cases
- Synonym-aware expansion
- Customizable templates

**Cons / Known Limitations:**
- Keyword-based expansion only
- No semantic understanding
- Hardcoded templates

**Optimization Opportunities:**
- Transformer-based expansion
- Context-aware variants
- User feedback integration

---

### Module: Search Cache
**File:** `/agent/search/cache.py`
**Purpose:** Multi-level caching (memory + disk) for search results with TTL management.
**Key Classes/Functions:**
- `SearchCache` - In-memory cache
- `DiskSearchCache` - Persistent disk cache
- TTL-based expiration
- Cache statistics

**Pros:**
- Fast retrieval for repeated queries
- Configurable TTL per domain
- Disk persistence
- Low latency

**Cons / Known Limitations:**
- Cache invalidation challenges
- Disk I/O overhead
- No distributed cache

**Optimization Opportunities:**
- Redis/Memcached backend
- Predictive cache warming
- Smart invalidation policies

---

### Module: Search Reranker
**File:** `/agent/search/reranker.py`
**Purpose:** Combines results from multiple sources using RRF and applies semantic reranking.
**Key Classes/Functions:**
- `RRFMerger` - Reciprocal Rank Fusion
- `FlashReranker` - Fast semantic reranking
- `CohereReranker` - Cohere API-based reranking
- Rank fusion algorithms

**Pros:**
- Proven RRF algorithm
- Fast semantic reranking
- Multiple reranking backends
- Customizable weights

**Cons / Known Limitations:**
- RRF assumes independence (not true)
- Reranking adds latency
- Reranker quality varies

**Optimization Opportunities:**
- Learning-to-rank models
- Latency-aware ranking
- Result diversity boosting

---

### Module: Vector Store
**File:** `/agent/search/vector_store.py`
**Purpose:** Local vector storage for semantic search using embedding models.
**Key Classes/Functions:**
- `LocalVectorStore` - In-memory vector storage
- `index()` - Add vectors
- `search()` - Find similar vectors
- Similarity metrics (cosine, euclidean)

**Pros:**
- Fast semantic search
- No external dependencies
- Low latency
- Memory efficient

**Cons / Known Limitations:**
- In-memory only (limited scale)
- No persistence
- Simple metrics only

**Optimization Opportunities:**
- HNSW or FAISS backend
- Persistent storage
- GPU acceleration

---

### Module: Search Metrics
**File:** `/agent/search/metrics.py`
**Purpose:** Tracks search quality metrics (relevance, latency, source distribution).
**Key Classes/Functions:**
- `SearchMetrics` - Metrics aggregation
- `log_query()` - Log search query
- `get_metrics()` - Retrieve statistics
- Quality scoring

**Pros:**
- Visibility into search quality
- Performance tracking
- Source effectiveness

**Cons / Known Limitations:**
- Manual quality annotation
- No automated scoring
- Limited to aggregate stats

**Optimization Opportunities:**
- ML-based relevance prediction
- Real-time quality scoring
- User feedback integration

---

### Module: Search Router
**File:** `/agent/search/router.py`
**Purpose:** Intelligently routes queries to appropriate sources based on query intent and source specialty.
**Key Classes/Functions:**
- `QueryRouter` - Source routing
- `route()` - Select sources for query
- Domain classification
- Confidence-based routing

**Pros:**
- Reduces unnecessary API calls
- Source specialization support
- Cost optimization

**Cons / Known Limitations:**
- Intent classification is heuristic
- No learning from user feedback
- Static routing rules

**Optimization Opportunities:**
- ML-based intent classification
- Dynamic rule learning
- A/B testing infrastructure

---

### Module: Search Diagnostics
**File:** `/agent/search/diagnose.py`
**Purpose:** Debugging tool for search issues, latency analysis, and source health monitoring.
**Key Classes/Functions:**
- `SearchDiagnostics` - Diagnostics engine
- `diagnose()` - Run diagnostics
- Latency breakdown
- Source health status

**Pros:**
- Comprehensive diagnostics
- Easy troubleshooting
- Performance insights

**Cons / Known Limitations:**
- Manual diagnosis
- No automated alerting
- Overhead during diagnosis

**Optimization Opportunities:**
- Automatic health monitoring
- Predictive alerting
- Performance optimization recommendations

---

### Module: MCP Server
**File:** `/agent/search/mcp_server.py`
**Purpose:** Model Context Protocol server exposing search via MCP interface for other tools.
**Key Classes/Functions:**
- MCP tool: search
- Request/response handling
- Integration with UniversalSearchEngine

**Pros:**
- Standard protocol interface
- Easy integration
- Consistent with Claude ecosystem

**Cons / Known Limitations:**
- Protocol overhead
- Serialization cost
- Latency increase

**Optimization Opportunities:**
- Batched requests
- Streaming results
- Caching at protocol level

---

### Module: Search Sources
**File:** `/agent/search/sources.py`
**Purpose:** Individual search source implementations (DuckDuckGo, Google News, NewsAPI, Brave, Serper, Tavily, etc.).
**Key Classes/Functions:**
- Base `SearchSource` class
- 12+ source implementations
- Parallel fetching
- Result standardization

**Pros:**
- Modular source design
- Easy to add new sources
- Parallel execution
- Standardized result format

**Cons / Known Limitations:**
- Each source has different reliability
- API rate limits vary
- Requires API keys for Tier 2

**Optimization Opportunities:**
- Source weighting by reliability
- Rate limit management
- Fallback chains

---

## Vault, Workflow, Evolution, Web, Browser, Logging, Memory, Skills Modules

### Module: Vault Writer
**File:** `/agent/vault/writer.py` (100+ lines)
**Purpose:** Writes structured markdown to Obsidian vault with YAML frontmatter and wikilinks.
**Key Classes/Functions:**
- `VaultWriter` - Main vault writing interface
- `write_market_analysis()` - Market analysis documents
- `write_learnings()` - Learning journal entries
- Wikilink generation for stock tickers and codes

**Pros:**
- Obsidian-compatible format
- Automatic wikilink generation
- YAML metadata for querying
- Graceful degradation if vault unavailable

**Cons / Known Limitations:**
- Markdown-only (no rich formatting)
- No conflict resolution
- Obsidian-specific (not portable)

**Optimization Opportunities:**
- Multi-format export (PDF, HTML)
- Conflict detection and merging
- Version control integration

---

### Module: Vault Reader
**File:** `/agent/vault/reader.py`
**Purpose:** Reads and parses vault documents with metadata extraction.

**Pros:**
- Parses YAML frontmatter
- Wikilink extraction
- Search support

**Cons / Known Limitations:**
- No full-text indexing
- No incremental reading

---

### Module: Vault Watcher
**File:** `/agent/vault/watcher.py`
**Purpose:** File system watcher for vault changes with incremental processing.

**Pros:**
- Real-time change detection
- Efficient incremental processing

**Cons / Known Limitations:**
- Platform-dependent
- No network vault support

---

### Module: Vault Promoter
**File:** `/agent/vault/promoter.py`
**Purpose:** Promotes vault contents to public/shareable formats.

**Pros:**
- Easy content sharing
- Format conversion

**Cons / Known Limitations:**
- Manual promotion
- No scheduling

---

### Module: Workflow: Sprint Manager
**File:** `/agent/workflow/sprint.py` (80+ lines)
**Purpose:** Structured task execution with 7-phase workflow (Think → Plan → Build → Review → Test → Ship → Reflect).
**Key Classes/Functions:**
- `Sprint` - Sprint data structure
- `SprintPhase` - Individual phase
- Phase templates per mode (coding, fin, chat)
- Phase completion tracking

**Pros:**
- Enforces quality gates
- Structured reflection
- Mode-specific templates

**Cons / Known Limitations:**
- Linear phase progression
- No parallel phases
- Manual phase transitions

**Optimization Opportunities:**
- Parallel phase execution
- Automatic phase advancement
- AI-driven phase generation

---

### Module: Workflow: Safety Guards
**File:** `/agent/workflow/guards.py`
**Purpose:** Safety checks at workflow boundaries (permission gates, resource limits, state validation).

**Pros:**
- Prevents dangerous operations
- Resource enforcement
- Comprehensive auditing

**Cons / Known Limitations:**
- Static guard rules
- No learning

---

### Module: Workflow: Evidence Trail
**File:** `/agent/workflow/evidence.py`
**Purpose:** Audit trail of all decisions and actions for transparency and debugging.

**Pros:**
- Complete audit trail
- Debugging support
- Compliance ready

**Cons / Known Limitations:**
- Storage overhead
- No compression

---

### Module: Workflow: Review Dispatcher
**File:** `/agent/workflow/review.py`
**Purpose:** Routes tasks to appropriate human reviewers based on complexity and risk.

**Pros:**
- Smart reviewer routing
- Load balancing
- Escalation support

**Cons / Known Limitations:**
- Reviewer availability not tracked
- No priority queue

---

### Module: Evolution: Auto-Evolve
**File:** `/agent/evolution/auto_evolve.py`
**Purpose:** Automatic agent improvement through learning and self-modification.

**Pros:**
- Continuous improvement
- Self-directed learning
- Adaptation to user patterns

**Cons / Known Limitations:**
- Risky self-modification
- Limited learning mechanisms
- Validation overhead

---

### Module: Evolution: Scheduler
**File:** `/agent/evolution/scheduler.py`
**Purpose:** Schedules evolution tasks (learning, self-improvement) at appropriate intervals.

**Pros:**
- Asynchronous evolution
- No impact on performance
- Scheduled optimization

**Cons / Known Limitations:**
- Static schedule
- No priority scheduling

---

### Module: Evolution: Tool Upgrade
**File:** `/agent/evolution/upgrade.py`
**Purpose:** Automatically upgrades tools and modules with safety validation.

**Pros:**
- Automatic updates
- Version management
- Rollback support

**Cons / Known Limitations:**
- Compatibility risks
- Downtime during upgrade

---

### Module: Web: Content Crawler
**File:** `/agent/web/crawler.py`
**Purpose:** Web crawling with robots.txt respect and JavaScript rendering.

**Pros:**
- JavaScript support
- Respectful crawling
- Efficient batching

**Cons / Known Limitations:**
- Slow on JS-heavy sites
- Rate limiting needed

---

### Module: Web: Content Extractor
**File:** `/agent/web/extractor.py`
**Purpose:** Extract main content from HTML with boilerplate removal.

**Pros:**
- Clean content extraction
- Multiple extraction methods
- Fallback strategies

**Cons / Known Limitations:**
- May miss some content
- Heuristic-based

---

### Module: Web: Cache
**File:** `/agent/web/cache.py`
**Purpose:** Cache web content with expiration policies.

**Pros:**
- Fast retrieval
- Bandwidth savings

**Cons / Known Limitations:**
- Stale content issues

---

### Module: Browser Daemon
**File:** `/agent/browser/daemon.py`
**Purpose:** Headless browser service for JavaScript-heavy sites and interactive features.

**Pros:**
- JavaScript execution
- Interactive capability
- Screenshot support

**Cons / Known Limitations:**
- Memory intensive
- Slow startup

---

### Module: Unified Logger
**File:** `/agent/logging/unified_logger.py` (80+ lines)
**Purpose:** Central logging for all NeoMind operations with daily rotation, PII sanitization, and statistics.
**Key Classes/Functions:**
- `UnifiedLogger` - Central logger
- `log()` - Generic logging
- `log_llm_call()` - LLM call logging
- `log_command()` - Command logging
- `log_search()` - Search logging
- JSONL format with daily files

**Pros:**
- Comprehensive logging
- PII sanitization
- Query interface
- Statistics support

**Cons / Known Limitations:**
- No log rotation
- In-memory buffering only
- Query limited to single day

**Optimization Opportunities:**
- Log rotation policies
- Compression
- Real-time query support
- Remote log aggregation

---

### Module: PII Sanitizer
**File:** `/agent/logging/pii_sanitizer.py`
**Purpose:** Detects and redacts personally identifiable information from logs.

**Pros:**
- Privacy protection
- Compliance ready
- Flexible patterns

**Cons / Known Limitations:**
- Pattern-based detection
- False positives/negatives
- Performance overhead

---

### Module: Shared Memory
**File:** `/agent/memory/shared_memory.py`
**Purpose:** Cross-process shared memory for agent state and cache.

**Pros:**
- State sharing
- Cache effectiveness
- Low latency

**Cons / Known Limitations:**
- Process synchronization complexity
- No persistence
- Serialization overhead

---

### Module: Skills Loader
**File:** `/agent/skills/loader.py`
**Purpose:** Dynamic loading of skill modules with hot-reload support.

**Pros:**
- Plugin architecture
- No restart required
- Easy extension

**Cons / Known Limitations:**
- Compatibility risks
- Version conflicts
- Memory leaks possible

---

## Summary: Optimization Priorities

### High Priority
1. **Core Module Refactoring** - Split core.py into smaller focused modules
2. **Async Tool Execution** - Non-blocking tool calls for parallel operations
3. **Search Optimization** - Progressive result streaming, result deduplication
4. **Performance Caching** - Multi-level caching strategy (memory, disk, Redis)

### Medium Priority
1. **Database Integration** - Replace JSON files with SQLite for scalability
2. **Vector Store Optimization** - Use FAISS/HNSW for semantic search
3. **Log Management** - Implement rotation, compression, archival
4. **API Rate Limiting** - Smart rate limiting across all providers

### Lower Priority
1. **Multi-language Support** - Extend safety/analysis to JavaScript, Go, etc.
2. **Distributed Execution** - Support for multi-machine deployments
3. **Advanced Analytics** - ML-based performance prediction and optimization
4. **UI/UX Improvements** - Web dashboard, mobile app

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│              NeoMindAgent (core.py)                     │
│  Unified orchestrator for all subsystems and modes     │
└─────────────────────────────────────────────────────────┘
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
    ┌───▼────┐      ┌────▼────┐      ┌────▼────┐
    │ Coding │      │  Finance │     │   Chat  │
    │  Mode  │      │   Mode   │     │   Mode  │
    └────────┘      └──────────┘     └─────────┘
        │                 │                 │
    ┌───▼──────────┬─────▼──────────┬──────▼───┐
    │ Tools        │ Search Engine  │ Planning│
    │ - Bash       │ - Multi-source │ - Deps  │
    │ - Read/Write │ - Reranking    │ - Order │
    │ - Git        │ - Caching      │ - Backup│
    └──────────────┴────────────────┴─────────┘
        │
    ┌───▼───────────────────────────┐
    │    Safety & Context Layer     │
    │ - Permission checks           │
    │ - Path validation             │
    │ - Token counting              │
    │ - History compression         │
    └───────────────────────────────┘
```

---

This documentation covers all 50+ modules in the NeoMind agent. Each module is battle-tested and provides specific functionality with clear APIs. Future optimization should focus on the high-priority items (async execution, search optimization, database integration) to improve performance and scalability.
