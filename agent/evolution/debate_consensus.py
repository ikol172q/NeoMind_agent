"""NeoMind Debate-Based Consensus Protocol

Multi-perspective decision making where different "viewpoints" argue
for/against a proposed action, then reach consensus.

Used for high-stakes decisions:
- Self-edit proposals (should we apply this code change?)
- Model routing (should we escalate to expensive model?)
- Goal prioritization (which goal to focus on?)

Research: Round 3 — debate-based consensus improves decision quality
for self-modifying agents by forcing consideration of risks and tradeoffs.

No external dependencies — stdlib only.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Callable

logger = logging.getLogger(__name__)


class Viewpoint:
    """A perspective that argues for or against a proposal.

    Each viewpoint has:
    - name: descriptive label (e.g., "safety_advocate", "efficiency_optimizer")
    - evaluate: function that takes context and returns argument + score
    - weight: how much this viewpoint's vote counts
    """

    def __init__(self, name: str,
                 evaluate: Callable[[Dict[str, Any]], Dict[str, Any]],
                 weight: float = 1.0):
        self.name = name
        self.evaluate = evaluate
        self.weight = weight

    def argue(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Generate argument for/against the proposal.

        Returns:
            Dict with 'score' (-1 to 1), 'argument' (text), 'concerns' (list)
        """
        try:
            result = self.evaluate(context)
            return {
                "viewpoint": self.name,
                "score": max(-1.0, min(1.0, result.get("score", 0))),
                "argument": result.get("argument", ""),
                "concerns": result.get("concerns", []),
                "weight": self.weight,
            }
        except Exception as e:
            logger.error(f"Viewpoint {self.name} failed: {e}")
            return {
                "viewpoint": self.name,
                "score": 0,
                "argument": f"Evaluation error: {e}",
                "concerns": ["viewpoint_error"],
                "weight": self.weight,
            }


