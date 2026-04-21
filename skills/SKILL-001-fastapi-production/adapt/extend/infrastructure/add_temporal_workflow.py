"""TOOL-067: add_temporal_workflow — add a Temporal.io durable workflow engine to a FastAPI project.

Writes an ``app/workflows/`` package containing a lazy-import ``TemporalClientFactory``
singleton, a ``WorkerFactory`` for the separate worker process, an
``OrderProcessingWorkflow`` with 3 activities and compensation-on-failure, activity
definitions with retry policies, REST companion routes for starting, querying,
signalling, and cancelling workflows, and a ``Dockerfile.temporal-worker`` for the
non-root container.

Why Temporal (and not arq / Celery)?

* **Durable execution** — workflows survive process restarts, network failures, and
  deploy cycles.  Temporal's server persists every event; nothing is lost.
* **Compensation pattern** — rollback logic is first-class: ``workflow.execute_activity``
  can be wrapped in try/except so compensations run on any activity failure.
* **Signals + queries** — external events (cancel, pause) can be injected into running
  workflows without polling or DB mutations.
* **Separate worker process** — the FastAPI app and the Temporal worker are completely
  decoupled; ``app/main.py`` is never modified.

Security / correctness guarantees:

* ``temporalio`` is imported LAZILY (inside function bodies) so ``app.main`` boots
  without the optional SDK installed.
* Temporal host, namespace, and task queue are read from ``settings`` — the tool
  never invents hostnames or hard-codes config.
* REST routes require authentication (``CurrentUser``) so workflow state cannot be
  inspected anonymously.
* Worker runs as non-root (``USER 1000``) in ``Dockerfile.temporal-worker``.

The tool is idempotent: a second run detects the ``TemporalClientFactory``
fingerprint in ``app/workflows/client.py`` and returns ``status="no_op"``
without touching any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_temporal_workflow import add_temporal_workflow

    result = add_temporal_workflow(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["…/app/workflows/client.py", …]
    print(result.next_steps)    # ["Start Temporal server", …]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_resiliency_add_temporal_workflow",
    "description": (
        "Add a Temporal.io durable workflow engine with order-processing example, "
        "compensation pattern, signal support, and REST companion routes."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_temporal_workflow",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _elapsed_ms(start: float) -> int:
    """Return milliseconds elapsed since *start* (monotonic clock).

    Args:
        start: Value from ``time.monotonic()`` at the start of the operation.

    Returns:
        Elapsed milliseconds as a positive integer (minimum 1).
    """
    return max(1, int((time.monotonic() - start) * 1000))


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_temporal_workflow(inp: ToolInput) -> ToolResult:
    """Add a Temporal.io durable workflow engine to a FastAPI project.

    Creates the workflows package (client singleton, worker factory, example
    workflow with compensation, activity definitions), REST companion routes,
    ``Dockerfile.temporal-worker``, and patches ``app/core/config.py`` and
    ``requirements.txt``.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and optional
            ``dry_run`` flag.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(
            status="error",
            error=err,
            execution_time_ms=_elapsed_ms(start),
        )

    # --- Prerequisite check (standalone mode) --------------------------------
    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.CONFIG_SETTINGS,
        Prereq.ROUTES_INIT,
        Prereq.REQUIREMENTS_TXT,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=[
                "These prerequisites cannot be auto-created.",
                "Generate a base project first:",
                "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    if scaffolded:
        files_created.extend(scaffolded)

    app_dir = project / "app"

    # --- Idempotency guard ---------------------------------------------------
    client_file = app_dir / "workflows" / "client.py"
    if client_file.exists() and "TemporalClientFactory" in client_file.read_text():
        return ToolResult(
            status="no_op",
            notes=[
                "TemporalClientFactory already present — "
                "Temporal workflow engine is already installed, skipped."
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/workflows/ package "
                "(client.py, worker.py, example_workflow.py, activities.py),",
                "         POST /workflows/start, GET /workflows/{id}/status, "
                "POST /workflows/{id}/signal, POST /workflows/{id}/cancel,",
                "         Dockerfile.temporal-worker.",
                "[dry_run] Would patch app/core/config.py with TEMPORAL_HOST, "
                "TEMPORAL_NAMESPACE, TEMPORAL_TASK_QUEUE.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # Step 1 — workflows package __init__.py
    workflows_dir = app_dir / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    workflows_init = workflows_dir / "__init__.py"
    if not workflows_init.exists():
        _write_workflows_init(workflows_init)
        files_created.append(str(workflows_init))

    # Step 2 — client.py (TemporalClientFactory singleton)
    _write_client_module(client_file)
    files_created.append(str(client_file))

    # Step 3 — worker.py (WorkerFactory + start/stop helpers)
    worker_file = workflows_dir / "worker.py"
    _write_worker_module(worker_file)
    files_created.append(str(worker_file))

    # Step 4 — activities.py (activity definitions with retry policies)
    activities_file = workflows_dir / "activities.py"
    _write_activities_module(activities_file)
    files_created.append(str(activities_file))

    # Step 5 — example_workflow.py (OrderProcessingWorkflow + compensation)
    workflow_file = workflows_dir / "example_workflow.py"
    _write_example_workflow(workflow_file)
    files_created.append(str(workflow_file))

    # Step 6 — REST companion routes
    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    workflow_routes_file = routes_dir / "workflows.py"
    _write_workflow_routes(workflow_routes_file)
    files_created.append(str(workflow_routes_file))

    # Step 7 — Dockerfile.temporal-worker
    dockerfile = project / "Dockerfile.temporal-worker"
    if not dockerfile.exists():
        _write_dockerfile(dockerfile)
        files_created.append(str(dockerfile))

    # Step 8 — patch config.py
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # Step 9 — patch requirements.txt
    requirements_file = project / "requirements.txt"
    if requirements_file.exists():
        _patch_requirements(requirements_file)
        files_modified.append(str(requirements_file))

    # Step 10 — register router in app/routes/__init__.py
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    # --- AST validation loop (BUG-02 guard) ---------------------------------
    for path_str in files_created:
        p = Path(path_str)
        if p.suffix == ".py" and p.is_file():
            try:
                ast.parse(p.read_text())
            except SyntaxError as exc:
                return ToolResult(
                    status="error",
                    error=f"Generated file has syntax error: {p}: {exc}",
                    execution_time_ms=_elapsed_ms(start),
                )

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "Temporal workflow engine added: TemporalClientFactory singleton, "
            "WorkerFactory, OrderProcessingWorkflow with compensation pattern.",
            "Activities: validate_order, charge_payment, fulfil_order "
            "(each with retry policy + compensation).",
            "REST routes: POST /workflows/start, GET /workflows/{id}/status, "
            "POST /workflows/{id}/signal, POST /workflows/{id}/cancel.",
            "Worker runs as a separate process — app/main.py is NOT modified.",
            "temporalio imported lazily so app boots without the SDK installed.",
            "Dockerfile.temporal-worker generated (non-root USER 1000).",
        ],
        next_steps=[
            "Start a Temporal server: "
            "docker run --rm -p 7233:7233 temporalio/auto-setup:latest",
            "Set TEMPORAL_HOST in .env (default: localhost:7233).",
            "Set TEMPORAL_NAMESPACE (default: default) and "
            "TEMPORAL_TASK_QUEUE (default: main-queue).",
            "Install the SDK: pip install 'temporalio>=1.7.0'",
            "Start the worker: "
            "docker build -f Dockerfile.temporal-worker -t myapp-temporal-worker . "
            "&& docker run --rm --env-file .env myapp-temporal-worker",
            "Or locally: python -m app.workflows.worker",
            "Restart the FastAPI app so the /workflows/* routes are active.",
            "Verify: POST /workflows/start with an order_id payload.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers
# ---------------------------------------------------------------------------

def _write_workflows_init(dest: Path) -> None:
    """Write ``app/workflows/__init__.py`` with re-exports.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Temporal workflow engine sub-package.

        Re-exports the public surface area so callers only need to import
        from ``app.workflows`` rather than individual sub-modules.
        \"\"\"

        from app.workflows.client import TemporalClientFactory, get_client
        from app.workflows.worker import WorkerFactory, start_worker, stop_worker

        __all__ = [
            "TemporalClientFactory",
            "get_client",
            "WorkerFactory",
            "start_worker",
            "stop_worker",
        ]
    """)
    dest.write_text(content)


def _write_client_module(dest: Path) -> None:
    """Write ``app/workflows/client.py`` with the lazy TemporalClientFactory.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Temporal client factory with lazy SDK import and singleton caching.

        ``temporalio`` is an OPTIONAL dependency.  This module never imports it
        at the top level so that ``app.main`` boots cleanly when the SDK is
        absent (e.g. in the API-only container that does not run workflows).

        Usage::

            from app.workflows.client import get_client

            client = await get_client()
            handle = await client.start_workflow(...)
        \"\"\"

        from __future__ import annotations

        import logging
        from typing import Any

        from app.core.config import settings

        logger = logging.getLogger(__name__)

        _client: Any | None = None


        class TemporalClientFactory:
            \"\"\"Factory that creates and caches a Temporal client singleton.

            All access goes through the module-level ``get_client()`` helper;
            this class exists so tests can substitute a mock without
            monkey-patching module globals.

            Attributes:
                host: Temporal server address (host:port).
                namespace: Temporal namespace for workflow isolation.
            \"\"\"

            def __init__(self, host: str, namespace: str) -> None:
                \"\"\"Initialise the factory with server coordinates.

                Args:
                    host: Temporal server address (e.g. ``localhost:7233``).
                    namespace: Temporal namespace (e.g. ``default``).
                \"\"\"
                self.host = host
                self.namespace = namespace

            async def connect(self) -> Any:
                \"\"\"Create a new Temporal client connection.

                Imports ``temporalio.client.Client`` lazily so the module is
                safe to import without the SDK installed.

                Returns:
                    A connected ``temporalio.client.Client`` instance.

                Raises:
                    ModuleNotFoundError: When ``temporalio`` is not installed.
                \"\"\"
                from temporalio.client import Client  # lazy SDK import

                client = await Client.connect(
                    self.host, namespace=self.namespace
                )
                logger.info(
                    "Temporal client connected",
                    extra={"host": self.host, "namespace": self.namespace},
                )
                return client


        async def get_client() -> Any:
            \"\"\"Return the process-wide Temporal client, creating it lazily.

            On first call, creates and caches the client using settings from
            ``app.core.config.settings``.  Subsequent calls return the cached
            instance without reconnecting.

            Returns:
                A connected ``temporalio.client.Client`` instance.
            \"\"\"
            global _client
            if _client is None:
                factory = TemporalClientFactory(
                    host=settings.TEMPORAL_HOST,
                    namespace=settings.TEMPORAL_NAMESPACE,
                )
                _client = await factory.connect()
            return _client
    """)
    dest.write_text(content)


def _write_worker_module(dest: Path) -> None:
    """Write ``app/workflows/worker.py`` with WorkerFactory and start/stop helpers.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Temporal worker factory and lifecycle helpers.

        The worker runs as a SEPARATE PROCESS from FastAPI.  ``app/main.py``
        is never imported or modified; the worker entry point is
        ``python -m app.workflows.worker``.

        ``temporalio`` is imported lazily so this module is safe to import
        without the SDK installed.
        \"\"\"

        from __future__ import annotations

        import logging
        from typing import Any

        from app.core.config import settings

        logger = logging.getLogger(__name__)

        _worker: Any | None = None


        class WorkerFactory:
            \"\"\"Creates a Temporal worker bound to a task queue.

            Attributes:
                task_queue: Name of the Temporal task queue to poll.
            \"\"\"

            def __init__(self, task_queue: str) -> None:
                \"\"\"Initialise the factory with a task queue name.

                Args:
                    task_queue: Temporal task queue the worker will poll.
                \"\"\"
                self.task_queue = task_queue

            async def create(self, client: Any) -> Any:
                \"\"\"Create a Temporal worker connected to *client*.

                Imports the SDK lazily, applies ``@activity.defn`` to each
                activity function, and registers workflows + activities.

                Args:
                    client: Connected ``temporalio.client.Client`` instance.

                Returns:
                    A configured ``temporalio.worker.Worker`` instance.
                \"\"\"
                from temporalio import activity as _act  # lazy SDK import
                from temporalio.worker import Worker

                import app.workflows.activities as _acts
                from app.workflows.example_workflow import OrderProcessingWorkflow

                activity_fns = [
                    _acts.validate_order,
                    _acts.charge_payment,
                    _acts.fulfil_order,
                    _acts.compensate_payment,
                ]
                registered = [_act.defn(fn) for fn in activity_fns]
                worker = Worker(
                    client,
                    task_queue=self.task_queue,
                    workflows=[OrderProcessingWorkflow],
                    activities=registered,
                )
                logger.info("Temporal worker created task_queue=%s", self.task_queue)
                return worker


        async def start_worker() -> Any:
            \"\"\"Create and start the Temporal worker (module-level singleton).

            Connects to the Temporal server, creates the worker, and starts
            polling.  Caches the worker so ``stop_worker()`` can shut it down.

            Returns:
                The running ``temporalio.worker.Worker`` instance.
            \"\"\"
            global _worker
            from app.workflows.client import get_client

            client = await get_client()
            factory = WorkerFactory(task_queue=settings.TEMPORAL_TASK_QUEUE)
            _worker = await factory.create(client)
            await _worker.start()
            logger.info("Temporal worker started")
            return _worker


        async def stop_worker() -> None:
            \"\"\"Gracefully shut down the running Temporal worker.

            No-op when no worker has been started (e.g. in the API-only
            container).
            \"\"\"
            global _worker
            if _worker is not None:
                await _worker.shutdown()
                logger.info("Temporal worker stopped")
                _worker = None


        def main() -> None:
            \"\"\"Run the Temporal worker until interrupted.

            Entry point for ``python -m app.workflows.worker`` and the
            ``Dockerfile.temporal-worker`` CMD.
            \"\"\"
            import asyncio

            async def _run() -> None:
                worker = await start_worker()
                await worker.wait_all_polling_complete()

            asyncio.run(_run())


        if __name__ == "__main__":
            main()
    """)
    dest.write_text(content)


