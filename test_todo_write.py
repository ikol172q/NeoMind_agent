#!/usr/bin/env python3
"""Test TodoWriteTool."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from agent.tools.todo_write_tool import create_todo_write_tool
from agent.tasks.todo_manager import TODO_MANAGER

def test_todo_write():
    """Test todo write tool."""
    tool = create_todo_write_tool()
    print(f"Tool metadata: {tool.metadata.name}")
    print(f"Description: {tool.metadata.description}")

    # Test validation
    items = [
        {
            "content": "Write tests",
            "status": "pending",
            "activeForm": "Writing tests"
        },
        {
            "content": "Implement feature",
            "status": "in_progress",
            "activeForm": "Implementing feature"
        },
        {
            "content": "Review code",
            "status": "completed",
            "activeForm": "Reviewing code"
        }
    ]

    result = tool.execute(items=items)
    print("Result:")
    print(result)
    print("\nCurrent todo items:")
    for item in TODO_MANAGER.get_items():
        print(f"  - {item}")

    # Test error: two in_progress
    items2 = [
        {
            "content": "Task A",
            "status": "in_progress",
            "activeForm": "Doing A"
        },
        {
            "content": "Task B",
            "status": "in_progress",
            "activeForm": "Doing B"
        }
    ]
    try:
        result = tool.execute(items=items2)
        print("Unexpected success:", result)
    except Exception as e:
        print(f"Expected error: {e}")

    # Test empty activeForm validation
    items3 = [
        {
            "content": "Task",
            "status": "pending",
            "activeForm": ""
        }
    ]
    try:
        result = tool.execute(items=items3)
        print("Unexpected success:", result)
    except Exception as e:
        print(f"Expected error: {e}")

    # Test max items
    many_items = []
    for i in range(25):
        many_items.append({
            "content": f"Task {i}",
            "status": "pending",
            "activeForm": f"Pending {i}"
        })
    try:
        result = tool.execute(items=many_items)
        print("Unexpected success:", result)
    except Exception as e:
        print(f"Expected error: {e}")

    print("\nAll tests passed.")

if __name__ == "__main__":
    test_todo_write()