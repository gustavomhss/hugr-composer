"""TOOL-075: add_passkey_auth — WebAuthn/FIDO2 passwordless authentication.

Orchestration only. Emitted code lives in ``templates/*.py.tmpl`` and is
rendered via :func:`adapt._base.render.render_to`. Idempotent: detects the
``Passkey`` model fingerprint and returns ``status="no_op"`` on repeat runs.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.config_patcher import patch_settings_fields
from adapt.contracts.migration_helper import find_migration_head
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_auth_add_passkey_auth",
    "description": ("Add WebAuthn/FIDO2 passwordless passkey authentication to a FastAPI project."),
    "tags": ["extend", "auth_access"],
    "entry": "add_passkey_auth",
    "imports_primitives": [],
    "imports_adapters": [],

}

_NOTES_SUCCESS = [
    "WebAuthn/FIDO2 passkey registration and login implemented.",
    "py_webauthn imported lazily inside WebAuthnManager methods.",
    "Credential public keys stored as LargeBinary (raw bytes).",
    "Registration/login challenges are Redis-backed under "
    "webauthn:challenge:{session_id} with TTL=WEBAUTHN_CHALLENGE_TTL_SECONDS "
    "(default 300 s). A per-worker dict fallback (encapsulated in "
    "_ChallengeStore) is used ONLY when Redis is unreachable; for any "
    "multi-worker deployment Redis must be reachable for begin→complete "
    "continuity across workers (closes R5-O4-H4).",
    "Sign count validated on every login to detect cloned credentials.",
    "⚠ require_user_verification=True is asserted by py_webauthn at verify time; if "
    "py_webauthn is absent at runtime the lazy import fails (no silent bypass).",
    "⚠ /passkeys/register/{begin,complete} REQUIRE an authenticated session "
    "(Depends(get_current_user)) — the credential is bound to current_user.id, "
    "NEVER to a client-supplied user_id. Registration is the "
    "\"add a passkey to my logged-in account\" flow; first-time passkey-only "
    "signup (no prior session) is OUT OF SCOPE and would need a separate "
    "partial-credential dep (R5-O4-C5).",
    "Write schemas declare ConfigDict(extra=\"forbid\") to block "
    "mass-assignment / key smuggling (R6-O3-P2). The credential field on "
    "Registration/Authentication CompleteRequest is intentionally typed "
    "dict[str, Any] (pragma: schema-any); the WebAuthn payload is "
    "validated end-to-end by py_webauthn (signature, RP-ID hash, "
    "origin, challenge, sign-count, UV flag).",
]
_NEXT_STEPS = [
    "pip install py_webauthn",
    "Add WEBAUTHN_RP_ID, WEBAUTHN_RP_NAME, WEBAUTHN_ORIGIN to settings.",
    "alembic upgrade head",
    "Set WEBAUTHN_RP_ID to your domain (e.g. 'example.com').",
    "Configure REDIS_URL so app.core.redis.get_redis_or_none() returns a "
    "live client — required for cross-worker challenge continuity. "
    "Single-instance deployments can omit Redis (the per-worker dict "
    "fallback honours WEBAUTHN_CHALLENGE_TTL_SECONDS).",
]
_PREREQ_NOTES = [
    "These prerequisites cannot be auto-created.",
    "Generate a base project first:",
    "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
]


def add_passkey_auth(inp: ToolInput) -> ToolResult:
    """Add WebAuthn/FIDO2 passkey authentication to a FastAPI project."""
    start = time.monotonic()
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

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
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded)
    project = Path(inp.project_dir)
    app_dir = project / "app"

    model_file = app_dir / "models" / "passkey.py"
    if model_file.exists() and "Passkey" in model_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["Passkey model already present — WebAuthn auth already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create WebAuthn/FIDO2 passkey files.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    render_to(_HERE, "model.py.tmpl", dest=model_file, substitutions={})
    files_created.append(str(model_file))
    _patch_models_init(app_dir / "models" / "__init__.py")

    webauthn_file = app_dir / "auth" / "webauthn.py"
    render_to(_HERE, "webauthn.py.tmpl", dest=webauthn_file, substitutions={})
    files_created.append(str(webauthn_file))

    auth_init = app_dir / "auth" / "__init__.py"
    if not auth_init.exists():
        auth_init.parent.mkdir(parents=True, exist_ok=True)
        auth_init.write_text('"""Auth package."""\n')
        files_created.append(str(auth_init))

    schema_file = app_dir / "schemas" / "passkey.py"
    render_to(_HERE, "schemas.py.tmpl", dest=schema_file, substitutions={})
    files_created.append(str(schema_file))

    routes_file = app_dir / "api" / "routes" / "passkeys.py"
    render_to(_HERE, "routes.py.tmpl", dest=routes_file, substitutions={})
    files_created.append(str(routes_file))

    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        down_rev = find_migration_head(versions_dir) or "0001_initial"
        mig_file = versions_dir / "0075_add_passkey_auth.py"
        render_to(
            _HERE,
            "migration.py.tmpl",
            dest=mig_file,
            substitutions={"down_rev": down_rev},
        )
        files_created.append(str(mig_file))

    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        patch_settings_fields(
            config_file,
            fields=[
                ("WEBAUTHN_RP_ID", 'WEBAUTHN_RP_ID: str = "localhost"'),
                ("WEBAUTHN_RP_NAME", 'WEBAUTHN_RP_NAME: str = "My App"'),
                ("WEBAUTHN_ORIGIN", 'WEBAUTHN_ORIGIN: str = "http://localhost:8000"'),
                ("WEBAUTHN_CHALLENGE_TTL_SECONDS", "WEBAUTHN_CHALLENGE_TTL_SECONDS: int = 300"),
            ],
        )
        if str(config_file) not in files_modified:
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
        notes=_NOTES_SUCCESS,
        next_steps=_NEXT_STEPS,
        execution_time_ms=_elapsed_ms(start),
    )


def _patch_models_init(models_init: Path) -> None:
    """Append ``from app.models.passkey import Passkey`` idempotently."""
    if not models_init.exists():
        return
    content = models_init.read_text()
    marker = "from app.models.passkey import Passkey"
    if marker in content:
        return
    if not content.endswith("\n"):
        content += "\n"
    content += f"{marker}  # noqa: F401\n"
    models_init.write_text(content)


def _patch_routes_init(routes_init: Path) -> None:
    """Register passkeys router in ``app/routes/__init__.py`` idempotently."""
    src = routes_init.read_text()
    import_line = "from app.api.routes.passkeys import router as passkeys_router"
    include_line = "api_router.include_router(passkeys_router)"
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


