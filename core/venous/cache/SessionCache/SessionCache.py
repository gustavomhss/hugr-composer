"""SessionCache primitive — node-agnostic read-through session cache.

Any node in a stateless tier can resolve per-caller state (quotas, flags,
cursors) via a single ``get(token)``. Misses return ``None`` (not raise),
so the caller distinguishes miss vs. error via the explicit
``SessionCacheError`` exception. TTL is honored on read — an expired
entry behaves exactly like a missing one.

Framework-agnostic: stdlib + typing only. No Redis / Envoy import. OSS
reference is cited in ``SessionCache.md`` provenance — the implementation
here is a stdlib-only reimagining of Redis `GETEX` read-through plus
JWT-claim style per-session state.

Invariant IDs (full text in ``SessionCache.md``):

- SC_INV_01: ``get()`` is read-only — never mutates server-side state.
- SC_INV_02: Missing key returns ``None``; caller distinguishes miss vs.
  error via an explicit exception type.
- SC_INV_03: ``invalidate()`` is idempotent and O(1).
- SC_INV_04: TTL is honored — an expired entry is equivalent to missing.
- SC_INV_05: A node that has never seen a token can still resolve its
  session via the external store (cold cache tolerant).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Optional, Protocol, runtime_checkable


class SessionCacheError(RuntimeError):
    """Raised when the external store is unreachable.

    SC_INV_02: callers distinguish miss (``get`` returns ``None``) from
    error (``get`` raises ``SessionCacheError``).
    """


@runtime_checkable
class SessionCache(Protocol):
    def get(self, token: str) -> Optional[Mapping[str, Any]]: ...
    def set(self, token: str, value: Mapping[str, Any], ttl_s: int) -> None: ...
    def invalidate(self, token: str) -> None: ...


@dataclass
class _Entry:
    value: Mapping[str, Any]
    expires_at_s: float


# Clock is injectable so SC_INV_04 is testable without wall-clock sleeps.
Clock = Callable[[], float]


class InMemorySessionCache:
    """Reference SessionCache.

    Pure in-process implementation — suitable for unit tests and
    single-process dev. Production deployments swap to an external
    adapter (Redis, Memcached) that shares the token space across nodes;
    the Protocol shape does not change.
    """

    def __init__(self, *, clock: Clock | None = None) -> None:
        self._store: dict[str, _Entry] = {}
        self._clock: Clock = clock or time.monotonic

    def get(self, token: str) -> Optional[Mapping[str, Any]]:
        """SC_INV_01: read-only. SC_INV_04: TTL honored on read."""
        entry = self._store.get(token)
        if entry is None:
            return None
        if entry.expires_at_s <= self._clock():
            # Expired — do NOT remove here (keeps get() read-only per
            # SC_INV_01); invalidate() or a separate sweeper handles GC.
            # For the caller, expired is indistinguishable from missing.
            return None
        return entry.value

    def set(self, token: str, value: Mapping[str, Any], ttl_s: int) -> None:
        if ttl_s <= 0:
            raise SessionCacheError("ttl_s MUST be > 0.")
        self._store[token] = _Entry(
            value=dict(value),  # defensive copy — caller mutations cannot leak.
            expires_at_s=self._clock() + ttl_s,
        )

    def invalidate(self, token: str) -> None:
        """SC_INV_03: idempotent, O(1)."""
        self._store.pop(token, None)


class ReadThroughSessionCache:
    """External-store read-through wrapper.

    The loader is the caller-provided function that fetches the session
    from the source of truth (Redis, session-DB, auth-service). On cache
    miss the wrapper queries the loader and memoizes the result for
    ``ttl_s`` seconds. SC_INV_05 — a cold node calling ``get`` still
    resolves via the loader, so node locality has no correctness impact.
    """

    def __init__(
        self,
        loader: Callable[[str], Optional[Mapping[str, Any]]],
        *,
        ttl_s: int = 300,
        clock: Clock | None = None,
    ) -> None:
        if ttl_s <= 0:
            raise SessionCacheError("ttl_s MUST be > 0.")
        self._loader = loader
        self._ttl_s = ttl_s
        self._local = InMemorySessionCache(clock=clock)

    def get(self, token: str) -> Optional[Mapping[str, Any]]:
        hit = self._local.get(token)
        if hit is not None:
            return hit
        # Cold cache — pull from external store.
        try:
            value = self._loader(token)
        except SessionCacheError:
            raise
        except Exception as exc:  # noqa: BLE001
            # Wrap unknown loader failures in the contract exception so
            # callers can distinguish miss (None) from error (raise).
            raise SessionCacheError(f"loader failed: {exc!r}") from exc
        if value is None:
            return None
        self._local.set(token, value, self._ttl_s)
        return value

    def set(self, token: str, value: Mapping[str, Any], ttl_s: int) -> None:
        self._local.set(token, value, ttl_s)

    def invalidate(self, token: str) -> None:
        self._local.invalidate(token)


__all__ = [
    "InMemorySessionCache",
    "ReadThroughSessionCache",
    "SessionCache",
    "SessionCacheError",
]
