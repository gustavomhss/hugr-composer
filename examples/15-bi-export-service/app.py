"""BI export service — idempotent snapshots, retry cap, health surface."""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class ExportResult:
    table: str
    date: str
    bytes_written: int
    content_hash: str
    attempts: int


class SnapshotView:
    """Snapshot-read surface: capturing state at a point in time.

    Writers can continue hitting the "live" rows while exporters read the
    captured snapshot — no lock contention.
    """

    def __init__(self) -> None:
        self._live: list[dict] = []
        self._snapshots: dict[str, list[dict]] = {}
        self._live_lock = threading.Lock()

    def write_live(self, row: dict) -> None:
        with self._live_lock:
            self._live.append(dict(row))

    def capture(self, date: str) -> None:
        """Copy live rows into a named snapshot. Brief lock for the copy only."""
        with self._live_lock:
            self._snapshots[date] = [dict(r) for r in self._live]

    def read_snapshot(self, date: str) -> list[dict]:
        # Reader does NOT take the live lock — the snapshot is a plain list.
        return list(self._snapshots.get(date, []))


@dataclass
class HealthState:
    last_success_by_table: dict[str, str] = field(default_factory=dict)
    pages_sent: int = 0


class Exporter:
    """Runs a retrying export job and surfaces state on a HealthProbe."""

    def __init__(self, view: SnapshotView, *, max_attempts: int = 3) -> None:
        self._view = view
        self._max_attempts = max_attempts
        self._outputs: dict[tuple[str, str], ExportResult] = {}
        self._running: set[tuple[str, str]] = set()
        self.health = HealthState()
        self._lock = threading.Lock()

    def run(
        self, table: str, date: str, *,
        fetch: Callable[[str, str], list[dict]] | None = None,
        attempt_action: Callable[[int], None] | None = None,
    ) -> ExportResult:
        key = (table, date)
        with self._lock:
            if key in self._running:
                raise RuntimeError("export already running for this key")
            self._running.add(key)
        try:
            last_error: Exception | None = None
            for attempt in range(1, self._max_attempts + 1):
                if attempt_action is not None:
                    try:
                        attempt_action(attempt)
                    except Exception as e:  # simulated transient failure
                        last_error = e
                        continue
                rows = fetch(table, date) if fetch else self._view.read_snapshot(date)
                payload = json.dumps(rows, sort_keys=True).encode()
                result = ExportResult(
                    table=table, date=date,
                    bytes_written=len(payload),
                    content_hash=hashlib.sha256(payload).hexdigest(),
                    attempts=attempt,
                )
                with self._lock:
                    self._outputs[key] = result  # overwrite: idempotent
                    self.health.last_success_by_table[table] = date
                return result
            # All attempts failed — emit ONE page, surface yesterday's success.
            with self._lock:
                self.health.pages_sent += 1
            raise RuntimeError(
                f"export failed after {self._max_attempts} attempts: {last_error}"
            )
        finally:
            with self._lock:
                self._running.discard(key)

    def output_for(self, table: str, date: str) -> ExportResult | None:
        with self._lock:
            return self._outputs.get((table, date))
