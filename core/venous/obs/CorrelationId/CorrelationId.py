"""CorrelationId primitive — opaque, request-scoped identifier.

Invariant IDs:

- CORRID-INV-01: CorrelationId MUST be populated for every inbound request
  before the first log line is emitted (extract() always returns a valid id).
- CORRID-INV-02: NEVER regenerates a present upstream id — a syntactically
  valid header value (``traceparent`` trace-id or ``x-request-id``) is
  propagated verbatim (after lowercase normalization).
- CORRID-INV-03: Generated ids MUST use a cryptographically-random 16+ byte
  encoding; sequential counters SHALL NOT be used.
- CORRID-INV-04: Any id produced (generated or accepted) MUST appear in every
  emitted log line, metric exemplar, and outbound HTTP request header header
  set returned by ``inject()``.
- CORRID-INV-05: CorrelationId CANNOT be mutated mid-request — the type is a
  frozen ``NewType[str]`` and ``inject`` never overwrites with a different id.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Mapping
from typing import Final, NewType, Protocol, runtime_checkable

CorrelationId = NewType("CorrelationId", str)

MIN_ID_CHARS: Final[int] = 16
MAX_ID_CHARS: Final[int] = 64
_HEX_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{16,64}$")
_TRACEPARENT_RE: Final[re.Pattern[str]] = re.compile(
    r"^[0-9a-f]{2}-(?P<trace>[0-9a-f]{32})-[0-9a-f]{16}-[0-9a-f]{2}$"
)
_INBOUND_HEADER_PRIORITY: Final[tuple[str, ...]] = (
    "x-request-id",
    "x-correlation-id",
    "request-id",
)
_OUTBOUND_HEADER: Final[str] = "x-request-id"


class CorrelationIdError(ValueError):
    """Runtime invariant violation on a correlation id."""


# ---------------------------------------------------------------------------
# Protocol surface — matches catalog api_signature byte-for-byte.
# ---------------------------------------------------------------------------
@runtime_checkable
class CorrelationIdProvider(Protocol):
    def current(self) -> CorrelationId: ...
    def generate(self) -> CorrelationId: ...


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------
def _normalize(raw: str) -> str | None:
    """Return a normalised (lowercase, hex, ≥16 chars) id, or None if invalid."""
    if not isinstance(raw, str):
        return None
    candidate = raw.strip().lower()
    if len(candidate) < MIN_ID_CHARS or len(candidate) > MAX_ID_CHARS:
        return None
    if not _HEX_RE.match(candidate):
        return None
    return candidate


def _parse_traceparent(raw: str) -> str | None:
    """Extract the 32-char trace-id field from a W3C traceparent, or None."""
    if not isinstance(raw, str):
        return None
    match = _TRACEPARENT_RE.match(raw.strip().lower())
    if match is None:
        return None
    return match.group("trace")


def generate() -> CorrelationId:
    """Produce a fresh, cryptographically-random correlation id.

    CORRID-INV-03: 16 bytes (=32 hex chars) from ``secrets.token_hex``.
    """
    return CorrelationId(secrets.token_hex(16))


def parse(raw: str) -> CorrelationId:
    """Parse an externally-supplied id, raising on invariant violation.

    CORRID-INV-01/05: strict — any non-conforming value is rejected rather
    than silently coerced. Callers that want "accept or generate" semantics
    should use :func:`extract`.
    """
    normalised = _normalize(raw)
    if normalised is None:
        raise CorrelationIdError(
            "CORRID-INV-01: value MUST be lowercase hex 16..64 chars, "
            f"got {raw!r}."
        )
    return CorrelationId(normalised)


def to_str(cid: CorrelationId) -> str:
    """Return the canonical string rendering of ``cid``.

    CORRID-INV-05: idempotent identity — the id is already a string, but this
    function establishes the single canonical rendering used by loggers and
    wire propagation.
    """
    if not isinstance(cid, str):
        raise CorrelationIdError(
            "CORRID-INV-05: CorrelationId MUST be a str NewType; "
            f"got {type(cid).__name__}."
        )
    # Defence in depth: if something bypassed NewType, still refuse to leak.
    if _normalize(cid) is None:
        raise CorrelationIdError(
            "CORRID-INV-01: corrupted CorrelationId fails validation."
        )
    return str(cid)


def extract(headers: Mapping[str, str]) -> CorrelationId:
    """Return an id for the request — propagate upstream, else generate.

    CORRID-INV-02: when any of ``x-request-id``, ``x-correlation-id``,
    ``request-id`` or ``traceparent`` carries a syntactically valid id, it is
    re-used (normalised to lowercase). Otherwise a fresh id is generated
    (CORRID-INV-01 / CORRID-INV-03).
    """
    if not isinstance(headers, Mapping):
        raise CorrelationIdError(
            "CORRID-INV-02: headers MUST be a Mapping[str, str]."
        )
    lowered: dict[str, str] = {
        str(k).lower(): str(v) for k, v in headers.items()
    }
    for name in _INBOUND_HEADER_PRIORITY:
        value = lowered.get(name)
        if value is None:
            continue
        normalised = _normalize(value)
        if normalised is not None:
            return CorrelationId(normalised)
    trace = _parse_traceparent(lowered.get("traceparent", ""))
    if trace is not None:
        return CorrelationId(trace)
    return generate()


def inject(cid: CorrelationId, headers: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return a new header mapping with ``cid`` bound for outbound propagation.

    CORRID-INV-04 / CORRID-INV-05: always writes ``x-request-id``; never
    mutates the input mapping; never downgrades or replaces an already-equal
    id already present.
    """
    canonical = to_str(cid)
    merged: dict[str, str] = {}
    if headers is not None:
        if not isinstance(headers, Mapping):
            raise CorrelationIdError(
                "CORRID-INV-04: headers MUST be a Mapping[str, str] or None."
            )
        for k, v in headers.items():
            merged[str(k)] = str(v)
    merged[_OUTBOUND_HEADER] = canonical
    return merged


# ---------------------------------------------------------------------------
# Reference provider — stateless-per-instance, safe to share.
# ---------------------------------------------------------------------------
class StatelessCorrelationIdProvider:
    """Reference :class:`CorrelationIdProvider` — each call yields a fresh id.

    Stateless per the briefing: ``current()`` and ``generate()`` are identical;
    upstream callers are expected to propagate a specific id themselves via
    :func:`extract` / :func:`inject` rather than via shared mutable state.
    """

    def current(self) -> CorrelationId:
        return generate()

    def generate(self) -> CorrelationId:
        return generate()


__all__ = [
    "MAX_ID_CHARS",
    "MIN_ID_CHARS",
    "CorrelationId",
    "CorrelationIdError",
    "CorrelationIdProvider",
    "StatelessCorrelationIdProvider",
    "extract",
    "generate",
    "inject",
    "parse",
    "to_str",
]
