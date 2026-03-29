"""File command handlers — diff, browse, undo, test.

Extracted from core.py (Tier 2F). Each function takes the core agent reference
and command string, returning formatted output.

Created: 2026-03-28 (Tier 2F)
"""

from __future__ import annotations

import difflib
import os
import sys
import time
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    pass


def handle_diff_command(core, command: str) -> str:
    """Handle /diff command — compare files or show git diffs."""
    if not command or command.strip() == "":
        help_text = """
📝 /diff Command Usage:
  /diff <file1> <file2>        - Compare two files
  /diff --git <file>           - Show git diff for file
  /diff --backup <file>        - Compare with latest backup
  /diff --help                 - Show this help

Examples:
  /diff old.py new.py
  /diff --git agent/core.py
        """.strip()
        return help_text

    parts = command.split()
    if parts[0] == '--git':
        # Git diff implementation
        if len(parts) < 2:
            return core.formatter.error("Please specify a file for git diff")
        file_path = parts[1]
        try:
            import subprocess
            result = subprocess.run(
                ['git', 'diff', file_path],
                capture_output=True,
                text=True,
                cwd=os.getcwd()
            )
            if result.stdout:
                return f"🔀 Git diff for {file_path}:\n\n{result.stdout}"
            else:
                return f"📭 No changes for {file_path} in git"
        except Exception as e:
            return core.formatter.error(f"Error running git diff: {str(e)}")
    elif parts[0] == '--backup':
        # Compare with backup
        if len(parts) < 2:
            return core.formatter.error("Please specify a file for backup comparison")
        file_path = parts[1]
        # Find latest backup
        backup_dir = os.path.join(core.safety_manager.workspace_root, '.safety_backups')
        if not os.path.exists(backup_dir):
            return f"📭 No backup directory found at {backup_dir}"
        base_name = os.path.basename(file_path)
        import glob
        import re as _re
        pattern = os.path.join(backup_dir, f"{base_name}.backup_*")
        backups = glob.glob(pattern)
        if not backups:
            return f"📭 No backups found for {file_path}"

        # Extract timestamp from filename: {base}.backup_{timestamp}
        def extract_timestamp(path):
            match = _re.search(r'\.backup_(\d+)$', os.path.basename(path))
            return int(match.group(1)) if match else 0

        latest_backup = max(backups, key=extract_timestamp)
        # Read backup content
        safe, reason, backup_content = core.safety_manager.safe_read_file(latest_backup)
        if not safe:
            return f"❌ Cannot read backup file {latest_backup}: {reason}"
        # Read current file
        from agent.code_analyzer import CodeAnalyzer
        if not core.code_analyzer:
            core.code_analyzer = CodeAnalyzer(os.getcwd(), safety_manager=core.safety_manager)
        success, msg, current_content = core.code_analyzer.read_file_safe(file_path)
        if not success:
            return core.formatter.error(f"Cannot read {file_path}: {msg}")
        # Generate diff
        lines1 = backup_content.splitlines(keepends=True)
        lines2 = current_content.splitlines(keepends=True)
        diff = difflib.unified_diff(
            lines1, lines2,
            fromfile=f"backup: {os.path.basename(latest_backup)}",
            tofile=f"current: {file_path}",
            lineterm=''
        )
        diff_result = ''.join(diff)
        if diff_result:
            return f"🔀 Diff between backup and current {file_path}:\n\n{diff_result}"
        else:
            return core.formatter.success(f"File {file_path} is identical to latest backup")
    else:
        # Compare two files
        if len(parts) < 2:
            return core.formatter.error("Please specify two files to compare")
        file1, file2 = parts[0], parts[1]
        try:
            # Read both files
            from agent.code_analyzer import CodeAnalyzer
            if not core.code_analyzer:
                core.code_analyzer = CodeAnalyzer(os.getcwd(), safety_manager=core.safety_manager)
            success1, msg1, content1 = core.code_analyzer.read_file_safe(file1)
            success2, msg2, content2 = core.code_analyzer.read_file_safe(file2)
            if not success1:
                return core.formatter.error(f"Cannot read {file1}: {msg1}")
            if not success2:
                return core.formatter.error(f"Cannot read {file2}: {msg2}")

            # Generate diff
            lines1 = content1.splitlines(keepends=True)
            lines2 = content2.splitlines(keepends=True)
            diff = difflib.unified_diff(
                lines1, lines2,
                fromfile=file1,
                tofile=file2,
                lineterm=''
            )
            diff_result = ''.join(diff)
            if diff_result:
                return f"🔀 Diff between {file1} and {file2}:\n\n{diff_result}"
            else:
                return core.formatter.success(f"Files {file1} and {file2} are identical")
        except Exception as e:
            return core.formatter.error(f"Error comparing files: {str(e)}")


