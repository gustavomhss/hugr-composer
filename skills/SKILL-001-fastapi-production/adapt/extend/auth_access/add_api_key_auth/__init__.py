"""TOOL-010: add_api_key_auth — API key authentication for FastAPI projects.

Orchestration only. Emitted code lives in ``templates/*.py.tmpl``. The tool
is idempotent: detects the ``APIKey`` model fingerprint and returns
``status="no_op"`` on repeat runs.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.migration_helper import find_migration_head
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

_HERE = Path(__file__).parent

# B0.12 bypass — the rate-limit fallback counter is per-worker by
# construction (each worker holds its own _LocalCounters instance).
# The Redis-primary path IS cross-worker durable; the fallback is the
# fail-degraded path documented in the warnings= disclosure below.
_SINGLE_PROCESS_OK: bool = True

MCP_TOOL = {
    "name": "fastapi_auth_add_api_key_auth",
    "description": "Add API key authentication alongside the existing JWT auth.",
    "tags": ["extend", "auth_access"],
    "entry": "add_api_key_auth",
}

_NOTES_SUCCESS = [
    "API-key model: app/models/api_key.py",
    "Hasher supports argon2id and sha256_pepper algorithms.",
    "Constant-time DUMMY_HASH prevents key-id enumeration timing attacks.",
    "Per-key rate limiting: Redis (atomic INCR+EXPIRE) with in-process fallback.",
    "Scope format: guards require resource:action; grants accept resource:action "
    "(wildcards *:* supported at eval) or bare read/write (any-resource action grant).",
    "Plaintext secret returned ONCE at creation; never stored, never logged.",
    "⚠ verify_secret uses hmac.compare_digest for sha256$$ branch (constant-time); "
    "argon2id branch relies on argon2-cffi internal compare.",
    "⚠ In-process rate-limit fallback is PER-WORKER only — cross-worker limits "
    "ARE NOT ENFORCED when Redis is absent.",
]
# B0.12 bypass disclosure — the rule's docstring requires a warnings=
# entry containing the substring "single-process" (case-insensitive).
# Surfaces the multi-worker degradation contract to agents at compose
# time so they cannot ship the tool blind to the trade-off.
_WARNINGS_SUCCESS = [
    "single-process fallback: rate-limit counter is per-worker when Redis is "
    "down (gunicorn -w N admits up to N * limit briefly during a Redis outage). "
    "Watch the rate_limit_redis_fallback_count metric to detect sustained "
    "fallback windows; for strict cross-worker enforcement keep Redis up.",
]
_NEXT_STEPS = [
    "Add API_KEY_PEPPER and API_KEY_RATE_LIMIT_PER_MINUTE to app/core/config.py settings.",
    "alembic upgrade head",
    "Include api_keys router in app/api/main.py (done automatically if file existed).",
    "Self-service keys may only be minted with scopes in GRANTABLE_SCOPES "
    "(default: bare 'read'/'write', which satisfy any resource:action guard). "
    "To allow resource-scoped grants set API_KEY_GRANTABLE_SCOPES="
    "'orders:read,billing:write' (resource:action literals; wildcards rejected).",
]
_PREREQ_NOTES = [
    "These prerequisites cannot be auto-created.",
    "Generate a base project first:",
    "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
]


def add_api_key_auth(inp: ToolInput) -> ToolResult:
    """Add API-key authentication to a FastAPI project."""
    start = time.monotonic()
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_ms(start))

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.BASE_MODEL,
        Prereq.MODELS_INIT,
        Prereq.CONFIG_SETTINGS,
        Prereq.ROUTES_INIT,
        Prereq.ALEMBIC_VERSIONS,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=_PREREQ_NOTES,
            execution_time_ms=_ms(start),
        )

    files_created: list[str] = []
    if scaffolded:
        files_created.extend(scaffolded)

    project = Path(inp.project_dir)
    app_dir = project / "app"

    model_file = app_dir / "models" / "api_key.py"
    if model_file.exists() and "APIKey" in model_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["APIKey model already present — api-key auth is already enabled, skipped."],
            execution_time_ms=_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create API-key auth files.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_ms(start),
        )

    files_modified: list[str] = []

    render_to(_HERE, "model.py.tmpl", dest=model_file, substitutions={})
    files_created.append(str(model_file))
    _patch_models_init(app_dir / "models" / "__init__.py")

    hasher_file = app_dir / "core" / "api_key_hasher.py"
    render_to(_HERE, "hasher.py.tmpl", dest=hasher_file, substitutions={})
    files_created.append(str(hasher_file))

    rate_limit_file = app_dir / "core" / "api_key_rate_limit.py"
    render_to(_HERE, "rate_limit.py.tmpl", dest=rate_limit_file, substitutions={})
    files_created.append(str(rate_limit_file))

    scopes_file = app_dir / "auth" / "api_key_scopes.py"
    render_to(_HERE, "scopes.py.tmpl", dest=scopes_file, substitutions={})
    files_created.append(str(scopes_file))

    deps_file = app_dir / "core" / "api_key_deps.py"
    render_to(_HERE, "deps.py.tmpl", dest=deps_file, substitutions={})
    files_created.append(str(deps_file))

    crud_file = app_dir / "crud" / "api_key.py"
    render_to(_HERE, "crud.py.tmpl", dest=crud_file, substitutions={})
    files_created.append(str(crud_file))

    schema_file = app_dir / "schemas" / "api_key.py"
    render_to(_HERE, "schemas.py.tmpl", dest=schema_file, substitutions={})
    files_created.append(str(schema_file))

    routes_file = app_dir / "api" / "routes" / "api_keys.py"
    render_to(_HERE, "routes.py.tmpl", dest=routes_file, substitutions={})
    files_created.append(str(routes_file))

    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        down_rev = find_migration_head(versions_dir) or "0001_initial"
        mig_file = versions_dir / "0010_add_api_key_auth.py"
        render_to(
            _HERE,
            "migration.py.tmpl",
            dest=mig_file,
            substitutions={"down_rev": down_rev},
        )
        files_created.append(str(mig_file))

    for path_str in files_created:
        p = Path(path_str)
        if p.suffix == ".py" and p.is_file():
            try:
                ast.parse(p.read_text())
            except SyntaxError as exc:
                return ToolResult(
                    status="error",
                    error=f"Generated file has syntax error: {p}: {exc}",
                    execution_time_ms=_ms(start),
                )

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=_NOTES_SUCCESS,
        warnings=_WARNINGS_SUCCESS,
        next_steps=_NEXT_STEPS,
        execution_time_ms=_ms(start),
    )


def _patch_models_init(models_init: Path) -> None:
    """Append ``from app.models.api_key import APIKey`` idempotently."""
    if not models_init.exists():
        return
    content = models_init.read_text()
    marker = "from app.models.api_key import APIKey"
    if marker in content:
        return
    if not content.endswith("\n"):
        content += "\n"
    content += f"{marker}  # noqa: F401\n"
    models_init.write_text(content)


def _patch_routes_init(routes_init: Path) -> None:
    """Register api_keys router in ``app/routes/__init__.py`` idempotently."""
    src = routes_init.read_text()
    import_line = "from app.api.routes.api_keys import router as api_keys_router"
    include_line = "api_router.include_router(api_keys_router)"
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


def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
