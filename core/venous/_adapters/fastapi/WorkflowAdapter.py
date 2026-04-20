"""FastAPI adapter over the `WorkflowRun` + `DurableTimer` primitives.

Exposes a workflow client + timer service on ``app.state`` for
long-running-task HTTP patterns (POST returns 202 + run_id, GET polls
status, DELETE cancels). ≤ 30 lines of glue.

Usage::

    from fastapi import FastAPI
    from core.venous._adapters.fastapi.WorkflowAdapter import install

    app = FastAPI()
    install(app)

    @app.post("/tasks", status_code=202)
    async def start(payload: dict, request: Request):
        client = request.app.state.workflow_client
        run = await client.start("export_report", payload["id"], "default", (payload,))
        return {"run_id": run.run_id, "workflow_id": run.workflow_id}
"""

from __future__ import annotations

from fastapi import FastAPI, Request

from core.venous.jobs.DurableTimer.DurableTimer import InMemoryTimerService
from core.venous.jobs.WorkflowRun.WorkflowRun import IdReusePolicy, InMemoryWorkflowClient


def install(
    app: FastAPI,
    *,
    id_reuse: IdReusePolicy = IdReusePolicy.REJECT,
) -> tuple[InMemoryWorkflowClient, InMemoryTimerService]:
    """Install a workflow client + timer service on *app*; return both."""
    client = InMemoryWorkflowClient(id_reuse=id_reuse)
    timers = InMemoryTimerService()
    app.state.workflow_client = client
    app.state.timer_service = timers
    return client, timers


def workflow_client_dep(request: Request) -> InMemoryWorkflowClient:
    """FastAPI ``Depends``-compatible accessor for the workflow client."""
    return request.app.state.workflow_client


def timer_service_dep(request: Request) -> InMemoryTimerService:
    """FastAPI ``Depends``-compatible accessor for the timer service."""
    return request.app.state.timer_service
