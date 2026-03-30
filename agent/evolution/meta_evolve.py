"""NeoMind Meta-Evolution — The Evolution System That Evolves Itself

Most self-improving agents have a fixed evolution strategy. NeoMind's
meta-evolution layer monitors which evolution mechanisms are actually
producing value, and adjusts the strategy accordingly.

What it tracks:
- Which learnings actually get recalled and used?
- Which skills get promoted vs deprecated?
- Which prompt tuning variants get adopted?
- Which goals get achieved?
- How often does self-edit succeed vs rollback?

What it adjusts:
- Learning extraction frequency (more/less aggressive)
- Skill crystallization threshold (raise/lower promotion bar)
- Prompt tuning exploration rate (more/less random exploration)
- Goal generation aggressiveness (more/fewer auto-goals)
- Self-edit daily limit (more/fewer edits per day)
- Reflection depth (quick-only vs include deep reflections)

This is the "governor" that prevents the evolution system from either
doing too much (wasting compute) or too little (stagnating).

No external dependencies — stdlib only.
"""

import json
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

STATE_FILE = Path("/data/neomind/evolution/meta_state.json")
HISTORY_FILE = Path("/data/neomind/evolution/meta_history.jsonl")


class MetaEvolution:
    """Meta-evolution controller — tunes the evolution system itself."""

    # Default strategy parameters (can be adjusted)
    DEFAULT_STRATEGY = {
        # Learning extraction
        "learning_extraction_enabled": True,
        "learning_extraction_frequency": "every_conversation",  # every_conversation | hourly | daily
        "learning_max_per_extraction": 3,

        # Skill forge
        "skill_forge_enabled": True,
        "skill_promotion_min_uses": 3,
        "skill_promotion_min_success_rate": 0.70,

        # Prompt tuning
        "prompt_tuning_enabled": True,
        "prompt_tuning_exploration_rate": 0.10,  # 10% random exploration
        "prompt_tuning_improvement_threshold": 0.05,

        # Goal tracking
        "goal_auto_generation": True,
        "goal_max_active": 10,

        # Self-edit
        "self_edit_enabled": True,
        "self_edit_daily_limit": 10,

        # Reflection
        "reflection_depth": "quick",  # quick | medium | deep
        "deep_reflection_frequency": "weekly",

        # Cost
        "evolution_token_budget_daily": 5000,  # tokens for evolution tasks
    }

    def __init__(self):
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.state = self._load_state()

    # ── Get Current Strategy ───────────────────────────────

    def get_strategy(self) -> Dict[str, Any]:
        """Return current evolution strategy parameters."""
        return self.state.get("strategy", dict(self.DEFAULT_STRATEGY))

    def get_param(self, key: str, default=None):
        """Get a single strategy parameter."""
        return self.get_strategy().get(key, default)

    # ── Record Evolution Outcomes ──────────────────────────

    def record_outcome(self, mechanism: str, outcome: str,
                        detail: str = "", value: float = 0):
        """Record an evolution mechanism's outcome for meta-analysis.

        Args:
            mechanism: learning | skill | prompt_tuning | goal | self_edit | reflection
            outcome: success | failure | neutral
            detail: Brief description
            value: Numeric value (e.g., metric improvement)
        """
        key = f"outcomes_{mechanism}"
        if key not in self.state:
            self.state[key] = []

        self.state[key].append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "outcome": outcome,
            "detail": detail[:200],
            "value": value,
        })

        # Keep last 100 per mechanism
        self.state[key] = self.state[key][-100:]
        self._save_state()

    # ── Analyze & Adjust ───────────────────────────────────

    def analyze_and_adjust(self) -> Dict[str, Any]:
        """Analyze evolution outcomes and adjust strategy.

        Called weekly by scheduler. Returns adjustment summary.

        Core logic:
        - Mechanism with >70% success → increase aggressiveness
        - Mechanism with <30% success → reduce aggressiveness
        - Mechanism with no data → keep defaults
        """
        strategy = dict(self.get_strategy())
        adjustments = []

        # Analyze each mechanism
        for mechanism in ["learning", "skill", "prompt_tuning", "goal", "self_edit", "reflection"]:
            success_rate, total = self._mechanism_success_rate(mechanism)

            if total < 5:
                continue  # Not enough data

            if mechanism == "learning":
                if success_rate > 0.7 and total > 10:
                    # Learnings are working well → extract more aggressively
                    strategy["learning_max_per_extraction"] = min(5, strategy.get("learning_max_per_extraction", 3) + 1)
                    adjustments.append(f"Learning extraction increased to {strategy['learning_max_per_extraction']}/conv")
                elif success_rate < 0.3:
                    strategy["learning_max_per_extraction"] = max(1, strategy.get("learning_max_per_extraction", 3) - 1)
                    adjustments.append(f"Learning extraction decreased to {strategy['learning_max_per_extraction']}/conv")

            elif mechanism == "skill":
                if success_rate > 0.8:
                    # Skills are high quality → lower promotion bar
                    strategy["skill_promotion_min_uses"] = max(2, strategy.get("skill_promotion_min_uses", 3) - 1)
                    adjustments.append(f"Skill promotion threshold lowered to {strategy['skill_promotion_min_uses']} uses")
                elif success_rate < 0.4:
                    # Too many bad skills → raise bar
                    strategy["skill_promotion_min_uses"] = min(5, strategy.get("skill_promotion_min_uses", 3) + 1)
                    adjustments.append(f"Skill promotion threshold raised to {strategy['skill_promotion_min_uses']} uses")

            elif mechanism == "prompt_tuning":
                if success_rate > 0.6:
                    # Tuning is productive → explore more
                    rate = min(0.20, strategy.get("prompt_tuning_exploration_rate", 0.10) + 0.02)
                    strategy["prompt_tuning_exploration_rate"] = round(rate, 2)
                    adjustments.append(f"Prompt exploration rate → {rate:.0%}")
                elif success_rate < 0.2:
                    # Tuning isn't helping → explore less
                    rate = max(0.05, strategy.get("prompt_tuning_exploration_rate", 0.10) - 0.02)
                    strategy["prompt_tuning_exploration_rate"] = round(rate, 2)
                    adjustments.append(f"Prompt exploration rate → {rate:.0%}")

            elif mechanism == "self_edit":
                if success_rate > 0.8:
                    limit = min(20, strategy.get("self_edit_daily_limit", 10) + 2)
                    strategy["self_edit_daily_limit"] = limit
                    adjustments.append(f"Self-edit daily limit → {limit}")
                elif success_rate < 0.3:
                    limit = max(3, strategy.get("self_edit_daily_limit", 10) - 2)
                    strategy["self_edit_daily_limit"] = limit
                    adjustments.append(f"Self-edit daily limit → {limit}")

            elif mechanism == "goal":
                if success_rate > 0.5:
                    # Goals being achieved → more ambitious
                    strategy["goal_max_active"] = min(15, strategy.get("goal_max_active", 10) + 2)
                    adjustments.append(f"Max active goals → {strategy['goal_max_active']}")
                elif success_rate < 0.2:
                    # Goals not being met → fewer, more focused
                    strategy["goal_max_active"] = max(3, strategy.get("goal_max_active", 10) - 2)
                    adjustments.append(f"Max active goals → {strategy['goal_max_active']}")

            elif mechanism == "reflection":
                if success_rate > 0.7 and total > 10:
                    if strategy.get("reflection_depth") == "quick":
                        strategy["reflection_depth"] = "medium"
                        adjustments.append("Reflection depth → medium")
                elif success_rate < 0.3:
                    if strategy.get("reflection_depth") == "medium":
                        strategy["reflection_depth"] = "quick"
                        adjustments.append("Reflection depth → quick")

        # Save updated strategy
        if adjustments:
            self.state["strategy"] = strategy
            self._save_state()
            self._log_adjustment(adjustments)
            logger.info(f"Meta-evolution adjusted {len(adjustments)} params: {adjustments}")

        return {
            "adjustments": adjustments,
            "mechanism_stats": self._all_mechanism_stats(),
        }

    # ── Emergency Controls ─────────────────────────────────

    def disable_mechanism(self, mechanism: str):
        """Emergency disable of an evolution mechanism."""
        strategy = self.get_strategy()
        key = f"{mechanism}_enabled"
        if key in strategy:
            strategy[key] = False
            self.state["strategy"] = strategy
            self._save_state()
            logger.warning(f"Meta-evolution: DISABLED {mechanism}")

    def enable_mechanism(self, mechanism: str):
        """Re-enable a disabled mechanism."""
        strategy = self.get_strategy()
        key = f"{mechanism}_enabled"
        if key in strategy:
            strategy[key] = True
            self.state["strategy"] = strategy
            self._save_state()
            logger.info(f"Meta-evolution: enabled {mechanism}")

    def reset_to_defaults(self):
        """Reset all strategy parameters to defaults."""
        self.state["strategy"] = dict(self.DEFAULT_STRATEGY)
        self._save_state()
        logger.info("Meta-evolution: reset to defaults")

    # ── Statistics ─────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Return meta-evolution statistics for dashboard."""
        return {
            "strategy": self.get_strategy(),
            "mechanism_stats": self._all_mechanism_stats(),
            "total_adjustments": self.state.get("total_adjustments", 0),
        }

    # ── Internal ───────────────────────────────────────────

    def _mechanism_success_rate(self, mechanism: str) -> Tuple[float, int]:
        """Calculate success rate for a mechanism over last 30 days."""
        key = f"outcomes_{mechanism}"
        outcomes = self.state.get(key, [])
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        recent = [o for o in outcomes if o.get("ts", "") > cutoff]

        if not recent:
            return 0.0, 0

        successes = sum(1 for o in recent if o["outcome"] == "success")
        return successes / len(recent), len(recent)

    def _all_mechanism_stats(self) -> Dict[str, Dict]:
        stats = {}
        for m in ["learning", "skill", "prompt_tuning", "goal", "self_edit", "reflection"]:
            rate, total = self._mechanism_success_rate(m)
            stats[m] = {"success_rate": round(rate, 3), "total_outcomes": total}
        return stats

    def _log_adjustment(self, adjustments: list):
        """Log strategy adjustment to history."""
        try:
            entry = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "adjustments": adjustments,
            }
            with open(HISTORY_FILE, "a") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self.state["total_adjustments"] = self.state.get("total_adjustments", 0) + 1
            self._save_state()
        except Exception:
            pass

    def _load_state(self) -> Dict:
        if STATE_FILE.exists():
            try:
                return json.loads(STATE_FILE.read_text())
            except Exception:
                pass
        return {"strategy": dict(self.DEFAULT_STRATEGY)}

    def _save_state(self):
        try:
            tmp = STATE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.state, ensure_ascii=False, indent=2))
            tmp.replace(STATE_FILE)
        except Exception as e:
            logger.error(f"Failed to save meta state: {e}")
