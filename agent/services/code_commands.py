"""
Tier 2H - Code Command Services Module

Extracted methods for handling /code commands, auto-fix operations, and code analysis.
These are standalone functions that take a 'core' parameter instead of being class methods.

This module centralizes code analysis, file inspection, change management, and
auto-fix functionality that was previously part of the core Agent class.
"""

import os
import sys
import re
import time
import json
import asyncio
import difflib
import requests
from typing import Optional, List, Dict, Tuple, Any

from agent.code_analyzer import CodeAnalyzer
from agent_config import agent_config

try:
    from agent.services.safety_service import log_operation
except ImportError:
    def log_operation(*args, **kwargs):
        pass  # No-op if logger not available

try:
    from agent.workflow.sprint import SprintManager
    HAS_SPRINT = True
except ImportError:
    HAS_SPRINT = False


def handle_code_command(core, command: str) -> str:
    """
    Handle /code command for code analysis and refactoring

    Available commands:
      /code scan [path]              - Scan codebase (default: current directory)
      /code summary                  - Show codebase summary
      /code find <pattern>          - Find files matching pattern
      /code read <file_path>        - Read and analyze a specific file
      /code analyze <file_path>     - Analyze file structure
      /code search <text>           - Search for text in code
      /code changes                 - Show pending changes
      /code apply                   - Apply pending changes (with confirmation)
      /code clear                   - Clear pending changes
      /code help                    - Show help
    """
    if not command or command.strip() == "":
        return _code_help(core)

    parts = command.split()
    subcommand = parts[0].lower() if parts else ""

    # Auto-switch to coding mode for code commands (except help)
    if subcommand != 'help' and core.mode != 'coding':
        core.switch_mode('coding', persist=False)

    if subcommand == 'help':
        return _code_help(core)
    elif subcommand == 'scan':
        path = ' '.join(parts[1:]) if len(parts) > 1 else os.getcwd()
        return core._code_scan(path)
    elif subcommand == 'summary':
        return _code_summary(core)
    elif subcommand == 'find':
        pattern = ' '.join(parts[1:]) if len(parts) > 1 else ""
        return _code_find(core, pattern)
    elif subcommand == 'read':
        file_path = ' '.join(parts[1:]) if len(parts) > 1 else ""
        return _code_read(core, file_path)
    elif subcommand == 'analyze':
        file_path = ' '.join(parts[1:]) if len(parts) > 1 else ""
        return _code_analyze(core, file_path)
    elif subcommand == 'search':
        text = ' '.join(parts[1:]) if len(parts) > 1 else ""
        return _code_search(core, text)
    elif subcommand == 'changes':
        return core._code_show_changes()
    elif subcommand == 'apply':
        return core._code_apply_changes()
    elif subcommand == 'clear':
        return _code_clear_changes(core)
    elif subcommand == 'self-scan':
        return core._code_self_scan()
    elif subcommand == 'self-improve':
        feature = ' '.join(parts[1:]) if len(parts) > 1 else ""
        return core._code_self_improve(feature)
    elif subcommand == 'self-apply':
        return core._code_self_apply()
    elif subcommand == 'reason':
        file_path = ' '.join(parts[1:]) if len(parts) > 1 else ""
        return core._code_reason(file_path)
    else:
        return core.formatter.error(f"Unknown subcommand: {subcommand}\n{_code_help(core)}")

def _code_help(core) -> str:
    return """
📁 CODE ANALYSIS COMMANDS:
  /code scan [path]          - Scan codebase (default: current directory)
  /code summary              - Show codebase summary (size, file types)
  /code find <pattern>       - Find files (supports wildcards: *.py, *test*)
  /code read <file_path>     - Read and display a file
  /code analyze <file_path>  - Analyze file structure (imports, functions, classes)
  /code search <text>        - Search for text in code files
  /code changes              - Show pending code changes
  /code apply                - Apply pending changes (requires confirmation)
  /code clear                - Clear pending changes
  /code self-scan            - Scan agent's own codebase
  /code self-improve [target]- Suggest improvements to agent's own code
  /code self-apply           - Apply vetted self-improvements with safety checks
  /code reason <file_path>   - Deep analysis using reasoning model (chain-of-thought)
  /code help                 - Show this help

💡 TIPS:
  • Use relative paths from current directory
  • Changes are grouped and require confirmation
  • Large codebases (>500 files) require specific file targeting
  • Use /code reason for complex analysis with deepseek-reasoner
    """.strip()

def _code_scan(core, path: str) -> str:
    """Initialize code analyzer with given path"""
    try:
        abs_path = os.path.abspath(path)
        if not os.path.exists(abs_path):
            return core.formatter.error(f"Path does not exist: {abs_path}")

        core.code_analyzer = CodeAnalyzer(abs_path, safety_manager=core.safety_manager)

        # Count files to warn if too many
        total_files, total_dirs = core.code_analyzer.count_files()

        result = f"{core.formatter.success(f'Codebase scanned: {abs_path}')}\n"
        result += f"📊 Statistics:\n"
        result += f"  • Total files: {total_files}\n"
        result += f"  • Total directories: {total_dirs}\n"

        if total_files > core.code_analyzer.max_files_before_warning:
            result += f"\n{core.formatter.warning(f'LARGE CODEBASE: {total_files} files detected')}\n"
            result += f"💡 Use '/code find <pattern>' to search for specific files\n"
            result += f"   or '/code read <specific_file>' to analyze individual files\n"

        # Check threshold and ask for confirmation to show detailed summary
        should_continue, _ = core._check_file_threshold(total_files, "scan codebase for detailed summary")
        if should_continue and total_files <= 1000:
            summary = core.code_analyzer.get_code_summary()
            if 'file_types' in summary:
                result += f"\n📁 File Types:\n"
                for ext, count in summary['file_types'].items():
                    result += f"  • {ext or 'no ext'}: {count} files\n"

        return result

    except Exception as e:
        return core.formatter.error(f"Error scanning path: {str(e)}")
    
def _code_summary(core) -> str:
    """Show codebase summary"""
    if not core.code_analyzer:
        return core.formatter.error("No codebase scanned. Use '/code scan <path>' first.")
        
    summary = core.code_analyzer.get_code_summary()
        
    result = f"📊 CODEBASE SUMMARY\n"
    result += f"────────────────────────\n"
    result += f"Root: {summary['root_path']}\n"
    result += f"Total files: {summary['total_files']}\n"

    if 'warning' in summary:
        result += f"\n{core.formatter.warning(summary['warning'])}\n"
        result += f"💡 {summary['suggestion']}\n"

    if 'file_types' in summary:
        result += f"\n📁 File Types:\n"
        for ext, count in summary['file_types'].items():
            percentage = (count / summary['total_files']) * 100
            result += f"  • {ext or 'no ext'}: {count} ({percentage:.1f}%)\n"

    if 'total_lines' in summary:
        result += f"\n📝 Total lines (est.): {summary['total_lines']:,}\n"
        
    if 'total_size' in summary:
        result += f"💾 Total size: {summary['total_size']}\n"

    result += f"\n💡 Use '/code find <pattern>' to explore specific files"
        
    return result

def _code_find(core, pattern: str) -> str:
    """Find files matching pattern"""
    if not core.code_analyzer:
        return core.formatter.error("No codebase scanned. Use '/code scan <path>' first.")

    if not pattern:
        return core.formatter.error("Please specify a pattern. Examples:\n" \
               "  /code find *.py\n" \
               "  /code find *test*\n" \
               "  /code find agent.py")
        
    # Check total files and ask for confirmation if large
    total_files, _ = core.code_analyzer.count_files()
    should_continue, limit = core._check_file_threshold(total_files, f"find files matching '{pattern}'")
    # Even if user declined full operation, we continue with reduced limit
    # Smart search with appropriate limit
    results = core.code_analyzer.smart_find_files(pattern, max_results=20, search_limit=limit)
        
    if not results:
        return f"🔍 No files found matching: {pattern}"

    result = f"🔍 Found {len(results)} files matching: {pattern}\n"
    result += "────────────────────────\n"

    for i, file_info in enumerate(results[:10], 1):
        size_kb = file_info['size'] / 1024
        result += f"{i}. {file_info['relative']}\n"
        result += f"   Size: {size_kb:.1f} KB\n"

    if len(results) > 10:
        result += f"\n... and {len(results) - 10} more files\n"

    result += f"\n💡 Use '/code read <file_path>' to read a specific file"
        
    return result

def _code_read(core, file_path: str) -> str:
    """Read and display a file"""
    if not core.code_analyzer:
        return core.formatter.error("No codebase scanned. Use '/code scan <path>' first.")
        
    if not file_path:
        return core.formatter.error("Please specify a file path")
        
    try:
        # ... existing file reading code ...
            
        # Add to AI memory with context that this is code
        core.add_to_history("user", f"""I've read the following code file:

File: {abs_path}
Lines: {line_count}

```python
{truncated}
```

Please remember this code. I may ask you to analyze or fix it.

Note: If I ask you to propose changes to this code, use the PROPOSED CHANGE format with exact Old Code and New Code.""")

        return result

    except Exception as e:
        return core.formatter.error(f"Error reading file: {str(e)}")
    
def add_code_context_instructions(core):
    """
    Add code-specific instructions to the current conversation
    This is called when user is asking about code but not using /fix or /analyze
    """
    code_instructions = """
    IMPORTANT: For code changes, use this format:

    PROPOSED CHANGE:
    File: [file_path]
    Description: [brief description]
    Old Code: [EXACT code from the file to replace]
    New Code: [improved replacement code]
    Line: [line number if known]

    Old Code must be exact code from the file, not comments or truncated text.
    """
        
    core.add_to_history("system", code_instructions)
        
def is_code_related_query(core, prompt: str) -> bool:
    """
    Detect if user is asking about code
    """
    code_keywords = [
        'fix', 'bug', 'error', 'code', 'function', 'class', 'method',
        'def ', 'import ', 'try:', 'except', 'file', 'line', 
        'syntax', 'compile', 'run', 'execute', 'debug',
        'improve', 'optimize', 'refactor', 'review'
    ]
        
    prompt_lower = prompt.lower()

    # Check for code file extensions
    if any(ext in prompt_lower for ext in ['.py', '.js', '.java', '.cpp', '.c', '.go', '.rs', '.rb']):
        return True

    # Check for code keywords
    if any(keyword in prompt_lower for keyword in code_keywords):
        return True

    # Check if it's about a specific file path
    import re
    file_patterns = [
        r'[\w/\\.-]+\.py',
        r'[\w/\\.-]+\.js',
        r'[\w/\\.-]+\.java',
        r'file:\s*[\w/\\.-]+',
        r'line\s+\d+',
    ]

    for pattern in file_patterns:
        if re.search(pattern, prompt_lower):
            return True

    return False

