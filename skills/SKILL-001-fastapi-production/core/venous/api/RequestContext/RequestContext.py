"""RequestContext primitive — per-request bag of known-shape identity, headers, assigns.

Implements the catalog shape for `api.RequestContext` and installs runtime
invariant checkers. The module performs zero I/O at import.

Invariant IDs cited by this module:

- RC-INV-01: a RequestContext MUST be constructed once per inbound request and
  disposed when the response is sent; `dispose()` makes the context inert so a
  late write raises and never mutates live state.
- RC-INV-02: a RequestContext NEVER leaks across request boundaries; a
  background task CANNOT reuse a parent context as live state — it gets a
  `detached_snapshot()` that is frozen and inert.
- RC-INV-03: `put()` MUST be idempotent for the same (key, value); overwriting
  an existing key with a different value REQUIRES `overwrite=True` or raises.
- RC-INV-04: `halt()` MUST cause subsequent middleware to skip (observable via
  `is_halted`), but SHALL NOT abort already-queued response bytes — the
  primitive never touches bytes; it only carries the flag.
- RC-INV-05: `request_id` MUST be populated before the first user code runs; a
  missing / blank / control-char id is replaced with a fresh UUIDv4.
"""

from __future__ import annotations

import unicodedata
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from threading import Lock
from types import MappingProxyType
from typing import Any, Final, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
REDACTED: Final[str] = "[REDACTED]"

# Assign keys whose VALUES MUST be redacted in log serialisation. Matched
# case-insensitively so callers cannot bypass via casing.
SENSITIVE_ASSIGN_KEYS: Final[frozenset[str]] = frozenset({
    "password",
    "pwd",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "id_token",
    "authorization",
    "cookie",
    "set-cookie",
    "api_key",
    "apikey",
    "x-api-key",
    "client_secret",
    "private_key",
})

_FORBIDDEN_ID_CHARS: Final[frozenset[str]] = frozenset({"\x00", "\r", "\n", "\t"})

_SENTINEL: Final[object] = object()


# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------
class RequestContextError(ValueError):
    """Raised when a construction or operation violates a RequestContext invariant."""


# ---------------------------------------------------------------------------
# Protocol — catalog extension contract
# ---------------------------------------------------------------------------
@runtime_checkable
class RequestContext(Protocol):
    """The catalog-declared request-context surface.

    Concrete implementations below (`MutableRequestContext`, `FrozenRequestContext`)
    satisfy this Protocol. Downstream code depends on the Protocol so alternative
    implementations (e.g. a Starlette-backed view) remain swap-in.
    """

    request_id: str
    principal: object | None
    headers: Mapping[str, str]
    assigns: dict[str, Any]

    def put(self, key: str, value: Any) -> RequestContext: ...

    def halt(self) -> RequestContext: ...


# ---------------------------------------------------------------------------
# Runtime validators
# ---------------------------------------------------------------------------
def _sanitise_request_id(candidate: str | None) -> str:
    """RC-INV-05: a missing / blank / control-char id is replaced with UUIDv4."""
    if candidate is None:
        return str(uuid.uuid4())
    if not isinstance(candidate, str):
        raise RequestContextError(
            "RC-INV-05: request_id MUST be str or None, "
            f"got {type(candidate).__name__}."
        )
    stripped = candidate.strip()
    if stripped == "":
        return str(uuid.uuid4())
    for ch in stripped:
        if ch in _FORBIDDEN_ID_CHARS or ord(ch) < 0x20 or 0x7F <= ord(ch) <= 0x9F:
            return str(uuid.uuid4())
        if unicodedata.category(ch) in {"Cf", "Cc", "Cs", "Co", "Cn"}:
            return str(uuid.uuid4())
    return stripped


def _validate_headers(headers: object) -> Mapping[str, str]:
    """Headers MUST be a Mapping[str,str]; stored as a read-only MappingProxy."""
    if not isinstance(headers, Mapping):
        raise RequestContextError(
            "RC-INV-01: headers MUST be a Mapping[str, str]; got "
            f"{type(headers).__name__}."
        )
    cleaned: dict[str, str] = {}
    for k, v in headers.items():
        if not isinstance(k, str) or k == "":
            raise RequestContextError(
                f"RC-INV-01: header keys MUST be non-empty str; got {k!r}."
            )
        if not isinstance(v, str):
            raise RequestContextError(
                "RC-INV-01: header values MUST be str (serialise upstream); "
                f"got {type(v).__name__} for {k!r}."
            )
        # Normalise to lower-case per HTTP/2 semantics.
        cleaned[k.lower()] = v
    return MappingProxyType(cleaned)


def _validate_key(key: object) -> str:
    if not isinstance(key, str) or key == "":
        raise RequestContextError(
            f"RC-INV-03: assign keys MUST be non-empty str; got {key!r}."
        )
    if key.strip() != key:
        raise RequestContextError(
            f"RC-INV-03: assign keys MUST NOT be whitespace-padded; got {key!r}."
        )
    return key


