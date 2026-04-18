"""TOOL-079: add_event_sourcing — add an event store with projections and replay to FastAPI.

Generates a production-grade event sourcing infrastructure: an append-only Event
model, EventStore (append, get_stream, get_all_since), Projector (project, rebuild),
Pydantic schemas, CRUD helpers, REST endpoints, and an Alembic migration.  Snapshots
are supported via a configurable EVENT_STORE_SNAPSHOT_INTERVAL setting.

The tool is idempotent: a second run detects ``EventStore`` in
``app/events/store.py`` and returns ``status="no_op"`` without touching any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.crud_data.add_event_sourcing import add_event_sourcing

    result = add_event_sourcing(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["app/events/__init__.py", ...]
    print(result.next_steps)    # ["alembic upgrade head", ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.migration_helper import find_migration_head


MCP_TOOL = {
    "name": "fastapi_add_event_sourcing",
    "description": "Add append-only event store with projections and replay.",
    "tags": ["extend", "crud_data"],
    "entry": "add_event_sourcing",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_event_sourcing(inp: ToolInput) -> ToolResult:
    """Add event sourcing infrastructure (event store + projections) to a FastAPI project.

    Generates Event model, EventStore, Projector, schemas, CRUD, routes, and
    an Alembic migration.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and
            optional ``dry_run`` flag.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err,
                          execution_time_ms=_elapsed_ms(start))

    # --- Prerequisite check (standalone mode) --------------------------------
    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.BASE_MODEL,
        Prereq.MODELS_INIT,
        Prereq.CONFIG_SETTINGS,
        Prereq.ROUTES_INIT,
        Prereq.ALEMBIC_VERSIONS,
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

    # --- Pre-flight: is event sourcing already enabled? ----------------------
    event_store_file = app_dir / "events" / "store.py"
    if event_store_file.exists() and "EventStore" in event_store_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["EventStore already present — event sourcing is already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would add event sourcing (EventStore, Projector, Event model).",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # --- Step 1: app/events/__init__.py ------------------------------------
    events_pkg = app_dir / "events" / "__init__.py"
    _write_events_init(events_pkg)
    files_created.append(str(events_pkg))

    # --- Step 2: app/events/models.py -------------------------------------
    event_model_file = app_dir / "events" / "models.py"
    _write_event_model_file(event_model_file)
    files_created.append(str(event_model_file))

    # --- Step 3: app/events/store.py --------------------------------------
    _write_event_store(event_store_file)
    files_created.append(str(event_store_file))

    # --- Step 4: app/events/projector.py ----------------------------------
    projector_file = app_dir / "events" / "projector.py"
    _write_projector(projector_file)
    files_created.append(str(projector_file))

    # --- Step 5: app/models/event.py  (ORM model) -------------------------
    orm_model_file = app_dir / "models" / "event.py"
    _write_orm_event_model(orm_model_file)
    files_created.append(str(orm_model_file))

    # Register model in app/models/__init__.py
    _patch_models_init(
        app_dir / "models" / "__init__.py",
        [("event", "Event")],
    )

    # --- Step 6: app/schemas/event.py -------------------------------------
    schema_file = app_dir / "schemas" / "event.py"
    _write_event_schema(schema_file)
    files_created.append(str(schema_file))

    # --- Step 7: app/crud/event.py ----------------------------------------
    crud_file = app_dir / "crud" / "event.py"
    _write_event_crud(crud_file)
    files_created.append(str(crud_file))

    # --- Step 8: app/api/routes/events.py ---------------------------------
    routes_file = app_dir / "api" / "routes" / "events.py"
    _write_event_routes(routes_file)
    files_created.append(str(routes_file))

    # --- Step 9: Register route in app/routes/__init__.py -----------------
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    # --- Step 10: Patch config.py with event sourcing settings ------------
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # --- Step 11: Alembic migration ---------------------------------------
    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        migration_file = _write_migration(versions_dir)
        files_created.append(str(migration_file))

    # --- ast.parse validation loop ----------------------------------------
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
            "Event model created (stream_id, event_type, data_json, version, created_at).",
            "EventStore: append (with optimistic concurrency), get_stream, get_all_since.",
            "Projector: project (apply one event), rebuild (replay full stream).",
            "Config: EVENT_STORE_SNAPSHOT_INTERVAL (default 100).",
            "Routes: append, get stream, rebuild projection — under /events/.",
        ],
        next_steps=[
            "alembic upgrade head",
            "Set EVENT_STORE_SNAPSHOT_INTERVAL in your .env to tune snapshot frequency.",
            "Implement handle_event() in your Projector subclass.",
            "Restart the application.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# Step helpers — each < 50 LOC
# ---------------------------------------------------------------------------

def _patch_models_init(models_init: Path, class_imports: list[tuple[str, str]]) -> None:
    """Append model imports to ``app/models/__init__.py`` idempotently.

    Args:
        models_init: Path to the models ``__init__.py``.
        class_imports: List of ``(module_stem, ClassName)`` tuples.
    """
    if not models_init.exists():
        return
    content = models_init.read_text()
    new_lines: list[str] = []
    for module, cls in class_imports:
        marker = f"from app.models.{module} import {cls}"
        if marker in content:
            continue
        new_lines.append(f"{marker}  # noqa: F401")
    if not new_lines:
        return
    if not content.endswith("\n"):
        content += "\n"
    content += "\n".join(new_lines) + "\n"
    models_init.write_text(content)


def _patch_routes_init(routes_init: Path) -> None:
    """Register events router in ``app/routes/__init__.py``.

    Args:
        routes_init: Path to the routes ``__init__.py``.
    """
    src = routes_init.read_text()
    if "events_router" in src:
        return
    addition = textwrap.dedent("""\

        # --- Event sourcing routes — added by add_event_sourcing tool ---
        from app.api.routes.events import router as events_router  # noqa: E402
        api_router.include_router(events_router)
        """)
    routes_init.write_text(src.rstrip("\n") + "\n" + addition)


def _patch_config(config_file: Path) -> None:
    """Inject event store settings into ``app/core/config.py``.

    Fields are inserted with 4-space indent so they land inside the Settings class body.

    Args:
        config_file: Path to the config module.
    """
    src = config_file.read_text()
    if "EVENT_STORE_SNAPSHOT_INTERVAL" in src:
        return
    fields = (
        "\n"
        "    # Event store settings\n"
        "    EVENT_STORE_SNAPSHOT_INTERVAL: int = 100\n"
    )
    if "settings = Settings()" in src:
        src = src.replace(
            "\nsettings = Settings()",
            fields + "\nsettings = Settings()",
        )
    else:
        src = src.rstrip("\n") + fields + "\n"
    config_file.write_text(src)


def _write_events_init(dest: Path) -> None:
    """Write ``app/events/__init__.py`` package marker.

    Args:
        dest: Destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Event sourcing package.

        Exposes EventStore for append-only event persistence and Projector
        for building read models from event streams.
        \"\"\"

        from app.events.projector import Projector
        from app.events.store import EventStore

        __all__ = ["EventStore", "Projector"]
        """))


