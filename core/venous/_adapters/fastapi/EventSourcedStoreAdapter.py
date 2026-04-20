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

from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException

from core.venous.events.EventSourcedStore.EventSourcedStore import (
    ConcurrencyError,
    InMemoryEventSourcedStore,
)


def install(app: FastAPI, *, prefix: str = "/events") -> InMemoryEventSourcedStore:
    """Attach an event-sourced store + REST router to *app*; return store."""
    store = InMemoryEventSourcedStore()
    router = APIRouter(prefix=prefix, tags=["events"])

    @router.get("/{aggregate_id}")
    def _load(aggregate_id: str) -> dict:
        events = [dict(e) if isinstance(e, dict) else {"event": repr(e)} for e in store.load(aggregate_id)]
        return {"aggregate_id": aggregate_id, "events": events, "version": len(events)}

    @router.post("/{aggregate_id}")
    def _append(aggregate_id: str, expected_version: int, events: list[dict[str, Any]]) -> dict:
        try:
            new_version = store.append(aggregate_id, expected_version, events)
        except ConcurrencyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"aggregate_id": aggregate_id, "version": new_version}

    app.include_router(router)
    app.state.event_store = store
    return store
