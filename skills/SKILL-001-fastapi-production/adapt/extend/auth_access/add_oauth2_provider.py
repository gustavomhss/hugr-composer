"""TOOL-011: add_oauth2_provider — ship TokenIntrospector + SessionStore primitives.

CONTRACT §B1.0 + §B1.0.1 pattern (mirrors `add_graceful_shutdown`):

1. Copy the framework-agnostic primitives `core.venous.auth.TokenIntrospector`
   and `core.venous.auth.SessionStore` into the generated project.
2. Copy the FastAPI adapter `core.venous._adapters.fastapi.OAuth2Adapter`
   alongside them.
3. Emit a thin ``app/oauth2.py`` (≤20 lines of glue) that wires both
   primitives into the FastAPI app via `OAuth2Adapter.install()` and
   exposes `current_claims(audience)` for route-level bearer auth.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir

MCP_TOOL = {
    "name": "fastapi_auth_add_oauth2_provider",
    "description": (
        "Copy TokenIntrospector + SessionStore primitives + FastAPI adapter "
        "into the project and wire a ≤20-line app/oauth2.py caller."
    ),
    "tags": ["extend", "auth_access"],
    "entry": "add_oauth2_provider",
    "imports_primitives": [
        "core.venous.auth.TokenIntrospector",
        "core.venous.auth.SessionStore",
    ],
    "imports_adapters": [
        "core.venous._adapters.fastapi.OAuth2Adapter",
    ],
}


_GLUE = '''\
"""Wire OAuth2 (introspection + sessions) into the FastAPI app.

Delegates to `OAuth2Adapter` copied under `core/venous/` by
`add_oauth2_provider`. Hand-editing is safe but the file is re-emitted
idempotently on subsequent tool runs.
"""

from __future__ import annotations

from fastapi import FastAPI

from core.venous._adapters.fastapi.OAuth2Adapter import (
    current_claims,
    install as _install,
)
from core.venous.auth.SessionStore.SessionStore import InMemorySessionStore


def install_oauth2(app: FastAPI, introspector, session_store=None) -> None:
    """Attach the introspector + session store to app.state."""
    _install(app, introspector=introspector, session_store=session_store or InMemorySessionStore())


__all__ = ["install_oauth2", "current_claims"]
'''


def add_oauth2_provider(inp: ToolInput) -> ToolResult:
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
    glue_file = app_dir / "oauth2.py"

    if glue_file.exists() and "OAuth2Adapter" in glue_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["OAuth2 already wired via the FastAPI adapter."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would copy TokenIntrospector + SessionStore primitives "
                "+ FastAPI adapter and write app/oauth2.py."
            ],
            next_steps=["Re-run without dry_run=True to apply."],
            execution_time_ms=_elapsed_ms(start),
        )

    from generators.scaffold_venous import ensure_primitives

    manifest = ensure_primitives(
        str(project),
        names=[
            "core.venous.auth.TokenIntrospector",
            "core.venous.auth.SessionStore",
        ],
        adapters=["core.venous._adapters.fastapi.OAuth2Adapter"],
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
            "Shipped primitives: TokenIntrospector (JWT+opaque), SessionStore (idle+absolute timeouts).",
            "Shipped adapter: OAuth2Adapter (Bearer scheme + current_claims dependency).",
            "Wrote app/oauth2.py — call install_oauth2(app, introspector) from main.py.",
        ],
        next_steps=[
            "Construct a CachingTokenIntrospector with your IssuerConfig + JwksFetcher.",
            "Call install_oauth2(app, introspector) after FastAPI() construction.",
            "Protect routes with `Depends(current_claims('your-api'))`.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
