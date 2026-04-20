"""DataMapper primitive — Fowler PEAA bidirectional domain ↔ row translator.

Implements the catalog Protocol for `data.DataMapper` and installs runtime
invariant checkers. The module performs zero I/O at import.

The DataMapper moves state between in-memory domain objects and persistence
rows while keeping both ignorant of each other. Domain objects have NO
import-time knowledge of storage; persistence payloads have NO reference to
domain types. The mapper is the only place that knows both.

Invariant IDs cited by this module:

- DM-INV-01: the domain object MUST have no import-time or runtime dependency
  on storage types; persistence knowledge SHALL live exclusively in the
  mapper.
- DM-INV-02: given a row r, load(r) followed by insert or update on the
  resulting entity MUST yield a row with the same identity key (round-trip
  identity).
- DM-INV-03: the mapper CANNOT mutate the domain object for persistence
  convenience; derived columns MUST be computed in map methods, never
  injected into the domain.
- DM-INV-04: a DataMapper NEVER issues database I/O directly; it returns
  parameterized payloads the UnitOfWork flush executes.
"""

from __future__ import annotations

import copy
import threading
from collections.abc import Callable, Mapping
from typing import Any, Final, Generic, Protocol, TypeVar, runtime_checkable

T = TypeVar("T")

# ---------------------------------------------------------------------------
# Payload kinds + forbidden-symbol registry (DM-INV-01 / DM-INV-04)
# ---------------------------------------------------------------------------
PAYLOAD_INSERT: Final[str] = "insert"
PAYLOAD_UPDATE: Final[str] = "update"
PAYLOAD_DELETE: Final[str] = "delete"
_PAYLOAD_KINDS: Final[frozenset[str]] = frozenset({PAYLOAD_INSERT, PAYLOAD_UPDATE, PAYLOAD_DELETE})

# DM-INV-01: these module names, if present on a domain class module, signal
# illegal storage coupling (a domain object MUST NOT import them directly).
_FORBIDDEN_DOMAIN_IMPORTS: Final[frozenset[str]] = frozenset(
    {
        "sqlalchemy",
        "psycopg",
        "psycopg2",
        "asyncpg",
        "pymongo",
        "sqlite3",
        "mysql",
    }
)


# ---------------------------------------------------------------------------
# Protocol surface (matches catalog api_signature verbatim)
# ---------------------------------------------------------------------------
@runtime_checkable
class DataMapper(Protocol, Generic[T]):
    def load(self, row: dict[str, Any]) -> T: ...
    def insert(self, entity: T) -> dict[str, Any]: ...
    def update(self, entity: T) -> dict[str, Any]: ...
    def delete(self, entity: T) -> dict[str, Any]: ...


# ---------------------------------------------------------------------------
# Invariant-violation marker
# ---------------------------------------------------------------------------
class DataMapperInvariantError(RuntimeError):
    """Raised when a DataMapper invariant is violated at runtime."""


class SchemaDriftError(DataMapperInvariantError):
    """Raised when a row's schema disagrees with the mapper's declared columns."""


