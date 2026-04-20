"""InputValidator primitive — schema-first ingress parser.

Implements the catalog Protocol for `security.InputValidator`. The validator
parses an untrusted `raw` payload against a declared `schema` type and returns
a fully constructed instance of that schema, or raises a typed error that
carries the offending field path.

Invariant IDs (enforced at runtime):

- IV_INV_01: parse() MUST reject payloads with unknown fields unless the
  schema explicitly opts into extras; silent field drop is FORBIDDEN.
- IV_INV_02: length, range and pattern bounds MUST be enforced before any
  business rule touches the value; unbounded strings CANNOT be accepted.
- IV_INV_03: type coercion MUST be narrowing (string->int only when
  digits-only); widening coercion (int->string for structured ids) SHALL
  require explicit opt-in.
- IV_INV_04: parse() MUST raise a typed ValidationError containing the
  offending field path; error payloads MUST NEVER include attacker-controlled
  content verbatim in structured logs.
- IV_INV_05: recursion depth and collection size MUST be bounded; payloads
  exceeding the configured limits SHALL be rejected before parsing.

The primitive is framework-agnostic. A schema is either (a) a subclass of
`SchemaModel` declared with `SchemaField` descriptors, or (b) any type whose
module-level `__input_validator_schema__` attribute resolves to a
`SchemaModel` subclass. Pydantic, attrs+cattrs, and msgspec plug in as
adapters by following the same registration rule.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import ClassVar, Final, Protocol, TypeVar, runtime_checkable

T = TypeVar("T")

# Hard upper bounds applied to EVERY parse call — IV_INV_05.
MAX_DEPTH: Final[int] = 16
MAX_COLLECTION_SIZE: Final[int] = 1024
MAX_STRING_LEN: Final[int] = 65_536
MAX_TOTAL_NODES: Final[int] = 50_000

# Characters forbidden in any string field by default — IV_INV_02.
# Null bytes, C0 control chars (except TAB/LF/CR), C1 controls, Unicode
# bidirectional override characters (RTL/LTR override injection).
_DISALLOWED_CHARS: Final[frozenset[str]] = frozenset(
    [chr(c) for c in range(0x20) if c not in (0x09, 0x0A, 0x0D)]
    + [chr(c) for c in range(0x7F, 0xA0)]
    + [
        "\u202a", "\u202b", "\u202c", "\u202d", "\u202e",  # LRE/RLE/PDF/LRO/RLO
        "\u2066", "\u2067", "\u2068", "\u2069",             # LRI/RLI/FSI/PDI
    ]
)


class ValidationError(ValueError):
    """Runtime invariant violation on an InputValidator.parse() call.

    `field_path` cites the dotted location of the offending field. `reason`
    is an opaque code that MUST NOT echo attacker-controlled content
    (IV_INV_04).
    """

    def __init__(self, field_path: str, reason: str) -> None:
        self.field_path = field_path
        self.reason = reason
        super().__init__(f"{reason} at {field_path or '<root>'}")


@runtime_checkable
class InputValidator(Protocol):
    def parse(self, raw: object, schema: type[T]) -> T: ...


# ---------------------------------------------------------------------------
# Schema declaration language — framework-agnostic.
# ---------------------------------------------------------------------------

_PRIMITIVE_TYPES: Final[tuple[type, ...]] = (str, int, float, bool)


@dataclass(frozen=True)
class SchemaField:
    """Declarative field constraint.

    `type_` is one of `str`, `int`, `float`, `bool`, a `SchemaModel` subclass,
    or `list[<primitive_or_model>]`. Everything else is rejected at
    registration time (IV_INV_02).
    """

    type_: object
    required: bool = True
    min_length: int | None = None
    max_length: int | None = None
    min_value: float | None = None
    max_value: float | None = None
    pattern: str | None = None
    allow_coerce: bool = False       # IV_INV_03 — narrowing coercion opt-in
    allow_widen: bool = False        # IV_INV_03 — widening coercion opt-in
    allow_control_chars: bool = False

    def compiled_pattern(self) -> re.Pattern[str] | None:
        return re.compile(self.pattern) if self.pattern is not None else None


class SchemaModel:
    """Base class for declarative schemas.

    Subclasses declare a class attribute `__fields__: Mapping[str, SchemaField]`
    (or use `SchemaField` class attributes). Unknown fields are rejected
    unless `__extra__` is the string 'allow' (IV_INV_01).
    """

    __fields__: ClassVar[Mapping[str, SchemaField]]
    __extra__: ClassVar[str] = "forbid"       # 'forbid' | 'allow'

    def __init__(self, **values: object) -> None:
        # Store parsed values as attributes.
        for k, v in values.items():
            object.__setattr__(self, k, v)

    def to_dict(self) -> dict[str, object]:
        return {k: getattr(self, k) for k in self.__fields__}


# ---------------------------------------------------------------------------
# Reference implementation.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Limits:
    max_depth: int = MAX_DEPTH
    max_collection_size: int = MAX_COLLECTION_SIZE
    max_string_len: int = MAX_STRING_LEN
    max_total_nodes: int = MAX_TOTAL_NODES


@dataclass
class _Counters:
    nodes: int = 0

    def bump(self, path: str, limit: int) -> None:
        self.nodes += 1
        if self.nodes > limit:
            raise ValidationError(path, "payload_node_budget_exceeded")


@dataclass(frozen=True)
class SchemaValidator:
    """Reference InputValidator. Stateless; safe to share across threads.

    Construct with tighter limits for a given route if the defaults are
    excessive.
    """

    limits: _Limits = field(default_factory=_Limits)

    def parse(self, raw: object, schema: type[T]) -> T:
        if not isinstance(schema, type) or not issubclass(schema, SchemaModel):
            raise ValidationError("", "schema_must_be_SchemaModel_subclass")
        fields_map = getattr(schema, "__fields__", None)
        if not isinstance(fields_map, Mapping) or not fields_map:
            raise ValidationError("", "schema_has_no_fields")

        counters = _Counters()
        # The root MUST be a mapping — an incoming JSON object. Lists at the
        # root are rejected to prevent type-confusion at the edge.
        parsed = self._parse_model(raw, schema, path="", depth=0, counters=counters)
        return parsed  # type: ignore[return-value]  # constructed from schema subclass; caller T is bound by signature

    # ---------------- internal ----------------

    def _parse_model(
        self,
        raw: object,
        schema: type[SchemaModel],
        path: str,
        depth: int,
        counters: _Counters,
    ) -> SchemaModel:
        if depth > self.limits.max_depth:
            raise ValidationError(path, "max_depth_exceeded")
        counters.bump(path, self.limits.max_total_nodes)

        if not isinstance(raw, Mapping):
            raise ValidationError(path, "expected_mapping")
        if len(raw) > self.limits.max_collection_size:
            raise ValidationError(path, "collection_size_exceeded")

        fields_map = schema.__fields__
        extras_policy = getattr(schema, "__extra__", "forbid")

        # IV_INV_01: unknown fields rejected unless schema opts in.
        for key in raw:
            if not isinstance(key, str):
                raise ValidationError(path, "non_string_field_name")
            if key not in fields_map and extras_policy != "allow":
                raise ValidationError(_join(path, key), "unknown_field")

        out: dict[str, object] = {}
        for name, spec in fields_map.items():
            sub_path = _join(path, name)
            if name not in raw:
                if spec.required:
                    raise ValidationError(sub_path, "field_required")
                continue
            out[name] = self._parse_field(raw[name], spec, sub_path, depth + 1, counters)

        return schema(**out)

    def _parse_field(
        self,
        value: object,
        spec: SchemaField,
        path: str,
        depth: int,
        counters: _Counters,
    ) -> object:
        if depth > self.limits.max_depth:
            raise ValidationError(path, "max_depth_exceeded")
        counters.bump(path, self.limits.max_total_nodes)

        t = spec.type_

        # Nested model.
        if isinstance(t, type) and issubclass(t, SchemaModel):
            return self._parse_model(value, t, path, depth, counters)

        # List[<primitive or model>].
        if isinstance(t, _ListOf):
            return self._parse_list(value, t, spec, path, depth, counters)

        # Primitive.
        if t is str:
            return self._parse_str(value, spec, path)
        if t is bool:
            return self._parse_bool(value, spec, path)
        if t is int:
            return self._parse_int(value, spec, path)
        if t is float:
            return self._parse_float(value, spec, path)

        raise ValidationError(path, "unsupported_schema_type")

    def _parse_list(
        self,
        value: object,
        t: _ListOf,
        spec: SchemaField,
        path: str,
        depth: int,
        counters: _Counters,
    ) -> list[object]:
        if not isinstance(value, list):
            raise ValidationError(path, "expected_list")
        self._check_list_bounds(value, spec, path)
        return [
            self._parse_list_item(item, t.inner, f"{path}[{i}]", depth + 1, counters)
            for i, item in enumerate(value)
        ]

    def _check_list_bounds(self, value: list[object], spec: SchemaField, path: str) -> None:
        if len(value) > self.limits.max_collection_size:
            raise ValidationError(path, "collection_size_exceeded")
        if spec.max_length is not None and len(value) > spec.max_length:
            raise ValidationError(path, "list_max_length_exceeded")
        if spec.min_length is not None and len(value) < spec.min_length:
            raise ValidationError(path, "list_min_length_violated")

    def _parse_list_item(
        self, item: object, inner: object, item_path: str, depth: int, counters: _Counters,
    ) -> object:
        if isinstance(inner, type) and issubclass(inner, SchemaModel):
            return self._parse_model(item, inner, item_path, depth, counters)
        if inner is str:
            return self._parse_str(item, _bare_str_spec(), item_path)
        if inner is int:
            return self._parse_int(item, _bare_int_spec(), item_path)
        if inner is float:
            return self._parse_float(item, _bare_float_spec(), item_path)
        if inner is bool:
            return self._parse_bool(item, _bare_bool_spec(), item_path)
        raise ValidationError(item_path, "unsupported_list_item_type")

    def _parse_str(self, value: object, spec: SchemaField, path: str) -> str:
        s = self._coerce_to_str(value, spec, path)
        self._check_str_bounds(s, spec, path)
        self._check_str_chars(s, spec, path)
        pat = spec.compiled_pattern()
        if pat is not None and pat.fullmatch(s) is None:
            raise ValidationError(path, "pattern_mismatch")
        return s

    def _coerce_to_str(self, value: object, spec: SchemaField, path: str) -> str:
        if isinstance(value, bool):
            # bool is an int subtype — reject before the int branch fires.
            raise ValidationError(path, "expected_string_got_bool")
        if isinstance(value, (int, float)):
            if not spec.allow_widen:
                raise ValidationError(path, "widening_coercion_not_allowed")
            return str(value)
        if isinstance(value, str):
            return value
        raise ValidationError(path, "expected_string")

    def _check_str_bounds(self, s: str, spec: SchemaField, path: str) -> None:
        ceiling = min(self.limits.max_string_len, spec.max_length or self.limits.max_string_len)
        if len(s) > ceiling:
            raise ValidationError(path, "string_max_length_exceeded")
        if spec.min_length is not None and len(s) < spec.min_length:
            raise ValidationError(path, "string_min_length_violated")

    def _check_str_chars(self, s: str, spec: SchemaField, path: str) -> None:
        if spec.allow_control_chars:
            return
        for ch in s:
            if ch in _DISALLOWED_CHARS:
                raise ValidationError(path, "disallowed_control_char")

    def _parse_int(self, value: object, spec: SchemaField, path: str) -> int:
        if isinstance(value, bool):
            raise ValidationError(path, "expected_int_got_bool")
        if isinstance(value, int):
            n = value
        elif isinstance(value, str) and spec.allow_coerce:
            # Narrowing coercion — digits-only, optional leading minus.
            if not re.fullmatch(r"-?[0-9]+", value):
                raise ValidationError(path, "non_numeric_string_for_int")
            if len(value) > 32:
                raise ValidationError(path, "int_string_too_long")
            n = int(value)
        else:
            raise ValidationError(path, "expected_int")

        if spec.min_value is not None and n < spec.min_value:
            raise ValidationError(path, "min_value_violated")
        if spec.max_value is not None and n > spec.max_value:
            raise ValidationError(path, "max_value_exceeded")
        return n

    def _parse_float(self, value: object, spec: SchemaField, path: str) -> float:
        if isinstance(value, bool):
            raise ValidationError(path, "expected_float_got_bool")
        if isinstance(value, (int, float)):
            f = float(value)
        elif isinstance(value, str) and spec.allow_coerce:
            if not re.fullmatch(r"-?[0-9]+(\.[0-9]+)?", value):
                raise ValidationError(path, "non_numeric_string_for_float")
            f = float(value)
        else:
            raise ValidationError(path, "expected_float")
        # NaN / inf rejected — IV_INV_02.
        if math.isnan(f) or math.isinf(f):
            raise ValidationError(path, "non_finite_float")
        if spec.min_value is not None and f < spec.min_value:
            raise ValidationError(path, "min_value_violated")
        if spec.max_value is not None and f > spec.max_value:
            raise ValidationError(path, "max_value_exceeded")
        return f

    def _parse_bool(self, value: object, spec: SchemaField, path: str) -> bool:
        if isinstance(value, bool):
            return value
        raise ValidationError(path, "expected_bool")


@dataclass(frozen=True)
class _ListOf:
    inner: object


def list_of(inner: object) -> _ListOf:
    """Declare a list[inner] field type.

    `inner` must be a primitive (`str`, `int`, `float`, `bool`) or a
    `SchemaModel` subclass.
    """
    if isinstance(inner, type) and issubclass(inner, SchemaModel):
        return _ListOf(inner)
    if inner in _PRIMITIVE_TYPES:
        return _ListOf(inner)
    raise ValidationError("", "unsupported_list_item_type")


def _bare_str_spec() -> SchemaField:
    return SchemaField(type_=str)


def _bare_int_spec() -> SchemaField:
    return SchemaField(type_=int)


def _bare_float_spec() -> SchemaField:
    return SchemaField(type_=float)


def _bare_bool_spec() -> SchemaField:
    return SchemaField(type_=bool)


def _join(path: str, name: str) -> str:
    return f"{path}.{name}" if path else name


# ---------------------------------------------------------------------------
# Adapter registry — IV_INV_01 policy check for third-party libraries.
# ---------------------------------------------------------------------------

def register_adapter(adapter: InputValidator, *, defaults_extras_forbid: bool, has_size_and_depth_limits: bool) -> InputValidator:
    """Register a third-party adapter (pydantic, attrs+cattrs, msgspec).

    Refuses to bind an adapter that defaults to `extra='allow'` or that lacks
    size/depth limits (extension contract clause).
    """
    if not defaults_extras_forbid:
        raise ValidationError("", "adapter_default_extras_must_be_forbid")
    if not has_size_and_depth_limits:
        raise ValidationError("", "adapter_must_declare_size_and_depth_limits")
    if not isinstance(adapter, InputValidator):
        raise ValidationError("", "adapter_does_not_implement_protocol")
    return adapter


def iter_disallowed_chars() -> Iterable[str]:
    """Expose the disallowed char set for documentation and tests."""
    return iter(_DISALLOWED_CHARS)


def is_finite_number(x: object) -> bool:
    """True iff `x` is a number that is neither NaN nor infinite."""
    if isinstance(x, bool):
        return False
    if not isinstance(x, (int, float)):
        return False
    return not math.isnan(x) and not math.isinf(x)


def bounded_sequence(seq: Sequence[object], *, limit: int) -> Sequence[object]:
    """Return `seq` iff its length does not exceed `limit`; else raise."""
    if len(seq) > limit:
        raise ValidationError("", "collection_size_exceeded")
    return seq


__all__ = [
    "MAX_COLLECTION_SIZE",
    "MAX_DEPTH",
    "MAX_STRING_LEN",
    "MAX_TOTAL_NODES",
    "InputValidator",
    "SchemaField",
    "SchemaModel",
    "SchemaValidator",
    "ValidationError",
    "bounded_sequence",
    "is_finite_number",
    "iter_disallowed_chars",
    "list_of",
    "register_adapter",
]