def _write_event_model_file(dest: Path) -> None:
    """Write ``app/events/models.py`` with the in-package domain event dataclass.

    Args:
        dest: Destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Domain event dataclass used by EventStore and Projector.

        The ``DomainEvent`` dataclass is the in-memory representation of an event.
        The ``Event`` ORM model in ``app/models/event.py`` is the persistence layer.
        \"\"\"

        from __future__ import annotations

        import uuid
        from dataclasses import dataclass, field
        from datetime import datetime, timezone
        from typing import Any


        @dataclass
        class DomainEvent:
            \"\"\"An immutable domain event captured in the event store.

            Attributes:
                stream_id: Opaque ID grouping related events (e.g. aggregate ID).
                event_type: Discriminator string identifying the event kind.
                data: JSON-serialisable payload for this event.
                version: Sequence number within the stream (1-based).
                event_id: Unique UUID for this event instance.
                created_at: UTC timestamp when the event was recorded.
            \"\"\"

            stream_id: str
            event_type: str
            data: dict[str, Any] = field(default_factory=dict)
            version: int = 1
            event_id: uuid.UUID = field(default_factory=uuid.uuid4)
            created_at: datetime = field(
                default_factory=lambda: datetime.now(timezone.utc)
            )
        """))


def _write_event_store(dest: Path) -> None:
    """Write ``app/events/store.py`` with the EventStore class.

    Args:
        dest: Destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"EventStore — append-only event persistence with optimistic concurrency.

        Optimistic concurrency is enforced via the (stream_id, version) unique
        constraint at the database level.  Callers should pass the expected next
        version; a unique-constraint violation indicates a concurrent write conflict.
        \"\"\"

        from __future__ import annotations

        import logging
        import uuid
        from datetime import datetime
        from typing import Any

        from sqlalchemy import select
        from sqlalchemy.exc import IntegrityError
        from sqlalchemy.ext.asyncio import AsyncSession

        from app.events.models import DomainEvent
        from app.models.event import Event

        logger = logging.getLogger(__name__)


        class EventStore:
            \"\"\"Append-only store for domain events, keyed by stream_id.

            Each append is transactional and uses optimistic concurrency control.
            \"\"\"

            async def append(
                self,
                session: AsyncSession,
                stream_id: str,
                event_type: str,
                data: dict[str, Any],
                expected_version: int | None = None,
            ) -> DomainEvent:
                \"\"\"Append one event to a stream with optional concurrency guard.

                Args:
                    session: Async SQLAlchemy session.
                    stream_id: Opaque stream identifier (e.g. aggregate UUID).
                    event_type: Discriminator string for the event kind.
                    data: JSON-serialisable event payload.
                    expected_version: If provided, the next version must equal this
                        value; raises ValueError on conflict.

                Returns:
                    The persisted DomainEvent with auto-assigned version and created_at.

                Raises:
                    ValueError: On optimistic concurrency conflict.
                \"\"\"
                next_version = await self._next_version(session, stream_id)
                if expected_version is not None and next_version != expected_version:
                    raise ValueError(
                        f"Concurrency conflict on stream {stream_id}: "
                        f"expected version {expected_version}, got {next_version}"
                    )
                row = await self._insert_event(
                    session, stream_id, event_type, data, next_version
                )
                return _row_to_domain(row)

            async def _insert_event(
                self,
                session: AsyncSession,
                stream_id: str,
                event_type: str,
                data: dict[str, Any],
                version: int,
            ) -> "Event":
                \"\"\"Insert an Event row and commit, rolling back on IntegrityError.

                Args:
                    session: Async SQLAlchemy session.
                    stream_id: Target stream identifier.
                    event_type: Event discriminator string.
                    data: JSON-serialisable event payload.
                    version: Pre-computed version number for this event.

                Returns:
                    The committed Event ORM instance.

                Raises:
                    ValueError: If a unique-constraint violation indicates a conflict.
                \"\"\"
                row = Event(
                    id=uuid.uuid4(),
                    stream_id=stream_id,
                    event_type=event_type,
                    data_json=data,
                    version=version,
                )
                session.add(row)
                try:
                    await session.commit()
                    await session.refresh(row)
                except IntegrityError as exc:
                    await session.rollback()
                    raise ValueError(
                        f"Concurrency conflict appending to stream {stream_id}: {exc}"
                    ) from exc
                return row

            async def get_stream(
                self,
                session: AsyncSession,
                stream_id: str,
                from_version: int = 1,
            ) -> list[DomainEvent]:
                \"\"\"Return all events in a stream from a given version onward.

                Args:
                    session: Async SQLAlchemy session.
                    stream_id: Stream to query.
                    from_version: Minimum version to include (default 1 = full stream).

                Returns:
                    Ordered list of DomainEvent instances (oldest first).
                \"\"\"
                stmt = (
                    select(Event)
                    .where(
                        Event.stream_id == stream_id,
                        Event.version >= from_version,
                    )
                    .order_by(Event.version)
                )
                rows = (await session.execute(stmt)).scalars().all()
                return [_row_to_domain(r) for r in rows]

            async def get_all_since(
                self,
                session: AsyncSession,
                since: datetime,
                limit: int = 1000,
            ) -> list[DomainEvent]:
                \"\"\"Return all events created after a given UTC timestamp.

                Args:
                    session: Async SQLAlchemy session.
                    since: UTC datetime (exclusive lower bound).
                    limit: Maximum events to return.

                Returns:
                    Events ordered by created_at ascending.
                \"\"\"
                stmt = (
                    select(Event)
                    .where(Event.created_at > since)
                    .order_by(Event.created_at)
                    .limit(limit)
                )
                rows = (await session.execute(stmt)).scalars().all()
                return [_row_to_domain(r) for r in rows]

            async def _next_version(
                self, session: AsyncSession, stream_id: str
            ) -> int:
                \"\"\"Compute the next version number for a stream.

                Args:
                    session: Async SQLAlchemy session.
                    stream_id: Stream identifier.

                Returns:
                    Current max version + 1, or 1 if the stream is empty.
                \"\"\"
                stmt = (
                    select(Event.version)
                    .where(Event.stream_id == stream_id)
                    .order_by(Event.version.desc())
                    .limit(1)
                )
                result = await session.execute(stmt)
                current = result.scalar_one_or_none()
                return (current or 0) + 1


        def _row_to_domain(row: Event) -> DomainEvent:
            \"\"\"Convert an Event ORM row to a DomainEvent dataclass.

            Args:
                row: ORM Event instance.

            Returns:
                DomainEvent with all fields populated.
            \"\"\"
            return DomainEvent(
                stream_id=row.stream_id,
                event_type=row.event_type,
                data=row.data_json or {},
                version=row.version,
                event_id=row.id,
                created_at=row.created_at,
            )
        """))


