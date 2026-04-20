"""IdentityMap primitive — Fowler PEAA session-scoped aggregate identity cache.

Implements the catalog Protocol for `data.IdentityMap` and installs runtime
invariant checkers. The module performs zero I/O at import.

Invariant IDs cited by this module:

- IDMAP-INV-01: given the same (type, id) within one session, the IdentityMap
  MUST return the SAME Python object reference on every lookup.
- IDMAP-INV-02: an object CANNOT be inserted twice for the same identity; a
  second add with a DIFFERENT instance SHALL raise a conflict error.
- IDMAP-INV-03: the map MUST be scoped to a single UnitOfWork / session and
  NEVER shared across concurrent transactions.
- IDMAP-INV-04: on UnitOfWork disposal the map ALWAYS clears its contents;
  retaining references beyond the session is FORBIDDEN.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from types import TracebackType
from typing import Any, Final, Literal, Protocol, Self, runtime_checkable

# ---------------------------------------------------------------------------
# Session lifecycle states
# ---------------------------------------------------------------------------
_STATE_OPEN: Final[str] = "open"
_STATE_DISPOSED: Final[str] = "disposed"


# ---------------------------------------------------------------------------
# Protocol surface (matches catalog api_signature verbatim)
# ---------------------------------------------------------------------------
@runtime_checkable
class IdentityMap(Protocol):
    def get(self, type_: type, id: object) -> Any | None: ...  # noqa: A002 — IDMAP-INV-01: `id` matches catalog api_signature verbatim.
    def add(self, obj: Any) -> None: ...
    def remove(self, type_: type, id: object) -> None: ...  # noqa: A002 — IDMAP-INV-04: `id` matches catalog api_signature verbatim.
    def contains(self, type_: type, id: object) -> bool: ...  # noqa: A002 — IDMAP-INV-01: `id` matches catalog api_signature verbatim.


# ---------------------------------------------------------------------------
# Invariant-violation marker
# ---------------------------------------------------------------------------
class IdentityMapInvariantError(RuntimeError):
    """Raised when an IdentityMap invariant is violated at runtime."""


# ---------------------------------------------------------------------------
# Reference implementation
# ---------------------------------------------------------------------------
class InMemoryIdentityMap:
    """Reference IdentityMap backed by a nested dict keyed by (type, id).

    - Thread-safe (serialised via a single lock) so concurrent registrations
      inside one session preserve referential identity.
    - Session-scoped: once disposed, every method except `state` raises so
      leaks past the owning UnitOfWork are IMPOSSIBLE (IDMAP-INV-03/04).
    - Identity key is (type(obj), obj.id); `add()` derives both from the
      object itself, matching Fowler's canonical API.
    - Eviction policies are installed via `register_eviction_hook`; the
      extension contract REFUSES to weaken referential identity — a hook may
      observe evictions but never mutate the cache on its own.
    """

    def __init__(
        self,
        *,
        session_id: object | None = None,
        id_attr: str = "id",
    ) -> None:
        self._by_type: dict[type, dict[object, Any]] = {}
        self._lock = threading.Lock()
        self._state: str = _STATE_OPEN
        self._session_id = session_id
        self._owner_thread: int | None = threading.get_ident()
        self._id_attr = id_attr
        self._eviction_hooks: list[Callable[[type, object, Any], None]] = []

    # ----- catalog surface -------------------------------------------------
    def get(self, type_: type, id: object) -> Any | None:  # noqa: A002 — catalog parameter name.
        self._guard_open()
        with self._lock:
            return self._by_type.get(type_, {}).get(id)

    def add(self, obj: Any) -> None:
        self._guard_open()
        if obj is None:
            raise IdentityMapInvariantError(
                "IDMAP-INV-02: cannot add None; the identity map tracks aggregate roots only."
            )
        key_type, key_id = self._key_of(obj)
        with self._lock:
            bucket = self._by_type.setdefault(key_type, {})
            existing = bucket.get(key_id)
            if existing is None:
                bucket[key_id] = obj
                return
            if existing is obj:
                # Idempotent re-add of the SAME reference is allowed — this
                # preserves IDMAP-INV-01 (same ref on every lookup).
                return
            raise IdentityMapInvariantError(
                "IDMAP-INV-02: a different instance is already registered for "
                f"({key_type.__name__}, id={key_id!r}); referential identity CANNOT be broken."
            )

    def remove(self, type_: type, id: object) -> None:  # noqa: A002 — catalog parameter name.
        self._guard_open()
        with self._lock:
            bucket = self._by_type.get(type_)
            if bucket is None:
                return
            evicted = bucket.pop(id, None)
        if evicted is not None:
            for hook in self._eviction_hooks:
                hook(type_, id, evicted)

    def contains(self, type_: type, id: object) -> bool:  # noqa: A002 — catalog parameter name.
        self._guard_open()
        with self._lock:
            bucket = self._by_type.get(type_)
            return bucket is not None and id in bucket

    # ----- session lifecycle (IDMAP-INV-03 / IDMAP-INV-04) ------------------
    def dispose(self) -> None:
        """Clear the map and mark the session as disposed.

        After `dispose()` every catalog method raises. Idempotent: disposing
        twice is a no-op so callers on error paths can disposal-then-log
        without fear of double-raise cascades.
        """
        with self._lock:
            if self._state == _STATE_DISPOSED:
                return
            self._by_type.clear()
            self._state = _STATE_DISPOSED

    # ----- extension contract ----------------------------------------------
    def register_eviction_hook(
        self,
        hook: Callable[[type, object, Any], None],
    ) -> None:
        """Install an observer that runs AFTER an entry is evicted by `remove`.

        Hooks are observation-only: they see (type, id, object) and CANNOT
        mutate the cache (any such mutation would violate IDMAP-INV-01).
        """
        self._guard_open()
        self._eviction_hooks.append(hook)

    # ----- context-manager semantics ---------------------------------------
    def __enter__(self) -> Self:
        if self._state == _STATE_DISPOSED:
            raise IdentityMapInvariantError(
                "IDMAP-INV-04: IdentityMap is DISPOSED; sessions CANNOT be reused."
            )
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> Literal[False]:
        # On every exit — normal or exceptional — IDMAP-INV-04 requires
        # clearing the map so references never outlive the session.
        self.dispose()
        return False

    # ----- introspection ---------------------------------------------------
    @property
    def state(self) -> str:
        return self._state

    @property
    def session_id(self) -> object | None:
        return self._session_id

    @property
    def owner_thread(self) -> int | None:
        return self._owner_thread

    def size(self) -> int:
        self._guard_open()
        with self._lock:
            return sum(len(bucket) for bucket in self._by_type.values())

    def snapshot(self) -> dict[type, dict[object, Any]]:
        """Return a shallow copy of the cache for debugging / tests."""
        self._guard_open()
        with self._lock:
            return {t: dict(b) for t, b in self._by_type.items()}

    # ----- helpers ----------------------------------------------------------
    def _guard_open(self) -> None:
        if self._state == _STATE_DISPOSED:
            raise IdentityMapInvariantError(
                "IDMAP-INV-04: IdentityMap is DISPOSED; retaining or touching a "
                "map beyond the owning session is FORBIDDEN."
            )

    def _key_of(self, obj: object) -> tuple[type, object]:
        key_type = type(obj)
        key_id = getattr(obj, self._id_attr, None)
        if key_id is None:
            raise IdentityMapInvariantError(
                "IDMAP-INV-01: object MUST expose a non-None "
                f"`{self._id_attr}` attribute to be tracked by IdentityMap."
            )
        return key_type, key_id


# ---------------------------------------------------------------------------
# Scoping helpers (IDMAP-INV-03)
# ---------------------------------------------------------------------------
@contextmanager
def session_scope(
    *,
    session_id: object | None = None,
    id_attr: str = "id",
) -> Iterator[InMemoryIdentityMap]:
    """Open a per-session IdentityMap bound to a fresh UnitOfWork-like scope.

    The returned map is DISPOSED on exit, guaranteeing IDMAP-INV-04 even on
    exception paths. Two calls to `session_scope` yield two DISTINCT maps —
    concurrent transactions therefore cannot share identity references.
    """
    imap = InMemoryIdentityMap(session_id=session_id, id_attr=id_attr)
    try:
        with imap as scoped:
            yield scoped
    finally:
        # `__exit__` already disposed on the normal path; dispose() is
        # idempotent so a second call here is safe and preserves the
        # invariant on any unexpected control flow.
        imap.dispose()


class ConcurrentSessionError(IdentityMapInvariantError):
    """Raised when a map is accessed from a thread other than its owner."""


class ThreadBoundIdentityMap(InMemoryIdentityMap):
    """Variant that REFUSES cross-thread access (IDMAP-INV-03 hardened).

    Useful when the caller wants runtime enforcement instead of an audit rule.
    """

    def _guard_open(self) -> None:
        super()._guard_open()
        current = threading.get_ident()
        if self._owner_thread is not None and current != self._owner_thread:
            raise ConcurrentSessionError(
                "IDMAP-INV-03: IdentityMap is bound to a single session and "
                "CANNOT be touched from a different thread."
            )


__all__ = [
    "ConcurrentSessionError",
    "IdentityMap",
    "IdentityMapInvariantError",
    "InMemoryIdentityMap",
    "ThreadBoundIdentityMap",
    "session_scope",
]
