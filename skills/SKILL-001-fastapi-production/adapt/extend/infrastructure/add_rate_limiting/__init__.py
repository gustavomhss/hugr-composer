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
"""

from __future__ import annotations

import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

_HERE = Path(__file__).parent

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


def add_rate_limiting(inp: ToolInput) -> ToolResult:
    """Add rate limiting by delegating to the shipped primitive + adapter."""
    start = time.monotonic()

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_ms(start))

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
            execution_time_ms=_ms(start),
        )

    project = Path(inp.project_dir)
    files_created: list[str] = list(scaffolded or [])
    app_dir = project / "app"
    glue_file = app_dir / "rate_limit.py"

    if glue_file.exists() and "RateLimiterAdapter" in glue_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["Rate limiting already wired via the FastAPI adapter."],
            execution_time_ms=_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would copy RateLimiter primitive + FastAPI adapter "
                "and write app/rate_limit.py calling RateLimiterAdapter.install(app)."
            ],
            next_steps=["Re-run without dry_run=True to apply."],
            execution_time_ms=_ms(start),
        )

    from generators.scaffold_venous import ensure_primitives

    manifest = ensure_primitives(
        str(project),
        names=["core.venous.resiliency.RateLimiter"],
        adapters=["core.venous._adapters.fastapi.RateLimiterAdapter"],
    )
    files_created.append(manifest.path)

    app_dir.mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "rate_limit_glue.py.tmpl", dest=glue_file, substitutions={})
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

    _emit_project_test(project, files_created)

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
        execution_time_ms=_ms(start),
    )


def _emit_project_test(project: Path, created: list[str]) -> None:
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_rate_limiting_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_rate_limiting_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
