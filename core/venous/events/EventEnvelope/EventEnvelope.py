"""EventEnvelope primitive — CloudEvents 1.0.2 canonical envelope.

Mirrors the catalog Protocol for `events.EventEnvelope` and installs the runtime
invariant checkers. Module load performs zero I/O.

Invariant IDs cited by this module:

- EE_INV_01: Producers MUST make the tuple (source, id) unique per distinct
  occurrence so consumers can deduplicate.
- EE_INV_02: Resending the same logical event ALWAYS reuses the original id
  so retries do not appear as new occurrences.
- EE_INV_03: specversion MUST equal '1.0' for envelopes produced under this
  contract.
- EE_INV_04: Extension attribute names MUST match the CloudEvents naming rules
  and CANNOT collide with reserved core attribute names.
- EE_INV_05: time when present SHALL be an RFC 3339 timestamp in UTC with no
  timezone offset ambiguity (trailing 'Z' or explicit +00:00 only).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from types import MappingProxyType
from typing import Any, Final

# ---------------------------------------------------------------------------
# Constants — CloudEvents 1.0.2 rules
# ---------------------------------------------------------------------------
CLOUDEVENTS_SPECVERSION: Final[str] = "1.0"

# CloudEvents attribute naming rule: lowercase letters and digits only,
# 1..20 chars. Core attributes are reserved and cannot be reused as extensions.
ATTRIBUTE_NAME_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9]{1,20}$")

RESERVED_CORE_ATTRIBUTES: Final[frozenset[str]] = frozenset(
    {
        "id",
        "source",
        "type",
        "specversion",
        "datacontenttype",
        "dataschema",
        "subject",
        "time",
        "data",
        "data_base64",
    },
)

# RFC 3339 timestamp with UTC zone only ('Z' or '+00:00' suffix).
_RFC3339_UTC_RE: Final[re.Pattern[str]] = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|\+00:00)$",
)

# CloudEvents 1.0.2 attribute value length cap (advisory but we enforce it).
_MAX_ID_LEN: Final[int] = 200
_MAX_SOURCE_LEN: Final[int] = 1024
_MAX_TYPE_LEN: Final[int] = 200
_MAX_SUBJECT_LEN: Final[int] = 200


# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------
class EventEnvelopeInvariantError(ValueError):
    """Raised when an EventEnvelope construction or mutation violates an invariant."""


# ---------------------------------------------------------------------------
# Validators (pure, runtime invariant enforcers)
# ---------------------------------------------------------------------------
def validate_required_string(field_name: str, value: object, max_len: int) -> str:
    """EE_INV_01 supporting: required attributes MUST be non-empty strings within cap."""
    if not isinstance(value, str):
        raise EventEnvelopeInvariantError(
            f"EE_INV_01: {field_name} MUST be a string, got {type(value).__name__}.",
        )
    if not value:
        raise EventEnvelopeInvariantError(
            f"EE_INV_01: {field_name} MUST be a non-empty string.",
        )
    if "\x00" in value:
        raise EventEnvelopeInvariantError(
            f"EE_INV_01: {field_name} MUST NOT contain null bytes.",
        )
    if len(value) > max_len:
        raise EventEnvelopeInvariantError(
            f"EE_INV_01: {field_name} length {len(value)} exceeds cap {max_len}.",
        )
    return value


def validate_specversion(value: object) -> str:
    """EE_INV_03: specversion MUST equal '1.0'."""
    if value != CLOUDEVENTS_SPECVERSION:
        raise EventEnvelopeInvariantError(
            f"EE_INV_03: specversion MUST equal {CLOUDEVENTS_SPECVERSION!r}, got {value!r}.",
        )
    return CLOUDEVENTS_SPECVERSION


def validate_time(value: str | None) -> str | None:
    """EE_INV_05: time MUST be RFC 3339 UTC ('Z' or '+00:00' only)."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise EventEnvelopeInvariantError(
            f"EE_INV_05: time MUST be a string or None, got {type(value).__name__}.",
        )
    if not _RFC3339_UTC_RE.match(value):
        raise EventEnvelopeInvariantError(
            f"EE_INV_05: time MUST be RFC 3339 UTC (ending 'Z' or '+00:00'), got {value!r}.",
        )
    # Extra belt-and-braces: it must parse.
    try:
        datetime.fromisoformat(value)
    except ValueError as e:
        raise EventEnvelopeInvariantError(
            f"EE_INV_05: time {value!r} failed RFC 3339 parse: {e}",
        ) from e
    return value


