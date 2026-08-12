"""TOOL-115: add_dpop_tokens — RFC 9449 DPoP proof-of-possession for FastAPI.

Orchestration only. Emitted code lives in ``templates/*.py.tmpl``.

Implements RFC 9449 Demonstrating Proof of Possession (DPoP):

* ``app/core/dpop.py`` — nonce manager, proof verifier, and token binder.
* ``app/core/dpop_deps.py`` — ``require_dpop`` FastAPI dependency.
* ``app/api/routes/dpop_nonce.py`` — ``POST /auth/dpop/nonce`` endpoint.

FAPI 2.0 compliance: the proof JWT must include ``htm``, ``htu``, fresh
``iat`` (within ``DPOP_CLOCK_SKEW_S``), and ``jti``. Server-side nonce
injection mirrors RFC 9449 §8 when ``DPOP_NONCE_TTL_S > 0``.

PyJWT is imported lazily inside verification functions so the application
can boot without the library when DPoP is disabled.

Idempotency: a second run detects ``DPoPVerifier`` in ``app/core/dpop.py``
and returns ``status="no_op"``.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.tool_result import _elapsed_ms

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_auth_add_dpop_tokens",
    "description": (
        "Add RFC 9449 DPoP (Demonstrating Proof of Possession) with proof verification "
        "middleware, server-side nonce, token binding, and JWK key management. "
        "FAPI 2.0 compliant."
    ),
    "tags": ["extend", "auth_access"],
    "entry": "add_dpop_tokens",
    "imports_primitives": [],
    "imports_adapters": [],

}

_NOTES_SUCCESS = [
    "DPoP (RFC 9449) installed: proof verifier, server-side nonce,",
    "token binding, JWK key management, @require_dpop dependency,",
    "POST /auth/dpop/nonce endpoint. FAPI 2.0 compliant.",
    "PyJWT is imported lazily — app boots without it when DPOP_ENABLED=false.",
]
_NEXT_STEPS = [
    "Set DPOP_ENABLED=true in .env.",
    "pip install PyJWT>=2.9.0 cryptography>=42.0.0",
    "Use @require_dpop in routes that require proof-of-possession.",
    "Clients: generate an EC P-256 key pair, include DPoP header on each request.",
    "See app/api/deps/dpop.py for usage example.",
]
_PREREQ_NOTES = [
    "Generate a base project first:",
    "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
]


def add_dpop_tokens(inp: ToolInput) -> ToolResult:
    """Add RFC 9449 DPoP proof-of-possession to a FastAPI project."""
    start = time.monotonic()

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.CONFIG_SETTINGS,
        Prereq.ROUTES_INIT,
        Prereq.REQUIREMENTS_TXT,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=_PREREQ_NOTES,
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded)
    project = Path(inp.project_dir)
    app_dir = project / "app"

    dpop_core = app_dir / "core" / "dpop.py"
    if dpop_core.exists() and "DPoPVerifier" in dpop_core.read_text():
        return ToolResult(
            status="no_op",
            notes=["DPoPVerifier already present — skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create: app/core/dpop.py, "
                "app/api/deps/dpop.py, app/api/routes/dpop_nonce.py.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    render_to(_HERE, "dpop_core.py.tmpl", dest=dpop_core, substitutions={})
    files_created.append(str(dpop_core))

    deps_dpop = app_dir / "core" / "dpop_deps.py"
    render_to(_HERE, "dpop_deps.py.tmpl", dest=deps_dpop, substitutions={})
    files_created.append(str(deps_dpop))

    nonce_route = app_dir / "api" / "routes" / "dpop_nonce.py"
    render_to(_HERE, "dpop_nonce_route.py.tmpl", dest=nonce_route, substitutions={})
    files_created.append(str(nonce_route))

    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    requirements_file = project / "requirements.txt"
    if requirements_file.exists():
        _patch_requirements(requirements_file)
        files_modified.append(str(requirements_file))

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
        notes=_NOTES_SUCCESS,
        next_steps=_NEXT_STEPS,
        execution_time_ms=_elapsed_ms(start),
    )


def _patch_config(config_file: Path) -> None:
    """Inject DPoP settings into the Settings class body — idempotent."""
    src = config_file.read_text()
    if "DPOP_ENABLED" in src:
        return
    block = (
        "\n"
        "    # --- DPoP tokens (RFC 9449) — added by add_dpop_tokens tool ---\n"
        "    DPOP_ENABLED: bool = False\n"
        "    DPOP_NONCE_TTL_S: int = 300\n"
        "    DPOP_CLOCK_SKEW_S: int = 60\n"
    )
    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    if anchor in src:
        src = src.replace(anchor, anchor + "\n" + block.lstrip("\n"))
    else:
        settings_line = "settings = Settings()"
        if settings_line in src:
            src = src.replace(settings_line, block.lstrip("\n") + "\n\n" + settings_line)
        else:
            src = src.rstrip("\n") + "\n" + block
    config_file.write_text(src)


def _patch_routes_init(routes_init: Path) -> None:
    """Register the DPoP nonce router in app/routes/__init__.py — idempotent."""
    import_line = "from app.api.routes.dpop_nonce import router as dpop_nonce_router"
    include_line = "api_router.include_router(dpop_nonce_router)"
    src = routes_init.read_text()
    if import_line in src:
        return
    lines = src.splitlines()
    last_app_import_idx = -1
    for idx, line in enumerate(lines):
        if line.startswith("from app."):
            last_app_import_idx = idx
    if last_app_import_idx == -1:
        for idx, line in enumerate(lines):
            if "api_router" in line and "APIRouter()" in line:
                last_app_import_idx = idx - 1
                break
    lines.insert(last_app_import_idx + 1, import_line)
    last_include_idx = -1
    for idx, line in enumerate(lines):
        if line.startswith("api_router.include_router"):
            last_include_idx = idx
    if last_include_idx == -1:
        for idx, line in enumerate(lines):
            if "api_router" in line and "APIRouter()" in line:
                last_include_idx = idx
                break
    lines.insert(last_include_idx + 1, include_line)
    routes_init.write_text("\n".join(lines) + ("\n" if src.endswith("\n") else ""))


def _patch_requirements(requirements_file: Path) -> None:
    """Ensure PyJWT is listed in requirements.txt — idempotent."""
    src = requirements_file.read_text()
    if "PyJWT" in src or "pyjwt" in src.lower():
        return
    trailing = "" if src.endswith("\n") else "\n"
    requirements_file.write_text(src + trailing + "PyJWT>=2.9.0\n")


