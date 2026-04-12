"""
Plan Mode Tools for NeoMind Agent.

EnterPlanMode/ExitPlanMode control read-only mode where
write/execute tools are disabled for safe planning.

Created: 2026-04-02 (Phase 2 - Coding 完整功能)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Any


@dataclass
class PlanModeResult:
    """Result from a plan mode operation."""
    success: bool
    active: bool
    message: str


class PlanModeManager:
    """
    Manages plan mode state.

    When plan mode is active, write and execute tools are disabled
    so the agent can safely explore, read, and plan without making
    any changes. This is useful for complex tasks where the agent
    should first understand the codebase before modifying it.

    Features:
    - Toggle plan mode on/off
    - Integrates with tool registry to disable/enable write tools
    - Query current mode state
    """

    def __init__(self, tool_registry: Optional[Any] = None):
        """
        Initialize PlanModeManager.

        Args:
            tool_registry: Optional tool registry that supports
                enter_plan_mode() and exit_plan_mode() methods.
        """
        self._active: bool = False
        self._registry = tool_registry

    def enter(self) -> PlanModeResult:
        """
        Enter plan mode — disables write/execute tools.

        Returns:
            PlanModeResult indicating the new state.
        """
        if self._active:
            return PlanModeResult(
                success=True,
                active=True,
                message="Already in plan mode.",
            )

        self._active = True

        if self._registry and hasattr(self._registry, "enter_plan_mode"):
            self._registry.enter_plan_mode()

        return PlanModeResult(
            success=True,
            active=True,
            message="Plan mode activated. Write/execute tools disabled. "
                    "Use ExitPlanMode when ready to implement.",
        )

    def exit(self) -> PlanModeResult:
        """
        Exit plan mode — re-enables all tools.

        Returns:
            PlanModeResult indicating the new state.
        """
        if not self._active:
            return PlanModeResult(
                success=True,
                active=False,
                message="Not in plan mode.",
            )

        self._active = False

        if self._registry and hasattr(self._registry, "exit_plan_mode"):
            self._registry.exit_plan_mode()

        return PlanModeResult(
            success=True,
            active=False,
            message="Plan mode deactivated. All tools re-enabled.",
        )

    @property
    def is_active(self) -> bool:
        """Whether plan mode is currently active."""
        return self._active


__all__ = [
    'PlanModeManager',
    'PlanModeResult',
]


if __name__ == "__main__":
    print("=== PlanModeManager Test ===\n")

    mgr = PlanModeManager()

    # Initially inactive
    assert not mgr.is_active
    print(f"Initial state: active={mgr.is_active}")

    # Enter plan mode
    r1 = mgr.enter()
    assert r1.success and r1.active
    assert mgr.is_active
    print(f"Enter: {r1.message}")

    # Enter again (idempotent)
    r2 = mgr.enter()
    assert r2.success and r2.active
    print(f"Enter again: {r2.message}")

    # Exit plan mode
    r3 = mgr.exit()
    assert r3.success and not r3.active
    assert not mgr.is_active
    print(f"Exit: {r3.message}")

    # Exit again (idempotent)
    r4 = mgr.exit()
    assert r4.success and not r4.active
    print(f"Exit again: {r4.message}")

    # Test with mock registry
    class MockRegistry:
        def __init__(self):
            self.plan_mode = False

        def enter_plan_mode(self):
            self.plan_mode = True

        def exit_plan_mode(self):
            self.plan_mode = False

    registry = MockRegistry()
    mgr2 = PlanModeManager(tool_registry=registry)

    mgr2.enter()
    assert registry.plan_mode is True
    print(f"\nWith registry - enter: registry.plan_mode={registry.plan_mode}")

    mgr2.exit()
    assert registry.plan_mode is False
    print(f"With registry - exit: registry.plan_mode={registry.plan_mode}")

    print("\nPlanModeManager test passed!")
