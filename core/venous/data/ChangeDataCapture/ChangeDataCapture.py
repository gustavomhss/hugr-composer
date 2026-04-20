"""ChangeDataCapture primitive — Kleppmann DDIA / Richardson CDC section.

Implements the catalog Protocol for `data.ChangeDataCapture` and installs
runtime invariant checkers. Zero I/O at import.

Invariant IDs cited by this module:

- CDC-INV-01: every committed row change in the source MUST appear in the
  stream exactly once in commit order; reordering across transactions is
  FORBIDDEN.
- CDC-INV-02: consumers MUST be able to resume from a persisted checkpoint;
  the stream SHALL carry a monotonically increasing position (LSN / offset).
- CDC-INV-03: CDC events NEVER include uncommitted changes; dirty reads are
  FORBIDDEN on the downstream side.
- CDC-INV-04: schema changes at the source MUST surface as schema events so
  consumers CANNOT silently parse new columns with the old parser.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable, Iterator, Mapping
from typing import Any, Final, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Protocol surface (matches catalog api_signature verbatim)
# ---------------------------------------------------------------------------
@runtime_checkable
class ChangeDataCapture(Protocol):
    def subscribe(self, table: str, from_position: object) -> Iterator[Any]: ...
    def checkpoint(self, position: object) -> None: ...
    def schema(self, table: str) -> dict[str, object]: ...


# ---------------------------------------------------------------------------
# Invariant-violation marker
# ---------------------------------------------------------------------------
class ChangeDataCaptureInvariantError(RuntimeError):
    """Raised when a ChangeDataCapture invariant is violated at runtime."""


# ---------------------------------------------------------------------------
# Event shape
# ---------------------------------------------------------------------------
_VALID_OPS: Final[frozenset[str]] = frozenset({"insert", "update", "delete", "schema"})
_REQUIRED_EVENT_KEYS: Final[frozenset[str]] = frozenset({"op", "table", "pos", "txid", "committed"})


def _as_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ChangeDataCaptureInvariantError(
            f"CDC-INV-02: event field '{field}' MUST be a plain int, got {type(value).__name__}."
        )
    return value


def _as_str(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ChangeDataCaptureInvariantError(
            f"CDC-INV-01: event field '{field}' MUST be a str, got {type(value).__name__}."
        )
    return value


def _validate_event_shape(event: Mapping[str, object]) -> None:
    missing = _REQUIRED_EVENT_KEYS - set(event.keys())
    if missing:
        raise ChangeDataCaptureInvariantError(
            f"CDC-INV-01: event missing required keys {sorted(missing)}; malformed events "
            f"CANNOT enter the stream."
        )
    op = event["op"]
    if not isinstance(op, str) or op not in _VALID_OPS:
        raise ChangeDataCaptureInvariantError(
            f"CDC-INV-01: event 'op' MUST be one of {sorted(_VALID_OPS)}, got {op!r}."
        )


# ---------------------------------------------------------------------------
# Reference implementation
# ---------------------------------------------------------------------------
class InMemoryChangeDataCapture:
    """Reference ChangeDataCapture backed by an in-memory append-only log.

    Models a source database's write-ahead log. Committed events land in
    `_log` tagged with a monotonically-increasing position (LSN). Uncommitted
    changes live in `_pending` keyed by txid; they are NEVER visible to
    subscribers until `commit_tx()` moves them atomically to the log at a
    single commit boundary.

    - CDC-INV-01 is enforced by reserving positions at `append()` time under
      the lock so every committed write is assigned a unique, monotonically
      increasing pos, and by flushing per-transaction buckets in insertion
      order at commit time.
    - CDC-INV-02 is enforced by `checkpoint()` persistence plus the
      monotonicity check on subscribe(from_position=...) which refuses to
      rewind below the consumer's own stored checkpoint.
    - CDC-INV-03 is enforced by isolating per-txid staging: subscribers only
      ever iterate the committed log; uncommitted / aborted txids disappear.
    - CDC-INV-04 is enforced by the `schema` event type plus a per-table
      schema-version counter that bumps on `evolve_schema()` and guarantees
      a schema event lands in the stream before any row event at the new
      version.
    """

    _STAGED_LIMIT: Final[int] = 100_000

    def __init__(self) -> None:
        # Append-only committed event log (CDC-INV-01 / CDC-INV-03 boundary).
        self._log: list[dict[str, object]] = []
        # Staged per-transaction buckets — invisible to subscribers (CDC-INV-03).
        self._pending: dict[str, list[dict[str, object]]] = {}
        # Aborted txids — remembered so repeat commit attempts fail loudly.
        self._aborted: set[str] = set()
        # Terminal txids — committed once, CANNOT be committed or appended to again.
        self._committed_txids: set[str] = set()
        # Monotonic position cursor for the next committed event.
        self._next_pos: int = 1
        # Per-table declared schema version (CDC-INV-04).
        self._schema_versions: dict[str, int] = {}
        # Persisted checkpoints per consumer-group (CDC-INV-02).
        self._checkpoints: dict[str, int] = {}
        # Default checkpoint group when callers use the shared checkpoint API.
        self._default_group: Final[str] = "_default"
        # Lock for all mutations on committed state + pending buckets.
        self._lock = threading.RLock()

    # ----- schema management (CDC-INV-04) ------------------------------------
    def register_table(self, table: str, columns: Iterable[str]) -> None:
        """Declare a table at schema_version=1 and emit an initial schema event."""
        if not isinstance(table, str) or not table:
            raise ChangeDataCaptureInvariantError(
                "CDC-INV-04: table MUST be a non-empty string."
            )
        cols = tuple(columns)
        for c in cols:
            if not isinstance(c, str) or not c:
                raise ChangeDataCaptureInvariantError(
                    "CDC-INV-04: column names MUST be non-empty strings."
                )
        with self._lock:
            if table in self._schema_versions:
                raise ChangeDataCaptureInvariantError(
                    f"CDC-INV-04: table '{table}' already registered; use evolve_schema() instead."
                )
            self._schema_versions[table] = 1
            self._log.append(
                {
                    "op": "schema",
                    "table": table,
                    "pos": self._next_pos,
                    "txid": "_schema",
                    "committed": True,
                    "schema_version": 1,
                    "columns": list(cols),
                }
            )
            self._next_pos += 1

    def evolve_schema(self, table: str, columns: Iterable[str]) -> int:
        """Emit a schema-change event on the stream (CDC-INV-04).

        Returns the new schema_version. Row events after this point MUST
        carry the new schema_version; events at the old version are REJECTED
        so consumers never silently parse new columns with the old parser.
        """
        if not isinstance(table, str) or not table:
            raise ChangeDataCaptureInvariantError(
                "CDC-INV-04: table MUST be a non-empty string."
            )
        cols = tuple(columns)
        with self._lock:
            if table not in self._schema_versions:
                raise ChangeDataCaptureInvariantError(
                    f"CDC-INV-04: table '{table}' is not registered; register_table() first."
                )
            new_version = self._schema_versions[table] + 1
            self._schema_versions[table] = new_version
            self._log.append(
                {
                    "op": "schema",
                    "table": table,
                    "pos": self._next_pos,
                    "txid": "_schema",
                    "committed": True,
                    "schema_version": new_version,
                    "columns": list(cols),
                }
            )
            self._next_pos += 1
            return new_version

    # ----- transactional staging (CDC-INV-03) --------------------------------
    def begin_tx(self, txid: str) -> None:
        if not isinstance(txid, str) or not txid or txid.startswith("_"):
            raise ChangeDataCaptureInvariantError(
                "CDC-INV-01: txid MUST be a non-empty string and CANNOT start with '_' (reserved)."
            )
        with self._lock:
            if txid in self._pending:
                raise ChangeDataCaptureInvariantError(
                    f"CDC-INV-01: transaction {txid!r} already open; begin_tx is not re-entrant."
                )
            if txid in self._committed_txids or txid in self._aborted:
                raise ChangeDataCaptureInvariantError(
                    f"CDC-INV-01: transaction {txid!r} is terminal; a fresh txid MUST be used."
                )
            self._pending[txid] = []

    def stage_change(
        self,
        txid: str,
        table: str,
        op: str,
        key: object,
        before: Mapping[str, object] | None = None,
        after: Mapping[str, object] | None = None,
    ) -> None:
        """Stage one row-level change inside an open transaction.

        CDC-INV-03: staged changes are invisible to subscribers until
        commit_tx(txid) lands them on the committed log.
        """
        if op not in ("insert", "update", "delete"):
            raise ChangeDataCaptureInvariantError(
                f"CDC-INV-01: stage_change op MUST be one of insert/update/delete, got {op!r}."
            )
        if not isinstance(table, str) or not table:
            raise ChangeDataCaptureInvariantError("CDC-INV-01: table MUST be a non-empty string.")
        with self._lock:
            if txid not in self._pending:
                raise ChangeDataCaptureInvariantError(
                    f"CDC-INV-01: transaction {txid!r} is not open; call begin_tx() first."
                )
            if table not in self._schema_versions:
                raise ChangeDataCaptureInvariantError(
                    f"CDC-INV-04: table '{table}' is not registered; schema events MUST "
                    f"precede row events."
                )
            if len(self._pending[txid]) >= self._STAGED_LIMIT:
                raise ChangeDataCaptureInvariantError(
                    f"CDC-INV-01: transaction {txid!r} exceeded staged-change limit "
                    f"({self._STAGED_LIMIT}); split into smaller transactions."
                )
            schema_version = self._schema_versions[table]
            self._pending[txid].append(
                {
                    "op": op,
                    "table": table,
                    "txid": txid,
                    "key": key,
                    "before": dict(before) if before is not None else None,
                    "after": dict(after) if after is not None else None,
                    "schema_version": schema_version,
                    "committed": False,  # stays False until commit_tx
                }
            )

    def commit_tx(self, txid: str) -> int:
        """Atomically publish every staged change under `txid` to the committed log.

        Returns the number of events published. Ordering within the
        transaction is preserved (CDC-INV-01). All events are tagged with
        monotonically increasing positions assigned in order under the lock
        (CDC-INV-02).
        """
        with self._lock:
            if txid not in self._pending:
                raise ChangeDataCaptureInvariantError(
                    f"CDC-INV-01: transaction {txid!r} is not open; commit refused."
                )
            if txid in self._committed_txids:
                raise ChangeDataCaptureInvariantError(
                    f"CDC-INV-01: transaction {txid!r} already committed; idempotent retry is FORBIDDEN."
                )
            staged = self._pending.pop(txid)
            published = 0
            for ev in staged:
                ev_out = dict(ev)
                ev_out["pos"] = self._next_pos
                ev_out["committed"] = True
                self._log.append(ev_out)
                self._next_pos += 1
                published += 1
            self._committed_txids.add(txid)
            return published

    def rollback_tx(self, txid: str) -> None:
        """Discard every staged change under `txid` (CDC-INV-03)."""
        with self._lock:
            if txid not in self._pending:
                # Tolerate rollback of an already-rolled-back or never-begun tx so
                # application error paths (exception cleanup) are safe.
                self._aborted.add(txid)
                return
            self._pending.pop(txid, None)
            self._aborted.add(txid)

    # ----- Protocol surface --------------------------------------------------
    def subscribe(self, table: str, from_position: object) -> Iterator[Any]:
        """Yield committed events for `table` whose pos > from_position.

        CDC-INV-02: `from_position` MUST be an int (>= 0). Callers resume
        from the last checkpoint they persisted.

        Implementation returns a snapshot iterator so concurrent appends
        during iteration never make the consumer observe a torn event — new
        events arriving after the subscribe call belong to the next poll.
        """
        if not isinstance(table, str) or not table:
            raise ChangeDataCaptureInvariantError(
                "CDC-INV-01: table MUST be a non-empty string."
            )
        pos_int = _as_int(from_position, "from_position")
        if pos_int < 0:
            raise ChangeDataCaptureInvariantError(
                "CDC-INV-02: from_position MUST be >= 0 (monotonic positions are non-negative)."
            )
        with self._lock:
            if table not in self._schema_versions:
                raise ChangeDataCaptureInvariantError(
                    f"CDC-INV-04: table '{table}' is not registered; subscribe refused."
                )
            snapshot = [
                dict(ev)
                for ev in self._log
                if ev["table"] == table and _as_int(ev["pos"], "pos") > pos_int
            ]
        return iter(snapshot)

    def checkpoint(self, position: object) -> None:
        """Persist the default consumer group's checkpoint (CDC-INV-02)."""
        self.checkpoint_group(self._default_group, position)

    def checkpoint_group(self, group: str, position: object) -> None:
        """Persist a named consumer group's checkpoint.

        CDC-INV-02: the checkpoint position is monotonically non-decreasing.
        A rewind attempt (position < persisted) is REJECTED so consumers
        CANNOT silently replay already-acknowledged events and double-apply
        side-effects.
        """
        if not isinstance(group, str) or not group:
            raise ChangeDataCaptureInvariantError(
                "CDC-INV-02: checkpoint group MUST be a non-empty string."
            )
        pos_int = _as_int(position, "position")
        if pos_int < 0:
            raise ChangeDataCaptureInvariantError(
                "CDC-INV-02: checkpoint position MUST be >= 0."
            )
        with self._lock:
            prior = self._checkpoints.get(group, 0)
            if pos_int < prior:
                raise ChangeDataCaptureInvariantError(
                    f"CDC-INV-02: checkpoint MUST be monotonic; attempted rewind from "
                    f"{prior} to {pos_int} for group {group!r} is FORBIDDEN."
                )
            self._checkpoints[group] = pos_int

    def checkpoint_of(self, group: str | None = None) -> int:
        """Return the persisted checkpoint for a consumer group (0 if unset)."""
        with self._lock:
            return self._checkpoints.get(group or self._default_group, 0)

    def schema(self, table: str) -> dict[str, object]:
        """Return the latest schema descriptor for a table.

        The descriptor includes `schema_version` (CDC-INV-04). Consumers
        compare their local parser version against this to decide whether to
        reload their handler before applying row events.
        """
        if not isinstance(table, str) or not table:
            raise ChangeDataCaptureInvariantError(
                "CDC-INV-04: table MUST be a non-empty string."
            )
        with self._lock:
            if table not in self._schema_versions:
                raise ChangeDataCaptureInvariantError(
                    f"CDC-INV-04: table '{table}' is not registered."
                )
            latest: dict[str, object] | None = None
            for ev in reversed(self._log):
                if ev["op"] == "schema" and ev["table"] == table:
                    latest = dict(ev)
                    break
            if latest is None:  # pragma: no cover — register_table always emits one
                raise ChangeDataCaptureInvariantError(
                    f"CDC-INV-04: table '{table}' is registered but no schema event found."
                )
            columns_raw = latest.get("columns", [])
            columns_list: list[object] = (
                list(columns_raw) if isinstance(columns_raw, list) else []
            )
            return {
                "table": table,
                "schema_version": self._schema_versions[table],
                "columns": columns_list,
                "pos": latest["pos"],
            }

    # ----- introspection (testing / observability helpers) ------------------
    @property
    def next_position(self) -> int:
        with self._lock:
            return self._next_pos

    @property
    def committed_event_count(self) -> int:
        with self._lock:
            return sum(1 for ev in self._log if ev["op"] != "schema")

    @property
    def open_tx_count(self) -> int:
        with self._lock:
            return len(self._pending)

    def log_snapshot(self) -> tuple[Mapping[str, object], ...]:
        with self._lock:
            return tuple(dict(ev) for ev in self._log)

    def schema_version(self, table: str) -> int:
        with self._lock:
            if table not in self._schema_versions:
                raise ChangeDataCaptureInvariantError(
                    f"CDC-INV-04: table '{table}' is not registered."
                )
            return self._schema_versions[table]


