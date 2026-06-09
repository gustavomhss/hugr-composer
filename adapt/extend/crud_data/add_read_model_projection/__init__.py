"""TOOL: add_read_model_projection — CQRS read-model projection for FastAPI.

CONTRACT §B1.3 refactor — copies the framework-agnostic ``MaterializedView``
primitive and the FastAPI ``MaterializedViewAdapter`` into the generated
project, then emits a ≤20-line glue module at ``app/projections.py`` that
wires them via ``install(app, store=app.state.event_store, ...)``.

The read model is the QUERY side of CQRS: it consumes the event store
(``app.state.event_store``, shipped by ``add_event_sourcing``) and maintains a
pre-computed view that read queries hit without recomputing the source.

Idempotent: a second run detects the import chain in ``app/projections.py``
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
    "name": "fastapi_data_add_read_model_projection",
    "description": (
        "Copy the MaterializedView primitive and the MaterializedViewAdapter "
        "into the project, then wire a ≤20-line app/projections.py caller that "
        "builds a CQRS read model over the event store (query side)."
    ),
    "tags": ["extend", "crud_data"],
    "entry": "add_read_model_projection",
    "imports_primitives": [
        "core.venous.data.MaterializedView",
    ],
    "imports_adapters": [
        "core.venous._adapters.fastapi.MaterializedViewAdapter",
    ],
}


def add_read_model_projection(inp: ToolInput) -> ToolResult:
    """Add a CQRS read-model projection by delegating to primitive + adapter."""
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
    glue_file = app_dir / "projections.py"

    if glue_file.exists() and "MaterializedViewAdapter" in glue_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["Read-model projections already wired via the FastAPI adapter."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would copy MaterializedView primitive + adapter "
                "and write app/projections.py."
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
    render_to(_HERE, "projections_glue.py.tmpl", dest=glue_file, substitutions={})
    files_created.append(str(glue_file))

    # Emit the durable SQL-backed projection store (opt-in via PROJECTIONS_DURABLE).
    store_file = app_dir / "projection_store.py"
    render_to(_HERE, "projection_store.py.tmpl", dest=store_file, substitutions={})
    files_created.append(str(store_file))

    files_modified: list[str] = []
    config_file = app_dir / "core" / "config.py"
    if config_file.exists() and _patch_config(config_file):
        files_modified.append(str(config_file))

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
        files_modified=files_modified,
        notes=[
            "Shipped primitive: MaterializedView.",
            "Shipped adapter: MaterializedViewAdapter.",
            "Wrote app/projections.py — call install_projections(app) from main.py "
            "AFTER install_event_store(app) (it reads app.state.event_store).",
            "Register handlers with view.on(event_type); rows are keyed by aggregate_id "
            "(per-aggregate-grain).",
            "Read models are IN-MEMORY BY DEFAULT (per-process, REBUILT ON RESTART — the "
            "view is never the system of record). They are durable and cross-worker ONLY "
            "WHEN you set PROJECTIONS_DURABLE=true (see next_steps): app/projection_store.py "
            "then persists each projection to a per-view table plus a per-(view,aggregate) "
            "checkpoint (last_seq).",
            "Reads are EVENTUALLY CONSISTENT / bounded-stale, NOT linearizable with the "
            "event store; the query route surfaces staleness_s so callers can decide.",
            "Rebuild is MANUAL / on-demand via POST /projections/{view}/rebuild "
            "(superuser-gated) — there is NO live background tailer in v1.",
            "Apply is at-least-once + idempotent: an event whose seq is <= last_applied is "
            "dropped, giving effectively-once (NOT exactly-once).",
        ],
        next_steps=[
            "Import install_projections in app/main.py and invoke it after "
            "install_event_store(app).",
            "GET /projections/{view} to read the projected rows (carries staleness_s).",
            "POST /projections/{view}/rebuild (superuser) to replay from the event store; "
            "pass an aggregate_id_resolver in app/projections.py so rebuild knows which "
            "aggregates to replay.",
            "For durability set PROJECTIONS_DURABLE=true; a SYNC driver is needed for "
            "PostgreSQL (e.g. `psycopg`) — SQLite works out of the box. Tables self-create.",
            "FAST-FOLLOW (not in v1): a background tailer that applies new events without a "
            "manual rebuild call.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _patch_config(config_file: Path) -> bool:
    """Add ``PROJECTIONS_DURABLE`` to the Settings class body — idempotent.

    Off by default: read models stay the in-memory reference unless an operator
    opts into the durable SQL-backed store (mirrors EVENT_STORE_DURABLE).
    Inserted after the standard ``ACCESS_TOKEN_EXPIRE_MINUTES`` field when
    present, else appended.
    """
    src = config_file.read_text()
    if "PROJECTIONS_DURABLE" in src:
        return False
    field = "    PROJECTIONS_DURABLE: bool = False\n"
    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    if anchor in src:
        src = src.replace(anchor, anchor + "\n" + field.rstrip(), 1)
    else:
        src = src.rstrip("\n") + "\n" + field + "\n"
    config_file.write_text(src)
    return True


def _emit_project_test(project: Path, created: list[str]) -> None:
    """Render emitted test into {project}/tests/test_add_read_model_projection_emitted.py."""
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_read_model_projection_emitted.py"
    if emitted.exists():
        return
    render_to(
        _HERE,
        "test_add_read_model_projection_emitted.py.tmpl",
        dest=emitted,
        substitutions={},
    )
    created.append(str(emitted))


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
