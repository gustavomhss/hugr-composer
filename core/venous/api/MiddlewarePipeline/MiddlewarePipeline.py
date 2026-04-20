"""MiddlewarePipeline primitive — ordered chain of request transformers.

Implements the catalog Protocol for `api.MiddlewarePipeline` and installs
runtime invariant checkers. The module performs zero I/O at import.

Invariant IDs cited by this module:

- MWP-INV-01: execution order MUST be the registration order; swap or insert
  operations SHALL be explicit, never implicit.
- MWP-INV-02: a middleware that does NOT await call_next MUST short-circuit
  the remainder of the pipeline.
- MWP-INV-03: each middleware CANNOT bypass downstream error handling:
  exceptions NEVER skip registered error filters.
- MWP-INV-04: registration MUST be frozen before run() is first called;
  adding middleware at request time SHALL raise.
- MWP-INV-05: MUST produce a response even if every middleware halts; an
  unhandled halt SHALL yield a 500 by contract.
"""

from __future__ import annotations

import threading
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Final, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Core type aliases (mirror catalog api_signature byte-for-byte)
# ---------------------------------------------------------------------------
Next = Callable[[], Awaitable[None]]
"""The `call_next` continuation passed to each middleware.

Awaiting it yields control to the next middleware in registration order.
NOT awaiting it short-circuits the remainder of the pipeline (MWP-INV-02).
"""


# ---------------------------------------------------------------------------
# RequestContext — the single mutable envelope threaded through the chain
# ---------------------------------------------------------------------------
DEFAULT_STATUS: Final[int] = 200
"""HTTP status assumed when no middleware sets ctx.status explicitly."""

FALLBACK_STATUS: Final[int] = 500
"""MWP-INV-05: status used when every middleware halted without writing one."""


@dataclass
class RequestContext:
    """Mutable envelope passed to every middleware.

    Carries request metadata, accumulated attributes, and the response slot.
    Fields map to the catalog RequestContext primitive surface (method,
    path, headers, attributes, status, body, response_written). The
    primitive itself owns an instance per `run()` call; the pipeline is
    re-entrant safe across concurrent requests because each run uses its
    own context.
    """

    method: str = "GET"
    path: str = "/"
    headers: Mapping[str, str] = field(default_factory=dict)
    attributes: dict[str, object] = field(default_factory=dict)
    status: int | None = None
    body: object = None
    response_written: bool = False
    # Halt metadata — set by the pipeline when a middleware returns without
    # awaiting call_next; inspected by MWP-INV-05 finalisation.
    halted_by: str | None = None
    # Error-filter chain walked by MWP-INV-03 when a middleware raises.
    error: BaseException | None = None

    def put(self, key: str, value: object) -> None:
        """Write a named attribute into the context's shared bag."""
        self.attributes[key] = value

    def get(self, key: str, default: object = None) -> object:
        """Read a named attribute; returns `default` when absent."""
        return self.attributes.get(key, default)

    def write_response(self, status: int, body: object = None) -> None:
        """Mark the response as written. Idempotent: second calls overwrite."""
        self.status = status
        self.body = body
        self.response_written = True


# ---------------------------------------------------------------------------
# Protocol surface (mirrors the catalog api_signature verbatim)
# ---------------------------------------------------------------------------
@runtime_checkable
class Middleware(Protocol):
    """A single stage in the pipeline.

    Receives the shared RequestContext and a `call_next` continuation. To
    pass control downstream, `await call_next()`. To short-circuit, return
    without awaiting (MWP-INV-02).
    """

    async def __call__(self, ctx: RequestContext, call_next: Next) -> None: ...


class MiddlewarePipeline(Protocol):
    """Protocol for the MiddlewarePipeline primitive; mirrors catalog api_signature."""

    def use(self, mw: Middleware) -> MiddlewarePipeline: ...
    async def run(self, ctx: RequestContext) -> None: ...


# ---------------------------------------------------------------------------
# Error filter — a specialised middleware-shape handler for MWP-INV-03
# ---------------------------------------------------------------------------
ErrorFilter = Callable[[RequestContext, BaseException], Awaitable[None]]
"""An error filter consumes a raised exception and writes a response.

MWP-INV-03: error filters are ALWAYS consulted when a middleware raises; the
exception can never silently skip them. A filter that chooses to re-raise
propagates the failure; a filter that writes a response resolves it.
"""


# ---------------------------------------------------------------------------
# Invariant enforcer
# ---------------------------------------------------------------------------
class MWPInvariantError(RuntimeError):
    """Raised when a runtime call violates a MiddlewarePipeline invariant."""