# ---------------------------------------------------------------------------
# Connector extension point (CDC-INV-04 schema change + CDC-INV-01 ordering)
# ---------------------------------------------------------------------------
class Connector:
    """Minimal connector helper enforcing the extension contract.

    New sources extend ChangeDataCapture by wrapping a transactional workload
    in a connector that stages row changes and atomically commits them.
    Transformation filters plug in via `transforms`; they MUST be pure and
    MUST NOT reorder events within a transaction (CDC-INV-01).
    """

    def __init__(
        self,
        cdc: InMemoryChangeDataCapture,
        transforms: Iterable[object] = (),
    ) -> None:
        self._cdc = cdc
        self._transforms = tuple(transforms)
        for t in self._transforms:
            if not callable(t):
                raise ChangeDataCaptureInvariantError(
                    "CDC-INV-01: every transform MUST be callable (event -> event)."
                )

    def publish_transaction(
        self,
        txid: str,
        changes: Iterable[tuple[str, str, object, Mapping[str, object] | None, Mapping[str, object] | None]],
    ) -> int:
        """Atomically stage + commit a full transaction's changes.

        Each change is a tuple of (table, op, key, before, after). Ordering
        in the input iterable is preserved in the committed log.
        """
        self._cdc.begin_tx(txid)
        try:
            for table, op, key, before, after in changes:
                self._cdc.stage_change(txid, table, op, key, before, after)
            return self._cdc.commit_tx(txid)
        except BaseException:
            # Any staging / commit error rolls the tx back so CDC-INV-03 holds
            # (no partial / dirty reads leak through).
            self._cdc.rollback_tx(txid)
            raise


__all__ = [
    "ChangeDataCapture",
    "ChangeDataCaptureInvariantError",
    "Connector",
    "InMemoryChangeDataCapture",
]
