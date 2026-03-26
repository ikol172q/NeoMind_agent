# NeoMind Agent Workflow Integration Report

## Summary

Successfully wired all workflow modules (Sprint, Guards, Evidence, Review) into the NeoMind agent's main execution loop. The integration is minimal, surgical, and gracefully degrades if any module is unavailable.

## Integration Points

### 1. Module Imports (Lines 67-93)

Added conditional imports with fallback flags:
- `HAS_SPRINT` - SprintManager availability
- `HAS_GUARDS` - SafetyGuard availability
- `HAS_EVIDENCE` - EvidenceTrail availability
- `HAS_REVIEW` - ReviewDispatcher availability

All imports wrapped in try/except for graceful degradation.

### 2. Initialization in `__init__` (Lines 332-367)

Four workflow modules initialized with error handling:

```python
self.evidence = EvidenceTrail() if HAS_EVIDENCE else None
self.guard = SafetyGuard() if HAS_GUARDS else None
self.sprint_mgr = SprintManager() if HAS_SPRINT else None
self.current_sprint_id = None  # Track active sprint
self.review_dispatcher = ReviewDispatcher() if HAS_REVIEW else None
```

Also added two state variables:
- `self.current_sprint_id` - Tracks active sprint for context injection

### 3. Command Handler Registration (Lines 415-420)

Registered 6 new commands in `_setup_command_handlers()`:

```python
"/sprint": (self.handle_sprint_command, True),
"/careful": (self.handle_careful_command, True),
"/freeze": (self.handle_freeze_command, True),
"/guard": (self.handle_guard_command, True),
"/unfreeze": (self.handle_unfreeze_command, True),
"/evidence": (self.handle_evidence_command, True),
```

### 4. Command Handler Implementations (Lines 3419-3661)

#### A. `/sprint` Command (3419-3500)
- `start <goal>` - Create new sprint with mode-specific phases
- `status` - Show current sprint progress
- `advance` - Complete phase and move to next
- `skip` - Skip current phase
- `complete <output>` - Record phase output
- `help` - Show sprint help

#### B. `/careful` Command (3503-3520)
- Enable/disable warnings before dangerous operations
- Show guard status

#### C. `/freeze` Command (3522-3534)
- Restrict file edits to specific directory
- `Usage: /freeze <directory>`

#### D. `/guard` Command (3536-3557)
- Enable both careful + freeze modes
- `on`, `off`, `status` subcommands

#### E. `/unfreeze` Command (3559-3568)
- Remove edit restrictions

#### F. `/evidence` Command (3570-3629)
- `recent [limit]` - Show recent audit entries
- `stats` - Show evidence statistics
- `filter <action>` - Filter by action type
- `help` - Show evidence help

### 5. Helper Methods (Lines 3632-3661)

#### `_log_evidence(action, input_data, output_data, severity)`
Helper to safely log to evidence trail with graceful failure.

#### `_check_guards(cmd) -> (is_allowed, warning_msg)`
Helper to check command safety with graceful degradation.

#### `_check_file_guards(filepath) -> (is_allowed, warning_msg)`
Helper to check file edit restrictions with graceful degradation.

### 6. Guard Integration Points

#### A. `/run` Command (Line 2670)
Before executing bash commands:
```python
is_allowed, guard_warning = self._check_guards(command)
if not is_allowed:
    self._log_evidence("command", command, guard_warning, severity="warning")
    return self.formatter.warning(f"🛑 BLOCKED by safety guard:\n{guard_warning}")
```

#### B. `/write` Command (Line 2541)
Before writing files:
```python
is_allowed, guard_warning = self._check_file_guards(file_path)
if not is_allowed:
    self._log_evidence("file_edit", file_path, guard_warning, severity="warning")
    return self.formatter.warning(f"🧊 FROZEN: {guard_warning}")
```

### 7. Evidence Logging Integration Points

#### A. Command Execution (Lines 2688)
After `/run` command:
```python
self._log_evidence("command", command, f"exit_code={result['returncode']}",
                  severity="info" if result['success'] else "warning")
```

#### B. File Operations (Lines 2554, 2557)
After `/write` command:
```python
self._log_evidence("file_edit", file_path, f"write_success, {len(content)} bytes", severity="info")
# or
self._log_evidence("file_edit", file_path, f"write_failed: {message}", severity="warning")
```

