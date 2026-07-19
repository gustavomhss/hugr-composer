"""ValueTransform primitive — typed parse/validate step for inbound arguments.

Implements the catalog Protocol for `api.ValueTransform` and ships pure
reference transforms (ParseInt, ParseBool, ParseUUID, Validation, Compose)
that collectively enforce every invariant at runtime. The module performs
zero I/O at import (lazy imports only for optional uuid/datetime helpers).

Invariant IDs cited by this module:

- VTRANSFORM-INV-01: transform() MUST raise a typed validation error on bad
  input; it NEVER returns None to signal invalid.
- VTRANSFORM-INV-02: A ValueTransform MUST be pure — same (value, meta) SHALL
  produce the same output with no observable side effects.
- VTRANSFORM-INV-03: metatype MUST drive the coercion target; CANNOT silently
  ignore the declared type.
- VTRANSFORM-INV-04: Composed transforms MUST apply left-to-right in
  declaration order; swapping order SHALL be explicit.
- VTRANSFORM-INV-05: NEVER mutates the incoming value in place; the returned
  value is always fresh.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Final, Protocol, TypeVar, runtime_checkable

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ARGUMENT_KINDS: Final[frozenset[str]] = frozenset(
    {"body", "query", "param", "custom"}
)

# TypeVar names `I` and `O` are catalog-mandated (see api_signature).
# Variance: Protocol with parameter-in / return-out => I contravariant, O covariant.
I = TypeVar("I", contravariant=True)  # noqa: E741, PLC0105 — VTRANSFORM-INV-03: catalog-mandated TypeVar name `I` (api_signature byte-for-byte)
O = TypeVar("O", covariant=True)  # noqa: E741, PLC0105 — VTRANSFORM-INV-03: catalog-mandated TypeVar name `O` (api_signature byte-for-byte)


# ---------------------------------------------------------------------------
# Typed errors (VTRANSFORM-INV-01)
# ---------------------------------------------------------------------------
class ValueTransformError(ValueError):
    """Base class for ValueTransform validation errors.

    All transforms MUST raise this (or a subclass) on bad input — never
    return None (VTRANSFORM-INV-01).
    """

    def __init__(
        self,
        message: str,
        *,
        field: str | None = None,
        received: object | None = None,
        expected: str | None = None,
    ) -> None:
        super().__init__(message)
        self.field: str | None = field
        self.received: object | None = received
        self.expected: str | None = expected


class CoercionError(ValueTransformError):
    """Raised when a value cannot be coerced to the declared metatype."""


class ValidationError(ValueTransformError):
    """Raised when a value is well-typed but violates a semantic rule."""


class MetatypeMismatchError(ValueTransformError):
    """Raised when the ArgumentMetadata.metatype disagrees with the transform.

    VTRANSFORM-INV-03: metatype MUST drive the coercion target.
    """


# ---------------------------------------------------------------------------
# Argument metadata (catalog-verbatim dataclass)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ArgumentMetadata:
    """Describes the handler parameter whose raw value is being transformed.

    - `kind`: where the value originated: body | query | param | custom.
    - `metatype`: the declared Python type the handler expects (drives coercion).
    - `data`: opaque handler-supplied tag (e.g. field name).
    """

    kind: str
    metatype: type | None
    data: str | None


# ---------------------------------------------------------------------------
# Protocol surface (mirrors the catalog api_signature verbatim)
# ---------------------------------------------------------------------------
@runtime_checkable
class ValueTransform(Protocol[I, O]):
    def transform(self, value: I, meta: ArgumentMetadata) -> O: ...


# ---------------------------------------------------------------------------
# Shared validators
# ---------------------------------------------------------------------------
def validate_kind(kind: str) -> str:
    """VTRANSFORM-INV-01 supporting: kind MUST be a known argument origin."""
    if kind not in ARGUMENT_KINDS:
        raise ValidationError(
            f"VTRANSFORM-INV-01: kind MUST be one of {sorted(ARGUMENT_KINDS)}, got {kind!r}.",
            expected=f"one of {sorted(ARGUMENT_KINDS)}",
            received=kind,
        )
    return kind


def ensure_metatype(meta: ArgumentMetadata, expected: type) -> None:
    """VTRANSFORM-INV-03: raise if metatype is declared and disagrees.

    A None metatype means "the caller did not declare a type"; that is allowed
    and the transform proceeds. But if a metatype IS declared, it MUST match
    the transform's output type (or a subclass of it).
    """
    if meta.metatype is None:
        return
    if not isinstance(expected, type):
        raise MetatypeMismatchError(
            "VTRANSFORM-INV-03: expected must be a type.",
            expected=str(expected),
            received=str(meta.metatype),
        )
    # VTRANSFORM-INV-03 hard-primitive exception: `bool` is a subclass of
    # `int` in Python, so `issubclass(bool, int)` is True — this would let a
    # `ParseInt` transform silently accept a field declared `bool` and
    # return an int at the boundary. Reject the (bool, int) pair explicitly
    # so primitive types maintain strict identity.
    if meta.metatype is bool and expected is int:
        raise MetatypeMismatchError(
            "VTRANSFORM-INV-03: declared metatype bool is NOT acceptable as "
            "int output — use a bool-specific transform to preserve type identity.",
            expected=str(expected),
            received=str(meta.metatype),
        )
    if not issubclass(meta.metatype, expected):
        raise MetatypeMismatchError(
            f"VTRANSFORM-INV-03: declared metatype {meta.metatype!r} is not a "
            f"subclass of the transform's output type {expected!r}; refusing to "
            f"silently ignore.",
            expected=expected.__name__,
            received=meta.metatype.__name__,
            field=meta.data,
        )


def _freeze_input(value: Any) -> Any:
    """VTRANSFORM-INV-05: return a deep copy of mutable containers so the
    caller's object is never touched; immutable values are returned as-is.
    """
    if isinstance(value, (str, int, float, bool, bytes)) or value is None:
        return value
    return copy.deepcopy(value)


# ---------------------------------------------------------------------------
# Reference transforms
# ---------------------------------------------------------------------------
class ParseInt:
    """Coerce `str | int | float` to `int`.

    Pure (VTRANSFORM-INV-02). Raises CoercionError on bad input
    (VTRANSFORM-INV-01). Respects metatype (VTRANSFORM-INV-03).
    Never mutates input (VTRANSFORM-INV-05).
    """

    def transform(self, value: object, meta: ArgumentMetadata) -> int:
        validate_kind(meta.kind)
        ensure_metatype(meta, int)
        if isinstance(value, bool):
            # bool is an int subclass; reject to avoid silent True→1 coercion.
            raise CoercionError(
                "VTRANSFORM-INV-01: ParseInt refuses bool to avoid silent True→1.",
                field=meta.data, received=value, expected="int",
            )
        if isinstance(value, int):
            return int(value)  # fresh (VTRANSFORM-INV-05)
        if isinstance(value, float):
            if not value.is_integer():
                raise CoercionError(
                    "VTRANSFORM-INV-01: float is not integral.",
                    field=meta.data, received=value, expected="int",
                )
            return int(value)
        if isinstance(value, str):
            s = value.strip()
            if not s:
                raise CoercionError(
                    "VTRANSFORM-INV-01: empty string cannot be parsed as int.",
                    field=meta.data, received=value, expected="int",
                )
            try:
                return int(s, 10)
            except ValueError as exc:
                raise CoercionError(
                    f"VTRANSFORM-INV-01: cannot parse {value!r} as int.",
                    field=meta.data, received=value, expected="int",
                ) from exc
        raise CoercionError(
            f"VTRANSFORM-INV-01: ParseInt does not accept {type(value).__name__}.",
            field=meta.data, received=value, expected="int",
        )


class ParseBool:
    """Coerce string/int to bool using the Nest.js convention."""

    _TRUE: Final[frozenset[str]] = frozenset({"1", "true", "yes", "on"})
    _FALSE: Final[frozenset[str]] = frozenset({"0", "false", "no", "off"})

    def transform(self, value: object, meta: ArgumentMetadata) -> bool:
        validate_kind(meta.kind)
        ensure_metatype(meta, bool)
        if isinstance(value, bool):
            return bool(value)
        if isinstance(value, int):
            if value in (0, 1):
                return bool(value)
            raise CoercionError(
                f"VTRANSFORM-INV-01: int {value!r} is not 0 or 1.",
                field=meta.data, received=value, expected="bool",
            )
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in self._TRUE:
                return True
            if lowered in self._FALSE:
                return False
            raise CoercionError(
                f"VTRANSFORM-INV-01: string {value!r} is not a bool literal.",
                field=meta.data, received=value, expected="bool",
            )
        raise CoercionError(
            f"VTRANSFORM-INV-01: ParseBool does not accept {type(value).__name__}.",
            field=meta.data, received=value, expected="bool",
        )


class ParseUUID:
    """Coerce a string to `uuid.UUID`.

    Lazy-imports `uuid` inside the method body — the module boots even if an
    alternative uuid library is swapped in. Pure + total (returns UUID or
    raises).
    """

    def transform(self, value: object, meta: ArgumentMetadata) -> object:
        validate_kind(meta.kind)
        from uuid import UUID
        ensure_metatype(meta, UUID)
        if isinstance(value, UUID):
            return UUID(str(value))  # fresh instance (VTRANSFORM-INV-05)
        if isinstance(value, str):
            s = value.strip()
            try:
                return UUID(s)
            except (ValueError, AttributeError) as exc:
                raise CoercionError(
                    f"VTRANSFORM-INV-01: {value!r} is not a valid UUID.",
                    field=meta.data, received=value, expected="UUID",
                ) from exc
        raise CoercionError(
            f"VTRANSFORM-INV-01: ParseUUID does not accept {type(value).__name__}.",
            field=meta.data, received=value, expected="UUID",
        )


class Validation:
    """Applies a predicate to an already-typed value.

    The predicate MUST be pure (the caller is responsible). Raises
    ValidationError on failure. Used downstream of coercion to enforce
    semantic rules (e.g. `x > 0`).
    """

    def __init__(self, predicate: Callable[[object], bool], *, message: str) -> None:
        if not callable(predicate):
            raise TypeError("Validation predicate must be callable.")
        if not isinstance(message, str) or not message.strip():
            raise TypeError("Validation message must be a non-empty string.")
        self._predicate = predicate
        self._message = message

    def transform(self, value: object, meta: ArgumentMetadata) -> object:
        validate_kind(meta.kind)
        # Do NOT validate metatype here: Validation is type-agnostic by design;
        # the preceding Parse* transform in a Compose chain binds the type.
        ok = self._predicate(value)
        if not ok:
            raise ValidationError(
                f"VTRANSFORM-INV-01: {self._message}",
                field=meta.data, received=value, expected=self._message,
            )
        # VTRANSFORM-INV-05: return a fresh value (deep copy for mutables).
        return _freeze_input(value)


class Compose:
    """Left-to-right composition of transforms.

    Given transforms [t1, t2, t3], applies t1 then t2 then t3. Order is
    preserved verbatim (VTRANSFORM-INV-04); reordering is only possible by
    constructing a new Compose with a different sequence (explicit by
    construction).
    """

    def __init__(self, transforms: Sequence[ValueTransform[Any, Any]]) -> None:
        if not isinstance(transforms, (list, tuple)):
            raise TypeError("Compose requires a list/tuple of transforms.")
        if len(transforms) == 0:
            raise ValueError(
                "VTRANSFORM-INV-04: Compose MUST contain at least one transform."
            )
        for idx, t in enumerate(transforms):
            if not hasattr(t, "transform"):
                raise TypeError(f"Compose[{idx}] is not a ValueTransform.")
        # Freeze as tuple to prevent downstream mutation of the declared order.
        self._transforms: tuple[ValueTransform[Any, Any], ...] = tuple(transforms)

    @property
    def transforms(self) -> tuple[ValueTransform[Any, Any], ...]:
        return self._transforms

    def transform(self, value: object, meta: ArgumentMetadata) -> object:
        validate_kind(meta.kind)
        # VTRANSFORM-INV-05: never touch the caller's original value.
        current: object = _freeze_input(value)
        for t in self._transforms:
            current = t.transform(current, meta)
        return current


__all__ = [
    "ARGUMENT_KINDS",
    "ArgumentMetadata",
    "CoercionError",
    "Compose",
    "MetatypeMismatchError",
    "ParseBool",
    "ParseInt",
    "ParseUUID",
    "Validation",
    "ValidationError",
    "ValueTransform",
    "ValueTransformError",
    "ensure_metatype",
    "validate_kind",
]
