# agent/workflow/review.py
"""
Self-Review — mode-aware review dispatch.

Each personality has its own review criteria:
- coding: code correctness, security, edge cases
- fin: trade validation, risk limits, data accuracy
- chat: fact-checking, source verification, logical consistency

The review prompt is injected after the "build" phase output.
"""

from typing import Optional
from ..skills import get_skill_loader


class ReviewDispatcher:
    """Dispatches the appropriate review skill based on mode.

    Usage:
        dispatcher = ReviewDispatcher()
        review_prompt = dispatcher.get_review_prompt("coding")
        # → returns eng-review skill body
    """

    # Map mode → review skill name
    MODE_REVIEW_SKILL = {
        "coding": "eng-review",
        "fin": "trade-review",
        "chat": None,  # chat uses inline review (no separate skill)
    }

    def get_review_prompt(self, mode: str) -> Optional[str]:
        """Get the review skill prompt for a mode."""
        skill_name = self.MODE_REVIEW_SKILL.get(mode)
        if not skill_name:
            return self._default_review_prompt()

        loader = get_skill_loader()
        skill = loader.get(skill_name)
        if skill:
            return skill.to_system_prompt()
        return self._default_review_prompt()

    def should_review(self, mode: str, action: str) -> bool:
        """Determine if an action needs review.

        coding: always review code changes
        fin: always review trades, optionally review analysis
        chat: review factual claims
        """
        if mode == "coding":
            return action in ("file_edit", "code_write", "build", "refactor")
        elif mode == "fin":
            return action in ("trade", "execute", "allocate")
        elif mode == "chat":
            return action in ("factual_claim", "recommendation")
        return False

    @staticmethod
    def _default_review_prompt() -> str:
        return (
            "## Self-Review\n"
            "Before finalizing, review your work:\n"
            "1. Is the output correct? Check facts, logic, calculations.\n"
            "2. Did you miss any edge cases?\n"
            "3. Is there anything you're uncertain about? If so, say so.\n"
            "4. Would you be comfortable if someone verified this?\n"
        )