# ---------------------------------------------------------------------------
# The primitive — mutable DURING the request, frozen on dispose
# ---------------------------------------------------------------------------
class MutableRequestContext:
    """Reference implementation of the catalog `RequestContext` Protocol.

    Lifecycle:
        1. Constructed by the middleware entry (`request_scope(...)`) at the
           earliest point — before any user code runs.
        2. Middleware/handlers call `put()` / read `assigns` as the request
           threads through the stack.
        3. On response emission (or abort), the framework calls `dispose()`
           which freezes the context. Subsequent `put()` / `halt()` raise;
           reads still work so a late logger can emit a line.

    Mutability is deliberate: a request context is a carrier, not a value.
    Thread-safety is provided by a per-instance `Lock` because the same
    context MAY be touched by overlapping handlers in a threaded server.
    """

    __slots__ = (
        "__weakref__",
        "_disposed",
        "_halted",
        "_lock",
        "assigns",
        "headers",
        "principal",
        "request_id",
    )

    request_id: str
    principal: object | None
    headers: Mapping[str, str]
    assigns: dict[str, Any]

    def __init__(
        self,
        request_id: str | None,
        headers: Mapping[str, str] | None = None,
        *,
        principal: object | None = None,
        assigns: Mapping[str, Any] | None = None,
    ) -> None:
        self.request_id = _sanitise_request_id(request_id)
        self.headers = _validate_headers(headers or {})
        self.principal = principal
        # Defensive copy — a later mutation of the source cannot retroactively
        # rewrite the request's assigns surface.
        self.assigns = dict(assigns or {})
        self._halted: bool = False
        self._disposed: bool = False
        self._lock: Lock = Lock()

    # ---- state flags ----------------------------------------------------
    @property
    def is_halted(self) -> bool:
        return self._halted

    @property
    def is_disposed(self) -> bool:
        return self._disposed

    # ---- Protocol methods ----------------------------------------------
    def put(self, key: str, value: Any, *, overwrite: bool = False) -> RequestContext:
        """Set `assigns[key] = value` under the RC-INV-03 idempotency rule.

        Returns `self` so middleware can chain (`ctx.put(...).put(...)`).
        """
        validated_key = _validate_key(key)
        with self._lock:
            if self._disposed:
                raise RequestContextError(
                    "RC-INV-01: cannot put() on a disposed RequestContext "
                    f"(request_id={self.request_id!r})."
                )
            existing = self.assigns.get(validated_key, _SENTINEL)
            if existing is _SENTINEL:
                self.assigns[validated_key] = value
                return self
            if existing == value:
                # Idempotent re-put — no change, no error.
                return self
            if not overwrite:
                raise RequestContextError(
                    "RC-INV-03: put() for key "
                    f"{validated_key!r} would overwrite an existing value; "
                    "pass overwrite=True to make the intent explicit."
                )
            self.assigns[validated_key] = value
            return self

    def halt(self) -> RequestContext:
        """Mark the context halted — subsequent middleware MUST skip.

        Halting does NOT abort already-queued response bytes (RC-INV-04); the
        primitive carries a flag, it does not touch I/O.
        """
        with self._lock:
            if self._disposed:
                raise RequestContextError(
                    "RC-INV-01: cannot halt() on a disposed RequestContext "
                    f"(request_id={self.request_id!r})."
                )
            self._halted = True
        return self

    # ---- lifecycle ------------------------------------------------------
    def dispose(self) -> None:
        """Freeze the context — RC-INV-01 end-of-life.

        Idempotent: calling `dispose()` twice is safe. After dispose, `put()`
        and `halt()` raise; reads still succeed so a late logger can emit a
        line.
        """
        with self._lock:
            if self._disposed:
                return
            self._disposed = True

    def detached_snapshot(self) -> FrozenRequestContext:
        """RC-INV-02: produce a frozen, background-safe view of this context.

        A background task MUST NOT receive the live RequestContext — passing
        the live object risks use-after-dispose and cross-request leaks. The
        returned snapshot has the same `request_id`, `principal`, `headers`,
        and a frozen copy of `assigns`; `put()` and `halt()` raise.
        """
        with self._lock:
            return FrozenRequestContext(
                request_id=self.request_id,
                principal=self.principal,
                headers=self.headers,  # already a proxy
                assigns_snapshot=dict(self.assigns),
                halted=self._halted,
            )

    # ---- logging --------------------------------------------------------
    def for_log(self) -> dict[str, object]:
        """Emit a log-safe dict; sensitive assigns are redacted by key policy."""
        redacted_assigns: dict[str, object] = {}
        for k, v in self.assigns.items():
            if k.lower() in SENSITIVE_ASSIGN_KEYS:
                redacted_assigns[k] = REDACTED
            else:
                redacted_assigns[k] = v
        return {
            "request_id": self.request_id,
            "has_principal": self.principal is not None,
            "header_keys": sorted(self.headers),
            "assign_keys": sorted(self.assigns),
            "is_halted": self._halted,
            "is_disposed": self._disposed,
            "assigns": redacted_assigns,
        }

    def __repr__(self) -> str:
        # Never leak assign values through repr — pair with for_log() for logs.
        return (
            f"MutableRequestContext(request_id={self.request_id!r}, "
            f"assign_keys={sorted(self.assigns)!r}, "
            f"is_halted={self._halted}, "
            f"is_disposed={self._disposed})"
        )