# ---------------------------------------------------------------------------
# Reference implementation
# ---------------------------------------------------------------------------
class InMemoryMiddlewarePipeline:
    """Reference MiddlewarePipeline.

    Thread-safe construction; once the first `run()` completes the middleware
    list is frozen (MWP-INV-04). Re-entrant across concurrent requests: each
    `run` walks the frozen tuple, so no shared mutable state is touched on
    the request path. The primitive itself is stateless by design — the
    ordered chain is configuration, not runtime state.
    """

    def __init__(self) -> None:
        self._middlewares: list[tuple[str, Middleware]] = []
        self._error_filters: list[ErrorFilter] = []
        self._frozen: bool = False
        self._lock = threading.Lock()

    # ----- registration ---------------------------------------------------
    def use(self, mw: Middleware, *, name: str | None = None) -> InMemoryMiddlewarePipeline:
        """Append a middleware to the end of the chain.

        MWP-INV-01: appends preserve registration order.
        MWP-INV-04: rejects registration after first `run()` call.
        """
        self._ensure_unfrozen("use")
        with self._lock:
            resolved_name = name or _middleware_name(mw, len(self._middlewares))
            if any(existing_name == resolved_name for existing_name, _ in self._middlewares):
                raise MWPInvariantError(
                    f"MWP-INV-01: middleware name {resolved_name!r} is already registered; "
                    "names MUST be unique so insert/swap operations can be explicit.",
                )
            self._middlewares.append((resolved_name, mw))
        return self

    def use_error_filter(self, flt: ErrorFilter) -> InMemoryMiddlewarePipeline:
        """Register an error filter. MWP-INV-03: consulted on any raised exception."""
        self._ensure_unfrozen("use_error_filter")
        with self._lock:
            self._error_filters.append(flt)
        return self

    def insert_before(self, anchor: str, mw: Middleware, *, name: str) -> InMemoryMiddlewarePipeline:
        """Explicit insert before the named anchor. MWP-INV-01: never implicit."""
        self._ensure_unfrozen("insert_before")
        with self._lock:
            # MWP-INV-01: enforce uniqueness — mirrors `use()` so the insert paths
            # cannot silently shadow an existing entry.
            if any(existing == name for existing, _ in self._middlewares):
                raise MWPInvariantError(
                    f"MWP-INV-01: middleware name {name!r} already registered.",
                )
            idx = self._index_of(anchor)
            self._middlewares.insert(idx, (name, mw))
        return self

    def insert_after(self, anchor: str, mw: Middleware, *, name: str) -> InMemoryMiddlewarePipeline:
        """Explicit insert after the named anchor. MWP-INV-01: never implicit."""
        self._ensure_unfrozen("insert_after")
        with self._lock:
            # MWP-INV-01: same uniqueness guard as use()/insert_before.
            if any(existing == name for existing, _ in self._middlewares):
                raise MWPInvariantError(
                    f"MWP-INV-01: middleware name {name!r} already registered.",
                )
            idx = self._index_of(anchor) + 1
            self._middlewares.insert(idx, (name, mw))
        return self

    def remove(self, name: str) -> InMemoryMiddlewarePipeline:
        """Remove a middleware by name. MWP-INV-01: explicit mutation only."""
        self._ensure_unfrozen("remove")
        with self._lock:
            idx = self._index_of(name)
            del self._middlewares[idx]
        return self

    def swap(self, a: str, b: str) -> InMemoryMiddlewarePipeline:
        """Swap two middlewares by name. MWP-INV-01: explicit ordering change."""
        self._ensure_unfrozen("swap")
        with self._lock:
            ia = self._index_of(a)
            ib = self._index_of(b)
            self._middlewares[ia], self._middlewares[ib] = (
                self._middlewares[ib],
                self._middlewares[ia],
            )
        return self

    # ----- lifecycle ------------------------------------------------------
    def freeze(self) -> None:
        """Idempotent freeze; called implicitly on first `run()`."""
        with self._lock:
            self._frozen = True

    @property
    def frozen(self) -> bool:
        return self._frozen

    @property
    def names(self) -> tuple[str, ...]:
        """Names in registration order. MWP-INV-01: observable ordering."""
        with self._lock:
            return tuple(n for n, _ in self._middlewares)

    def _ensure_unfrozen(self, op: str) -> None:
        # Read under lock so concurrent `run()` cannot race past the check.
        with self._lock:
            frozen = self._frozen
        if frozen:
            raise MWPInvariantError(
                f"MWP-INV-04: pipeline is frozen after first run(); "
                f"operation {op!r} is FORBIDDEN at request time.",
            )

    def _index_of(self, name: str) -> int:
        for i, (n, _) in enumerate(self._middlewares):
            if n == name:
                return i
        raise MWPInvariantError(
            f"MWP-INV-01 supporting: no middleware named {name!r} is registered.",
        )

    # ----- execution ------------------------------------------------------
    async def run(self, ctx: RequestContext) -> None:
        """Drive the ordered chain on the supplied context.

        Enforces:
          * MWP-INV-01 by walking a frozen snapshot in registration order;
          * MWP-INV-02 by tracking `awaited_next` per stage and recording the
            halt origin on the context;
          * MWP-INV-03 by routing every raised exception through every error
            filter before propagation;
          * MWP-INV-04 by freezing on first invocation;
          * MWP-INV-05 by writing a 500 response if no middleware wrote one.
        """
        # Freeze on first run — MWP-INV-04.
        self.freeze()
        with self._lock:
            chain = tuple(self._middlewares)
            filters = tuple(self._error_filters)

        try:
            await _walk(chain, 0, ctx)
        except Exception as exc:  # MWP-INV-03: every raise routes through filters before propagating.
            ctx.error = exc
            await _run_error_filters(filters, ctx, exc)
            if not ctx.response_written:
                # MWP-INV-03 + MWP-INV-05: no filter resolved; re-raise with a
                # 500 stamped on the context so upstream adapters see both.
                ctx.status = FALLBACK_STATUS
                ctx.body = {"error": type(exc).__name__, "message": str(exc)}
                ctx.response_written = True
                raise

        # MWP-INV-05: produce a response even when every middleware halted OR
        # when the chain drained without writing one. 500 is the contract for
        # either "unhandled halt" or "no middleware produced a response".
        if not ctx.response_written:
            ctx.status = FALLBACK_STATUS
            ctx.body = {
                "error": "UnhandledHalt" if ctx.halted_by else "NoResponse",
                "halted_by": ctx.halted_by,
                "message": "pipeline produced no response (MWP-INV-05).",
            }
            ctx.response_written = True


