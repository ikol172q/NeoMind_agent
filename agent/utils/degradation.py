"""NeoMind Graceful Degradation — Service Tier Management

Implements three-tier degradation strategy:
  Tier 1 (LIVE):   Full LLM calls, real-time data, all features
  Tier 2 (CACHE):  Serve from cache, no new LLM calls, stale data OK
  Tier 3 (STATIC): Pre-computed fallback responses, minimal functionality

Automatic tier transitions based on:
  - API failure rate (circuit breaker state)
  - Memory pressure (cgroup monitor)
  - Budget exhaustion (cost optimizer)
  - Manual override

Research source: Round 5 — single failure point should not cause total unavailability.

No external dependencies — stdlib only.
"""

import enum
import json
import logging
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, Callable, List

logger = logging.getLogger(__name__)

# Static fallback directory
STATIC_FALLBACK_DIR = Path("/data/neomind/fallback")


class ServiceTier(enum.Enum):
    """Service degradation tiers."""
    LIVE = "live"         # Full functionality
    CACHE = "cache"       # Cache-only mode
    STATIC = "static"     # Static fallback mode


class DegradationReason(enum.Enum):
    """Reasons for degradation."""
    API_FAILURE = "api_failure"
    MEMORY_PRESSURE = "memory_pressure"
    BUDGET_EXHAUSTED = "budget_exhausted"
    MANUAL = "manual"
    CIRCUIT_OPEN = "circuit_open"


