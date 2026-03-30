"""NeoMind Prompt Auto-Tuner — Metric-Driven YAML Parameter Tuning

Automatically optimizes NeoMind's per-mode system prompts based on user
feedback signals. Unlike full prompt rewriting, this tunes YAML config
parameters (temperature, response style, reasoning depth, etc.).

Three-stage pipeline:
  Stage 1: Signal collection (after each conversation)
  Stage 2: Variant generation (daily)
  Stage 3: A/B evaluation + adopt/rollback (weekly)

No external dependencies (no DSPy, TextGrad, etc.) — stdlib + PyYAML only.
"""

import copy
import json
import random
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, Tuple, Optional, List

logger = logging.getLogger(__name__)

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False
    logger.warning("PyYAML not available — prompt tuner will use JSON fallback")


class PromptTuner:
    """Three-stage prompt auto-tuner.

    Stage 1: Signal collection (per conversation)
    Stage 2: Variant generation (daily)
    Stage 3: Evaluation + adopt/rollback (weekly)
    """

    CONFIG_DIR = Path("/app/agent/config")
    TUNE_STATE = Path("/data/neomind/evolution/prompt_tune_state.json")

    # Search space for tunable parameters
    SEARCH_SPACE = {
        "temperature": {"type": "float", "min": 0.1, "max": 1.5, "step": 0.1},
        "max_tokens": {"type": "int", "min": 2048, "max": 16384, "step": 1024},
        "response_style": {"type": "choice", "options": ["concise", "balanced", "detailed"]},
        "language_preference": {"type": "choice", "options": ["auto", "zh", "en"]},
        "reasoning_depth": {"type": "choice", "options": ["shallow", "medium", "deep"]},
        "example_count": {"type": "int", "min": 0, "max": 5, "step": 1},
    }

    # Signal weights for composite scoring
    SIGNAL_WEIGHTS = {
        "user_satisfaction": 0.4,
        "task_completion": 0.3,
        "retry_rate": -0.2,       # Lower is better
        "response_length_ok": 0.1,
    }

    MIN_SIGNALS_FOR_EVAL = 20    # Need 20+ signals before evaluating
    IMPROVEMENT_THRESHOLD = 0.05  # 5% improvement required to adopt
    OPRO_MAX_HISTORY = 10        # Keep last 10 optimization attempts

    def __init__(self):
        self.TUNE_STATE.parent.mkdir(parents=True, exist_ok=True)
        self.state = self._load_state()
        self._ensure_opro_state()

    # ── Stage 1: Signal Collection ─────────────────────────

    def record_signal(self, mode: str, signal_type: str, value: float,
                      context: Optional[Dict] = None):
        """Record a quality signal after a conversation.

        Args:
            mode: Agent mode (chat, coding, fin)
            signal_type: One of:
                - "user_satisfaction": 0-1, inferred from feedback
                - "task_completion": 0 or 1
                - "retry_rate": 0-1, lower is better
                - "response_length_ok": 0 or 1
            value: Signal value
            context: Optional context dict
        """
        key = f"{mode}:{signal_type}"
        if key not in self.state["signals"]:
            self.state["signals"][key] = []

        self.state["signals"][key].append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "value": value,
            "context": context or {},
        })

        # Limit storage: max 200 per signal type
        if len(self.state["signals"][key]) > 200:
            self.state["signals"][key] = self.state["signals"][key][-200:]

        self._save_state()

    # ── Stage 2: Variant Generation (Daily) ────────────────

    def generate_variant(self, mode: str, use_opro: bool = False) -> Optional[Dict[str, Any]]:
        """Generate a parameter variant based on signal analysis or OPRO.

        Args:
            mode: Agent mode (chat, coding, fin)
            use_opro: If True, return OPRO prompt instead of rule-based variant
                     (caller sends to LLM, parses result, and applies)

        Strategy (rule-based):
        - High retry rate → deeper reasoning
        - Bad response length → adjust style
        - Low task completion → adjust temperature
        - High satisfaction → don't change
        - 10% random exploration

        Strategy (OPRO):
        - Returns optimization prompt for LLM to generate suggestions
        - Returns None (prompt is in return value)
        """
        if os.getenv("NEOMIND_SAFE_MODE") == "1":
            logger.info("Prompt tuning disabled in safe mode")
            return None

        config = self._load_config(mode)
        if not config or "tunable" not in config:
            logger.debug(f"No tunable section in {mode}.yaml — skipping")
            return None

        current = config["tunable"]

        # OPRO mode: return optimization prompt for LLM
        if use_opro:
            signals = self._aggregate_signals(mode)
            if not signals:
                logger.debug(f"No signals for OPRO in {mode}")
                return None
            prompt = self.generate_opro_optimization_prompt(mode, current, [])
            # Caller will send this prompt to LLM, parse result, and apply
            logger.info(f"Generated OPRO optimization prompt for {mode}")
            return {"_opro_prompt": prompt}

        # Rule-based variant generation
        variant = copy.deepcopy(current)

        # Analyze signals
        signals = self._aggregate_signals(mode)

        if not signals:
            logger.debug(f"No signals for mode {mode}")
            return None

        # Already performing well → don't change
        if signals.get("user_satisfaction", 0) > 0.8:
            logger.info(f"Mode {mode} satisfaction > 0.8 — no variant needed")
            return None

        # Rule-based adjustments
        changes_made = []

        if signals.get("retry_rate", 0) > 0.3:
            variant["reasoning_depth"] = "deep"
            changes_made.append("reasoning_depth→deep (high retry rate)")

        if signals.get("response_length_ok", 1) < 0.5:
            current_style = current.get("response_style", "balanced")
            if current_style == "detailed":
                variant["response_style"] = "balanced"
                changes_made.append("style: detailed→balanced")
            elif current_style == "balanced":
                variant["response_style"] = "concise"
                changes_made.append("style: balanced→concise")

        if signals.get("task_completion", 1) < 0.6:
            t = current.get("temperature", 0.7)
            variant["temperature"] = min(1.2, round(t + 0.1, 1))
            changes_made.append(f"temperature: {t}→{variant['temperature']}")

        # Random exploration (10% chance)
        if random.random() < 0.1:
            param = random.choice(list(self.SEARCH_SPACE.keys()))
            space = self.SEARCH_SPACE[param]
            old_val = variant.get(param)
            if space["type"] == "float":
                variant[param] = round(random.uniform(space["min"], space["max"]), 1)
            elif space["type"] == "int":
                variant[param] = random.randrange(
                    space["min"], space["max"] + 1, space["step"]
                )
            elif space["type"] == "choice":
                variant[param] = random.choice(space["options"])
            changes_made.append(f"random explore: {param} {old_val}→{variant[param]}")

        if not changes_made:
            return None

        # Store pending variant
        self.state["pending_variants"][mode] = {
            "variant": variant,
            "changes": changes_made,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "signals_at_creation": signals,
        }
        self._save_state()

        logger.info(f"Generated variant for {mode}: {changes_made}")
        return variant

    # ── Stage 3: Evaluation & Adoption (Weekly) ────────────

    def evaluate_and_adopt(self, mode: str) -> Tuple[bool, str]:
        """Compare variant vs current config performance, adopt if better.

        Only evaluates when enough new signals (≥20) have been collected.
        """
        pending = self.state["pending_variants"].get(mode)
        if not pending:
            return False, "No pending variant"

        # Check for sufficient data
        variant_created = pending["created_at"]
        new_signals = self._count_signals_after(mode, variant_created)

        if new_signals < self.MIN_SIGNALS_FOR_EVAL:
            return False, f"Insufficient data ({new_signals}/{self.MIN_SIGNALS_FOR_EVAL})"

        # Compare: variant period vs before
        before = pending["signals_at_creation"]
        after = self._aggregate_signals(mode, after=variant_created)

        before_score = self._composite_score(before)
        after_score = self._composite_score(after)

        if after_score > before_score + self.IMPROVEMENT_THRESHOLD:
            # Adopt: write to YAML
            config = self._load_config(mode)
            config["tunable"] = pending["variant"]
            self._save_config(mode, config)

            # Record adoption
            del self.state["pending_variants"][mode]
            self.state["adoption_history"].append({
                "mode": mode,
                "ts": datetime.now(timezone.utc).isoformat(),
                "before_score": round(before_score, 3),
                "after_score": round(after_score, 3),
                "changes": pending.get("changes", []),
                "adopted": pending["variant"],
            })
            self._save_state()

            msg = f"Adopted variant (score {before_score:.2f} → {after_score:.2f})"
            logger.info(f"Prompt tuner: {mode} — {msg}")
            return True, msg
        else:
            # Rollback: discard variant
            del self.state["pending_variants"][mode]
            self._save_state()

            msg = f"Variant not better ({before_score:.2f} → {after_score:.2f}), discarded"
            logger.info(f"Prompt tuner: {mode} — {msg}")
            return False, msg

    # ── OPRO-Style Prompt Self-Optimization ───────────────────

    def generate_opro_optimization_prompt(self, mode: str, current_params: Dict[str, Any],
                                          signal_history: List[Dict]) -> str:
        """Generate a prompt for LLM-guided parameter optimization (OPRO).

        Formats current parameters, recent signals, and past variants into a prompt
        that asks the LLM to suggest improved parameters based on performance patterns.

        Args:
            mode: Agent mode (chat, coding, fin)
            current_params: Current tunable parameter values
            signal_history: Recent signal data for context

        Returns:
            Optimization prompt string (caller sends to LLM)
        """
        # Aggregate recent signals
        recent_signals = self._aggregate_signals(mode)
        past_variants = self._get_optimization_history(mode, limit=5)

        prompt = f"""You are optimizing NeoMind's prompt parameters for the '{mode}' mode.

Current Parameters:
{self._format_params(current_params)}

Recent Performance Signals:
{self._format_signals(recent_signals)}

Search Space (constraints for your suggestions):
{self._format_search_space()}

Recent Optimization History (past attempts):
{self._format_optimization_history(past_variants)}

Based on performance patterns:
1. Identify which parameters are underperforming
2. Suggest specific parameter changes to improve outcomes
3. Explain your reasoning for each change
4. Ensure all suggested values respect the Search Space bounds

Respond with ONLY a JSON dict with keys "suggestions" (dict of param→value),
"reasoning" (string), and "expected_improvement" (float 0.0-1.0).
Example:
{{"suggestions": {{"temperature": 0.8, "reasoning_depth": "deep"}}, "reasoning": "...", "expected_improvement": 0.15}}
"""
        return prompt

    def parse_opro_suggestion(self, llm_output: str) -> Optional[Dict[str, Any]]:
        """Parse and validate LLM's suggested parameter changes.

        Extracts JSON from LLM output, validates against SEARCH_SPACE bounds,
        and returns validated variant dict.

        Args:
            llm_output: Raw LLM response (should contain JSON)

        Returns:
            Validated variant dict, or None if parsing/validation fails
        """
        # Extract JSON from response
        try:
            # Try parsing entire response first
            parsed = json.loads(llm_output)
        except json.JSONDecodeError:
            # Try extracting JSON from markdown code blocks or other text
            import re
            matches = re.findall(r'\{.*\}', llm_output, re.DOTALL)
            if not matches:
                logger.error(f"Could not find JSON in OPRO output: {llm_output}")
                return None
            try:
                parsed = json.loads(matches[-1])  # Use last match
            except json.JSONDecodeError:
                logger.error(f"Could not parse OPRO JSON: {matches[-1]}")
                return None

        if not isinstance(parsed, dict) or "suggestions" not in parsed:
            logger.error(f"OPRO response missing 'suggestions' key: {parsed}")
            return None

        suggestions = parsed.get("suggestions", {})
        if not isinstance(suggestions, dict):
            return None

        # Validate each suggestion against SEARCH_SPACE
        validated = {}
        for param, value in suggestions.items():
            if param not in self.SEARCH_SPACE:
                logger.warning(f"OPRO suggested unknown parameter: {param}")
                continue

            space = self.SEARCH_SPACE[param]
            space_type = space["type"]

            try:
                if space_type == "float":
                    val = float(value)
                    val = max(space["min"], min(space["max"], val))  # Clamp
                    validated[param] = round(val, 1)

                elif space_type == "int":
                    val = int(value)
                    val = max(space["min"], min(space["max"], val))  # Clamp
                    validated[param] = val

                elif space_type == "choice":
                    if value not in space["options"]:
                        logger.warning(f"OPRO suggested invalid choice for {param}: {value}")
                        continue
                    validated[param] = value

            except (ValueError, TypeError):
                logger.warning(f"Could not validate OPRO suggestion {param}={value}")
                continue

        if not validated:
            logger.error("OPRO suggestions yielded no valid parameters")
            return None

        logger.info(f"OPRO parsed suggestions: {validated}")
        return validated

    def get_optimization_history(self, mode: str, limit: int = 10) -> List[Dict]:
        """Return recent optimization attempts with outcomes.

        Used by OPRO to learn from past successes/failures.

        Args:
            mode: Agent mode
            limit: Max history entries to return

        Returns:
            List of optimization records with variants and results
        """
        return self._get_optimization_history(mode, limit)

    # ── Status & Reporting ─────────────────────────────────

    def get_status(self) -> Dict[str, Any]:
        """Return current tuning status for dashboard."""
        return {
            "pending_variants": {
                mode: {
                    "changes": v.get("changes", []),
                    "created_at": v.get("created_at"),
                }
                for mode, v in self.state["pending_variants"].items()
            },
            "total_adoptions": len(self.state["adoption_history"]),
            "recent_adoptions": self.state["adoption_history"][-5:],
            "signal_counts": {
                key: len(vals)
                for key, vals in self.state["signals"].items()
            },
        }

    def get_current_tunable(self, mode: str) -> Optional[Dict]:
        """Get current tunable parameters for a mode."""
        config = self._load_config(mode)
        if config:
            return config.get("tunable")
        return None

    # ── Internal Helpers ───────────────────────────────────

    def _ensure_opro_state(self):
        """Ensure optimization_history exists in state."""
        if "optimization_history" not in self.state:
            self.state["optimization_history"] = {}

    def _get_optimization_history(self, mode: str, limit: int = 10) -> List[Dict]:
        """Retrieve optimization attempts for a mode."""
        if "optimization_history" not in self.state:
            return []
        history = self.state.get("optimization_history", {}).get(mode, [])
        return history[-limit:] if history else []

    def _format_params(self, params: Dict[str, Any]) -> str:
        """Format parameters for OPRO prompt."""
        lines = []
        for key, value in params.items():
            lines.append(f"  {key}: {value}")
        return "\n".join(lines) if lines else "  (none)"

    def _format_signals(self, signals: Dict[str, float]) -> str:
        """Format signal averages for OPRO prompt."""
        if not signals:
            return "  (no recent signals)"
        lines = []
        for key, value in signals.items():
            lines.append(f"  {key}: {value:.3f}")
        return "\n".join(lines)

    def _format_search_space(self) -> str:
        """Format search space bounds for OPRO prompt."""
        lines = []
        for param, space in self.SEARCH_SPACE.items():
            space_type = space.get("type", "unknown")
            if space_type == "float":
                lines.append(f"  {param}: float [{space['min']}, {space['max']}] step {space.get('step', 0.1)}")
            elif space_type == "int":
                lines.append(f"  {param}: int [{space['min']}, {space['max']}] step {space.get('step', 1)}")
            elif space_type == "choice":
                options = ", ".join(space.get("options", []))
                lines.append(f"  {param}: choice of [{options}]")
        return "\n".join(lines)

    def _format_optimization_history(self, history: List[Dict]) -> str:
        """Format past optimization attempts for OPRO context."""
        if not history:
            return "  (no previous attempts)"
        lines = []
        for i, attempt in enumerate(history, 1):
            variant = attempt.get("variant", {})
            score = attempt.get("score", "N/A")
            lines.append(f"  Attempt {i}: {variant} → score {score}")
        return "\n".join(lines)

    def _aggregate_signals(self, mode: str, after: str = None) -> Dict[str, float]:
        """Aggregate signals into per-type averages."""
        result = {}
        for key, records in self.state["signals"].items():
            if not key.startswith(f"{mode}:"):
                continue
            signal_type = key.split(":", 1)[1]
            filtered = records
            if after:
                filtered = [r for r in records if r["ts"] > after]
            if filtered:
                result[signal_type] = sum(r["value"] for r in filtered) / len(filtered)
        return result

    def _composite_score(self, signals: Dict[str, float]) -> float:
        """Weighted composite score from signal averages."""
        score = 0.0
        for key, weight in self.SIGNAL_WEIGHTS.items():
            if key in signals:
                score += signals[key] * weight
        return score

    def _count_signals_after(self, mode: str, after: str) -> int:
        """Count signals collected after a timestamp."""
        count = 0
        for key, records in self.state["signals"].items():
            if key.startswith(f"{mode}:"):
                count += sum(1 for r in records if r["ts"] > after)
        return count

    def _load_config(self, mode: str) -> Optional[Dict]:
        """Load YAML config for a mode."""
        path = self.CONFIG_DIR / f"{mode}.yaml"
        if not path.exists():
            return None
        try:
            if HAS_YAML:
                with open(path) as f:
                    return yaml.safe_load(f)
            else:
                # JSON fallback
                json_path = path.with_suffix(".json")
                if json_path.exists():
                    return json.loads(json_path.read_text())
                return None
        except Exception as e:
            logger.error(f"Failed to load config {path}: {e}")
            return None

    def _save_config(self, mode: str, config: Dict):
        """Save YAML config for a mode (atomic write)."""
        path = self.CONFIG_DIR / f"{mode}.yaml"
        try:
            tmp = path.with_suffix(".yaml.tmp")
            if HAS_YAML:
                with open(tmp, "w") as f:
                    yaml.dump(config, f, allow_unicode=True,
                              default_flow_style=False, sort_keys=False)
            else:
                tmp = path.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(config, ensure_ascii=False, indent=2))
            tmp.replace(path)
            logger.info(f"Config saved: {path}")
        except Exception as e:
            logger.error(f"Failed to save config {path}: {e}")

    def _load_state(self) -> Dict:
        """Load tuner state from JSON."""
        if self.TUNE_STATE.exists():
            try:
                return json.loads(self.TUNE_STATE.read_text())
            except Exception as e:
                logger.error(f"Failed to load tune state: {e}")
        return {
            "signals": {},
            "pending_variants": {},
            "adoption_history": [],
            "optimization_history": {},
        }

    def _save_state(self):
        """Save tuner state atomically."""
        try:
            tmp = self.TUNE_STATE.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.state, ensure_ascii=False, indent=2))
            tmp.replace(self.TUNE_STATE)
        except Exception as e:
            logger.error(f"Failed to save tune state: {e}")