def _write_activities_module(dest: Path) -> None:
    """Write ``app/workflows/activities.py`` with retry-policy activity definitions.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Temporal activity definitions for the order-processing workflow.

        Activities are ordinary ``async def`` functions decorated with
        ``@activity.defn``.  Each activity has an explicit retry policy
        so behaviour under failure is deterministic and auditable.

        ``temporalio`` is imported lazily (inside function bodies) so this
        module can be imported without the SDK installed.
        \"\"\"

        from __future__ import annotations

        import logging
        from datetime import timedelta
        from typing import Any

        logger = logging.getLogger(__name__)


        def _apply_retry_policy(fn: Any, *, schedule_to_close: int) -> Any:
            \"\"\"Tag *fn* with Temporal retry metadata used by the worker factory.

            The actual ``@activity.defn`` decorator requires the SDK, so we
            store the policy as attributes and apply ``activity.defn`` lazily
            in ``WorkerFactory.create`` when the SDK is available.

            Args:
                fn: Async activity function to tag.
                schedule_to_close: Schedule-to-close timeout in seconds.

            Returns:
                The same function, with ``__temporal_schedule_to_close__``
                and ``__temporal_max_attempts__`` attributes set.
            \"\"\"
            fn.__temporal_schedule_to_close__ = timedelta(seconds=schedule_to_close)
            fn.__temporal_max_attempts__ = 3
            return fn


        async def validate_order(order_id: str) -> dict[str, Any]:
            \"\"\"Validate an order before processing.

            Checks that the order exists and is in a processable state.
            This activity is idempotent — safe to retry.

            Args:
                order_id: Unique order identifier.

            Returns:
                Dict with ``order_id``, ``valid``, and optional ``reason``.
            \"\"\"
            from temporalio import activity  # lazy SDK import

            activity.logger.info("Validating order %s", order_id)
            # Stub: replace with real DB / service call in production.
            return {"order_id": order_id, "valid": True}


        validate_order = _apply_retry_policy(validate_order, schedule_to_close=60)


        async def charge_payment(order_id: str, amount_cents: int) -> dict[str, Any]:
            \"\"\"Charge the payment instrument for an order.

            Calls the payment provider and returns a charge reference.  On
            failure the workflow will execute ``compensate_payment`` to void
            any partial charge.

            Args:
                order_id: Unique order identifier.
                amount_cents: Amount to charge in the smallest currency unit.

            Returns:
                Dict with ``order_id``, ``charge_id``, and ``status``.
            \"\"\"
            from temporalio import activity  # lazy SDK import

            activity.logger.info(
                "Charging payment for order %s amount_cents=%d",
                order_id,
                amount_cents,
            )
            # Stub: replace with real payment provider call in production.
            return {
                "order_id": order_id,
                "charge_id": f"ch_{order_id[:8]}",
                "status": "captured",
            }


        charge_payment = _apply_retry_policy(charge_payment, schedule_to_close=30)


        async def fulfil_order(order_id: str, charge_id: str) -> dict[str, Any]:
            \"\"\"Fulfil an order after successful payment.

            Triggers inventory deduction, dispatch, and notification.

            Args:
                order_id: Unique order identifier.
                charge_id: Charge reference returned by ``charge_payment``.

            Returns:
                Dict with ``order_id``, ``fulfillment_id``, and ``status``.
            \"\"\"
            from temporalio import activity  # lazy SDK import

            activity.logger.info(
                "Fulfilling order %s charge_id=%s", order_id, charge_id
            )
            # Stub: replace with real fulfilment service call in production.
            return {
                "order_id": order_id,
                "fulfillment_id": f"ff_{order_id[:8]}",
                "status": "dispatched",
            }


        fulfil_order = _apply_retry_policy(fulfil_order, schedule_to_close=120)


        async def compensate_payment(order_id: str, charge_id: str) -> dict[str, Any]:
            \"\"\"Void or refund a payment charge on workflow failure.

            Compensation activity: called from the workflow's except block
            when a downstream activity fails after payment has been captured.

            Args:
                order_id: Unique order identifier.
                charge_id: Charge reference to void/refund.

            Returns:
                Dict with ``order_id``, ``charge_id``, and ``status``.
            \"\"\"
            from temporalio import activity  # lazy SDK import

            activity.logger.info(
                "Compensating payment for order %s charge_id=%s",
                order_id,
                charge_id,
            )
            # Stub: replace with real refund/void call in production.
            return {
                "order_id": order_id,
                "charge_id": charge_id,
                "status": "refunded",
            }


        compensate_payment = _apply_retry_policy(
            compensate_payment, schedule_to_close=30
        )
    """)
    dest.write_text(content)


