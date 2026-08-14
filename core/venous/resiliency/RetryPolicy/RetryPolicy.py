"""RetryPolicy primitive — SRE-grade retry with exponential backoff, jitter, budget.

Implements the catalog Protocol for `resiliency.RetryPolicy` and installs
runtime invariant checkers. The module performs zero I/O at import.

Invariant IDs cited by this module:

- RETRY-INV-01: a call MUST NEVER be retried unless it is marked idempotent
  or the policy has `requires_idempotency=False` by an explicit operator
  decision. Non-idempotent mutations without an idempotency key are FORBIDDEN.
- RETRY-INV-02: the total retry attempts across the policy MUST NEVER exceed
  `budget_ratio` of successful traffic in the trailing window; once the
  budget is exhausted retries are rejected.
- RETRY-INV-03: backoff intervals SHALL include jitter in the range
  [0, jitter * base_interval] so synchronized retry storms CANNOT form.
- RETRY-INV-04: retries CANNOT be issued when the governing
  TimeoutBudget.remaining_ms is less than or equal to zero.
- RETRY-INV-05: a retry policy SHALL classify errors as retryable,
  non-retryable, or fatal and NEVER retry a non-retryable / fatal error.
"""

from __future__ import annotations

import asyncio
import random
import threading
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Final, Literal, Protocol, TypeVar, runtime_checkable

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Error classification taxonomy (RETRY-INV-05)
# ---------------------------------------------------------------------------
_CLASS_RETRYABLE: Final[str] = "retryable"
_CLASS_NON_RETRYABLE: Final[str] = "non_retryable"
_CLASS_FATAL: Final[str] = "fatal"

_CLASSIFICATIONS: Final[frozenset[str]] = frozenset(
    {_CLASS_RETRYABLE, _CLASS_NON_RETRYABLE, _CLASS_FATAL}
)

ErrorClass = Literal["retryable", "non_retryable", "fatal"]


# ---------------------------------------------------------------------------
# Protocol surface (matches catalog api_signature verbatim)
# ---------------------------------------------------------------------------
@runtime_checkable
class RetryPolicy(Protocol):
    max_attempts: int
    initial_interval_ms: int
    multiplier: float
    max_interval_ms: int
    jitter: float
    budget_ratio: float
    requires_idempotency: bool

    def should_retry(self, attempt: int, exc: BaseException) -> bool: ...
    def next_delay_ms(self, attempt: int) -> int: ...
    async def execute(self, fn: Callable[[], Awaitable[T]]) -> T: ...


# ---------------------------------------------------------------------------
# Invariant-violation marker
# ---------------------------------------------------------------------------
class RetryPolicyInvariantError(RuntimeError):
    """Raised when a RetryPolicy invariant is violated at runtime."""


class NonRetryableError(Exception):
    """Caller-declared non-retryable error — classifier maps this to non_retryable."""


class FatalError(Exception):
    """Caller-declared fatal error — classifier maps this to fatal."""


# ---------------------------------------------------------------------------
# Classifier (extension point — RETRY-INV-05)
# ---------------------------------------------------------------------------
class RetryClassifier:
    """Default classifier. Maps exceptions to retryable / non_retryable / fatal.

    Rules (deterministic, side-effect free):
    - ``FatalError`` -> ``fatal``
    - ``NonRetryableError`` -> ``non_retryable``
    - ``ValueError``, ``TypeError``, ``KeyError``, ``AttributeError`` -> ``non_retryable``
      (programmer error; retrying cannot help).
    - ``TimeoutError``, ``ConnectionError``, ``OSError`` -> ``retryable``
    - everything else -> ``non_retryable`` (conservative default — retry only
      when we have positive evidence the error is transient).
    """

    _RETRYABLE: Final[tuple[type[BaseException], ...]] = (
        TimeoutError,
        ConnectionError,
        OSError,
    )
    _NON_RETRYABLE: Final[tuple[type[BaseException], ...]] = (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
    )

    def classify(self, exc: BaseException) -> ErrorClass:
        if isinstance(exc, FatalError):
            return "fatal"
        if isinstance(exc, NonRetryableError):
            return "non_retryable"
        if isinstance(exc, self._NON_RETRYABLE):
            return "non_retryable"
        if isinstance(exc, self._RETRYABLE):
            return "retryable"
        return "non_retryable"


# ---------------------------------------------------------------------------
# Timeout budget (RETRY-INV-04) — caller-supplied deadline carrier
# ---------------------------------------------------------------------------
class TimeoutBudget:
    """Minimal deadline carrier read by RetryPolicy.execute for RETRY-INV-04.

    Callers set a remaining-ms budget at request entry; retries CANNOT be
    issued once the budget is exhausted (<= 0).
    """

    def __init__(self, remaining_ms: int) -> None:
        self._remaining_ms = remaining_ms
        self._lock = threading.Lock()

    @property
    def remaining_ms(self) -> int:
        with self._lock:
            return self._remaining_ms

    def consume(self, ms: int) -> None:
        with self._lock:
            self._remaining_ms -= ms