# ── DSPy-Inspired Signature Optimization ──────────────────────────
# Research: Round 3 — DSPy defines LLM tasks as signatures (input→output)
# and automatically optimizes the prompt structure and demonstrations.


@dataclass
class SignatureField:
    """A typed field in a DSPy-style signature."""
    name: str
    description: str
    field_type: str = "str"  # str, int, float, list, json
    required: bool = True
    prefix: str = ""  # Optional prefix in prompt (e.g., "Context:")


@dataclass
class Signature:
    """DSPy-style task signature: typed input→output specification.

    Example:
        sig = Signature(
            name="extract_learnings",
            instruction="Extract actionable learnings from a conversation",
            input_fields=[
                SignatureField("conversation", "The conversation text"),
                SignatureField("mode", "Agent personality mode"),
            ],
            output_fields=[
                SignatureField("learnings", "JSON array of learnings", field_type="json"),
            ],
            demonstrations=[
                {"conversation": "...", "mode": "chat", "learnings": "[...]"},
            ],
        )
    """
    name: str
    instruction: str
    input_fields: List[SignatureField]
    output_fields: List[SignatureField]
    demonstrations: List[Dict[str, Any]] = field(default_factory=list)
    max_demonstrations: int = 3
    performance_score: float = 0.0
    call_count: int = 0