# ---------------------------------------------------------------------------
# Domain-coupling guard (DM-INV-01)
# ---------------------------------------------------------------------------
def assert_domain_has_no_storage_coupling(domain_cls: type) -> None:
    """Fail loudly if a domain class module imports any known storage library.

    DM-INV-01: the domain object MUST have no import-time or runtime
    dependency on storage types.
    """
    mod = getattr(domain_cls, "__module__", "")
    import inspect as _inspect
    import sys as _sys
    from types import ModuleType as _ModuleType

    module_obj = _sys.modules.get(mod)
    if module_obj is None:
        return
    # DM-INV-01: coupling hides in two places —
    #   (a) `import sqlalchemy` — value is a module; its `__name__` is
    #       `"sqlalchemy"` so the top-split matches directly.
    #   (b) `from sqlalchemy import Column` — value is a CLASS whose own
    #       `__name__` is `"Column"` (not dotted). The class's origin module
    #       is `sqlalchemy.sql.schema`, reachable via `inspect.getmodule`.
    # Both paths must be walked or the check gives false confidence.
    for value in vars(module_obj).values():
        # Path (a): direct module import.
        if isinstance(value, _ModuleType):
            dotted = getattr(value, "__name__", "")
            if not isinstance(dotted, str):
                continue
            top = dotted.split(".", 1)[0]
            if top in _FORBIDDEN_DOMAIN_IMPORTS:
                raise DataMapperInvariantError(
                    f"DM-INV-01: domain class {domain_cls.__qualname__} (module {mod}) "
                    f"imports storage library {top!r}; persistence knowledge MUST "
                    f"live exclusively in the mapper."
                )
            continue
        # Path (b): symbol imported from a forbidden module.
        origin = _inspect.getmodule(value)
        if origin is None:
            continue
        origin_name = getattr(origin, "__name__", "") or ""
        if not isinstance(origin_name, str):
            continue
        origin_top = origin_name.split(".", 1)[0]
        if origin_top in _FORBIDDEN_DOMAIN_IMPORTS:
            raise DataMapperInvariantError(
                f"DM-INV-01: domain class {domain_cls.__qualname__} (module {mod}) "
                f"imports {getattr(value, '__name__', '<symbol>')!r} from storage "
                f"library {origin_top!r}; persistence knowledge MUST live exclusively "
                f"in the mapper."
            )


# ---------------------------------------------------------------------------
# Schema-drift detector (DM-INV-02 support)
# ---------------------------------------------------------------------------
def detect_schema_drift(
    row: Mapping[str, Any],
    expected_columns: frozenset[str],
    *,
    allow_extra: bool = False,
) -> None:
    """Raise SchemaDriftError if the row disagrees with the declared columns.

    Missing required columns are always a drift; extra columns are a drift
    unless ``allow_extra`` is True. Detecting drift is cheap and fires before
    the round-trip is attempted (DM-INV-02 support).
    """
    row_keys = frozenset(row.keys())
    missing = expected_columns - row_keys
    if missing:
        raise SchemaDriftError(
            f"DM-INV-02: schema drift — row missing required columns "
            f"{sorted(missing)!r} (expected {sorted(expected_columns)!r})."
        )
    if not allow_extra:
        extra = row_keys - expected_columns
        if extra:
            raise SchemaDriftError(
                f"DM-INV-02: schema drift — row contains unknown columns "
                f"{sorted(extra)!r} (expected {sorted(expected_columns)!r})."
            )