def _write_projector(dest: Path) -> None:
    """Write ``app/events/projector.py`` with the Projector base class.

    Args:
        dest: Destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Projector — build read models by replaying event streams.

        Subclass Projector and implement ``handle_event`` to build a specific
        read model.  Call ``rebuild`` to replay a full stream from scratch.

        Snapshot support: when event count exceeds snapshot_interval the projector
        records a checkpoint via ``save_snapshot`` (no-op base implementation;
        subclasses override to persist to cache or DB).
        \"\"\"

        from __future__ import annotations

        import logging
        from typing import Any

        from sqlalchemy.ext.asyncio import AsyncSession

        from app.events.models import DomainEvent
        from app.events.store import EventStore

        logger = logging.getLogger(__name__)


        class Projector:
            \"\"\"Base class for event-sourced read model projectors.

            Subclass and implement ``handle_event`` and optionally ``save_snapshot``.

            Attributes:
                snapshot_interval: Number of events between snapshot checkpoints.
                _state: Mutable read model state dict (subclasses may customise).
            \"\"\"

            def __init__(self, snapshot_interval: int = 100) -> None:
                \"\"\"Initialise the projector.

                Args:
                    snapshot_interval: Events between automatic snapshot calls.
                \"\"\"
                self.snapshot_interval = snapshot_interval
                self._state: dict[str, Any] = {}

            def project(self, event: DomainEvent) -> None:
                \"\"\"Apply a single event to the projector state.

                Calls ``handle_event`` then triggers a snapshot if the interval
                has been reached.

                Args:
                    event: The domain event to apply.
                \"\"\"
                self.handle_event(event)
                if self.snapshot_interval > 0 and event.version % self.snapshot_interval == 0:
                    self.save_snapshot(event.stream_id, event.version, self._state)

            def handle_event(self, event: DomainEvent) -> None:
                \"\"\"Apply a domain event to the read model state.

                Override in subclasses to implement domain-specific projection logic.

                Args:
                    event: The domain event to apply.
                \"\"\"
                logger.debug(
                    "handle_event stream=%s type=%s version=%d (base no-op)",
                    event.stream_id, event.event_type, event.version,
                )

            def save_snapshot(
                self, stream_id: str, version: int, state: dict[str, Any]
            ) -> None:
                \"\"\"Persist a projection snapshot for fast catch-up on next load.

                Base implementation is a no-op.  Override to save to Redis/DB.

                Args:
                    stream_id: Stream identifier.
                    version: Event version at snapshot time.
                    state: Current projection state to persist.
                \"\"\"

            async def rebuild(
                self,
                session: AsyncSession,
                store: EventStore,
                stream_id: str,
            ) -> dict[str, Any]:
                \"\"\"Rebuild the read model by replaying all events in a stream.

                Resets internal state, fetches all events for the stream, and
                applies them in order via ``project``.

                Args:
                    session: Async SQLAlchemy session.
                    store: EventStore to fetch events from.
                    stream_id: Stream to replay.

                Returns:
                    Final projection state dict after full replay.
                \"\"\"
                self._state = {}
                events = await store.get_stream(session, stream_id)
                for event in events:
                    self.project(event)
                logger.info(
                    "rebuild complete stream=%s events=%d", stream_id, len(events)
                )
                return dict(self._state)
        """))


