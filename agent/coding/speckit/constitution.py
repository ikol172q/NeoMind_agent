"""
ConstitutionManager — project constitution lifecycle and validation.

Wraps SpecManager to provide:
- Constitution scaffolding
- System-prompt-ready constitution sections
- Spec-against-constitution validation
"""

from __future__ import annotations

from typing import List, Optional
from pathlib import Path

from agent.coding.speckit.spec_manager import SpecManager


class ConstitutionManager:
    """Manages project constitution and its integration into the system prompt."""

    def __init__(self, spec_manager: SpecManager):
        self.spec = spec_manager

    # ── Lifecycle ─────────────────────────────────────────────────

    def init(self, project_name: str) -> str:
        """Scaffold a new constitution from template. Returns path."""
        path = self.spec.init_constitution(project_name)
        return str(path)

    def load(self) -> Optional[str]:
        """Load the current constitution text."""
        return self.spec.load_constitution()

    def is_initialized(self) -> bool:
        return self.spec.has_constitution()

    # ── System prompt integration ─────────────────────────────────

    def get_system_prompt_section(self) -> Optional[str]:
        """Produce a condensed constitution section for the LLM system prompt.

        Returns None if no constitution exists, so callers can skip injection.
        """
        return self.spec.get_constitution_prompt()

    # ── Validation ────────────────────────────────────────────────

    def validate_spec_against_constitution(
        self, feature_slug: str
    ) -> List[str]:
        """Check a feature spec against constitutional principles.

        Returns a list of violation messages (empty = compliant).
        Currently a structural check — full semantic validation
        requires LLM review in the analyze phase.
        """
        violations = []
        const = self.load()
        if not const:
            return ["No constitution found. Run /speckit.constitution first."]

        spec_text = self.spec.load_spec(feature_slug)
        if not spec_text:
            violations.append(f"Spec '{feature_slug}' not found.")
            return violations

        # Structural checks (extensible)
        if "## User Scenarios" not in spec_text:
            violations.append("Spec missing User Scenarios section.")
        if "## Requirements" not in spec_text:
            violations.append("Spec missing Requirements section.")
        if "## Success Criteria" not in spec_text:
            violations.append("Spec missing Success Criteria section.")
        if "Main Contradiction" not in spec_text:
            violations.append("Spec missing Main Contradiction section.")
        if "[NEEDS CLARIFICATION]" in spec_text:
            violations.append("Spec has unresolved [NEEDS CLARIFICATION] markers. Run /speckit.clarify.")

        return violations

    def validate_plan_against_constitution(
        self, feature_slug: str
    ) -> List[str]:
        """Check an implementation plan against constitutional principles."""
        violations = []
        const = self.load()
        if not const:
            return ["No constitution found."]

        plan_text = self.spec.load_plan(feature_slug)
        if not plan_text:
            violations.append(f"Plan '{feature_slug}' not found.")
            return violations

        if "## Constitution Check" not in plan_text:
            violations.append("Plan missing Constitution Check section.")
        if "## Source Graph" not in plan_text:
            violations.append("Plan missing Source Graph section.")
        if "## Verification Plan" not in plan_text:
            violations.append("Plan missing Verification Plan section.")

        return violations


__all__ = ["ConstitutionManager"]