def _code_analyze(core, file_path: str) -> str:
    """Analyze a file's structure"""
    if not core.code_analyzer:
        return core.formatter.error("No codebase scanned. Use '/code scan <path>' first.")

    if not file_path:
        return core.formatter.error("Please specify a file path")
        
    try:
        abs_path = os.path.abspath(file_path)
        analysis = core.code_analyzer.analyze_file(abs_path)

        if not analysis['success']:
            return core.formatter.error(f"{analysis['error']}")

        result = f"🔬 FILE ANALYSIS: {os.path.basename(abs_path)}\n"
        result += f"📁 Path: {abs_path}\n"
        result += f"📊 Stats: {analysis['lines']} lines, {analysis['size']:,} bytes\n"
        result += "────────────────────────\n"

        # Show imports
        if analysis['imports']:
            result += f"\n📦 IMPORTS ({len(analysis['imports'])}):\n"
            for imp in analysis['imports'][:10]:  # Show first 10
                result += f"  • Line {imp['line']}: {imp['content']}\n"
            if len(analysis['imports']) > 10:
                result += f"  ... and {len(analysis['imports']) - 10} more imports\n"

        # Show classes
        if analysis['classes']:
            result += f"\n🏛 ️  CLASSES ({len(analysis['classes'])}):\n"
            for cls in analysis['classes']:
                result += f"  • Line {cls['line']}: {cls['name']}\n"

        # Show functions
        if analysis['functions']:
            result += f"\n⚙️  FUNCTIONS ({len(analysis['functions'])}):\n"
            for func in analysis['functions'][:15]:  # Show first 15
                result += f"  • Line {func['line']}: {func['name']}()\n"
            if len(analysis['functions']) > 15:
                result += f"  ... and {len(analysis['functions']) - 15} more functions\n"

        # Show preview
        result += f"\n📄 CONTENT PREVIEW (first 50 lines):\n"
        result += "```\n"
        result += analysis['content_preview']
        result += "\n```\n"

        if analysis['has_more_lines']:
            result += f"\n💡 File has {analysis['lines']} total lines. Use '/code read {file_path}' to see full content."

        # Add to AI memory for analysis
        core.add_to_history("user", f"""I've analyzed the following code file:

File: {abs_path}
Lines: {analysis['lines']}
Imports: {len(analysis['imports'])}
Classes: {len(analysis['classes'])}
Functions: {len(analysis['functions'])}

```{os.path.splitext(abs_path)[1][1:] or 'text'}
{analysis['content_preview']}
```

Please analyze this code structure.""")

        return result

    except Exception as e:
        return core.formatter.error(f"Error analyzing file: {str(e)}")

def _code_search(core, search_text: str) -> str:
    """Search for text in code files"""
    if not core.code_analyzer:
        return core.formatter.error("No codebase scanned. Use '/code scan <path>' first.")
        
    if not search_text:
        return core.formatter.error("Please specify search text")

    # Check total files and ask for confirmation if large
    total_files, _ = core.code_analyzer.count_files()

    should_continue, limit = core._check_file_threshold(
        total_files, f"search for '{search_text}'"
    )
    # Even if user declined full operation, we continue with reduced limit

    # Find code files with appropriate limit
    code_files = core.code_analyzer.find_code_files(limit=limit)

    if not code_files:
        return core.formatter.error("No code files found in the scanned codebase.")

    results = []
    core._safe_print(f"🔍 Searching in {len(code_files)} files...")
        
    for file_path in code_files:
        try:
            success, message, content = core.code_analyzer.read_file_safe(file_path)
            if success and search_text.lower() in content.lower():
                # Count occurrences
                occurrences = content.lower().count(search_text.lower())

                # Get context lines
                lines = content.split('\n')
                matching_lines = []
                for i, line in enumerate(lines):
                    if search_text.lower() in line.lower():
                        context_start = max(0, i - 1)
                        context_end = min(len(lines), i + 2)
                        context = "\n".join(f"{j+1:4d}: {lines[j]}" for j in range(context_start, context_end))
                        matching_lines.append(context)

                results.append({
                    'path': file_path,
                    'occurrences': occurrences,
                    'relative': os.path.relpath(file_path, core.code_analyzer.root_path),
                    'sample': matching_lines[0] if matching_lines else ""
                })

                if len(results) >= 20:  # Limit results
                    break
        except:
            continue

    if not results:
        result_msg = f"🔍 No matches found for '{search_text}' in {len(code_files)} files."
        core.add_search_results_to_history('code', search_text, result_msg)
        return result_msg
        
    result = f"🔍 SEARCH RESULTS for '{search_text}'\n"
    result += f"📁 Found in {len(results)} files (searched {len(code_files)} files)\n"
    result += "────────────────────────\n"

    for i, res in enumerate(results, 1):
        result += f"\n{i}. {res['relative']}\n"
        result += f"   Matches: {res['occurrences']}\n"
        if res['sample']:
            result += f"   Sample:\n{res['sample']}\n"

    core.add_search_results_to_history('code', search_text, result)
    return result

def _code_show_changes(core) -> str:
    """Show pending code changes"""
    if not core.code_changes_pending:
        return "📭 No pending changes. Use the AI to suggest code fixes."
        
    result = f"📋 PENDING CODE CHANGES ({len(core.code_changes_pending)})\n"
    result += "────────────────────────\n"

    # Order changes by dependencies
    ordered_changes = core._order_changes_by_dependencies(core.code_changes_pending)

    # Group changes by file, preserving file order
    changes_by_file = {}
    file_order = []
    for change in ordered_changes:
        file_path = change['file_path']
        if file_path not in changes_by_file:
            changes_by_file[file_path] = []
            file_order.append(file_path)
        changes_by_file[file_path].append(change)

    for file_path, changes in changes_by_file.items():
        result += f"\n📄 File: {file_path}\n"
        for change in changes:
            result += f"  • {change['description']}\n"
            if 'old_code' in change and 'new_code' in change:
                result += f"    Change:\n"
                result += f"    - {change['old_code'][:100]}{'...' if len(change['old_code']) > 100 else ''}\n"
                result += f"    + {change['new_code'][:100]}{'...' if len(change['new_code']) > 100 else ''}\n"
        
    result += f"\n💡 Apply changes with: /code apply"
    result += f"\n💡 Clear changes with: /code clear"

    return result

def _code_apply_changes(core) -> str:
    """Apply pending code changes with confirmation"""
    if not core.code_changes_pending:
        return "📭 No pending changes to apply."

    # Show what will be changed
    result = _code_show_changes(core, )
    result += "\n\n" + "="*60 + "\n"
    result += f"{core.formatter.warning('WARNING: This will modify files on disk!')}\n"
    result += "="*60 + "\n\n"

    # Ask for confirmation
    result += "Are you sure you want to apply these changes? (yes/no): "

    # In the CLI, we would handle this interactively
    # For now, return instructions
    result += "\n\n💡 To apply, type 'yes' and then run '/code apply confirm'"
    result += "\n💡 Or use '/code apply force' to apply without interactive confirmation"
        
    return result
def _order_changes_by_dependencies(core, changes):
    """Order changes based on file dependencies."""
    if not changes:
        return changes
    # Determine root path: use agent_root for self-modifications, else code_analyzer.root_path
    import os
    root_path = core.agent_root if hasattr(core, 'agent_root') else (core.code_analyzer.root_path if core.code_analyzer else os.getcwd())
    planner = Planner(root_path)
    ordered = planner.plan_changes(changes)
    return ordered

def _code_apply_changes_confirm(core, force: bool = False) -> str:
    """Actually apply the changes (called after confirmation)"""
    if not core.code_changes_pending:
        return " No pending changes to apply."

    applied = []
    failed = []

    # Order changes by dependencies
    ordered_changes = core._order_changes_by_dependencies(core.code_changes_pending)

    # Group changes by file, preserving file order
    changes_by_file = {}
    file_order = []
    for change in ordered_changes:
        file_path = change['file_path']
        if file_path not in changes_by_file:
            changes_by_file[file_path] = []
            file_order.append(file_path)
        changes_by_file[file_path].append(change)

    # Apply changes to each file
    for file_path in file_order:
        changes = changes_by_file[file_path]
        try:
            # Check if this is a self-modification
            if core._is_self_modification(file_path):
                # Use self-iteration framework for safety
                si = core._get_self_iteration()
                file_applied = False
                for change in changes:
                    if 'old_code' in change and 'new_code' in change:
                        success, msg, backup = si.apply_change(
                            file_path,
                            change['old_code'],
                            change['new_code'],
                            change.get('description', 'Unknown change')
                        )
                        if success:
                            file_applied = True
                        else:
                            failed.append(f"{file_path}: {msg}")
                if file_applied:
                    applied.append(file_path)
                continue  # Skip original logic

            # Original logic for non-self modifications
            # Read current file
            success, message, content = core.code_analyzer.read_file_safe(file_path)
            if not success:
                failed.append(f"{file_path}: {message}")
                continue

            original_content = content

            # Apply changes in reverse order (to preserve line numbers)
            # FIX: Handle None values in sorting
            changes_sorted = sorted(
                changes, 
                key=lambda x: x.get('line') if x.get('line') is not None else 0, 
                reverse=True
            )

            for change in changes_sorted:
                if 'old_code' in change and 'new_code' in change:
                    # Simple string replacement (could be more sophisticated)
                    if change['old_code'] in content:
                        content = content.replace(change['old_code'], change['new_code'])
                    else:
                        # Try line-based replacement
                        lines = content.split('\n')
                        line_num = change.get('line')
                        if line_num and 0 < line_num <= len(lines):
                            lines[line_num - 1] = change['new_code']
                            content = '\n'.join(lines)
                        else:
                            # Try fuzzy matching - find similar code
                            old_code_stripped = change['old_code'].strip()
                            lines = content.split('\n')
                            for i, line in enumerate(lines):
                                if old_code_stripped in line.strip():
                                    lines[i] = change['new_code']
                                    content = '\n'.join(lines)
                                    break
                            else:
                                failed.append(f"{file_path}: Could not find '{change['old_code'][:50]}...' in file")

            # Write back only if changes were made
            if content != original_content:
                success, message, _ = core.safety_manager.safe_write_file(file_path, content, create_backup=True)
                if not success:
                    failed.append(f"{file_path}: {message}")
                    continue
                applied.append(file_path)
            else:
                failed.append(f"{file_path}: No changes were made (old_code not found)")

        except Exception as e:
            failed.append(f"{file_path}: {str(e)}")
        
    # Clear pending changes
    core.code_changes_pending = []

    # Build result
    result = " APPLYING CODE CHANGES\n"
    result += "\n"
        
    if applied:
        result += f"\n{core.formatter.success(f'Successfully applied changes to {len(applied)} files:')}\n"
        for file_path in applied:
            result += f"   📄 {file_path}\n"

    if failed:
        result += f"\n{core.formatter.error(f'Failed to apply changes to {len(failed)} files:')}\n"
        for error in failed:
            result += f"   {core.formatter.warning(error)}\n"

    if not applied and not failed:
        result += "\n📭 No changes were applied."
        
    return result

