"""FastAPI adapter over `EventSourcedStore` + `DomainEvent`.

Wires an :class:`InMemoryEventSourcedStore` to FastAPI via a small read
router that exposes per-aggregate stream loading and append-with-
optimistic-concurrency in ≤ 30 lines of glue.

Usage::

    from fastapi import FastAPI
    from core.venous._adapters.fastapi.EventSourcedStoreAdapter import install

    app = FastAPI()
    store = install(app)
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException

from core.venous.events.EventSourcedStore.EventSourcedStore import (
    ConcurrencyError,
    InMemoryEventSourcedStore,
)


def install(
    app: FastAPI,
    *,
    auth_dependency: Callable[..., Any],
    prefix: str = "/events",
    store: Any = None,
) -> Any:
    """Attach an event-sourced store + auth-gated router to *app*; return store.

    The ``/events`` router reads and appends raw events for ANY aggregate id, so
    every route requires the injected ``auth_dependency`` (R5-O2-D6): anonymous
    access would let a caller read another aggregate's full event stream or
    append forged events. ``auth_dependency`` is REQUIRED — pass the app's
    ``get_current_superuser`` (this is a raw, cross-aggregate admin surface;
    application code uses ``app.state.event_store`` directly).

    *store* is an optional pre-built ``EventSourcedStore`` (e.g. the durable
    ``SqlEventSourcedStore``). When omitted, an in-memory reference store is
    created — NON-durable, lost on restart.
    """
    if store is None:
        store = InMemoryEventSourcedStore()
    router = APIRouter(prefix=prefix, tags=["events"])

    @router.get("/{aggregate_id}")
    def _load(aggregate_id: str, principal: object = Depends(auth_dependency)) -> dict:
        events = [
            dict(e) if isinstance(e, dict) else {"event": repr(e)} for e in store.load(aggregate_id)
        ]
        return {"aggregate_id": aggregate_id, "events": events, "version": len(events)}

    @router.post("/{aggregate_id}")
    def _append(
        aggregate_id: str,
        expected_version: int,
        events: list[dict[str, Any]],
        principal: object = Depends(auth_dependency),
    ) -> dict:
        try:
            new_version = store.append(aggregate_id, expected_version, events)
        except ConcurrencyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"aggregate_id": aggregate_id, "version": new_version}

    app.include_router(router)
    app.state.event_store = store
    return store
