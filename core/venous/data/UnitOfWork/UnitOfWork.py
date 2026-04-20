"""UnitOfWork primitive — Fowler PEAA transactional change-tracking boundary.

Implements the catalog Protocol for `data.UnitOfWork` and installs runtime
invariant checkers. The module performs zero I/O at import.

Invariant IDs cited by this module:

- UOW-INV-01: commit MUST flush every registered new / dirty / removed object
  in a single atomic transaction; on any exception the unit MUST rollback.
- UOW-INV-02: the same object identity CANNOT be registered in more than one
  bucket (new, dirty, removed) inside one unit.
- UOW-INV-03: a UnitOfWork CANNOT be reused after commit or rollback; a fresh
  unit MUST be opened for the next transaction.
- UOW-INV-04: context-manager semantics ALWAYS drive lifecycle; on exception
  the unit SHALL rollback so leaks on error paths are impossible.
- UOW-INV-05: repositories operating inside the unit MUST enlist mutations
  with the unit; direct writes bypassing the unit are FORBIDDEN.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from types import TracebackType
from typing import Any, Final, Literal, Protocol, Self, runtime_checkable

# ---------------------------------------------------------------------------
# Lifecycle states
# ---------------------------------------------------------------------------
_STATE_OPEN: Final[str] = "open"
_STATE_COMMITTED: Final[str] = "committed"
_STATE_ROLLED_BACK: Final[str] = "rolled_back"

_TERMINAL_STATES: Final[frozenset[str]] = frozenset({_STATE_COMMITTED, _STATE_ROLLED_BACK})


# ---------------------------------------------------------------------------
# Protocol surface (matches catalog api_signature verbatim)
# ---------------------------------------------------------------------------
@runtime_checkable
class UnitOfWork(Protocol):
    def register_new(self, obj: object) -> None: ...
    def register_dirty(self, obj: object) -> None: ...
    def register_removed(self, obj: object) -> None: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def __enter__(self) -> Self: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> Literal[False]: ...


# ---------------------------------------------------------------------------
# Invariant-violation marker
# ---------------------------------------------------------------------------
class UnitOfWorkInvariantError(RuntimeError):
    """Raised when a UnitOfWork invariant is violated at runtime."""


# ---------------------------------------------------------------------------
# Reference implementation
# ---------------------------------------------------------------------------
class InMemoryUnitOfWork:
    """Reference UnitOfWork that tracks changes in memory and flushes on commit.

    The flush target is a pluggable callable (``flush_fn``) that accepts the
    three ordered buckets and performs the actual transaction — SQL, ORM,
    mock, etc. Ordering is always: new, dirty, removed.
    """

    def __init__(
        self,
        flush_fn: Callable[[list[object], list[object], list[object]], None] | None = None,
    ) -> None:
        self._flush_fn = flush_fn or (lambda _n, _d, _r: None)
        self._new: list[object] = []
        self._dirty: list[object] = []
        self._removed: list[object] = []
        self._new_ids: set[int] = set()
        self._dirty_ids: set[int] = set()
        self._removed_ids: set[int] = set()
        self._state: str = _STATE_OPEN
        self._lock = threading.Lock()
        self._before_commit: list[Callable[[InMemoryUnitOfWork], None]] = []
        self._on_commit: list[Callable[[InMemoryUnitOfWork], None]] = []
        self._after_commit: list[Callable[[InMemoryUnitOfWork], None]] = []

    # ----- registration API --------------------------------------------------
    def register_new(self, obj: object) -> None:
        self._guard_open()
        oid = id(obj)
        with self._lock:
            if oid in self._new_ids or oid in self._dirty_ids or oid in self._removed_ids:
                raise UnitOfWorkInvariantError(
                    "UOW-INV-02: object already registered in another bucket; "
                    "the same instance CANNOT appear twice inside one unit."
                )
            self._new.append(obj)
            self._new_ids.add(oid)

    def register_dirty(self, obj: object) -> None:
        self._guard_open()
        oid = id(obj)
        with self._lock:
            if oid in self._new_ids or oid in self._dirty_ids or oid in self._removed_ids:
                raise UnitOfWorkInvariantError(
                    "UOW-INV-02: object already registered; dirty registration rejected."
                )
            self._dirty.append(obj)
            self._dirty_ids.add(oid)

    def register_removed(self, obj: object) -> None:
        self._guard_open()
        oid = id(obj)
        with self._lock:
            if oid in self._new_ids or oid in self._dirty_ids or oid in self._removed_ids:
                raise UnitOfWorkInvariantError(
                    "UOW-INV-02: object already registered; removed registration rejected."
                )
            self._removed.append(obj)
            self._removed_ids.add(oid)

    # ----- hook registration (extension point) ------------------------------
    def register_before_commit(self, fn: Callable[[InMemoryUnitOfWork], None]) -> None:
        self._guard_open()
        self._before_commit.append(fn)

    def register_on_commit(self, fn: Callable[[InMemoryUnitOfWork], None]) -> None:
        self._guard_open()
        self._on_commit.append(fn)

    def register_after_commit(self, fn: Callable[[InMemoryUnitOfWork], None]) -> None:
        self._guard_open()
        self._after_commit.append(fn)

    # ----- lifecycle ---------------------------------------------------------
    def commit(self) -> None:
        self._guard_open()
        # Snapshot ordered buckets under lock; flush outside the lock so
        # application code does not deadlock on the unit's own lock.
        with self._lock:
            new_list = list(self._new)
            dirty_list = list(self._dirty)
            removed_list = list(self._removed)
        try:
            for h in self._before_commit:
                h(self)
            self._flush_fn(new_list, dirty_list, removed_list)
            for h in self._on_commit:
                h(self)
            self._state = _STATE_COMMITTED
            for h in self._after_commit:
                h(self)
        except BaseException:
            # UOW-INV-01: any exception rolls back and discards tracked changes.
            self._do_rollback()
            raise

    def rollback(self) -> None:
        if self._state in _TERMINAL_STATES:
            # UOW-INV-03: post-terminal rollback is a no-op (nothing to undo).
            return
        self._do_rollback()

    def _do_rollback(self) -> None:
        with self._lock:
            self._new.clear()
            self._dirty.clear()
            self._removed.clear()
            self._new_ids.clear()
            self._dirty_ids.clear()
            self._removed_ids.clear()
            self._state = _STATE_ROLLED_BACK

    # ----- context-manager semantics (UOW-INV-04) ---------------------------
    def __enter__(self) -> Self:
        # A fresh unit is required — reusing a terminal unit is forbidden.
        if self._state in _TERMINAL_STATES:
            raise UnitOfWorkInvariantError(
                "UOW-INV-03: UnitOfWork is terminal and CANNOT be reused; open a fresh unit."
            )
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> Literal[False]:
        if exc_type is not None:
            # On exception, UOW-INV-04: rollback and let the exception propagate.
            if self._state not in _TERMINAL_STATES:
                self._do_rollback()
            return False
        # Normal exit without explicit commit → conservative rollback so partial
        # units NEVER silently leak mutations.
        if self._state not in _TERMINAL_STATES:
            self._do_rollback()
        return False

    # ----- introspection -----------------------------------------------------
    @property
    def state(self) -> str:
        return self._state

    @property
    def new_snapshot(self) -> tuple[object, ...]:
        with self._lock:
            return tuple(self._new)

    @property
    def dirty_snapshot(self) -> tuple[object, ...]:
        with self._lock:
            return tuple(self._dirty)

    @property
    def removed_snapshot(self) -> tuple[object, ...]:
        with self._lock:
            return tuple(self._removed)

    # ----- guard helpers -----------------------------------------------------
    def _guard_open(self) -> None:
        if self._state in _TERMINAL_STATES:
            raise UnitOfWorkInvariantError(
                f"UOW-INV-03: UnitOfWork is {self._state}; a fresh unit MUST be opened."
            )


# ---------------------------------------------------------------------------
# Repository enlistment helper (UOW-INV-05)
# ---------------------------------------------------------------------------
class EnlistingRepository:
    """Minimal repository that ALWAYS enlists writes with a UnitOfWork.

    Direct writes bypassing the unit are FORBIDDEN; this helper demonstrates
    the contract for downstream repositories.
    """

    def __init__(self, uow: InMemoryUnitOfWork) -> None:
        self._uow = uow
        self._store: dict[int, Any] = {}

    def add(self, entity: Any) -> None:
        self._uow.register_new(entity)
        self._store[id(entity)] = entity

    def mark_dirty(self, entity: Any) -> None:
        self._uow.register_dirty(entity)

    def remove(self, entity: Any) -> None:
        self._uow.register_removed(entity)
        self._store.pop(id(entity), None)

    def direct_write(self, entity: Any) -> None:
        # UOW-INV-05: ALWAYS refuse direct writes that bypass the unit.
        raise UnitOfWorkInvariantError(
            "UOW-INV-05: direct_write is FORBIDDEN; repositories MUST enlist with the UnitOfWork."
        )


__all__ = [
    "EnlistingRepository",
    "InMemoryUnitOfWork",
    "UnitOfWork",
    "UnitOfWorkInvariantError",
]
