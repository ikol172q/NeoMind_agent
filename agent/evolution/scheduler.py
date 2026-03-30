"""NeoMind Evolution Scheduler — Orchestrates All Evolution Engines

Integrates with NeoMind's natural lifecycle points to run evolution tasks
at the right time with the right frequency:

Session start:
  - Health check
  - Restore checkpoint
  - Inject learnings into system prompt
  - Boot loop detection (via health_monitor)

After each conversation turn (every N turns):
  - Quick reflection
  - Signal collection for prompt tuner
  - Heartbeat update
  - Checkpoint save

Daily (checked at session start + every 50 turns):
  - Daily audit (auto_evolve)
  - Learning decay/prune
  - Prompt variant generation
  - Goal progress check
  - Cost report
  - Cache cleanup

Weekly (checked at session start):
  - Weekly retrospective
  - Deep reflection (LLM-assisted)
  - Prompt evaluation + adopt/rollback
  - Meta-evolution analysis + strategy adjustment
  - Goal expiry

All runs are non-blocking and wrapped in try/except.
No external dependencies — stdlib only.
"""

import os
import logging
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)


class EvolutionScheduler:
    """Orchestrates all evolution engines at lifecycle points.

    Usage:
        scheduler = EvolutionScheduler(auto_evolve)
        scheduler.on_session_start()                  # at startup
        scheduler.on_turn_complete(turn_number, ...)   # after each turn
        scheduler.on_session_end()                     # at shutdown
    """

    def __init__(self, auto_evolve=None):
        self.auto_evolve = auto_evolve
        self.actions_taken: List[str] = []
        self.daily_ran_this_session = False
        self.weekly_ran_this_session = False
        self.turn_check_interval = 50
        self.last_turn_checked = 0

        # Lazy-init engines (only when needed)
        self._learnings = None
        self._reflection = None
        self._prompt_tuner = None
        self._goal_tracker = None
        self._skill_forge = None
        self._meta = None
        self._cost = None
        self._checkpoint = None
        self._heartbeat = None
        self._intelligence = None  # Cross-mode intelligence pipeline

        # Safe mode check
        self._safe_mode = os.getenv("NEOMIND_SAFE_MODE") == "1"

    # ── Engine Accessors (lazy-init) ───────────────────────

    def _get_learnings(self):
        if self._learnings is None:
            try:
                from .learnings import LearningsEngine
                self._learnings = LearningsEngine()
            except Exception as e:
                logger.debug(f"LearningsEngine not available: {e}")
        return self._learnings

    def _get_reflection(self):
        if self._reflection is None:
            try:
                from .reflection import ReflectionEngine
                self._reflection = ReflectionEngine()
            except Exception as e:
                logger.debug(f"ReflectionEngine not available: {e}")
        return self._reflection

    def _get_prompt_tuner(self):
        if self._prompt_tuner is None:
            try:
                from .prompt_tuner import PromptTuner
                self._prompt_tuner = PromptTuner()
            except Exception as e:
                logger.debug(f"PromptTuner not available: {e}")
        return self._prompt_tuner

    def _get_goal_tracker(self):
        if self._goal_tracker is None:
            try:
                from .goal_tracker import GoalTracker
                self._goal_tracker = GoalTracker()
            except Exception as e:
                logger.debug(f"GoalTracker not available: {e}")
        return self._goal_tracker

    def _get_skill_forge(self):
        if self._skill_forge is None:
            try:
                from .skill_forge import SkillForge
                self._skill_forge = SkillForge()
            except Exception as e:
                logger.debug(f"SkillForge not available: {e}")
        return self._skill_forge

    def _get_meta(self):
        if self._meta is None:
            try:
                from .meta_evolve import MetaEvolution
                self._meta = MetaEvolution()
            except Exception as e:
                logger.debug(f"MetaEvolution not available: {e}")
        return self._meta

    def _get_cost(self):
        if self._cost is None:
            try:
                from .cost_optimizer import CostOptimizer
                self._cost = CostOptimizer()
            except Exception as e:
                logger.debug(f"CostOptimizer not available: {e}")
        return self._cost

    def _get_checkpoint(self):
        if self._checkpoint is None:
            try:
                from .checkpoint import Checkpoint
                self._checkpoint = Checkpoint()
            except Exception as e:
                logger.debug(f"Checkpoint not available: {e}")
        return self._checkpoint

    def _get_heartbeat(self):
        if self._heartbeat is None:
            try:
                from .health_monitor import HeartbeatWriter
                self._heartbeat = HeartbeatWriter()
            except Exception as e:
                logger.debug(f"HeartbeatWriter not available: {e}")
        return self._heartbeat

    def _get_intelligence(self):
        """Cross-mode intelligence pipeline (data-collector ↔ personalities)."""
        if self._intelligence is None:
            try:
                from agent.data.intelligence import CrossModeIntelligence
                self._intelligence = CrossModeIntelligence()
            except Exception as e:
                logger.debug(f"CrossModeIntelligence not available: {e}")
        return self._intelligence

    # ── Session Start ──────────────────────────────────────

    def on_session_start(self) -> List[str]:
        """Called at the start of a new session.

        Runs:
        1. Start heartbeat writer
        2. Restore checkpoint
        3. Health check (auto_evolve)
        4. Daily audit (if 24h+ since last)
        5. Weekly retro (if 7d+ since last)
        6. Goal expiry check

        Returns: List of action descriptions
        """
        self.actions_taken = []

        # Start heartbeat
        heartbeat = self._get_heartbeat()
        if heartbeat:
            try:
                heartbeat.start()
                self.actions_taken.append("Heartbeat writer started")
            except Exception as e:
                logger.error(f"Heartbeat start failed: {e}")

        # Restore checkpoint
        cp = self._get_checkpoint()
        if cp:
            try:
                state = cp.load()
                if state:
                    self.actions_taken.append(
                        f"Checkpoint restored (turn {state.get('turn_count', '?')})"
                    )
            except Exception as e:
                logger.error(f"Checkpoint restore failed: {e}")

        # Health check
        if self.auto_evolve:
            try:
                health = self.auto_evolve.run_startup_check()
                if health:
                    msg = f"Health: {health.checks_passed} checks passed"
                    if health.issues:
                        msg += f", {len(health.issues)} issues"
                    self.actions_taken.append(msg)
            except Exception as e:
                logger.error(f"Health check failed: {e}")
                self.actions_taken.append(f"Health check error: {str(e)[:40]}")

        # Daily audit
        if (self.auto_evolve and
                self.auto_evolve.should_run_daily() and
                not self.daily_ran_this_session):
            self._run_daily_cycle()

        # Weekly retro
        if (self.auto_evolve and
                self.auto_evolve.should_run_weekly() and
                not self.weekly_ran_this_session):
            self._run_weekly_cycle()

        # Expire stale goals
        goal_tracker = self._get_goal_tracker()
        if goal_tracker:
            try:
                expired = goal_tracker.expire_stale_goals()
                if expired:
                    self.actions_taken.append(f"Expired {expired} stale goals")
            except Exception as e:
                logger.debug(f"Goal expiry failed: {e}")

        return self.actions_taken

    # ── Per-Turn ───────────────────────────────────────────

    def on_turn_complete(self, turn_number: int,
                          mode: str = "chat",
                          user_satisfaction: float = 0.5,
                          error_occurred: bool = False,
                          conversation_summary: str = "") -> List[str]:
        """Called after each conversation turn.

        Runs:
        1. Quick reflection
        2. Prompt tuner signal collection
        3. Heartbeat beat
        4. Checkpoint save
        5. Every N turns: check daily audit

        Args:
            turn_number: Current turn count
            mode: Agent mode (chat/coding/fin)
            user_satisfaction: Estimated satisfaction 0-1
            error_occurred: Whether an error happened
            conversation_summary: Brief summary for learning extraction
        """
        self.actions_taken = []

        if self._safe_mode:
            return self.actions_taken

        # Manual heartbeat
        heartbeat = self._get_heartbeat()
        if heartbeat:
            heartbeat.beat()

        # Quick reflection (lightweight, every turn)
        reflection = self._get_reflection()
        if reflection:
            try:
                reflection.reflect_quick(
                    mode, conversation_summary,
                    user_satisfaction, error_occurred
                )
            except Exception as e:
                logger.debug(f"Quick reflection failed: {e}")

        # Prompt tuner signals
        tuner = self._get_prompt_tuner()
        if tuner:
            try:
                tuner.record_signal(mode, "user_satisfaction", user_satisfaction)
                if error_occurred:
                    tuner.record_signal(mode, "task_completion", 0.0)
                else:
                    tuner.record_signal(mode, "task_completion", 1.0)
            except Exception as e:
                logger.debug(f"Signal recording failed: {e}")

        # Save checkpoint
        cp = self._get_checkpoint()
        if cp:
            try:
                cp.save({
                    "mode": mode,
                    "turn_count": turn_number,
                    "safe_mode": self._safe_mode,
                })
            except Exception:
                pass

        # Integration hooks: periodic tasks (drift, KG, distillation cleanup)
        if turn_number % 50 == 0:
            try:
                from agent.evolution.integration_hooks import periodic_tasks
                hook_results = periodic_tasks(turn_number, mode)
                if hook_results.get("alerts"):
                    for alert in hook_results["alerts"]:
                        self.actions_taken.append(
                            f"⚠️ {alert['type']}: {alert.get('severity', '?')} "
                            f"— {', '.join(alert.get('metrics', []))}"
                        )
                logger.debug(f"Periodic hooks: {hook_results}")
            except ImportError:
                pass
            except Exception as e:
                logger.debug(f"Periodic hooks error: {e}")

        # Every N turns: check daily cycle
        if turn_number - self.last_turn_checked >= self.turn_check_interval:
            self.last_turn_checked = turn_number
            if (self.auto_evolve and
                    self.auto_evolve.should_run_daily() and
                    not self.daily_ran_this_session):
                self._run_daily_cycle()

        return self.actions_taken

    # ── Session End ────────────────────────────────────────

    def on_session_end(self, mode: str = "chat") -> List[str]:
        """Called at the end of a session.

        Runs:
        1. Final daily audit if not yet run
        2. Save checkpoint (clean shutdown)
        3. Final learning extraction prompt (for next session)
        """
        self.actions_taken = []

        # Final daily audit
        if (self.auto_evolve and
                not self.daily_ran_this_session and
                self.auto_evolve.should_run_daily()):
            self._run_daily_cycle()

        # Save final checkpoint
        cp = self._get_checkpoint()
        if cp:
            try:
                cp.save({"mode": mode, "clean_shutdown": True})
                self.actions_taken.append("Checkpoint saved (clean shutdown)")
            except Exception:
                pass

        return self.actions_taken

    # ── Error Handler ──────────────────────────────────────

    def on_error(self, mode: str, error_type: str,
                  error_msg: str, context: str = "") -> List[str]:
        """Called when an error occurs — triggers reflection + learning.

        This is where the agent learns from its mistakes.
        """
        self.actions_taken = []

        if self._safe_mode:
            return self.actions_taken

        # Error reflection
        reflection = self._get_reflection()
        if reflection:
            try:
                result = reflection.reflect_on_error(mode, error_type, error_msg, context)
                self.actions_taken.append(f"Error reflection: {len(result.get('hypotheses', []))} hypotheses")
            except Exception as e:
                logger.debug(f"Error reflection failed: {e}")

        # Error learning
        learnings = self._get_learnings()
        if learnings:
            try:
                learnings.add_error_learning(mode, error_type, error_msg, "pending investigation")
            except Exception:
                pass

        # Record for meta-evolution
        meta = self._get_meta()
        if meta:
            meta.record_outcome("reflection", "success", f"error_{error_type}")

        return self.actions_taken

    # ── Prompt Injection ───────────────────────────────────

    def get_prompt_additions(self, mode: str) -> str:
        """Get evolution-generated additions for the system prompt.

        Returns text to append to system prompt, containing:
        - Top learnings
        - Active goals
        """
        if self._safe_mode:
            return ""

        parts = []

        # Learnings
        learnings = self._get_learnings()
        if learnings:
            try:
                injection = learnings.get_prompt_injection(mode)
                if injection:
                    parts.append(injection)
            except Exception:
                pass

        # Goals
        goal_tracker = self._get_goal_tracker()
        if goal_tracker:
            try:
                summary = goal_tracker.get_goal_summary(mode)
                if summary:
                    parts.append(summary)
            except Exception:
                pass

        # Cross-mode intelligence (briefings, decisions, market data)
        intelligence = self._get_intelligence()
        if intelligence:
            try:
                intel_text = intelligence.get_prompt_addition(mode)
                if intel_text:
                    parts.append(intel_text)
            except Exception as e:
                logger.debug(f"Cross-mode intelligence injection failed: {e}")

        return "\n\n".join(parts)

    # ── Daily Cycle ────────────────────────────────────────

    def _run_daily_cycle(self):
        """Run all daily evolution tasks."""
        logger.info("Evolution: Running daily cycle")

        # Auto_evolve daily audit
        if self.auto_evolve:
            try:
                report = self.auto_evolve.run_daily_audit()
                if report:
                    msg = f"Daily audit: {report.total_calls} calls, {report.errors} errors"
                    self.actions_taken.append(msg)
                    self.daily_ran_this_session = True
            except Exception as e:
                logger.error(f"Daily audit failed: {e}")

        # Learning decay
        learnings = self._get_learnings()
        if learnings:
            try:
                total, pruned = learnings.decay_and_prune()
                if pruned:
                    self.actions_taken.append(f"Pruned {pruned} stale learnings ({total} remaining)")
            except Exception as e:
                logger.debug(f"Learning decay failed: {e}")

        # Prompt variant generation
        tuner = self._get_prompt_tuner()
        if tuner:
            for mode in ["chat", "coding", "fin"]:
                try:
                    variant = tuner.generate_variant(mode)
                    if variant:
                        self.actions_taken.append(f"Prompt variant generated for {mode}")
                except Exception as e:
                    logger.debug(f"Variant generation failed for {mode}: {e}")

        # Cost cache cleanup
        cost = self._get_cost()
        if cost:
            try:
                cost.cleanup_cache()
            except Exception:
                pass

    # ── Weekly Cycle ───────────────────────────────────────

    def _run_weekly_cycle(self):
        """Run all weekly evolution tasks."""
        logger.info("Evolution: Running weekly cycle")

        # Auto_evolve weekly retro
        if self.auto_evolve:
            try:
                report = self.auto_evolve.run_weekly_retro()
                if report:
                    msg = f"Weekly retro: {report.total_sessions} sessions"
                    self.actions_taken.append(msg)
                    self.weekly_ran_this_session = True
            except Exception as e:
                logger.error(f"Weekly retro failed: {e}")

        # Prompt tuning evaluation
        tuner = self._get_prompt_tuner()
        if tuner:
            for mode in ["chat", "coding", "fin"]:
                try:
                    adopted, msg = tuner.evaluate_and_adopt(mode)
                    if msg:
                        self.actions_taken.append(f"Prompt tuner ({mode}): {msg}")
                except Exception as e:
                    logger.debug(f"Prompt evaluation failed for {mode}: {e}")

        # Meta-evolution analysis
        meta = self._get_meta()
        if meta:
            try:
                result = meta.analyze_and_adjust()
                adjustments = result.get("adjustments", [])
                if adjustments:
                    self.actions_taken.append(
                        f"Meta-evolution: {len(adjustments)} strategy adjustments"
                    )
            except Exception as e:
                logger.debug(f"Meta-evolution failed: {e}")

        # Goal expiry
        goal_tracker = self._get_goal_tracker()
        if goal_tracker:
            try:
                expired = goal_tracker.expire_stale_goals()
                if expired:
                    self.actions_taken.append(f"Expired {expired} stale goals")
            except Exception:
                pass

    # ── Dashboard Data ─────────────────────────────────────

    def get_evolution_status(self) -> Dict[str, Any]:
        """Comprehensive evolution status for dashboard."""
        status = {
            "safe_mode": self._safe_mode,
            "daily_ran": self.daily_ran_this_session,
            "weekly_ran": self.weekly_ran_this_session,
        }

        for name, getter in [
            ("learnings", self._get_learnings),
            ("skills", self._get_skill_forge),
            ("reflection", self._get_reflection),
            ("goals", self._get_goal_tracker),
            ("meta", self._get_meta),
            ("cost", self._get_cost),
        ]:
            engine = getter()
            if engine and hasattr(engine, "get_stats"):
                try:
                    status[name] = engine.get_stats()
                except Exception:
                    status[name] = {"error": "unavailable"}

        return status

    def check_and_run_pending(self) -> List[str]:
        """Legacy compatibility — check all pending tasks."""
        return self.on_session_start()