# ---------------------------------------------------------------------------
# FrozenRequestContext — background-task-safe snapshot
# ---------------------------------------------------------------------------
class FrozenRequestContext:
    """RC-INV-02 carrier: an inert, read-only snapshot of a RequestContext.

    Implements the `RequestContext` Protocol. `put()` and `halt()` raise
    because a background task MUST NOT mutate the originating request's live
    state; pass explicit values into your worker function instead.
    """

    __slots__ = ("_assigns_frozen", "_halted", "headers", "principal", "request_id")

    request_id: str
    principal: object | None
    headers: Mapping[str, str]

    def __init__(
        self,
        *,
        request_id: str,
        principal: object | None,
        headers: Mapping[str, str],
        assigns_snapshot: dict[str, Any],
        halted: bool,
    ) -> None:
        self.request_id = request_id
        self.principal = principal
        self.headers = headers
        # Hold the frozen view internally; .assigns returns a fresh copy so
        # external mutation is harmless (RC-INV-02).
        self._assigns_frozen: Mapping[str, Any] = MappingProxyType(assigns_snapshot)
        self._halted: bool = halted

    @property
    def assigns(self) -> dict[str, Any]:
        # Catalog surface demands `dict`; return a fresh dict copy each call
        # so external mutation does NOT feed back into the snapshot.
        return dict(self._assigns_frozen)

    @property
    def is_halted(self) -> bool:
        return self._halted

    @property
    def is_disposed(self) -> bool:
        return True  # a snapshot is, by definition, final.

    def put(self, key: str, value: Any) -> RequestContext:  # RC-INV-02: snapshot is inert; arg names honour the Protocol surface.
        del key, value  # RC-INV-02: arguments accepted for Protocol parity, discarded before raise.
        raise RequestContextError(
            "RC-INV-02: put() is forbidden on a detached snapshot; a "
            "background task MUST NOT mutate the originating request's "
            "live state."
        )

    def halt(self) -> RequestContext:
        raise RequestContextError(
            "RC-INV-02: halt() is forbidden on a detached snapshot."
        )

    def __repr__(self) -> str:
        return (
            f"FrozenRequestContext(request_id={self.request_id!r}, "
            f"halted={self._halted}, assign_keys={sorted(self._assigns_frozen)!r})"
        )


# ---------------------------------------------------------------------------
# Provider protocol + reference provider
# ---------------------------------------------------------------------------
@runtime_checkable
class RequestContextProvider(Protocol):
    """Extension point for framework adapters that build a RequestContext.

    A provider reads the inbound request envelope (headers, already-resolved
    principal, a correlation header if present) and returns a live
    `RequestContext` bound to that request.
    """

    def bind(
        self,
        *,
        request_id: str | None,
        headers: Mapping[str, str],
        principal: object | None,
    ) -> RequestContext: ...


class DefaultRequestContextProvider:
    """Reference provider — constructs a `MutableRequestContext` per bind call.

    Real adapters (Starlette, ASGI, plug-style) implement their own provider
    so they can attach the context to the framework's request state; the
    Protocol keeps them interoperable.
    """

    def bind(
        self,
        *,
        request_id: str | None = None,
        headers: Mapping[str, str] | None = None,
        principal: object | None = None,
    ) -> RequestContext:
        return MutableRequestContext(
            request_id=request_id,
            headers=headers or {},
            principal=principal,
        )


# ---------------------------------------------------------------------------
# Context manager — scoped lifecycle
# ---------------------------------------------------------------------------
@contextmanager
def request_scope(
    request_id: str | None = None,
    headers: Mapping[str, str] | None = None,
    *,
    principal: object | None = None,
) -> Iterator[MutableRequestContext]:
    """Build a RequestContext, yield it, guarantee disposal — RC-INV-01.

    Exceptions propagate; the context is disposed in `finally` so a crashing
    handler still surrenders the carrier.
    """
    ctx = MutableRequestContext(
        request_id=request_id,
        headers=headers or {},
        principal=principal,
    )
    try:
        yield ctx
    finally:
        ctx.dispose()


__all__ = [
    "REDACTED",
    "SENSITIVE_ASSIGN_KEYS",
    "DefaultRequestContextProvider",
    "FrozenRequestContext",
    "MutableRequestContext",
    "RequestContext",
    "RequestContextError",
    "RequestContextProvider",
    "request_scope",
]
