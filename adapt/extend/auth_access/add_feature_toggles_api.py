"""TOOL: add_feature_toggles_api — ship FeatureToggle primitive + FastAPI adapter.

CONTRACT §B1.0 + §B1.0.1 pattern (mirrors `add_graceful_shutdown`):

1. Copy the framework-agnostic primitive `core.venous.flags.FeatureToggle`
   into the generated project.
2. Copy the FastAPI adapter
   `core.venous._adapters.fastapi.FeatureToggleAdapter` alongside it.
3. Emit a thin ``app/feature_toggles.py`` (≤20 lines of glue) that calls
   ``install(app)`` and re-exports ``is_active(key)`` as a route gate.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir

MCP_TOOL = {
    "name": "fastapi_auth_add_feature_toggles_api",
    "description": (
        "Copy FeatureToggle primitive + FastAPI adapter into the project and "
        "wire a ≤20-line app/feature_toggles.py caller."
    ),
    "tags": ["extend", "auth_access"],
    "entry": "add_feature_toggles_api",
    "imports_primitives": [
        "core.venous.flags.FeatureToggle",
    ],
    "imports_adapters": [
        "core.venous._adapters.fastapi.FeatureToggleAdapter",
    ],
}


_GLUE = '''\
"""Wire feature toggles into the FastAPI app.

Delegates to `FeatureToggleAdapter` copied under `core/venous/` by
`add_feature_toggles_api`. Hand-editing is safe but the file is
re-emitted idempotently on subsequent tool runs.
"""

from __future__ import annotations

from fastapi import FastAPI

from core.venous._adapters.fastapi.FeatureToggleAdapter import (
    install as _install,
    is_active,
)


def install_feature_toggles(app: FastAPI):
    """Attach a FeatureToggleRegistry to app.state.toggles; return it."""
    return _install(app)


__all__ = ["install_feature_toggles", "is_active"]
'''


def add_feature_toggles_api(inp: ToolInput) -> ToolResult:
    start = time.monotonic()
    project = Path(inp.project_dir)

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

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
            notes=["Generate a base project first via fastapi_generate_project."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    app_dir = project / "app"
    glue_file = app_dir / "feature_toggles.py"

    if glue_file.exists() and "FeatureToggleAdapter" in glue_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["Feature toggles already wired via the FastAPI adapter."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=["[dry_run] Would copy FeatureToggle primitive + adapter and write app/feature_toggles.py."],
            next_steps=["Re-run without dry_run=True to apply."],
            execution_time_ms=_elapsed_ms(start),
        )

    from generators.scaffold_venous import ensure_primitives

    manifest = ensure_primitives(
        str(project),
        names=["core.venous.flags.FeatureToggle"],
        adapters=["core.venous._adapters.fastapi.FeatureToggleAdapter"],
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
        files_modified=[],
        notes=[
            "Shipped primitive: core.venous.flags.FeatureToggle (off-by-default registry).",
            "Shipped adapter: FeatureToggleAdapter (install + is_active dependency).",
            "Wrote app/feature_toggles.py — call install_feature_toggles(app) from main.py.",
        ],
        next_steps=[
            "Call install_feature_toggles(app) after FastAPI() construction.",
            "Gate routes with dependencies=[Depends(is_active('your_flag'))].",
            "Register your own FeatureToggle subclasses on app.state.toggles.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
