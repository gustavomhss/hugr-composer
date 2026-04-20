"""RpcInterceptor primitive — gRPC-style per-call middleware contract.

Implements the catalog Protocol for `extras.RpcInterceptor` and installs runtime
invariant checkers. The module performs zero I/O at import.

Invariant IDs cited by this module:

- RPCI-INV-01: interceptors MUST call `next` exactly once per invocation unless
  they deliberately short-circuit with a status.
- RPCI-INV-02: metadata keys ending with `-bin` ALWAYS carry binary values and
  CANNOT be compared as plain strings.
- RPCI-INV-03: keys starting with `grpc-` are FORBIDDEN for user metadata
  because that prefix is reserved by the runtime.
- RPCI-INV-04: a deadline propagated in ctx MUST NOT be extended by an
  interceptor; it SHALL only be shortened or respected.
- RPCI-INV-05: cancellation signals NEVER cross interceptor boundaries
  silently; every interceptor SHALL honor cancel or raise a cancellation error.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Final, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
RESERVED_METADATA_PREFIX: Final[str] = "grpc-"
BINARY_METADATA_SUFFIX: Final[str] = "-bin"


# ---------------------------------------------------------------------------
# Exception taxonomy
# ---------------------------------------------------------------------------
class RpcInterceptorError(ValueError):
    """Raised when a call violates an RpcInterceptor invariant."""


class RpcCancelledError(RuntimeError):
    """Raised when the RPC is cancelled and the interceptor honors the signal (RPCI-INV-05)."""


# ---------------------------------------------------------------------------
# Context dataclass (mirrors the catalog api_signature)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RpcContext:
    method: str
    deadline_ms: int | None
    metadata: Mapping[str, object] = field(default_factory=dict)


Handler = Callable[[RpcContext, bytes], Awaitable[bytes]]


@runtime_checkable
class RpcInterceptor(Protocol):
    async def intercept(self, ctx: RpcContext, payload: bytes, next: Handler) -> bytes: ...  # noqa: A002 — `next` matches catalog signature (RPCI-INV-01).


# ---------------------------------------------------------------------------
# Runtime invariant enforcers
# ---------------------------------------------------------------------------
def validate_metadata(metadata: Mapping[str, object]) -> None:
    """RPCI-INV-02 / RPCI-INV-03: validate user metadata keys and -bin values."""
    for k, v in metadata.items():
        if not isinstance(k, str) or not k:
            raise RpcInterceptorError(
                "RPCI-INV-02 supporting: metadata keys MUST be non-empty strings."
            )
        key = k.lower()
        if key.startswith(RESERVED_METADATA_PREFIX):
            raise RpcInterceptorError(
                f"RPCI-INV-03: user metadata key {k!r} uses reserved 'grpc-' prefix; FORBIDDEN."
            )
        if key.endswith(BINARY_METADATA_SUFFIX):
            if not isinstance(v, (bytes, bytearray, memoryview)):
                raise RpcInterceptorError(
                    f"RPCI-INV-02: metadata key {k!r} ends with '-bin'; value MUST be bytes, got {type(v).__name__}."
                )
        elif not isinstance(v, str):
            raise RpcInterceptorError(
                f"RPCI-INV-02: non-bin metadata key {k!r} MUST carry a str value, got {type(v).__name__}."
            )


def validate_deadline(old_ms: int | None, new_ms: int | None) -> None:
    """RPCI-INV-04: deadline SHALL only be shortened or respected."""
    if old_ms is None:
        return
    if new_ms is None:
        raise RpcInterceptorError(
            "RPCI-INV-04: deadline MUST NOT be dropped; interceptors can only shorten or respect it."
        )
    if new_ms > old_ms:
        raise RpcInterceptorError(
            f"RPCI-INV-04: deadline CANNOT be extended (old={old_ms}ms, attempted={new_ms}ms)."
        )


def shorten_deadline(ctx: RpcContext, new_deadline_ms: int) -> RpcContext:
    """Return a new RpcContext with a shorter (or equal) deadline. Raises on extension."""
    validate_deadline(ctx.deadline_ms, new_deadline_ms)
    return RpcContext(method=ctx.method, deadline_ms=new_deadline_ms, metadata=dict(ctx.metadata))


# ---------------------------------------------------------------------------
# Reference interceptor implementations
# ---------------------------------------------------------------------------
class CountingInterceptor:
    """Reference interceptor: counts `next` invocations and short-circuits.

    Demonstrates RPCI-INV-01: `next` is called AT MOST once per intercept call.
    The `short_circuit_on` keyword lets tests exercise the short-circuit path
    without violating the invariant.
    """

    def __init__(self, *, short_circuit_on: str | None = None, short_circuit_payload: bytes = b"") -> None:
        self.next_calls: int = 0
        self.intercept_calls: int = 0
        self._short_method = short_circuit_on
        self._short_payload = short_circuit_payload

    async def intercept(self, ctx: RpcContext, payload: bytes, next: Handler) -> bytes:  # noqa: A002 — catalog signature
        self.intercept_calls += 1
        validate_metadata(ctx.metadata)
        if self._short_method is not None and ctx.method == self._short_method:
            return self._short_payload
        self.next_calls += 1
        return await next(ctx, payload)


class DeadlineEnforcingInterceptor:
    """Reference interceptor: can shorten but never extend the deadline."""

    def __init__(self, *, shorten_by_ms: int = 0) -> None:
        self._shorten_by = shorten_by_ms

    async def intercept(self, ctx: RpcContext, payload: bytes, next: Handler) -> bytes:  # noqa: A002 — catalog signature
        if ctx.deadline_ms is None:
            return await next(ctx, payload)
        shortened = max(0, ctx.deadline_ms - self._shorten_by)
        new_ctx = shorten_deadline(ctx, shortened)
        return await next(new_ctx, payload)


class CancellationAwareInterceptor:
    """Reference interceptor: propagates cancellation explicitly (RPCI-INV-05)."""

    def __init__(self, *, cancelled: bool = False) -> None:
        self._cancelled = cancelled

    async def intercept(self, ctx: RpcContext, payload: bytes, next: Handler) -> bytes:  # noqa: A002 — catalog signature
        if self._cancelled:
            raise RpcCancelledError(f"RPCI-INV-05: call {ctx.method!r} cancelled before handler.")
        # RPCI-INV-05: any RpcCancelledError raised by downstream SHALL propagate, never be swallowed.
        return await next(ctx, payload)


# ---------------------------------------------------------------------------
# Composition helper — ordered interceptor chain
# ---------------------------------------------------------------------------
def compose(interceptors: list[RpcInterceptor], terminal: Handler) -> Handler:
    """Compose an ordered chain so earlier entries wrap later ones.

    RPCI-INV-01: each interceptor's `intercept` receives a `next` that calls
    exactly the subsequent interceptor (or the terminal handler).
    """
    chain: Handler = terminal
    for interceptor in reversed(interceptors):
        chain = _wrap(interceptor, chain)
    return chain


def _wrap(interceptor: RpcInterceptor, nxt: Handler) -> Handler:
    async def call(ctx: RpcContext, payload: bytes) -> bytes:
        outer_deadline = ctx.deadline_ms

        async def guarded_nxt(inner_ctx: RpcContext, inner_payload: bytes) -> bytes:
            # RPCI-INV-04: deadline MUST be monotonically non-increasing
            # across the chain. An interceptor that constructs a fresh
            # RpcContext with a larger deadline (or removes a previous
            # deadline) would otherwise smuggle extra time to the terminal
            # handler. Enforce at the wrap boundary so the invariant holds
            # regardless of interceptor implementation discipline.
            inner_deadline = inner_ctx.deadline_ms
            if outer_deadline is not None:
                if inner_deadline is None or inner_deadline > outer_deadline:
                    raise RpcInterceptorError(
                        f"RPCI-INV-04: deadline extension blocked — from {outer_deadline} to "
                        f"{'unbounded' if inner_deadline is None else inner_deadline}; "
                        f"deadlines MUST only shrink across the chain."
                    )
            return await nxt(inner_ctx, inner_payload)

        return await interceptor.intercept(ctx, payload, guarded_nxt)
    return call


__all__ = [
    "BINARY_METADATA_SUFFIX",
    "RESERVED_METADATA_PREFIX",
    "CancellationAwareInterceptor",
    "CountingInterceptor",
    "DeadlineEnforcingInterceptor",
    "Handler",
    "RpcCancelledError",
    "RpcContext",
    "RpcInterceptor",
    "RpcInterceptorError",
    "compose",
    "shorten_deadline",
    "validate_deadline",
    "validate_metadata",
]
