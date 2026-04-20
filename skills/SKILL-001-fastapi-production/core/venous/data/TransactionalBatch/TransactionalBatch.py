"""TransactionalBatch primitive — atomic multi-key upsert/delete unit.

Implements the catalog Protocol for `data.TransactionalBatch`. Zero I/O at
import. The reference implementation holds an ordered operation list, applies
it atomically to an injected in-memory store under an internal per-batch
"transaction", and surfaces a conflict error on any etag mismatch.

Invariant IDs cited by this module:

- TXB-INV-01: commit MUST apply every queued operation atomically or apply
  none of them, with no partial visible state.
- TXB-INV-02: a conflicting etag on any queued operation MUST abort the
  entire batch and surface a conflict error.
- TXB-INV-03: after commit returns successfully the batch MUST NOT be
  reusable; reusing it SHALL raise a state error.
- TXB-INV-04: operations inside one batch ALWAYS target the same state store
  instance to preserve the atomicity boundary.
- TXB-INV-05: read operations are FORBIDDEN inside the batch because the
  contract covers only writes and deletes.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum
from typing import Final, Literal, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MAX_OPS_PER_BATCH: Final[int] = 1000


# ---------------------------------------------------------------------------
# Exception taxonomy
# ---------------------------------------------------------------------------
class TransactionalBatchError(ValueError):
    """Raised when a call violates a TransactionalBatch invariant."""


class BatchStateError(RuntimeError):
    """Raised for illegal reuse of a committed/aborted batch (TXB-INV-03)."""


class EtagConflictError(RuntimeError):
    """Raised when any queued op conflicts on etag (TXB-INV-02)."""

    def __init__(self, key: str, expected: str | None, actual: str | None) -> None:
        super().__init__(
            f"TXB-INV-02: etag conflict on key {key!r}: expected {expected!r}, actual {actual!r}."
        )
        self.key = key
        self.expected = expected
        self.actual = actual


# ---------------------------------------------------------------------------
# Core types
# ---------------------------------------------------------------------------
class BatchState(Enum):
    OPEN = "open"
    COMMITTED = "committed"
    ABORTED = "aborted"


@dataclass
class _Op:
    op: Literal["upsert", "delete"]
    key: str
    value: bytes | None
    etag: str | None


# ---------------------------------------------------------------------------
# Backing store Protocol (mirrors Dapr state store semantics)
# ---------------------------------------------------------------------------
@runtime_checkable
class StateStore(Protocol):
    def get_with_etag(self, key: str) -> tuple[bytes | None, str | None]: ...
    def apply_transaction(self, ops: list[_Op]) -> None: ...


# ---------------------------------------------------------------------------
# Reference in-memory store
# ---------------------------------------------------------------------------
class InMemoryStateStore:
    """Thread-safe in-memory KV store with etag semantics."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[bytes, str]] = {}
        self._lock = threading.RLock()
        self._rev: int = 0

    def _next_etag(self) -> str:
        self._rev += 1
        return f"rev-{self._rev}"

    def get_with_etag(self, key: str) -> tuple[bytes | None, str | None]:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return (None, None)
            return entry

    def apply_transaction(self, ops: list[_Op]) -> None:
        """TXB-INV-01: atomic apply. Snapshot check under the lock; on any
        conflict abort with EtagConflictError BEFORE mutating."""
        with self._lock:
            for op in ops:
                current = self._data.get(op.key)
                current_etag = current[1] if current is not None else None
                if op.etag is not None and op.etag != current_etag:
                    raise EtagConflictError(
                        key=op.key, expected=op.etag, actual=current_etag,
                    )
            for op in ops:
                if op.op == "upsert":
                    if op.value is None:
                        raise TransactionalBatchError(
                            f"TXB-INV-01 supporting: upsert for {op.key!r} MUST supply bytes value."
                        )
                    self._data[op.key] = (bytes(op.value), self._next_etag())
                elif op.op == "delete":
                    self._data.pop(op.key, None)
                else:
                    raise TransactionalBatchError(
                        f"TXB-INV-01 supporting: unknown op kind {op.op!r}."
                    )

    # Introspection for tests only — NOT part of the catalog surface.
    def snapshot(self) -> dict[str, bytes]:
        with self._lock:
            return {k: v[0] for k, v in self._data.items()}


# ---------------------------------------------------------------------------
# The batch itself (the catalog's `TransactionalBatch` Protocol)
# ---------------------------------------------------------------------------
@runtime_checkable
class TransactionalBatch(Protocol):
    def upsert(self, key: str, value: bytes, etag: str | None = None) -> TransactionalBatch: ...
    def delete(self, key: str, etag: str | None = None) -> TransactionalBatch: ...
    async def commit(self) -> None: ...


class InMemoryTransactionalBatch:
    """Reference implementation bound to exactly one StateStore (TXB-INV-04)."""

    def __init__(self, store: StateStore) -> None:
        self._store: StateStore = store
        self._ops: list[_Op] = []
        self._state: BatchState = BatchState.OPEN

    # ----- catalog API -------------------------------------------------------
    def upsert(
        self, key: str, value: bytes, etag: str | None = None,
    ) -> InMemoryTransactionalBatch:
        self._require_open("upsert")
        self._check_key_value(key, value)
        self._ops.append(_Op(op="upsert", key=key, value=bytes(value), etag=etag))
        self._enforce_op_cap()
        return self

    def delete(self, key: str, etag: str | None = None) -> InMemoryTransactionalBatch:
        self._require_open("delete")
        if not isinstance(key, str) or not key:
            raise TransactionalBatchError(
                "TXB-INV-01 supporting: key MUST be non-empty str."
            )
        self._ops.append(_Op(op="delete", key=key, value=None, etag=etag))
        self._enforce_op_cap()
        return self

    async def commit(self) -> None:
        self._require_open("commit")
        try:
            self._store.apply_transaction(list(self._ops))
        except Exception:
            self._state = BatchState.ABORTED
            raise
        self._state = BatchState.COMMITTED

    # ----- inspection --------------------------------------------------------
    @property
    def state(self) -> BatchState:
        return self._state

    @property
    def op_count(self) -> int:
        return len(self._ops)

    # ----- helpers -----------------------------------------------------------
    def _require_open(self, verb: str) -> None:
        if self._state is not BatchState.OPEN:
            raise BatchStateError(
                f"TXB-INV-03: batch is {self._state.value}; cannot {verb} on a closed batch."
            )

    @staticmethod
    def _check_key_value(key: str, value: bytes) -> None:
        if not isinstance(key, str) or not key:
            raise TransactionalBatchError(
                "TXB-INV-01 supporting: key MUST be non-empty str."
            )
        if not isinstance(value, (bytes, bytearray, memoryview)):
            raise TransactionalBatchError(
                f"TXB-INV-01 supporting: value MUST be bytes, got {type(value).__name__}."
            )

    def _enforce_op_cap(self) -> None:
        if len(self._ops) > MAX_OPS_PER_BATCH:
            raise TransactionalBatchError(
                f"TXB-INV-01 supporting: batch MUST NOT exceed {MAX_OPS_PER_BATCH} ops."
            )


# Module also refuses to expose a `get` / `read` / `scan` method on the batch —
# TXB-INV-05 is enforced by ABSENCE. Tests assert the public surface has no
# read methods.


__all__ = [
    "MAX_OPS_PER_BATCH",
    "BatchState",
    "BatchStateError",
    "EtagConflictError",
    "InMemoryStateStore",
    "InMemoryTransactionalBatch",
    "StateStore",
    "TransactionalBatch",
    "TransactionalBatchError",
]
