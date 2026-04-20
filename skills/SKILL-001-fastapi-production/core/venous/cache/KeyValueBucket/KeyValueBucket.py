"""KeyValueBucket primitive — compare-and-swap bucket with watch channel.

Mirrors the catalog Protocol for `cache.KeyValueBucket`. Module load performs
zero I/O; lazy imports hide optional backends (JetStream / etcd).

Invariant IDs cited by this module:

- KVB_INV_01: create MUST fail when the key already exists; it NEVER
  overwrites a present value.
- KVB_INV_02: update MUST fail when the supplied revision does not match the
  stored revision (compare-and-swap semantics).
- KVB_INV_03: Every successful write ALWAYS increases the entry revision
  monotonically.
- KVB_INV_04: Watch channels SHALL emit changes in revision order for a given
  key and CANNOT skip a revision without an explicit gap signal.
- KVB_INV_05: Deleting a key NEVER frees its historical revisions if history
  retention is configured greater than one.
"""

from __future__ import annotations

import threading
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Final, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MIN_HISTORY: Final[int] = 1
DEFAULT_HISTORY: Final[int] = 5


# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------
class KeyValueBucketError(Exception):
    """Base for KeyValueBucket invariant violations."""


class KeyAlreadyExistsError(KeyValueBucketError):
    """KVB_INV_01: create on an existing key is rejected."""


class RevisionMismatchError(KeyValueBucketError):
    """KVB_INV_02: compare-and-swap rejected because revision drifted."""


# ---------------------------------------------------------------------------
# Catalog data shape
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class KvEntry:
    """A snapshot of a bucket entry at one revision."""

    key: str
    value: bytes
    revision: int


# ---------------------------------------------------------------------------
# Protocol surface (mirrors catalog api_signature)
# ---------------------------------------------------------------------------
@runtime_checkable
class KeyValueBucket(Protocol):
    async def create(self, key: str, value: bytes) -> KvEntry: ...
    async def update(self, key: str, value: bytes, revision: int) -> KvEntry: ...
    async def get(self, key: str) -> KvEntry | None: ...
    async def delete(self, key: str, revision: int | None = None) -> None: ...
    def watch(self, key: str) -> AsyncIterator[KvEntry]: ...


