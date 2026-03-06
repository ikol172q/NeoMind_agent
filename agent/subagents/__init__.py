"""
Subagent system for user_agent.

Subagents are specialized agents that handle specific types of tasks
delegated by the main agent via the Task tool.
"""

from .base import Subagent, AsyncSubagent, SubagentMetadata, SubagentError, SubagentTimeoutError, SubagentValidationError
from .explore_agent import ExploreAgent
from .plan_agent import PlanAgent
from .bash_agent import BashAgent

__all__ = [
    "Subagent",
    "AsyncSubagent",
    "SubagentMetadata",
    "SubagentError",
    "SubagentTimeoutError",
    "SubagentValidationError",
    "ExploreAgent",
    "PlanAgent",
    "BashAgent",
]