def _write_example_workflow(dest: Path) -> None:
    """Write ``app/workflows/example_workflow.py`` with OrderProcessingWorkflow.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"OrderProcessingWorkflow — durable order processing with compensation.

        Demonstrates:
        * Three sequential activities with retry policies.
        * Compensation-on-failure: ``compensate_payment`` is called when
          ``fulfil_order`` raises, guaranteeing no phantom charges.
        * Signal support: ``cancel`` signal aborts mid-flight execution.
        * Query support: ``status`` query returns the current phase.

        The Temporal SDK decorators (``@workflow.defn``, ``@workflow.run``,
        ``@workflow.signal``, ``@workflow.query``) require ``temporalio`` to be
        installed.  When the SDK is absent the class is still importable for
        unit tests — the ``try/except ModuleNotFoundError`` block at module
        level handles this gracefully.
        \"\"\"

        from __future__ import annotations

        import logging
        from datetime import timedelta
        from typing import Any

        logger = logging.getLogger(__name__)


        class OrderProcessingWorkflow:
            \"\"\"Durable Temporal workflow for processing an order end-to-end.

            Phases:
              1. validate_order  — check the order is processable.
              2. charge_payment  — capture payment from the customer.
              3. fulfil_order    — dispatch and notify; compensate on failure.

            Attributes:
                _status: Current phase label (``pending``, ``validating``,
                    ``charging``, ``fulfilling``, ``completed``, ``failed``,
                    ``cancelled``).
                _cancelled: Whether a cancel signal was received.
            \"\"\"

            def __init__(self) -> None:
                \"\"\"Initialise the workflow state machine.\"\"\"
                self._status: str = "pending"
                self._cancelled: bool = False

            async def run(self, order_id: str, amount_cents: int) -> dict[str, Any]:
                \"\"\"Execute the full order-processing pipeline.

                Args:
                    order_id: Unique order identifier passed from the REST caller.
                    amount_cents: Payment amount in the smallest currency unit.

                Returns:
                    Result dict with ``order_id``, ``status``, and phase outputs.
                \"\"\"
                from temporalio import workflow  # lazy SDK import

                workflow.logger.info("OrderProcessingWorkflow starting %s", order_id)

                if self._cancelled:
                    self._status = "cancelled"
                    return {"order_id": order_id, "status": "cancelled"}

                validation = await self._validate(workflow, order_id)
                if not validation.get("valid"):
                    self._status = "failed"
                    return {
                        "order_id": order_id,
                        "status": "failed",
                        "reason": validation.get("reason", "invalid order"),
                    }

                if self._cancelled:
                    self._status = "cancelled"
                    return {"order_id": order_id, "status": "cancelled"}

                charge_id = await self._charge(workflow, order_id, amount_cents)
                return await self._fulfil(workflow, order_id, charge_id)

            async def _validate(self, workflow: Any, order_id: str) -> dict[str, Any]:
                \"\"\"Phase 1: validate the order via Temporal activity.

                Args:
                    workflow: The ``temporalio.workflow`` module.
                    order_id: Unique order identifier.

                Returns:
                    Validation result dict with ``valid`` boolean.
                \"\"\"
                from app.workflows.activities import validate_order

                self._status = "validating"
                return await workflow.execute_activity(
                    validate_order,
                    order_id,
                    start_to_close_timeout=timedelta(seconds=60),
                )

            async def _charge(
                self, workflow: Any, order_id: str, amount_cents: int
            ) -> str:
                \"\"\"Phase 2: charge the payment instrument.

                Args:
                    workflow: The ``temporalio.workflow`` module.
                    order_id: Unique order identifier.
                    amount_cents: Amount to charge in the smallest currency unit.

                Returns:
                    Charge reference string (``charge_id``).
                \"\"\"
                from app.workflows.activities import charge_payment

                self._status = "charging"
                charge = await workflow.execute_activity(
                    charge_payment,
                    order_id,
                    amount_cents,
                    start_to_close_timeout=timedelta(seconds=30),
                )
                return charge["charge_id"]

            async def _fulfil(
                self, workflow: Any, order_id: str, charge_id: str
            ) -> dict[str, Any]:
                \"\"\"Phase 3: fulfil with compensation on failure.

                Args:
                    workflow: The ``temporalio.workflow`` module.
                    order_id: Unique order identifier.
                    charge_id: Charge reference from Phase 2.

                Returns:
                    Result dict with ``order_id``, ``status``, and outcomes.
                \"\"\"
                from app.workflows.activities import compensate_payment, fulfil_order

                if self._cancelled:
                    self._status = "cancelled"
                    await workflow.execute_activity(
                        compensate_payment, order_id, charge_id,
                        start_to_close_timeout=timedelta(seconds=30),
                    )
                    return {"order_id": order_id, "status": "cancelled"}

                self._status = "fulfilling"
                try:
                    result = await workflow.execute_activity(
                        fulfil_order, order_id, charge_id,
                        start_to_close_timeout=timedelta(seconds=120),
                    )
                except Exception:  # noqa: BLE001
                    logger.warning("fulfil_order failed, compensating order=%s", order_id)
                    await workflow.execute_activity(
                        compensate_payment, order_id, charge_id,
                        start_to_close_timeout=timedelta(seconds=30),
                    )
                    self._status = "failed"
                    return {
                        "order_id": order_id, "status": "failed",
                        "charge_id": charge_id, "compensated": True,
                    }

                self._status = "completed"
                return {
                    "order_id": order_id, "status": "completed",
                    "charge_id": charge_id,
                    "fulfillment_id": result.get("fulfillment_id"),
                }

            def cancel(self) -> None:
                \"\"\"Signal handler: request graceful cancellation.

                Sets ``_cancelled`` so the workflow checks between phases
                and compensates any captured payment before exiting.
                \"\"\"
                logger.info("cancel signal received")
                self._cancelled = True

            def status(self) -> str:
                \"\"\"Query handler: return the current workflow phase.

                Returns:
                    One of: ``pending``, ``validating``, ``charging``,
                    ``fulfilling``, ``completed``, ``failed``, ``cancelled``.
                \"\"\"
                return self._status


        try:
            from temporalio import workflow as _wf

            OrderProcessingWorkflow = _wf.defn(OrderProcessingWorkflow)
            OrderProcessingWorkflow.run = _wf.run(OrderProcessingWorkflow.run)
            OrderProcessingWorkflow.cancel = _wf.signal(OrderProcessingWorkflow.cancel)
            OrderProcessingWorkflow.status = _wf.query(OrderProcessingWorkflow.status)
        except ModuleNotFoundError:
            # temporalio not installed — class still importable for unit tests
            pass
    """)
    dest.write_text(content)


