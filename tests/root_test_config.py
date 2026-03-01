#!/usr/bin/env python3
"""Test agent_config functionality"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import agent_config

print("Testing agent_config...")

# Get current values
agent_model = agent_config.agent_config.model
thinking_enabled = agent_config.agent_config.thinking_enabled

print(f"Current agent model: {agent_model}")
print(f"Current thinking enabled: {thinking_enabled}")

# Test update_value for agent model
print("\nTesting update_value for agent.model...")
success = agent_config.agent_config.update_value("agent.model", "deepseek-chat")  # Same value
print(f"Update success: {success}")

# Test update_value for thinking_enabled
print("\nTesting update_value for agent.thinking_enabled...")
success = agent_config.agent_config.update_value("agent.thinking_enabled", False)  # Same value
print(f"Update success: {success}")

print("\nTest completed.")