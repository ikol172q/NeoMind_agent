"""
Structured signal schema for fin persona agent output (Phase 1).

Every analysis call the fin persona makes must return an ``AgentAnalysis``
instance — a Pydantic-validated structure with signal / confidence / reason
/ target_price / risk_level / sources. Free-text LLM output is parsed
through a three-layer fallback ladder:

  1. **Strict**: parse the LLM output as clean JSON, validate via Pydantic.
  2. **Lenient**: strip markdown code fences, allow extra fields, accept
     wider case on enum fields, coerce common confidence formats.
  3. **Conservative**: on failure, return a hold signal with confidence=1
     and the parse error as the reason. Logged but never crashes.

This matches the Round 2 decision in
``~/Desktop/Investment/plans/2026-04-11_neomind-investment-system-plan-v1.md``
(three-layer Agent output degradation). The layered recovery is the single
biggest fix against LLM hallucinated or malformed structured output.

Default model note: when this schema is used in prompts or docs that name
a model, the default is **DeepSeek reasoner** per the user directive on
2026-04-12 + the local LLM router in ``agent/services/llm_provider.py``.

Contract: plans/2026-04-12_fin_deepening_fusion_plan.md §4 Phase 1.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger(__name__)

__all__ = [
    "SignalType",
    "RiskLevel",
    "StockQuoteSchema",
    "AgentAnalysis",
    "AnalysisResult",
    "SignalParseError",
    "parse_signal",
    "parse_signal_strict",
    "hold_fallback",
]


SignalType = Literal["buy", "hold", "sell"]
RiskLevel = Literal["low", "medium", "high"]


# ── Pydantic models ─────────────────────────────────────────────────────


class StockQuoteSchema(BaseModel):
    """Structured quote used as input context for agent analysis."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str = Field(..., min_length=1, max_length=10)
    price: float = Field(..., ge=0)
    change_percent: float = 0.0
    currency: str = "USD"
    source: str = "unknown"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("symbol")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()


class AgentAnalysis(BaseModel):
    """Structured agent output for a single analysis call.

    Every fin persona analysis must return this shape. Validation is
    strict on the happy path; the ``parse_signal`` helper gives us a
    three-layer recovery ladder for LLM outputs that don't quite match.
    """

    model_config = ConfigDict(extra="forbid")

    signal: SignalType
    confidence: int = Field(..., ge=1, le=10)
    reason: str = Field(..., min_length=1, max_length=2000)
    target_price: Optional[float] = Field(None, ge=0)
    risk_level: RiskLevel = "medium"
    sources: List[str] = Field(default_factory=list)

    @field_validator("sources")
    @classmethod
    def _strip_empty_sources(cls, v: List[str]) -> List[str]:
        return [s.strip() for s in v if s and s.strip()]


class AnalysisResult(BaseModel):
    """Wraps a quote + analysis + metadata for persistence."""

    model_config = ConfigDict(extra="forbid")

    symbol: str
    quote: StockQuoteSchema
    analysis: AgentAnalysis
    model_used: str = "deepseek-reasoner"
    project_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Parse ladder ────────────────────────────────────────────────────────


class SignalParseError(ValueError):
    """Raised internally by the strict layer so the lenient layer can catch it."""


_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.DOTALL)
_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)

_SIGNAL_NORMALIZE = {
    "buy": "buy", "long": "buy", "bullish": "buy", "accumulate": "buy",
    "hold": "hold", "neutral": "hold", "wait": "hold", "watch": "hold",
    "sell": "sell", "short": "sell", "bearish": "sell", "reduce": "sell",
    "trim": "sell",
}

_RISK_NORMALIZE = {
    "low": "low", "l": "low", "small": "low", "minimal": "low",
    "medium": "medium", "mid": "medium", "moderate": "medium", "m": "medium",
    "high": "high", "h": "high", "large": "high", "elevated": "high",
}


def _extract_first_json_blob(text: str) -> Optional[str]:
    """Return the first plausible JSON object in *text*.

    Tries fenced code blocks first (``` ... ```), then a greedy ``{...}``.
    """
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    if not stripped:
        return None
    # If the entire stripped text is already a JSON object, use it.
    if stripped.startswith("{") and stripped.rstrip().endswith("}"):
        return stripped
    m = _FENCE_RE.search(stripped)
    if m:
        return m.group(1).strip()
    m = _OBJECT_RE.search(stripped)
    if m:
        return m.group(0).strip()
    return None


