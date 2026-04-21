"""FastAPI adapter for the ``resiliency.Bulkhead`` primitive.

Wraps ``core.venous.resiliency.Bulkhead.PartitionRegistry`` in an ergonomic
multi-group interface that a generated FastAPI app can use directly:

- ``Bulkhead(BulkheadConfig(limits={"payments": 10, "crud": 50}))`` bundles
  multiple partitions into a single facade.
- ``async with bulkhead.acquire("payments"): ...`` holds a permit for the
  partition's body and raises ``BulkheadFullError`` on saturation (maps to
  the motor's ``BulkheadFull``).
- ``bulkhead.status()`` returns ``{group: {active, max, available}}`` per
  partition — the shape a status-endpoint returns to operators.
- ``BulkheadMiddleware`` is a BaseHTTPMiddleware that classifies each
  request to a partition (caller-provided ``classify_route``) and returns
  ``503 + X-Bulkhead-Group`` on rejection.

All permit accounting, invariant enforcement (BH_INV_01..05) and rejection
metering live in the motor. This adapter is PURE framework wiring — no
business logic. Tools that need a multi-partition Bulkhead in a FastAPI app
import from here instead of inlining the wrapper.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from core.venous.resiliency.Bulkhead import (
    BulkheadFull,
    InMemoryBulkhead,
    PartitionConfig,
    PartitionRegistry,
    RejectionMeter,
    RequestRejectionLedger,
    snapshot,
)

# Ergonomic alias — tools and user code commonly name the exception
# ``BulkheadFullError`` (matches resilience4j / Hystrix lineage), but the
# motor ships ``BulkheadFull`` to match Nygard's taxonomy. Both names
# point to the same exception class.
BulkheadFullError = BulkheadFull

__all__ = [
    "Bulkhead",
    "BulkheadConfig",
    "BulkheadFullError",
    "BulkheadMiddleware",
]


# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------
@dataclass
class BulkheadConfig:
    """Multi-partition configuration accepted by ``Bulkhead``.

    Fields:
        limits: ``{partition_name: max_concurrent_calls}``. Each limit MUST
            be >= 1; a zero-or-negative limit would silently reject every
            call.
        wait_ms: Max time a waiting caller blocks for a permit before
            rejection. ``0`` means zero-wait (the immediate-rejection
            semantics the motor documents as ``effective_timeout = 1e-9``).
    """

    limits: dict[str, int] = field(default_factory=dict)
    wait_ms: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.limits, dict) or not self.limits:
            raise ValueError(
                "BulkheadConfig.limits MUST be a non-empty {partition: limit} "
                "dict; an empty bulkhead can admit no callers."
            )
        for group, limit in self.limits.items():
            if not isinstance(group, str) or group == "":
                raise ValueError(
                    f"BulkheadConfig.limits keys MUST be non-empty str, got {group!r}."
                )
            if not isinstance(limit, int) or limit < 1:
                raise ValueError(
                    f"BulkheadConfig.limits['{group}'] MUST be int >= 1, got {limit!r}."
                )
        if not isinstance(self.wait_ms, int) or self.wait_ms < 0:
            raise ValueError(
                f"BulkheadConfig.wait_ms MUST be int >= 0, got {self.wait_ms!r}."
            )


# ---------------------------------------------------------------------------
# Per-group gate — re-entrant async context manager
# ---------------------------------------------------------------------------
class _GroupGate:
    """Async context manager bound to one partition.

    Each ``__aenter__`` call acquires a fresh motor permit (may raise
    ``BulkheadFullError`` on saturation). Each matching ``__aexit__``
    releases the most recently acquired permit. The gate is intentionally
    re-entrant so callers can ``await gate.__aenter__()`` twice to exhaust
    a partition's capacity in a single test body.
    """

    __slots__ = ("_partition", "_active")

    def __init__(self, partition: InMemoryBulkhead) -> None:
        self._partition = partition
        self._active: list[Any] = []

    async def __aenter__(self) -> "_GroupGate":
        cm = self._partition.acquire()
        # ``acquire()`` is a @asynccontextmanager — driving it through
        # __aenter__ here raises BulkheadFull on saturation BEFORE we
        # append to _active, so an exit never releases a permit we
        # didn't take.
        await cm.__aenter__()
        self._active.append(cm)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: Any,
    ) -> None:
        if not self._active:
            raise RuntimeError(
                "BulkheadAdapter._GroupGate: __aexit__ without matching "
                "__aenter__; permit accounting would drift."
            )
        cm = self._active.pop()
        await cm.__aexit__(exc_type, exc, tb)


# ---------------------------------------------------------------------------
# Public Bulkhead facade (multi-partition)
# ---------------------------------------------------------------------------
class Bulkhead:
    """Multi-partition bulkhead facade.

    Wraps ``PartitionRegistry`` with an ergonomic API:

    - ``acquire(group)`` → async context manager holding a permit.
    - ``status()`` → per-group ``{active, max, available}``.
    - ``meter`` / ``ledger`` → shared observability primitives from the motor.

    All invariant enforcement (BH_INV_01..05) lives in the motor; this
    class is pure framework wiring.
    """

    def __init__(
        self,
        config: BulkheadConfig,
        *,
        meter: RejectionMeter | None = None,
        ledger: RequestRejectionLedger | None = None,
    ) -> None:
        if not isinstance(config, BulkheadConfig):
            raise TypeError(
                f"Bulkhead expects BulkheadConfig, got {type(config).__name__}."
            )
        self._config = config
        self._registry = PartitionRegistry(meter=meter, ledger=ledger)
        for group, limit in config.limits.items():
            self._registry.register(
                PartitionConfig(
                    name=group,
                    max_concurrent_calls=limit,
                    max_wait_duration_ms=config.wait_ms,
                )
            )

    # ---- accessors --------------------------------------------------------
    @property
    def groups(self) -> tuple[str, ...]:
        """Sorted tuple of registered partition names."""
        return self._registry.names()

    @property
    def meter(self) -> RejectionMeter:
        return self._registry.meter

    @property
    def ledger(self) -> RequestRejectionLedger:
        return self._registry.ledger

    # ---- acquire / status -------------------------------------------------
    def acquire(self, group: str) -> _GroupGate:
        """Return an async context manager holding a permit for ``group``.

        Raises:
            BulkheadInvariantError: ``group`` is not registered.
            BulkheadFullError: ``group`` is at capacity and the wait
                budget is exhausted.
        """
        partition = self._registry.get(group)
        return _GroupGate(partition)

    def status(self) -> dict[str, dict[str, int]]:
        """Return ``{group: {active, max, available}}`` for every partition."""
        out: dict[str, dict[str, int]] = {}
        for name in self._registry.names():
            snap = snapshot(self._registry.get(name))
            out[name] = {
                "active": snap.in_flight,
                "max": snap.capacity,
                "available": snap.available,
            }
        return out


# ---------------------------------------------------------------------------
# FastAPI middleware — pure framework wiring
# ---------------------------------------------------------------------------
class BulkheadMiddleware(BaseHTTPMiddleware):
    """Starlette/FastAPI middleware that partitions concurrency per route group.

    Caller supplies:

    - ``bulkhead``: a ``Bulkhead`` facade with the partitions registered.
    - ``classify_route``: ``request.url.path -> group_name`` function that
      MUST always return a registered group (unknown groups raise
      ``BulkheadInvariantError``; middleware lets that bubble so the bug
      surfaces loudly).
    - ``logger``: optional ``logging.Logger``; defaults to module logger.

    On saturation (``BulkheadFullError``): returns ``503`` with
    ``X-Bulkhead-Group`` header and a JSON body naming the saturated group
    so clients can implement group-aware backoff.
    """

    def __init__(
        self,
        app: Any,
        bulkhead: Bulkhead,
        classify_route: Callable[[str], str],
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        super().__init__(app)
        self._bulkhead = bulkhead
        self._classify = classify_route
        self._logger = logger or logging.getLogger(__name__)

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        group = self._classify(request.url.path)
        try:
            async with self._bulkhead.acquire(group):
                return await call_next(request)
        except BulkheadFullError as exc:
            self._logger.warning(
                "Bulkhead full for group '%s': %s", group, exc
            )
            return JSONResponse(
                status_code=503,
                content={
                    "detail": (
                        f"Service unavailable: '{group}' pool at capacity. "
                        "Please retry."
                    )
                },
                headers={"X-Bulkhead-Group": group},
            )