def handle_browse_command(core, command: str) -> str:
    """Handle /browse command — browse directory contents."""
    if not command or command.strip() == "":
        path = os.getcwd()
    else:
        path = command.strip()

    # Parse flags
    details = False
    filter_ext = None
    parts = path.split()
    actual_path = os.getcwd()

    i = 0
    while i < len(parts):
        if parts[i] == '--details':
            details = True
            parts.pop(i)
        elif parts[i] == '--filter':
            if i + 1 < len(parts):
                filter_ext = parts[i + 1]
                parts.pop(i)  # Remove --filter
                parts.pop(i)  # Remove the extension
            else:
                return core.formatter.error("Missing extension after --filter")
        elif parts[i] == '--help':
            help_text = """
📁 /browse Command Usage:
  /browse [path]              - Browse directory (default: current)
  /browse --details [path]    - Show detailed listing with sizes
  /browse --filter <ext>      - Filter by extension (e.g., .py)
  /browse --help              - Show this help

Examples:
  /browse                     # Browse current directory
  /browse agent/              # Browse agent directory
  /browse --details src/      # Detailed listing of src/
  /browse --filter .py        # Show only Python files
            """.strip()
            return help_text
        else:
            # This is the path
            if i == len(parts) - 1:  # Last part
                actual_path = parts[i]
                if not os.path.isabs(actual_path):
                    actual_path = os.path.join(os.getcwd(), actual_path)
            i += 1

    # If no path specified and we consumed all parts with flags
    if actual_path is None:
        actual_path = os.getcwd()

    try:
        if not os.path.exists(actual_path):
            return core.formatter.error(f"Path does not exist: {actual_path}")
        if not os.path.isdir(actual_path):
            return core.formatter.error(f"Not a directory: {actual_path}")

        # List directory
        items = os.listdir(actual_path)

        # Separate directories and files
        dirs = []
        files = []
        for item in items:
            item_path = os.path.join(actual_path, item)
            if os.path.isdir(item_path):
                dirs.append(item)
            else:
                if filter_ext and not item.endswith(filter_ext):
                    continue
                files.append(item)

        # Sort
        dirs.sort()
        files.sort()

        # Build result
        result = f"📁 Directory: {actual_path}\n"
        result += f"📊 Items: {len(dirs)} directories, {len(files)} files"
        if filter_ext:
            result += f" (filtered: *{filter_ext})"
        result += "\n\n"

        # Show directories
        if dirs:
            result += "📂 Directories:\n"
            for d in dirs[:20]:  # Limit to 20
                result += f"  • {d}/\n"
            if len(dirs) > 20:
                result += f"  ... and {len(dirs) - 20} more directories\n"
            result += "\n"

        # Show files
        if files:
            result += "📄 Files:\n"
            for f in files[:30]:  # Limit to 30
                if details:
                    try:
                        size = os.path.getsize(os.path.join(actual_path, f))
                        size_str = f"{size:,} bytes"
                        if size > 1024:
                            size_str = f"{size/1024:.1f} KB"
                        result += f"  • {f} ({size_str})\n"
                    except Exception:
                        result += f"  • {f}\n"
                else:
                    result += f"  • {f}\n"
            if len(files) > 30:
                result += f"  ... and {len(files) - 30} more files\n"

        result += f"\n💡 Use '/browse --details {actual_path}' for detailed listing"
        result += f"\n💡 Use '/read {actual_path}/<file>' to read a file"

        return result
    except Exception as e:
        return core.formatter.error(f"Error browsing directory: {str(e)}")


def handle_undo_command(core, command: str) -> str:
    """Handle /undo command — revert file changes."""
    if not command or command.strip() == "":
        command = "list 5"

    parts = command.split()
    action = parts[0].lower()

    if action == '--help':
        help_text = """
↩️ /undo Command Usage:
  /undo list [n]              - List recent changes (default: 5)
  /undo last                  - Revert last change
  /undo <change_id>           - Revert specific change by index
  /undo --help                - Show this help

Examples:
  /undo list                 # List 5 most recent changes
  /undo list 10              # List 10 most recent changes
  /undo last                 # Revert last change
  /undo 2                    # Revert change with ID 2
        """.strip()
        return help_text

    if action == 'list':
        limit = 5
        if len(parts) > 1:
            try:
                limit = int(parts[1])
            except ValueError:
                return core.formatter.error(f"Invalid limit: {parts[1]}")

        si = core._get_self_iteration()
        changes = si.get_change_history(limit=limit)
        if not changes:
            return "📭 No change history found."

        result = f"📜 Recent Changes (last {len(changes)}):\n\n"
        for i, change in enumerate(changes):
            timestamp = change.get('timestamp', 0)
            dt = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(timestamp))
            file_path = change.get('file_path', 'unknown')
            desc = change.get('description', 'No description')
            backup = change.get('backup', 'No backup')
            result += f"{i+1}. [{dt}] {file_path}\n"
            result += f"   Description: {desc}\n"
            if backup and os.path.exists(backup):
                result += f"   Backup: {backup} ✓\n"
            result += "\n"
        result += "💡 Use '/undo <number>' to revert a specific change"
        return result

    elif action == 'last':
        # Revert last change
        si = core._get_self_iteration()
        changes = si.get_change_history(limit=1)
        if not changes:
            return "📭 No changes to undo."
        change = changes[0]
        return core._revert_change(change)

    else:
        # Try to parse as number
        try:
            change_id = int(action)
            si = core._get_self_iteration()
            changes = si.get_change_history(limit=change_id + 10)  # Get enough
            if change_id < 1 or change_id > len(changes):
                return core.formatter.error(f"Invalid change ID. Use '/undo list' to see available IDs.")
            change = changes[change_id - 1]  # 1-indexed
            return core._revert_change(change)
        except ValueError:
            return core.formatter.error(f"Invalid command: {command}. Use '/undo --help' for usage.")