def _coerce_confidence(raw) -> Optional[int]:
    """Coerce confidence values like '7/10', '70%', '0.7', 7 into 1..10."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if 1 <= raw <= 10 else max(1, min(10, raw))
    if isinstance(raw, float):
        if 0 <= raw <= 1:
            return max(1, min(10, round(raw * 10)))
        return max(1, min(10, round(raw)))
    if isinstance(raw, str):
        s = raw.strip()
        m = re.match(r"^(\d+)\s*/\s*10$", s)
        if m:
            return max(1, min(10, int(m.group(1))))
        m = re.match(r"^(\d+(?:\.\d+)?)\s*%$", s)
        if m:
            pct = float(m.group(1))
            return max(1, min(10, round(pct / 10)))
        try:
            return _coerce_confidence(float(s))
        except ValueError:
            return None
    return None


def _normalize_enum(value, table, field_name: str) -> str:
    if not isinstance(value, str):
        raise SignalParseError(f"{field_name} must be a string, got {type(value).__name__}")
    key = value.strip().lower()
    if key in table:
        return table[key]
    raise SignalParseError(f"Unknown {field_name} value {value!r}")


def parse_signal_strict(raw_llm_output: str) -> AgentAnalysis:
    """Strict layer: input must be clean JSON and pass every Pydantic check.

    Raises ``SignalParseError`` on any failure. Caller typically wraps this
    in ``parse_signal`` which adds the lenient + conservative layers.
    """
    if not isinstance(raw_llm_output, str):
        raise SignalParseError("Input must be a string")
    try:
        data = json.loads(raw_llm_output.strip())
    except json.JSONDecodeError as exc:
        raise SignalParseError(f"Not valid JSON: {exc}") from exc
    try:
        return AgentAnalysis(**data)
    except Exception as exc:
        raise SignalParseError(f"Pydantic validation failed: {exc}") from exc


def _parse_signal_lenient(raw_llm_output: str) -> AgentAnalysis:
    """Lenient layer: extracts JSON from prose/fences, normalizes enums and
    confidence, drops unknown keys.
    """
    blob = _extract_first_json_blob(raw_llm_output)
    if blob is None:
        raise SignalParseError("No JSON object found in output")

    try:
        raw = json.loads(blob)
    except json.JSONDecodeError:
        # Minor repair: strip trailing commas and single-quote dict keys
        repaired = re.sub(r",\s*([}\]])", r"\1", blob)
        repaired = re.sub(r"'", '"', repaired)
        try:
            raw = json.loads(repaired)
        except json.JSONDecodeError as exc:
            raise SignalParseError(f"JSON still invalid after repair: {exc}") from exc

    if not isinstance(raw, dict):
        raise SignalParseError(f"Top-level must be object, got {type(raw).__name__}")

    # Case-insensitive key lookup helper
    def _get(*names, default=None):
        for n in names:
            if n in raw:
                return raw[n]
            for k in raw.keys():
                if isinstance(k, str) and k.lower() == n.lower():
                    return raw[k]
        return default

    signal_raw = _get("signal", "action", "recommendation")
    confidence_raw = _get("confidence", "conviction", "score")
    reason_raw = _get("reason", "rationale", "thesis", "explanation")
    target_raw = _get("target_price", "target", "price_target")
    risk_raw = _get("risk_level", "risk")
    sources_raw = _get("sources", "source", "citations", default=[])

    if signal_raw is None:
        raise SignalParseError("Missing required field 'signal'")
    if reason_raw is None or not str(reason_raw).strip():
        raise SignalParseError("Missing required field 'reason'")
    if confidence_raw is None:
        raise SignalParseError("Missing required field 'confidence'")

    signal_norm = _normalize_enum(signal_raw, _SIGNAL_NORMALIZE, "signal")
    confidence_norm = _coerce_confidence(confidence_raw)
    if confidence_norm is None:
        raise SignalParseError(f"Could not coerce confidence {confidence_raw!r} into 1..10")

    risk_norm: str = "medium"
    if risk_raw is not None:
        try:
            risk_norm = _normalize_enum(risk_raw, _RISK_NORMALIZE, "risk_level")
        except SignalParseError:
            risk_norm = "medium"  # silent fallback on unknown risk

    target_norm: Optional[float] = None
    if target_raw is not None and target_raw != "":
        try:
            target_norm = float(target_raw)
            if target_norm < 0:
                target_norm = None
        except (TypeError, ValueError):
            target_norm = None

    sources_list: List[str]
    if isinstance(sources_raw, str):
        sources_list = [sources_raw]
    elif isinstance(sources_raw, (list, tuple)):
        sources_list = [str(s) for s in sources_raw]
    else:
        sources_list = []

    return AgentAnalysis(
        signal=signal_norm,  # type: ignore[arg-type]
        confidence=confidence_norm,
        reason=str(reason_raw).strip()[:2000],
        target_price=target_norm,
        risk_level=risk_norm,  # type: ignore[arg-type]
        sources=sources_list,
    )


def hold_fallback(error_message: str, max_len: int = 200) -> AgentAnalysis:
    """Conservative hold signal used when every parse layer fails.

    Reason field encodes the failure so operators can trace it in the
    analysis log. Confidence is pinned at 1 and risk at 'high' so nobody
    mistakes the fallback for a real recommendation.
    """
    msg = (error_message or "unknown error").strip().replace("\n", " ")
    if len(msg) > max_len:
        msg = msg[: max_len - 3] + "..."
    return AgentAnalysis(
        signal="hold",
        confidence=1,
        reason=f"[parse_fallback] {msg}",
        target_price=None,
        risk_level="high",
        sources=[],
    )


def parse_signal(raw_llm_output: str) -> Tuple[AgentAnalysis, str]:
    """Parse LLM output into ``AgentAnalysis`` via a three-layer ladder.

    Returns ``(analysis, layer_used)`` where ``layer_used`` is one of
    ``"strict"``, ``"lenient"``, or ``"fallback"``. Callers interested in
    monitoring prompt drift should log the layer — rising
    lenient/fallback rates indicate the prompt needs attention.

    This function NEVER raises. Any input — including garbage — yields an
    ``AgentAnalysis`` (the fallback is a conservative hold).
    """
    try:
        return parse_signal_strict(raw_llm_output), "strict"
    except SignalParseError as strict_err:
        pass

    try:
        return _parse_signal_lenient(raw_llm_output), "lenient"
    except SignalParseError as lenient_err:
        logger.warning(
            "parse_signal: both strict and lenient layers failed, using hold_fallback. "
            "lenient_error=%s",
            lenient_err,
        )
        return hold_fallback(str(lenient_err)), "fallback"
    except Exception as exc:  # defensive: never crash the caller
        logger.exception("parse_signal: unexpected error in lenient layer")
        return hold_fallback(f"unexpected: {exc}"), "fallback"
