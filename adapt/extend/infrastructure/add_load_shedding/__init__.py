"""TOOL: add_load_shedding — priority-aware admission control for FastAPI.

CONTRACT §B1.3 refactor — copies the framework-agnostic ``LoadShedder``
primitive and the FastAPI ``LoadShedderAdapter`` into the generated
project, then emits a ≤20-line glue module at ``app/load_shedding.py``
that wires them via ``install(app)``.

Idempotent: a second run detects the import chain in
``app/load_shedding.py`` and returns ``status="no_op"``.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_resiliency_add_load_shedding",
    "description": (
        "Copy LoadShedder primitive + LoadShedderAdapter into the project and "
        "wire a ≤20-line app/load_shedding.py caller."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_load_shedding",
    "imports_primitives": ["core.venous.resiliency.LoadShedder"],
    "imports_adapters": ["core.venous._adapters.fastapi.LoadShedderAdapter"],
}


def add_load_shedding(inp: ToolInput) -> ToolResult:
    """Add load shedding by delegating to the shipped primitive + adapter."""
    start = time.monotonic()

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

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

    project = Path(inp.project_dir)
    files_created: list[str] = list(scaffolded or [])
    app_dir = project / "app"
    glue_file = app_dir / "load_shedding.py"

    if glue_file.exists() and "LoadShedderAdapter" in glue_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["Load shedding already wired via the FastAPI adapter."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=["[dry_run] Would copy LoadShedder + adapter and write app/load_shedding.py."],
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
    render_to(_HERE, "load_shedding_glue.py.tmpl", dest=glue_file, substitutions={})
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
            "Shipped primitive: LoadShedder.",
            "Shipped adapter: LoadShedderAdapter.",
            "Wrote app/load_shedding.py — call install_load_shedding(app) from main.py.",
            "Overloaded requests receive 503 + Retry-After (LSH-INV-02).",
        ],
        next_steps=[
            "Import install_load_shedding in app/main.py and invoke it after FastAPI() construction.",
            "Clients SHOULD send X-Priority: critical|normal|sheddable_plus|sheddable.",
            "Feed queue depth / CPU EWMA via X-Queue-Depth / X-Cpu-Ewma headers or a custom composer.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _emit_project_test(project: Path, created: list[str]) -> None:
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_load_shedding_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_load_shedding_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


