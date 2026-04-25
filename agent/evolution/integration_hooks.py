"""NeoMind Integration Hooks — Wire Phase 5-7 modules into the main loop.

This is the single integration point for all research-enhanced modules.
Three hooks are called from the main flow:

1. pre_llm_call()   — Before sending request to LLM API
                      → Degradation check, distillation attempt, output token limits
2. post_response()  — After receiving LLM response
                      → Drift recording, KG learning, exemplar storage, AgentSpec check
3. periodic_tasks() — Called by evolution_scheduler every N turns
                      → Drift detection, KG cluster discovery, distillation cleanup

Design principles:
  - Every hook is wrapped in try/except — NEVER blocks the main response loop
  - All modules are lazy-loaded — no import cost if unused
  - Each hook returns a dict of results (for logging/debugging)
  - Thread-safe: no shared mutable state between hooks

No external dependencies — stdlib only.
"""

import time
import logging
from typing import Dict, Any, Optional, Tuple
from pathlib import Path

from agent.constants.models import DEFAULT_MODEL, PREMIUM_MODEL

logger = logging.getLogger(__name__)

# ── Lazy module singletons ─────────────────────────────────────

_degradation_mgr = None
_distillation_engine = None
_knowledge_graph = None
_drift_detector = None
_agent_spec = None
_debate_consensus = None
_cost_optimizer = None


def _get_degradation():
    global _degradation_mgr
    if _degradation_mgr is None:
        try:
            from agent.utils.degradation import get_degradation_manager
            _degradation_mgr = get_degradation_manager()
        except Exception as e:
            logger.debug(f"Degradation manager unavailable: {e}")
    return _degradation_mgr


def _get_distillation():
    global _distillation_engine
    if _distillation_engine is None:
        try:
            from agent.evolution.distillation import get_distillation_engine
            _distillation_engine = get_distillation_engine()
        except Exception as e:
            logger.debug(f"Distillation engine unavailable: {e}")
    return _distillation_engine


def _get_knowledge_graph():
    global _knowledge_graph
    if _knowledge_graph is None:
        try:
            from agent.evolution.knowledge_graph import get_knowledge_graph
            _knowledge_graph = get_knowledge_graph()
        except Exception as e:
            logger.debug(f"Knowledge graph unavailable: {e}")
    return _knowledge_graph


def _get_drift_detector():
    global _drift_detector
    if _drift_detector is None:
        try:
            from agent.evolution.drift_detector import DriftDetector
            _drift_detector = DriftDetector()
        except Exception as e:
            logger.debug(f"Drift detector unavailable: {e}")
    return _drift_detector


def _get_agent_spec():
    global _agent_spec
    if _agent_spec is None:
        try:
            from agent.evolution.agentspec import get_agent_spec
            _agent_spec = get_agent_spec()
        except Exception as e:
            logger.debug(f"AgentSpec unavailable: {e}")
    return _agent_spec


def _get_debate():
    global _debate_consensus
    if _debate_consensus is None:
        try:
            from agent.evolution.debate_consensus import DebateConsensus
            _debate_consensus = DebateConsensus()
        except Exception as e:
            logger.debug(f"Debate consensus unavailable: {e}")
    return _debate_consensus


def _get_cost_optimizer():
    global _cost_optimizer
    if _cost_optimizer is None:
        try:
            from agent.evolution.cost_optimizer import CostOptimizer
            _cost_optimizer = CostOptimizer()
        except Exception as e:
            logger.debug(f"Cost optimizer unavailable: {e}")
    return _cost_optimizer


# ═══════════════════════════════════════════════════════════════
# Hook 1: PRE-LLM CALL
# Called right before the API request is sent.
# Returns modifications to the request (or None to proceed normally).
# ═══════════════════════════════════════════════════════════════

