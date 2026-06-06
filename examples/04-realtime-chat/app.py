"""Realtime chat — room stream + per-connection offset + graceful drain.

Self-contained demo of the `TopicBus` + `SessionCache` + `GracefulShutdown`
recipe. Synchronous primitives are used for test clarity; the production
version is async under `core/venous/`.
"""
from __future__ import annotations

import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from itertools import count
from typing import Iterable


@dataclass(frozen=True)
class Message:
    offset: int
    room: str
    sender: str
    body: str


class RoomStream:
    """Mirror of `StreamSubject` + `TopicBus` — monotonic offsets, per-room."""

    def __init__(self) -> None:
        self._log: dict[str, list[Message]] = defaultdict(list)
        self._ids = defaultdict(lambda: count(1))
        self._lock = threading.Lock()

    def publish(self, room: str, sender: str, body: str) -> Message:
        with self._lock:
            msg = Message(offset=next(self._ids[room]), room=room, sender=sender, body=body)
            self._log[room].append(msg)
            return msg

    def replay(self, room: str, *, since: int) -> list[Message]:
        with self._lock:
            return [m for m in self._log[room] if m.offset > since]


@dataclass
class SessionEntry:
    last_offset: int
    expires_at: float


class OffsetCache:
    """Mirror of `SessionCache` primitive — TTL-bounded per-connection offset."""

    def __init__(self, *, ttl_s: float = 30.0) -> None:
        self.ttl_s = ttl_s
        self._entries: dict[str, SessionEntry] = {}
        self._lock = threading.Lock()

    def set(self, conn_id: str, offset: int, *, now: float) -> None:
        with self._lock:
            self._entries[conn_id] = SessionEntry(
                last_offset=offset, expires_at=now + self.ttl_s,
            )

    def get(self, conn_id: str, *, now: float) -> int | None:
        with self._lock:
            e = self._entries.get(conn_id)
            if e is None or e.expires_at <= now:
                return None
            return e.last_offset


class ConnectionBulkhead:
    """Mirror of `Bulkhead` primitive — caps concurrent conns per `(user, room)`."""

    def __init__(self, *, max_per_room: int) -> None:
        self.max_per_room = max_per_room
        self._open: dict[tuple[str, str], int] = defaultdict(int)
        self._lock = threading.Lock()

    def open(self, user: str, room: str) -> bool:
        with self._lock:
            if self._open[(user, room)] >= self.max_per_room:
                return False
            self._open[(user, room)] += 1
            return True

    def close(self, user: str, room: str) -> None:
        with self._lock:
            self._open[(user, room)] = max(0, self._open[(user, room)] - 1)


class DrainCoordinator:
    """Mirror of `GracefulShutdown` primitive.

    Invariant: once ``begin_drain()`` is called, every subsequent ``publish()``
    call via the coordinator emits a ``reconnect`` hint before returning.
    """

    def __init__(self) -> None:
        self._draining = False
        self._hints: list[str] = []
        self._lock = threading.Lock()

    def begin_drain(self, connections: Iterable[str]) -> None:
        with self._lock:
            self._draining = True
            self._hints.extend(connections)

    def drained_hints(self) -> list[str]:
        with self._lock:
            return list(self._hints)

    @property
    def draining(self) -> bool:
        return self._draining
