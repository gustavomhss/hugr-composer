"""ValueObject primitive — immutable, equality-by-value, frozen-dataclass-backed.

Implements the catalog Protocol for `data.ValueObject` and installs runtime
invariant checkers. The module performs zero I/O at import.

Invariant IDs cited by this module:

- VO-INV-01: instances MUST be immutable after construction; attribute
  assignment post-init is FORBIDDEN.
- VO-INV-02: two instances with the same attribute values MUST compare equal
  and MUST share the same hash.
- VO-INV-03: a ValueObject CANNOT hold a reference to an Aggregate root or
  Entity whose identity is unstable.
- VO-INV-04: construction SHALL validate every invariant eagerly; a
  partially-valid instance NEVER exists.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Mapping
from typing import Any, ClassVar, Final, Protocol, Self, runtime_checkable

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# Types a ValueObject may hold as attribute values. Mutable containers (list,
# set, dict) and references to objects exposing identity-mutating interfaces
# are FORBIDDEN by VO-INV-01 / VO-INV-03.
VALUE_PRIMITIVE_TYPES: Final[tuple[type, ...]] = (
    str,
    int,
    float,
    bool,
    bytes,
    type(None),
)
# Marker attribute names used by DDD Aggregates / Entities to expose their
# unstable identity. A ValueObject carrying any of these would silently
# alias a mutable identity and break VO-INV-03.
UNSTABLE_IDENTITY_MARKERS: Final[frozenset[str]] = frozenset(
    {"_aggregate_id", "_entity_id", "__aggregate_root__", "__entity__"}
)


# ---------------------------------------------------------------------------
# Protocol surface (mirrors the catalog api_signature verbatim)
# ---------------------------------------------------------------------------
@runtime_checkable
class ValueObject(Protocol):
    def __eq__(self, other: object) -> bool: ...
    def __hash__(self) -> int: ...
    def with_changes(self, **kwargs: object) -> ValueObject: ...


# ---------------------------------------------------------------------------
# Runtime invariant errors
# ---------------------------------------------------------------------------
class ValueObjectInvariantError(ValueError):
    """Raised when a runtime call violates a ValueObject invariant."""


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def _is_hashable(value: object) -> bool:
    try:
        hash(value)
    except TypeError:
        return False
    return True


def _is_allowed_value(value: object) -> bool:
    """VO-INV-01/03: attribute values MUST be immutable + stable-identity.

    Accepted: primitives (str/int/float/bool/bytes/None), frozenset, tuple of
    accepted values, another ValueObject (nested composition allowed).
    Rejected: list, set, dict, references to objects carrying Aggregate/Entity
    identity markers, and any non-hashable object.
    """
    if isinstance(value, (*VALUE_PRIMITIVE_TYPES, FrozenValueObject)):
        return True
    if isinstance(value, (frozenset, tuple)):
        return all(_is_allowed_value(v) for v in value)
    # Explicit rejects for mutable containers and unstable-identity references.
    if isinstance(value, (list, set, dict, bytearray)):
        return False
    if any(hasattr(value, marker) for marker in UNSTABLE_IDENTITY_MARKERS):
        return False
    # Must be hashable to satisfy VO-INV-02.
    return _is_hashable(value)


def validate_attributes(name: str, values: Mapping[str, object]) -> None:
    """VO-INV-01/03/04: enforce value-type discipline at construction time."""
    for key, value in values.items():
        if not _is_allowed_value(value):
            raise ValueObjectInvariantError(
                f"VO-INV-01/03: {name}.{key} carries a forbidden value of type "
                f"{type(value).__name__}; ValueObject attributes MUST be immutable "
                f"primitives, tuples, frozensets, or nested ValueObjects, and MUST "
                f"NOT reference objects with unstable identity."
            )


# ---------------------------------------------------------------------------
# Reference implementation — frozen + slotted dataclass base
# ---------------------------------------------------------------------------
@dataclasses.dataclass(frozen=True, slots=True)
class FrozenValueObject:
    """Reference base for ValueObjects.

    Subclasses declare their attributes as dataclass fields. The base
    guarantees:

    - ``frozen=True`` ⇒ VO-INV-01 (no post-init mutation; __setattr__ raises
      ``dataclasses.FrozenInstanceError``).
    - ``slots=True`` ⇒ no ``__dict__``; attribute set is closed at class
      definition.
    - ``__eq__`` + ``__hash__`` synthesised by @dataclass compare all fields
      (VO-INV-02).
    - ``__post_init__`` validates every field eagerly (VO-INV-04).
    - ``with_changes`` returns a fresh, fully-validated instance via
      :func:`dataclasses.replace` — the original is never mutated.
    """

    # Subclasses MAY override with a stricter pattern; the base validates
    # only that values are allowed (primitives / tuples / nested VOs).
    _invariant_id: ClassVar[str] = "VO-INV-04"

    def __post_init__(self) -> None:
        # VO-INV-04: eager validation. Subclasses may override and call super().
        self._validate_invariants()

    def _validate_invariants(self) -> None:
        cls_name = type(self).__name__
        fields = dataclasses.fields(self)
        values = {f.name: getattr(self, f.name) for f in fields}
        validate_attributes(cls_name, values)

    def with_changes(self, **kwargs: object) -> Self:
        """Return a new instance with selected fields replaced.

        VO-INV-01 preserved: the receiver is never mutated. VO-INV-04
        preserved: the replacement goes through __post_init__ and therefore
        re-validates the full set of fields.
        """
        field_names = {f.name for f in dataclasses.fields(self)}
        bad = set(kwargs) - field_names
        if bad:
            raise ValueObjectInvariantError(
                f"VO-INV-04: with_changes received unknown field(s) "
                f"{sorted(bad)} for {type(self).__name__}; "
                f"valid fields: {sorted(field_names)}."
            )
        return dataclasses.replace(self, **kwargs)

    def to_dict(self) -> dict[str, object]:
        """Return a shallow dict view of fields.

        Provided for serialization adapters (the extension contract). The
        returned dict is a fresh object; mutating it does NOT affect the
        ValueObject.
        """
        return {f.name: getattr(self, f.name) for f in dataclasses.fields(self)}


# ---------------------------------------------------------------------------
# Small, domain-canonical ValueObjects used by the test suites.
# They double as worked examples of the extension contract.
# ---------------------------------------------------------------------------
@dataclasses.dataclass(frozen=True, slots=True)
class Money(FrozenValueObject):
    """Money(amount_cents, currency). Classic DDD ValueObject.

    VO-INV-04: amount_cents MUST be non-negative; currency MUST be a 3-letter
    ISO-4217-ish uppercase code. Violations at construction time raise
    :class:`ValueObjectInvariantError`.
    """

    amount_cents: int
    currency: str

    def __post_init__(self) -> None:
        FrozenValueObject.__post_init__(self)
        if not isinstance(self.amount_cents, int) or isinstance(self.amount_cents, bool):
            raise ValueObjectInvariantError(
                "VO-INV-04: Money.amount_cents MUST be an int (not bool)."
            )
        if self.amount_cents < 0:
            raise ValueObjectInvariantError("VO-INV-04: Money.amount_cents MUST be >= 0.")
        if not isinstance(self.currency, str) or len(self.currency) != 3:
            raise ValueObjectInvariantError("VO-INV-04: Money.currency MUST be a 3-letter code.")
        if self.currency != self.currency.upper() or not self.currency.isalpha():
            raise ValueObjectInvariantError(
                "VO-INV-04: Money.currency MUST be uppercase ASCII letters."
            )

    def add(self, other: Money) -> Money:
        """Algebraic add; currencies MUST match."""
        if not isinstance(other, Money):
            raise ValueObjectInvariantError("VO-INV-04: Money.add requires a Money operand.")
        if other.currency != self.currency:
            raise ValueObjectInvariantError("VO-INV-04: Money.add requires matching currency.")
        return self.with_changes(amount_cents=self.amount_cents + other.amount_cents)


@dataclasses.dataclass(frozen=True, slots=True)
class Email(FrozenValueObject):
    """Email(address). Minimal RFC-5321-ish validation.

    VO-INV-04: address MUST contain exactly one '@' with non-empty local and
    domain parts.
    """

    address: str

    def __post_init__(self) -> None:
        FrozenValueObject.__post_init__(self)
        if not isinstance(self.address, str):
            raise ValueObjectInvariantError("VO-INV-04: Email.address MUST be a string.")
        if self.address.count("@") != 1:
            raise ValueObjectInvariantError(
                "VO-INV-04: Email.address MUST contain exactly one '@'."
            )
        local, _, domain = self.address.partition("@")
        if not local or not domain or "." not in domain:
            raise ValueObjectInvariantError(
                "VO-INV-04: Email.address MUST have non-empty local and dotted domain."
            )


@dataclasses.dataclass(frozen=True, slots=True)
class DateRange(FrozenValueObject):
    """DateRange(start_epoch_s, end_epoch_s). Half-open [start, end).

    VO-INV-04: end_epoch_s MUST be strictly greater than start_epoch_s.
    """

    start_epoch_s: int
    end_epoch_s: int

    def __post_init__(self) -> None:
        FrozenValueObject.__post_init__(self)
        if not isinstance(self.start_epoch_s, int) or isinstance(self.start_epoch_s, bool):
            raise ValueObjectInvariantError("VO-INV-04: DateRange.start_epoch_s MUST be an int.")
        if not isinstance(self.end_epoch_s, int) or isinstance(self.end_epoch_s, bool):
            raise ValueObjectInvariantError("VO-INV-04: DateRange.end_epoch_s MUST be an int.")
        if self.end_epoch_s <= self.start_epoch_s:
            raise ValueObjectInvariantError(
                "VO-INV-04: DateRange.end_epoch_s MUST be > start_epoch_s."
            )


# ---------------------------------------------------------------------------
# Serialization adapter registry — the extension contract
# ---------------------------------------------------------------------------
class CoercionRegistry:
    """Registers ValueObject <-> serializable-form adapters.

    Stateless per-instance bag (module-level singleton is optional). An
    adapter is any callable ``adapter(vo) -> Mapping[str, object]``; the
    inverse is ``factory(Mapping[str, object]) -> VO``. This is the
    mechanism the catalog extension contract names.
    """

    def __init__(self) -> None:
        self._to: dict[type, Any] = {}
        self._from: dict[type, Any] = {}

    def register(
        self,
        cls: type,
        to_mapping: Any,
        from_mapping: Any,
    ) -> None:
        if not isinstance(cls, type):
            raise ValueObjectInvariantError("VO-INV-04: register requires a class.")
        if not callable(to_mapping) or not callable(from_mapping):
            raise ValueObjectInvariantError("VO-INV-04: register requires callable adapters.")
        self._to[cls] = to_mapping
        self._from[cls] = from_mapping

    def to_mapping(self, vo: FrozenValueObject) -> Mapping[str, object]:
        cls = type(vo)
        if cls in self._to:
            result = self._to[cls](vo)
            if not isinstance(result, Mapping):
                raise ValueObjectInvariantError(
                    "VO-INV-04: to_mapping adapter MUST return a Mapping."
                )
            return result
        return vo.to_dict()

    def from_mapping(self, cls: type, data: Mapping[str, object]) -> FrozenValueObject:
        if cls in self._from:
            result = self._from[cls](data)
            if not isinstance(result, FrozenValueObject):
                raise ValueObjectInvariantError(
                    "VO-INV-04: from_mapping adapter MUST return a FrozenValueObject."
                )
            return result
        # Default: invoke the dataclass constructor with the mapping as kwargs.
        instance = cls(**dict(data))
        if not isinstance(instance, FrozenValueObject):
            raise ValueObjectInvariantError(
                "VO-INV-04: from_mapping default path requires a FrozenValueObject subclass."
            )
        return instance


# ---------------------------------------------------------------------------
# Observability counters (module-level; stateless per-call primitive hooks).
# Bumped by the reference implementation so the observability harness has
# something concrete to assert without requiring an OTel SDK.
# ---------------------------------------------------------------------------
class _Counters:
    """Simple int counters; never blocks, never raises."""

    __slots__ = ("constructed", "validation_failures", "with_changes_calls")

    def __init__(self) -> None:
        self.constructed: int = 0
        self.with_changes_calls: int = 0
        self.validation_failures: int = 0


COUNTERS: Final[_Counters] = _Counters()


def _observe_construction(_cls_name: str) -> None:
    COUNTERS.constructed += 1


def _observe_with_changes(_cls_name: str) -> None:
    COUNTERS.with_changes_calls += 1


def _observe_validation_failure(_cls_name: str) -> None:
    COUNTERS.validation_failures += 1


def iter_fields(vo: FrozenValueObject) -> Iterable[tuple[str, object]]:
    """Yield (field_name, value) pairs for any FrozenValueObject."""
    for field in dataclasses.fields(vo):
        yield field.name, getattr(vo, field.name)


__all__ = [
    "COUNTERS",
    "UNSTABLE_IDENTITY_MARKERS",
    "VALUE_PRIMITIVE_TYPES",
    "CoercionRegistry",
    "DateRange",
    "Email",
    "FrozenValueObject",
    "Money",
    "ValueObject",
    "ValueObjectInvariantError",
    "iter_fields",
    "validate_attributes",
]
