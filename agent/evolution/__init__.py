"""NeoMind Evolution Module — Complete Self-Improvement & Resilience System
数据驱动的个人能力延伸系统 — 自我进化引擎

Core engines:
- auto_evolve: Baseline evolution (health checks, daily/weekly audits, feedback learning)
- learnings: Structured learning extraction with FOREVER adaptive Ebbinghaus decay
- skill_forge: SkillRL dual-bank crystallization (general + task-specific)
- reflection: Post-task self-evaluation + PreFlect prospective reflection
- goal_tracker: Autonomous self-improvement goal setting + tracking
- meta_evolve: The evolution system that evolves itself
- cost_optimizer: Token/cost tracking + RouteLLM-inspired adaptive routing

Infrastructure:
- self_edit: Git-Gated code self-modification with AST safety
- prompt_tuner: Metric-driven YAML prompt parameter tuning
- self_unblock: Automatic diagnosis + repair for runtime obstacles
- health_monitor: Heartbeat detection, boot loop protection, Telegram alerts
- watchdog: Last-resort hang detection + forced restart
- checkpoint: Atomic state save/restore for restart recovery
- scheduler: Orchestrates all engines + cross-mode intelligence at lifecycle points
- upgrade: Git-based self-upgrade mechanism
- dashboard: HTML dashboard for evolution metrics

New subsystems (v0.3.1):
- agent.data: 24/7 background data collection (collector, rate_limiter, compliance)
- agent.data.intelligence: Cross-mode intelligence pipeline (data → fin → chat)
- agent.llm: LLM-agnostic abstraction (context_budget, tool_translator)

New subsystems (v0.3.3):
- agent.utils: Structured logging, circuit breaker, shared utilities
- learnings: Sleep-cycle memory consolidation (merge, promote, archive, cross-link)
- self_edit: Constitutional safety constraints (7 principles + AST regression detection)
- prompt_tuner: OPRO-style LLM-driven prompt self-optimization
- cost_optimizer: Semantic caching with n-gram fingerprints
- health_monitor: SQLite PRAGMA health checks (integrity, optimize, WAL)
"""

from .auto_evolve import AutoEvolve, HealthReport, DailyReport, RetroReport

__all__ = [
    "AutoEvolve", "HealthReport", "DailyReport", "RetroReport",
]


# ── Lazy accessors (avoid slowing down agent startup) ──────

def get_self_editor():
    from .self_edit import SelfEditor
    return SelfEditor()

def get_prompt_tuner():
    from .prompt_tuner import PromptTuner
    return PromptTuner()

def get_self_unblocker():
    from .self_unblock import SelfUnblocker
    return SelfUnblocker()

def get_checkpoint():
    from .checkpoint import Checkpoint
    return Checkpoint()

def get_heartbeat_writer():
    from .health_monitor import HeartbeatWriter
    return HeartbeatWriter()

def get_learnings_engine():
    from .learnings import LearningsEngine
    return LearningsEngine()

def get_skill_forge():
    from .skill_forge import SkillForge
    return SkillForge()

def get_reflection_engine():
    from .reflection import ReflectionEngine
    return ReflectionEngine()

def get_goal_tracker():
    from .goal_tracker import GoalTracker
    return GoalTracker()

def get_meta_evolution():
    from .meta_evolve import MetaEvolution
    return MetaEvolution()

def get_cost_optimizer():
    from .cost_optimizer import CostOptimizer
    return CostOptimizer()

def get_cross_mode_intelligence():
    from agent.data.intelligence import CrossModeIntelligence
    return CrossModeIntelligence()

def get_context_budget_manager(model_max_tokens=131072):
    from agent.llm.context_budget import ContextBudgetManager
    return ContextBudgetManager(model_max_tokens=model_max_tokens)

def get_tool_translator():
    from agent.llm.tool_translator import ToolSchemaTranslator
    return ToolSchemaTranslator()

def get_circuit_breaker(name: str, **kwargs):
    from agent.utils.circuit_breaker import CircuitBreakerRegistry
    return CircuitBreakerRegistry.get_breaker(name, **kwargs)

def get_structured_logger(name: str, **kwargs):
    from agent.utils.structured_log import setup_logging
    return setup_logging(name, **kwargs)
