"""OptimisticConcurrency primitive — compare-and-swap with version tokens.

Writers read ``(value, version)``; write with
``compare_and_swap(key, old_version, new_value)`` which atomically succeeds
iff the stored version still equals ``old_version``. Mismatch raises
``ConcurrencyError`` — the caller retries through a retry primitive.

Invariant IDs (full text in ``OptimisticConcurrency.md``):

- OC_INV_01: ``compare_and_swap`` atomically checks old_version AND writes
  OR raises; no partial update.
- OC_INV_02: Writer MUST retry on conflict ONLY via the retry primitive
  (no hidden retry here).
- OC_INV_03: Version is monotonic and gap-free per key (next = prev + 1).
- OC_INV_04: Readers never observe a torn write (read returns full value
  atomic with its version).
- OC_INV_05: ``read(k)`` of an unknown key returns ``(None, 0)`` — canonical
  empty, never raises.
"""

from __future__ import annotations

import threading
from typing import Any, Generic, Protocol, TypeVar, runtime_checkable

V = TypeVar("V")


class OptimisticConcurrencyError(RuntimeError):
    """Base error for CAS contract violations."""


class ConcurrencyError(OptimisticConcurrencyError):
    """Raised when compare_and_swap sees a stale old_version."""

    def __init__(
        self, key: str, expected_version: int, actual_version: int
    ) -> None:
        super().__init__(
            f"CAS conflict on key={key!r}: expected v{expected_version}, "
            f"store at v{actual_version}"
        )
        self.key = key
        self.expected_version = expected_version
        self.actual_version = actual_version


@runtime_checkable
class OptimisticConcurrency(Protocol[V]):
    def read(self, key: str) -> tuple[V | None, int]: ...
    def compare_and_swap(
        self, key: str, old_version: int, new_value: V
    ) -> int: ...


class InMemoryOptimisticConcurrency(Generic[V]):
    """Reference CAS store — threading.Lock-guarded dict."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[Any, int]] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public Protocol
    # ------------------------------------------------------------------
    def read(self, key: str) -> tuple[V | None, int]:
        """OC_INV_04 + OC_INV_05: atomic snapshot; missing → (None, 0)."""
        if not isinstance(key, str):
            raise OptimisticConcurrencyError("key MUST be a str")
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return (None, 0)
            # Return a tuple — outside-the-lock mutation of the store does
            # not affect this snapshot.
            value, version = entry
            return (value, version)

    def compare_and_swap(
        self, key: str, old_version: int, new_value: V
    ) -> int:
        """Atomically write iff stored version == old_version; return new version.

        OC_INV_01: atomic check-and-write.
        OC_INV_03: returns old_version + 1 (monotonic, gap-free).
        """
        if not isinstance(key, str) or not key:
            raise OptimisticConcurrencyError("key MUST be a non-empty str")
        if not isinstance(old_version, int) or old_version < 0:
            raise OptimisticConcurrencyError(
                "old_version MUST be a non-negative int"
            )
        with self._lock:
            entry = self._store.get(key)
            stored_version = 0 if entry is None else entry[1]
            if stored_version != old_version:
                raise ConcurrencyError(key, old_version, stored_version)
            new_version = old_version + 1
            self._store[key] = (new_value, new_version)
            return new_version


__all__ = [
    "ConcurrencyError",
    "InMemoryOptimisticConcurrency",
    "OptimisticConcurrency",
    "OptimisticConcurrencyError",
]