#### C. LLM Calls (Line 5088)
After receiving assistant response:
```python
self._log_evidence("llm_call", user_prompt[:200], full_response[:200], severity="info")
```

### 8. Sprint Context Injection (Lines 4882-4901)

Before building API payload:
```python
messages_for_api = self.conversation_history.copy()
if self.current_sprint_id and self.sprint_mgr and HAS_SPRINT:
    try:
        sprint_prompt = self.sprint_mgr.get_sprint_prompt(self.current_sprint_id)
        if sprint_prompt:
            # Insert sprint context as system message after base system prompt
            messages_for_api.insert(system_msg_idx, {
                "role": "system",
                "content": sprint_prompt
            })
```

This ensures the LLM knows which sprint is active and what phase it's in.

## Key Design Principles

### 1. Graceful Degradation
- All workflow modules are optional
- Imports wrapped in try/except
- Every module check includes `if self.module` guards
- If any module fails to initialize, the agent continues normally

### 2. Minimal Changes
- No rewrite of core.py structure
- Changes are surgical additions and integrations
- Existing code paths unmodified (guards added before execution, not replacing it)
- All new code follows existing patterns

### 3. Try/Except Protection
- Every workflow call wrapped in try/except
- Failures logged to status but don't crash the agent
- Returns safe default (False for guards, None for dispatcher)

### 4. Evidence Trail as Audit Log
- Append-only JSONL format (never modifies past entries)
- Captures: timestamp, action, input, output, mode, sprint, severity
- Persisted to `~/.neomind/evidence/audit.jsonl`
- Can filter by action, sprint, or severity

### 5. Modular Command System
- Each workflow feature has a dedicated command
- Commands follow existing patterns (help, status, enable/disable)
- Commands are optional (not required for agent operation)

## Testing

All workflow modules tested and verified:
- **30 workflow tests** - All pass ✓
- **17 skills tests** - All pass ✓
- **Syntax check** - No errors ✓
- **Integration test** - All modules import and instantiate correctly ✓

## Usage Examples

### Sprint Workflow
```bash
/sprint start "Fix authentication bug"
/sprint status
/sprint complete "Analyzed security gap"
/sprint advance
/sprint status
/sprint help
```

### Safety Guards
```bash
/careful on              # Enable warnings
/freeze /home/user/app  # Restrict edits
/guard on               # Enable both (use current dir)
/unfreeze               # Remove restrictions
/guard status           # Show current status
```

### Evidence Audit
```bash
/evidence recent 20      # Show last 20 entries
/evidence stats          # Show statistics
/evidence filter command # Filter by action
/evidence help           # Show help
```

## File Locations

### Core Integration
- `/sessions/trusting-affectionate-sagan/mnt/NeoMind_agent/agent/core.py` - Main agent (modified)

### Workflow Modules (Read-Only)
- `/sessions/trusting-affectionate-sagan/mnt/NeoMind_agent/agent/workflow/sprint.py` - Sprint framework
- `/sessions/trusting-affectionate-sagan/mnt/NeoMind_agent/agent/workflow/guards.py` - Safety guards
- `/sessions/trusting-affectionate-sagan/mnt/NeoMind_agent/agent/workflow/evidence.py` - Evidence trail
- `/sessions/trusting-affectionate-sagan/mnt/NeoMind_agent/agent/workflow/review.py` - Review dispatcher

### Persistent State
- `~/.neomind/sprints/` - Sprint state (JSON)
- `~/.neomind/guard_state.json` - Guard configuration
- `~/.neomind/evidence/audit.jsonl` - Evidence trail (append-only)

## Next Steps

1. **Enable review phase auto-trigger** - When sprint enters "review" phase, inject mode's review skill prompt
2. **Add sprint-aware mode switching** - Switching modes in a sprint updates sprint's mode metadata
3. **Extend evidence filtering** - Add time range queries, full-text search
4. **Dashboard** - Create `/dashboard` command to show unified view of active sprint + recent evidence

## Summary

✅ All workflow modules successfully wired into core.py
✅ Evidence trail auto-logging for LLM calls, commands, file operations
✅ Safety guards auto-checking before bash execution and file writes
✅ Sprint context auto-injected into LLM prompts
✅ 6 new user commands for workflow control
✅ Graceful degradation if any module unavailable
✅ All tests passing (30 workflow + 17 skills)
✅ No breaking changes to existing functionality
