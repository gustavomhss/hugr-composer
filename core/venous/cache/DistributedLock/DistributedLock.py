"""DistributedLock primitive — named mutex with lease expiry and owner fencing.

Mirrors the catalog Protocol for `cache.DistributedLock`. Module load performs
zero I/O.

Invariant IDs cited by this module:

- DL_INV_01: At most one caller MUST hold a given resource_id at a time;
  try_lock on a held lock returns None.
- DL_INV_02: Locks ALWAYS auto release after lease_s elapses so a crashed
  holder CANNOT deadlock the resource forever.
- DL_INV_03: Unlock with a non-matching owner_id MUST be rejected so callers
  cannot release locks they do not own.
- DL_INV_04: lease_s MUST be positive; a zero or negative lease SHALL raise
  a configuration error.
- DL_INV_05: The primitive NEVER guarantees fairness across callers beyond
  the single holder invariant.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Final, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MIN_LEASE_SECONDS: Final[int] = 1
MAX_LEASE_SECONDS: Final[int] = 86_400  # one day


# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------
class DistributedLockError(ValueError):
    """Base for DistributedLock invariant violations."""


class LockOwnershipError(DistributedLockError):
    """DL_INV_03: unlock rejected because owner_id does not match."""


# ---------------------------------------------------------------------------
# Catalog data shape
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class LockHandle:
    """Grant returned by try_lock; the caller presents it on unlock.

    `fencing_token` is a strictly-monotonic integer per-resource — downstream
    storage MUST reject writes carrying a token strictly lower than the highest
    it has observed for the same resource_id. This defends the classic
    "paused-process wakes with stale lease" failure: even if two holders
    overlap in time, only the later fencing token survives at the storage tier.
    """

    resource_id: str
    owner_id: str
    lease_s: int
    fencing_token: int = 0


# ---------------------------------------------------------------------------
# Protocol surface
# ---------------------------------------------------------------------------
@runtime_checkable
class DistributedLock(Protocol):
    async def try_lock(
        self, resource_id: str, owner_id: str, lease_s: int,
    ) -> LockHandle | None: ...
    async def unlock(self, handle: LockHandle) -> None: ...


# ---------------------------------------------------------------------------
# Reference implementation — in-process, monotonic-clock lease tracking
# ---------------------------------------------------------------------------
def _validate_resource_id(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise DistributedLockError("resource_id MUST be a non-empty string.")
    if "\x00" in value:
        raise DistributedLockError("resource_id MUST NOT contain null bytes.")
    return value


def _validate_owner_id(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise DistributedLockError("owner_id MUST be a non-empty string.")
    if "\x00" in value:
        raise DistributedLockError("owner_id MUST NOT contain null bytes.")
    return value


def _validate_lease(lease_s: int) -> int:
    """DL_INV_04: lease MUST be positive and bounded."""
    if not isinstance(lease_s, int) or isinstance(lease_s, bool):
        raise DistributedLockError(
            f"lease_s MUST be int, got {type(lease_s).__name__}.",
        )
    if lease_s < MIN_LEASE_SECONDS:
        raise DistributedLockError(
            f"DL_INV_04: lease_s MUST be >= {MIN_LEASE_SECONDS}, got {lease_s}.",
        )
    if lease_s > MAX_LEASE_SECONDS:
        raise DistributedLockError(
            f"DL_INV_04: lease_s MUST be <= {MAX_LEASE_SECONDS}, got {lease_s}.",
        )
    return lease_s


@dataclass
class _LockRecord:
    owner_id: str
    expires_at_monotonic: float
    fencing_token: int


class InMemoryDistributedLock:
    """Reference DistributedLock.

    State is a `resource_id -> _LockRecord` map gated by a single lock. Lease
    expiry is evaluated at acquire-time using monotonic_ns.
    """

    def __init__(self, *, clock: ClockProtocol | None = None) -> None:
        self._mu = threading.Lock()
        self._held: dict[str, _LockRecord] = {}
        self._clock: ClockProtocol = clock or _MonotonicClock()
        # DL_INV_05: monotonic fencing counter per resource_id; NEVER decreases,
        # survives lease expiration, so a stale lease holder's write can always
        # be rejected downstream against the current token.
        self._fencing: dict[str, int] = {}

    async def try_lock(
        self, resource_id: str, owner_id: str, lease_s: int,
    ) -> LockHandle | None:
        _validate_resource_id(resource_id)
        _validate_owner_id(owner_id)
        _validate_lease(lease_s)
        now = self._clock.now()
        with self._mu:
            rec = self._held.get(resource_id)
            # DL_INV_02: expired leases are reclaimable.
            if rec is None or now >= rec.expires_at_monotonic:
                # DL_INV_05: advance fencing token on every successful acquire,
                # including reclamation of expired leases.
                token = self._fencing.get(resource_id, 0) + 1
                self._fencing[resource_id] = token
                self._held[resource_id] = _LockRecord(
                    owner_id=owner_id,
                    expires_at_monotonic=now + lease_s,
                    fencing_token=token,
                )
                return LockHandle(
                    resource_id=resource_id,
                    owner_id=owner_id,
                    lease_s=lease_s,
                    fencing_token=token,
                )
            # DL_INV_01: held and not expired — reject.
            return None

    async def unlock(self, handle: LockHandle) -> None:
        _validate_resource_id(handle.resource_id)
        _validate_owner_id(handle.owner_id)
        now = self._clock.now()
        with self._mu:
            rec = self._held.get(handle.resource_id)
            if rec is None:
                return  # already released — idempotent
            if now >= rec.expires_at_monotonic:
                # Expired. DL_INV_03: reject stale unlock from a past epoch if
                # the caller's fencing token is not the current one.
                current_token = self._fencing.get(handle.resource_id, 0)
                if handle.fencing_token != current_token:
                    raise LockOwnershipError(
                        f"DL_INV_03: unlock rejected — handle fencing_token "
                        f"{handle.fencing_token} is not the current token "
                        f"{current_token} for resource {handle.resource_id!r}.",
                    )
                self._held.pop(handle.resource_id, None)
                return
            # DL_INV_03: owner AND fencing-token mismatch MUST be rejected.
            if rec.owner_id != handle.owner_id or rec.fencing_token != handle.fencing_token:
                raise LockOwnershipError(
                    f"DL_INV_03: unlock rejected — caller "
                    f"(owner={handle.owner_id!r}, token={handle.fencing_token}) "
                    f"does not match holder "
                    f"(owner={rec.owner_id!r}, token={rec.fencing_token}) "
                    f"for resource {handle.resource_id!r}.",
                )
            del self._held[handle.resource_id]

    # ---- observability / test hooks -------------------------------------
    def is_held(self, resource_id: str) -> bool:
        now = self._clock.now()
        with self._mu:
            rec = self._held.get(resource_id)
            return rec is not None and now < rec.expires_at_monotonic

    def current_holder(self, resource_id: str) -> str | None:
        now = self._clock.now()
        with self._mu:
            rec = self._held.get(resource_id)
            if rec is None or now >= rec.expires_at_monotonic:
                return None
            return rec.owner_id


# ---------------------------------------------------------------------------
# Clock abstraction (so tests drive DL_INV_02 without sleeping)
# ---------------------------------------------------------------------------
@runtime_checkable
class ClockProtocol(Protocol):
    def now(self) -> float: ...


class _MonotonicClock:
    def now(self) -> float:
        return time.monotonic()


class FakeClock:
    """Test-controlled monotonic clock; not thread-safe by design.

    Tests SHALL serialize access or use it from a single thread.
    """

    def __init__(self, start: float = 0.0) -> None:
        self._t = start

    def now(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("FakeClock.advance MUST receive a non-negative delta.")
        self._t += seconds


__all__ = [
    "MAX_LEASE_SECONDS",
    "MIN_LEASE_SECONDS",
    "ClockProtocol",
    "DistributedLock",
    "DistributedLockError",
    "FakeClock",
    "InMemoryDistributedLock",
    "LockHandle",
    "LockOwnershipError",
]