def pre_llm_call(
    prompt: str,
    mode: str = "chat",
    model: Optional[str] = None,
    max_tokens: int = 4096,
    **kwargs,
) -> Dict[str, Any]:
    """Pre-processing before LLM API call.

    Checks:
    1. Degradation tier → if STATIC, return cached response instead of calling API
    2. Distillation → if exemplar available, build enhanced prompt for cheap model
    3. Output token limit → enforce per-mode budget

    Args:
        prompt: User's input text
        mode: Current agent mode (chat/coding/fin)
        model: Target LLM model name
        max_tokens: Requested max output tokens

    Returns:
        Dict with keys:
        - skip_api: bool — True if should NOT call API (use fallback instead)
        - fallback_response: str — Static response if skip_api=True
        - modified_prompt: str — Enhanced prompt (e.g., with distillation exemplar)
        - adjusted_max_tokens: int — Adjusted output token limit
        - distillation_used: bool — Whether distillation prompt was injected
        - tier: str — Current degradation tier
    """
    result = {
        "skip_api": False,
        "fallback_response": None,
        "modified_prompt": prompt,
        "adjusted_max_tokens": max_tokens,
        "distillation_used": False,
        "tier": "live",
    }

    # ── 1. Degradation check ────────────────────────────────────
    try:
        dm = _get_degradation()
        if dm:
            result["tier"] = dm.current_tier.value
            if dm.current_tier.value == "static":
                # Don't call API — use static fallback
                fallback = dm.get_static_fallback(mode)
                if fallback:
                    result["skip_api"] = True
                    result["fallback_response"] = fallback
                    logger.info(f"[hooks] STATIC tier — returning fallback for {mode}")
                    return result
    except Exception as e:
        logger.debug(f"[hooks] Degradation check error: {e}")

    # ── 2. Distillation: try cheap model with exemplar ──────────
    try:
        engine = _get_distillation()
        if engine and mode in ("fin", "chat"):
            # Detect task type from mode/prompt
            task_type = _infer_task_type(prompt, mode)
            if task_type and engine.should_try_distillation(task_type):
                exemplar = engine.get_best_exemplar(task_type)
                if exemplar:
                    distilled = engine.build_distilled_prompt(prompt, exemplar)
                    result["modified_prompt"] = distilled
                    result["distillation_used"] = True
                    result["_task_type"] = task_type
                    result["_exemplar_id"] = exemplar.get("id")
                    logger.info(f"[hooks] Distillation: injected exemplar for {task_type}")
    except Exception as e:
        logger.debug(f"[hooks] Distillation check error: {e}")

    # ── 3. Output token limits ──────────────────────────────────
    try:
        optimizer = _get_cost_optimizer()
        if optimizer:
            limit = optimizer.get_output_limit(mode)
            if limit and limit < result["adjusted_max_tokens"]:
                result["adjusted_max_tokens"] = limit
                logger.debug(f"[hooks] Output limit for {mode}: {limit}")
    except Exception as e:
        logger.debug(f"[hooks] Token limit check error: {e}")

    return result


# ═══════════════════════════════════════════════════════════════
# Hook 2: POST-RESPONSE
# Called after LLM response is received and added to history.
# Records metrics and triggers lightweight learning.
# ═══════════════════════════════════════════════════════════════

