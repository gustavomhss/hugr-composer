"""Tests for the FastAPI `WorkflowAdapter` (WorkflowRun + DurableTimer)."""

from __future__ import annotations

import asyncio


def test_adapter_imports_cleanly() -> None:
    from core.venous._adapters.fastapi import WorkflowAdapter

    assert hasattr(WorkflowAdapter, "install")
    assert hasattr(WorkflowAdapter, "workflow_client_dep")
    assert hasattr(WorkflowAdapter, "timer_service_dep")


def test_install_attaches_client_and_timers() -> None:
    from fastapi import FastAPI

    from core.venous._adapters.fastapi.WorkflowAdapter import install
    from core.venous.jobs.DurableTimer.DurableTimer import InMemoryTimerService
    from core.venous.jobs.WorkflowRun.WorkflowRun import InMemoryWorkflowClient

    app = FastAPI()
    client, timers = install(app)
    assert isinstance(client, InMemoryWorkflowClient)
    assert isinstance(timers, InMemoryTimerService)
    assert app.state.workflow_client is client
    assert app.state.timer_service is timers


def test_client_can_start_and_describe_run() -> None:
    from fastapi import FastAPI

    from core.venous._adapters.fastapi.WorkflowAdapter import install

    app = FastAPI()
    client, _ = install(app)

    async def go() -> None:
        run = await client.start("export_report", "wf-1", "default", ())
        assert run.workflow_id == "wf-1"
        assert run.task_queue == "default"
        described = await client.describe("wf-1")
        assert described.run_id == run.run_id

    asyncio.run(go())


def test_timer_service_schedules_and_fires() -> None:
    from fastapi import FastAPI

    from core.venous._adapters.fastapi.WorkflowAdapter import install
    from core.venous.jobs.DurableTimer.DurableTimer import DurableTimer, TimerStatus

    app = FastAPI()
    _, timers = install(app)

    async def go() -> None:
        t = DurableTimer(workflow_id="wf-1", timer_id="t1", delay_s=0.0)
        await timers.start(t)
        timers.fire("wf-1", "t1")
        assert timers.status_of("wf-1", "t1") is TimerStatus.FIRED

    asyncio.run(go())


if __name__ == "__main__":
    import sys

    tests = [
        test_adapter_imports_cleanly,
        test_install_attaches_client_and_timers,
        test_client_can_start_and_describe_run,
        test_timer_service_schedules_and_fires,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL  {t.__name__}: {exc}")
            failed += 1
    sys.exit(1 if failed else 0)
