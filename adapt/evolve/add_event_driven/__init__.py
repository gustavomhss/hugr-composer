"""TOOL-046: add_event_driven — event-driven architecture scaffold for FastAPI.

Scaffolds full event-driven infrastructure: ``BaseEvent`` (UUID v7),
transactional outbox model + worker, consumer with idempotency (Redis
seen-cache) + DLQ, retry engine (exponential backoff + jitter), per-event
Pydantic schemas, run_consumer entrypoint.

The tool is idempotent: if ``events/base.py`` already contains
``BaseEvent``, returns ``status="no_op"``.

Warnings:
    - The outbox worker's ``_drain_batch`` is a STUB (returns 0). The
      operator MUST wire ``async_session_factory`` and ``broker_publish``
      before any event will leave the outbox table.
    - The main.py registration is a COMMENTED-OUT snippet; the outbox
      worker is not auto-started at boot.
    - The idempotency cache and DLQ both fall back silently when Redis is
      unavailable (open-on-fail), which prioritises availability over
      strict de-duplication — the warning is logged, not raised.
"""

from __future__ import annotations

import ast
import re
import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

_HERE = Path(__file__).parent

# B0.12 — emitted ``consumer.py`` keeps the registered event handlers
# inside a ``_HandlerRegistry`` instance (class-instance singleton,
# allow-listed by ``r_no_module_state``). The body is in-process; under
# a multi-worker deployment each worker has its own copy. This flag +
# the ``single-process`` ``warnings=`` entry below disclose the
# trade-off explicitly. Production multi-worker deployments must
# re-register handlers declaratively at import-time on every worker
# (the consumer module already does this) — see the emitted module's
# docstring for swapping the registry body for Redis if cross-worker
# dynamic registration is ever required.
_SINGLE_PROCESS_OK: bool = True

_VALID_BROKERS = frozenset({"redis_streams", "kafka", "nats"})


MCP_TOOL = {
    "name": "fastapi_data_add_event_driven",
    "description": "Add event-driven architecture with domain events and async handlers.",
    "tags": ["evolve"],
    "entry": "add_event_driven",
}


