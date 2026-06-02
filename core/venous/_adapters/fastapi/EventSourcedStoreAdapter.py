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
    owner_resolver: Callable[[Any, str], bool] | None = None,
) -> Any:
    """Attach an event-sourced store + auth-gated router to *app*; return store.

    The ``/events`` router reads and appends raw events for ANY aggregate id, so
    every route requires the injected ``auth_dependency`` (R5-O2-D6): anonymous
    access would let a caller read another aggregate's full event stream or
    append forged events. ``auth_dependency`` is REQUIRED — pass the app's
    ``get_current_superuser`` (this is a raw, cross-aggregate admin surface;
    application code uses ``app.state.event_store`` directly).

    .. warning::

       ⚠️ FOOTGUN (R8-J1-4): ``auth_dependency`` enforces *authentication*
       only — it does NOT scope access to the caller's own aggregates. With
       a non-superuser dependency, ANY authenticated user can read or append
       to ANY ``aggregate_id``. ``auth_dependency`` MUST therefore be
       SUPERUSER-GRADE, *unless* you also pass ``owner_resolver`` for
       per-aggregate ownership checks.

    ``owner_resolver`` (optional) — ``(principal, aggregate_id) -> bool``.
    When provided, every route additionally checks that the authenticated
    ``principal`` owns ``aggregate_id``; a falsy return yields HTTP 403. This
    lets a non-superuser ``auth_dependency`` be used safely for per-tenant /
    per-owner access. When omitted, no ownership check is applied (the
    superuser footgun above applies).

    *store* is an optional pre-built ``EventSourcedStore`` (e.g. the durable
    ``SqlEventSourcedStore``). When omitted, an in-memory reference store is
    created — NON-durable, lost on restart.
    """
    if store is None:
        store = InMemoryEventSourcedStore()
    router = APIRouter(prefix=prefix, tags=["events"])

    def _check_owner(principal: Any, aggregate_id: str) -> None:
        if owner_resolver is not None and not owner_resolver(principal, aggregate_id):
            raise HTTPException(status_code=403, detail="not the aggregate owner")

    @router.get("/{aggregate_id}")
    def _load(aggregate_id: str, principal: object = Depends(auth_dependency)) -> dict:
        _check_owner(principal, aggregate_id)
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
        _check_owner(principal, aggregate_id)
        try:
            new_version = store.append(aggregate_id, expected_version, events)
        except ConcurrencyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"aggregate_id": aggregate_id, "version": new_version}

    app.include_router(router)
    app.state.event_store = store
    return store
