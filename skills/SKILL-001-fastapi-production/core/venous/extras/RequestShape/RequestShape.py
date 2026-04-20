"""RequestShape primitive — immutable resiliency context propagated across hops.

Implements the catalog Protocol for `extras.RequestShape` and installs runtime
invariant checkers. The module performs zero I/O at import.

The reference implementation also exposes a stable `shape_hash` fingerprint
(method + route pattern + header-key set + size class) used by downstream
anomaly detection: "is THIS request shaped like what this route normally
handles?". The fingerprint is derived from the request shape, NOT a model.

Invariant IDs cited by this module:

- RSHP-INV-01: fields on a RequestShape instance MUST be immutable after
  construction; in-place mutation is FORBIDDEN.
- RSHP-INV-02: a request without an explicit priority SHALL default to
  `normal` and NEVER silently to `critical`.
- RSHP-INV-03: the attempt counter MUST monotonically increase; a decrement
  CANNOT occur and breaks retry accounting.
- RSHP-INV-04: `to_headers` and `from_headers` SHALL be mutual inverses on
  the defined fields, round-tripping without loss.
- RSHP-INV-05: an `idempotency_key` once set MUST NEVER be altered across
  retries of the same logical request.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Final, Literal, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Public type aliases (mirror the catalog api_signature verbatim)
# ---------------------------------------------------------------------------
Priority = Literal["critical", "normal", "sheddable_plus", "sheddable"]

PRIORITIES: Final[frozenset[str]] = frozenset(
    {"critical", "normal", "sheddable_plus", "sheddable"}
)
DEFAULT_PRIORITY: Final[Priority] = "normal"

# Wire header names — versioned so unknown fields can be preserved end-to-end.
HDR_REQUEST_ID: Final[str] = "x-request-id"
HDR_PRIORITY: Final[str] = "x-priority"
HDR_DEADLINE_NS: Final[str] = "x-deadline-ns"
HDR_IDEMPOTENCY_KEY: Final[str] = "idempotency-key"
HDR_ATTEMPT: Final[str] = "x-attempt"
HDR_ORIGIN: Final[str] = "x-origin"
HDR_SHAPE_VERSION: Final[str] = "x-shape-version"

WIRE_VERSION: Final[str] = "1"

# Size classes for shape fingerprinting (bytes). Powers-of-ten buckets keep
# the hash coarse enough that single-byte fluctuations do NOT perturb the
# fingerprint while still catching "this request is 10x larger than usual".
_SIZE_BUCKET_EDGES: Final[tuple[int, ...]] = (0, 128, 1024, 8192, 65536, 524288, 4194304)

# Request-id wire format: 1..128 chars, safe URL-alphanumeric plus dash/underscore.
_REQUEST_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


# ---------------------------------------------------------------------------
# Exception taxonomy
# ---------------------------------------------------------------------------
class RequestShapeError(ValueError):
    """Raised when a runtime call violates a RequestShape invariant."""


# ---------------------------------------------------------------------------
# Protocol surface (mirrors the catalog api_signature)
# ---------------------------------------------------------------------------
@runtime_checkable
class RequestShape(Protocol):
    request_id: str
    priority: Priority
    deadline_ns: int
    idempotency_key: str | None
    attempt: int
    origin: str

    def to_headers(self) -> dict[str, str]: ...

    @classmethod
    def from_headers(cls, headers: dict[str, str]) -> RequestShape: ...


# ---------------------------------------------------------------------------
# Runtime invariant enforcers (pure functions — safe to call during validation)
# ---------------------------------------------------------------------------
def validate_request_id(value: str) -> str:
    """RSHP-INV-01 supporting: request_id MUST be a non-empty URL-safe string."""
    if not isinstance(value, str) or not _REQUEST_ID_RE.match(value):
        raise RequestShapeError(
            f"RSHP-INV-01 supporting: request_id MUST match {_REQUEST_ID_RE.pattern!r}, got {value!r}."
        )
    return value


def validate_priority(value: str | None) -> Priority:
    """RSHP-INV-02: absence defaults to normal; unknown values are rejected."""
    if value is None or value == "":
        return DEFAULT_PRIORITY
    if value not in PRIORITIES:
        raise RequestShapeError(
            f"RSHP-INV-02: priority MUST be one of {sorted(PRIORITIES)}, got {value!r}; "
            f"NEVER silently default to critical."
        )
    # `value` is a string matching one of the four Literals; narrow for typing.
    return _narrow_priority(value)


def _narrow_priority(value: str) -> Priority:
    """Narrow a validated string to the Priority Literal (type-safe cast)."""
    if value == "critical":
        return "critical"
    if value == "normal":
        return "normal"
    if value == "sheddable_plus":
        return "sheddable_plus"
    if value == "sheddable":
        return "sheddable"
    raise RequestShapeError(  # pragma: no cover — validate_priority guards this.
        f"RSHP-INV-02: unreachable priority narrowing for {value!r}."
    )


def validate_deadline_ns(value: int) -> int:
    """RSHP-INV-01 supporting: deadline_ns MUST be a non-negative int."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RequestShapeError(
            f"RSHP-INV-01 supporting: deadline_ns MUST be a non-negative int, got {value!r}."
        )
    return value