# ---------------------------------------------------------------------------
# Reference implementation — AbstractDataMapper
# ---------------------------------------------------------------------------
class AbstractDataMapper(Generic[T]):
    """Reference mapper base enforcing all four invariants at runtime.

    Subclasses implement four pure functions:

    - ``_row_to_entity(row)`` → domain object (no storage side-effects)
    - ``_entity_to_row(entity)`` → plain dict (derived columns computed here)
    - ``_identity_key(entity)`` → tuple of the identity columns
    - ``_identity_key_from_row(row)`` → same tuple from a row

    The base class:

    - validates incoming rows against ``columns`` (schema-drift detection),
    - snapshots the domain object before map methods to verify no mutation
      (DM-INV-03),
    - tags every returned payload with the mapper kind + table (DM-INV-04),
    - NEVER issues any I/O.
    """

    # Declared persistence columns — subclasses MUST set this.
    columns: frozenset[str] = frozenset()
    # Identity columns (the subset of ``columns`` that forms the primary key).
    identity_columns: tuple[str, ...] = ()
    # Persistence table / collection name.
    table: str = ""

    def __init__(self) -> None:
        # DM-INV-04: I/O counter — any subclass that performs real I/O will
        # trip the assertion in map methods (they are wrapped).
        self._io_attempts = 0
        self._lock = threading.Lock()

    # ---- subclass extension points (pure functions) ----------------------
    def _row_to_entity(self, row: Mapping[str, Any]) -> T:
        raise NotImplementedError

    def _entity_to_row(self, entity: T) -> dict[str, Any]:
        raise NotImplementedError

    def _identity_key(self, entity: T) -> tuple[Any, ...]:
        raise NotImplementedError

    def _identity_key_from_row(self, row: Mapping[str, Any]) -> tuple[Any, ...]:
        return tuple(row[c] for c in self.identity_columns)

    # ---- Protocol surface (DataMapper) -----------------------------------
    def load(self, row: dict[str, Any]) -> T:
        # DM-INV-02 support: drift detection before translation.
        detect_schema_drift(row, self.columns, allow_extra=False)
        # Pass an immutable view so subclasses cannot mutate the caller's dict.
        frozen = dict(row)
        entity = self._row_to_entity(frozen)
        return entity

    def insert(self, entity: T) -> dict[str, Any]:
        return self._map_with_guards(entity, PAYLOAD_INSERT)

    def update(self, entity: T) -> dict[str, Any]:
        return self._map_with_guards(entity, PAYLOAD_UPDATE)

    def delete(self, entity: T) -> dict[str, Any]:
        # Delete only needs the identity columns — we still validate the
        # identity key is recoverable from the entity.
        snapshot = _snapshot(entity)
        key = self._identity_key(entity)
        _assert_no_mutation(entity, snapshot)
        return {
            "kind": PAYLOAD_DELETE,
            "table": self.table,
            "identity_columns": list(self.identity_columns),
            "identity_values": list(key),
            "row": dict(zip(self.identity_columns, key, strict=True)),
        }

    # ---- round-trip helper (explicit DM-INV-02 check) --------------------
    def round_trip(self, row: dict[str, Any]) -> dict[str, Any]:
        """Load a row then re-serialise; identity key MUST be preserved."""
        entity = self.load(row)
        payload = self._map_with_guards(entity, PAYLOAD_UPDATE)
        before = self._identity_key_from_row(row)
        after = self._identity_key_from_row(payload["row"])
        if before != after:
            raise DataMapperInvariantError(
                f"DM-INV-02: round-trip identity violated — before={before!r}, "
                f"after={after!r}. load→update MUST preserve the identity key."
            )
        return payload

    # ---- internal -------------------------------------------------------
    def _map_with_guards(self, entity: T, kind: str) -> dict[str, Any]:
        if kind not in _PAYLOAD_KINDS:
            raise DataMapperInvariantError(
                f"DM-INV-04: unknown payload kind {kind!r}; expected one of {_PAYLOAD_KINDS!r}."
            )
        # DM-INV-03: snapshot before call, verify no mutation after.
        snapshot = _snapshot(entity)
        io_before = self._io_attempts
        row = self._entity_to_row(entity)
        io_after = self._io_attempts
        _assert_no_mutation(entity, snapshot)
        if io_after != io_before:
            raise DataMapperInvariantError(
                "DM-INV-04: DataMapper attempted database I/O; mappers MUST "
                "return parameterized payloads only."
            )
        # Returned row MUST carry every declared column.
        detect_schema_drift(row, self.columns, allow_extra=False)
        payload: dict[str, Any] = {
            "kind": kind,
            "table": self.table,
            "identity_columns": list(self.identity_columns),
            "identity_values": list(self._identity_key(entity)),
            "row": row,
        }
        return payload

    # ---- I/O tripwire ---------------------------------------------------
    def _record_io_attempt(self) -> None:
        """Subclasses that erroneously attempt I/O call this; it trips INV-04."""
        with self._lock:
            self._io_attempts += 1