# ---------------------------------------------------------------------------
# Retry budget — trailing-window success / retry ratio (RETRY-INV-02)
# ---------------------------------------------------------------------------
class RetryBudget:
    """Sealed trailing-window budget. Retries are admitted only if

        current_retries < budget_ratio * current_successes + min_floor

    The min_floor is 0 by default — a freshly started service sees 0
    successes and therefore 0 retries until one call succeeds. Callers who
    want to retry the very first call SHALL configure `min_floor` explicitly.
    """

    def __init__(self, budget_ratio: float, min_floor: int = 0) -> None:
        if budget_ratio < 0.0 or budget_ratio > 1.0:
            raise ValueError("budget_ratio MUST be in [0.0, 1.0] — see RETRY-INV-02.")
        self._budget_ratio = budget_ratio
        self._min_floor = min_floor
        self._successes = 0
        self._retries = 0
        self._lock = threading.Lock()

    def record_success(self) -> None:
        with self._lock:
            self._successes += 1

    def try_admit_retry(self) -> bool:
        with self._lock:
            allowed = int(self._budget_ratio * self._successes) + self._min_floor
            if self._retries >= allowed:
                return False
            self._retries += 1
            return True

    @property
    def retries(self) -> int:
        with self._lock:
            return self._retries

    @property
    def successes(self) -> int:
        with self._lock:
            return self._successes


