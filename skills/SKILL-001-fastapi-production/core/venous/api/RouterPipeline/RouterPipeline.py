"""RouterPipeline primitive — named bundle of middleware joined by route.

Implements the catalog Protocol for `api.RouterPipeline` plus a reference
`Router` that owns a name -> pipeline index and a `RequestContext` that carries
per-request state in its `assigns` dict. The module performs zero I/O at import.

Invariant IDs cited by this module:

- RP-INV-01: a pipeline MUST run its middleware in declared order, every time;
  reorder at runtime SHALL NEVER happen.
- RP-INV-02: a route joined to a pipeline MUST execute its chain before the
  handler; the chain CANNOT be bypassed per request.
- RP-INV-03: pipelines MUST NOT share mutable state across requests; any state
  SHALL live in RequestContext.assigns.
- RP-INV-04: joining a route to a pipeline MUST be declarative; programmatic
  attach CANNOT happen after the router is sealed.
- RP-INV-05: a pipeline name MUST be unique within the router; duplicate
  declarations SHALL raise at boot.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final, Protocol, cast, runtime_checkable

# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------
PIPELINE_NAME_PATTERN_HINT: Final[str] = "non-empty ASCII identifier"
"""RP-INV-05: a pipeline name SHOULD be an identifier-like token so that error
messages remain legible; the Router enforces non-emptiness and type only."""


@dataclass
class RequestContext:
    """Per-request carrier for state that middleware and handlers may share.

    RP-INV-03: `assigns` is the ONLY sanctioned mutation surface. Pipelines and
    middleware MUST NOT hold request-scoped state on themselves; they write to
    `ctx.assigns` so that concurrent requests never interfere.
    """

    route: str
    method: str = "GET"
    assigns: dict[str, object] = field(default_factory=dict)
    halted: bool = False
    halt_reason: str | None = None

    def halt(self, reason: str) -> None:
        """Terminate the chain early while still returning through the pipeline.

        RP-INV-02: halting is the sanctioned way to short-circuit a chain; the
        pipeline still considers the request 'dispatched' because every
        middleware up to the halting one executed.
        """
        self.halted = True
        self.halt_reason = reason


# Middleware signature: receives ctx + `next` continuation, returns any object.
# Lower-case `next_` avoids shadowing the builtin while keeping the canonical
# middleware-chain vocabulary.
Middleware = Callable[["RequestContext", Callable[["RequestContext"], object]], object]
"""A Middleware takes (ctx, next) and either calls next(ctx) to continue or
returns a short-circuit value. RP-INV-01 requires that every Middleware in a
pipeline runs in index order before the handler is invoked."""

Handler = Callable[["RequestContext"], object]
"""Terminal endpoint invoked after every middleware has run (RP-INV-02)."""


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class RouterPipelineError(ValueError):
    """Raised when a runtime call violates a RouterPipeline invariant."""


# ---------------------------------------------------------------------------
# Protocol surface (mirrors the catalog api_signature byte-for-byte)
# ---------------------------------------------------------------------------
@runtime_checkable
class RouterPipeline(Protocol):
    """Protocol for the RouterPipeline primitive.

    Mirrors the catalog `api_signature` verbatim: a name, a Sequence of
    Middleware in declared order, and an `attach(route)` directive that joins
    a route to this bundle's chain.
    """

    name: str
    middleware: Sequence[Middleware]

    def attach(self, route: str) -> None: ...


# ---------------------------------------------------------------------------
# Reference pipeline
# ---------------------------------------------------------------------------
@dataclass
class _PipelineImpl:
    """Internal pipeline record owned by a Router.

    The `middleware` sequence is immutable post-registration (RP-INV-01); the
    `routes` list grows only while the router is unsealed (RP-INV-04).
    """

    name: str
    middleware: Sequence[Middleware]
    _router: Router
    _routes: list[str] = field(default_factory=list)

    def attach(self, route: str) -> None:
        """Join `route` to this pipeline.

        Fails loudly if the router has been sealed (RP-INV-04). The attach is
        declarative: no execution happens here; the route is simply indexed.
        """
        if self._router.is_sealed:
            raise RouterPipelineError(
                f"RP-INV-04: router is sealed; cannot attach {route!r} to pipeline "
                f"{self.name!r}. Declare attachments before Router.seal().",
            )
        if not isinstance(route, str) or not route:
            raise RouterPipelineError(
                "RP-INV-04 supporting: route MUST be a non-empty string; got "
                f"{type(route).__name__}={route!r}.",
            )
        self._router.record_attachment(self.name, route)
        self._routes.append(route)

    @property
    def routes(self) -> tuple[str, ...]:
        """Read-only snapshot of routes joined to this pipeline."""
        return tuple(self._routes)


# ---------------------------------------------------------------------------
# Router — owns pipelines + attachments + seal state
# ---------------------------------------------------------------------------
class Router:
    """Reference `Router` that registers pipelines and dispatches routes.

    Thread-safe: `register`, `seal`, and `record_attachment` acquire an internal
    lock so concurrent bootstrapping produces a deterministic index.
    """

    def __init__(self) -> None:
        self._pipelines: dict[str, _PipelineImpl] = {}
        # route -> pipeline name (RP-INV-02: every dispatched route is linked).
        self._route_index: dict[str, str] = {}
        self._sealed: bool = False
        self._lock = threading.Lock()

    # ----- introspection -----------------------------------------------------
    @property
    def is_sealed(self) -> bool:
        return self._sealed

    @property
    def pipelines(self) -> Mapping[str, RouterPipeline]:
        """Read-only view of registered pipelines keyed by name."""
        with self._lock:
            snapshot: dict[str, RouterPipeline] = {
                name: cast("RouterPipeline", pipeline)
                for name, pipeline in self._pipelines.items()
            }
        return snapshot

    @property
    def attachments(self) -> Mapping[str, str]:
        """Read-only view of route -> pipeline name mappings."""
        with self._lock:
            return dict(self._route_index)

    def get(self, name: str) -> RouterPipeline:
        """O(1) lookup of a pipeline by name (RP-INV-05 guarantees uniqueness)."""
        with self._lock:
            pipeline = self._pipelines.get(name)
        if pipeline is None:
            raise RouterPipelineError(
                f"RP-INV-05 supporting: no pipeline registered under {name!r}; "
                f"registered names: {sorted(self._pipelines)}.",
            )
        return cast("RouterPipeline", pipeline)

    # ----- registration ------------------------------------------------------
    def register(
        self, name: str, middleware: Iterable[Middleware],
    ) -> RouterPipeline:
        """Declare a new pipeline bundle.

        RP-INV-05: duplicate names raise immediately.
        RP-INV-04: registration AFTER seal is forbidden.
        RP-INV-01: the middleware order captured here is the order used at
        dispatch — the stored tuple is immutable.
        """
        if not isinstance(name, str) or not name:
            raise RouterPipelineError(
                "RP-INV-05 supporting: pipeline name MUST be a non-empty string; "
                f"got {type(name).__name__}={name!r}.",
            )
        chain = tuple(middleware)
        for idx, mw in enumerate(chain):
            if not callable(mw):
                raise RouterPipelineError(
                    f"RP-INV-01 supporting: middleware[{idx}] in pipeline {name!r} "
                    f"MUST be callable; got {type(mw).__name__}.",
                )
        with self._lock:
            if self._sealed:
                raise RouterPipelineError(
                    f"RP-INV-04: router is sealed; cannot register pipeline {name!r}.",
                )
            if name in self._pipelines:
                raise RouterPipelineError(
                    f"RP-INV-05: pipeline name {name!r} is already registered; "
                    "duplicate declarations SHALL raise at boot.",
                )
            pipeline = _PipelineImpl(name=name, middleware=chain, _router=self)
            self._pipelines[name] = pipeline
        return cast("RouterPipeline", pipeline)

    def seal(self) -> None:
        """Freeze the router; no further registrations or attachments allowed.

        RP-INV-04: this is the one-way gate that turns declarative wiring into
        runtime dispatch.
        """
        with self._lock:
            self._sealed = True

    def record_attachment(self, pipeline_name: str, route: str) -> None:
        """Index a route under a pipeline. Called by `_PipelineImpl.attach`."""
        with self._lock:
            if self._sealed:
                raise RouterPipelineError(
                    f"RP-INV-04: router is sealed; cannot attach {route!r} to "
                    f"pipeline {pipeline_name!r}.",
                )
            if pipeline_name not in self._pipelines:
                raise RouterPipelineError(
                    f"RP-INV-05 supporting: pipeline {pipeline_name!r} is not registered.",
                )
            existing = self._route_index.get(route)
            if existing is not None and existing != pipeline_name:
                raise RouterPipelineError(
                    f"RP-INV-02 supporting: route {route!r} is already attached to "
                    f"pipeline {existing!r}; a route MUST resolve to exactly one "
                    "chain.",
                )
            self._route_index[route] = pipeline_name

    # ----- dispatch ----------------------------------------------------------
    def dispatch(self, route: str, handler: Handler, ctx: RequestContext) -> object:
        """Execute the chain attached to `route` and then invoke `handler`.

        RP-INV-02: the chain ALWAYS runs before the handler. There is no path
        through `dispatch` that calls the handler without running the indexed
        middleware in declared order.
        RP-INV-03: `ctx.assigns` is the only shared surface; the Router never
        stashes request-scoped state on itself or on `_PipelineImpl`.
        """
        if not self._sealed:
            raise RouterPipelineError(
                "RP-INV-04: router MUST be sealed before dispatch; call Router.seal() "
                "after all pipelines are registered and routes attached.",
            )
        with self._lock:
            pipeline_name = self._route_index.get(route)
        if pipeline_name is None:
            raise RouterPipelineError(
                f"RP-INV-02 supporting: no pipeline attached to route {route!r}; "
                "attach the route before dispatch.",
            )
        pipeline = self._pipelines[pipeline_name]
        return run_chain(pipeline.middleware, handler, ctx)


# ---------------------------------------------------------------------------
# Chain executor — single authoritative implementation of RP-INV-01 / INV-02
# ---------------------------------------------------------------------------
def run_chain(
    middleware: Sequence[Middleware],
    handler: Handler,
    ctx: RequestContext,
) -> object:
    """Run `middleware` in index order, then `handler`.

    Any middleware that declines to call `next_` short-circuits the chain; its
    own return value becomes the dispatch result. If `ctx.halt()` was called,
    subsequent middleware are NOT executed but the pipeline still considers the
    request delivered (RP-INV-02: the chain up to halt did run before any
    downstream decision was made).
    """

    def _step(index: int, current_ctx: RequestContext) -> object:
        if current_ctx.halted:
            return {"halted": True, "reason": current_ctx.halt_reason}
        if index >= len(middleware):
            return handler(current_ctx)
        mw = middleware[index]

        def _next(next_ctx: RequestContext) -> object:
            return _step(index + 1, next_ctx)

        return mw(current_ctx, _next)

    return _step(0, ctx)


__all__ = [
    "PIPELINE_NAME_PATTERN_HINT",
    "Handler",
    "Middleware",
    "RequestContext",
    "Router",
    "RouterPipeline",
    "RouterPipelineError",
    "run_chain",
]
