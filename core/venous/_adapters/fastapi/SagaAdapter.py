"""FastAPI adapter over `SagaOrchestrator`.

Wires an :class:`InMemorySagaOrchestrator` (with an empty-by-default
:class:`SagaDefinition` supplied by the caller) to FastAPI through a
small admin router exposing ``start``, ``step``, ``compensate``, and
``status`` in ≤ 30 lines of glue.

Every route requires an injected ``auth_dependency`` (B0.11): the
``/admin/sagas`` surface starts, advances, and inspects saga state for ANY
correlation id, so anonymous access would let a caller drive or read
another tenant's orchestration. ``auth_dependency`` is REQUIRED — pass the
app's ``get_current_superuser`` (this is a raw, cross-correlation admin
surface; application code uses ``app.state.saga_orchestrator`` directly).

Usage::

    from fastapi import FastAPI
    from app.api.deps import get_current_superuser
    from core.venous._adapters.fastapi.SagaAdapter import install
    from core.venous.events.SagaOrchestrator.SagaOrchestrator import SagaDefinition

    app = FastAPI()
    d = SagaDefinition("checkout")
    d.register("charge", handler=..., compensator=...)
    install(app, definition=d, auth_dependency=get_current_superuser)
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException

from core.venous.events.SagaOrchestrator.SagaOrchestrator import (
    InMemorySagaOrchestrator,
    SagaDefinition,
    SagaOrchestratorInvariantError,
)


def install(
    app: FastAPI,
    *,
    definition: SagaDefinition,
    auth_dependency: Callable[..., Any],
    prefix: str = "/admin/sagas",
) -> InMemorySagaOrchestrator:
    """Attach a saga orchestrator + auth-gated admin router to *app*.

    ``auth_dependency`` guards every route (e.g. the app's
    ``get_current_superuser``). REQUIRED — there is no anonymous access to
    the saga admin surface. Returns the orchestrator.
    """
    orch = InMemorySagaOrchestrator(definition)
    router = APIRouter(prefix=prefix, tags=["sagas"])

    @router.post("/{correlation_id}/start")
    def _start(
        correlation_id: str,
        payload: dict | None = None,
        principal: object = Depends(auth_dependency),
    ) -> dict:
        try:
            orch.start(correlation_id, payload or {})
        except SagaOrchestratorInvariantError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        state, completed = orch.status(correlation_id)
        return {"correlation_id": correlation_id, "state": state, "completed": list(completed)}

    @router.post("/{correlation_id}/step/{name}")
    def _step(
        correlation_id: str,
        name: str,
        outcome: Any = None,
        principal: object = Depends(auth_dependency),
    ) -> dict:
        orch.step(correlation_id, name, outcome)
        state, completed = orch.status(correlation_id)
        return {"state": state, "completed": list(completed)}

    @router.get("/{correlation_id}")
    def _status(
        correlation_id: str,
        principal: object = Depends(auth_dependency),
    ) -> dict:
        state, completed = orch.status(correlation_id)
        return {"correlation_id": correlation_id, "state": state, "completed": list(completed)}

    app.include_router(router)
    app.state.saga_orchestrator = orch
    return orch
