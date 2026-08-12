"""Protocol for Repository — generated from Repository.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Callable, Iterable

@runtime_checkable
class Repository(Protocol):
    """Repository primitive — Evans / Fowler collection-facade for aggregate roots."""

    def get(self, id: object) -> T | None: ...
    def add(self, entity: T) -> None: ...
    def remove(self, entity: T) -> None: ...
    def find(self, spec: object) -> Iterable[T]: ...

@runtime_checkable
class AggregateRoot(Protocol):
    """Marker Protocol — REPO-INV-01 requires entities to carry an id."""

    ...

@runtime_checkable
class Specification(Protocol):
    """Catalog-mandated query surface (REPO-INV-02)."""

    def is_satisfied_by(self, entity: object) -> bool: ...

@runtime_checkable
class IdentityMap(Protocol):
    """Hook shape for REPO-INV-05."""

    def get(self, root_type: type, id: object) -> object | None: ...
    def put(self, root_type: type, id: object, entity: object) -> None: ...
    def forget(self, root_type: type, id: object) -> None: ...

@runtime_checkable
class UnitOfWorkPort(Protocol):
    """Minimal write-side port (REPO-INV-04)."""

    def register_new(self, obj: object) -> None: ...
    def register_dirty(self, obj: object) -> None: ...
    def register_removed(self, obj: object) -> None: ...
