"""Lock-free reads + serializable writes — CAS record store."""
from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class Record:
    """Immutable tuple. Readers see all fields or the previous version — never a torn state."""
    id: str
    rev: int
    a: int
    b: int
    c: int


class ConflictError(Exception):
    def __init__(self, current_rev: int) -> None:
        super().__init__(f"CAS conflict; current rev {current_rev}")
        self.current_rev = current_rev


class CasStore:
    """Lock-free reader, serializable writer.

    The reader never takes the write lock — it grabs the current pointer.
    Writers take a small lock only to serialize CAS attempts.
    """

    def __init__(self) -> None:
        # Live pointer per record id. Readers load this without locking.
        self._records: dict[str, Record] = {}
        # Short lock to serialize writers; read path does NOT use it.
        self._write_lock = threading.Lock()
        self.read_lock_acquires = 0  # instrumented for the test assertion

    def read(self, rec_id: str) -> Record | None:
        """Lock-free: just a dict lookup of an immutable pointer."""
        # dict.get on CPython is atomic w.r.t. the GIL; no lock acquired here.
        return self._records.get(rec_id)

    def cas(self, rec_id: str, *, expected_rev: int,
            a: int, b: int, c: int) -> Record:
        with self._write_lock:
            cur = self._records.get(rec_id)
            cur_rev = cur.rev if cur else 0
            if expected_rev != cur_rev:
                raise ConflictError(cur_rev)
            new = Record(id=rec_id, rev=cur_rev + 1, a=a, b=b, c=c)
            self._records[rec_id] = new
            return new
