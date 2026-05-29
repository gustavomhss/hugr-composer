"""TOOL-024: add_saga — saga orchestration for FastAPI.

CONTRACT §B1.3 refactor — copies the framework-agnostic
``SagaOrchestrator`` primitive and the FastAPI ``SagaAdapter`` into the
generated project, then emits a ≤20-line glue module at ``app/saga.py``
that wires them via ``install(app, definition=...)``.

The tool ships a stub ``SagaDefinition`` named ``checkout`` with a single
no-op step; callers register their real forward/compensator pairs on the
returned definition.

Idempotent: a second run detects the import chain in ``app/saga.py`` and
returns ``status="no_op"``.

WARNING (honesty rule F-06): Compensation steps are BEST-EFFORT only.
If a compensator itself raises, the failure is logged and the orchestration
continues reversing remaining steps. Do NOT assert exactly-once compensation.
"""

from __future__ import annotations

import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_data_add_saga",
    "description": (
        "Copy SagaOrchestrator primitive + SagaAdapter into the project and "
        "wire a ≤20-line app/saga.py caller."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_saga",
    "imports_primitives": ["core.venous.events.SagaOrchestrator"],
    "imports_adapters": ["core.venous._adapters.fastapi.SagaAdapter"],
}


def add_saga(inp: ToolInput) -> ToolResult:
    """Add a saga orchestrator by delegating to the shipped primitive + adapter."""
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
    glue_file = app_dir / "saga.py"

    if glue_file.exists() and "SagaAdapter" in glue_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["Saga orchestrator already wired via the FastAPI adapter."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=["[dry_run] Would copy SagaOrchestrator + SagaAdapter and write app/saga.py."],
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
    render_to(_HERE, "saga_glue.py.tmpl", dest=glue_file, substitutions={})
    files_created.append(str(glue_file))

    _emit_project_test(project, files_created)

    return ToolResult(
        status="success",
        files_created=files_created,
        notes=[
            "Shipped primitive: SagaOrchestrator.",
            "Shipped adapter: SagaAdapter.",
            "Wrote app/saga.py — call install_saga(app) from main.py.",
            "Forward steps in REGISTRATION order; compensators run in STRICT REVERSE order (SAGA-INV-02).",
            "WARNING: compensation is BEST-EFFORT — compensator failures are logged, not re-raised.",
        ],
        next_steps=[
            "Register real forward + compensator pairs on a SagaDefinition.",
            "Call install_saga(app, definition=my_definition) from app/main.py.",
            "Drive the saga via POST /admin/sagas/{correlation_id}/start.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _emit_project_test(project: Path, created: list[str]) -> None:
    """Render emitted test into {project}/tests/test_add_saga_emitted.py."""
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_saga_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_saga_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
