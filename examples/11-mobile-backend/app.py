"""Mobile backend — sync cursor, push registry, batch mutations."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from itertools import count
from typing import Callable


@dataclass
class Record:
    id: str
    value: dict
    rev: int


class ConflictError(Exception):
    def __init__(self, current_rev: int) -> None:
        super().__init__(f"conflict; current rev {current_rev}")
        self.current_rev = current_rev


class SyncStore:
    """OptimisticConcurrency-backed record store with a monotonic global rev."""

    def __init__(self) -> None:
        self._records: dict[str, Record] = {}
        self._revs = count(1)
        self._lock = threading.Lock()

    def write(self, rec_id: str, value: dict, *, expected_rev: int) -> Record:
        with self._lock:
            current = self._records.get(rec_id)
            current_rev = current.rev if current else 0
            if expected_rev != current_rev:
                raise ConflictError(current_rev)
            new_rev = next(self._revs)
            r = Record(id=rec_id, value=dict(value), rev=new_rev)
            self._records[rec_id] = r
            return r

    def get(self, rec_id: str) -> Record | None:
        with self._lock:
            r = self._records.get(rec_id)
            return None if r is None else Record(r.id, dict(r.value), r.rev)

    def since(self, cursor: int) -> list[Record]:
        with self._lock:
            changed = [r for r in self._records.values() if r.rev > cursor]
            return sorted(changed, key=lambda r: r.rev)


class DeviceRegistry:
    """Per-user push-token set with stale-token pruning."""

    def __init__(self, send: Callable[[str, str], str]) -> None:
        self._send = send
        self._tokens: dict[str, set[str]] = {}
        self._lock = threading.Lock()

    def register(self, user: str, token: str) -> None:
        with self._lock:
            self._tokens.setdefault(user, set()).add(token)

    def unregister(self, user: str, token: str) -> None:
        with self._lock:
            self._tokens.get(user, set()).discard(token)

    def tokens(self, user: str) -> set[str]:
        with self._lock:
            return set(self._tokens.get(user, set()))

    def push(self, user: str, message: str) -> tuple[int, int]:
        """Returns (delivered, pruned)."""
        delivered = 0
        pruned = 0
        for tok in list(self.tokens(user)):
            status = self._send(tok, message)
            if status == "ok":
                delivered += 1
            elif status in ("stale", "unregistered"):
                with self._lock:
                    self._tokens.get(user, set()).discard(tok)
                pruned += 1
        return delivered, pruned


@dataclass
class BatchItem:
    rec_id: str
    value: dict
    expected_rev: int


@dataclass
class BatchResult:
    ok: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)


def apply_batch(store: SyncStore, items: list[BatchItem]) -> BatchResult:
    """All-or-nothing: on ANY conflict, none of the batch lands.

    If all items validate (right expected_rev, no duplicate ids), commit them
    and return ok. Otherwise return precise per-item errors.
    """
    result = BatchResult()
    seen_ids: set[str] = set()
    # Pre-validate: every item must have a non-conflicting rev + unique id.
    with store._lock:
        for item in items:
            if item.rec_id in seen_ids:
                result.errors[item.rec_id] = "duplicate id in batch"
                continue
            seen_ids.add(item.rec_id)
            cur = store._records.get(item.rec_id)
            cur_rev = cur.rev if cur else 0
            if item.expected_rev != cur_rev:
                result.errors[item.rec_id] = f"conflict; current rev {cur_rev}"
        if result.errors:
            return result  # Nothing committed.
        # All good — commit atomically.
        for item in items:
            new_rev = next(store._revs)
            store._records[item.rec_id] = Record(
                id=item.rec_id, value=dict(item.value), rev=new_rev,
            )
            result.ok.append(item.rec_id)
    return result
