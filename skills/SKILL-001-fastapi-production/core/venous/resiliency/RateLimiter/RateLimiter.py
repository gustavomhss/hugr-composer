"""RateLimiter primitive — per-key admission governor over a rolling window.

Algorithm: token-bucket (primary), adapted from the `limits` library
(https://github.com/alisaifee/limits, MIT) and the Envoy ``token_bucket`` filter.
A key's bucket holds up to ``burst`` tokens; tokens refill at
``rate_per_second``. An ``acquire(key, cost, wait_ms)`` call is admitted when
the bucket holds ``>= cost`` tokens (atomically decrement). Otherwise the
caller waits up to ``wait_ms`` for enough tokens to arrive and — if still
short — is rejected with a typed ``RateLimitedError`` carrying
``retry_after_ms``. Buckets are keyed explicitly; keys cross-scope nothing.

Invariant IDs cited here (full text in ``RateLimiter.md``):

- RATE_INV_01: the long-run admitted rate per key MUST NEVER exceed
  ``rate_per_second`` over any window longer than ``burst / rate_per_second``
  seconds.
- RATE_INV_02: ``acquire`` SHALL NEVER block longer than ``wait_ms``; after
  that it MUST raise ``RateLimitedError``.
- RATE_INV_03: keys are explicit strings scoped to the limiter instance;
  implicit / empty keys are FORBIDDEN.
- RATE_INV_04: a rejection MUST include a ``retry_after_ms`` computed from
  the current bucket depletion.
- RATE_INV_05: ``cost > 1`` SHALL consume proportional tokens and MUST NEVER
  equal the effect of ``cost == 1``.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Final, Literal, Protocol, runtime_checkable

Algorithm = Literal["token_bucket", "leaky_bucket", "sliding_window"]
ALGORITHMS: Final[frozenset[str]] = frozenset(
    {"token_bucket", "leaky_bucket", "sliding_window"}
)


class RateLimiterError(RuntimeError):
    """Raised for RateLimiter contract violations and admission rejections."""


class RateLimitedError(RateLimiterError):
    """Typed rejection raised when a caller is denied admission (RATE_INV_02, RATE_INV_04).

    ``retry_after_ms`` is the minimum wall-clock delay before a fresh attempt
    of the SAME cost could be admitted, computed from the current bucket
    depletion at rejection time.
    """

    def __init__(self, key: str, cost: int, retry_after_ms: int) -> None:
        if retry_after_ms < 0:
            raise RateLimiterError(
                "RATE_INV_04: retry_after_ms MUST NOT be negative."
            )
        super().__init__(
            f"RATE_INV_02: key={key!r} cost={cost} rejected; "
            f"retry_after_ms={retry_after_ms}."
        )
        self.key: str = key
        self.cost: int = cost
        self.retry_after_ms: int = retry_after_ms


# ---------------------------------------------------------------------------
# Protocol surface (mirrors the catalog api_signature byte-for-byte)
# ---------------------------------------------------------------------------
@runtime_checkable
class RateLimiter(Protocol):
    algorithm: Algorithm
    rate_per_second: float
    burst: int

    async def acquire(self, key: str, cost: int = 1, wait_ms: int = 0) -> bool: ...
    def try_acquire(self, key: str, cost: int = 1) -> bool: ...
    def current_rate(self, key: str) -> float: ...


# ---------------------------------------------------------------------------
# Observability event
# ---------------------------------------------------------------------------
class AdmissionEvent:
    """One admission-decision record. Emitted on every acquire / try_acquire."""

    __slots__ = ("admitted", "cost", "key", "monotonic_ns", "retry_after_ms", "waited_ms")

    def __init__(
        self,
        key: str,
        cost: int,
        admitted: bool,
        waited_ms: float,
        retry_after_ms: int,
        monotonic_ns: int,
    ) -> None:
        self.key: str = key
        self.cost: int = cost
        self.admitted: bool = admitted
        self.waited_ms: float = waited_ms
        self.retry_after_ms: int = retry_after_ms
        self.monotonic_ns: int = monotonic_ns


# ---------------------------------------------------------------------------
# Internal bucket state (one per key)
# ---------------------------------------------------------------------------
class _Bucket:
    """Token-bucket state; refilled lazily on read using a monotonic clock."""

    __slots__ = ("last_refill_ns", "tokens")

    def __init__(self, capacity: float, now_ns: int) -> None:
        self.tokens: float = capacity
        self.last_refill_ns: int = now_ns


def _validate_key(key: str) -> None:
    """RATE_INV_03: keys are explicit, non-empty, instance-scoped strings."""
    if not isinstance(key, str):
        raise RateLimiterError(
            f"RATE_INV_03: key MUST be a str, got {type(key).__name__}."
        )
    if not key:
        raise RateLimiterError(
            "RATE_INV_03: key MUST be a non-empty string; implicit keys are FORBIDDEN."
        )
    if len(key) > 512:
        raise RateLimiterError(
            "RATE_INV_03: key MUST NOT exceed 512 chars (prevent unbounded bucket map growth)."
        )


# ---------------------------------------------------------------------------
# Reference in-memory implementation
# ---------------------------------------------------------------------------
class InMemoryRateLimiter:
    """Reference token-bucket implementation.

    Thread- and async-safe: a single ``threading.RLock`` guards all bucket
    state. The lock is held only while computing / mutating token counts —
    the ``acquire`` wait loop releases the lock between polls so unrelated
    keys never contend, and an asyncio event loop is never blocked for the
    full ``wait_ms`` window.

    ``algorithm`` is declared for catalog conformance; the reference impl
    implements ``token_bucket`` only, which subsumes ``leaky_bucket`` at the
    same ``rate_per_second`` via the equivalence documented in the `limits`
    library README. ``sliding_window`` may be registered via the
    extension_contract ``AlgorithmProvider`` hook.
    """

    def __init__(
        self,
        *,
        rate_per_second: float,
        burst: int,
        algorithm: Algorithm = "token_bucket",
        poll_interval_ms: int = 2,
    ) -> None:
        if not isinstance(rate_per_second, (int, float)) or rate_per_second <= 0.0:
            raise RateLimiterError(
                "rate_per_second MUST be a positive number."
            )
        if not isinstance(burst, int) or burst < 1:
            raise RateLimiterError("burst MUST be an int >= 1.")
        if algorithm not in ALGORITHMS:
            raise RateLimiterError(
                f"algorithm MUST be one of {sorted(ALGORITHMS)}, got {algorithm!r}."
            )
        if poll_interval_ms < 1 or poll_interval_ms > 100:
            raise RateLimiterError(
                "poll_interval_ms MUST be in [1, 100] ms."
            )

        self.algorithm: Algorithm = algorithm
        self.rate_per_second: float = float(rate_per_second)
        self.burst: int = burst
        self._poll_interval_s: float = poll_interval_ms / 1000.0
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.RLock()
        self._events: list[AdmissionEvent] = []

    # ------------------------------------------------------------------
    # Observability surface
    # ------------------------------------------------------------------
    @property
    def events(self) -> tuple[AdmissionEvent, ...]:
        with self._lock:
            return tuple(self._events)

    def _record(
        self,
        key: str,
        cost: int,
        admitted: bool,
        waited_ms: float,
        retry_after_ms: int,
    ) -> None:
        self._events.append(
            AdmissionEvent(
                key=key,
                cost=cost,
                admitted=admitted,
                waited_ms=waited_ms,
                retry_after_ms=retry_after_ms,
                monotonic_ns=time.monotonic_ns(),
            )
        )

    # ------------------------------------------------------------------
    # Core token-bucket math (lock-free helpers called only under _lock)
    # ------------------------------------------------------------------
    def _get_or_create(self, key: str, now_ns: int) -> _Bucket:
        b = self._buckets.get(key)
        if b is None:
            b = _Bucket(capacity=float(self.burst), now_ns=now_ns)
            self._buckets[key] = b
        return b

    def _refill(self, bucket: _Bucket, now_ns: int) -> None:
        """Lazily replenish tokens based on elapsed monotonic time."""
        elapsed_s = (now_ns - bucket.last_refill_ns) / 1_000_000_000.0
        if elapsed_s <= 0.0:
            return
        added = elapsed_s * self.rate_per_second
        if added > 0.0:
            bucket.tokens = min(float(self.burst), bucket.tokens + added)
            bucket.last_refill_ns = now_ns

    def _retry_after_ms_for(self, bucket: _Bucket, cost: int) -> int:
        """Time (ms) until ``cost`` tokens become available (RATE_INV_04)."""
        deficit = float(cost) - bucket.tokens
        if deficit <= 0.0:
            return 0
        seconds = deficit / self.rate_per_second
        return max(1, int(seconds * 1000.0 + 0.5))

    @staticmethod
    def _validate_cost(cost: int) -> None:
        if not isinstance(cost, int) or isinstance(cost, bool):
            # RATE_INV_05 — cost must be a concrete int, not a truthy bool.
            raise RateLimiterError(
                "RATE_INV_05: cost MUST be an int (bool is FORBIDDEN)."
            )
        if cost < 1:
            raise RateLimiterError("RATE_INV_05: cost MUST be >= 1.")

    # ------------------------------------------------------------------
    # Public API — mirrors the catalog Protocol surface
    # ------------------------------------------------------------------
    def try_acquire(self, key: str, cost: int = 1) -> bool:
        """Non-blocking attempt. Returns True iff ``cost`` tokens were consumed.

        On rejection the limiter records a ``retry_after_ms`` into the event
        log (RATE_INV_04) but — per contract — returns ``False`` rather than
        raising. The raising variant lives on ``acquire`` after ``wait_ms``
        expires (RATE_INV_02).
        """
        _validate_key(key)
        self._validate_cost(cost)
        if cost > self.burst:
            # A cost that exceeds burst can NEVER be admitted; refuse deterministically.
            with self._lock:
                self._record(key, cost, admitted=False, waited_ms=0.0, retry_after_ms=-1)
            raise RateLimiterError(
                f"RATE_INV_05: cost={cost} exceeds burst={self.burst}; unsatisfiable."
            )

        with self._lock:
            now_ns = time.monotonic_ns()
            bucket = self._get_or_create(key, now_ns)
            self._refill(bucket, now_ns)
            if bucket.tokens >= float(cost):
                bucket.tokens -= float(cost)  # RATE_INV_05: proportional decrement
                self._record(key, cost, admitted=True, waited_ms=0.0, retry_after_ms=0)
                return True
            retry_after = self._retry_after_ms_for(bucket, cost)
            self._record(
                key, cost, admitted=False, waited_ms=0.0, retry_after_ms=retry_after
            )
            return False

    async def acquire(self, key: str, cost: int = 1, wait_ms: int = 0) -> bool:
        """Admit iff ``cost`` tokens are (or become) available within ``wait_ms``.

        - Returns ``True`` on admission.
        - Raises ``RateLimitedError`` after ``wait_ms`` if still short
          (RATE_INV_02); the error carries ``retry_after_ms`` (RATE_INV_04).
        """
        _validate_key(key)
        self._validate_cost(cost)
        if not isinstance(wait_ms, int) or isinstance(wait_ms, bool) or wait_ms < 0:
            raise RateLimiterError("wait_ms MUST be a non-negative int.")
        if cost > self.burst:
            with self._lock:
                self._record(key, cost, admitted=False, waited_ms=0.0, retry_after_ms=-1)
            raise RateLimiterError(
                f"RATE_INV_05: cost={cost} exceeds burst={self.burst}; unsatisfiable."
            )

        deadline_ns = time.monotonic_ns() + int(wait_ms) * 1_000_000
        started_ns = time.monotonic_ns()

        while True:
            with self._lock:
                now_ns = time.monotonic_ns()
                bucket = self._get_or_create(key, now_ns)
                self._refill(bucket, now_ns)
                if bucket.tokens >= float(cost):
                    bucket.tokens -= float(cost)
                    waited_ms = (now_ns - started_ns) / 1_000_000.0
                    self._record(
                        key, cost, admitted=True, waited_ms=waited_ms, retry_after_ms=0
                    )
                    return True
                retry_after_ms = self._retry_after_ms_for(bucket, cost)
                now_ns = time.monotonic_ns()
                remaining_ns = deadline_ns - now_ns
                if remaining_ns <= 0:
                    waited_ms = (now_ns - started_ns) / 1_000_000.0
                    self._record(
                        key,
                        cost,
                        admitted=False,
                        waited_ms=waited_ms,
                        retry_after_ms=retry_after_ms,
                    )
                    raise RateLimitedError(
                        key=key, cost=cost, retry_after_ms=retry_after_ms
                    )
                # RATE_INV_02: sleep OUTSIDE the lock to respect deadline under contention.
                sleep_s = min(
                    self._poll_interval_s,
                    remaining_ns / 1_000_000_000.0,
                    retry_after_ms / 1000.0 if retry_after_ms > 0 else self._poll_interval_s,
                )
            if sleep_s > 0:
                await asyncio.sleep(sleep_s)

    def current_rate(self, key: str) -> float:
        """Return the instantaneous admitted rate (tokens/s) for ``key``.

        Computed as the exponentially-weighted average of the last admission
        inter-arrival; with an empty event log it returns 0.0. Pure read
        under the lock — no refill side effects.
        """
        _validate_key(key)
        with self._lock:
            # Filter to admissions for this key in the last rolling window.
            window_ns = int(2 * (self.burst / self.rate_per_second) * 1_000_000_000)
            cutoff = time.monotonic_ns() - window_ns
            hits = [
                e for e in self._events
                if e.key == key and e.admitted and e.monotonic_ns >= cutoff
            ]
            if len(hits) < 2:
                # Not enough evidence — report 0 (never report an unbounded rate).
                return 0.0
            span_ns = hits[-1].monotonic_ns - hits[0].monotonic_ns
            if span_ns <= 0:
                return 0.0
            # Sum of costs over wall-clock span.
            total_cost = sum(h.cost for h in hits)
            return total_cost / (span_ns / 1_000_000_000.0)

    def reset(self, key: str) -> None:
        """Drop the bucket state for ``key``. Purely administrative."""
        _validate_key(key)
        with self._lock:
            self._buckets.pop(key, None)


__all__ = [
    "ALGORITHMS",
    "AdmissionEvent",
    "Algorithm",
    "InMemoryRateLimiter",
    "RateLimitedError",
    "RateLimiter",
    "RateLimiterError",
]