# ---------------------------------------------------------------------------
# Reference implementation — in-memory, history-bounded
# ---------------------------------------------------------------------------
class InMemoryKeyValueBucket:
    """Reference KeyValueBucket.

    Stores at most `history` recent revisions per key, including tombstones for
    deletes. Non-async-native: wraps sync state in async methods for contract
    conformance.
    """

    def __init__(self, history: int = DEFAULT_HISTORY) -> None:
        if history < MIN_HISTORY:
            raise ValueError(
                f"history MUST be >= {MIN_HISTORY}, got {history}.",
            )
        self._history: int = history
        self._lock = threading.Lock()
        # key -> list[KvEntry]; most recent last. Deletes append a tombstone
        # with value=b"" and a new revision.
        self._store: dict[str, list[KvEntry]] = {}
        self._tombstoned: set[str] = set()
        self._next_rev: int = 0
        self._watchers: dict[str, list[list[KvEntry]]] = {}

    def _validate_key(self, key: str) -> None:
        if not isinstance(key, str) or not key:
            raise KeyValueBucketError("key MUST be a non-empty string.")
        if "\x00" in key:
            raise KeyValueBucketError("key MUST NOT contain null bytes.")

    def _allocate_revision(self) -> int:
        """KVB_INV_03: monotonically increasing global revision."""
        self._next_rev += 1
        return self._next_rev

    def _fanout(self, key: str, entry: KvEntry) -> None:
        """KVB_INV_04: watchers receive entries in revision order."""
        for inbox in self._watchers.get(key, []):
            inbox.append(entry)

    async def create(self, key: str, value: bytes) -> KvEntry:
        self._validate_key(key)
        with self._lock:
            history = self._store.get(key)
            # A key with only tombstones (no active value) IS re-creatable.
            if history and not self._is_tombstoned(history):
                raise KeyAlreadyExistsError(
                    f"KVB_INV_01: key {key!r} already exists at "
                    f"revision {history[-1].revision}.",
                )
            rev = self._allocate_revision()
            entry = KvEntry(key=key, value=value, revision=rev)
            self._store.setdefault(key, []).append(entry)
            self._trim(key)
            self._tombstoned.discard(key)
            self._fanout(key, entry)
            return entry

    async def update(
        self, key: str, value: bytes, revision: int,
    ) -> KvEntry:
        self._validate_key(key)
        with self._lock:
            history = self._store.get(key)
            if not history or self._is_tombstoned(history):
                raise KeyValueBucketError(
                    f"KVB_INV_02: update rejected — key {key!r} does not exist.",
                )
            current = history[-1]
            if current.revision != revision:
                raise RevisionMismatchError(
                    f"KVB_INV_02: expected revision {current.revision}, "
                    f"got {revision} for key {key!r}.",
                )
            rev = self._allocate_revision()
            entry = KvEntry(key=key, value=value, revision=rev)
            history.append(entry)
            self._trim(key)
            self._fanout(key, entry)
            return entry

    async def get(self, key: str) -> KvEntry | None:
        self._validate_key(key)
        with self._lock:
            history = self._store.get(key)
            if not history or self._is_tombstoned(history):
                return None
            return history[-1]

    async def delete(
        self, key: str, revision: int | None = None,
    ) -> None:
        self._validate_key(key)
        with self._lock:
            history = self._store.get(key)
            if not history or self._is_tombstoned(history):
                return
            current = history[-1]
            if revision is not None and current.revision != revision:
                raise RevisionMismatchError(
                    f"KVB_INV_02: delete rejected — expected revision "
                    f"{current.revision}, got {revision} for key {key!r}.",
                )
            rev = self._allocate_revision()
            # KVB_INV_05: append tombstone, retain prior history entries.
            tombstone = KvEntry(key=key, value=b"", revision=rev)
            history.append(tombstone)
            self._tombstoned.add(key)
            self._trim(key)
            self._fanout(key, tombstone)

    def watch(self, key: str) -> AsyncIterator[KvEntry]:
        """Return an async iterator replaying current history in revision order.

        **Reference-impl limitation (explicit):** this primitive is REPLAY-ONLY.
        The iterator yields the snapshot of history at subscription time plus
        any entries appended while the synchronous loop has not yet drained;
        once exhausted, the generator returns. It is NOT a live stream.

        A production backend (etcd/Consul/DynamoDB-Streams) MUST wrap the
        broker with an `asyncio.Queue` + `Condition.notify` fanout so late
        subscribers also receive revisions appended after their subscribe.
        KVB_INV_04 ("no revision skipped") holds for the replay window only.
        """
        self._validate_key(key)
        with self._lock:
            inbox: list[KvEntry] = list(self._store.get(key, []))
            self._watchers.setdefault(key, []).append(inbox)

        async def _stream() -> AsyncIterator[KvEntry]:
            for entry in inbox:
                yield entry

        return _stream()

    # ---- internal helpers ------------------------------------------------
    def _is_tombstoned(self, history: list[KvEntry]) -> bool:
        if not history:
            return True
        last = history[-1]
        return last.key in self._tombstoned and last.value == b""

    def _trim(self, key: str) -> None:
        """KVB_INV_05: retain up to `history` entries per key."""
        history = self._store.get(key, [])
        if len(history) > self._history:
            drop = len(history) - self._history
            self._store[key] = history[drop:]

    # ---- observability ---------------------------------------------------
    def history_depth(self, key: str) -> int:
        with self._lock:
            return len(self._store.get(key, []))

    def current_revision(self) -> int:
        with self._lock:
            return self._next_rev


__all__ = [
    "DEFAULT_HISTORY",
    "MIN_HISTORY",
    "InMemoryKeyValueBucket",
    "KeyAlreadyExistsError",
    "KeyValueBucket",
    "KeyValueBucketError",
    "KvEntry",
    "RevisionMismatchError",
]
