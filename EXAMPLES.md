# user-agent Examples

This document provides practical examples and tutorials for using user-agent, focusing on its code analysis and self-iteration capabilities.

## Table of Contents

1. [Basic Usage](#basic-usage)
2. [Code Analysis Commands](#code-analysis-commands)
3. [Self-Iteration Tutorial](#self-iteration-tutorial)
4. [Safety Features](#safety-features)
5. [Advanced Scenarios](#advanced-scenarios)

## Basic Usage

### Starting the Agent

```bash
# Interactive chat mode
user-agent

# Or as a module
python -m user_agent
```

### Essential Commands

```bash
# Search the web for information
/search Python asyncio tutorial

# Switch to a different model
/models switch deepseek-reasoner

# Toggle thinking mode (shows reasoning process)
/think

# Read a webpage or local file
/read https://example.com
/read agent/core.py:10-50
/read --no-ai config.yaml  # Read without adding to AI memory

# Write a new file
/write hello.py "print('Hello, World!')"
/write --interactive script.py  # Enter multiline content

# Edit existing code
/edit hello.py "print('Hello, World!')" "print('Hello, AI!')"

# Run shell commands safely
/run ls -la
/run python --version

# Git operations
/git status
/git log --oneline -5
```

## Code Analysis Commands

### Scanning a Codebase

```bash
# Scan current directory
/code scan .

# Scan specific path
/code scan ~/projects/myapp

# Get summary of scanned codebase
/code summary
```

### Finding and Reading Files

```bash
# Find Python files
/code find *.py

# Find files containing 'test' in name
/code find *test*

# Read a specific file with syntax highlighting
/code read agent/core.py

# Analyze file structure (imports, functions, classes)
/code analyze agent/core.py
```

### Searching Code

```bash
# Search for text across all files
/code search "def handle_"

# Case-insensitive search
/code search -i "exception"
```

### Proposing and Applying Changes

```bash
# View pending changes
/code changes

# Apply changes (with confirmation)
/code apply

# Apply changes without confirmation
/code apply force

# Clear pending changes
/code clear
```

## Self-Iteration Tutorial

### Scanning the Agent's Own Codebase

```bash
# Scan the agent's own source code
/code self-scan
```

This command analyzes the agent's own directory structure and provides statistics about file types and sizes.

### Suggesting Improvements

```bash
# Suggest improvements to all Python files in the agent
/code self-improve

# Suggest improvements to a specific file
/code self-improve agent/core.py

# Suggest improvements to a directory
/code self-improve agent/
```

The agent will analyze its own code and propose improvements such as:
- Adding error handling
- Improving code readability
- Optimizing performance
- Fixing potential bugs

### Applying Self-Improvements Safely

```bash
# First, review proposed changes
/code changes

# Apply self-improvements with safety checks
/code self-apply
```

The self-apply process:
1. Runs pre-application tests to ensure the agent still works
2. Creates backups of all modified files
3. Applies changes one by one with validation
4. Runs post-application tests
5. Provides rollback capability if anything fails

### Deep Analysis with Reasoning Model

```bash
# Perform deep analysis using deepseek-reasoner
/code reason agent/core.py
```

This command temporarily switches to the reasoning model for complex chain-of-thought analysis of code structure and quality.

## Safety Features

### File Operation Safety

All file operations go through the safety manager which:
- Validates paths are within allowed workspace
- Blocks dangerous file extensions (.exe, .sh, .bat, etc.)
- Prevents access to system directories
- Enforces size limits (10MB maximum)
- Creates audit logs of all operations

### Command Execution Safety

The command executor:
- Blocks dangerous command patterns
- Limits execution time (30 second timeout)
- Restricts resource usage
- Validates git operations are safe
- Runs commands in a controlled environment

### Audit Logging

All safety-critical operations are logged to `.safety_audit.log` in JSON format:

```json
{
  "timestamp": "2024-01-15 10:30:45",
  "action": "write",
  "path": "/workspace/hello.py",
  "success": true,
  "details": "File written successfully",
  "user": "developer",
  "cwd": "/workspace"
}
```

### Recovery and Rollback

The self-iteration framework provides:
- Automatic backups before modifications
- Validation of syntax and imports
- Rollback to previous versions if validation fails
- Change journal tracking all modifications

## Advanced Scenarios

### Automated Code Refactoring

```bash
# Analyze a file and automatically fix issues
/fix agent/core.py "improve error handling"

# Analyze without auto-fix
/analyze agent/core.py
```

### Comparing Code Versions

```bash
# Compare two files
/diff old_version.py new_version.py

# Compare with git version
/diff --git agent/core.py

# Compare with backup
/diff --backup agent/core.py
```

### Browsing Directory Structure

```bash
# Browse current directory
/browse

# Browse with details
/browse --details

# Browse with filter for Python files
/browse --filter .py

# Browse specific path
/browse agent/
```

### Undoing Changes

```bash
# List recent changes with IDs
/undo list

# Undo the last change
/undo last

# Undo specific change by ID
/undo 2
```

### Running Tests

```bash
# Run development tests
/test

# Run unit tests only
/test unit

# Run all tests including integration
/test all
```

## Troubleshooting

### Common Issues

1. **Unicode encoding errors on Windows**: The agent automatically replaces emojis with ASCII equivalents when printing fails.

2. **API key not set**: Set `DEEPSEEK_API_KEY` environment variable or pass as argument.

3. **File permission errors**: Ensure the agent has write permissions in the workspace directory.

4. **Safety manager blocking operations**: Check `.safety_audit.log` for details on blocked operations.

### Getting Help

```bash
# List all available commands
/help

# Get detailed help for a specific command
/help write
/help code
/help self-improve
```

## Contributing

For contributing to the agent's development, see the [README.md](README.md) for setup instructions. The agent can even improve its own code using the self-iteration features described above.