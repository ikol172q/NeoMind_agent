"""Built-in agent types for NeoMind — mirrors Claude Code's 6 built-in agent types.

Each type defines:
- Purpose and description
- Tool allowlist (subset of full tool pool)
- Recommended model
- Permission mode
- Specialized system prompt additions

Usage:
    from agent.agentic.builtin_agents import EXPLORE_AGENT, PLAN_AGENT, VERIFY_AGENT
    agent_type = EXPLORE_AGENT
    tools = agent_type.filter_tools(all_tools)
    prompt = agent_type.system_prompt_addition

Created: 2026-04-25 (Phase 3 — Agent System)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Set


@dataclass
class BuiltinAgentType:
    """Defines a built-in agent type with tool restrictions and model preference.

    Each type specifies exactly which tools the agent can use and what
    model it should run on. This prevents sub-agents from having access
    to tools they shouldn't use (e.g., a search agent shouldn't write files).
    """

    agent_type: str           # e.g. "Explore", "Plan", "Verify"
    description: str          # One-line purpose
    system_prompt_addition: str  # Specialized instructions injected into system prompt
    tool_allowlist: Set[str]  # Only these tools are visible to the agent
    recommended_model: str    # Preferred model for this agent type
    permission_mode: str = "auto_accept"  # Sub-agents typically auto-accept
    max_turns: int = 25       # Max turns before auto-stop
    is_background: bool = True  # Run in background, notify on completion

    def filter_tools(self, all_tool_definitions: list) -> list:
        """Filter a full tool list down to this agent type's allowlist.

        Args:
            all_tool_definitions: List of ToolDefinition objects from the registry.

        Returns:
            Filtered list containing only allowed tools, in original order.
        """
        return [t for t in all_tool_definitions if t.name in self.tool_allowlist]

    @property
    def name(self) -> str:
        return self.agent_type.lower()


# ── Built-in agent type definitions ───────────────────────────────────

EXPLORE_AGENT = BuiltinAgentType(
    agent_type="Explore",
    description="Fast agent for codebase exploration — search, read, and report. "
                "Use for broad searches, finding files by pattern, understanding "
                "code structure, or answering 'where is X' questions.",
    tool_allowlist={
        "Read", "Grep", "Glob", "LS", "Bash",
        "WebFetch", "WebSearch",
        "TaskCreate", "TaskUpdate",   # For tracking exploration progress
    },
    recommended_model="deepseek-v4-flash",  # Faster, cheaper for search-heavy work
    system_prompt_addition=(
        "You are an Explore agent. Your job is to search the codebase, "
        "read files, and report findings. You cannot write or edit code. "
        "Be thorough: when you find something, verify it by reading the file. "
        "Report your findings as a structured summary with file paths and line numbers. "
        "If searching for something broad, break it into specific sub-searches."
    ),
    max_turns=15,
)

PLAN_AGENT = BuiltinAgentType(
    agent_type="Plan",
    description="Software architect agent for designing implementation plans. "
                "Reads code, analyzes architecture, considers trade-offs, "
                "and produces step-by-step plans with file paths and changes.",
    tool_allowlist={
        "Read", "Grep", "Glob", "LS", "Bash",
        "TaskCreate", "TaskUpdate", "TaskGet", "TaskList",
        "AskUser",
        "GitStatus", "GitDiff", "GitLog",
    },
    recommended_model="deepseek-v4-pro",  # Smarter model for architecture decisions
    system_prompt_addition=(
        "You are a Plan agent. Your job is to analyze code, consider "
        "architectural trade-offs, and produce a concrete, step-by-step "
        "implementation plan. You cannot write or edit code — only plan. "
        "Your plan must include: specific files to change, what to change "
        "in each, the order of changes, and how to verify each step. "
        "Consider edge cases, existing patterns in the codebase, and "
        "backwards compatibility. Flag risks explicitly."
    ),
    max_turns=20,
)

VERIFY_AGENT = BuiltinAgentType(
    agent_type="Verify",
    description="Adversarial verification agent — independently checks that "
                "implemented changes are correct, complete, and safe. "
                "Runs tests, checks diffs, and assigns PASS/FAIL/PARTIAL verdict.",
    tool_allowlist={
        "Read", "Grep", "Glob", "LS", "Bash",
        "GitStatus", "GitDiff", "GitLog",
        "TaskCreate", "TaskUpdate",
    },
    recommended_model="deepseek-v4-pro",  # Smarter model for correctness verification
    system_prompt_addition=(
        "You are a Verify agent. Your job is to independently verify that "
        "changes are correct, complete, and safe. You are adversarial: "
        "assume nothing, check everything. Run the tests, inspect the diffs, "
        "verify that every claimed change actually happened. "
        "Your verdict must be one of:\n"
        "- PASS: all changes correct, tests pass, no regressions\n"
        "- FAIL: found bugs, missing changes, or broken tests (list specifics)\n"
        "- PARTIAL: some things verified, some couldn't be (explain why)\n"
        "For every verdict item, include the exact command you ran and its output. "
        "Never claim PASS without running the relevant test or command."
    ),
    max_turns=20,
)


# ── Registry ──────────────────────────────────────────────────────────

BUILTIN_AGENTS: dict = {
    "explore": EXPLORE_AGENT,
    "plan": PLAN_AGENT,
    "verify": VERIFY_AGENT,
}


def get_builtin_agent(agent_type: str) -> Optional[BuiltinAgentType]:
    """Look up a built-in agent type by name (case-insensitive)."""
    return BUILTIN_AGENTS.get(agent_type.lower())


def list_builtin_agents() -> List[str]:
    """Return list of available built-in agent types."""
    return list(BUILTIN_AGENTS.keys())
