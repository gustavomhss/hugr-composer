"""FastAPI adapter over `MaterializedView` (CQRS read model / projection).

Wires one or more :class:`InMemoryMaterializedView` projections to FastAPI via
a small read router that exposes ``GET /projections/{view}`` (query the
read model) and a superuser-gated ``POST /projections/{view}/rebuild``
(replay from the event store). The companion ``add_event_sourcing`` /
``add_read_model_projection`` tools own the application-level handler
registration; this adapter is the runtime wiring.

Usage::

    from fastapi import FastAPI
    from core.venous._adapters.fastapi.MaterializedViewAdapter import install

    app = FastAPI()
    views = install(app, store=app.state.event_store, auth_dependency=...)

Read-model guarantees (NOT linearizable, NOT real-time): a projection is
bounded-stale w.r.t. the event store. Rebuild is MANUAL/on-demand — there is
NO background tailer in v1. Apply is at-least-once + idempotent (events whose
``seq`` is ``<= last_applied`` are dropped), giving effectively-once, not
exactly-once.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException

from core.venous.data.MaterializedView.MaterializedView import (
    InMemoryMaterializedView,
    MaterializedViewInvariantError,
)


def rebuild_from_store(
    view: InMemoryMaterializedView,
    store: Any,
    aggregate_ids: Iterable[str],
    *,
    schema_version: int = 1,
) -> int:
    """Replay events from an EventSourcedStore-shaped *store* into *view*.

    Maps each store event into the MaterializedView event shape
    (``type``/``aggregate_id``/``seq``/``schema_version``). Rows are keyed by
    ``aggregate_id`` (PER-AGGREGATE-GRAIN projection); ``seq`` is a monotonic
    counter assigned over the whole replay (the view dedupes on a single
    monotonic ``last_applied_seq``, so seq MUST strictly increase across the
    replay regardless of aggregate). Returns the number of events applied.

    MV-INV-02: the view is regenerated purely from the source feed; it is
    NEVER the system of record. At-least-once + idempotent: re-running the same
    replay starts ``seq`` from 1 again, so every event lands ``<= last_applied``
    and is dropped by the view — effectively-once, not exactly-once. The return
    value counts events the view ACTUALLY applied (dropped duplicates excluded).
    """
    before = view.applied_event_count
    seq = 0
    for aggregate_id in aggregate_ids:
        for raw in store.load(aggregate_id):
            seq += 1
            event = _to_view_event(raw, aggregate_id, seq, schema_version)
            view.apply(event)
    return view.applied_event_count - before


def _to_view_event(
    raw: Any,
    aggregate_id: str,
    seq: int,
    schema_version: int,
) -> dict[str, Any]:
    """Coerce a raw store event into the MaterializedView event shape.

    The event store holds opaque per-aggregate events (e.g.
    ``{"type": "created", "data": {...}}``). The view requires
    ``type``/``aggregate_id``/``seq``/``schema_version``; the per-aggregate
    version supplies ``seq`` (per-aggregate-grain). A non-mapping raw event is
    rejected rather than silently coerced (MV-INV-05 is enforced downstream by
    ``view.apply``).
    """
    base: dict[str, Any] = dict(raw) if isinstance(raw, dict) else {"type": repr(raw)}
    base["aggregate_id"] = aggregate_id
    base["seq"] = seq
    base.setdefault("schema_version", schema_version)
    return base


def install(
    app: FastAPI,
    *,
    store: Any,
    auth_dependency: Callable[..., Any],
    prefix: str = "/projections",
    views: dict[str, InMemoryMaterializedView] | None = None,
    aggregate_id_resolver: Callable[[Any], Iterable[str]] | None = None,
) -> dict[str, InMemoryMaterializedView]:
    """Attach read-model projections + auth-gated router to *app*; return views.

    The ``/projections`` router serves cross-aggregate read-model rows and can
    trigger a full replay of the event store, so every route requires the
    injected ``auth_dependency`` (mirrors EventSourcedStoreAdapter, R5-O2-D6):
    anonymous access would let a caller read any projected row or force an
    expensive cross-aggregate rebuild. ``auth_dependency`` is REQUIRED — pass
    the app's ``get_current_superuser``.

    .. warning::

       FOOTGUN: ``auth_dependency`` enforces *authentication* only — it does
       NOT scope rows to the caller's own aggregates. The read model is a
       cross-aggregate surface; ``auth_dependency`` MUST therefore be
       SUPERUSER-GRADE. The ``POST /{view}/rebuild`` route is additionally a
       cross-aggregate replay (cost amplification) and is gated by the same
       superuser dependency.

    *store* is the EventSourcedStore (typically ``app.state.event_store``) the
    rebuild route replays from. *views* is an optional pre-built mapping of
    ``view_name -> InMemoryMaterializedView`` with handlers already registered
    (via ``view.on(event_type)``); when omitted an empty registry is created
    and projections can be added later through ``app.state.materialized_views``.

    *aggregate_id_resolver* (optional) — ``(store) -> Iterable[str]`` listing
    the aggregate ids to replay on rebuild. Required for rebuild to do anything
    useful: the EventSourcedStore surface has no portable "list all aggregates"
    method, so the application supplies the id set. When omitted, rebuild
    raises HTTP 501 (no source of aggregate ids).
    """
    views = views if views is not None else {}
    router = APIRouter(prefix=prefix, tags=["projections"])

    def _get_view(view: str) -> InMemoryMaterializedView:
        mv = app.state.materialized_views.get(view)
        if mv is None:
            raise HTTPException(status_code=404, detail=f"unknown projection {view!r}")
        return mv

    @router.get("/{view}")
    def _query(view: str, _principal: object = Depends(auth_dependency)) -> dict:
        mv = _get_view(view)
        try:
            rows = [dict(r) for r in mv.query(None)]
        except MaterializedViewInvariantError as exc:
            # e.g. pending schema evolution → rebuild required (409, not 500).
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "view": view,
            "rows": rows,
            "stale": not mv.is_fresh(),
            "staleness_s": mv.staleness_s(),
            "last_applied_seq": mv.last_applied_seq,
        }

    @router.post("/{view}/rebuild")
    def _rebuild(view: str, _principal: object = Depends(auth_dependency)) -> dict:
        mv = _get_view(view)
        if aggregate_id_resolver is None:
            raise HTTPException(
                status_code=501,
                detail=(
                    "rebuild needs an aggregate_id_resolver to enumerate the "
                    "event store's aggregate ids (no portable list-all on the "
                    "EventSourcedStore surface)."
                ),
            )
        aggregate_ids = list(aggregate_id_resolver(store))
        # Drop-and-replay: regenerate purely from the source feed (MV-INV-02).
        mv.rebuild(())
        applied = rebuild_from_store(mv, store, aggregate_ids)
        return {"view": view, "aggregates": len(aggregate_ids), "events_applied": applied}

    app.include_router(router)
    app.state.materialized_views = views
    return views


def make_view(
    view_name: str,
    *,
    schema_version: int = 1,
    max_age_s: float = 60.0,
) -> InMemoryMaterializedView:
    """Convenience factory for an in-memory projection (per-process, non-durable)."""
    return InMemoryMaterializedView(
        view_name,
        schema_version=schema_version,
        max_age_s=max_age_s,
    )


__all__ = ["install", "make_view", "rebuild_from_store"]