class DegradationManager:
    """Manages service tier transitions and fallback behavior.

    Usage:
        mgr = DegradationManager()

        # Check current tier before making LLM call
        if mgr.current_tier == ServiceTier.LIVE:
            response = call_llm(prompt)
        elif mgr.current_tier == ServiceTier.CACHE:
            response = cache.get(prompt) or mgr.get_static_fallback(mode)
        else:
            response = mgr.get_static_fallback(mode)
    """

    def __init__(self):
        self._current_tier = ServiceTier.LIVE
        self._reason: Optional[DegradationReason] = None
        self._degraded_at: Optional[str] = None
        self._lock = threading.Lock()
        self._history: List[Dict[str, Any]] = []
        self._static_responses: Dict[str, str] = {}
        self._load_static_fallbacks()

    @property
    def current_tier(self) -> ServiceTier:
        """Get current service tier."""
        return self._current_tier

    @property
    def is_degraded(self) -> bool:
        """Check if service is in degraded state."""
        return self._current_tier != ServiceTier.LIVE

    def degrade_to(self, tier: ServiceTier, reason: DegradationReason) -> None:
        """Transition to a lower service tier.

        Only allows degradation (lower tiers), never auto-upgrades.
        Use recover() to return to LIVE.

        Args:
            tier: Target tier
            reason: Why degradation is happening
        """
        with self._lock:
            if tier.value >= self._current_tier.value and tier != ServiceTier.LIVE:
                # Already at this tier or lower, skip
                if self._current_tier == tier:
                    return

            old_tier = self._current_tier
            self._current_tier = tier
            self._reason = reason
            self._degraded_at = datetime.now(timezone.utc).isoformat()

            event = {
                "from": old_tier.value,
                "to": tier.value,
                "reason": reason.value,
                "ts": self._degraded_at,
            }
            self._history.append(event)

            # Keep history bounded
            if len(self._history) > 100:
                self._history = self._history[-50:]

            logger.warning(
                f"Service degraded: {old_tier.value} → {tier.value} "
                f"(reason: {reason.value})"
            )

    def recover(self) -> bool:
        """Attempt to recover to LIVE tier.

        Returns:
            True if recovered, False if recovery conditions not met
        """
        with self._lock:
            if self._current_tier == ServiceTier.LIVE:
                return True

            old_tier = self._current_tier
            self._current_tier = ServiceTier.LIVE
            self._reason = None

            event = {
                "from": old_tier.value,
                "to": "live",
                "reason": "recovery",
                "ts": datetime.now(timezone.utc).isoformat(),
            }
            self._history.append(event)

            logger.info(f"Service recovered: {old_tier.value} → live")
            return True

    def get_static_fallback(self, mode: str) -> str:
        """Get pre-computed static fallback response for a mode.

        Args:
            mode: Agent personality mode (chat, fin, coding)

        Returns:
            Static fallback message
        """
        if mode in self._static_responses:
            return self._static_responses[mode]

        fallbacks = {
            "chat": "I'm currently operating in limited mode due to a temporary issue. "
                    "I can still help with basic questions. Please try again in a few minutes "
                    "for full functionality.",
            "fin": "Financial analysis is temporarily limited. "
                   "Markets data may be delayed. Key indices are available in the daily briefing. "
                   "Full analysis will resume shortly.",
            "coding": "Code assistance is temporarily limited. "
                      "I can help with simple questions but complex code generation "
                      "requires full service. Please try again shortly.",
        }
        return fallbacks.get(mode, fallbacks["chat"])

    def get_status(self) -> Dict[str, Any]:
        """Get current degradation status."""
        return {
            "tier": self._current_tier.value,
            "is_degraded": self.is_degraded,
            "reason": self._reason.value if self._reason else None,
            "degraded_at": self._degraded_at,
            "history_count": len(self._history),
            "recent_events": self._history[-5:] if self._history else [],
        }

    def check_and_auto_degrade(
        self,
        api_failure_rate: float = 0.0,
        memory_usage_pct: float = 0.0,
        budget_remaining: float = float('inf'),
        circuit_breaker_open: bool = False,
    ) -> ServiceTier:
        """Evaluate conditions and auto-degrade if needed.

        Called periodically by the health monitor / scheduler.

        Args:
            api_failure_rate: Recent API failure rate (0.0-1.0)
            memory_usage_pct: Memory usage percentage (0-100)
            budget_remaining: Remaining daily budget in USD
            circuit_breaker_open: Whether circuit breaker is open

        Returns:
            Current tier after evaluation
        """
        # Circuit breaker open → CACHE mode
        if circuit_breaker_open:
            self.degrade_to(ServiceTier.CACHE, DegradationReason.CIRCUIT_OPEN)
            return self._current_tier

        # High API failure rate → CACHE mode
        if api_failure_rate > 0.5:
            self.degrade_to(ServiceTier.CACHE, DegradationReason.API_FAILURE)
            return self._current_tier

        # Critical memory → STATIC mode (most aggressive)
        if memory_usage_pct > 95:
            self.degrade_to(ServiceTier.STATIC, DegradationReason.MEMORY_PRESSURE)
            return self._current_tier

        # High memory → CACHE mode
        if memory_usage_pct > 85:
            self.degrade_to(ServiceTier.CACHE, DegradationReason.MEMORY_PRESSURE)
            return self._current_tier

        # Budget exhausted → CACHE mode (use cached responses only)
        if budget_remaining <= 0:
            self.degrade_to(ServiceTier.CACHE, DegradationReason.BUDGET_EXHAUSTED)
            return self._current_tier

        # All clear → try to recover if we were degraded
        if self.is_degraded and api_failure_rate < 0.1 and memory_usage_pct < 70:
            self.recover()

        return self._current_tier

    def _load_static_fallbacks(self) -> None:
        """Load pre-computed static fallback responses from disk."""
        fallback_file = STATIC_FALLBACK_DIR / "responses.json"
        try:
            if fallback_file.exists():
                with open(fallback_file) as f:
                    self._static_responses = json.load(f)
                logger.debug(f"Loaded {len(self._static_responses)} static fallbacks")
        except Exception as e:
            logger.debug(f"No static fallbacks loaded: {e}")

    def save_static_fallback(self, mode: str, response: str) -> None:
        """Save a response as static fallback for future degraded operation.

        Called when a good response is generated — caches it for degraded mode.

        Args:
            mode: Agent mode
            response: The response to cache as fallback
        """
        self._static_responses[mode] = response
        try:
            STATIC_FALLBACK_DIR.mkdir(parents=True, exist_ok=True)
            fallback_file = STATIC_FALLBACK_DIR / "responses.json"
            with open(fallback_file, "w") as f:
                json.dump(self._static_responses, f, indent=2)
        except Exception as e:
            logger.debug(f"Cannot save static fallback: {e}")


# Global singleton
_manager: Optional[DegradationManager] = None


def get_degradation_manager() -> DegradationManager:
    """Get or create the global DegradationManager singleton."""
    global _manager
    if _manager is None:
        _manager = DegradationManager()
    return _manager