def _code_clear_changes(core) -> str:
    """Clear all pending changes"""
    count = len(core.code_changes_pending)
    core.code_changes_pending = []
    return f"🧹 Cleared {count} pending changes."

def _code_self_scan(core) -> str:
    """Scan the agent's own codebase."""
    if not core.code_analyzer:
        core.code_analyzer = CodeAnalyzer(core.agent_root, safety_manager=core.safety_manager)
    summary = core.code_analyzer.get_code_summary()
    result = "🔍 SELF-SCAN: Agent's own codebase\n"
    result += f"Root: {core.agent_root}\n"
    result += f"Total files: {summary['total_files']}\n"
    if 'file_types' in summary:
        result += "\nFile types:\n"
        for ext, count in summary['file_types'].items():
            result += f"  {ext or 'no ext'}: {count}\n"
    return result

def _code_self_improve(core, feature: str) -> str:
    """Suggest improvements to the agent's own code."""
    try:
        si = core._get_self_iteration()
        # Determine target files
        target_files = []
        if feature and os.path.isfile(feature):
            target_files.append(feature)
        elif feature and os.path.isdir(feature):
            # Directory: find Python files
            for root, dirs, files in os.walk(feature):
                dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('__pycache__', '.git')]
                for f in files:
                    if f.endswith('.py'):
                        target_files.append(os.path.join(root, f))
        else:
            # Default: agent's own Python files
            for root, dirs, files in os.walk(core.agent_root):
                dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('__pycache__', '.git')]
                for f in files:
                    if f.endswith('.py'):
                        target_files.append(os.path.join(root, f))

        if not target_files:
            return core.formatter.error("No Python files found to improve.")

        total_suggestions = 0
        result = f"🔍 Self-improvement scan: {len(target_files)} Python files\n"

        for file_path in target_files:
            suggestions = si.suggest_improvements(file_path)
            if suggestions:
                result += f"\n📄 {os.path.relpath(file_path, core.agent_root)}:\n"
                for sugg in suggestions:
                    # Propose change
                    core.propose_code_change(
                        file_path=file_path,
                        old_code=sugg['old_code'],
                        new_code=sugg['new_code'],
                        description=sugg['description']
                    )
                    result += f"  • {sugg['description']}\n"
                    total_suggestions += 1

        if total_suggestions == 0:
            result += f"\n{core.formatter.success('No improvements suggested (code looks good!).')}"
        else:
            result += f"\n💡 {total_suggestions} improvement(s) proposed. Use '/code changes' to review, '/code apply' to apply."

        return result
    except Exception as e:
        return core.formatter.error(f"Error during self-improvement: {str(e)}")

def _code_self_apply(core) -> str:
    """Apply vetted self-improvements with safety checks."""
    # Check if there are pending changes
    if not core.code_changes_pending:
        return "📭 No pending changes to apply."

    # Ensure all changes are self-modifications (optional)
    non_self = []
    for change in core.code_changes_pending:
        if not core._is_self_modification(change['file_path']):
            non_self.append(change['file_path'])
    if non_self:
        return core.formatter.error(f"Self-apply only works on agent's own code. Non-self files: {', '.join(set(non_self))}")

    # Run pre-tests using self-iteration framework
    si = core._get_self_iteration()
    test_success, test_msg = si.run_basic_tests()
    if not test_success:
        return core.formatter.error(f"Pre-test suite failed: {test_msg}. Aborting self-apply.")

    # Apply changes using existing logic (which will use self-iteration with tests)
    result = _code_apply_changes_confirm(core, force=True)

    # Run post-tests (optional) - already done per file in apply_change
    # Add note about tests
    return "🔧 Self-apply completed with safety checks.\n" + result
def _code_reason(core, file_path: str) -> str:
    """Deep analysis of a file using reasoning model (chain-of-thought)."""
    if not file_path:
        return core.formatter.error("Please specify a file path")

    # Read file
    if not core.code_analyzer:
        return core.formatter.error("No codebase scanned. Use '/code scan <path>' first.")

    success, message, content = core.code_analyzer.read_file_safe(file_path)
    if not success:
        return core.formatter.error(f"Cannot read file: {message}")

    # Use deepseek-reasoner for deep analysis (temporary switch)
    reasoner_model = "deepseek-reasoner"
    model_used = core.model  # default

    # Construct prompt for analysis
    prompt = f"""Please analyze the following code file using chain-of-thought reasoning.
Provide a detailed analysis covering:
1. Code structure and organization
2. Potential bugs or issues
3. Performance considerations
4. Readability and maintainability
5. Suggested improvements with reasoning

File: {file_path}
Code:
```python
{content}
```

Please think step by step and provide your analysis:"""

    messages = [
        {"role": "user", "content": prompt}
    ]

    # Define analysis function to run with temporary model
    def perform_analysis():
        print(f"[Reasoner] Using model '{core.model}' for deep analysis...")
        return core.generate_completion(messages, temperature=0.3, max_tokens=4000)

    try:
        analysis = core.with_model(reasoner_model, perform_analysis)
        model_used = reasoner_model
    except ValueError as e:
        # Fallback to current model if reasoner not available
        print(f"Warning: {e}. Falling back to current model '{core.model}'.")
        analysis = perform_analysis()
        model_used = core.model

    if analysis.startswith("Error generating completion"):
        return core.formatter.error(analysis)

    result = f"[Analysis] DEEP ANALYSIS (using {model_used}): {os.path.basename(file_path)}\n"
    result += f"Path: {file_path}\n"
    line_count = content.count('\n')
    result += f"Stats: Content length: {len(content)} characters, {line_count} lines\n"
    result += "────────────────────────\n"
    result += analysis
    result += "\n\nTip: Use '/code analyze' for structural analysis or '/code self-improve' to propose changes."

    return result

def propose_code_change(core, file_path: str, old_code: str, new_code: str,
                       description: str, line: int = None) -> str:
    """
    Propose a code change (called by AI analysis)
    Returns: Confirmation message and adds to pending changes
    """
    change = {
        'file_path': file_path,
        'old_code': old_code,
        'new_code': new_code,
        'description': description,
        'line': line,
        'proposed_at': time.time()
    }
        
    core.code_changes_pending.append(change)
        
    result = f"💡 CODE CHANGE PROPOSED\n"
    result += f"File: {file_path}\n"
    result += f"Description: {description}\n"
    result += f"\nChange Preview:\n"
    result += f"- {old_code[:100]}{'...' if len(old_code) > 100 else ''}\n"
    result += f"+ {new_code[:100]}{'...' if len(new_code) > 100 else ''}\n"
    result += f"\n💡 View all pending changes with: /code changes"
    result += f"\n💡 Apply changes with: /code apply"
        
    return result
    
def search_sync(core, query: str) -> str:
    """Run async search from sync code"""
    if not core.search_loop:
        core.search_loop = asyncio.new_event_loop()

    return core.search_loop.run_until_complete(
        core.searcher.search(query)
    )

def add_to_history(core, role: str, content: str):
    """Add message to conversation history"""
    core.conversation_history.append({"role": role, "content": content})

def add_search_results_to_history(core, search_type: str, query: str, results: str):
    """
    Add search results to conversation history as system message.

    Args:
        search_type: 'web' or 'code'
        query: The search query
        results: The search results text
    """
    if search_type == 'web':
        prefix = "🔍 Web search results for"
    elif search_type == 'code':
        prefix = "📁 Code search results for"
    else:
        prefix = "Search results for"

    message = f"{prefix} '{query}':\n\n{results}"
    core.add_to_history("system", message)

def clear_history(core):
    """Clear conversation history"""
    core.conversation_history = []

def get_conversation_summary(core) -> str:
    """Return a summary of the conversation history."""
    total_messages = len(core.conversation_history)
    token_count = core.context_manager.count_conversation_tokens()
    return f"Conversation summary: {total_messages} messages, {token_count} tokens."

def get_token_count(core) -> int:
    """Return total token count of conversation history."""
    return core.context_manager.count_conversation_tokens()

def _ensure_system_prompt(core):
    """Ensure system prompt is present in conversation history."""
    if not agent_config.system_prompt:
        return
    # Check if any system prompt already exists
    system_prompt_text = agent_config.system_prompt
    for msg in core.conversation_history:
        if msg["role"] == "system" and msg["content"] == system_prompt_text:
            return
    # Add system prompt at the beginning
    core.conversation_history.insert(0, {"role": "system", "content": system_prompt_text})

def toggle_thinking_mode(core):
    """Toggle thinking mode on/off and save to config"""
    core.thinking_enabled = not core.thinking_enabled
    try:
        success = agent_config.update_value("agent.thinking_enabled", core.thinking_enabled)
        if success:
            print(f"✓ Thinking mode {'enabled' if core.thinking_enabled else 'disabled'} (saved to config)")
        else:
            print(f"✓ Thinking mode {'enabled' if core.thinking_enabled else 'disabled'} (but failed to save config)")
    except Exception as e:
        print(f"✓ Thinking mode {'enabled' if core.thinking_enabled else 'disabled'} (config update error: {e})")
    return core.thinking_enabled