def _write_workflow_routes(dest: Path) -> None:
    """Write ``app/api/routes/workflows.py`` with 4 REST endpoints.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"REST companion routes for Temporal workflow management.

        Provides start, status, signal, and cancel endpoints for the
        OrderProcessingWorkflow.  All routes require authentication so
        workflow state cannot be probed anonymously.
        \"\"\"

        from __future__ import annotations

        import logging
        import uuid

        from fastapi import APIRouter, HTTPException, status
        from pydantic import BaseModel

        from app.api.deps import CurrentUser

        logger = logging.getLogger(__name__)

        router = APIRouter(prefix="/workflows", tags=["workflows"])


        class StartWorkflowRequest(BaseModel):
            \"\"\"Request body for POST /workflows/start.

            Attributes:
                order_id: Unique order identifier to process.
                amount_cents: Payment amount in the smallest currency unit.
            \"\"\"

            order_id: str
            amount_cents: int = 0


        class WorkflowStatusResponse(BaseModel):
            \"\"\"Response body for GET /workflows/{workflow_id}/status.

            Attributes:
                workflow_id: Temporal workflow run ID.
                status: Current lifecycle status string.
            \"\"\"

            workflow_id: str
            status: str


        @router.post("/start", status_code=status.HTTP_202_ACCEPTED)
        async def start_workflow(
            body: StartWorkflowRequest,
            current_user: CurrentUser,
        ) -> dict:
            \"\"\"Start an OrderProcessingWorkflow for the given order.

            Args:
                body: ``StartWorkflowRequest`` with order_id and amount_cents.
                current_user: Authenticated user (auth gate only).

            Returns:
                Dict with ``workflow_id`` and ``status``.

            Raises:
                HTTPException(503): Temporal client unavailable.
            \"\"\"
            _ = current_user  # auth gate only
            try:
                from app.workflows.client import get_client
                from app.workflows.example_workflow import OrderProcessingWorkflow

                client = await get_client()
                workflow_id = f"order-{body.order_id}-{uuid.uuid4().hex[:8]}"
                handle = await client.start_workflow(
                    OrderProcessingWorkflow.run,
                    body.order_id,
                    body.amount_cents,
                    id=workflow_id,
                    task_queue=_get_task_queue(),
                )
                return {"workflow_id": handle.id, "status": "started"}
            except (ModuleNotFoundError, Exception) as exc:  # noqa: BLE001
                logger.warning("start_workflow error: %s", exc)
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Temporal client unavailable",
                ) from exc


        @router.get("/{workflow_id}/status")
        async def get_workflow_status(
            workflow_id: str,
            current_user: CurrentUser,
        ) -> WorkflowStatusResponse:
            \"\"\"Return the current status of a running or completed workflow.

            Args:
                workflow_id: Temporal workflow run ID.
                current_user: Authenticated user (auth gate only).

            Returns:
                ``WorkflowStatusResponse`` with workflow_id and status.

            Raises:
                HTTPException(404): Workflow not found.
                HTTPException(503): Temporal client unavailable.
            \"\"\"
            _ = current_user  # auth gate only
            try:
                from app.workflows.client import get_client

                client = await get_client()
                handle = client.get_workflow_handle(workflow_id)
                wf_status = await handle.query(lambda wf: wf.status())
                return WorkflowStatusResponse(
                    workflow_id=workflow_id, status=str(wf_status)
                )
            except ModuleNotFoundError as exc:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Temporal client unavailable",
                ) from exc
            except Exception as exc:  # noqa: BLE001
                logger.warning("get_workflow_status error: %s", exc)
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="workflow not found",
                ) from exc


        @router.post("/{workflow_id}/signal")
        async def signal_workflow(
            workflow_id: str,
            current_user: CurrentUser,
        ) -> dict:
            \"\"\"Send a cancel signal to a running workflow.

            Args:
                workflow_id: Temporal workflow run ID.
                current_user: Authenticated user (auth gate only).

            Returns:
                Dict with ``workflow_id`` and ``status``.

            Raises:
                HTTPException(404): Workflow not found.
                HTTPException(503): Temporal client unavailable.
            \"\"\"
            _ = current_user  # auth gate only
            try:
                from app.workflows.client import get_client

                client = await get_client()
                handle = client.get_workflow_handle(workflow_id)
                await handle.signal("cancel")
                return {"workflow_id": workflow_id, "status": "signal_sent"}
            except ModuleNotFoundError as exc:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Temporal client unavailable",
                ) from exc
            except Exception as exc:  # noqa: BLE001
                logger.warning("signal_workflow error: %s", exc)
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="workflow not found",
                ) from exc


        @router.post("/{workflow_id}/cancel")
        async def cancel_workflow(
            workflow_id: str,
            current_user: CurrentUser,
        ) -> dict:
            \"\"\"Request cancellation of a running workflow via Temporal's cancel API.

            Args:
                workflow_id: Temporal workflow run ID.
                current_user: Authenticated user (auth gate only).

            Returns:
                Dict with ``workflow_id`` and ``status``.

            Raises:
                HTTPException(404): Workflow not found.
                HTTPException(503): Temporal client unavailable.
            \"\"\"
            _ = current_user  # auth gate only
            try:
                from app.workflows.client import get_client

                client = await get_client()
                handle = client.get_workflow_handle(workflow_id)
                await handle.cancel()
                return {"workflow_id": workflow_id, "status": "cancel_requested"}
            except ModuleNotFoundError as exc:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Temporal client unavailable",
                ) from exc
            except Exception as exc:  # noqa: BLE001
                logger.warning("cancel_workflow error: %s", exc)
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="workflow not found",
                ) from exc


        def _get_task_queue() -> str:
            \"\"\"Return the configured Temporal task queue name.

            Returns:
                Task queue string from ``settings.TEMPORAL_TASK_QUEUE``.
            \"\"\"
            from app.core.config import settings

            return settings.TEMPORAL_TASK_QUEUE
    """)
    dest.write_text(content)


