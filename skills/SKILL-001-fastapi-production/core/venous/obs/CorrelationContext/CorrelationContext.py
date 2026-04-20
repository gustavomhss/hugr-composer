"""CorrelationContext primitive — request-scoped baggage + stable request_id.

Invariant IDs:

- CORR-INV-01: request_id MUST be lowercase hex or ULID of ≥ 16 chars, stable
  for the request lifecycle.
- CORR-INV-02: baggage values MUST be ASCII and CANNOT exceed 8192 bytes.
- CORR-INV-03: activate() MUST restore the prior context on exit even on exception.
- CORR-INV-04: invalid traceparent SHALL cause a new trace id to be generated and
  NEVER falls back to empty trace context.
- CORR-INV-05: baggage keys reserved for authentication (password, authorization,
  cookie) are FORBIDDEN and SHALL be stripped.
- CORR-INV-06: context NEVER leaks across event loops; asynchronous spawns
  copy-on-capture via contextvars.
"""

from __future__ import annotations

import contextvars
import re
import secrets
from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from typing import Final, Protocol, runtime_checkable

FORBIDDEN_BAGGAGE_KEYS: Final[frozenset[str]] = frozenset(
    {"password", "authorization", "cookie", "set-cookie", "proxy-authorization"}
)
MAX_BAGGAGE_VALUE_BYTES: Final[int] = 8192
# CORR-INV-01: accept EITHER a lowercase-hex id (common) OR a Crockford
# base32 ULID (26 chars, `[0-9A-HJKMNP-TV-Z]`). Both are fixed-width,
# sortable, and URL-safe. Case is normalized to lower on return.
REQUEST_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:[0-9a-fA-F]{16,64}|[0-9A-HJKMNP-TV-Za-hjkmnp-tv-z]{26})$"
)
TRACEPARENT_RE: Final[re.Pattern[str]] = re.compile(
    r"^[0-9a-f]{2}-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$"
)


class CorrelationInvariantError(ValueError):
    """Runtime invariant violation on a correlation context."""


# ---------------------------------------------------------------------------
# Protocol surface
# ---------------------------------------------------------------------------
@runtime_checkable
class CorrelationContext(Protocol):
    @property
    def request_id(self) -> str: ...

    @property
    def trace_id(self) -> str | None: ...

    def baggage(self) -> Mapping[str, str]: ...
    def activate(self) -> AbstractContextManager[None]: ...

    @classmethod
    def current(cls) -> CorrelationContext: ...

    @classmethod
    def from_headers(cls, headers: Mapping[str, str]) -> CorrelationContext: ...

    def to_headers(self) -> Mapping[str, str]: ...


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def validate_request_id(rid: str) -> str:
    if not isinstance(rid, str) or len(rid) < 16 or not REQUEST_ID_RE.match(rid):
        raise CorrelationInvariantError(
            f"CORR-INV-01: request_id MUST be lowercase hex >=16 chars OR "
            f"a 26-char Crockford base32 ULID; got {rid!r}."
        )
    return rid.lower()


def _validate_baggage_entry(key: str, value: str) -> None:
    if key.lower() in FORBIDDEN_BAGGAGE_KEYS:
        raise CorrelationInvariantError(
            f"CORR-INV-05: baggage key {key!r} is FORBIDDEN (authentication reserved)."
        )
    if not isinstance(value, str):
        raise CorrelationInvariantError("CORR-INV-02: baggage value MUST be str.")
    if not value.isascii():
        raise CorrelationInvariantError("CORR-INV-02: baggage value MUST be ASCII.")
    if len(value.encode("ascii")) > MAX_BAGGAGE_VALUE_BYTES:
        raise CorrelationInvariantError(
            f"CORR-INV-02: baggage value CANNOT exceed {MAX_BAGGAGE_VALUE_BYTES} bytes."
        )


def _gen_request_id() -> str:
    return secrets.token_hex(16)


def _gen_trace_id() -> str:
    return secrets.token_hex(16)


# ---------------------------------------------------------------------------
# Reference implementation
# ---------------------------------------------------------------------------
_CURRENT: contextvars.ContextVar[InMemoryCorrelationContext | None] = (
    contextvars.ContextVar("correlation_context", default=None)
)


class InMemoryCorrelationContext:
    """Reference CorrelationContext — contextvars-based, immutable baggage snapshot."""

    def __init__(
        self,
        *,
        request_id: str | None = None,
        trace_id: str | None = None,
        baggage: Mapping[str, str] | None = None,
    ) -> None:
        self._request_id: str = validate_request_id(request_id or _gen_request_id())
        self._trace_id: str | None = trace_id
        clean: dict[str, str] = {}
        for k, v in (baggage or {}).items():
            # CORR-INV-05: strip forbidden keys on ingest.
            if k.lower() in FORBIDDEN_BAGGAGE_KEYS:
                continue
            _validate_baggage_entry(k, v)
            clean[k] = v
        self._baggage: dict[str, str] = clean

    @property
    def request_id(self) -> str:
        return self._request_id

    @property
    def trace_id(self) -> str | None:
        return self._trace_id

    def baggage(self) -> Mapping[str, str]:
        return dict(self._baggage)

    @contextmanager
    def activate(self) -> Iterator[None]:
        """CORR-INV-03: restore prior context on exit, even under exception."""
        token = _CURRENT.set(self)
        try:
            yield
        finally:
            _CURRENT.reset(token)

    @classmethod
    def current(cls) -> InMemoryCorrelationContext:
        ctx = _CURRENT.get()
        if ctx is None:
            # Create a detached default context so calls never crash.
            return cls()
        return ctx

    @classmethod
    def from_headers(cls, headers: Mapping[str, str]) -> InMemoryCorrelationContext:
        tp = headers.get("traceparent", "")
        if tp and TRACEPARENT_RE.match(tp):
            trace_id = tp.split("-")[1]
        else:
            # CORR-INV-04: invalid → generate a fresh trace_id; NEVER return empty.
            trace_id = _gen_trace_id()
        request_id = headers.get("x-request-id", "") or _gen_request_id()
        try:
            request_id = validate_request_id(request_id)
        except CorrelationInvariantError:
            request_id = _gen_request_id()

        baggage_header = headers.get("baggage", "")
        baggage: dict[str, str] = {}
        if baggage_header:
            for entry in baggage_header.split(","):
                if "=" in entry:
                    k, _, v = entry.partition("=")
                    k = k.strip()
                    v = v.strip()
                    if not k or k.lower() in FORBIDDEN_BAGGAGE_KEYS:
                        continue
                    try:
                        _validate_baggage_entry(k, v)
                        baggage[k] = v
                    except CorrelationInvariantError:
                        continue

        return cls(request_id=request_id, trace_id=trace_id, baggage=baggage)

    def to_headers(self) -> Mapping[str, str]:
        headers: dict[str, str] = {"x-request-id": self._request_id}
        if self._trace_id:
            headers["traceparent"] = f"00-{self._trace_id}-{_gen_trace_id()[:16]}-01"
        if self._baggage:
            headers["baggage"] = ",".join(f"{k}={v}" for k, v in self._baggage.items())
        return headers


__all__ = [
    "FORBIDDEN_BAGGAGE_KEYS",
    "MAX_BAGGAGE_VALUE_BYTES",
    "REQUEST_ID_RE",
    "TRACEPARENT_RE",
    "CorrelationContext",
    "CorrelationInvariantError",
    "InMemoryCorrelationContext",
    "validate_request_id",
]