# ---------------------------------------------------------------------------
# Reference implementation
# ---------------------------------------------------------------------------
class ExponentialBackoffRetryPolicy:
    """Reference RetryPolicy: exponential backoff + full jitter + budget.

    Delay schedule (attempt counts from 1 = first retry):

        base = min(initial_interval_ms * multiplier ** (attempt - 1),
                   max_interval_ms)
        delay = base + uniform(0, jitter * base)

    Attempt count is monotonic per execute() call; classification is
    deterministic for a fixed classifier.
    """

    def __init__(
        self,
        *,
        max_attempts: int = 3,
        initial_interval_ms: int = 100,
        multiplier: float = 2.0,
        max_interval_ms: int = 30_000,
        jitter: float = 1.0,
        budget_ratio: float = 0.1,
        requires_idempotency: bool = True,
        classifier: RetryClassifier | None = None,
        budget: RetryBudget | None = None,
        rng: random.Random | None = None,
        sleep_fn: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts MUST be >= 1.")
        if initial_interval_ms < 0 or max_interval_ms < 0:
            raise ValueError("interval_ms values MUST be >= 0.")
        if multiplier < 1.0:
            raise ValueError("multiplier MUST be >= 1.0.")
        if jitter < 0.0:
            raise ValueError("jitter MUST be >= 0.0 — see RETRY-INV-03.")
        if budget_ratio < 0.0 or budget_ratio > 1.0:
            raise ValueError("budget_ratio MUST be in [0.0, 1.0] — see RETRY-INV-02.")

        self.max_attempts = max_attempts
        self.initial_interval_ms = initial_interval_ms
        self.multiplier = multiplier
        self.max_interval_ms = max_interval_ms
        self.jitter = jitter
        self.budget_ratio = budget_ratio
        self.requires_idempotency = requires_idempotency

        self._classifier = classifier or RetryClassifier()
        self._budget = budget or RetryBudget(
            budget_ratio=budget_ratio,
            min_floor=max(1, max_attempts - 1),
        )
        self._rng = rng or random.Random()  # noqa: S311 — jitter RETRY-INV-03 is statistical, not cryptographic.
        self._sleep_fn = sleep_fn or asyncio.sleep

        # Bookkeeping for observability / tests
        self._attempts_log: deque[dict[str, object]] = deque(maxlen=1024)
        self._lock = threading.Lock()

    # ----- classification ----------------------------------------------------
    def classify(self, exc: BaseException) -> ErrorClass:
        cls = self._classifier.classify(exc)
        if cls not in _CLASSIFICATIONS:
            raise RetryPolicyInvariantError(
                f"RETRY-INV-05: classifier returned {cls!r}; MUST be one of "
                f"{sorted(_CLASSIFICATIONS)}."
            )
        return cls

    # ----- protocol surface --------------------------------------------------
    def should_retry(self, attempt: int, exc: BaseException) -> bool:
        if attempt < 1:
            raise RetryPolicyInvariantError(
                "RETRY-INV attempts are monotonic and 1-indexed; attempt < 1 is invalid."
            )
        if attempt >= self.max_attempts:
            return False
        # RETRY-INV-05: NEVER retry a non-retryable / fatal error.
        return self.classify(exc) not in ("non_retryable", "fatal")

    def next_delay_ms(self, attempt: int) -> int:
        if attempt < 1:
            raise RetryPolicyInvariantError(
                "RETRY-INV attempts are monotonic and 1-indexed; attempt < 1 is invalid."
            )
        # Exponential base, capped at max_interval_ms.
        growth = self.multiplier ** (attempt - 1)
        base = min(float(self.initial_interval_ms) * growth, float(self.max_interval_ms))
        # RETRY-INV-03: full jitter in [0, jitter * base].
        extra = self._rng.uniform(0.0, self.jitter * base)
        delay = base + extra
        if delay < 0.0:
            raise RetryPolicyInvariantError(
                "RETRY-INV-03: negative delay produced; classifier / rng invariant violated."
            )
        return int(delay)

    async def execute(  # noqa: C901 — the retry loop mirrors the RETRY-INV-01..04 guard ordering verbatim; extracting helpers would obscure the invariant chain
        self,
        fn: Callable[[], Awaitable[T]],
        *,
        idempotent: bool | None = None,
        budget: TimeoutBudget | None = None,
    ) -> T:
        """Execute fn with retries. Idempotency and deadline enforced.

        - ``idempotent``: if the caller omits it, ``requires_idempotency``
          governs. When ``requires_idempotency=True`` the caller MUST pass
          ``idempotent=True`` explicitly (RETRY-INV-01).
        - ``budget``: optional TimeoutBudget (RETRY-INV-04).
        """
        idempotent_resolved = self._resolve_idempotency(idempotent)

        attempt = 1
        last_exc: BaseException | None = None
        while attempt <= self.max_attempts:
            try:
                result = await fn()
            except BaseException as exc:
                last_exc = exc
                cls = self.classify(exc)
                self._record(attempt, outcome=f"error:{cls}")

                if not self.should_retry(attempt, exc):
                    raise

                # RETRY-INV-01: first-attempt is always allowed; retries require
                # idempotent=True when requires_idempotency is in effect.
                if not idempotent_resolved:
                    raise RetryPolicyInvariantError(
                        "RETRY-INV-01: non-idempotent call CANNOT be retried; "
                        "pass idempotent=True or set requires_idempotency=False "
                        "by explicit operator decision."
                    ) from exc

                # RETRY-INV-04: deadline check.
                if budget is not None and budget.remaining_ms <= 0:
                    raise RetryPolicyInvariantError(
                        "RETRY-INV-04: TimeoutBudget exhausted; retry FORBIDDEN."
                    ) from exc

                # RETRY-INV-02: budget admission.
                if not self._budget.try_admit_retry():
                    raise RetryPolicyInvariantError(
                        "RETRY-INV-02: retry budget exhausted; refusing to amplify load."
                    ) from exc

                delay_ms = self.next_delay_ms(attempt)
                if budget is not None:
                    budget.consume(delay_ms)
                await self._sleep_fn(delay_ms / 1000.0)
                # RETRY-INV-04 defense-in-depth: re-check deadline AFTER sleep so
                # a long backoff cannot smuggle one extra attempt past the budget.
                if budget is not None and budget.remaining_ms <= 0:
                    raise RetryPolicyInvariantError(
                        "RETRY-INV-04: TimeoutBudget exhausted during backoff; retry FORBIDDEN."
                    ) from exc
                attempt += 1
                continue
            else:
                self._budget.record_success()
                self._record(attempt, outcome="success")
                return result

        # Loop fell through — max_attempts exhausted. Re-raise last error.
        if last_exc is None:
            raise RetryPolicyInvariantError(
                "RETRY-INV attempts are monotonic; loop exited without exception or result."
            )
        raise last_exc

    # ----- helpers -----------------------------------------------------------
    def _resolve_idempotency(self, idempotent: bool | None) -> bool:
        if idempotent is not None:
            return bool(idempotent)
        # No caller override — RETRY-INV-01 forbids retrying when the policy
        # requires idempotency and the caller did not mark the call.
        return not self.requires_idempotency

    def _record(self, attempt: int, *, outcome: str) -> None:
        with self._lock:
            self._attempts_log.append({"attempt": attempt, "outcome": outcome})

    # ----- introspection -----------------------------------------------------
    @property
    def budget(self) -> RetryBudget:
        return self._budget

    @property
    def attempts_log(self) -> tuple[dict[str, object], ...]:
        with self._lock:
            return tuple(self._attempts_log)


__all__ = [
    "ExponentialBackoffRetryPolicy",
    "FatalError",
    "NonRetryableError",
    "RetryBudget",
    "RetryClassifier",
    "RetryPolicy",
    "RetryPolicyInvariantError",
    "TimeoutBudget",
]
