"""TOOL-022: add_circuit_breaker — three-state circuit breaker for FastAPI.

Follows the CONTRACT §B1.0 + §B1.0.1 pattern:

1. Copy ``core.venous.resiliency.CircuitBreaker`` into the project.
2. Copy the FastAPI adapter ``CircuitBreakerAdapter``.
3. Emit ``app/circuit_breaker.py`` (≤ 20-line glue) calling
   ``CircuitBreakerAdapter.install(app)``.

Idempotent: a second run detects ``CircuitBreakerAdapter`` in the glue
and returns ``status="no_op"``.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir

MCP_TOOL = {
    "name": "fastapi_add_circuit_breaker",
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


_GLUE = '''\
"""Wire the circuit-breaker registry into the FastAPI app.

Delegates to the primitive + FastAPI adapter copied under `core/venous/`
by the `add_circuit_breaker` tool. Re-emitted idempotently on subsequent runs.
"""

from __future__ import annotations

from fastapi import FastAPI

from core.venous._adapters.fastapi.CircuitBreakerAdapter import breaker, install


def install_circuit_breakers(app: FastAPI) -> None:
    """Attach a named-breaker registry to *app.state.circuit_breakers*."""
    install(app)


# Re-export the Depends factory so routes can import from app.circuit_breaker.
__all__ = ["breaker", "install_circuit_breakers"]
'''


def add_circuit_breaker(inp: ToolInput) -> ToolResult:
    """Add circuit-breaker support by delegating to the shipped primitive + adapter."""
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
            notes=["Generate a base project first via fastapi_generate_project(...)."],
            execution_time_ms=_elapsed_ms(start),
        )

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


def _elapsed_ms(start: float) -> int:
    """Return elapsed ms since *start* (from ``time.monotonic()``)."""
    return int((time.monotonic() - start) * 1000)