async def _walk(
    chain: tuple[tuple[str, Middleware], ...],
    index: int,
    ctx: RequestContext,
) -> None:
    """Recursive chain walk; single stack frame per middleware."""
    if index >= len(chain):
        return
    name, mw = chain[index]
    awaited_next = False

    async def call_next() -> None:
        nonlocal awaited_next
        awaited_next = True
        await _walk(chain, index + 1, ctx)

    await mw(ctx, call_next)
    # MWP-INV-02: a middleware that declines call_next short-circuits the rest.
    # Only record as a halt when there was actually a "rest" to skip; the
    # tail middleware naturally omits call_next and that is not a halt.
    has_downstream = index + 1 < len(chain)
    if not awaited_next and has_downstream and ctx.halted_by is None:
        ctx.halted_by = name


async def _run_error_filters(
    filters: tuple[ErrorFilter, ...],
    ctx: RequestContext,
    exc: BaseException,
) -> None:
    """MWP-INV-03: walk every registered filter in registration order.

    A filter that writes a response resolves the error; subsequent filters
    still run (they may observe the resolution but MUST NOT clear it). A
    filter that raises is caught and recorded; the chain continues so a
    later filter can still recover.
    """
    for flt in filters:
        try:
            await flt(ctx, exc)
        except Exception as inner:  # noqa: BLE001, PERF203 — MWP-INV-03: every filter MUST run even when a predecessor raised; filter failures MUST NOT mask the original exception. The per-iteration try/except is the contract, not an accident.
            bucket = ctx.attributes.get("mwp.filter_errors")
            if not isinstance(bucket, list):
                bucket = []
                ctx.attributes["mwp.filter_errors"] = bucket
            bucket.append(inner)


def _middleware_name(mw: Middleware, index: int) -> str:
    """Derive a stable human-readable name for a middleware callable.

    Falls back to `<type>#<index>` for anonymous callables to keep names
    unique (MWP-INV-01 requires explicit names for insert/swap targets).
    """
    raw = getattr(mw, "__name__", None)
    candidate = str(raw) if isinstance(raw, str) else ""
    if candidate and candidate != "<lambda>":
        return candidate
    return f"{type(mw).__name__}#{index}"


# ---------------------------------------------------------------------------
# Finaliser helpers — public so adapters can reuse the INV-05 contract
# ---------------------------------------------------------------------------
def ensure_response(ctx: RequestContext) -> None:
    """MWP-INV-05 helper: stamp a 500 on an unresponded context."""
    if ctx.response_written:
        return
    ctx.status = FALLBACK_STATUS
    ctx.body = {"error": "NoResponse", "message": "middleware chain produced no response."}
    ctx.response_written = True


__all__ = [
    "DEFAULT_STATUS",
    "FALLBACK_STATUS",
    "ErrorFilter",
    "InMemoryMiddlewarePipeline",
    "MWPInvariantError",
    "Middleware",
    "MiddlewarePipeline",
    "Next",
    "RequestContext",
    "ensure_response",
]