class SignatureOptimizer:
    """Manages and optimizes DSPy-style signatures for NeoMind's LLM tasks.

    Usage:
        optimizer = SignatureOptimizer()

        # Define a signature
        sig = Signature(
            name="extract_learnings",
            instruction="Extract learnings from conversation",
            input_fields=[...],
            output_fields=[...],
        )
        optimizer.register(sig)

        # Generate optimized prompt
        prompt = optimizer.compile("extract_learnings", {
            "conversation": "...",
            "mode": "chat",
        })

        # Record result quality
        optimizer.record_result("extract_learnings", score=0.85)
    """

    SIGNATURES_FILE = Path("/data/neomind/evolution/signatures.json")

    def __init__(self):
        self._signatures: Dict[str, Signature] = {}
        self._load_builtin_signatures()

    def register(self, sig: Signature) -> None:
        """Register a new signature."""
        self._signatures[sig.name] = sig
        logger.debug(f"Registered signature: {sig.name}")

    def compile(self, name: str, inputs: Dict[str, Any]) -> str:
        """Compile a signature into an optimized prompt.

        Generates a structured prompt with:
        1. Task instruction
        2. Demonstrations (few-shot examples)
        3. Input fields with values
        4. Output field specifications

        Args:
            name: Signature name
            inputs: Dict of input field values

        Returns:
            Compiled prompt string
        """
        sig = self._signatures.get(name)
        if not sig:
            raise ValueError(f"Unknown signature: {name}")

        parts = []

        # 1. Instruction
        parts.append(sig.instruction)
        parts.append("")

        # 2. Demonstrations (if any)
        if sig.demonstrations:
            parts.append("Examples:")
            for i, demo in enumerate(sig.demonstrations[:sig.max_demonstrations]):
                parts.append(f"\n--- Example {i+1} ---")
                for field in sig.input_fields:
                    if field.name in demo:
                        prefix = field.prefix or field.name.replace("_", " ").title()
                        parts.append(f"{prefix}: {demo[field.name]}")
                for field in sig.output_fields:
                    if field.name in demo:
                        prefix = field.prefix or field.name.replace("_", " ").title()
                        parts.append(f"{prefix}: {demo[field.name]}")
            parts.append("\n--- Your Turn ---")
            parts.append("")

        # 3. Input fields
        for field in sig.input_fields:
            value = inputs.get(field.name, "")
            if field.required and not value:
                logger.warning(f"Missing required input: {field.name} for {name}")
            prefix = field.prefix or field.name.replace("_", " ").title()
            parts.append(f"{prefix}: {value}")

        parts.append("")

        # 4. Output specification
        for field in sig.output_fields:
            prefix = field.prefix or field.name.replace("_", " ").title()
            type_hint = f" ({field.field_type})" if field.field_type != "str" else ""
            parts.append(f"{prefix}{type_hint}:")

        sig.call_count += 1
        return "\n".join(parts)

    def record_result(self, name: str, score: float) -> None:
        """Record performance score for a signature invocation.

        Uses exponential moving average to track signature quality.
        """
        sig = self._signatures.get(name)
        if sig:
            alpha = 0.3  # EMA smoothing factor
            sig.performance_score = (
                alpha * score + (1 - alpha) * sig.performance_score
            )

    def add_demonstration(self, name: str, demo: Dict[str, Any]) -> None:
        """Add a demonstration example to a signature.

        Keeps only the top-performing demonstrations up to max_demonstrations.
        """
        sig = self._signatures.get(name)
        if sig:
            sig.demonstrations.append(demo)
            if len(sig.demonstrations) > sig.max_demonstrations * 2:
                # Keep most recent
                sig.demonstrations = sig.demonstrations[-sig.max_demonstrations:]

    def get_stats(self) -> Dict[str, Any]:
        """Get signature performance statistics."""
        return {
            name: {
                "calls": sig.call_count,
                "performance": round(sig.performance_score, 3),
                "demonstrations": len(sig.demonstrations),
                "input_fields": len(sig.input_fields),
                "output_fields": len(sig.output_fields),
            }
            for name, sig in self._signatures.items()
        }

    def _load_builtin_signatures(self) -> None:
        """Load NeoMind's standard LLM task signatures."""

        # Signature: Learning extraction
        self.register(Signature(
            name="extract_learnings",
            instruction="Analyze the conversation and extract actionable learnings for future improvement. "
                       "Return 0-3 learnings as a JSON array.",
            input_fields=[
                SignatureField("conversation", "Conversation summary text", prefix="Conversation"),
                SignatureField("mode", "Agent personality mode (chat/coding/fin)", prefix="Mode"),
            ],
            output_fields=[
                SignatureField("learnings", "JSON array of learnings", field_type="json", prefix="Learnings JSON"),
            ],
            demonstrations=[
                {
                    "conversation": "User asked about Python async patterns, I explained await/async but missed mentioning asyncio.gather for parallel tasks",
                    "mode": "coding",
                    "learnings": '[{"type":"INSIGHT","category":"python_async","content":"Always mention asyncio.gather when explaining async patterns","importance":0.7}]',
                },
            ],
        ))

        # Signature: Reflection generation
        self.register(Signature(
            name="generate_reflection",
            instruction="Reflect on the recent interaction and identify areas for improvement. "
                       "Focus on what went well, what could be better, and specific action items.",
            input_fields=[
                SignatureField("interaction_summary", "Summary of recent interaction", prefix="Interaction"),
                SignatureField("metrics", "Performance metrics (response time, satisfaction)", prefix="Metrics"),
            ],
            output_fields=[
                SignatureField("reflection", "Structured reflection text", prefix="Reflection"),
                SignatureField("action_items", "Specific improvements to make", field_type="json", prefix="Actions"),
            ],
        ))

        # Signature: Financial briefing
        self.register(Signature(
            name="generate_briefing",
            instruction="Generate a concise market briefing from the provided data. "
                       "Focus on actionable insights and notable changes.",
            input_fields=[
                SignatureField("market_data", "Recent price data and changes", prefix="Market Data"),
                SignatureField("news", "Recent relevant news headlines", prefix="News"),
                SignatureField("macro", "Macro economic indicators", prefix="Macro"),
            ],
            output_fields=[
                SignatureField("briefing", "Market briefing text", prefix="Briefing"),
                SignatureField("key_events", "Top 3 events to watch", field_type="json", prefix="Key Events"),
                SignatureField("market_mood", "Overall market sentiment", prefix="Mood"),
            ],
        ))

        # Signature: OPRO optimization
        self.register(Signature(
            name="opro_optimize",
            instruction="You are an optimization expert. Given the current parameters, "
                       "performance history, and search space, suggest better parameter values.",
            input_fields=[
                SignatureField("current_params", "Current parameter values", field_type="json", prefix="Current"),
                SignatureField("history", "Past optimization attempts and scores", field_type="json", prefix="History"),
                SignatureField("search_space", "Valid ranges for each parameter", field_type="json", prefix="Bounds"),
            ],
            output_fields=[
                SignatureField("suggestion", "Suggested parameter values", field_type="json", prefix="Suggestion"),
                SignatureField("reasoning", "Why these values should work better", prefix="Reasoning"),
            ],
        ))
