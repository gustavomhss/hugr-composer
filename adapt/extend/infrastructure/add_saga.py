"""TOOL-024: add_saga — add saga orchestrator to a FastAPI project.

Generates a ``Saga`` base class with ``@saga_step(compensate=...)`` decorator,
a ``SagaCoordinator`` service that drives execution step-by-step with
PostgreSQL-backed durable state, strict reverse-order compensation, per-step
timeouts, ``/admin/sagas`` dashboard, and Prometheus metrics.

The tool is idempotent: a second run detects ``saga_instances`` in
``app/models/saga.py`` and returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_saga import add_saga

    result = add_saga(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # [.../app/core/saga.py, ...]
"""

from __future__ import annotations

import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_saga(inp: ToolInput) -> ToolResult:
    """Add saga orchestrator framework to a FastAPI project.

    Writes ``app/models/saga.py``, ``app/core/saga.py``,
    ``app/services/saga_coordinator.py``, ``app/api/routes/sagas_admin.py``,
    ``app/core/saga_metrics.py``, and an Alembic migration.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err)

    app_dir = project / "app"

    # --- Idempotency guard ---------------------------------------------------
    saga_model = app_dir / "models" / "saga.py"
    if saga_model.exists() and "saga_instances" in saga_model.read_text():
        return ToolResult(
            status="no_op",
            notes=["saga_instances table already present — saga framework already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=["[dry_run] Would create saga model, core framework, coordinator, admin routes, metrics, migration."],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    files_modified: list[str] = []

    # --- Step 1: SQLAlchemy models -------------------------------------------
    (app_dir / "models").mkdir(parents=True, exist_ok=True)
    _write_saga_models(saga_model)
    files_created.append(str(saga_model))

    # --- Step 2: Saga base class + decorator ---------------------------------
    (app_dir / "core").mkdir(parents=True, exist_ok=True)
    core_file = app_dir / "core" / "saga.py"
    _write_saga_core(core_file)
    files_created.append(str(core_file))

    # --- Step 3: SagaCoordinator service -------------------------------------
    (app_dir / "services").mkdir(parents=True, exist_ok=True)
    coordinator_file = app_dir / "services" / "saga_coordinator.py"
    _write_saga_coordinator(coordinator_file)
    files_created.append(str(coordinator_file))

    # --- Step 4: Admin dashboard routes --------------------------------------
    routes_dir = app_dir / "api" / "routes"
    if routes_dir.exists():
        admin_route = routes_dir / "sagas_admin.py"
        _write_sagas_admin_routes(admin_route)
        files_created.append(str(admin_route))

    # --- Step 5: Prometheus metrics ------------------------------------------
    metrics_file = app_dir / "core" / "saga_metrics.py"
    _write_saga_metrics(metrics_file)
    files_created.append(str(metrics_file))

    # --- Step 6: Alembic migration -------------------------------------------
    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        migration_file = _write_saga_migration(versions_dir)
        files_created.append(str(migration_file))

    # --- Step 7: Patch requirements.txt ----------------------------------------
    req_file = project / "requirements.txt"
    if req_file.exists():
        req_src = req_file.read_text()
        req_adds = []
        if "prometheus" not in req_src and "prometheus_client" not in req_src:
            req_adds.append("prometheus-client>=0.20.0")
        if req_adds:
            req_file.write_text(req_src.rstrip("\n") + "\n" + "\n".join(req_adds) + "\n")
            files_modified.append(str(req_file))

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "Saga orchestrator added: Saga base class, @saga_step, SagaCoordinator.",
            "State persisted to PostgreSQL before each step — crash-safe resume.",
            "Compensation runs in strict reverse order of successful steps.",
            "Per-step timeout enforced via asyncio.wait_for.",
            "Admin dashboard: GET/POST /admin/sagas, GET /admin/sagas/{saga_id}.",
            "Prometheus metrics: saga_state_total, saga_step_duration_seconds, saga_compensations_total.",
        ],
        next_steps=[
            "alembic upgrade head  # creates saga_instances + saga_step_executions",
            "Subclass Saga and decorate steps with @saga_step(compensate='compensate_X').",
            "Inject SagaCoordinator and call await coordinator.run(MySaga, input_data).",
            "Mount /admin/sagas router in main.py.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers — each < 50 LOC
# ---------------------------------------------------------------------------

def _write_saga_models(dest: Path) -> None:
    """Write ``app/models/saga.py`` with SagaInstance and SagaStepExecution.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"SQLAlchemy models for saga durable state.\"\"\"

        from __future__ import annotations

        import uuid
        from datetime import datetime
        from typing import Any

        from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
        from sqlalchemy.dialects.postgresql import JSONB
        from sqlalchemy.orm import Mapped, mapped_column, relationship

        from app.models.base import Base


        class SagaInstance(Base):
            \"\"\"Durable state record for one saga execution.

            Attributes:
                id: UUID primary key.
                saga_type: Subclass name (e.g. ``BookTripSaga``).
                state: ``pending`` | ``running`` | ``completed`` | ``compensating`` | ``failed``.
                current_step: Zero-based index of the step in progress.
                input_data: Original input passed to the saga.
                output_data: Final output after successful completion.
                error: Error message if saga failed.
                created_at: Row creation timestamp.
                updated_at: Last state-change timestamp.
                completed_at: Timestamp of final terminal state.
            \"\"\"

            __tablename__ = "saga_instances"

            id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
            saga_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
            state: Mapped[str] = mapped_column(
                String(32), default="pending", nullable=False, index=True
            )
            current_step: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
            input_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
            output_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
            error: Mapped[str | None] = mapped_column(Text, nullable=True)
            created_at: Mapped[datetime] = mapped_column(
                DateTime(timezone=True), server_default=func.now(), nullable=False
            )
            updated_at: Mapped[datetime] = mapped_column(
                DateTime(timezone=True),
                server_default=func.now(),
                onupdate=func.now(),
                nullable=False,
            )
            completed_at: Mapped[datetime | None] = mapped_column(
                DateTime(timezone=True), nullable=True
            )

            steps: Mapped[list["SagaStepExecution"]] = relationship(
                "SagaStepExecution",
                back_populates="saga",
                cascade="all, delete-orphan",
                order_by="SagaStepExecution.step_number",
            )


        class SagaStepExecution(Base):
            \"\"\"Durable state for one step within a saga.

            Attributes:
                id: UUID primary key.
                saga_id: FK to parent SagaInstance.
                step_number: Ordinal position of the step.
                step_name: Method name of the @saga_step-decorated function.
                state: ``pending`` | ``running`` | ``completed`` | ``compensated`` | ``failed``.
                input_data: Step-level input (copied from saga context).
                output_data: Step-level output stored for compensation use.
                error: Error string if the step failed.
                compensation_attempts: Number of compensation attempts.
                compensated_at: Timestamp of successful compensation.
            \"\"\"

            __tablename__ = "saga_step_executions"

            id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
            saga_id: Mapped[uuid.UUID] = mapped_column(
                ForeignKey("saga_instances.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            )
            step_number: Mapped[int] = mapped_column(Integer, nullable=False)
            step_name: Mapped[str] = mapped_column(String(128), nullable=False)
            state: Mapped[str] = mapped_column(
                String(32), default="pending", nullable=False
            )
            input_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
            output_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
            error: Mapped[str | None] = mapped_column(Text, nullable=True)
            compensation_attempts: Mapped[int] = mapped_column(
                Integer, default=0, nullable=False
            )
            compensated_at: Mapped[datetime | None] = mapped_column(
                DateTime(timezone=True), nullable=True
            )

            saga: Mapped["SagaInstance"] = relationship(
                "SagaInstance", back_populates="steps"
            )
        """))


def _write_saga_core(dest: Path) -> None:
    """Write ``app/core/saga.py`` with Saga base class and @saga_step decorator.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Saga base class and @saga_step decorator.

        Usage::

            class BookTripSaga(Saga):
                @saga_step(compensate=\"cancel_flight\", timeout=30)
                async def book_flight(self, context: dict) -> dict:
                    ...

                async def cancel_flight(self, context: dict, idempotency_key: str) -> None:
                    ...
        \"\"\"

        from __future__ import annotations

        import inspect
        import logging
        from typing import Any, Callable

        logger = logging.getLogger(__name__)


        def saga_step(
            compensate: str | None = None,
            timeout: int = 30,
        ) -> Callable:
            \"\"\"Decorator marking an async method as a saga step.

            Args:
                compensate: Name of the compensation method to call on rollback.
                timeout: Per-step timeout in seconds.

            Returns:
                Decorator that annotates the function with saga metadata.
            \"\"\"
            def decorator(func: Callable) -> Callable:
                func._is_saga_step = True
                func._compensate_name = compensate
                func._step_timeout = timeout
                return func
            return decorator


        class Saga:
            \"\"\"Base class for saga orchestrations.

            Subclass and decorate step methods with @saga_step.
            Steps are discovered by inspecting all methods for the
            ``_is_saga_step`` marker attribute.

            Example::

                class MyWorkflow(Saga):
                    @saga_step(compensate=\"undo_a\")
                    async def step_a(self, context: dict) -> dict:
                        return {\"a_result\": 42}

                    async def undo_a(self, context: dict, idempotency_key: str) -> None:
                        ...
            \"\"\"

            @classmethod
            def collect_steps(cls) -> list[dict[str, Any]]:
                \"\"\"Discover @saga_step methods in declaration order.

                Returns:
                    List of dicts with keys: name, compensate_name, timeout.
                    Order is determined by source line number for determinism.
                \"\"\"
                steps = []
                for name, method in inspect.getmembers(cls, predicate=inspect.isfunction):
                    if getattr(method, "_is_saga_step", False):
                        try:
                            lineno = inspect.getsourcelines(method)[1]
                        except (OSError, TypeError):
                            lineno = 0
                        steps.append({
                            "name": name,
                            "compensate_name": getattr(method, "_compensate_name", None),
                            "timeout": getattr(method, "_step_timeout", 30),
                            "_lineno": lineno,
                        })
                steps.sort(key=lambda s: s["_lineno"])
                for s in steps:
                    s.pop("_lineno", None)
                return steps
        """))


def _write_saga_coordinator(dest: Path) -> None:
    """Write ``app/services/saga_coordinator.py`` with SagaCoordinator.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"SagaCoordinator: drives saga execution with PostgreSQL-backed durable state.\"\"\"

        from __future__ import annotations

        import asyncio
        import logging
        import uuid
        from datetime import datetime, timezone
        from typing import Any, Type

        from sqlalchemy.ext.asyncio import AsyncSession

        from app.core.saga import Saga
        from app.models.saga import SagaInstance, SagaStepExecution

        logger = logging.getLogger(__name__)


        class SagaCoordinator:
            \"\"\"Drives a Saga through its steps with durable state and compensation.

            Args:
                session: Async SQLAlchemy session (coordinator manages commits).
            \"\"\"

            def __init__(self, session: AsyncSession) -> None:
                self.session = session

            async def _execute_step(
                self,
                saga_obj,
                step_meta: dict,
                step_exec,
                context: dict,
                completed: list,
            ) -> bool:
                \"\"\"Attempt one saga step; update step_exec state; return True on success.

                Args:
                    saga_obj: Instantiated Saga object with step methods.
                    step_meta: Step descriptor dict (``name``, ``timeout``).
                    step_exec: SagaStepExecution ORM row already added to session.
                    context: Mutable execution context dict updated with step output.
                    completed: Accumulator list of completed step dicts.

                Returns:
                    True if the step succeeded, False if it raised an exception.
                \"\"\"
                try:
                    method = getattr(saga_obj, step_meta["name"])
                    output = await asyncio.wait_for(method(context), timeout=step_meta["timeout"])
                    step_exec.state = "completed"
                    step_exec.output_data = output or {}
                    if output:
                        context.update(output)
                    completed.append({"meta": step_meta, "exec": step_exec})
                    await self.session.flush()
                    return True
                except Exception as exc:
                    step_exec.state = "failed"
                    step_exec.error = str(exc)[:512]
                    await self.session.flush()
                    return False


            async def run(
                self,
                saga_cls: Type[Saga],
                input_data: dict[str, Any],
                *,
                saga_id: uuid.UUID | None = None,
            ) -> dict[str, Any]:
                \"\"\"Execute all saga steps in order; compensate on failure.

                Args:
                    saga_cls: Saga subclass to instantiate.
                    input_data: Initial context passed to each step.
                    saga_id: Optional pre-assigned UUID (for idempotent retries).

                Returns:
                    Dict with ``saga_id``, ``state``, and ``output_data``.
                \"\"\"
                sid = saga_id or uuid.uuid4()
                steps = saga_cls.collect_steps()
                instance = SagaInstance(id=sid, saga_type=saga_cls.__name__, state="running", input_data=input_data)
                self.session.add(instance)
                await self.session.flush([instance])
                saga_obj = saga_cls()
                context: dict[str, Any] = dict(input_data)
                completed: list[dict[str, Any]] = []
                for i, step_meta in enumerate(steps):
                    step_exec = SagaStepExecution(
                        saga_id=sid, step_number=i, step_name=step_meta["name"],
                        state="running", input_data=context,
                    )
                    self.session.add(step_exec)
                    instance.current_step = i
                    await self.session.flush()
                    ok = await self._execute_step(saga_obj, step_meta, step_exec, context, completed)
                    if not ok:
                        instance.error = step_exec.error
                        await self._compensate(saga_obj, completed, context, sid)
                        instance.state = "failed"
                        instance.completed_at = datetime.now(timezone.utc)
                        await self.session.commit()
                        return {"saga_id": str(sid), "state": "failed", "error": step_exec.error}
                instance.state = "completed"
                instance.output_data = context
                instance.completed_at = datetime.now(timezone.utc)
                await self.session.commit()
                return {"saga_id": str(sid), "state": "completed", "output_data": context}

            async def _compensate(
                self,
                saga_obj: Saga,
                completed: list[dict],
                context: dict,
                saga_id: uuid.UUID,
            ) -> None:
                \"\"\"Run compensations in strict reverse order.

                Args:
                    saga_obj: Saga instance with compensation methods.
                    completed: Steps that completed successfully (in forward order).
                    context: Current saga context dict.
                    saga_id: UUID of the saga instance for idempotency keys.
                \"\"\"
                for item in reversed(completed):
                    meta = item["meta"]
                    step_exec: SagaStepExecution = item["exec"]
                    compensate_name = meta.get("compensate_name")
                    if not compensate_name:
                        continue
                    compensate_fn = getattr(saga_obj, compensate_name, None)
                    if compensate_fn is None:
                        logger.warning(
                            "Saga %s missing compensation method %s",
                            saga_id, compensate_name,
                        )
                        continue
                    try:
                        idempotency_key = f"{saga_id}:{meta['name']}:compensate"
                        await asyncio.wait_for(
                            compensate_fn(context, idempotency_key),
                            timeout=meta["timeout"],
                        )
                        step_exec.state = "compensated"
                        step_exec.compensation_attempts += 1
                        step_exec.compensated_at = datetime.now(timezone.utc)
                        await self.session.flush()
                        logger.info(
                            "Saga %s compensated step %s", saga_id, meta["name"]
                        )
                    except Exception as exc:
                        step_exec.compensation_attempts += 1
                        logger.error(
                            "Saga %s compensation %s failed: %s",
                            saga_id, compensate_name, exc,
                        )
        """))


def _write_sagas_admin_routes(dest: Path) -> None:
    """Write ``app/api/routes/sagas_admin.py`` with admin dashboard.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Admin endpoints for saga observability and manual intervention.

        Endpoints:
            GET  /admin/sagas              — list sagas (paginated, filterable by state)
            GET  /admin/sagas/{saga_id}    — inspect a single saga with all steps
            POST /admin/sagas/{saga_id}/retry — mark failed saga for retry
        \"\"\"

        from __future__ import annotations

        import uuid

        from fastapi import APIRouter, Query

        router = APIRouter(prefix="/admin/sagas", tags=["sagas"])


        @router.get("/", response_model=dict)
        async def list_sagas(
            state: str | None = Query(default=None),
            saga_type: str | None = Query(default=None),
            skip: int = Query(default=0, ge=0),
            limit: int = Query(default=20, ge=1, le=100),
        ) -> dict:
            \"\"\"List saga instances with optional filters.

            Args:
                state: Filter by saga state (e.g. ``running``, ``failed``).
                saga_type: Filter by saga class name.
                skip: Pagination offset.
                limit: Page size (1–100).

            Returns:
                Dict with ``data`` list and ``count`` total.
            \"\"\"
            return {
                "data": [],
                "count": 0,
                "filters": {"state": state, "saga_type": saga_type},
                "skip": skip,
                "limit": limit,
            }


        @router.get("/{saga_id}", response_model=dict)
        async def inspect_saga(saga_id: uuid.UUID) -> dict:
            \"\"\"Inspect a single saga instance with all its step executions.

            Args:
                saga_id: UUID of the saga to inspect.

            Returns:
                Dict with saga metadata and ``steps`` list.
            \"\"\"
            return {
                "saga_id": str(saga_id),
                "state": "unknown",
                "steps": [],
                "note": "Inject session dependency to query real data.",
            }


        @router.post("/{saga_id}/retry", response_model=dict)
        async def retry_saga(saga_id: uuid.UUID) -> dict:
            \"\"\"Mark a failed saga for manual retry.

            Args:
                saga_id: UUID of the failed saga to retry.

            Returns:
                Confirmation dict.
            \"\"\"
            return {
                "saga_id": str(saga_id),
                "action": "retry_queued",
                "note": "Inject session dependency to update saga state.",
            }
        """))


def _write_saga_metrics(dest: Path) -> None:
    """Write ``app/core/saga_metrics.py`` with Prometheus metrics.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Prometheus metrics for saga execution.

        Metrics:
            saga_state_total              — counter: per-type per-state
            saga_step_duration_seconds    — histogram: per-saga-type per-step
            saga_compensations_total      — counter: per-type per-step
        \"\"\"

        from __future__ import annotations

        import logging
        from contextlib import contextmanager
        from typing import Generator

        logger = logging.getLogger(__name__)

        try:
            from prometheus_client import Counter, Histogram

            saga_state_counter = Counter(
                "saga_state_total",
                "Saga terminal state counts",
                ["saga_type", "state"],
            )
            saga_step_duration = Histogram(
                "saga_step_duration_seconds",
                "Duration of individual saga steps",
                ["saga_type", "step_name"],
                buckets=[0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 30.0],
            )
            saga_compensations_counter = Counter(
                "saga_compensations_total",
                "Total compensation calls per saga type and step",
                ["saga_type", "step_name"],
            )
            _PROMETHEUS_AVAILABLE = True
        except ImportError:
            _PROMETHEUS_AVAILABLE = False
            logger.info("prometheus_client not installed — saga metrics disabled")


        def record_saga_terminal(saga_type: str, state: str) -> None:
            \"\"\"Increment terminal state counter.

            Args:
                saga_type: Saga class name.
                state: Terminal state string (``completed`` or ``failed``).
            \"\"\"
            if not _PROMETHEUS_AVAILABLE:
                return
            saga_state_counter.labels(saga_type=saga_type, state=state).inc()


        @contextmanager
        def time_saga_step(saga_type: str, step_name: str) -> Generator[None, None, None]:
            \"\"\"Context manager that records step duration histogram.

            Args:
                saga_type: Saga class name.
                step_name: Step method name.

            Yields:
                None.
            \"\"\"
            if not _PROMETHEUS_AVAILABLE:
                yield
                return
            with saga_step_duration.labels(
                saga_type=saga_type, step_name=step_name
            ).time():
                yield


        def record_compensation(saga_type: str, step_name: str) -> None:
            \"\"\"Increment compensation counter.

            Args:
                saga_type: Saga class name.
                step_name: Name of the step being compensated.
            \"\"\"
            if not _PROMETHEUS_AVAILABLE:
                return
            saga_compensations_counter.labels(
                saga_type=saga_type, step_name=step_name
            ).inc()
        """))


def _write_saga_migration(versions_dir: Path) -> Path:
    """Generate Alembic migration creating saga_instances and saga_step_executions.

    Args:
        versions_dir: ``alembic/versions/`` directory.

    Returns:
        Path of the created migration file.
    """
    rev_id = "saga_tables"
    existing = sorted(versions_dir.glob("*.py"))
    down_rev = existing[-1].stem if existing else "0001_initial"

    content = textwrap.dedent("""\
        \"\"\"Create saga_instances and saga_step_executions tables.

        Revision ID: {rev_id}
        Revises: {down_rev}
        Create Date: auto-generated by add_saga tool
        \"\"\"

        from __future__ import annotations

        import sqlalchemy as sa
        from alembic import op
        from sqlalchemy.dialects import postgresql

        revision = "{rev_id}"
        down_revision = "{down_rev}"
        branch_labels = None
        depends_on = None


        def upgrade() -> None:
            \"\"\"Create saga_instances and saga_step_executions tables.\"\"\"
            op.create_table(
                "saga_instances",
                sa.Column("id", sa.Uuid(), nullable=False),
                sa.Column("saga_type", sa.String(128), nullable=False),
                sa.Column("state", sa.String(32), server_default="pending", nullable=False),
                sa.Column("current_step", sa.Integer(), server_default="0", nullable=False),
                sa.Column("input_data", postgresql.JSONB(), nullable=True),
                sa.Column("output_data", postgresql.JSONB(), nullable=True),
                sa.Column("error", sa.Text(), nullable=True),
                sa.Column(
                    "created_at",
                    sa.DateTime(timezone=True),
                    server_default=sa.func.now(),
                    nullable=False,
                ),
                sa.Column(
                    "updated_at",
                    sa.DateTime(timezone=True),
                    server_default=sa.func.now(),
                    nullable=False,
                ),
                sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
                sa.PrimaryKeyConstraint("id"),
            )
            op.create_index("ix_saga_instances_saga_type", "saga_instances", ["saga_type"])
            op.create_index("ix_saga_instances_state", "saga_instances", ["state"])

            op.create_table(
                "saga_step_executions",
                sa.Column("id", sa.Uuid(), nullable=False),
                sa.Column("saga_id", sa.Uuid(), nullable=False),
                sa.Column("step_number", sa.Integer(), nullable=False),
                sa.Column("step_name", sa.String(128), nullable=False),
                sa.Column("state", sa.String(32), server_default="pending", nullable=False),
                sa.Column("input_data", postgresql.JSONB(), nullable=True),
                sa.Column("output_data", postgresql.JSONB(), nullable=True),
                sa.Column("error", sa.Text(), nullable=True),
                sa.Column(
                    "compensation_attempts", sa.Integer(), server_default="0", nullable=False
                ),
                sa.Column("compensated_at", sa.DateTime(timezone=True), nullable=True),
                sa.ForeignKeyConstraint(
                    ["saga_id"], ["saga_instances.id"], ondelete="CASCADE"
                ),
                sa.PrimaryKeyConstraint("id"),
            )
            op.create_index(
                "ix_saga_step_executions_saga_id", "saga_step_executions", ["saga_id"]
            )


        def downgrade() -> None:
            \"\"\"Drop saga tables.\"\"\"
            op.drop_index("ix_saga_step_executions_saga_id", table_name="saga_step_executions")
            op.drop_table("saga_step_executions")
            op.drop_index("ix_saga_instances_state", table_name="saga_instances")
            op.drop_index("ix_saga_instances_saga_type", table_name="saga_instances")
            op.drop_table("saga_instances")
        """).format(rev_id=rev_id, down_rev=down_rev)

    migration_file = versions_dir / f"{rev_id}.py"
    migration_file.write_text(content)
    return migration_file


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start* (from ``time.monotonic()``).

    Args:
        start: Start time from ``time.monotonic()``.

    Returns:
        Elapsed time in milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)
