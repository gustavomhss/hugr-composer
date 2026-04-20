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
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir

MCP_TOOL = {
    "name": "fastapi_add_saga",
    "description": (
        "Copy SagaOrchestrator primitive + SagaAdapter into the project and "
        "wire a ≤20-line app/saga.py caller."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_saga",
    "imports_primitives": ["core.venous.events.SagaOrchestrator"],
    "imports_adapters": ["core.venous._adapters.fastapi.SagaAdapter"],
}


_GLUE = '''\
"""Wire the saga orchestrator into the FastAPI app.

Delegates to the primitive + FastAPI adapter copied under `core/venous/`
by the `add_saga` tool. Register real forward/compensator pairs on the
returned definition before calling install().
"""

from __future__ import annotations

from fastapi import FastAPI

from core.venous._adapters.fastapi.SagaAdapter import install
from core.venous.events.SagaOrchestrator.SagaOrchestrator import SagaDefinition


def install_saga(app: FastAPI, *, definition: SagaDefinition | None = None) -> None:
    """Attach a saga orchestrator + /admin/sagas router to *app*."""
    d = definition or _default_definition()
    install(app, definition=d)


def _default_definition() -> SagaDefinition:
    d = SagaDefinition("checkout")
    d.register("noop", compensator=lambda payload: None)(lambda payload: {"ok": True})
    return d
'''


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
    glue_file.write_text(_GLUE)
    files_created.append(str(glue_file))

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
            "Shipped primitive: SagaOrchestrator.",
            "Shipped adapter: SagaAdapter.",
            "Wrote app/saga.py — call install_saga(app) from main.py.",
            "Forward steps in REGISTRATION order; compensators run in STRICT REVERSE order (SAGA-INV-02).",
        ],
        next_steps=[
            "Register real forward + compensator pairs on a SagaDefinition.",
            "Call install_saga(app, definition=my_definition) from app/main.py.",
            "Drive the saga via POST /admin/sagas/{correlation_id}/start.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
