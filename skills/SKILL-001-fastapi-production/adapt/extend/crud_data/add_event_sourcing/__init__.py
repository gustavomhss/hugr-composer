"""TOOL-079: add_event_sourcing — event store + replay for FastAPI.

CONTRACT §B1.3 refactor — copies the framework-agnostic
``EventSourcedStore`` + ``DomainEvent`` primitives and the FastAPI
``EventSourcedStoreAdapter`` into the generated project, then emits a
≤20-line glue module at ``app/event_store.py`` that wires them via
``install(app)``.

Idempotent: a second run detects the import chain in ``app/event_store.py``
and returns ``status="no_op"``.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_data_add_event_sourcing",
    "description": (
        "Copy EventSourcedStore + DomainEvent primitives and the "
        "EventSourcedStoreAdapter into the project, then wire a ≤20-line "
        "app/event_store.py caller."
    ),
    "tags": ["extend", "crud_data"],
    "entry": "add_event_sourcing",
    "imports_primitives": [
        "core.venous.events.EventSourcedStore",
        "core.venous.events.DomainEvent",
    ],
    "imports_adapters": [
        "core.venous._adapters.fastapi.EventSourcedStoreAdapter",
    ],
}


def add_event_sourcing(inp: ToolInput) -> ToolResult:
    """Add an event-sourced store by delegating to primitives + adapter."""
    start = time.monotonic()
    project = Path(inp.project_dir)

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.CONFIG_SETTINGS,
        Prereq.REQUIREMENTS_TXT,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    app_dir = project / "app"
    glue_file = app_dir / "event_store.py"

    if glue_file.exists() and "EventSourcedStoreAdapter" in glue_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["Event store already wired via the FastAPI adapter."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would copy EventSourcedStore + DomainEvent primitives + adapter "
                "and write app/event_store.py."
            ],
            next_steps=["Re-run without dry_run=True to apply."],
            execution_time_ms=_elapsed_ms(start),
        )

    from generators.scaffold_venous import ensure_primitives

    manifest = ensure_primitives(
        str(project),
        names=MCP_TOOL["imports_primitives"],
        adapters=MCP_TOOL["imports_adapters"],
    )
    files_created.append(manifest.path)

    app_dir.mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "event_store_glue.py.tmpl", dest=glue_file, substitutions={})
    files_created.append(str(glue_file))

    _emit_project_test(project, files_created)

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
        notes=[
            "Shipped primitives: EventSourcedStore, DomainEvent.",
            "Shipped adapter: EventSourcedStoreAdapter.",
            "Wrote app/event_store.py — call install_event_store(app) from main.py.",
            "Optimistic-concurrency append returns 409 on stale expected_version (ESS-INV-01).",
        ],
        next_steps=[
            "Import install_event_store in app/main.py and invoke it after FastAPI() construction.",
            "POST /events/{aggregate_id}?expected_version=N with a JSON event list to append.",
            "GET /events/{aggregate_id} to load the stream.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _emit_project_test(project: Path, created: list[str]) -> None:
    """Render emitted test into {project}/tests/test_add_event_sourcing_emitted.py."""
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_event_sourcing_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_event_sourcing_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