def _write_orm_event_model(dest: Path) -> None:
    """Write ``app/models/event.py`` with the Event ORM model.

    Args:
        dest: Destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Event ORM model — append-only event store table.

        Invariants enforced at the DB level:
        - (stream_id, version) unique index prevents version conflicts
        - created_at uses server default (cannot be forged by application code)
        \"\"\"

        from __future__ import annotations

        import uuid
        from datetime import datetime
        from typing import Any

        from sqlalchemy import DateTime, Index, Integer, String, Uuid, func
        from sqlalchemy import JSON
        from sqlalchemy.orm import Mapped, mapped_column

        from app.models.base import Base


        class Event(Base):
            \"\"\"Append-only event row in the event store.

            Attributes:
                id: UUID primary key (event_id).
                stream_id: Opaque aggregate/stream identifier.
                event_type: Discriminator string for the event kind.
                data_json: JSON payload for this event instance.
                version: Monotonically increasing sequence number within the stream.
                created_at: UTC timestamp (server default — immutable after insert).
            \"\"\"

            __tablename__ = "events"

            id: Mapped[uuid.UUID] = mapped_column(
                Uuid, primary_key=True, default=uuid.uuid4
            )
            stream_id: Mapped[str] = mapped_column(
                String(255), nullable=False, index=True
            )
            event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
            data_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
            version: Mapped[int] = mapped_column(Integer, nullable=False)
            created_at: Mapped[datetime] = mapped_column(
                DateTime(timezone=True), server_default=func.now(), nullable=False
            )

            __table_args__ = (
                Index(
                    "ix_events_stream_id_version",
                    "stream_id",
                    "version",
                    unique=True,
                ),
            )
        """))


