"""TOOL-013: add_mfa — ship TotpVerifier primitive + FastAPI adapter.

CONTRACT §B1.0 + §B1.0.1 pattern (mirrors `add_graceful_shutdown`):

1. Copy the framework-agnostic primitive `core.venous.auth.TotpVerifier`
   into the generated project.
2. Copy the FastAPI adapter `core.venous._adapters.fastapi.TotpVerifierAdapter`
   alongside it.
3. Emit a thin ``app/mfa.py`` (≤20 lines of glue) that calls
   ``install(app)`` and exposes ``verify_totp(secret, code, last_step)``.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir

MCP_TOOL = {
    "name": "fastapi_auth_add_mfa",
    "description": (
        "Copy TotpVerifier primitive + FastAPI adapter into the project and "
        "wire a ≤20-line app/mfa.py caller."
    ),
    "tags": ["extend", "auth_access"],
    "entry": "add_mfa",
    "imports_primitives": [
        "core.venous.auth.TotpVerifier",
    ],
    "imports_adapters": [
        "core.venous._adapters.fastapi.TotpVerifierAdapter",
    ],
}


_GLUE = '''\
"""Wire MFA (TOTP) into the FastAPI app.

Delegates to `TotpVerifierAdapter` copied under `core/venous/` by
`add_mfa`. Hand-editing is safe but the file is re-emitted idempotently
on subsequent tool runs.
"""

from __future__ import annotations

from fastapi import FastAPI

from core.venous._adapters.fastapi.TotpVerifierAdapter import (
    get_verifier,
    install as _install,
    verify_code,
)


def install_mfa(app: FastAPI):
    """Attach a StandardTotpVerifier to app.state.totp; return it."""
    return _install(app)


__all__ = ["install_mfa", "get_verifier", "verify_code"]
'''


def add_mfa(inp: ToolInput) -> ToolResult:
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
    glue_file = app_dir / "mfa.py"

    if glue_file.exists() and "TotpVerifierAdapter" in glue_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["MFA already wired via the TotpVerifier adapter."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=["[dry_run] Would copy TotpVerifier primitive + adapter and write app/mfa.py."],
            next_steps=["Re-run without dry_run=True to apply."],
            execution_time_ms=_elapsed_ms(start),
        )

    from generators.scaffold_venous import ensure_primitives

    manifest = ensure_primitives(
        str(project),
        names=["core.venous.auth.TotpVerifier"],
        adapters=["core.venous._adapters.fastapi.TotpVerifierAdapter"],
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
            "Shipped primitive: core.venous.auth.TotpVerifier (RFC 6238 TOTP, replay-safe).",
            "Shipped adapter: TotpVerifierAdapter (install + verify_code + get_verifier).",
            "Wrote app/mfa.py — call install_mfa(app) from main.py.",
        ],
        next_steps=[
            "Persist each user's secret (bytes) + last_used_step (int) on your user model.",
            "In /mfa/verify route: verify_code(verifier, secret=..., code=..., last_step=...).",
            "Return the returned step and persist it as the new last_used_step.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