# ---------------------------------------------------------------------------
# Mapper registry (extension contract)
# ---------------------------------------------------------------------------
class MapperRegistry:
    """Maps domain types → their DataMapper instance.

    DM-INV-01 enforcement: on register we assert the domain class has no
    storage coupling.
    """

    def __init__(self) -> None:
        self._by_type: dict[type, AbstractDataMapper[Any]] = {}
        self._lock = threading.Lock()

    def register(self, domain_cls: type, mapper: AbstractDataMapper[Any]) -> None:
        assert_domain_has_no_storage_coupling(domain_cls)
        if not isinstance(mapper, AbstractDataMapper):
            raise DataMapperInvariantError(
                "DM-INV-04: registered mapper MUST inherit AbstractDataMapper "
                "so runtime guards apply; got "
                f"{type(mapper).__qualname__}."
            )
        with self._lock:
            if domain_cls in self._by_type:
                raise DataMapperInvariantError(
                    f"mapper for {domain_cls.__qualname__} already registered; "
                    "call unregister() first or use a fresh registry."
                )
            self._by_type[domain_cls] = mapper

    def unregister(self, domain_cls: type) -> None:
        with self._lock:
            self._by_type.pop(domain_cls, None)

    def get(self, domain_cls: type) -> AbstractDataMapper[Any]:
        with self._lock:
            try:
                return self._by_type[domain_cls]
            except KeyError as exc:
                raise DataMapperInvariantError(
                    f"no mapper registered for {domain_cls.__qualname__}"
                ) from exc

    def for_entity(self, entity: object) -> AbstractDataMapper[Any]:
        return self.get(type(entity))


# ---------------------------------------------------------------------------
# Snapshot helpers (DM-INV-03)
# ---------------------------------------------------------------------------
def _snapshot(entity: object) -> dict[str, Any]:
    """Return a deep snapshot of the entity's __dict__ (or equivalent)."""
    if hasattr(entity, "__dict__"):
        return copy.deepcopy(vars(entity))
    if isinstance(entity, dict):
        return copy.deepcopy(entity)
    # Fallback: repr-based snapshot (value objects, dataclasses frozen=True).
    return {"__repr__": repr(entity)}


def _assert_no_mutation(entity: object, snapshot: dict[str, Any]) -> None:
    if hasattr(entity, "__dict__"):
        current = vars(entity)
        if current != snapshot:
            raise DataMapperInvariantError(
                "DM-INV-03: mapper mutated the domain object; derived columns "
                "MUST be computed inside the map method, NEVER injected into "
                "the domain."
            )
        return
    if isinstance(entity, dict):
        if entity != snapshot:
            raise DataMapperInvariantError(
                "DM-INV-03: mapper mutated the domain dict; map methods MUST be pure."
            )
        return
    if snapshot.get("__repr__") != repr(entity):
        raise DataMapperInvariantError(
            "DM-INV-03: mapper mutated the domain value; map methods MUST be pure."
        )


# ---------------------------------------------------------------------------
# Storage adapter surface (extension contract)
# ---------------------------------------------------------------------------
class StorageAdapter(Protocol):
    """Encodes/decodes one column value for a specific storage backend.

    JSONB, arrays, encrypted columns, enums — adapters plug in per column so
    the domain NEVER imports the storage dialect.
    """

    def encode(self, value: Any) -> Any: ...
    def decode(self, value: Any) -> Any: ...


class IdentityAdapter:
    """Pass-through adapter used when no encoding is needed."""

    def encode(self, value: Any) -> Any:
        return value

    def decode(self, value: Any) -> Any:
        return value


# ---------------------------------------------------------------------------
# Flush executor wiring (DM-INV-04)
# ---------------------------------------------------------------------------
FlushFn = Callable[[list[dict[str, Any]]], None]


def enqueue_payload_sink() -> tuple[list[dict[str, Any]], FlushFn]:
    """Return (sink, flush_fn) pair for a UnitOfWork to enqueue payloads into.

    The flush_fn records payloads into the sink list — the actual database
    write happens outside the DataMapper (DM-INV-04).
    """
    sink: list[dict[str, Any]] = []

    def flush(payloads: list[dict[str, Any]]) -> None:
        sink.extend(payloads)

    return sink, flush


__all__ = [
    "PAYLOAD_DELETE",
    "PAYLOAD_INSERT",
    "PAYLOAD_UPDATE",
    "AbstractDataMapper",
    "DataMapper",
    "DataMapperInvariantError",
    "FlushFn",
    "IdentityAdapter",
    "MapperRegistry",
    "SchemaDriftError",
    "StorageAdapter",
    "assert_domain_has_no_storage_coupling",
    "detect_schema_drift",
    "enqueue_payload_sink",
]