def _write_event_schema(dest: Path) -> None:
    """Write ``app/schemas/event.py`` with Pydantic request/response schemas.

    Args:
        dest: Destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Pydantic schemas for the event store API.\"\"\"

        from __future__ import annotations

        import uuid
        from datetime import datetime
        from typing import Any

        from pydantic import BaseModel, ConfigDict, Field


        class EventAppend(BaseModel):
            \"\"\"Request body for appending an event to a stream.

            Attributes:
                event_type: Discriminator string for the event kind.
                data: JSON-serialisable event payload.
                expected_version: Optional optimistic concurrency guard.
            \"\"\"

            event_type: str = Field(..., description="Discriminator string for the event kind")
            data: dict[str, Any] = Field(default_factory=dict, description="Event payload")
            expected_version: int | None = Field(
                None, description="Expected next version (optimistic concurrency)"
            )


        class EventRead(BaseModel):
            \"\"\"Public representation of a persisted event.

            Attributes:
                id: UUID primary key (event_id).
                stream_id: Owning stream identifier.
                event_type: Discriminator string.
                data: Event payload.
                version: Sequence number within the stream.
                created_at: UTC timestamp.
            \"\"\"

            model_config = ConfigDict(from_attributes=True)

            id: uuid.UUID
            stream_id: str
            event_type: str
            data: dict[str, Any]
            version: int
            created_at: datetime


        class ProjectionRebuildResult(BaseModel):
            \"\"\"Response returned after a projection rebuild.

            Attributes:
                stream_id: Stream that was replayed.
                projection_name: Name of the projector that ran.
                events_replayed: Total events processed during replay.
                state: Final projection state snapshot.
            \"\"\"

            stream_id: str
            projection_name: str
            events_replayed: int
            state: dict[str, Any]
        """))


