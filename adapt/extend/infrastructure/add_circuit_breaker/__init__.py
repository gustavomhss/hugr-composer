from __future__ import annotations
"""TOOL-022: add_circuit_breaker — three-state circuit breaker for FastAPI.

Follows the CONTRACT §B1.0 + §B1.0.1 pattern:

1. Copy ``core.venous.resiliency.CircuitBreaker`` into the project.
2. Copy the FastAPI adapter ``CircuitBreakerAdapter``.
3. Emit ``app/circuit_breaker.py`` (≤ 20-line glue) calling
   ``CircuitBreakerAdapter.install(app)``.

Idempotent: a second run detects ``CircuitBreakerAdapter`` in the glue
and returns ``status="no_op"``.
"""

import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_resiliency_add_circuit_breaker",
    "description": (
        "Copy CircuitBreaker primitive + FastAPI adapter into the project and "
        "wire a ≤20-line app/circuit_breaker.py caller."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_circuit_breaker",
    "imports_primitives": [
        "core.venous.resiliency.CircuitBreaker",
    ],
    "imports_adapters": [
        "core.venous._adapters.fastapi.CircuitBreakerAdapter",
    ],
}


def add_circuit_breaker(inp: ToolInput) -> ToolResult:
    """Add circuit-breaker support by delegating to the shipped primitive + adapter."""
    start = time.monotonic()

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would copy CircuitBreaker primitive + FastAPI adapter "
                "and write app/circuit_breaker.py calling CircuitBreakerAdapter.install(app)."
            ],
            next_steps=["Re-run without dry_run=True to apply."],
            execution_time_ms=_elapsed_ms(start),
        )

    from generators.scaffold_venous import ensure_primitives

    manifest = ensure_primitives(
        str(project),
        names=["core.venous.resiliency.CircuitBreaker"],
        adapters=["core.venous._adapters.fastapi.CircuitBreakerAdapter"],
    )
    files_created.append(manifest.path)

    app_dir.mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "circuit_breaker_glue.py.tmpl", dest=glue_file, substitutions={})
    files_created.append(str(glue_file))

    _emit_project_test(project, files_created)

    import ast
    for fpath in files_created:
        if fpath.endswith(".py"):
            try:
                ast.parse(Path(fpath).read_text())
            except SyntaxError as e:
                return ToolResult(
                    status="error",
                    error=f"Syntax error in {fpath}: {e}",
                    files_created=[],
                    execution_time_ms=_elapsed_ms(start),
                )

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=[],
        notes=[
            "Shipped primitive: core.venous.resiliency.CircuitBreaker.",
            "Shipped adapter: core.venous._adapters.fastapi.CircuitBreakerAdapter.",
            "Wrote app/circuit_breaker.py — call install_circuit_breakers(app) from main.py.",
            "Use `Depends(breaker('service_name'))` on routes to wrap external dependency calls.",
        ],
        next_steps=[
            "Import install_circuit_breakers in app/main.py and invoke it after FastAPI().",
            "Wrap external calls: `async def read(cb=Depends(breaker('upstream')))` then `await cb.call(fn, ...)`.",
            "Breaker opens at failure_rate_threshold=0.5 (default); tune via get_breaker(..., **kw).",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _emit_project_test(project: Path, created: list[str]) -> None:
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_circuit_breaker_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_circuit_breaker_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))





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
            notes=["Generate a base project first via fastapi_generate_project(...)."],
            execution_time_ms=_elapsed_ms(start),
        )

    project = Path(inp.project_dir)
    files_created: list[str] = list(scaffolded or [])
    app_dir = project / "app"
    glue_file = app_dir / "circuit_breaker.py"

    if glue_file.exists() and "CircuitBreakerAdapter" in glue_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["Circuit breakers already wired via the FastAPI adapter."],
            execution_time_ms=_elapsed_ms(start),
        )

"""TOOL-022: add_circuit_breaker — three-state circuit breaker for FastAPI.

Follows the CONTRACT §B1.0 + §B1.0.1 pattern:

1. Copy ``core.venous.resiliency.CircuitBreaker`` into the project.
2. Copy the FastAPI adapter ``CircuitBreakerAdapter``.
3. Emit ``app/circuit_breaker.py`` (≤ 20-line glue) calling
   ``CircuitBreakerAdapter.install(app)``.

Idempotent: a second run detects ``CircuitBreakerAdapter`` in the glue
and returns ``status="no_op"``.
"""

import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_resiliency_add_circuit_breaker",
    "description": (
        "Copy CircuitBreaker primitive + FastAPI adapter into the project and "
        "wire a ≤20-line app/circuit_breaker.py caller."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_circuit_breaker",
    "imports_primitives": [
        "core.venous.resiliency.CircuitBreaker",
    ],
    "imports_adapters": [
        "core.venous._adapters.fastapi.CircuitBreakerAdapter",
    ],
}


def add_circuit_breaker(inp: ToolInput) -> ToolResult:
    """Add circuit-breaker support by delegating to the shipped primitive + adapter."""
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
            notes=["Generate a base project first via fastapi_generate_project(...)."],
            execution_time_ms=_elapsed_ms(start),
        )

    project = Path(inp.project_dir)
    files_created: list[str] = list(scaffolded or [])
    app_dir = project / "app"
    glue_file = app_dir / "circuit_breaker.py"

    if glue_file.exists() and "CircuitBreakerAdapter" in glue_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["Circuit breakers already wired via the FastAPI adapter."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would copy CircuitBreaker primitive + FastAPI adapter "
                "and write app/circuit_breaker.py calling CircuitBreakerAdapter.install(app)."
            ],
            next_steps=["Re-run without dry_run=True to apply."],
            execution_time_ms=_elapsed_ms(start),
        )

    from generators.scaffold_venous import ensure_primitives

    manifest = ensure_primitives(
        str(project),
        names=["core.venous.resiliency.CircuitBreaker"],
        adapters=["core.venous._adapters.fastapi.CircuitBreakerAdapter"],
    )
    files_created.append(manifest.path)

    app_dir.mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "circuit_breaker_glue.py.tmpl", dest=glue_file, substitutions={})
    files_created.append(str(glue_file))

    _emit_project_test(project, files_created)

    import ast
    for fpath in files_created:
        if fpath.endswith(".py"):
            try:
                ast.parse(Path(fpath).read_text())
            except SyntaxError as e:
                return ToolResult(
                    status="error",
                    error=f"Syntax error in {fpath}: {e}",
                    files_created=[],
                    execution_time_ms=_elapsed_ms(start),
                )

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=[],
        notes=[
            "Shipped primitive: core.venous.resiliency.CircuitBreaker.",
            "Shipped adapter: core.venous._adapters.fastapi.CircuitBreakerAdapter.",
            "Wrote app/circuit_breaker.py — call install_circuit_breakers(app) from main.py.",
            "Use `Depends(breaker('service_name'))` on routes to wrap external dependency calls.",
        ],
        next_steps=[
            "Import install_circuit_breakers in app/main.py and invoke it after FastAPI().",
            "Wrap external calls: `async def read(cb=Depends(breaker('upstream')))` then `await cb.call(fn, ...)`.",
            "Breaker opens at failure_rate_threshold=0.5 (default); tune via get_breaker(..., **kw).",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _emit_project_test(project: Path, created: list[str]) -> None:
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_circuit_breaker_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_circuit_breaker_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