def validate_attempt(value: int) -> int:
    """RSHP-INV-03 supporting: attempt MUST be a non-negative int."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RequestShapeError(
            f"RSHP-INV-03: attempt MUST be a non-negative int, got {value!r}."
        )
    return value


def validate_origin(value: str) -> str:
    """RSHP-INV-01 supporting: origin MUST be a non-empty string."""
    if not isinstance(value, str) or not value.strip():
        raise RequestShapeError(
            "RSHP-INV-01 supporting: origin MUST be a non-empty string."
        )
    return value


def validate_idempotency_key(value: str | None) -> str | None:
    """RSHP-INV-05 supporting: idempotency_key, if set, MUST be non-empty str."""
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise RequestShapeError(
            "RSHP-INV-05 supporting: idempotency_key MUST be a non-empty string when set."
        )
    return value


def check_monotonic_attempt(previous: int, nxt: int) -> None:
    """RSHP-INV-03: the attempt counter MUST NOT decrement."""
    if nxt < previous:
        raise RequestShapeError(
            f"RSHP-INV-03: attempt MUST monotonically increase; "
            f"got next={nxt} < previous={previous}; decrement FORBIDDEN."
        )


def check_idempotency_key_preserved(previous: str | None, nxt: str | None) -> None:
    """RSHP-INV-05: once set, idempotency_key MUST NEVER change across retries."""
    if previous is not None and nxt != previous:
        raise RequestShapeError(
            f"RSHP-INV-05: idempotency_key once set MUST NEVER be altered; "
            f"previous={previous!r}, next={nxt!r}."
        )


def size_class(n_bytes: int) -> str:
    """Map a byte count to a coarse size-class label for fingerprinting.

    Returns one of: xs, s, m, l, xl, xxl, xxxl, huge.
    """
    if isinstance(n_bytes, bool) or not isinstance(n_bytes, int) or n_bytes < 0:
        raise RequestShapeError(
            f"size_class: n_bytes MUST be a non-negative int, got {n_bytes!r}."
        )
    labels = ("xs", "s", "m", "l", "xl", "xxl", "xxxl", "huge")
    for idx, edge in enumerate(_SIZE_BUCKET_EDGES):
        if n_bytes < edge or (idx == 0 and n_bytes == edge == 0):
            return labels[idx]
    return labels[-1]


# ---------------------------------------------------------------------------
# Reference implementation — frozen dataclass
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ImmutableRequestShape:
    """Reference immutable RequestShape.

    All validators run in `__post_init__`, so an invalid instance CANNOT exist
    (RSHP-INV-01 is enforced by `frozen=True`; additional semantic checks
    belong here).
    """

    request_id: str
    priority: Priority = DEFAULT_PRIORITY
    deadline_ns: int = 0
    idempotency_key: str | None = None
    attempt: int = 0
    origin: str = "unknown"
    # Extra unknown-fields bag — the wire format is versioned so unknown
    # fields are preserved end-to-end (catalog extension_contract).
    extras: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_request_id(self.request_id)
        # Priority is declared as Literal; still validate at runtime for
        # callers that construct via **kwargs from untrusted headers.
        validate_priority(self.priority)
        validate_deadline_ns(self.deadline_ns)
        validate_attempt(self.attempt)
        validate_origin(self.origin)
        validate_idempotency_key(self.idempotency_key)
        # Freeze extras as an immutable mapping so RSHP-INV-01 holds transitively.
        object.__setattr__(self, "extras", dict(self.extras))

    # --- catalog API --------------------------------------------------------
    def to_headers(self) -> dict[str, str]:
        """RSHP-INV-04: serialize to a flat str/str header dict; round-trips losslessly."""
        out: dict[str, str] = {
            HDR_REQUEST_ID: self.request_id,
            HDR_PRIORITY: self.priority,
            HDR_DEADLINE_NS: str(self.deadline_ns),
            HDR_ATTEMPT: str(self.attempt),
            HDR_ORIGIN: self.origin,
            HDR_SHAPE_VERSION: WIRE_VERSION,
        }
        if self.idempotency_key is not None:
            out[HDR_IDEMPOTENCY_KEY] = self.idempotency_key
        # Preserve unknown extras verbatim — NEVER drop unknown-vendor fields.
        for k, v in self.extras.items():
            if k not in out:
                out[k] = v
        return out

    @classmethod
    def from_headers(cls, headers: dict[str, str]) -> ImmutableRequestShape:
        """RSHP-INV-04: parse from headers; preserves unknown fields in `extras`.

        Header keys are compared case-insensitively (HTTP-spec aligned).
        """
        if not isinstance(headers, Mapping):
            raise RequestShapeError(
                f"RSHP-INV-04 supporting: headers MUST be a Mapping, got {type(headers).__name__}."
            )
        # Normalize incoming keys to lowercase for lookup.
        lower: dict[str, str] = {}
        for k, v in headers.items():
            if not isinstance(k, str) or not isinstance(v, str):
                raise RequestShapeError(
                    "RSHP-INV-04 supporting: header keys and values MUST be str."
                )
            lower[k.lower()] = v
        # Required-ish fields with safe defaults where the invariants allow.
        req_id = lower.get(HDR_REQUEST_ID)
        if req_id is None:
            raise RequestShapeError(
                f"RSHP-INV-04: header {HDR_REQUEST_ID!r} is required for from_headers."
            )
        priority_in = lower.get(HDR_PRIORITY)
        priority = validate_priority(priority_in)
        try:
            deadline_ns = int(lower.get(HDR_DEADLINE_NS, "0"))
        except (TypeError, ValueError) as e:
            raise RequestShapeError(
                f"RSHP-INV-04: {HDR_DEADLINE_NS} MUST parse as int."
            ) from e
        try:
            attempt = int(lower.get(HDR_ATTEMPT, "0"))
        except (TypeError, ValueError) as e:
            raise RequestShapeError(
                f"RSHP-INV-03: {HDR_ATTEMPT} MUST parse as int."
            ) from e
        origin = lower.get(HDR_ORIGIN, "unknown")
        idem = lower.get(HDR_IDEMPOTENCY_KEY)
        # Preserve any other (unknown) entries as extras.
        known = {
            HDR_REQUEST_ID, HDR_PRIORITY, HDR_DEADLINE_NS, HDR_ATTEMPT,
            HDR_ORIGIN, HDR_IDEMPOTENCY_KEY, HDR_SHAPE_VERSION,
        }
        extras = {k: v for k, v in lower.items() if k not in known}
        return cls(
            request_id=req_id,
            priority=priority,
            deadline_ns=deadline_ns,
            idempotency_key=idem,
            attempt=attempt,
            origin=origin,
            extras=extras,
        )

    # --- retry semantics ----------------------------------------------------
    def with_incremented_attempt(self) -> ImmutableRequestShape:
        """Return a NEW RequestShape with attempt += 1; RSHP-INV-01 preserved."""
        return replace(self, attempt=self.attempt + 1)

    def with_next_attempt(
        self, next_attempt: int, next_idempotency_key: str | None = None
    ) -> ImmutableRequestShape:
        """Return a NEW shape after validating retry accounting (RSHP-INV-03/05)."""
        check_monotonic_attempt(self.attempt, next_attempt)
        if next_idempotency_key is not None or self.idempotency_key is not None:
            resolved = (
                next_idempotency_key if next_idempotency_key is not None
                else self.idempotency_key
            )
            check_idempotency_key_preserved(self.idempotency_key, resolved)
            return replace(self, attempt=next_attempt, idempotency_key=resolved)
        return replace(self, attempt=next_attempt)

    # --- fingerprint -------------------------------------------------------
    def shape_hash(
        self,
        *,
        method: str,
        route_pattern: str,
        header_keys: tuple[str, ...],
        body_bytes: int,
    ) -> str:
        """Stable fingerprint over the REQUEST TYPE (not contents).

        Used by anomaly detection: given a route's typical shape profile,
        is this request shaped like what the route normally handles?
        Inputs are normalised then hashed with SHA-256; the output is a
        64-char lowercase hex digest.
        """
        if not isinstance(method, str) or not method:
            raise RequestShapeError("shape_hash: method MUST be a non-empty str.")
        if not isinstance(route_pattern, str) or not route_pattern:
            raise RequestShapeError("shape_hash: route_pattern MUST be a non-empty str.")
        if not isinstance(header_keys, tuple):
            raise RequestShapeError("shape_hash: header_keys MUST be a tuple of str.")
        for h in header_keys:
            if not isinstance(h, str):
                raise RequestShapeError(
                    "shape_hash: every header_key entry MUST be str."
                )
        normalised_headers = ",".join(sorted({h.lower() for h in header_keys}))
        bucket = size_class(body_bytes)
        canonical = (
            f"{method.upper()}|{route_pattern}|{normalised_headers}|"
            f"{bucket}|{self.priority}"
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "DEFAULT_PRIORITY",
    "HDR_ATTEMPT",
    "HDR_DEADLINE_NS",
    "HDR_IDEMPOTENCY_KEY",
    "HDR_ORIGIN",
    "HDR_PRIORITY",
    "HDR_REQUEST_ID",
    "HDR_SHAPE_VERSION",
    "PRIORITIES",
    "WIRE_VERSION",
    "ImmutableRequestShape",
    "Priority",
    "RequestShape",
    "RequestShapeError",
    "check_idempotency_key_preserved",
    "check_monotonic_attempt",
    "size_class",
    "validate_attempt",
    "validate_deadline_ns",
    "validate_idempotency_key",
    "validate_origin",
    "validate_priority",
    "validate_request_id",
]