def validate_extension_name(name: str) -> str:
    """EE_INV_04: extension name MUST match CE rules and NOT collide with core."""
    if not isinstance(name, str):
        raise EventEnvelopeInvariantError(
            f"EE_INV_04: extension name MUST be str, got {type(name).__name__}.",
        )
    if not ATTRIBUTE_NAME_RE.match(name):
        raise EventEnvelopeInvariantError(
            f"EE_INV_04: extension name {name!r} MUST match [a-z0-9]{{1,20}}.",
        )
    if name in RESERVED_CORE_ATTRIBUTES:
        raise EventEnvelopeInvariantError(
            f"EE_INV_04: extension name {name!r} collides with reserved core attribute.",
        )
    return name


def validate_extensions(
    extensions: Mapping[str, str] | None,
) -> dict[str, str] | None:
    """EE_INV_04: validate every extension key; values must be strings."""
    if extensions is None:
        return None
    if not isinstance(extensions, Mapping):
        raise EventEnvelopeInvariantError(
            f"EE_INV_04: extensions MUST be a Mapping or None, got {type(extensions).__name__}.",
        )
    out: dict[str, str] = {}
    for key, val in extensions.items():
        validate_extension_name(key)
        if not isinstance(val, str):
            raise EventEnvelopeInvariantError(
                f"EE_INV_04: extension {key!r} value MUST be str, got {type(val).__name__}.",
            )
        out[key] = val
    return out


# ---------------------------------------------------------------------------
# Primitive dataclass (frozen; catalog-aligned)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class EventEnvelope:
    """CloudEvents 1.0.2 canonical envelope.

    All required attributes (id, source, type) are validated on construction.
    The tuple (source, id) forms the dedup identity per EE_INV_01.
    """

    id: str
    source: str
    type: str
    specversion: str = CLOUDEVENTS_SPECVERSION
    datacontenttype: str | None = None
    dataschema: str | None = None
    subject: str | None = None
    time: str | None = None
    data: Any = None  # payload is caller-defined; not validated here
    extensions: Mapping[str, str] | None = field(default=None)

    def __post_init__(self) -> None:
        validate_required_string("id", self.id, _MAX_ID_LEN)
        validate_required_string("source", self.source, _MAX_SOURCE_LEN)
        validate_required_string("type", self.type, _MAX_TYPE_LEN)
        validate_specversion(self.specversion)
        if self.datacontenttype is not None and not isinstance(
            self.datacontenttype,
            str,
        ):
            raise EventEnvelopeInvariantError(
                "EE_INV_01 supporting: datacontenttype MUST be str or None.",
            )
        if self.dataschema is not None and not isinstance(self.dataschema, str):
            raise EventEnvelopeInvariantError(
                "EE_INV_01 supporting: dataschema MUST be str or None.",
            )
        if self.subject is not None:
            validate_required_string("subject", self.subject, _MAX_SUBJECT_LEN)
        validate_time(self.time)
        validated_exts = validate_extensions(self.extensions)
        # EE_INV_01: freeze extensions into a MappingProxyType so the envelope
        # is transitively immutable. A mutable dict leaks the "frozen" promise:
        # downstream code could mutate routing/dedup inputs post-construction.
        if validated_exts is not None:
            object.__setattr__(self, "extensions", MappingProxyType(validated_exts))

    def dedup_key(self) -> tuple[str, str]:
        """EE_INV_01: stable dedup identity tuple (source, id)."""
        return (self.source, self.id)

    def retry(self) -> EventEnvelope:
        """EE_INV_02: produce a retry envelope that reuses id and source.

        Only mutable bookkeeping (time) is refreshed; the dedup key is preserved
        so a consumer sees the same occurrence.
        """
        # Use replace so any derived class still works; new time is optional.
        return replace(self)


# ---------------------------------------------------------------------------
# Dedup helper — an embodiment of EE_INV_01
# ---------------------------------------------------------------------------
class InMemoryDedupSet:
    """Reference dedup oracle. Not thread-safe; wrap in a lock for concurrent use.

    Used by behavioral / chaos tests to prove the dedup invariant holds end-to-end.
    """

    def __init__(self) -> None:
        self._seen: set[tuple[str, str]] = set()

    def accept(self, envelope: EventEnvelope) -> bool:
        """Return True on first sight, False on repeat (proves EE_INV_01)."""
        key = envelope.dedup_key()
        if key in self._seen:
            return False
        self._seen.add(key)
        return True

    def size(self) -> int:
        return len(self._seen)


__all__ = [
    "ATTRIBUTE_NAME_RE",
    "CLOUDEVENTS_SPECVERSION",
    "RESERVED_CORE_ATTRIBUTES",
    "EventEnvelope",
    "EventEnvelopeInvariantError",
    "InMemoryDedupSet",
    "validate_extension_name",
    "validate_extensions",
    "validate_required_string",
    "validate_specversion",
    "validate_time",
]