def _revert_change(core, change: dict) -> str:
    """Revert a change by restoring from backup."""
    try:
        file_path = change.get('file_path')
        backup_path = change.get('backup')
        description = change.get('description', 'Unknown change')

        if not file_path:
            return core.formatter.error("Cannot revert: missing file path in change record")
        if not backup_path:
            return core.formatter.error("Cannot revert: no backup path in change record")
        if not os.path.exists(backup_path):
            return core.formatter.error(f"Cannot revert: backup file not found: {backup_path}")

        # Read backup content
        success, message, backup_content = core.safety_manager.safe_read_file(backup_path)
        if not success:
            return core.formatter.error(f"Cannot read backup: {message}")

        # Write back to original file
        success, message, _ = core.safety_manager.safe_write_file(file_path, backup_content, create_backup=False)
        if not success:
            return core.formatter.error(f"Cannot write original file: {message}")

        # Log the revert
        si = core._get_self_iteration()
        si.log_change({
            'timestamp': time.time(),
            'file_path': file_path,
            'description': f'Reverted: {description}',
            'backup': backup_path,
            'status': 'reverted',
            'original_change': change.get('timestamp')
        })

        return f"{core.formatter.success(f'Reverted change: {description}')}\n📄 File restored from: {backup_path}"
    except Exception as e:
        return core.formatter.error(f"Error reverting change: {str(e)}")


def handle_test_command(core, command: str) -> str:
    """Handle /test command — run development and unit tests."""
    import subprocess

    if not command or command.strip() == "":
        command = "basic"

    cmd = command.strip().lower()
    if cmd == '--help':
        help_text = """
🧪 /test Command Usage:
  /test                       - Run basic development tests (dev_test.py)
  /test unit                  - Run unit tests (if available)
  /test all                   - Run all available tests
  /test --help                - Show this help

Examples:
  /test              # Run basic tests
  /test unit         # Run unit tests
        """.strip()
        return help_text

    try:
        if cmd == 'basic' or cmd == 'dev' or cmd == '':
            # Run dev_test.py
            test_path = os.path.join(core.agent_root, "..", "dev_test.py")
            test_path = os.path.abspath(test_path)
            if not os.path.exists(test_path):
                return core.formatter.error(f"Test file not found: {test_path}")

            result = subprocess.run(
                [sys.executable, test_path],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=os.path.dirname(test_path)
            )

            output = result.stdout
            if result.stderr:
                output += f"\n\nSTDERR:\n{result.stderr}"

            if result.returncode == 0:
                return core.formatter.success(f"Tests passed:\n\n{output}")
            else:
                return core.formatter.error(f"Tests failed (exit code: {result.returncode}):\n\n{output}")

        elif cmd == 'unit':
            # Try to run pytest
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "pytest", "tests/", "-v"],
                    capture_output=True,
                    text=True,
                    timeout=120,
                    cwd=os.getcwd()
                )
                output = result.stdout
                if result.stderr:
                    output += f"\n\nSTDERR:\n{result.stderr}"

                if result.returncode == 0:
                    return core.formatter.success(f"Unit tests passed:\n\n{output}")
                else:
                    return core.formatter.error(f"Unit tests failed (exit code: {result.returncode}):\n\n{output}")
            except FileNotFoundError:
                return core.formatter.error("pytest not found. Install with: pip install pytest")
            except Exception as e:
                return core.formatter.error(f"Error running unit tests: {str(e)}")

        elif cmd == 'all':
            # Run both
            basic_result = handle_test_command(core, 'basic')
            unit_result = handle_test_command(core, 'unit')
            return f"🧪 ALL TESTS\n\n{'='*60}\nBASIC TESTS:\n{basic_result}\n\n{'='*60}\nUNIT TESTS:\n{unit_result}"
        else:
            return core.formatter.error(f"Unknown test command: {command}. Use '/test --help' for usage.")
    except subprocess.TimeoutExpired:
        return core.formatter.error("Test execution timed out")
    except Exception as e:
        return core.formatter.error(f"Error running tests: {str(e)}")