def post_response(
    prompt: str,
    response: str,
    mode: str = "chat",
    model: Optional[str] = None,
    latency_ms: float = 0,
    tokens_used: int = 0,
    cost_usd: float = 0,
    success: bool = True,
    pre_call_result: Optional[Dict] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Post-processing after LLM response.

    Actions:
    1. Drift detector → record response metrics
    2. Degradation → update API success/failure stats
    3. Distillation → if good response, store as exemplar
    4. Knowledge graph → (lightweight) tag for later connection

    Args:
        prompt: Original user prompt
        response: LLM's response text
        mode: Agent mode
        model: Model that was used
        latency_ms: Response latency in milliseconds
        tokens_used: Total tokens consumed
        cost_usd: Estimated cost in USD
        success: Whether the response was successful
        pre_call_result: Result from pre_llm_call (for distillation tracking)

    Returns:
        Dict with recorded actions
    """
    actions = []
    pcr = pre_call_result or {}

    # ── 1. Drift detector: record metrics ───────────────────────
    try:
        detector = _get_drift_detector()
        if detector:
            detector.record("response_latency_ms", latency_ms, mode)
            detector.record("output_tokens_per_request", float(tokens_used), mode)
            detector.record("task_success_rate", 1.0 if success else 0.0, mode)
            if cost_usd > 0:
                detector.record("cost_per_request", cost_usd, mode)
            actions.append("drift_metrics_recorded")
    except Exception as e:
        logger.debug(f"[hooks] Drift recording error: {e}")

    # ── 2. Degradation: update health status ────────────────────
    try:
        dm = _get_degradation()
        if dm:
            if not success:
                # Record failure for auto-degrade calculation
                dm.check_and_auto_degrade(api_failure_rate=0.3)
            elif dm.is_degraded:
                # Try to recover if in degraded state and response succeeded
                dm.recover()
                actions.append("degradation_recovery_attempted")
    except Exception as e:
        logger.debug(f"[hooks] Degradation update error: {e}")

    # ── 3. Distillation: store good responses as exemplars ──────
    try:
        engine = _get_distillation()
        if engine and success and len(response) > 100:
            task_type = pcr.get("_task_type") or _infer_task_type(prompt, mode)
            was_distilled = pcr.get("distillation_used", False)

            if was_distilled:
                # Record the distillation attempt result
                quality = _estimate_quality(response, mode)
                engine.record_attempt(
                    task_type=task_type,
                    model_used=model,
                    quality_score=quality,
                    cost_usd=cost_usd,
                    tokens_used=tokens_used,
                    was_distilled=True,
                    exemplar_id=pcr.get("_exemplar_id"),
                )
                actions.append(f"distillation_attempt_recorded(q={quality:.2f})")
            elif not was_distilled and task_type:
                # Non-distilled good response from expensive model → store as exemplar
                quality = _estimate_quality(response, mode)
                if quality >= 0.8 and model == PREMIUM_MODEL:
                    engine.store_exemplar(
                        task_type=task_type,
                        prompt_summary=prompt[:200],
                        response=response[:3000],
                        model=model,
                        quality_score=quality,
                        mode=mode,
                    )
                    actions.append(f"exemplar_stored({task_type},q={quality:.2f})")
    except Exception as e:
        logger.debug(f"[hooks] Distillation storage error: {e}")

    return {"actions": actions}


# ═══════════════════════════════════════════════════════════════
# Hook 3: PERIODIC TASKS
# Called by evolution_scheduler every N turns (default: 50).
# Runs heavier analysis that shouldn't happen every turn.
# ═══════════════════════════════════════════════════════════════

def periodic_tasks(
    turn_number: int,
    mode: str = "chat",
    **kwargs,
) -> Dict[str, Any]:
    """Periodic maintenance tasks (every ~50 turns).

    Actions:
    1. Drift detection → full PSI check across all metrics
    2. Knowledge graph → discover clusters, suggest connections
    3. Distillation → cleanup old exemplars
    4. Degradation → evaluate and possibly auto-recover

    Returns:
        Dict with task results and any alerts
    """
    results = {}
    alerts = []

    # ── 1. Full drift check ─────────────────────────────────────
    try:
        detector = _get_drift_detector()
        if detector:
            report = detector.check_drift()
            overall = report.get("overall_status", "no_drift")
            results["drift"] = overall
            if overall in ("moderate_drift", "drift_detected"):
                drifted = [
                    m for m, v in report.get("metrics", {}).items()
                    if v.get("status") in ("moderate", "significant")
                ]
                alerts.append({
                    "type": "behavior_drift",
                    "severity": "high" if overall == "drift_detected" else "medium",
                    "metrics": drifted,
                })
                logger.warning(f"[hooks] Drift detected: {drifted}")

            # Re-compute baselines periodically
            for metric in report.get("metrics", {}):
                try:
                    detector.compute_baseline(metric)
                except Exception:
                    pass
    except Exception as e:
        logger.debug(f"[hooks] Drift check error: {e}")

    # ── 2. Knowledge graph maintenance ──────────────────────────
    try:
        kg = _get_knowledge_graph()
        if kg:
            clusters = kg.discover_clusters()
            results["kg_clusters"] = len(clusters)
            stats = kg.get_stats()
            results["kg_edges"] = stats.get("total_edges", 0)
    except Exception as e:
        logger.debug(f"[hooks] KG maintenance error: {e}")

    # ── 3. Distillation cleanup ─────────────────────────────────
    try:
        engine = _get_distillation()
        if engine:
            cleaned = engine.cleanup_old_exemplars(max_age_days=30)
            results["distillation_cleaned"] = cleaned
            report = engine.get_savings_report()
            results["distillation_savings"] = report.get("total_saved_usd", 0)
    except Exception as e:
        logger.debug(f"[hooks] Distillation cleanup error: {e}")

    # ── 4. Degradation health eval ──────────────────────────────
    try:
        dm = _get_degradation()
        if dm:
            results["tier"] = dm.current_tier.value
    except Exception as e:
        logger.debug(f"[hooks] Degradation eval error: {e}")

    if alerts:
        results["alerts"] = alerts

    return results


# ═══════════════════════════════════════════════════════════════
# Hook 4: SELF-EDIT GATE
# Called before any self-edit operation.
# Returns (allowed: bool, reason: str)
# ═══════════════════════════════════════════════════════════════

def self_edit_gate(
    file_path: str,
    new_content: str,
    old_content: str = "",
    reason: str = "",
    **kwargs,
) -> Tuple[bool, str]:
    """Safety gate for self-edit operations.

    Pipeline:
    1. AgentSpec rule check (fast, local)
    2. Debate consensus (4-viewpoint vote)

    Returns:
        (allowed: bool, reason: str)
    """
    # ── 1. AgentSpec ────────────────────────────────────────────
    try:
        spec = _get_agent_spec()
        if spec:
            from agent.evolution.agentspec import TriggerPoint
            violations = spec.check(TriggerPoint.PRE_EDIT, {
                "file_path": file_path,
                "new_content": new_content,
                "old_content": old_content,
                "reason": reason,
            })
            blocking = [v for v in violations if v.blocked]
            if blocking:
                rules = ", ".join(v.rule_name for v in blocking)
                return False, f"AgentSpec BLOCKED: {rules}"
            if violations:
                logger.warning(
                    f"[hooks] AgentSpec warnings: "
                    f"{', '.join(v.rule_name for v in violations)}"
                )
    except Exception as e:
        logger.debug(f"[hooks] AgentSpec check error: {e}")

    # ── 2. Debate consensus ─────────────────────────────────────
    try:
        debate = _get_debate()
        if debate:
            # Determine risk level from file path
            safety_files = {"guards.py", "safety", "agentspec", "compliance"}
            is_safety = any(s in file_path.lower() for s in safety_files)

            result = debate.deliberate({
                "description": reason or f"Self-edit: {file_path}",
                "risk_level": "critical" if is_safety else "medium",
                "changes_safety_files": is_safety,
                "file_path": file_path,
                "rollback_possible": True,
            })

            if result["decision"] == "block":
                blockers = result.get("blocked_by", [])
                return False, f"Debate BLOCKED by: {', '.join(blockers)}"
            elif result["decision"] == "reject":
                return False, f"Debate REJECTED (score={result['score']:.2f})"
    except Exception as e:
        logger.debug(f"[hooks] Debate check error: {e}")

    return True, "Approved"


# ═══════════════════════════════════════════════════════════════
# Helper functions
# ═══════════════════════════════════════════════════════════════

def _infer_task_type(prompt: str, mode: str) -> Optional[str]:
    """Infer distillation task type from prompt and mode."""
    prompt_lower = prompt.lower()

    if mode == "fin":
        if any(k in prompt_lower for k in ("财报", "earnings", "revenue", "eps")):
            return "financial_analysis"
        if any(k in prompt_lower for k in ("情绪", "sentiment", "看多", "看空")):
            return "sentiment_analysis"
        if any(k in prompt_lower for k in ("简报", "briefing", "市场", "概况")):
            return "market_briefing"
        return "financial_analysis"  # default for fin mode

    if mode == "coding":
        if any(k in prompt_lower for k in ("review", "审查", "检查")):
            return "code_review"
        return None  # coding tasks are too varied for distillation

    if mode == "chat":
        if any(k in prompt_lower for k in ("总结", "summarize", "提取", "extract")):
            return "learning_extraction"
        return None

    return None


def _estimate_quality(response: str, mode: str) -> float:
    """Quick heuristic quality estimate (0-1) without calling LLM.

    A real implementation would use the LLM or a fine-tuned classifier.
    This is a rough approximation based on structural signals.
    """
    score = 0.5  # baseline

    # Length bonus (up to 0.15)
    length = len(response)
    if length > 500:
        score += 0.05
    if length > 1000:
        score += 0.05
    if length > 2000:
        score += 0.05

    # Structure bonus (headers, lists, data points)
    if "##" in response or "**" in response:
        score += 0.05
    if any(c in response for c in ("1.", "2.", "3.", "- ")):
        score += 0.05

    # Mode-specific signals
    if mode == "fin":
        # Financial analysis should have numbers
        import re
        numbers = re.findall(r'\d+\.?\d*[%$BM]', response)
        if len(numbers) >= 3:
            score += 0.1
        if any(k in response for k in ("风险", "risk", "估值", "valuation")):
            score += 0.05

    if mode == "coding":
        if "```" in response:
            score += 0.1
        if any(k in response for k in ("def ", "class ", "function")):
            score += 0.05

    return min(1.0, score)