def _write_event_crud(dest: Path) -> None:
    """Write ``app/crud/event.py`` with thin CRUD helpers for the Event model.

    Args:
        dest: Destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Thin CRUD layer for Event queries.

        Higher-level operations (append, stream, replay) live in EventStore
        (app/events/store.py).
        \"\"\"

        from __future__ import annotations

        import uuid
        from datetime import datetime

        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession

        from app.models.event import Event


        async def get_event_by_id(
            session: AsyncSession, event_id: uuid.UUID
        ) -> Event | None:
            \"\"\"Fetch an Event row by its primary key.

            Args:
                session: Async SQLAlchemy session.
                event_id: UUID of the event.

            Returns:
                Event ORM instance or None if not found.
            \"\"\"
            result = await session.execute(
                select(Event).where(Event.id == event_id)
            )
            return result.scalar_one_or_none()


        async def count_stream_events(
            session: AsyncSession, stream_id: str
        ) -> int:
            \"\"\"Return the total number of events in a stream.

            Args:
                session: Async SQLAlchemy session.
                stream_id: Stream identifier.

            Returns:
                Total event count for the stream.
            \"\"\"
            from sqlalchemy import func as _func  # noqa: PLC0415

            stmt = (
                select(_func.count())
                .select_from(Event)
                .where(Event.stream_id == stream_id)
            )
            result = await session.execute(stmt)
            return result.scalar_one() or 0


        async def list_event_types(
            session: AsyncSession, stream_id: str
        ) -> list[str]:
            \"\"\"Return distinct event_type values in a stream.

            Args:
                session: Async SQLAlchemy session.
                stream_id: Stream identifier.

            Returns:
                Sorted list of unique event_type strings.
            \"\"\"
            from sqlalchemy import distinct  # noqa: PLC0415

            stmt = select(distinct(Event.event_type)).where(
                Event.stream_id == stream_id
            )
            result = await session.execute(stmt)
            return sorted(row for (row,) in result.all())
        """))


def _write_event_routes(dest: Path) -> None:
    """Write ``app/api/routes/events.py`` with event store REST endpoints.

    Args:
        dest: Destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Event store endpoints.

        Endpoints
        ---------
        POST /events/streams/{stream_id}/append          — append event to stream
        GET  /events/streams/{stream_id}                 — read full stream
        POST /events/projections/{projection_name}/rebuild — rebuild a projection
        \"\"\"

        from __future__ import annotations

        from fastapi import APIRouter, Depends, HTTPException, status
        from sqlalchemy.ext.asyncio import AsyncSession

        from app.events.projector import Projector
        from app.events.store import EventStore
        from app.schemas.event import EventAppend, EventRead, ProjectionRebuildResult

        router = APIRouter(prefix="/events", tags=["events"])


        async def _get_session() -> AsyncSession:
            \"\"\"FastAPI dependency placeholder — replaced by real session dep on boot.

            Raises:
                RuntimeError: Always — callers must override this dependency.
            \"\"\"
            raise RuntimeError("Inject get_async_session via app.dependency_overrides")


        def _get_store() -> EventStore:
            \"\"\"Return a shared EventStore instance.

            Returns:
                A new EventStore (stateless; safe to create per-request).
            \"\"\"
            return EventStore()


        def _get_projector() -> Projector:
            \"\"\"Return a Projector configured from application settings.

            Returns:
                Projector with snapshot_interval from settings.
            \"\"\"
            from app.core.config import settings  # noqa: PLC0415

            return Projector(snapshot_interval=settings.EVENT_STORE_SNAPSHOT_INTERVAL)


        @router.post(
            "/streams/{stream_id}/append",
            response_model=EventRead,
            status_code=status.HTTP_201_CREATED,
        )
        async def append_event(
            stream_id: str,
            body: EventAppend,
            session: AsyncSession = Depends(_get_session),
            store: EventStore = Depends(_get_store),
        ) -> EventRead:
            \"\"\"Append an event to a stream.

            Uses optimistic concurrency if expected_version is supplied.

            Args:
                stream_id: Opaque stream identifier (e.g. aggregate UUID).
                body: EventAppend with event_type, data, and optional expected_version.
                session: Injected async DB session.
                store: EventStore instance.

            Returns:
                The persisted EventRead with assigned version and created_at.

            Raises:
                HTTPException 409: On optimistic concurrency conflict.
            \"\"\"
            try:
                event = await store.append(
                    session,
                    stream_id=stream_id,
                    event_type=body.event_type,
                    data=body.data,
                    expected_version=body.expected_version,
                )
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"detail": str(exc)},
                ) from exc
            return EventRead(
                id=event.event_id,
                stream_id=event.stream_id,
                event_type=event.event_type,
                data=event.data,
                version=event.version,
                created_at=event.created_at,
            )


        @router.get("/streams/{stream_id}", response_model=list[EventRead])
        async def read_stream(
            stream_id: str,
            from_version: int = 1,
            session: AsyncSession = Depends(_get_session),
            store: EventStore = Depends(_get_store),
        ) -> list[EventRead]:
            \"\"\"Return all events in a stream from a given version onward.

            Args:
                stream_id: Stream identifier.
                from_version: Minimum event version to include (default 1).
                session: Injected async DB session.
                store: EventStore instance.

            Returns:
                Ordered list of EventRead (oldest first).
            \"\"\"
            events = await store.get_stream(session, stream_id, from_version=from_version)
            return [
                EventRead(
                    id=e.event_id,
                    stream_id=e.stream_id,
                    event_type=e.event_type,
                    data=e.data,
                    version=e.version,
                    created_at=e.created_at,
                )
                for e in events
            ]


        @router.post(
            "/projections/{projection_name}/rebuild",
            response_model=ProjectionRebuildResult,
        )
        async def rebuild_projection(
            projection_name: str,
            stream_id: str,
            session: AsyncSession = Depends(_get_session),
            store: EventStore = Depends(_get_store),
            projector: Projector = Depends(_get_projector),
        ) -> ProjectionRebuildResult:
            \"\"\"Rebuild a named projection by replaying all events in a stream.

            Args:
                projection_name: Name of the projection to rebuild (informational).
                stream_id: Stream whose events will be replayed.
                session: Injected async DB session.
                store: EventStore instance.
                projector: Projector instance configured from settings.

            Returns:
                ProjectionRebuildResult with event count and final state.
            \"\"\"
            state = await projector.rebuild(session, store, stream_id)
            events = await store.get_stream(session, stream_id)
            return ProjectionRebuildResult(
                stream_id=stream_id,
                projection_name=projection_name,
                events_replayed=len(events),
                state=state,
            )
        """))


