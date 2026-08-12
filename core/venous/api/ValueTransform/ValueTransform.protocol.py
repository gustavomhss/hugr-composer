"""Protocol for ValueTransform — generated from ValueTransform.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

@runtime_checkable
class ValueTransformProtocol(Protocol):
    """ValueTransform primitive — typed parse/validate step for inbound arguments."""

    def transform(self, value: I, meta: ArgumentMetadata) -> O: ...

@runtime_checkable
class ArgumentMetadataProtocol(Protocol):
    """Describes the handler parameter whose raw value is being transformed."""

    ...

@runtime_checkable
class ParseIntProtocol(Protocol):
    """Coerce `str | int | float` to `int`."""

    def transform(self, value: object, meta: ArgumentMetadata) -> int: ...

@runtime_checkable
class ParseBoolProtocol(Protocol):
    """Coerce string/int to bool using the Nest.js convention."""

    def transform(self, value: object, meta: ArgumentMetadata) -> bool: ...

@runtime_checkable
class ParseUUIDProtocol(Protocol):
    """Coerce a string to `uuid.UUID`."""

    def transform(self, value: object, meta: ArgumentMetadata) -> object: ...

@runtime_checkable
class ValidationProtocol(Protocol):
    """Applies a predicate to an already-typed value."""

    def transform(self, value: object, meta: ArgumentMetadata) -> object: ...

@runtime_checkable
class ComposeProtocol(Protocol):
    """Left-to-right composition of transforms."""

    def transforms(self) -> tuple[ValueTransform[Any, Any], ...]: ...
    def transform(self, value: object, meta: ArgumentMetadata) -> object: ...
