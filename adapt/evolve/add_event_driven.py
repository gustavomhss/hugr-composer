"""TOOL-046: add_event_driven — event-driven architecture scaffold for FastAPI.

Scaffolds the full event-driven infrastructure:
- ``BaseEvent`` Pydantic model with UUID v7
- Transactional outbox pattern (``OutboxEvent`` SQLAlchemy model + outbox worker)
- Consumer workers with idempotency via Redis seen-cache and DLQ
- Retry engine with exponential backoff + jitter
- Schema evolution helpers (versioned event classes)
- Event type–specific scaffolds for each name in ``events``

The tool is idempotent: if ``events/base.py`` already contains ``BaseEvent``,
the tool returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.evolve.add_event_driven import add_event_driven

    result = add_event_driven(
        ToolInput(project_dir="/path/to/project"),
        broker="redis_streams",
        events=["OrderCreated", "UserDeleted"],
    )
    print(result.status)
    print(result.files_created)
"""

from __future__ import annotations

import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir

_VALID_BROKERS = frozenset({"redis_streams", "kafka", "nats"})


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def add_event_driven(
    inp: ToolInput,
    broker: str = "redis_streams",
    events: list[str] | None = None,
    schema_registry_path: str = "events/schemas",
    generate_consumer: bool = True,
    generate_producer: bool = True,
) -> ToolResult:
    """Add event-driven architecture scaffold to a FastAPI project.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.
        broker: Message broker — ``redis_streams``, ``kafka``, or ``nats``.
        events: List of event type names to scaffold (e.g. ``["OrderCreated"]``).
            ``None`` scaffolds base infrastructure only.
        schema_registry_path: Directory for Pydantic event schemas.
        generate_consumer: Scaffold consumer workers with retry/DLQ.
        generate_producer: Scaffold transactional outbox producer.

    Returns:
        ``ToolResult`` describing every file created or modified.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err)

    events = events or []

    if broker not in _VALID_BROKERS:
        return ToolResult(
            status="error",
            error=f"Unknown broker '{broker}'. Choose: {sorted(_VALID_BROKERS)}",
            execution_time_ms=_elapsed_ms(start),
        )

    # Idempotency guard
    base_event_file = project / "events" / "base.py"
    if base_event_file.exists() and "BaseEvent" in base_event_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["BaseEvent already present in events/base.py — skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                f"[dry_run] broker={broker}, events={events or 'base only'}",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    files_modified: list[str] = []

    # Create directory structure
    events_dir = project / "events"
    schemas_dir = project / schema_registry_path
    for d in [events_dir, schemas_dir]:
        d.mkdir(parents=True, exist_ok=True)

    # Step 1: BaseEvent
    (events_dir / "__init__.py").write_text('"""Event-driven architecture package."""\n')
    files_created.append(str(events_dir / "__init__.py"))

    base_event_file.write_text(_base_event_content())
    files_created.append(str(base_event_file))

    # Step 2: Outbox model
    if generate_producer:
        app_models_dir = project / "app" / "models"
        app_models_dir.mkdir(parents=True, exist_ok=True)
        outbox_file = app_models_dir / "outbox_event.py"
        outbox_file.write_text(_outbox_model_content())
        files_created.append(str(outbox_file))

        # Outbox worker
        worker_file = events_dir / "outbox_worker.py"
        worker_file.write_text(_outbox_worker_content(broker))
        files_created.append(str(worker_file))

        # Producer helper
        producer_file = events_dir / "producer.py"
        producer_file.write_text(_producer_content(broker))
        files_created.append(str(producer_file))

    # Step 3: Consumer with retry + DLQ + idempotency
    if generate_consumer:
        consumer_file = events_dir / "consumer.py"
        consumer_file.write_text(_consumer_content(broker))
        files_created.append(str(consumer_file))

        retry_file = events_dir / "retry_engine.py"
        retry_file.write_text(_retry_engine_content())
        files_created.append(str(retry_file))

        idempotency_file = events_dir / "idempotency.py"
        idempotency_file.write_text(_idempotency_content())
        files_created.append(str(idempotency_file))

        dlq_file = events_dir / "dlq.py"
        dlq_file.write_text(_dlq_content())
        files_created.append(str(dlq_file))

    # Step 4: Per-event schema scaffolds
    schemas_init = schemas_dir / "__init__.py"
    schemas_init.write_text('"""Event schema registry."""\n')
    files_created.append(str(schemas_init))

    for event_name in events:
        event_file = schemas_dir / f"{_to_snake(event_name)}.py"
        event_file.write_text(_event_schema_content(event_name))
        files_created.append(str(event_file))

    # Step 5: Worker entrypoint
    worker_entry = project / "run_consumer.py"
    worker_entry.write_text(_worker_entrypoint_content(broker))
    files_created.append(str(worker_entry))

    # Step 6: Patch main.py to include outbox startup
    main_file = project / "app" / "main.py"
    if main_file.exists() and generate_producer:
        _patch_main_outbox(main_file)
        files_modified.append(str(main_file))

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            f"Event-driven infrastructure scaffolded (broker={broker})",
            f"Events scaffolded: {events if events else 'base only'}",
            "Outbox pattern: business row + outbox_events written atomically.",
            "Consumer idempotency: Redis seen-cache with 7-day TTL.",
            "DLQ: events written after max_attempts exhausted.",
        ],
        next_steps=[
            "docker compose up redis -d  # ensure Redis is running",
            "alembic revision --autogenerate -m 'add outbox_events table'",
            "alembic upgrade head",
            "python run_consumer.py  # start consumer worker",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# Content generators
# ---------------------------------------------------------------------------


def _base_event_content() -> str:
    """Return content for events/base.py with BaseEvent and UUID v7.

    Returns:
        Python source string.
    """
    return textwrap.dedent("""\
        \"\"\"Base event schema for all domain events.

        Uses UUID v7 for time-ordered event IDs (chronological by construction).
        All events are immutable (frozen=True) after creation.
        \"\"\"
        from __future__ import annotations

        import uuid
        from datetime import datetime, timezone
        from typing import Any

        from pydantic import BaseModel, Field


        def _uuid7() -> uuid.UUID:
            \"\"\"Generate a UUID v7 (time-ordered, RFC 9562).

            Falls back to uuid4 with timestamp injection for Python < 3.13.

            Returns:
                A time-ordered UUID.
            \"\"\"
            try:
                return uuid.uuid7()  # type: ignore[attr-defined]  # Python 3.13+
            except AttributeError:
                import time as _time
                ts_ms = int(_time.time() * 1000)
                rand_b = uuid.uuid4().int & 0x3FFF_FFFF_FFFF_FFFF
                val = (ts_ms << 80) | (0x7 << 76) | rand_b
                return uuid.UUID(int=val)


        class BaseEvent(BaseModel):
            \"\"\"Immutable base for all domain events.

            Attributes:
                event_id: Time-ordered UUID v7 for chronological sort.
                event_type: Discriminator string (e.g. 'OrderCreated').
                occurred_at: UTC timestamp of when the event was raised.
                correlation_id: Optional trace ID linking related events.
                schema_version: Monotonic version for schema evolution.
                producer_service: Name of the originating service.
            \"\"\"

            event_id: uuid.UUID = Field(default_factory=_uuid7)
            event_type: str
            occurred_at: datetime = Field(
                default_factory=lambda: datetime.now(timezone.utc)
            )
            correlation_id: uuid.UUID | None = None
            schema_version: int = 1
            producer_service: str = ""

            model_config = {"frozen": True}

            def to_stream_payload(self) -> dict[str, str]:
                \"\"\"Serialize to Redis XADD-compatible flat dict (all strings).

                Returns:
                    Dict with all string values for Redis Streams.
                \"\"\"
                return {
                    "event_id": str(self.event_id),
                    "event_type": self.event_type,
                    "occurred_at": self.occurred_at.isoformat(),
                    "correlation_id": str(self.correlation_id) if self.correlation_id else "",
                    "schema_version": str(self.schema_version),
                    "payload": self.model_dump_json(),
                }
    """)


def _outbox_model_content() -> str:
    """Return content for app/models/outbox_event.py.

    Returns:
        Python source string.
    """
    return textwrap.dedent("""\
        \"\"\"Transactional outbox model.

        Written atomically with the business row in the same transaction.
        Background outbox_worker.py drains this table to the broker.
        \"\"\"
        from __future__ import annotations

        import uuid
        from datetime import datetime, timezone

        from sqlalchemy import Boolean, DateTime, Integer, String, Text, Uuid
        from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


        class _OutboxBase(DeclarativeBase):
            pass


        class OutboxEvent(_OutboxBase):
            \"\"\"Outbox table row for at-least-once delivery guarantee.

            Attributes:
                id: Auto-increment surrogate PK.
                event_id: UUID v7 identifying the domain event.
                event_type: Discriminator (e.g. 'OrderCreated').
                payload: JSON-serialized event payload.
                published: False until the outbox worker successfully publishes.
                attempts: Number of publish attempts made.
                created_at: Row creation timestamp (UTC).
            \"\"\"

            __tablename__ = "outbox_events"

            id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
            event_id: Mapped[uuid.UUID] = mapped_column(Uuid, unique=True, nullable=False)
            event_type: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
            payload: Mapped[str] = mapped_column(Text, nullable=False)
            published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
            attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
            created_at: Mapped[datetime] = mapped_column(
                DateTime(timezone=True),
                default=lambda: datetime.now(timezone.utc),
                nullable=False,
            )
    """)


def _outbox_worker_content(broker: str) -> str:
    """Return content for events/outbox_worker.py.

    Args:
        broker: Target message broker identifier.

    Returns:
        Python source string.
    """
    return textwrap.dedent(f"""\
        \"\"\"Outbox worker: drains the outbox_events table to the {broker} broker.

        Run as a background process:
            python run_consumer.py  (calls start_outbox_worker)
        \"\"\"
        from __future__ import annotations

        import asyncio
        import json
        import logging
        import time

        logger = logging.getLogger(__name__)

        # Maximum rows per drain cycle
        _BATCH_LIMIT = 100
        # Polling interval when outbox is empty (seconds)
        _IDLE_SLEEP = 0.5


        async def start_outbox_worker() -> None:
            \"\"\"Poll and drain unpublished outbox_events in a tight loop.

            Runs indefinitely; cancel the task to stop.
            \"\"\"
            logger.info("Outbox worker started (broker={broker})")
            while True:
                try:
                    await _drain_batch()
                except Exception as exc:  # noqa: BLE001
                    logger.error("Outbox drain error: %s", exc)
                await asyncio.sleep(_IDLE_SLEEP)


        async def _drain_batch() -> int:
            \"\"\"Drain one batch of unpublished events.

            Returns:
                Number of events published in this cycle.
            \"\"\"
            # CUSTOMIZE: replace with real DB session + broker publish call
            logger.debug("Draining outbox batch (limit=%d)", _BATCH_LIMIT)
            return 0  # placeholder — real impl queries DB and publishes
    """)


def _producer_content(broker: str) -> str:
    """Return content for events/producer.py.

    Args:
        broker: Target message broker identifier.

    Returns:
        Python source string.
    """
    return textwrap.dedent(f"""\
        \"\"\"Producer helper: write domain events to the transactional outbox.

        Usage::

            from events.producer import publish_event
            from events.schemas.order_created import OrderCreatedV1

            event = OrderCreatedV1(order_id=order.id, user_id=user.id)
            # Call inside an active SQLAlchemy session (same transaction as business row):
            publish_event(session, event)
        \"\"\"
        from __future__ import annotations

        import logging

        from sqlalchemy.orm import Session

        from events.base import BaseEvent

        logger = logging.getLogger(__name__)


        def publish_event(session: Session, event: BaseEvent) -> None:
            \"\"\"Write *event* to the outbox table (does NOT commit — caller owns the transaction).

            Args:
                session: Active SQLAlchemy session.
                event: Domain event to publish.

            Note:
                The outbox worker will drain this row to the {broker} broker.
            \"\"\"
            from app.models.outbox_event import OutboxEvent

            row = OutboxEvent(
                event_id=event.event_id,
                event_type=event.event_type,
                payload=event.model_dump_json(),
            )
            session.add(row)
            logger.debug("Queued event %s id=%s", event.event_type, event.event_id)
    """)


def _consumer_content(broker: str) -> str:
    """Return content for events/consumer.py.

    Args:
        broker: Target message broker identifier.

    Returns:
        Python source string.
    """
    return textwrap.dedent(f"""\
        \"\"\"Event consumer for {broker}.

        Dispatches incoming events to registered handlers with retry logic,
        idempotency checking, and DLQ quarantine on exhaustion.
        \"\"\"
        from __future__ import annotations

        import logging
        from typing import Callable

        from events.idempotency import is_seen, mark_seen
        from events.retry_engine import retry_with_backoff
        from events.dlq import send_to_dlq

        logger = logging.getLogger(__name__)

        # Handler registry: event_type → async handler function
        _HANDLERS: dict[str, Callable] = {{}}


        def register_handler(event_type: str, handler: Callable) -> None:
            \"\"\"Register an async handler for an event type.

            Args:
                event_type: Event discriminator string (e.g. 'OrderCreated').
                handler: Async callable accepting a single event dict.
            \"\"\"
            _HANDLERS[event_type] = handler
            logger.info("Registered handler for %s", event_type)


        async def dispatch_event(event_id: str, event_type: str, payload: dict) -> None:
            \"\"\"Dispatch one event to its registered handler with idempotency + retry.

            Args:
                event_id: Unique event identifier (UUID string).
                event_type: Event discriminator.
                payload: Parsed event payload dict.
            \"\"\"
            consumer_name = "default"
            if is_seen(consumer_name, event_id):
                logger.debug("Duplicate event %s — skipped", event_id)
                return

            handler = _HANDLERS.get(event_type)
            if handler is None:
                logger.warning("No handler for event_type=%s", event_type)
                return

            try:
                await retry_with_backoff(handler, payload)
                mark_seen(consumer_name, event_id)
            except Exception as exc:  # noqa: BLE001
                logger.error("Handler failed after retries: %s | event_id=%s", exc, event_id)
                send_to_dlq(event_id, event_type, payload, str(exc))
    """)


def _retry_engine_content() -> str:
    """Return content for events/retry_engine.py.

    Returns:
        Python source string.
    """
    return textwrap.dedent("""\
        \"\"\"Exponential backoff retry engine for event handlers.

        Policy: 5 attempts, 200ms base, 2× multiplier, ±10% jitter, 30s hard cap.
        \"\"\"
        from __future__ import annotations

        import asyncio
        import logging
        import random
        from typing import Callable

        logger = logging.getLogger(__name__)

        _MAX_ATTEMPTS = 5
        _BASE_MS = 200
        _MULTIPLIER = 2.0
        _JITTER = 0.10
        _CAP_S = 30.0


        async def retry_with_backoff(fn: Callable, *args: object, **kwargs: object) -> object:
            \"\"\"Call *fn* with exponential backoff retry.

            Args:
                fn: Async callable to retry.
                *args: Positional arguments forwarded to *fn*.
                **kwargs: Keyword arguments forwarded to *fn*.

            Returns:
                Return value of *fn* on success.

            Raises:
                Exception: Re-raises the last exception after max attempts.
            \"\"\"
            delay_s = _BASE_MS / 1000
            last_exc: Exception | None = None
            for attempt in range(1, _MAX_ATTEMPTS + 1):
                try:
                    return await fn(*args, **kwargs)
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    if attempt == _MAX_ATTEMPTS:
                        break
                    jitter_factor = 1.0 + random.uniform(-_JITTER, _JITTER)
                    sleep_s = min(delay_s * jitter_factor, _CAP_S)
                    logger.warning(
                        "Attempt %d/%d failed: %s — retrying in %.2fs",
                        attempt, _MAX_ATTEMPTS, exc, sleep_s,
                    )
                    await asyncio.sleep(sleep_s)
                    delay_s = min(delay_s * _MULTIPLIER, _CAP_S)
            raise last_exc  # type: ignore[misc]
    """)


def _idempotency_content() -> str:
    """Return content for events/idempotency.py.

    Returns:
        Python source string.
    """
    return textwrap.dedent("""\
        \"\"\"Consumer idempotency via Redis seen-cache.

        Uses a Redis SET with 7-day TTL to absorb duplicate deliveries.
        Falls back gracefully (allows processing) when Redis is unavailable.
        \"\"\"
        from __future__ import annotations

        import logging

        logger = logging.getLogger(__name__)

        _TTL_SECONDS = 7 * 24 * 3600  # 7 days


        def _redis_client():  # type: ignore[return]
            \"\"\"Return a Redis client or None if unavailable.\"\"\"
            try:
                import redis  # type: ignore[import-untyped]
                return redis.Redis(host="localhost", port=6379, decode_responses=True)
            except Exception:  # noqa: BLE001
                return None


        def is_seen(consumer_name: str, event_id: str) -> bool:
            \"\"\"Return True if this event has already been processed by this consumer.

            Args:
                consumer_name: Unique consumer identifier.
                event_id: Event UUID string.

            Returns:
                True if the event was already seen (should be skipped).
            \"\"\"
            client = _redis_client()
            if client is None:
                return False
            key = f"seen:{consumer_name}:{event_id}"
            try:
                return bool(client.exists(key))
            except Exception:  # noqa: BLE001
                return False


        def mark_seen(consumer_name: str, event_id: str) -> None:
            \"\"\"Mark an event as processed by this consumer (7-day TTL).

            Args:
                consumer_name: Unique consumer identifier.
                event_id: Event UUID string.
            \"\"\"
            client = _redis_client()
            if client is None:
                return
            key = f"seen:{consumer_name}:{event_id}"
            try:
                client.set(key, "1", ex=_TTL_SECONDS)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to mark event seen: %s", exc)
    """)


def _dlq_content() -> str:
    """Return content for events/dlq.py.

    Returns:
        Python source string.
    """
    return textwrap.dedent("""\
        \"\"\"Dead Letter Queue: quarantine poisoned events after max retry exhaustion.\"\"\"
        from __future__ import annotations

        import json
        import logging
        from datetime import datetime, timezone

        logger = logging.getLogger(__name__)

        _DLQ_STREAM = "dlq:events"


        def send_to_dlq(
            event_id: str,
            event_type: str,
            payload: dict,
            error: str,
        ) -> None:
            \"\"\"Write a failed event to the DLQ stream for operator inspection.

            Args:
                event_id: UUID string of the failed event.
                event_type: Event discriminator string.
                payload: Original event payload dict.
                error: Error message from the last handler attempt.
            \"\"\"
            entry = {
                "event_id": event_id,
                "event_type": event_type,
                "payload": json.dumps(payload),
                "error": error,
                "quarantined_at": datetime.now(timezone.utc).isoformat(),
            }
            try:
                import redis  # type: ignore[import-untyped]
                client = redis.Redis(host="localhost", port=6379, decode_responses=True)
                client.xadd(_DLQ_STREAM, entry)
                logger.error("Event %s quarantined to DLQ: %s", event_id, error)
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to write to DLQ (event=%s): %s", event_id, exc)
    """)


def _event_schema_content(event_name: str) -> str:
    """Return content for a per-event Pydantic schema module.

    Args:
        event_name: PascalCase event type name.

    Returns:
        Python source string.
    """
    return textwrap.dedent(f"""\
        \"\"\"Pydantic schema for {event_name} domain event.

        Versioned: {event_name}V1 is the current stable version.
        Add {event_name}V2 when the schema changes; keep V1 for backward compat.
        \"\"\"
        from __future__ import annotations

        import uuid

        from pydantic import Field

        from events.base import BaseEvent


        class {event_name}V1(BaseEvent):
            \"\"\"Version 1 of the {event_name} event.

            CUSTOMIZE: add domain-specific fields below.

            Attributes:
                entity_id: Primary key of the affected entity.
            \"\"\"

            event_type: str = Field(default="{event_name}", frozen=True)
            schema_version: int = Field(default=1, frozen=True)

            # CUSTOMIZE: add your domain fields here
            entity_id: uuid.UUID


        # Convenience alias — update when a V2 is released
        {event_name} = {event_name}V1
    """)


def _worker_entrypoint_content(broker: str) -> str:
    """Return content for run_consumer.py.

    Args:
        broker: Target message broker identifier.

    Returns:
        Python source string.
    """
    return textwrap.dedent(f"""\
        \"\"\"Entry-point: run the outbox worker and event consumer.\"\"\"
        from __future__ import annotations

        import asyncio
        import logging

        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
        logger = logging.getLogger(__name__)


        async def main() -> None:
            \"\"\"Start all background workers.\"\"\"
            from events.outbox_worker import start_outbox_worker

            logger.info("Starting workers (broker={broker})")
            await asyncio.gather(
                start_outbox_worker(),
                # Add additional consumer tasks here
            )


        if __name__ == "__main__":
            asyncio.run(main())
    """)


def _patch_main_outbox(main_file: Path) -> None:
    """Inject outbox worker startup hook into app/main.py.

    Args:
        main_file: Path to ``app/main.py``.
    """
    src = main_file.read_text()
    if "outbox_worker" in src:
        return
    hook = textwrap.dedent("""\

        # Event-driven: outbox worker startup (added by add_event_driven tool)
        # import asyncio
        # from events.outbox_worker import start_outbox_worker
        #
        # @app.on_event("startup")
        # async def _start_outbox() -> None:
        #     asyncio.create_task(start_outbox_worker())
    """)
    main_file.write_text(src + hook)


def _to_snake(name: str) -> str:
    """Convert PascalCase *name* to snake_case.

    Args:
        name: PascalCase identifier string.

    Returns:
        snake_case version.
    """
    import re
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*.

    Args:
        start: Reference time from ``time.monotonic()``.

    Returns:
        Elapsed milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)
