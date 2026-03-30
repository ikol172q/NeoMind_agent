"""NeoMind Circuit Breaker — Prevent cascading API failures.

Three states: CLOSED (normal), OPEN (all calls fail-fast), HALF_OPEN (test one call).
Transitions: CLOSED→OPEN after N failures, OPEN→HALF_OPEN after timeout, HALF_OPEN→CLOSED on success.

No external dependencies — stdlib only.
"""

import time
import logging
import threading
from enum import Enum
from datetime import datetime, timezone, timedelta
from typing import Callable, Any, Optional, Dict
from functools import wraps

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject fast
    HALF_OPEN = "half_open"  # Testing recovery


class CircuitBreakerException(Exception):
    """Raised when circuit breaker is OPEN."""

    pass


class CircuitBreaker:
    """Prevent cascading API failures with circuit breaker pattern.

    Configuration:
        failure_threshold: Number of failures before opening (default: 5)
        recovery_timeout: Seconds before attempting recovery (default: 60)
        half_open_max: Max calls to test in HALF_OPEN state (default: 1)
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        half_open_max: int = 1,
    ):
        """Initialize circuit breaker.

        Args:
            name: Identifier for this breaker (e.g., "openai_api")
            failure_threshold: Failures before opening
            recovery_timeout: Seconds before HALF_OPEN test
            half_open_max: Max simultaneous test calls in HALF_OPEN
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max = half_open_max

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[datetime] = None
        self._half_open_calls = 0
        self._lock = threading.RLock()

    # ── State Management ───────────────────────────────────

    @property
    def state(self) -> str:
        """Get current state (closed, open, or half_open)."""
        with self._lock:
            if self._state == CircuitState.OPEN:
                # Check if recovery timeout has elapsed
                if self._last_failure_time:
                    elapsed = (
                        datetime.now(timezone.utc) - self._last_failure_time
                    ).total_seconds()
                    if elapsed >= self.recovery_timeout:
                        self._state = CircuitState.HALF_OPEN
                        self._half_open_calls = 0
                        logger.info(
                            f"[{self.name}] Circuit breaker: OPEN → HALF_OPEN "
                            f"(recovery timeout elapsed)"
                        )

            return self._state.value

    def _record_success(self) -> None:
        """Record a successful call."""
        with self._lock:
            self._failure_count = 0
            self._success_count += 1

            if self._state == CircuitState.HALF_OPEN:
                if self._success_count >= 1:
                    self._state = CircuitState.CLOSED
                    self._success_count = 0
                    logger.info(
                        f"[{self.name}] Circuit breaker: HALF_OPEN → CLOSED "
                        f"(recovered)"
                    )

    def _record_failure(self) -> None:
        """Record a failed call."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = datetime.now(timezone.utc)

            if self._state == CircuitState.HALF_OPEN:
                # One failure in HALF_OPEN goes back to OPEN
                self._state = CircuitState.OPEN
                logger.warning(
                    f"[{self.name}] Circuit breaker: HALF_OPEN → OPEN "
                    f"(recovery test failed)"
                )
            elif (
                self._state == CircuitState.CLOSED
                and self._failure_count >= self.failure_threshold
            ):
                self._state = CircuitState.OPEN
                logger.warning(
                    f"[{self.name}] Circuit breaker: CLOSED → OPEN "
                    f"({self._failure_count} failures)"
                )

    # ── Call Wrapping ────────────────────────────────────

    def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute func with circuit breaker protection.

        Args:
            func: Callable to execute
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Result of func(*args, **kwargs)

        Raises:
            CircuitBreakerException: If circuit is OPEN
        """
        # Check state and fail-fast if OPEN
        if self.state == CircuitState.OPEN:
            raise CircuitBreakerException(
                f"[{self.name}] Circuit breaker is OPEN; failing fast"
            )

        # If HALF_OPEN, limit concurrent test calls
        if self.state == CircuitState.HALF_OPEN:
            with self._lock:
                if self._half_open_calls >= self.half_open_max:
                    raise CircuitBreakerException(
                        f"[{self.name}] HALF_OPEN: max test calls reached"
                    )
                self._half_open_calls += 1

        try:
            result = func(*args, **kwargs)
            self._record_success()
            return result
        except Exception as e:
            self._record_failure()
            raise


def retry_with_backoff(
    func: Callable,
    max_retries: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
) -> Any:
    """Execute func with exponential backoff retry.

    Args:
        func: Callable to execute
        max_retries: Maximum retry attempts (default: 5)
        base_delay: Initial delay in seconds (default: 1.0)
        max_delay: Maximum delay between retries (default: 60.0)

    Returns:
        Result of func() on success

    Raises:
        The last exception if all retries exhausted
    """
    delay = base_delay
    last_exception = None

    for attempt in range(max_retries + 1):
        try:
            return func()
        except Exception as e:
            last_exception = e
            if attempt < max_retries:
                logger.debug(
                    f"Retry {attempt + 1}/{max_retries} after {delay:.1f}s: {e}"
                )
                time.sleep(delay)
                # Exponential backoff: delay *= 2, capped at max_delay
                delay = min(delay * 2, max_delay)
            else:
                logger.error(
                    f"All {max_retries} retries exhausted for {func.__name__}"
                )

    raise last_exception


class CircuitBreakerRegistry:
    """Singleton registry for managing multiple circuit breakers.

    One breaker per API source (OpenAI, DeepSeek, etc.).
    """

    _instance: Optional["CircuitBreakerRegistry"] = None
    _lock = threading.Lock()
    _breakers: Dict[str, CircuitBreaker] = {}

    def __new__(cls) -> "CircuitBreakerRegistry":
        """Implement singleton pattern."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def get_breaker(
        cls,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
    ) -> CircuitBreaker:
        """Get or create a circuit breaker.

        Args:
            name: Breaker identifier
            failure_threshold: Failures before opening
            recovery_timeout: Recovery timeout in seconds

        Returns:
            CircuitBreaker instance
        """
        instance = cls()
        if name not in instance._breakers:
            instance._breakers[name] = CircuitBreaker(
                name,
                failure_threshold=failure_threshold,
                recovery_timeout=recovery_timeout,
            )
        return instance._breakers[name]

    @classmethod
    def get_all(cls) -> Dict[str, CircuitBreaker]:
        """Get all registered breakers."""
        instance = cls()
        return instance._breakers.copy()

    @classmethod
    def reset(cls, name: Optional[str] = None) -> None:
        """Reset one or all circuit breakers.

        Args:
            name: Specific breaker to reset, or None for all
        """
        instance = cls()
        if name:
            if name in instance._breakers:
                instance._breakers[name] = CircuitBreaker(
                    name,
                    failure_threshold=instance._breakers[name].failure_threshold,
                    recovery_timeout=instance._breakers[name].recovery_timeout,
                )
                logger.info(f"Reset circuit breaker: {name}")
        else:
            instance._breakers.clear()
            logger.info("Reset all circuit breakers")

    @classmethod
    def status(cls) -> Dict[str, str]:
        """Get status of all breakers."""
        instance = cls()
        return {name: breaker.state for name, breaker in instance._breakers.items()}