def add_event_driven(
    inp: ToolInput,
    broker: str = "redis_streams",
    events: list[str] | None = None,
    schema_registry_path: str = "events/schemas",
    generate_consumer: bool = True,
    generate_producer: bool = True,
) -> ToolResult:
    """Add event-driven architecture scaffold to a FastAPI project."""
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err)

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


    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.BASE_MODEL,
        Prereq.CONFIG_SETTINGS,
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

    events = events or []

    if broker not in _VALID_BROKERS:
        return ToolResult(
            status="error",
            error=f"Unknown broker '{broker}'. Choose: {sorted(_VALID_BROKERS)}",
            execution_time_ms=_elapsed_ms(start),
        )

    base_event_file = project / "events" / "base.py"
    if base_event_file.exists() and "BaseEvent" in base_event_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["BaseEvent already present in events/base.py — skipped."],
            execution_time_ms=_elapsed_ms(start),
        )


    files_modified: list[str] = []

    events_dir = project / "events"
    schemas_dir = project / schema_registry_path
    for d in [events_dir, schemas_dir]:
        d.mkdir(parents=True, exist_ok=True)

    (events_dir / "__init__.py").write_text('"""Event-driven architecture package."""\n')
    files_created.append(str(events_dir / "__init__.py"))

    render_to(_HERE, "base_event.py.tmpl", dest=base_event_file, substitutions={})
    files_created.append(str(base_event_file))

    if generate_producer:
        app_models_dir = project / "app" / "models"
        app_models_dir.mkdir(parents=True, exist_ok=True)
        render_to(
            _HERE,
            "outbox_model.py.tmpl",
            dest=app_models_dir / "outbox_event.py",
            substitutions={},
        )
        files_created.append(str(app_models_dir / "outbox_event.py"))

        render_to(
            _HERE,
            "outbox_worker.py.tmpl",
            dest=events_dir / "outbox_worker.py",
            substitutions={"broker": broker},
        )
        files_created.append(str(events_dir / "outbox_worker.py"))

        render_to(
            _HERE,
            "producer.py.tmpl",
            dest=events_dir / "producer.py",
            substitutions={"broker": broker},
        )
        files_created.append(str(events_dir / "producer.py"))

    if generate_consumer:
        render_to(
            _HERE,
            "consumer.py.tmpl",
            dest=events_dir / "consumer.py",
            substitutions={"broker": broker},
        )
        files_created.append(str(events_dir / "consumer.py"))

        render_to(
            _HERE, "retry_engine.py.tmpl", dest=events_dir / "retry_engine.py", substitutions={}
        )
        files_created.append(str(events_dir / "retry_engine.py"))

        render_to(
            _HERE, "idempotency.py.tmpl", dest=events_dir / "idempotency.py", substitutions={}
        )
        files_created.append(str(events_dir / "idempotency.py"))

        render_to(_HERE, "dlq.py.tmpl", dest=events_dir / "dlq.py", substitutions={})
        files_created.append(str(events_dir / "dlq.py"))

    schemas_init = schemas_dir / "__init__.py"
    schemas_init.write_text('"""Event schema registry."""\n')
    files_created.append(str(schemas_init))

    for event_name in events:
        event_file = schemas_dir / f"{_to_snake(event_name)}.py"
        render_to(
            _HERE,
            "event_schema.py.tmpl",
            dest=event_file,
            substitutions={"event_name": event_name},
        )
        files_created.append(str(event_file))

    render_to(
        _HERE,
        "run_consumer.py.tmpl",
        dest=project / "run_consumer.py",
        substitutions={"broker": broker},
    )
    files_created.append(str(project / "run_consumer.py"))

    main_file = project / "app" / "main.py"
    if main_file.exists() and generate_producer and _patch_main_outbox(main_file):
        files_modified.append(str(main_file))

    _emit_project_test(project, files_created)

    # CLAUDE.md pattern #7 — validate emitted .py files parse cleanly.
    # Wave I-1.N closure of Codex v8 HIGH (preserved from pre-migration).
    for path_str in files_created:
        p = Path(path_str)
        if p.suffix == ".py" and p.exists():
            try:
                ast.parse(p.read_text())
            except SyntaxError as exc:
                return ToolResult(
                    status="error",
                    error=f"emitted file failed ast.parse: {p} :: {exc}",
                    execution_time_ms=_elapsed_ms(start),
                )

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
        warnings=[
            # B0.12 disclosure — paired with _SINGLE_PROCESS_OK = True
            # above. The emitted consumer's _HandlerRegistry is
            # in-process; under multi-worker (gunicorn -w N / uvicorn
            # --workers) each worker has its own copy. Handlers
            # registered declaratively at app-import time re-populate
            # on every worker so steady-state dispatch is safe; if
            # handlers must be wired dynamically at runtime across
            # workers, swap the _HandlerRegistry body for a
            # Redis-backed store (public surface unchanged).
            "Consumer handler registry is single-process (in-memory). "
            "Multi-worker deployments: register handlers declaratively "
            "at import-time on every worker, or swap _HandlerRegistry "
            "for a Redis-backed store for cross-worker dynamic "
            "registration.",
        ],
        next_steps=[
            "docker compose up redis -d  # ensure Redis is running",
            "alembic revision --autogenerate -m 'add outbox_events table'",
            "alembic upgrade head",
            "python run_consumer.py  # start consumer worker",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _patch_main_outbox(main_file: Path) -> bool:
    """Append a commented-out outbox startup hook to app/main.py."""
    src = main_file.read_text()
    if "outbox_worker" in src:
        return False
    hook = (
        "\n# Event-driven: outbox worker startup (added by add_event_driven tool)\n"
        "# import asyncio\n"
        "# from events.outbox_worker import start_outbox_worker\n"
        "#\n"
        '# @app.on_event("startup")\n'
        "# async def _start_outbox() -> None:\n"
        "#     asyncio.create_task(start_outbox_worker())\n"
    )
    main_file.write_text(src + hook)
    return True


def _to_snake(name: str) -> str:
    """Convert PascalCase *name* to snake_case."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _emit_project_test(project: Path, created: list[str]) -> None:
    """Emit tests/test_add_event_driven_emitted.py into the generated project."""
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_event_driven_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_event_driven_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*."""
    return int((time.monotonic() - start) * 1000)