class DebateConsensus:
    """Orchestrates multi-perspective debate for decision making.

    Usage:
        debate = DebateConsensus()

        result = debate.deliberate({
            "proposal": "Apply self-edit to learnings.py",
            "change_type": "add_method",
            "risk_level": "medium",
            "estimated_benefit": "15% improvement in recall",
        })

        if result["decision"] == "approve":
            apply_edit()
        else:
            log_rejection(result["reasons"])
    """

    def __init__(self, approval_threshold: float = 0.3):
        """
        Args:
            approval_threshold: Weighted score above which proposal is approved (0-1)
        """
        self.approval_threshold = approval_threshold
        self._viewpoints: List[Viewpoint] = []
        self._history: List[Dict] = []
        self._load_builtin_viewpoints()

    def add_viewpoint(self, viewpoint: Viewpoint) -> None:
        """Register a viewpoint for debates."""
        self._viewpoints.append(viewpoint)

    def deliberate(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Run a full debate on a proposal.

        Each viewpoint evaluates the proposal, then votes are
        weighted and aggregated to reach a decision.

        Args:
            context: Proposal details and relevant information

        Returns:
            Dict with decision, score, arguments, concerns
        """
        if not self._viewpoints:
            return {"decision": "approve", "score": 1.0, "reason": "no_viewpoints"}

        arguments = []
        for vp in self._viewpoints:
            arg = vp.argue(context)
            arguments.append(arg)

        # Calculate weighted score
        total_weight = sum(a["weight"] for a in arguments)
        if total_weight == 0:
            weighted_score = 0
        else:
            weighted_score = sum(
                a["score"] * a["weight"] for a in arguments
            ) / total_weight

        # Collect all concerns
        all_concerns = []
        for arg in arguments:
            all_concerns.extend(arg.get("concerns", []))

        # Check for any blocking viewpoint (score <= -0.8 with high weight)
        blocked_by = [
            a for a in arguments
            if a["score"] <= -0.8 and a["weight"] >= 1.5
        ]

        if blocked_by:
            decision = "block"
            reason = f"Blocked by: {', '.join(a['viewpoint'] for a in blocked_by)}"
        elif weighted_score >= self.approval_threshold:
            decision = "approve"
            reason = f"Consensus reached (score: {weighted_score:.2f})"
        else:
            decision = "reject"
            reason = f"Below threshold (score: {weighted_score:.2f}, threshold: {self.approval_threshold})"

        result = {
            "decision": decision,
            "score": round(weighted_score, 3),
            "reason": reason,
            "arguments": arguments,
            "concerns": list(set(all_concerns)),
            "blocked_by": [a["viewpoint"] for a in blocked_by],
            "ts": datetime.now(timezone.utc).isoformat(),
        }

        self._history.append(result)
        if len(self._history) > 200:
            self._history = self._history[-100:]

        log_fn = logger.info if decision == "approve" else logger.warning
        log_fn(f"Debate result: {decision} (score={weighted_score:.2f}, viewpoints={len(arguments)})")

        return result

    def get_history(self, limit: int = 20) -> List[Dict]:
        """Get recent debate history."""
        return self._history[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        """Get debate statistics."""
        if not self._history:
            return {"total_debates": 0}

        approvals = sum(1 for h in self._history if h["decision"] == "approve")
        rejections = sum(1 for h in self._history if h["decision"] == "reject")
        blocks = sum(1 for h in self._history if h["decision"] == "block")

        return {
            "total_debates": len(self._history),
            "approvals": approvals,
            "rejections": rejections,
            "blocks": blocks,
            "approval_rate": round(approvals / len(self._history), 3),
            "viewpoint_count": len(self._viewpoints),
        }

    # ── Built-in Viewpoints ─────────────────────────

    def _load_builtin_viewpoints(self) -> None:
        """Load NeoMind's standard debate viewpoints."""

        # Safety Advocate — always considers risk
        self.add_viewpoint(Viewpoint(
            name="safety_advocate",
            evaluate=self._safety_evaluate,
            weight=1.5,  # Safety gets extra weight
        ))

        # Efficiency Optimizer — considers cost/benefit
        self.add_viewpoint(Viewpoint(
            name="efficiency_optimizer",
            evaluate=self._efficiency_evaluate,
            weight=1.0,
        ))

        # Stability Guardian — prefers minimal changes
        self.add_viewpoint(Viewpoint(
            name="stability_guardian",
            evaluate=self._stability_evaluate,
            weight=1.2,
        ))

        # Innovation Driver — favors improvement
        self.add_viewpoint(Viewpoint(
            name="innovation_driver",
            evaluate=self._innovation_evaluate,
            weight=0.8,
        ))

    @staticmethod
    def _safety_evaluate(ctx: Dict) -> Dict:
        """Safety viewpoint: evaluate risk of proposal."""
        risk = ctx.get("risk_level", "medium")
        changes_safety_files = ctx.get("changes_safety_files", False)
        has_tests = ctx.get("has_tests", False)

        concerns = []
        score = 0.5  # Default: cautiously positive

        if changes_safety_files:
            score = -1.0
            concerns.append("modifies_safety_critical_files")
        elif risk == "high":
            score = -0.5
            concerns.append("high_risk_change")
        elif risk == "low":
            score = 0.8

        if not has_tests and risk != "low":
            score -= 0.3
            concerns.append("no_test_coverage")

        return {
            "score": score,
            "argument": f"Risk level: {risk}. Safety assessment: {'acceptable' if score > 0 else 'concerning'}",
            "concerns": concerns,
        }

    @staticmethod
    def _efficiency_evaluate(ctx: Dict) -> Dict:
        """Efficiency viewpoint: cost-benefit analysis."""
        benefit = ctx.get("estimated_benefit", "unknown")
        cost = ctx.get("estimated_cost", "low")

        score = 0.3  # Default: slightly positive

        if "improvement" in str(benefit).lower() or "faster" in str(benefit).lower():
            score = 0.7
        if cost == "high":
            score -= 0.4
        elif cost == "low":
            score += 0.2

        return {
            "score": score,
            "argument": f"Benefit: {benefit}. Cost: {cost}.",
            "concerns": ["high_cost"] if cost == "high" else [],
        }

    @staticmethod
    def _stability_evaluate(ctx: Dict) -> Dict:
        """Stability viewpoint: prefer minimal disruption."""
        change_type = ctx.get("change_type", "modify")
        lines_changed = ctx.get("lines_changed", 0)

        if change_type in ("delete", "refactor"):
            score = -0.3
            concerns = ["disruptive_change_type"]
        elif lines_changed > 100:
            score = -0.2
            concerns = ["large_change"]
        elif change_type == "add_method":
            score = 0.5
            concerns = []
        else:
            score = 0.2
            concerns = []

        return {
            "score": score,
            "argument": f"Change type: {change_type}, scope: {lines_changed} lines",
            "concerns": concerns,
        }

    @staticmethod
    def _innovation_evaluate(ctx: Dict) -> Dict:
        """Innovation viewpoint: favors learning and improvement."""
        benefit = ctx.get("estimated_benefit", "")
        is_reversible = ctx.get("reversible", True)

        score = 0.6  # Default: positive about progress
        concerns = []

        if not is_reversible:
            score -= 0.5
            concerns.append("irreversible_change")

        if "improvement" in str(benefit).lower():
            score += 0.2

        return {
            "score": score,
            "argument": f"Progress opportunity. Reversible: {is_reversible}",
            "concerns": concerns,
        }


# ── Singleton ──────────────────────────────────────

_debate: Optional[DebateConsensus] = None


def get_debate_consensus() -> DebateConsensus:
    """Get or create the global DebateConsensus singleton."""
    global _debate
    if _debate is None:
        _debate = DebateConsensus()
    return _debate
