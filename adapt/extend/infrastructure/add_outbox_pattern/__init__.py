"""TOOL-023: add_outbox_pattern — transactional outbox backed by the primitive.

Follows the CONTRACT §B1.0 + §B1.0.1 pattern:

1. Copy the framework-agnostic primitive
   ``core.venous.events.TransactionalOutbox`` into the generated project.
2. Emit a thin ``app/events/outbox.py`` glue (≤ 20 logic lines) that imports
   ``InMemoryTransactionalOutbox`` from the primitive and wires it to a
   SQLAlchemy session + a background relayer task.
3. Emit backing files: ``OutboxEvent``/``OutboxDlq`` models, ``OutboxService``
   (atomically writes events inside business transaction), ARQ-based dispatcher
   worker with SELECT FOR UPDATE SKIP LOCKED, admin routes, Alembic migration.

The tool is idempotent: a second run detects the primitive's
``InMemoryTransactionalOutbox`` import in ``app/events/outbox.py`` and
returns ``status="no_op"``.

WARNING (honesty, F-06): Delivery is AT-LEAST-ONCE. Consumers must be
idempotent. The outbox INSERT is atomic with the business write — if the
business transaction rolls back, the outbox row rolls back too (enforced
by OutboxService.emit() requiring an active session.in_transaction()).
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_data_add_outbox_pattern",
    "description": (
        "Copy TransactionalOutbox primitive into the project and wire a "
        "thin app/events/outbox.py glue plus SQLAlchemy + ARQ backing "
        "(model, service, dispatcher, DLQ, admin routes, migration)."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_outbox_pattern",
    "imports_primitives": [
        "core.venous.events.TransactionalOutbox",
    ],
    "imports_adapters": (),
}


def add_outbox_pattern(inp: ToolInput) -> ToolResult:
    """Add transactional outbox pattern to a FastAPI project.

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
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.BASE_MODEL,
        Prereq.MODELS_INIT,
        Prereq.CONFIG_SETTINGS,
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

    files_created: list[str] = list(scaffolded or [])
    app_dir = project / "app"
    events_dir = app_dir / "events"
    glue_file = events_dir / "outbox.py"

    if glue_file.exists() and "InMemoryTransactionalOutbox" in glue_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["TransactionalOutbox primitive already wired via app/events/outbox.py."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would copy TransactionalOutbox primitive and write "
                "app/events/outbox.py + outbox model, service, dispatcher, routes, migration."
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    from generators.scaffold_venous import ensure_primitives

    manifest = ensure_primitives(
        str(project),
        names=["core.venous.events.TransactionalOutbox"],
        adapters=[],
    )
    files_created.append(manifest.path)

    events_dir.mkdir(parents=True, exist_ok=True)
    events_init = events_dir / "__init__.py"
    if not events_init.exists():
        events_init.write_text(
            '"""Events package — outbox wiring over the TransactionalOutbox primitive."""\n'
        )
        files_created.append(str(events_init))

    render_to(_HERE, "outbox_glue.py.tmpl", dest=glue_file, substitutions={})
    files_created.append(str(glue_file))

    files_modified: list[str] = []

    outbox_model = app_dir / "models" / "outbox.py"
    (app_dir / "models").mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "outbox_model.py.tmpl", dest=outbox_model, substitutions={})
    files_created.append(str(outbox_model))

    _patch_models_init(
        app_dir / "models" / "__init__.py",
        [("outbox", "OutboxEvent"), ("outbox", "OutboxDlq")],
    )

    (app_dir / "services").mkdir(parents=True, exist_ok=True)
    service_file = app_dir / "services" / "outbox.py"
    render_to(_HERE, "outbox_service.py.tmpl", dest=service_file, substitutions={})
    files_created.append(str(service_file))

    (app_dir / "workers").mkdir(parents=True, exist_ok=True)
    dispatcher_file = app_dir / "workers" / "outbox_dispatcher.py"
    render_to(_HERE, "outbox_dispatcher.py.tmpl", dest=dispatcher_file, substitutions={})
    files_created.append(str(dispatcher_file))

    routes_dir = app_dir / "api" / "routes"
    if routes_dir.exists():
        admin_route = routes_dir / "outbox_admin.py"
        render_to(_HERE, "outbox_admin_routes.py.tmpl", dest=admin_route, substitutions={})
        files_created.append(str(admin_route))

    (app_dir / "schemas").mkdir(parents=True, exist_ok=True)
    schemas_file = app_dir / "schemas" / "outbox.py"
    render_to(_HERE, "outbox_schemas.py.tmpl", dest=schemas_file, substitutions={})
    files_created.append(str(schemas_file))

    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        rev_id = "outbox_tables"
        existing = sorted(versions_dir.glob("*.py"))
        down_rev = existing[-1].stem if existing else "0001_initial"
        migration_file = versions_dir / f"{rev_id}.py"
        render_to(
            _HERE,
            "migration.py.tmpl",
            dest=migration_file,
            substitutions={"rev_id": rev_id, "down_rev": down_rev},
        )
        files_created.append(str(migration_file))

    _verify_glue_loc(glue_file)
    _emit_project_test(project, files_created)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "Shipped primitive: core.venous.events.TransactionalOutbox.",
            "Glue: app/events/outbox.py wires InMemoryTransactionalOutbox + relay_loop.",
            "Transactional outbox added: emit_event() writes inside business transaction.",
            "Dispatcher uses SELECT FOR UPDATE SKIP LOCKED — safe for multiple workers.",
            "Retry schedule: 1s -> 5s -> 30s -> 5m -> 30m (exponential backoff).",
            "Events exhausting retries move to outbox_dlq table.",
            "/outbox/metrics and /outbox/dlq admin endpoints registered.",
            "WARNING: AT-LEAST-ONCE delivery — downstream consumers must be idempotent.",
        ],
        next_steps=[
            "alembic upgrade head  # creates outbox_events + outbox_dlq tables",
            "pip install arq",
            "Set ARQ_REDIS_URL in .env.",
            "Start dispatcher: arq app.workers.outbox_dispatcher.WorkerSettings",
            "Call await outbox_svc.emit('OrderCreated', payload) inside your transaction.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _verify_glue_loc(glue_file: Path) -> None:
    """Assert the primary glue has ≤ 20 logic lines (CONTRACT §B1.0.1)."""
    try:
        tree = ast.parse(glue_file.read_text())
    except SyntaxError:
        return
    loc = 0
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            start = node.body[0].lineno
            end = node.end_lineno or start
            loc += end - start + 1
    if loc > 20:
        raise RuntimeError(f"Primary glue {glue_file} has {loc} logic lines (> 20).")


def _emit_project_test(project: Path, created: list[str]) -> None:
    """Render emitted test into {project}/tests/test_add_outbox_pattern_emitted.py."""
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_outbox_pattern_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_outbox_pattern_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


def _patch_models_init(
    models_init: Path,
    class_imports: list[tuple[str, str]],
) -> None:
    """Append model imports to ``app/models/__init__.py`` idempotently."""
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


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start* (from ``time.monotonic()``)."""
    return int((time.monotonic() - start) * 1000)
