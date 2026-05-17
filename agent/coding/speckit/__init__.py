"""
spec-kit integration for NeoMind Coding personality.

Spec-driven development methodology:
    constitution → specify → clarify → plan → tasks → analyze → implement

Usage:
    /speckit.constitution [project-name]   — Scaffold project constitution
    /speckit.specify <name> [description]  — Create feature specification
    /speckit.clarify <slug>                — Resolve [NEEDS CLARIFICATION]
    /speckit.plan <slug>                   — Generate implementation plan
    /speckit.tasks <slug>                  — Break plan into tasks
    /speckit.analyze <slug>                — Cross-artifact consistency check
    /speckit.implement <slug>              — Execute implementation
    /speckit.checklist <slug>              — Generate quality checklist
    /speckit.status [slug]                 — Show spec-kit state
"""

from agent.coding.speckit.spec_manager import SpecManager
from agent.coding.speckit.constitution import ConstitutionManager
from agent.coding.speckit.phase_runner import PhaseRunner, PhaseResult

__all__ = [
    "SpecManager",
    "ConstitutionManager",
    "PhaseRunner",
    "PhaseResult",
]
