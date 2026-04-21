"""TOOL-057: add_rate_limiting — token-bucket rate limiting for FastAPI.

Follows the CONTRACT §B1.0 + §B1.0.1 pattern:

1. Copy the framework-agnostic primitive
   ``core.venous.resiliency.RateLimiter`` into the generated project.
2. Copy the FastAPI adapter
   ``core.venous._adapters.fastapi.RateLimiterAdapter``.
3. Emit a thin ``app/rate_limit.py`` (≤ 20 lines of glue) that calls
   ``RateLimiterAdapter.install(app, ...)``.

The tool is idempotent: a second run detects ``RateLimiterAdapter`` in the
glue file and returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_rate_limiting import add_rate_limiting

    result = add_rate_limiting(ToolInput(project_dir="/path/to/project"))
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir

MCP_TOOL = {
    "name": "fastapi_resiliency_add_rate_limiting",
    "description": (
        "Copy RateLimiter primitive + FastAPI adapter into the project and "
        "wire a ≤20-line app/rate_limit.py caller."
    ),
    "tags": ["extend", "infrastructure", "security"],
    "entry": "add_rate_limiting",
    "imports_primitives": [
        "core.venous.resiliency.RateLimiter",
    ],
    "imports_adapters": [
        "core.venous._adapters.fastapi.RateLimiterAdapter",
    ],
}


_GLUE = '''\
"""Wire token-bucket rate limiting into the FastAPI app.

Delegates to the primitive + FastAPI adapter copied under `core/venous/`
by the `add_rate_limiting` tool. Re-emitted idempotently on subsequent runs.
"""

from __future__ import annotations

import os

from fastapi import FastAPI

from core.venous._adapters.fastapi.RateLimiterAdapter import install


def install_rate_limiting(app: FastAPI) -> None:
    """Attach a token-bucket rate limiter middleware to *app*."""
    install(
        app,
        rate_per_second=float(os.getenv("RATE_LIMIT_PER_SECOND", "100")),
        burst=int(os.getenv("RATE_LIMIT_BURST", "200")),
        key=os.getenv("RATE_LIMIT_KEY", "ip"),  # type: ignore[arg-type]
    )
'''


def add_rate_limiting(inp: ToolInput) -> ToolResult:
    """Add rate limiting by delegating to the shipped primitive + adapter."""
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
    glue_file = app_dir / "rate_limit.py"

    if glue_file.exists() and "RateLimiterAdapter" in glue_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["Rate limiting already wired via the FastAPI adapter."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would copy RateLimiter primitive + FastAPI adapter "
                "and write app/rate_limit.py calling RateLimiterAdapter.install(app)."
            ],
            next_steps=["Re-run without dry_run=True to apply."],
            execution_time_ms=_elapsed_ms(start),
        )

    from generators.scaffold_venous import ensure_primitives

    manifest = ensure_primitives(
        str(project),
        names=["core.venous.resiliency.RateLimiter"],
        adapters=["core.venous._adapters.fastapi.RateLimiterAdapter"],
    )
    files_created.append(manifest.path)

    app_dir.mkdir(parents=True, exist_ok=True)
    glue_file.write_text(_GLUE)
    files_created.append(str(glue_file))

    files_modified: list[str] = []
    config_file = app_dir / "core" / "config.py"
    if config_file.exists() and "RATE_LIMIT_PER_SECOND" not in config_file.read_text():
        from adapt.contracts.config_patcher import patch_settings_fields

        patch_settings_fields(
            config_file,
            fields=[
                ("RATE_LIMIT_PER_SECOND", "RATE_LIMIT_PER_SECOND: float = 100.0"),
                ("RATE_LIMIT_BURST", "RATE_LIMIT_BURST: int = 200"),
                ("RATE_LIMIT_KEY", 'RATE_LIMIT_KEY: str = "ip"'),
            ],
        )
        files_modified.append(str(config_file))

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
            "Shipped primitive: core.venous.resiliency.RateLimiter.",
            "Shipped adapter: core.venous._adapters.fastapi.RateLimiterAdapter.",
            "Wrote app/rate_limit.py — call install_rate_limiting(app) from main.py.",
            "429 + Retry-After emitted automatically when the bucket is empty.",
        ],
        next_steps=[
            "Import install_rate_limiting in app/main.py and invoke it after FastAPI() construction.",
            "Set RATE_LIMIT_PER_SECOND / RATE_LIMIT_BURST / RATE_LIMIT_KEY in .env to override defaults.",
            "Add key='user' or 'user_endpoint' to scope buckets per authenticated user.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _elapsed_ms(start: float) -> int:
    """Return elapsed ms since *start* (from ``time.monotonic()``)."""
    return int((time.monotonic() - start) * 1000)