def _write_migration(versions_dir: Path) -> Path:
    """Generate an Alembic migration for the events table.

    Args:
        versions_dir: Path to ``alembic/versions/``.

    Returns:
        Path of the created migration file.
    """
    rev_id = "add_event_store"
    down_rev = find_migration_head(versions_dir) or "0001_initial"
    dest = versions_dir / f"{rev_id}.py"
    content = textwrap.dedent(f"""\
        \"\"\"add events table

        Revision ID: {rev_id}
        Revises: {down_rev}
        Create Date: auto-generated by add_event_sourcing tool
        \"\"\"

        from __future__ import annotations

        import sqlalchemy as sa
        from alembic import op

        revision: str = "{rev_id}"
        down_revision: str | None = "{down_rev}"
        branch_labels: str | None = None
        depends_on: str | None = None


        def upgrade() -> None:
            \"\"\"Create the events table with unique (stream_id, version) index.\"\"\"
            op.create_table(
                "events",
                sa.Column("id", sa.Uuid(), nullable=False),
                sa.Column("stream_id", sa.String(255), nullable=False),
                sa.Column("event_type", sa.String(100), nullable=False),
                sa.Column("data_json", sa.JSON(), nullable=True),
                sa.Column("version", sa.Integer(), nullable=False),
                sa.Column(
                    "created_at",
                    sa.DateTime(timezone=True),
                    server_default=sa.text("now()"),
                    nullable=False,
                ),
                sa.PrimaryKeyConstraint("id"),
            )
            op.create_index("ix_events_stream_id", "events", ["stream_id"])
            op.create_index("ix_events_event_type", "events", ["event_type"])
            op.create_index(
                "ix_events_stream_id_version",
                "events",
                ["stream_id", "version"],
                unique=True,
            )


        def downgrade() -> None:
            \"\"\"Drop the events table.\"\"\"
            op.drop_index("ix_events_stream_id_version", table_name="events")
            op.drop_index("ix_events_event_type", table_name="events")
            op.drop_index("ix_events_stream_id", table_name="events")
            op.drop_table("events")
        """)
    dest.write_text(content)
    return dest


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start* (minimum 1).

    Args:
        start: ``time.monotonic()`` value captured at function entry.

    Returns:
        Integer milliseconds elapsed, at least 1 to satisfy ``> 0`` checks.
    """
    return max(1, int((time.monotonic() - start) * 1000))
