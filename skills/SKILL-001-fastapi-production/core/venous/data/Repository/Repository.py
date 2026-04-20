"""Repository primitive — Evans / Fowler collection-facade for aggregate roots.

Implements the catalog Protocol for `data.Repository` and installs runtime
invariant checkers. The module performs zero I/O at import.

Invariant IDs cited by this module:

- REPO-INV-01: a Repository MUST only expose aggregate roots, NEVER internal
  child entities of another aggregate.
- REPO-INV-02: query methods MUST accept a Specification object (or a named
  finder) and SHALL NOT leak SQL, ORM, or storage syntax to callers.
- REPO-INV-03: a single logical aggregate type MUST have exactly one
  Repository; duplicate repositories for the same root are FORBIDDEN.
- REPO-INV-04: mutations (add, remove) MUST enlist with the active UnitOfWork
  and NEVER issue direct writes bypassing it.
- REPO-INV-05: the Repository CANNOT return stale in-memory copies when an
  IdentityMap is present; it MUST consult the map first.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable, Iterator
from typing import Final, Generic, Protocol, TypeVar, runtime_checkable

# ---------------------------------------------------------------------------
# Type variables and role markers
# ---------------------------------------------------------------------------
T = TypeVar("T")
# Invariant REPO-INV-03: one repository per aggregate type. The process-wide
# registry is a class-level dict guarded by a lock; duplicate registrations
# raise `RepositoryInvariantError`.
_ROOT_REGISTRY_LOCK: Final[threading.Lock] = threading.Lock()
_ROOT_REGISTRY: dict[tuple[type, object], object] = {}


# ---------------------------------------------------------------------------
# Protocol surface (matches catalog api_signature verbatim)
# ---------------------------------------------------------------------------
@runtime_checkable
class Repository(Protocol, Generic[T]):
    def get(self, id: object) -> T | None: ...  # noqa: A002 — REPO-INV-01: `id` matches catalog api_signature verbatim.
    def add(self, entity: T) -> None: ...
    def remove(self, entity: T) -> None: ...
    def find(self, spec: object) -> Iterable[T]: ...


# ---------------------------------------------------------------------------
# Invariant-violation marker
# ---------------------------------------------------------------------------
class RepositoryInvariantError(RuntimeError):
    """Raised when a Repository invariant is violated at runtime."""


# ---------------------------------------------------------------------------
# Protocol helpers: AggregateRoot marker, Specification, IdentityMap, UoW port
# ---------------------------------------------------------------------------
@runtime_checkable
class AggregateRoot(Protocol):
    """Marker Protocol — REPO-INV-01 requires entities to carry an id.

    Implementations may expose more domain methods; only the id is mandated.
    """

    id: object


@runtime_checkable
class Specification(Protocol):
    """Catalog-mandated query surface (REPO-INV-02).

    A Specification exposes a single boolean predicate `is_satisfied_by`; the
    Repository translates that predicate against its storage without leaking
    SQL / ORM syntax to callers.
    """

    def is_satisfied_by(self, entity: object) -> bool: ...


@runtime_checkable
class IdentityMap(Protocol):
    """Hook shape for REPO-INV-05.

    The Repository consults `get` before materialising from storage; when the
    map already tracks the aggregate, the cached reference wins.
    """

    def get(self, root_type: type, id: object) -> object | None: ...  # noqa: A002 — catalog parameter name.
    def put(self, root_type: type, id: object, entity: object) -> None: ...  # noqa: A002 — catalog parameter name.
    def forget(self, root_type: type, id: object) -> None: ...  # noqa: A002 — catalog parameter name.


@runtime_checkable
class UnitOfWorkPort(Protocol):
    """Minimal write-side port (REPO-INV-04).

    The Repository calls `register_new` / `register_dirty` / `register_removed`
    instead of issuing writes directly. This matches the `UnitOfWork` primitive
    in the same namespace but is Protocol-typed so callers can bind ANY unit
    implementation that honours the shape.
    """

    def register_new(self, obj: object) -> None: ...
    def register_dirty(self, obj: object) -> None: ...
    def register_removed(self, obj: object) -> None: ...


# ---------------------------------------------------------------------------
# In-memory IdentityMap reference impl (used by tests and by default)
# ---------------------------------------------------------------------------
class InMemoryIdentityMap:
    """Thread-safe in-memory IdentityMap honouring the `IdentityMap` Protocol."""

    def __init__(self) -> None:
        self._by_type: dict[type, dict[object, object]] = {}
        self._lock = threading.Lock()

    def get(self, root_type: type, id: object) -> object | None:  # noqa: A002 — catalog parameter name.
        with self._lock:
            return self._by_type.get(root_type, {}).get(id)

    def put(self, root_type: type, id: object, entity: object) -> None:  # noqa: A002 — catalog parameter name.
        # IDMAP-INV-01: first-writer-wins per (root_type, id). Two concurrent
        # cold-loads resolving the same id MUST return the SAME reference —
        # unconditional overwrite would hand out two different in-memory
        # instances for the same identity, breaking the identity-map contract.
        with self._lock:
            bucket = self._by_type.setdefault(root_type, {})
            existing = bucket.get(id)
            if existing is not None:
                return  # keep first-written reference; drop the racing loser
            bucket[id] = entity

    def forget(self, root_type: type, id: object) -> None:  # noqa: A002 — catalog parameter name.
        with self._lock:
            bucket = self._by_type.get(root_type)
            if bucket is not None:
                bucket.pop(id, None)


# ---------------------------------------------------------------------------
# Reference Repository implementation
# ---------------------------------------------------------------------------
class ConcreteRepository(Generic[T]):
    """Reference Repository that mediates one aggregate root to its storage.

    - REPO-INV-01 is enforced by the `root_type` argument: every `add` /
      `remove` instance MUST be an instance of `root_type`.
    - REPO-INV-02 is enforced by `find` accepting either a `Specification` or
      a named finder key bound via `register_finder`; raw SQL / ORM syntax is
      rejected.
    - REPO-INV-03 is enforced by a process-wide registry keyed on
      `(root_type, shard)`; a second instantiation with the same key raises.
    - REPO-INV-04 is enforced by requiring a `UnitOfWorkPort` and calling its
      register_* methods on every mutation. The `direct_write` method ALWAYS
      raises to advertise that no bypass is possible.
    - REPO-INV-05 is enforced when an `IdentityMap` is wired: `get` consults
      the map first and only falls through to storage when the map is cold;
      the materialised row is put back into the map to stop later divergence.

    A `load_fn` callable provides the storage pre-image used by `get` cold
    paths and by `find`. Passing `load_fn=None` keeps a storage-less reference
    mode suitable for tests where every entity is added through `add` before
    it is read back.
    """

    def __init__(
        self,
        root_type: type[T],
        uow: UnitOfWorkPort,
        *,
        identity_map: IdentityMap | None = None,
        load_fn: Callable[[object], T | None] | None = None,
        find_fn: Callable[[object], Iterable[T]] | None = None,
        shard: object = "default",
    ) -> None:
        self._root_type = root_type
        self._uow = uow
        self._identity_map = identity_map
        self._load_fn = load_fn
        self._find_fn = find_fn
        self._shard = shard
        self._store: dict[object, T] = {}
        self._finders: dict[str, Callable[[object], Iterable[T]]] = {}
        self._tombstones: set[object] = set()
        self._lock = threading.Lock()

        # REPO-INV-03 — refuse duplicate repository for (root_type, shard).
        key = (root_type, shard)
        with _ROOT_REGISTRY_LOCK:
            if key in _ROOT_REGISTRY:
                raise RepositoryInvariantError(
                    "REPO-INV-03: duplicate Repository for aggregate "
                    f"{root_type.__name__!s} shard={shard!r} is FORBIDDEN."
                )
            _ROOT_REGISTRY[key] = self

    # ----- lifecycle --------------------------------------------------------
    def close(self) -> None:
        """Release the singleton slot so the same root_type can be rebuilt.

        Used by tests / fixtures to reset the global registry between cases.
        """
        key = (self._root_type, self._shard)
        with _ROOT_REGISTRY_LOCK:
            _ROOT_REGISTRY.pop(key, None)

    # ----- UnitOfWork rollback hook (REPO-INV-04) --------------------------
    def on_unit_rollback(self) -> None:
        """Discard any `remove()`-scheduled tombstones.

        REPO-INV-04: `remove()` stages a tombstone so `get()` stops returning
        the entity during the active UnitOfWork. If the UoW rolls back, those
        tombstones are stale — the entity was NEVER actually removed from
        storage. Consumers integrating Repository with their UoW MUST wire the
        UoW's rollback signal to this hook so subsequent `get()` calls
        correctly re-load the entity.

        The symmetric commit path does not need to clear tombstones; once the
        UoW commits the removal, the underlying `_store` entry is gone and
        `load_fn` either returns None (true removal) or the entity is absent
        from the authoritative store.
        """
        with self._lock:
            self._tombstones.clear()

    # ----- collection-facade API (catalog surface) --------------------------
    def get(self, id: object) -> T | None:  # noqa: A002 — catalog parameter name.
        # REPO-INV-05: consult the IdentityMap FIRST; never prefer a stale copy.
        if self._identity_map is not None:
            cached = self._identity_map.get(self._root_type, id)
            if cached is not None:
                # The map stores object references; narrowing keeps mypy strict.
                if not isinstance(cached, self._root_type):
                    raise RepositoryInvariantError(
                        "REPO-INV-05: IdentityMap returned a value whose type "
                        f"does not match root {self._root_type.__name__}."
                    )
                return cached
        with self._lock:
            if id in self._tombstones:
                return None
            local = self._store.get(id)
        if local is not None:
            self._remember(id, local)
            return local
        if self._load_fn is None:
            return None
        materialised = self._load_fn(id)
        if materialised is None:
            return None
        if not isinstance(materialised, self._root_type):
            raise RepositoryInvariantError(
                "REPO-INV-01: load_fn returned a non-aggregate-root value; "
                f"expected {self._root_type.__name__}."
            )
        with self._lock:
            self._store[id] = materialised
        self._remember(id, materialised)
        return materialised

    def add(self, entity: T) -> None:
        self._require_root(entity)
        eid = self._require_id(entity)
        with self._lock:
            if eid in self._store:
                raise RepositoryInvariantError(
                    "REPO-INV-01: aggregate with id "
                    f"{eid!r} already present in repository {self._root_type.__name__}."
                )
            # REPO-INV-04: enlist with the UnitOfWork BEFORE mutating storage
            # so a failing unit aborts without leaving ghost state.
            self._uow.register_new(entity)
            self._store[eid] = entity
            self._tombstones.discard(eid)
        self._remember(eid, entity)

    def remove(self, entity: T) -> None:
        self._require_root(entity)
        eid = self._require_id(entity)
        with self._lock:
            # REPO-INV-04: enlist before dropping from local store.
            self._uow.register_removed(entity)
            self._store.pop(eid, None)
            self._tombstones.add(eid)
        if self._identity_map is not None:
            self._identity_map.forget(self._root_type, eid)

    def find(self, spec: object) -> Iterable[T]:
        # REPO-INV-02: accept a Specification object or a registered finder key.
        # Reject raw strings that look like SQL / ORM fragments so callers never
        # couple the domain to storage syntax.
        if isinstance(spec, str):
            if spec in self._finders:
                return self._materialise(self._finders[spec](None))
            raise RepositoryInvariantError(
                "REPO-INV-02: find() rejected unregistered string spec "
                f"{spec!r}; pass a Specification or register a named finder."
            )
        if isinstance(spec, Specification):
            return self._materialise(
                entity for entity in self._iter_all() if spec.is_satisfied_by(entity)
            )
        raise RepositoryInvariantError(
            "REPO-INV-02: find() requires a Specification or a named finder; "
            f"got {type(spec).__name__}."
        )

    # ----- extension points (REPO-INV-02: named-finder decorator) -----------
    def register_finder(
        self,
        name: str,
        fn: Callable[[object], Iterable[T]],
    ) -> None:
        if not name or not name.isidentifier():
            raise RepositoryInvariantError(
                "REPO-INV-02: finder name must be a valid identifier, got "
                f"{name!r}."
            )
        self._finders[name] = fn

    def mark_dirty(self, entity: T) -> None:
        """Explicit dirty marker — REPO-INV-04 enlists the mutation."""
        self._require_root(entity)
        self._require_id(entity)
        self._uow.register_dirty(entity)

    # ----- REPO-INV-04 enforcement surface ---------------------------------
    def direct_write(self, entity: T) -> None:
        """Bypass surface that ALWAYS raises (REPO-INV-04).

        Exists so static review and unit tests can assert that the Repository
        refuses to issue writes that skip the UnitOfWork.
        """
        raise RepositoryInvariantError(
            "REPO-INV-04: direct_write is FORBIDDEN; the Repository MUST enlist "
            "mutations with the active UnitOfWork."
        )

    # ----- introspection ----------------------------------------------------
    @property
    def root_type(self) -> type[T]:
        return self._root_type

    @property
    def tracked_ids(self) -> tuple[object, ...]:
        with self._lock:
            return tuple(self._store.keys())

    # ----- private helpers --------------------------------------------------
    def _iter_all(self) -> Iterator[T]:
        if self._find_fn is not None:
            yield from self._find_fn(None)
        with self._lock:
            snapshot = tuple(self._store.values())
        yield from snapshot

    def _materialise(self, it: Iterable[T]) -> list[T]:
        out: list[T] = []
        seen: set[object] = set()
        for entity in it:
            self._require_root(entity)
            eid = self._require_id(entity)
            if eid in seen:
                continue
            seen.add(eid)
            self._remember(eid, entity)
            out.append(entity)
        return out

    def _remember(self, eid: object, entity: T) -> None:
        if self._identity_map is not None:
            self._identity_map.put(self._root_type, eid, entity)

    def _require_root(self, entity: object) -> None:
        if not isinstance(entity, self._root_type):
            raise RepositoryInvariantError(
                "REPO-INV-01: Repository accepts only aggregate roots of type "
                f"{self._root_type.__name__}; got {type(entity).__name__}."
            )

    def _require_id(self, entity: T) -> object:
        eid = getattr(entity, "id", None)
        if eid is None:
            raise RepositoryInvariantError(
                "REPO-INV-01: aggregate root MUST expose an `id` attribute."
            )
        return eid


__all__ = [
    "AggregateRoot",
    "ConcreteRepository",
    "IdentityMap",
    "InMemoryIdentityMap",
    "Repository",
    "RepositoryInvariantError",
    "Specification",
    "UnitOfWorkPort",
]