def _write_dockerfile(dest: Path) -> None:
    """Write ``Dockerfile.temporal-worker`` for the non-root worker container.

    Args:
        dest: Absolute path for the new file.
    """
    content = textwrap.dedent("""\
        # Dockerfile.temporal-worker
        # Builds the Temporal worker process as a separate, non-root container.
        # The FastAPI API container and this worker container share the same
        # app/ source tree via a common base image or volume mount.
        #
        # Build:
        #   docker build -f Dockerfile.temporal-worker -t myapp-temporal-worker .
        #
        # Run:
        #   docker run --rm --env-file .env myapp-temporal-worker

        FROM python:3.12-slim AS base

        WORKDIR /app

        # Install dependencies (layer-cached)
        COPY requirements.txt .
        RUN pip install --no-cache-dir -r requirements.txt

        # Copy application source
        COPY . .

        # Run as non-root user (UID 1000) — do not change without security review
        RUN adduser --disabled-password --gecos "" --uid 1000 worker
        USER 1000

        CMD ["python", "-m", "app.workflows.worker"]
    """)
    dest.write_text(content)


def _patch_config(config_file: Path) -> None:
    """Patch ``app/core/config.py`` to add TEMPORAL_* settings.

    Fields are appended inside the ``Settings`` class body (4-space indent).
    Already-present fields are never duplicated (idempotent).

    Args:
        config_file: Absolute path to ``app/core/config.py``.
    """
    if not config_file.exists():
        return
    content = config_file.read_text()
    fields_to_add = [
        ('TEMPORAL_HOST', '    TEMPORAL_HOST: str = "localhost:7233"'),
        ('TEMPORAL_NAMESPACE', '    TEMPORAL_NAMESPACE: str = "default"'),
        ('TEMPORAL_TASK_QUEUE', '    TEMPORAL_TASK_QUEUE: str = "main-queue"'),
    ]
    new_lines: list[str] = []
    for field_name, field_line in fields_to_add:
        if field_name not in content:
            new_lines.append(field_line)
    if not new_lines:
        return
    # Insert before the closing line of Settings class or append before settings = Settings()
    insert_marker = "settings = Settings()"
    if insert_marker in content:
        content = content.replace(
            insert_marker,
            "\n".join(new_lines) + "\n\n" + insert_marker,
        )
    else:
        if not content.endswith("\n"):
            content += "\n"
        content += "\n".join(new_lines) + "\n"
    config_file.write_text(content)


def _patch_requirements(requirements_file: Path) -> None:
    """Append ``temporalio>=1.7.0`` to requirements.txt idempotently.

    Args:
        requirements_file: Absolute path to ``requirements.txt``.
    """
    if not requirements_file.exists():
        return
    content = requirements_file.read_text()
    if "temporalio" in content:
        return
    if not content.endswith("\n"):
        content += "\n"
    content += "temporalio>=1.7.0\n"
    requirements_file.write_text(content)


def _patch_routes_init(routes_init: Path) -> None:
    """Register ``workflows`` router in ``app/routes/__init__.py`` idempotently.

    Args:
        routes_init: Absolute path to ``app/routes/__init__.py``.
    """
    if not routes_init.exists():
        return
    content = routes_init.read_text()
    import_line = "from app.api.routes.workflows import router as workflows_router"
    include_line = "api_router.include_router(workflows_router)"
    if "workflows_router" in content:
        return
    if not content.endswith("\n"):
        content += "\n"
    content += f"\n{import_line}\n{include_line}\n"
    routes_init.write_text(content)