def debug_agent_status(core):
    """Show current agent status for debugging"""
    print(f"\n🔍 AGENT DEBUG INFO:")
    print(f"  • Model: {core.model}")
    print(f"  • API Key: {'Set' if core.api_key else 'Not set'}")
    print(f"  • Conversation history length: {len(core.conversation_history)}")
    print(f"  • Code analyzer: {'Initialized' if core.code_analyzer else 'Not initialized'}")
    print(f"  • Auto-fix mode: {'ACTIVE' if hasattr(core, 'auto_fix_mode') and core.auto_fix_mode else 'Inactive'}")
        
    if hasattr(core, 'current_fix_file'):
        print(f"  • Current fix file: {core.current_fix_file}")
        
    print(f"  • Pending changes: {len(core.code_changes_pending)}")

def stream_response(core, prompt: str, temperature: float = 0.7, max_tokens: int = 2048 * 4):
    """Stream response with auto-file detection, analysis, and auto-fix capabilities"""
    import re
    import sys
    import os

    # Color support for thinking content (light gray)
    COLORS_ENABLED = sys.stdout.isatty() and os.getenv('TERM') not in ('dumb', '')
    COLOR_THINKING = '\033[90m'  # Light gray
    COLOR_RESET = '\033[0m'

    # Auto-detect if this is a code-related query
    if not prompt.startswith(('/fix', '/analyze', '/code', '/read', '/search', '/models')):
        if core.is_code_related_query(prompt):
            core._status_print(f"🔍 Detected code-related query. Adding code context...", "debug")
            core.add_code_context_instructions()

    core._status_print(f"🔄 Processing command: {prompt[:50]}{'...' if len(prompt) > 50 else ''}", "info")

    # Quick input classification (URLs, file paths, etc.)
    modified_prompt = prompt
    classified_cmd = core.classify_and_enhance_input(prompt)
    if classified_cmd:
        core._status_print(f"🎯 Classified as: {classified_cmd}", "debug")
        modified_prompt = classified_cmd
        # Skip natural language interpretation since we already classified
        skip_natural_language = True
    else:
        skip_natural_language = False

    # Natural language interpretation (skip if already classified)
    if not skip_natural_language and core.natural_language_enabled and core.interpreter:
        suggested_cmd, confidence = core.interpreter.interpret(prompt, core.mode)
        if suggested_cmd and confidence >= core.interpreter.confidence_threshold:
            core._status_print(f"🤖 Interpreting as: {suggested_cmd} (confidence: {confidence:.2f})", "debug")
            log_operation("natural_language_interpretation", prompt, True,
                         f"interpreted_as={suggested_cmd}, confidence={confidence:.2f}")
            modified_prompt = suggested_cmd

    # Auto-search detection (skip if already a command)
    if (core.auto_search_enabled and
        not modified_prompt.startswith('/') and
        core.searcher.should_search(modified_prompt)):
        core._status_print(f"🔍 Auto-detected search needed for: {modified_prompt[:50]}...", "debug")
        log_operation("auto_search_triggered", modified_prompt, True,
                     f"query_length={len(modified_prompt)}")
        success, results = core.search_sync(modified_prompt)
        if success:
            log_operation("auto_search_results", modified_prompt, True,
                         f"results_length={len(results)}")
            core.add_search_results_to_history('web', modified_prompt, results)
            modified_prompt = f"Web search results:\n{results}\n\nUser question: {modified_prompt}"
        else:
            log_operation("auto_search_failed", modified_prompt, False,
                         "search returned no results or error")
            core.add_to_history("system", f"Web search failed for '{modified_prompt}': {results}")

    # Update prompt with modifications
    prompt = modified_prompt

    # Auto-detect file paths before handling commands (skip if already a read command)
    file_content = None
    if not prompt.startswith(('/read', '/code read', '/fix', '/analyze')):
        file_content = core.auto_detect_and_read_file(prompt)
    if file_content:
        # Extract just the filename from path
        file_match = re.search(r'([^\\/]+\.\w+)$', prompt)
        filename = file_match.group(1) if file_match else "file"
        # Inject the file content into the prompt so the model can analyze it directly
        prompt = (
            f"{prompt}\n\n"
            f"<file path=\"{filename}\">\n"
            f"{file_content}\n"
            f"</file>"
        )

    # Handle commands using registry
    skip_user_add = False
    command_handled = False
    # Sort prefixes by length descending to match longest first
    for prefix in sorted(core.command_handlers.keys(), key=len, reverse=True):
        if prompt.startswith(prefix):
            handler, strip_prefix = core.command_handlers[prefix]
            arg = prompt[len(prefix):].strip() if strip_prefix else prompt
            cmd_start_time = time.time()
            response = handler(arg)
            cmd_duration = (time.time() - cmd_start_time) * 1000  # Convert to ms
            command_handled = True

            # Log command execution to unified logger
            if core._unified_logger:
                try:
                    core._unified_logger.log_command(
                        cmd=f"{prefix} {arg}" if arg else prefix,
                        exit_code=0 if response is not None else 1,
                        duration_ms=cmd_duration,
                        mode=core.mode,
                    )
                except Exception as e:
                    core._status_print(f"Unified logger command log failed (non-fatal): {e}", "debug")

            # Special handling for /fix and /analyze
            if prefix in ["/fix", "/analyze"]:
                skip_user_add = True
                if response is not None:
                    core._safe_print(f"\n{response}\n")
                # Continue to API call
                break

            # Special handling for /code apply confirm
            if prefix == "/code":
                subcommand = arg
                if subcommand.startswith("apply confirm") or subcommand == "apply force":
                    force = "force" in subcommand
                    response = _code_apply_changes_confirm(core, force)

            # For other commands, print response and return
            if response is not None:
                core._safe_print(f"\n{response}\n")

                # Feed tool output to LLM so it can reason about results
                if prefix in core.COMMANDS_FEED_TO_LLM and response:
                    truncated = core._truncate_middle(str(response))
                    core.add_to_history("user", f"[Tool: {prefix}] {truncated}")

                return None

            # response is None → handler wants us to continue to LLM
            # (e.g. /search with comprehension intent adds context to history)
            if response is None and prefix == "/search":
                skip_user_add = True  # context already added by handle_search
                command_handled = False  # fall through to LLM
                break

            return None

    # If no command matched
    if not command_handled:
        skip_user_add = False

    # Check if caller already added the user message (agentic loop re-prompt)
    if getattr(core, '_skip_next_user_add', False):
        skip_user_add = True
        core._skip_next_user_add = False

    # Regular chat processing (skip if we already added in handle_auto_fix_command)
    if not skip_user_add:
        core.add_to_history("user", prompt)

    # Context management check (use model-specific default)
    spec = core._get_model_spec(core.model)
    actual_max_tokens = max_tokens or spec["default_max"]
    should_continue = core.context_manager.interactive_context_management(additional_tokens=actual_max_tokens)
    # Ensure system prompt is present regardless of choice (unless cancelled)
    core._ensure_system_prompt()
    # Re-add user prompt if it was removed during compression/clear
    user_prompt_exists = any(
        msg["role"] == "user" and msg["content"] == prompt
        for msg in core.conversation_history
    )
    if not user_prompt_exists and not skip_user_add:
        core.add_to_history("user", prompt)
    if not should_continue:
        return None

    core._status_print(f"Sending request ({len(core.conversation_history)} messages)", "debug")

    # Resolve provider for current model (may be DeepSeek or z.ai)
    provider = core._resolve_provider()
    request_api_key = provider["api_key"] or core.api_key
    request_base_url = provider["base_url"]

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {request_api_key}"
    }

    # Model-specific limits
    spec = core._get_model_spec(core.model)
    total_tokens = core.context_manager.count_conversation_tokens()
    max_context = spec["max_context"]
    actual_max_tokens = max_tokens or spec["default_max"]
    # Clamp to model's hard output limit
    actual_max_tokens = min(actual_max_tokens, spec["max_output"])
    if total_tokens + actual_max_tokens > max_context:
        new_max = max(1, max_context - total_tokens)
        core._status_print(f"⚠️  Context limit: reducing max_tokens from {actual_max_tokens} to {new_max}", "info")
        actual_max_tokens = new_max
    elif total_tokens > agent_config.context_warning_threshold * max_context:
        core._status_print(f"⚠️  Context warning: {total_tokens}/{max_context} tokens used", "info")

    # ── Inject sprint context if active ────────────────────────────────────
    messages_for_api = core.conversation_history.copy()
    if core.current_sprint_id and core.sprint_mgr and HAS_SPRINT:
        try:
            sprint_prompt = core.sprint_mgr.get_sprint_prompt(core.current_sprint_id)
            if sprint_prompt:
                # Inject sprint context as system message (after base system prompt)
                system_msg_idx = 0
                for i, msg in enumerate(messages_for_api):
                    if msg["role"] == "system":
                        system_msg_idx = i + 1
                        break
                messages_for_api.insert(system_msg_idx, {
                    "role": "system",
                    "content": sprint_prompt
                })
                core._status_print(f"📋 Sprint context injected", "debug")
        except Exception as e:
            core._status_print(f"⚠️  Sprint context inject failed: {e}", "debug")

    # ── Integration hooks: pre-LLM check (degradation, distillation, output limits) ──
    _pre_call_result = None
    try:
        from agent.evolution.integration_hooks import pre_llm_call
        _pre_call_result = pre_llm_call(
            prompt=prompt, mode=core.mode, model=core.model,
            max_tokens=actual_max_tokens,
        )
        if _pre_call_result.get("skip_api"):
            # STATIC tier fallback — don't call API
            fallback = _pre_call_result.get("fallback_response", "")
            if fallback:
                core.add_to_history("assistant", fallback)
                core._status_print(f"⚡ Degraded mode: using static fallback", "info")
                return fallback
        if _pre_call_result.get("adjusted_max_tokens"):
            actual_max_tokens = _pre_call_result["adjusted_max_tokens"]
        if _pre_call_result.get("distillation_used"):
            core._status_print(f"🧪 Distillation: exemplar injected", "debug")
    except ImportError:
        pass  # hooks not available
    except Exception as e:
        core._status_print(f"Pre-call hooks error (non-fatal): {e}", "debug")

    # Respect model-level fixed temperature (e.g. kimi-k2.5 only accepts temperature=1)
    actual_temperature = spec.get("fixed_temperature", temperature or agent_config.temperature)

    payload = {
        "model": core.model,
        "messages": messages_for_api,
        "stream": True,
        "temperature": actual_temperature,
        "max_tokens": actual_max_tokens,
    }

    # Only add thinking param for providers that support it (DeepSeek)
    if core.thinking_enabled and provider.get("name") == "deepseek":
        payload["thinking"] = {"type": "enabled"}
        core._status_print(f"Thinking mode: on", "debug")

    try:
        core._status_print(f"Connecting to API...", "debug")

        # Start timing
        start_time = time.time()

        # Spinner is now handled by the UI layer (NeoMindInterface._stream_and_render)
        # We just notify when first token arrives via _ui_on_first_token callback

        response = requests.post(
            request_base_url,
            headers=headers,
            json=payload,
            stream=True,
            timeout=60
        )

        elapsed_time = time.time() - start_time
        core._status_print(f"Connected to {provider['name']} ({elapsed_time:.1f}s, status {response.status_code})", "debug")

        if response.status_code != 200:
            core._status_print(f"❌ Error {response.status_code}: {response.text}", "critical")
            core.conversation_history.pop()
            return None

        core._status_print(f"Streaming response...", "debug")

        full_response = ""
        reasoning_content = ""
        is_reasoning_active = False
        is_final_response_active = False
        has_seen_reasoning = False
        first_token_notified = False
        thinking_start_time = None
        last_thinking_summary_time = 0
        content_was_displayed = False  # Track if any visible content was printed

        # Callback to notify UI layer (spinner) on first token
        def _notify_first_token():
            nonlocal first_token_notified
            if not first_token_notified:
                first_token_notified = True
                cb = getattr(core, '_ui_on_first_token', None)
                if cb:
                    try:
                        cb()
                    except Exception:
                        pass

        def _summarize_thinking(text, max_len=100):
            """Extract a brief summary from thinking content for spinner display."""
            # Take the last meaningful sentence/phrase
            lines = text.strip().split('\n')
            for line in reversed(lines):
                line = line.strip()
                if len(line) > 5:
                    if len(line) > max_len:
                        # Try to cut at a word boundary
                        cut = line[:max_len].rfind(' ')
                        if cut > max_len // 2:
                            return line[:cut] + "…"
                        return line[:max_len - 1] + "…"
                    return line
            return ""

        def _update_thinking_spinner(reasoning_so_far):
            """Update the spinner label with a thinking summary (via stderr)."""
            nonlocal last_thinking_summary_time
            now = time.time()
            # Update at most every 0.5 seconds to keep it responsive
            if now - last_thinking_summary_time < 0.5:
                return
            last_thinking_summary_time = now
            summary = _summarize_thinking(reasoning_so_far)
            if summary:
                elapsed = now - (thinking_start_time or now)
                sys.stderr.write(f"\r\033[K\033[36m⠸\033[0m Thinking… \033[2m{summary}\033[0m")
                sys.stderr.flush()

        try:
            for line in response.iter_lines():
                if line:
                    line = line.decode('utf-8')
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            core._status_print(f"Stream complete", "debug")
                            break
                        try:
                            json_data = json.loads(data)
                            if "choices" in json_data and json_data["choices"]:
                                delta = json_data["choices"][0].get("delta", {})
                                reasoning_chunk = delta.get("reasoning_content")

                                if reasoning_chunk is not None:
                                    if reasoning_chunk and not is_reasoning_active:
                                        # Don't stop spinner yet — keep it running
                                        # during thinking, just update its label
                                        is_reasoning_active = True
                                        is_final_response_active = False
                                        has_seen_reasoning = True
                                        thinking_start_time = time.time()

                                    if reasoning_chunk:
                                        reasoning_content += reasoning_chunk
                                        # Update spinner with thinking summary
                                        _update_thinking_spinner(reasoning_content)

                                content = delta.get("content", "")
                                if content:
                                    if not is_final_response_active:
                                        # Transition: thinking → response
                                        _notify_first_token()  # Stop spinner

                                        if has_seen_reasoning and thinking_start_time:
                                            # Show condensed thinking summary
                                            elapsed = time.time() - thinking_start_time
                                            summary = _summarize_thinking(reasoning_content)
                                            if COLORS_ENABLED:
                                                if summary:
                                                    print(f"{COLOR_THINKING}Thought for {elapsed:.1f}s — {summary}{COLOR_RESET}")
                                                else:
                                                    print(f"{COLOR_THINKING}Thought for {elapsed:.1f}s{COLOR_RESET}")
                                            else:
                                                if summary:
                                                    print(f"Thought for {elapsed:.1f}s — {summary}")
                                                else:
                                                    print(f"Thought for {elapsed:.1f}s")
                                        else:
                                            _notify_first_token()
                                        is_final_response_active = True
                                        is_reasoning_active = False

                                    # Accumulate full response regardless of filter
                                    full_response += content
                                    # Content filter: suppress code fences if active
                                    _cf = getattr(core, '_content_filter', None)
                                    if _cf:
                                        display = _cf.write(content)
                                        if display:
                                            print(display, end="", flush=True)
                                            content_was_displayed = True
                                    else:
                                        print(content, end="", flush=True)
                                        content_was_displayed = True

                        except json.JSONDecodeError:
                            continue
        except KeyboardInterrupt:
            _notify_first_token()
            print("\n[interrupted]")
            response.close()
            if full_response:
                core.add_to_history("assistant", full_response + "\n[interrupted]")
                return full_response
            else:
                core.conversation_history.pop()
                return None

        # Flush content filter if active
        _cf = getattr(core, '_content_filter', None)
        if _cf:
            remaining = _cf.flush()
            if remaining:
                print(remaining, end="", flush=True)
                content_was_displayed = True

        # Track whether content was visible (used by agentic loop)
        core._last_content_was_displayed = content_was_displayed

        # Add the complete response to history
        if full_response:
            # ── Personality-driven response enhancement ──────────────────
            # Finance mode: validator adds disclaimers for unsubstantiated claims
            # Other modes: enhance_response() is a passthrough (returns unchanged)
            if core._active_personality:
                try:
                    tool_results_this_turn = []
                    for msg in reversed(core.conversation_history):
                        if msg.get("role") == "user":
                            break
                        if msg.get("role") == "system" and "[Tool:" in msg.get("content", ""):
                            tool_results_this_turn.append({"content": msg["content"]})
                    enhanced = core._active_personality.enhance_response(
                        full_response, tool_results_this_turn
                    )
                    if enhanced != full_response and content_was_displayed:
                        # Print any appended disclaimer text
                        print(enhanced[len(full_response):], end="", flush=True)
                    full_response = enhanced
                except Exception as e:
                    core._status_print(f"Response enhancement error (non-fatal): {e}", "debug")

            core.add_to_history("assistant", full_response)
            if content_was_displayed:
                print()  # Clean newline after visible streaming output

            # ── Periodic vault watcher check (every 50 turns) ──────────
            if core._vault_watcher:
                core._response_turn_count += 1
                if core._response_turn_count >= 50:
                    core._response_turn_count = 0
                    try:
                        changed_context = core._vault_watcher.get_changed_context(
                            mode=getattr(core, 'mode', 'chat')
                        )
                        if changed_context:
                            core.add_to_history("system", changed_context)
                            core._vault_watcher.mark_seen()
                            core._status_print(
                                "Detected vault changes from Obsidian — updated context",
                                "debug"
                            )
                    except Exception as e:
                        core._status_print(f"Vault watcher check failed (non-fatal): {e}", "debug")

            # ── Log to evidence trail ────────────────────────────────────
            # Get the user's prompt (last user message before this response)
            user_prompt = ""
            for msg in reversed(core.conversation_history[:-1]):  # Exclude the assistant response we just added
                if msg["role"] == "user":
                    user_prompt = msg["content"]
                    break
            core._log_evidence("llm_call", user_prompt[:200], full_response[:200], severity="info")

            # ── Log to unified logger ────────────────────────────────────
            # Track LLM API calls with token usage and latency
            if core._unified_logger:
                try:
                    prompt_tokens = core.context_manager.count_conversation_tokens()
                    completion_tokens = core.context_manager.count_tokens(full_response)
                    latency_ms = (time.time() - start_time) * 1000 if start_time else 0
                    core._unified_logger.log_llm_call(
                        model=core.model,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        latency_ms=latency_ms,
                        mode=core.mode,
                        thinking_enabled=core.thinking_enabled,
                    )
                except Exception as e:
                    core._status_print(f"Unified logger LLM call failed (non-fatal): {e}", "debug")

            # ── Integration hooks: post-response (drift, distillation, degradation) ──
            try:
                from agent.evolution.integration_hooks import post_response as _post_hook
                _elapsed = (time.time() - start_time) * 1000 if 'start_time' in dir() else 0
                _post_hook(
                    prompt=user_prompt or prompt,
                    response=full_response,
                    mode=core.mode,
                    model=core.model,
                    latency_ms=_elapsed,
                    tokens_used=getattr(core.context_manager, '_last_token_count', 0),
                    success=bool(full_response),
                    pre_call_result=_pre_call_result if '_pre_call_result' in dir() else None,
                )
            except ImportError:
                pass
            except Exception:
                pass  # Non-fatal

            # ── SharedMemory: learn from conversation ───────────────
            # Record patterns from user prompts (lightweight extraction)
            if core._shared_memory and user_prompt:
                try:
                    core._learn_patterns_from_turn(user_prompt, full_response)
                except Exception:
                    pass  # Non-fatal — never block response delivery

            # ── Evolution: check for scheduled tasks every N turns ─────────
            if core.evolution_scheduler:
                core._turn_counter += 1
                try:
                    actions = core.evolution_scheduler.on_turn_complete(core._turn_counter)
                    if actions:
                        for action in actions:
                            core._status_print(f"✨ {action}", "debug")
                except Exception:
                    pass  # Non-fatal — never block response delivery

            # ── AutoDream: attempt memory consolidation during idle ────────
            if hasattr(core, 'services') and core.services is not None:
                try:
                    dream = core.services.auto_dream
                    if dream is not None:
                        dream.on_turn_complete()
                        history = getattr(core, 'conversation_history', None)
                        if history:
                            dream.maybe_consolidate(history)
                except Exception:
                    pass  # Non-fatal

                # ── Session Notes: auto-update structured notes ──────────
                try:
                    notes = core.services.session_notes
                    if notes is not None:
                        history = getattr(core, 'conversation_history', None)
                        tool_count = getattr(core, '_tool_call_count', 0)
                        total_chars = sum(len(str(m.get('content', ''))) for m in (history or []))
                        est_tokens = total_chars // 4
                        notes.maybe_update(
                            messages=history or [],
                            tool_count=tool_count,
                            est_tokens=est_tokens,
                        )
                except Exception:
                    pass  # Non-fatal

                # ── Frustration detection on last user message ─────────
                try:
                    detector = core.services.frustration_detector
                    if detector and core.conversation_history:
                        last_user = None
                        for m in reversed(core.conversation_history):
                            if m.get('role') == 'user':
                                last_user = str(m.get('content', ''))
                                break
                        if last_user:
                            signals = detector(last_user)
                            if signals:
                                from agent.services.frustration_detector import get_frustration_guidance
                                guidance = get_frustration_guidance(signals)
                                if guidance:
                                    core._status_print(f"📊 {guidance}", "debug")
                except Exception:
                    pass  # Non-fatal

                # ── JSONL session storage: append messages ─────────────
                try:
                    sw = core.services.session_storage_writer
                    if sw and full_response:
                        sw.append_message('assistant', full_response[:10000])
                        sw.flush()
                except Exception:
                    pass  # Non-fatal

        # Store thinking content for expansion later
        if reasoning_content:
            if not hasattr(core, '_thinking_history'):
                core._thinking_history = []
            core._thinking_history.append({
                "timestamp": time.time(),
                "thinking": reasoning_content,
                "response_preview": full_response[:200] if full_response else "",
                "duration": (time.time() - thinking_start_time) if thinking_start_time else 0,
            })

        # ============================================
        # AUTO-FIX LOGIC
        # ============================================

        # Check if we're in auto-fix mode and have a file to fix
        if (hasattr(core, 'auto_fix_mode') and core.auto_fix_mode and
            hasattr(core, 'current_fix_file') and core.current_fix_file and
            full_response):

            print(f"\n{'='*80}")
            core._safe_print(f"🔧 AUTO-FIX MODE: Processing AI response...")
            print(f"{'='*80}")

            # Parse the AI response for PROPOSED CHANGE blocks
            changes_found = core._parse_ai_changes_for_file(full_response, core.current_fix_file)

            if changes_found > 0:
                print(f"✅ Found {changes_found} proposed change(s)")
                _handle_auto_fix_confirmation(core, )
            else:
                print(f"📭 No PROPOSED CHANGE blocks found")
                print(f"💡 Tip: Ask the AI to use the PROPOSED CHANGE format")

            # Reset auto-fix mode
            core.auto_fix_mode = False
            core.current_fix_file = None

        return full_response

    except requests.exceptions.Timeout:
        print(f"\n❌ Request timed out after 60 seconds")
        print(f"💡 Try reducing the file size or using a simpler query")
        core.conversation_history.pop()
        return None
    except requests.exceptions.RequestException as e:
        print(f"\n❌ Network error: {e}")
        core.conversation_history.pop()
        return None
    except Exception as e:
        print(f"\n⚠️  Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return None

    # Note: Timeout and RequestException are already handled above

async def stream_response_async(core, prompt: str, **kwargs):
    """Async version - handles search and model commands asynchronously"""
    # Special case for /search (native async)
    if prompt.startswith("/search"):
        query = prompt[7:].strip()
        core._safe_print(f"\n🔍 Searching for: {query}")
        success, result = await core.searcher.search(query)
        if success:
            core.add_search_results_to_history('web', query, result)
        else:
            # Add error to history as system message
            core.add_to_history("system", f"Web search failed for '{query}': {result}")
        core._safe_print(f"\n{result}\n")
        return None

    # Use command registry for other commands (excluding /search, /fix, /analyze)
    for prefix in sorted(core.command_handlers.keys(), key=len, reverse=True):
        if prefix in ["/search", "/fix", "/analyze"]:
            continue
        if prompt.startswith(prefix):
            handler, strip_prefix = core.command_handlers[prefix]
            arg = prompt[len(prefix):].strip() if strip_prefix else prompt
            # Run sync handler in thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, handler, arg)

            # Special handling for /code apply confirm
            if prefix == "/code":
                subcommand = arg
                if subcommand.startswith("apply confirm") or subcommand == "apply force":
                    force = "force" in subcommand
                    response = _code_apply_changes_confirm(core, force)

            if response is not None:
                core._safe_print(f"\n{response}\n")

                # Feed tool output to LLM so it can reason about results
                if prefix in core.COMMANDS_FEED_TO_LLM and response:
                    truncated = core._truncate_middle(str(response))
                    core.add_to_history("user", f"[Tool: {prefix}] {truncated}")

            return None

    # No command matched, fall back to sync stream_response
    return core.stream_response(prompt, **kwargs)

def run_async(core, prompt: str, **kwargs):
    """Helper to run async from sync code"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(
            core.stream_response_async(prompt, **kwargs)
        )
        return result
    finally:
        loop.close()

def _handle_auto_fix_confirmation(core):
    """Handle the auto-fix confirmation flow"""
    if not core.code_changes_pending:
        print(f"📭 No changes to apply")
        return

    print(f"\n📋 CHANGES TO APPLY:")
    print(f"{'-'*80}")

    # Group changes by file
    changes_by_file = {}
    for change in core.code_changes_pending:
        file_path = change['file_path']
        if file_path not in changes_by_file:
            changes_by_file[file_path] = []
        changes_by_file[file_path].append(change)

    for file_path, changes in changes_by_file.items():
        print(f"\n📄 {file_path}:")
        for i, change in enumerate(changes, 1):
            print(f"  {i}. {change['description']}")
            if 'old_code' in change and 'new_code' in change:
                # Show first line of change
                old_first = change['old_code'].split('\n')[0][:50]
                new_first = change['new_code'].split('\n')[0][:50]
                print(f"     - {old_first}{'...' if len(old_first) >= 50 else ''}")
                print(f"     + {new_first}{'...' if len(new_first) >= 50 else ''}")
        
    print(f"\n{'='*80}")

    # Get user confirmation
    print(f"\n❓ Apply these changes?")
    print(f"   Options:")
    print(f"   1. Type 'yes' to apply all changes")
    print(f"   2. Type 'diff' to see the changes before applying")
    print(f"   3. Type 'no' to save as pending changes")
    print(f"   4. Type 'cancel' to discard changes")
    print(f"\n   Your choice: ", end="", flush=True)
        
    try:
        import sys
        if sys.stdin.isatty():
            choice = input().strip().lower()

            if choice in ['yes', 'y', 'ok', 'apply', '1']:
                print(f"\n🔄 Applying changes...")

                # Show diff before applying
                if hasattr(core, 'original_file_content'):
                    success, message, current_content = core.code_analyzer.read_file_safe(core.current_fix_file)
                    if success:
                        print(f"\n📊 Showing changes:")
                        core.show_diff(core.original_file_content, current_content, core.current_fix_file)

                # Apply the changes
                result = _code_apply_changes_confirm(core, force=True)
                print(f"\n{result}")

            elif choice in ['diff', 'show', 'preview', '2']:
                if hasattr(core, 'original_file_content'):
                    success, message, current_content = core.code_analyzer.read_file_safe(core.current_fix_file)
                    if success:
                        print(f"\n📊 DIFF VIEW:")
                        core.show_diff(core.original_file_content, current_content, core.current_fix_file)

                        # Ask again after showing diff
                        if core.get_user_confirmation("\nApply these changes now?", "no"):
                            print(f"\n🔄 Applying changes...")
                            result = _code_apply_changes_confirm(core, force=True)
                            print(f"\n{result}")
                        else:
                            print(f"\n⏸️  Changes saved as pending.")
                            print(f"💡 Use '/code changes' to review or '/code apply' to apply later.")
                    else:
                        print(f"\n⚠️  Could not show diff: {message}")
                else:
                    print(f"\n⚠️  Original content not available for diff")

            elif choice in ['no', 'n', 'save', '3']:
                print(f"\n⏸️  Changes saved as pending.")
                print(f"💡 Use '/code changes' to review or '/code apply' to apply later.")

            elif choice in ['cancel', 'discard', '4']:
                count = len(core.code_changes_pending)
                core.code_changes_pending = []
                print(f"\n🗑 ️  Discarded {count} pending changes")

            else:
                print(f"\n❓ Unknown option. Changes saved as pending.")
                print(f"💡 Use '/code changes' to review or '/code apply' to apply.")
            
        else:
            print(f"\n⚠️  Non-interactive mode. Changes saved as pending.")
            print(f"💡 Use '/code changes' to review or '/code apply' to apply.")
        
    except (EOFError, KeyboardInterrupt):
        print(f"\n\n⏸️  Input interrupted. Changes saved as pending.")
        print(f"💡 Use '/code changes' to review or '/code apply' to apply.")

    except Exception as e:
        print(f"\n⚠️  Error: {e}")
        print(f"💡 Changes saved as pending. Use '/code changes' to review.")
    
def auto_detect_and_read_file(core, text: str) -> Optional[str]:
    """
    Automatically detect file paths in text and read them
    Returns: File content if found and readable
    """
    import re  # ADD THIS LINE at the beginning of the method!

    # Patterns for file paths
    patterns = [
        r'[A-Za-z]:\\(?:[^\\/:*?"<>|\r\n]+\\)*[^\\/:*?"<>|\r\n]+\.\w+',  # Windows absolute
        r'/(?:[^/]+\/)*[^/]+\.[a-zA-Z0-9]+',  # Unix absolute
        r'(?:\.{1,2}/)?(?:[^/\s]+/)*[^/\s]+\.[a-zA-Z0-9]+',  # Relative
    ]
        
    for pattern in patterns:
        matches = re.findall(pattern, text)
        for match in matches:
            # Check if it looks like a real file path (not just random text)
            if any(ext in match for ext in ['.py', '.js', '.java', '.txt', '.md', '.json', '.yaml', '.yml', '.html', '.css']):
                # Safety confirmation for auto-file operations
                if core.safety_confirm_file_operations:
                    print(f"🔍 Detected file reference: {match}")
                    response = input("Read file? (y/n): ").strip().lower()
                    if response not in ('y', 'yes'):
                        log_operation("auto_file_read", match, False, "user_denied_confirmation")
                        continue
                    else:
                        log_operation("auto_file_read", match, True, "user_confirmed")
                try:
                    # Try to read the file
                    if not core.code_analyzer:
                        core.code_analyzer = CodeAnalyzer(safety_manager=core.safety_manager)

                    success, message, content = core.code_analyzer.read_file_safe(match)
                    if success:
                        core._safe_print(f"📄 Auto-reading detected file: {match}")
                        log_operation("auto_file_read", match, True, f"size={len(content)}")
                        return content
                    else:
                        log_operation("auto_file_read", match, False, f"reason={message}")
                except Exception as e:
                    log_operation("auto_file_read", match, False, f"exception={str(e)}")
                    continue

    return None

def classify_and_enhance_input(core, text: str) -> Optional[str]:
    """
    Classify input type and convert to appropriate command if it's a direct object.
    Returns command string or None if no classification.
    """
    import re
    text = text.strip()

    # If it's already a command, don't reclassify
    if text.startswith('/'):
        return None

    # 1. URL detection — bare URL or URL with surrounding context
    url_pattern = r'^(https?://[^\s]+)$'
    if re.match(url_pattern, text, re.IGNORECASE):
        core._safe_print(f"🔗 Detected URL: {text}")
        log_operation("url_detection", text, True, "auto_classified_as_url")
        return f"/read {text}"

    # 1b. URL embedded in short text — "帮我看看 https://..." / "read https://..."
    embedded_url = re.search(r'(https?://[^\s]+)', text)
    if embedded_url and len(text) < 200:
        url = embedded_url.group(1)
        context = text[:embedded_url.start()].strip().lower()
        # Crawl intent keywords
        crawl_kw = {'crawl', 'spider', '爬取', '抓取', '爬', '全部', 'all pages', 'entire site', '整个', '全面'}
        # Links intent keywords
        links_kw = {'links', 'link', '链接', '所有链接', 'list links', 'extract links', '提取链接', '列出链接'}

        if any(kw in context for kw in crawl_kw):
            core._safe_print(f"🕷️ Detected crawl intent: {url}")
            log_operation("url_detection", text, True, "auto_classified_as_crawl")
            return f"/crawl {url}"
        elif any(kw in context for kw in links_kw):
            core._safe_print(f"🔗 Detected links intent: {url}")
            log_operation("url_detection", text, True, "auto_classified_as_links")
            return f"/links {url}"
        else:
            # Default: read the URL
            core._safe_print(f"🔗 Detected URL in context: {url}")
            log_operation("url_detection", text, True, "auto_classified_as_url_in_context")
            return f"/read {url}"

    # 2. File path with optional line numbers (e.g., file.py:15, file.py:10-20)
    # Match whole string as a file path
    file_line_pattern = r'^([A-Za-z]:\\(?:[^\\/:*?"<>|\r\n]+\\)*[^\\/:*?"<>|\r\n]+\.\w+)(?::(\d+)(?:-(\d+))?)?$'
    file_line_pattern_unix = r'^(/(?:[^/]+/)*[^/]+\.[a-zA-Z0-9]+)(?::(\d+)(?:-(\d+))?)?$'
    file_line_pattern_rel = r'^((?:\.{1,2}/)?(?:[^/\s]+/)*[^/\s]+\.[a-zA-Z0-9]+)(?::(\d+)(?:-(\d+))?)?$'

    for pattern in [file_line_pattern, file_line_pattern_unix, file_line_pattern_rel]:
        match = re.match(pattern, text)
        if match:
            file_path = match.group(1)
            line_start = match.group(2) if match.group(2) else None
            line_end = match.group(3) if match.group(3) else None

            # Check if it's a known file extension
            if any(ext in file_path for ext in ['.py', '.js', '.java', '.txt', '.md', '.json', '.yaml', '.yml', '.html', '.css']):
                core._safe_print(f"📄 Detected file path with line numbers: {text}")
                log_operation("file_path_detection", text, True, f"path={file_path}, lines={line_start}-{line_end}")

                # Build appropriate command
                if line_start:
                    if line_end:
                        return f"/read {file_path}:{line_start}-{line_end}"
                    else:
                        return f"/read {file_path}:{line_start}"
                else:
                    return f"/read {file_path}"

    # 3. Simple filename (just a filename without path)
    simple_file_pattern = r'^([^/\s]+\.\w+)$'
    match = re.match(simple_file_pattern, text)
    if match:
        filename = match.group(1)
        if any(ext in filename for ext in ['.py', '.js', '.java', '.txt', '.md', '.json', '.yaml', '.yml', '.html', '.css']):
            core._safe_print(f"📄 Detected simple filename: {filename}")
            log_operation("filename_detection", text, True, f"filename={filename}")
            return f"/read {filename}"

    # 4. Code reference pattern (e.g., "function_name()", "ClassName.method", "module.Class")
    # This is more speculative - might trigger false positives
    code_ref_pattern = r'^([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*\(\)?)$'
    match = re.match(code_ref_pattern, text)
    if match and len(text.split()) == 1:  # Single token only
        core._safe_print(f"🔍 Detected possible code reference: {text}")
        log_operation("code_reference_detection", text, True, "possible_code_reference")
        # Could trigger code search, but might be too aggressive
        # Let's not auto-convert this, as it could be many things

    return None

def handle_auto_file_analysis(core, file_path: str) -> str:
    """
    Automatically handle file analysis when mentioned
    """
    if not core.code_analyzer:
        core.code_analyzer = CodeAnalyzer(safety_manager=core.safety_manager)
        
    # Try to read the file
    success, message, content = core.code_analyzer.read_file_safe(file_path)
        
    if not success:
        return core.formatter.error(f"Could not read file {file_path}: {message}")
        
    # Add to conversation history
    core.add_to_history("user", f"""I want to analyze this file:

File: {file_path}

```python
{content[:5000]}  # Limit to avoid token overflow
```

Please analyze this code and suggest any improvements, fixes, or optimizations.""")

    return core.formatter.success(f"Successfully loaded {file_path} for analysis. Please continue with your request.")
    
def handle_auto_fix_command(core, command: str) -> Optional[str]:
    """
    Handle automatic fixing commands:
    /fix <file_path> - Analyze and fix file
    /analyze <file_path> - Analyze file without auto-fix
    """
    parts = command.split()
    if len(parts) < 2:
        print("Usage: /fix <file_path> [description]\nExample: /fix agent/core.py 'fix the error handling'")
        return None

    cmd_type = parts[0]  # /fix or /analyze
    file_path = parts[1]
    description = " ".join(parts[2:]) if len(parts) > 2 else "Please analyze and fix any issues"

    # Auto-switch to coding mode for fix/analyze commands
    if core.mode != 'coding':
        core.switch_mode('coding', persist=False)

    core._safe_print(f"🔧 {'Fixing' if cmd_type == '/fix' else 'Analyzing'}: {file_path}")
    core._safe_print(f"📝 Description: {description}")

    # Initialize code analyzer if needed
    if not core.code_analyzer:
        core.code_analyzer = CodeAnalyzer(safety_manager=core.safety_manager)

    # Read the file
    success, message, content = core.code_analyzer.read_file_safe(file_path)
    if not success:
        core._safe_print(f"❌ Cannot read file: {message}")
        return None

    # Store original content for diff
    core.original_file_content = content

    # CODE-SPECIFIC INSTRUCTIONS - Only added for code actions
    code_instructions = """
    CRITICAL INSTRUCTIONS FOR PROPOSING CHANGES:

    1. **Only propose changes to ACTUAL CODE** that exists in the file
    2. **NEVER include "Truncated for large files"** or similar comments in Old Code
    3. **Old Code must be EXACT code** from the file, with proper indentation
    4. **New Code should be the replacement** with improvements
    5. **Line numbers should be accurate** if provided

    When analyzing code, look for:
    - Missing error handling (try/except blocks)
    - Resource leaks (files, sessions not closed)
    - Security issues (hardcoded secrets, input validation)
    - Performance issues (inefficient loops, duplicate code)
    - Code quality (long functions, missing comments)

    ALWAYS use this exact format for proposing changes:

    PROPOSED CHANGE:
    File: [file_path]
    Description: [brief description]
    Old Code: [EXACT code from the file to replace]
    New Code: [improved replacement code]
    Line: [line number if known]

    Example of CORRECT format:
    PROPOSED CHANGE:
    File: agent/core.py
    Description: Add error handling for file reading
    Old Code: with open(file_path, 'r') as f:
                content = f.read()
    New Code: try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            except FileNotFoundError:
                return "File not found"
            except PermissionError:
                return "Permission denied"
    Line: 123

    Do NOT include comments about truncation or sample code!
    """

    # Create analysis prompt with code-specific instructions
    analysis_prompt = f"""I want to {cmd_type[1:]} this file:

File: {file_path}

{description}

Here's the current code (first 4000 characters):
```python
{content[:4000]}
```

{code_instructions}

Please analyze the code and provide specific fixes. If you find issues, propose changes in the PROPOSED CHANGE format."""

    # Add to history and trigger analysis
    core.add_to_history("user", analysis_prompt)

    # Set auto-fix mode
    core.auto_fix_mode = (cmd_type == '/fix')
    core.current_fix_file = file_path

    core._safe_print(f"🤖 AI is analyzing the file. It will propose changes automatically...")

    # Return None to let the normal streaming handle the response
    return None
    
def _parse_ai_changes_for_file(core, ai_response: str, file_path: str) -> int:
    """Parse AI response for proposed changes and add to pending changes"""
    import re

    # Pattern to find PROPOSED CHANGE blocks
    pattern = r'PROPOSED CHANGE:\s*File:\s*(.+?)\s*Description:\s*(.+?)\s*Old Code:\s*(?:```(?:\w+)?)?\s*(.+?)\s*(?:```)?\s*New Code:\s*(?:```(?:\w+)?)?\s*(.+?)\s*(?:```)?\s*(?:Line:\s*(\d+))?'
        
    changes = re.findall(pattern, ai_response, re.DOTALL | re.IGNORECASE)

    change_count = 0
    for match in changes:
        match_file = match[0].strip()
        description = match[1].strip()
        old_code = match[2].strip()
        new_code = match[3].strip()
        line = int(match[4].strip()) if match[4] and match[4].strip().isdigit() else None

        # Clean code blocks
        old_code = re.sub(r'^```\w*\s*|\s*```$', '', old_code).strip()
        new_code = re.sub(r'^```\w*\s*|\s*```$', '', new_code).strip()

        core._safe_print(f"\n🔍 Validating change: {description}")
            
        # Skip if old_code is clearly invalid
        if "# truncated for large files" in old_code.lower() or "# sample code" in old_code.lower():
            core._safe_print(f"❌ Skipping invalid change (contains truncation comment)")
            continue

        # Try to validate, but be more lenient
        is_valid, error_msg = core.validate_proposed_change(old_code, new_code, file_path)

        if not is_valid:
            core._safe_print(f"⚠️  Change validation warning: {error_msg}")
            core._safe_print(f"💡 Still adding to pending changes for manual review")
            # Still add it, but mark as needs review
            description = f"[Needs Review] {description}"
            
        # Add to pending changes
        core.propose_code_change(file_path, old_code, new_code, description, line)
        change_count += 1
        core._safe_print(f"✅ Added change to pending changes")

    return change_count

def _auto_apply_changes_with_confirmation(core):
    """
    Automatically apply changes after user confirmation
    """
    if not core.code_changes_pending:
        core._safe_print("📭 No changes to apply.")
        return

    # Show what will be changed
    print("\n" + "="*60)
    core._safe_print("📋 PROPOSED CHANGES:")
    print("="*60)
        
    for change in core.code_changes_pending:
        core._safe_print(f"\n📄 File: {change['file_path']}")
        core._safe_print(f"📝 {change['description']}")
        if 'old_code' in change and 'new_code' in change:
            print(f"   - {change['old_code'][:80]}{'...' if len(change['old_code']) > 80 else ''}")
            print(f"   + {change['new_code'][:80]}{'...' if len(change['new_code']) > 80 else ''}")

    print("\n" + "="*60)
    print("❓ Apply these changes? (yes/no/cancel): ", end="", flush=True)
        
    # Get user response
    try:
        import sys
        if sys.stdin.isatty():
            response = input()
        else:
            # If running in non-interactive mode
            print("\n⚠️  Running in non-interactive mode. Changes will not be applied.")
            return
    except:
        print("\n⚠️  Could not get user input. Changes will not be applied.")
        return

    if response.lower() in ['yes', 'y', 'ok', 'apply']:
        print("\n🔄 Applying changes...")
        result = _code_apply_changes_confirm(core, force=True)
        print(f"\n{result}")
    elif response.lower() in ['no', 'n']:
        print("\n❌ Changes not applied. You can view them with /code changes")
    else:
        print("\n⏸️  Changes kept pending. Use /code changes to review or /code apply to apply.")

def get_user_confirmation(core, question: str, default: str = "no") -> bool:
    """
    Get yes/no confirmation from user
    """
    import sys

    if not sys.stdin.isatty():
        print(f"⚠️  Non-interactive mode. Assuming '{default}'")
        return default.lower() in ['yes', 'y']

    valid_responses = {'yes': True, 'y': True, 'no': False, 'n': False}

    while True:
        print(f"\n{question} (yes/no): ", end="", flush=True)
        try:
            response = input().strip().lower()
            if response in valid_responses:
                return valid_responses[response]
            elif response == '':
                return default.lower() in ['yes', 'y']
            else:
                print("Please answer 'yes' or 'no'")
        except (EOFError, KeyboardInterrupt):
            print("\n\nInterrupted. Assuming 'no'")
            return False

def _check_file_threshold(core, total_files: int, operation_description: str = "process files") -> Tuple[bool, Optional[int]]:
    """
    Check if total files exceeds thresholds and ask user for confirmation.

    Args:
        total_files: Total number of files detected
        operation_description: Description of the operation for the prompt

    Returns:
        Tuple[bool, Optional[int]]: (should_continue, limit)
            - should_continue: True if user wants to continue, False otherwise
            - limit: Suggested limit for file operations (None for no limit)
    """
    # Thresholds for confirmation
    thresholds = [100, 200, 300]
    exceeded_threshold = None

    for threshold in sorted(thresholds, reverse=True):
        if total_files >= threshold:
            exceeded_threshold = threshold
            break

    limit = 200  # Default limit for performance

    if exceeded_threshold is not None:
        core._safe_print(f"📊 Found {total_files} total files in codebase (exceeds threshold: {exceeded_threshold})")
        if core.get_user_confirmation(f"Continue to {operation_description} for all {total_files} files?", "no"):
            limit = None  # No limit, process all files
            core._safe_print(f"✅ Processing all {total_files} files...")
            return True, limit
        else:
            limit = 100  # Reduced limit for safety
            core._safe_print(f"⚠️  Using reduced limit of {limit} files for safety.")
            return False, limit  # User declined full operation

    # If no threshold exceeded, continue with default limit
    return True, limit

def show_diff(core, old_content: str, new_content: str, filename: str = "file"):
    """
    Show colored diff between old and new content
    """
    try:
        import difflib

        print(f"\n📊 DIFF: {filename}")
        print("="*60)
            
        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)

        # Generate unified diff
        diff = difflib.unified_diff(
            old_lines, new_lines,
            fromfile=f'Original: {filename}',
            tofile=f'Modified: {filename}',
            lineterm='',
            n=3  # Context lines
        )
            
        # Print with colors
        for line in diff:
            if line.startswith('---') or line.startswith('+++'):
                print(f"\033[90m{line}\033[0m")  # Gray for headers
            elif line.startswith('-'):
                print(f"\033[91m{line}\033[0m")  # Red for deletions
            elif line.startswith('+'):
                print(f"\033[92m{line}\033[0m")  # Green for additions
            else:
                print(f"\033[90m{line}\033[0m")  # Gray for context

        # Also show summary
        print(f"\n📈 Summary:")
        print(f"  Original: {len(old_lines)} lines")
        print(f"  Modified: {len(new_lines)} lines")
        print(f"  Changes: {abs(len(new_lines) - len(old_lines))} lines added/removed")
        print("="*60)
            
    except Exception as e:
        print(f"⚠️ Could not generate diff: {e}")
        print(f"📄 Showing simple comparison instead:")
        print("="*60)
        print(f"Original (first 200 chars):\n{old_content[:200]}")
        print(f"\nModified (first 200 chars):\n{new_content[:200]}")
        print("="*60)

def validate_proposed_change(core, old_code: str, new_code: str, file_path: str) -> Tuple[bool, str]:
    """
    Validate that a proposed change is valid

    Returns: (is_valid, error_message)
    """
    # Check if old_code is empty or just a comment
    if not old_code or old_code.strip() == "":
        return False, "Old Code cannot be empty"

    # Check if old_code contains truncation comments
    truncation_phrases = [
        "truncated for large files",
        "truncated for context",
        "first 4000 characters",
        "first 3000 characters",
        "sample code",
        "example code",
        "..."
    ]

    old_code_lower = old_code.lower()
    for phrase in truncation_phrases:
        if phrase in old_code_lower:
            return False, f"Old Code contains truncation comment: '{phrase}'"

    # Check if old_code looks like actual code (not just a comment)
    lines = old_code.split('\n')
    code_lines = [line for line in lines if line.strip() and not line.strip().startswith('#')]
        
    if len(code_lines) == 0:
        # Only comments, not actual code
        return False, "Old Code contains no actual code (only comments)"
        
    # Read the actual file to check if old_code exists
    success, message, actual_content = core.code_analyzer.read_file_safe(file_path)
    if not success:
        return False, f"Cannot read file to validate: {message}"
        
    # Check if old_code exists in the file (allow for minor whitespace differences)
    normalized_old = re.sub(r'\s+', ' ', old_code.strip())
    normalized_file = re.sub(r'\s+', ' ', actual_content)

    if normalized_old not in normalized_file:
        # Try to find similar code
        similar = core.find_similar_code(old_code, actual_content)
        if similar:
            return False, f"Old Code not found. Did you mean:\n{similar[:200]}"
        else:
            return False, "Old Code not found in the file"
        
    return True, "Valid"
    
def find_similar_code(core, old_code: str, file_content: str, context_lines: int = 3) -> str:
    """
    Find code similar to old_code in file_content
    Returns: Similar code snippet with context
    """
    import difflib

    # Clean the old_code
    old_code_clean = old_code.strip()

    # Split into lines
    file_lines = file_content.splitlines()

    # If old_code is very short, just return empty
    if len(old_code_clean) < 10:
        return ""
        
    # Try to find exact or similar matches
    best_match = None
    best_ratio = 0

    # Check if any line contains the old_code
    for i, line in enumerate(file_lines):
        if old_code_clean in line:
            # Found exact substring
            start = max(0, i - context_lines)
            end = min(len(file_lines), i + context_lines + 1)
            return "\n".join(file_lines[start:end])

    # Try to find similar code using difflib
    # Break the file into chunks and compare
    chunk_size = min(10, len(file_lines))
        
    for i in range(0, len(file_lines) - chunk_size + 1, chunk_size // 2):
        chunk = "\n".join(file_lines[i:i+chunk_size])
            
        # Calculate similarity ratio
        ratio = difflib.SequenceMatcher(None, old_code_clean, chunk).ratio()
            
        if ratio > best_ratio:
            best_ratio = ratio
            start = max(0, i - context_lines)
            end = min(len(file_lines), i + chunk_size + context_lines)
            best_match = "\n".join(file_lines[start:end])
        
    # If we found something reasonably similar (ratio > 0.3)
    if best_match and best_ratio > 0.3:
        return best_match
    else:
        # Return a snippet around the middle of the file
        middle = len(file_lines) // 2
        start = max(0, middle - context_lines * 2)
        end = min(len(file_lines), middle + context_lines * 2)
        return "\n".join(file_lines[start:end])