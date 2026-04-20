"""FastAPI adapter over `SagaOrchestrator`.

Wires an :class:`InMemorySagaOrchestrator` (with an empty-by-default
:class:`SagaDefinition` supplied by the caller) to FastAPI through a
small admin router exposing ``start``, ``step``, ``compensate``, and
``status`` in ≤ 30 lines of glue.

Usage::

    from fastapi import FastAPI
    from core.venous._adapters.fastapi.SagaAdapter import install
    from core.venous.events.SagaOrchestrator.SagaOrchestrator import SagaDefinition

    app = FastAPI()
    d = SagaDefinition("checkout")
    d.register("charge", handler=..., compensator=...)
    install(app, definition=d)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException

from core.venous.events.SagaOrchestrator.SagaOrchestrator import (
    InMemorySagaOrchestrator,
    SagaDefinition,
    SagaOrchestratorInvariantError,
)


def install(app: FastAPI, *, definition: SagaDefinition, prefix: str = "/admin/sagas") -> InMemorySagaOrchestrator:
    """Attach a saga orchestrator + admin router to *app*; return orchestrator."""
    orch = InMemorySagaOrchestrator(definition)
    router = APIRouter(prefix=prefix, tags=["sagas"])

    @router.post("/{correlation_id}/start")
    def _start(correlation_id: str, payload: dict | None = None) -> dict:
        try:
            orch.start(correlation_id, payload or {})
        except SagaOrchestratorInvariantError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        state, completed = orch.status(correlation_id)
        return {"correlation_id": correlation_id, "state": state, "completed": list(completed)}

    @router.post("/{correlation_id}/step/{name}")
    def _step(correlation_id: str, name: str, outcome: Any = None) -> dict:
        orch.step(correlation_id, name, outcome)
        state, completed = orch.status(correlation_id)
        return {"state": state, "completed": list(completed)}

    @router.get("/{correlation_id}")
    def _status(correlation_id: str) -> dict:
        state, completed = orch.status(correlation_id)
        return {"correlation_id": correlation_id, "state": state, "completed": list(completed)}

    app.include_router(router)
    app.state.saga_orchestrator = orch
    return orch
