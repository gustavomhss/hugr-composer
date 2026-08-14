"""PersistedQueryRegistry primitive — SHA-256 keyed query allow-list.

Production clients send a 64-char sha-256 id instead of the raw query
string; the server looks the id up in this registry. Unregistered ids are
rejected — a tiny allow-list that shuts down arbitrary-query surface.

Invariant IDs (full text in ``PersistedQueryRegistry.md``):

- PQR_INV_01: Hash id is lowercase sha-256 hex of UTF-8 query bytes;
  registration is idempotent.
- PQR_INV_02: ``get()`` never returns a query whose re-hash differs from
  the id (tamper detection).
- PQR_INV_03: Registry is read-only in production mode; ``register()``
  in prod raises ``PQRImmutableError``.
- PQR_INV_04: Lookup is O(1) in the backing store.
- PQR_INV_05: Callers cannot enumerate registered ids (no public ``list()``).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Protocol, runtime_checkable


class PQRError(RuntimeError):
    """Base error for registry contract violations."""


class PQRImmutableError(PQRError):
    """Raised when register() is invoked while the registry is frozen."""


class PQRTamperError(PQRError):
    """Raised when a stored query's re-hash differs from its stored id."""


@runtime_checkable
class PersistedQueryRegistry(Protocol):
    def register(self, query: str) -> str: ...
    def get(self, query_id: str) -> str | None: ...
    def contains(self, query_id: str) -> bool: ...


SnapshotSink = Callable[[dict[str, str]], None]


class InMemoryPersistedQueryRegistry:
    """Reference implementation — single-process dict backing store."""

    def __init__(
        self,
        *,
        frozen: bool = False,
        snapshot_sink: SnapshotSink | None = None,
    ) -> None:
        self._store: dict[str, str] = {}
        self._frozen: bool = frozen
        self._snapshot_sink: SnapshotSink | None = snapshot_sink

    # ------------------------------------------------------------------
    # Hashing
    # ------------------------------------------------------------------
    @staticmethod
    def hash_query(query: str) -> str:
        """PQR_INV_01: lowercase sha-256 hex of UTF-8 query bytes."""
        if not isinstance(query, str):
            raise PQRError("query MUST be a str")
        return hashlib.sha256(query.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------
    # Public Protocol
    # ------------------------------------------------------------------
    def register(self, query: str) -> str:
        """Add a query to the registry and return its canonical id.

        PQR_INV_03: raises ``PQRImmutableError`` if the registry is frozen.
        Registration is idempotent — repeated calls with the same query
        return the same id and do NOT snapshot again.
        """
        if self._frozen:
            raise PQRImmutableError("PQR_INV_03: registry is frozen; register() forbidden")
        qid = self.hash_query(query)
        if self._store.get(qid) == query:
            return qid  # idempotent — no sink call
        self._store[qid] = query
        if self._snapshot_sink is not None:
            # Copy so the sink cannot mutate internal state.
            self._snapshot_sink(dict(self._store))
        return qid

    def get(self, query_id: str) -> str | None:
        """Return the query for ``query_id`` or ``None``.

        PQR_INV_02: the stored query is re-hashed; mismatch raises.
        PQR_INV_04: dict lookup is O(1).
        """
        if not isinstance(query_id, str):
            raise PQRError("query_id MUST be a str")
        if query_id not in self._store:
            return None
        query = self._store[query_id]
        recomputed = self.hash_query(query)
        if recomputed != query_id:
            raise PQRTamperError(
                f"PQR_INV_02: stored query re-hashes to {recomputed!r}, not {query_id!r}"
            )
        return query

    def contains(self, query_id: str) -> bool:
        return isinstance(query_id, str) and query_id in self._store

    # ------------------------------------------------------------------
    # Mode control
    # ------------------------------------------------------------------
    def freeze(self) -> None:
        """Irreversibly transition to production read-only mode."""
        self._frozen = True

    @property
    def frozen(self) -> bool:
        return self._frozen

    # PQR_INV_05: NO public list() / keys() / __iter__ — callers cannot
    # enumerate registered ids.


__all__ = [
    "InMemoryPersistedQueryRegistry",
    "PQRError",
    "PQRImmutableError",
    "PQRTamperError",
    "PersistedQueryRegistry",
]
