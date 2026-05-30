"""TOOL-074: add_social_login — Google/GitHub/Apple OAuth2 social login.

Orchestration only. Emitted code lives in ``templates/*.py.tmpl``. Account
linking matches by verified email; falls back to creating a new user.
Idempotent: detects ``SocialAccount`` and returns ``status="no_op"`` on repeat.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.config_patcher import patch_settings_fields
from adapt.contracts.migration_helper import find_migration_head
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_auth_add_social_login",
    "description": (
        "Add Google/GitHub/Apple OAuth2 social login with account linking to a FastAPI project."
    ),
    "tags": ["extend", "auth_access"],
    "entry": "add_social_login",
}

_NOTES_SUCCESS = [
    "Providers enabled: Google, GitHub, Apple.",
    "Account linking: email-based — matches existing user by verified email.",
    "New users auto-provisioned when no email match found.",
    "httpx imported lazily inside provider methods (no top-level SDK import).",
    "Tokens never stored; only JWT issued after successful OAuth exchange.",
    "Apple id_token RS256 signature verified against appleid.apple.com/auth/keys "
    "JWKS (cached 1h); iss/aud/exp claims enforced. Requires APPLE_CLIENT_ID "
    "to be set (callback refuses to verify without an audience).",
    "⚠ STATE PARAMETER IS NOT VALIDATED on the callback (CSRF protection is "
    "advisory-only — state is generated at /{provider}/login but the "
    "/{provider}/callback endpoint accepts any value). Tracked: R5-O4-C1.",
]
_NEXT_STEPS = [
    "Add GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GITHUB_CLIENT_ID, "
    "GITHUB_CLIENT_SECRET, APPLE_CLIENT_ID, APPLE_CLIENT_SECRET, "
    "APPLE_TEAM_ID, APPLE_KEY_ID, APPLE_PRIVATE_KEY to settings.",
    "alembic upgrade head",
    "Set SOCIAL_LOGIN_CALLBACK_BASE_URL to your public domain.",
]
_PREREQ_NOTES = [
    "These prerequisites cannot be auto-created.",
    "Generate a base project first:",
    "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
]


def add_social_login(inp: ToolInput) -> ToolResult:
    """Add social login (Google, GitHub, Apple) to a FastAPI project."""
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

    files_created: list[str] = list(scaffolded)
    project = Path(inp.project_dir)
    app_dir = project / "app"

    model_file = app_dir / "models" / "social_account.py"
    if model_file.exists() and "SocialAccount" in model_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["SocialAccount model already present — social login already enabled, skipped."],
            execution_time_ms=_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create social login files (Google, GitHub, Apple).",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_ms(start),
        )

    files_modified: list[str] = []

    render_to(_HERE, "model.py.tmpl", dest=model_file, substitutions={})
    files_created.append(str(model_file))
    _patch_models_init(app_dir / "models" / "__init__.py")

    social_config_file = app_dir / "auth" / "social_config.py"
    render_to(_HERE, "social_config.py.tmpl", dest=social_config_file, substitutions={})
    files_created.append(str(social_config_file))

    social_file = app_dir / "auth" / "social.py"
    render_to(_HERE, "social_auth.py.tmpl", dest=social_file, substitutions={})
    files_created.append(str(social_file))

    auth_init = app_dir / "auth" / "__init__.py"
    if not auth_init.exists():
        auth_init.parent.mkdir(parents=True, exist_ok=True)
        auth_init.write_text('"""Auth package."""\n')
        files_created.append(str(auth_init))

    schema_file = app_dir / "schemas" / "social.py"
    render_to(_HERE, "schemas.py.tmpl", dest=schema_file, substitutions={})
    files_created.append(str(schema_file))

    routes_file = app_dir / "api" / "routes" / "social_auth.py"
    render_to(_HERE, "routes.py.tmpl", dest=routes_file, substitutions={})
    files_created.append(str(routes_file))

    crud_file = routes_file.parent / "_social_crud.py"
    render_to(_HERE, "social_crud.py.tmpl", dest=crud_file, substitutions={})
    files_created.append(str(crud_file))

    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        down_rev = find_migration_head(versions_dir) or "0001_initial"
        mig_file = versions_dir / "0074_add_social_login.py"
        render_to(
            _HERE,
            "migration.py.tmpl",
            dest=mig_file,
            substitutions={"down_rev": down_rev},
        )
        files_created.append(str(mig_file))

    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
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
                    execution_time_ms=_ms(start),
                )

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=_NOTES_SUCCESS,
        next_steps=_NEXT_STEPS,
        execution_time_ms=_ms(start),
    )


def _patch_models_init(models_init: Path) -> None:
    """Append ``from app.models.social_account import SocialAccount`` idempotently."""
    if not models_init.exists():
        return
    content = models_init.read_text()
    marker = "from app.models.social_account import SocialAccount"
    if marker in content:
        return
    if not content.endswith("\n"):
        content += "\n"
    content += f"{marker}  # noqa: F401\n"
    models_init.write_text(content)


def _patch_config(config_file: Path) -> None:
    """Inject social login config fields into Settings class idempotently."""
    patch_settings_fields(
        config_file,
        fields=[
            ("GOOGLE_CLIENT_ID", 'GOOGLE_CLIENT_ID: str = ""'),
            ("GOOGLE_CLIENT_SECRET", 'GOOGLE_CLIENT_SECRET: str = ""'),
            ("GITHUB_CLIENT_ID", 'GITHUB_CLIENT_ID: str = ""'),
            ("GITHUB_CLIENT_SECRET", 'GITHUB_CLIENT_SECRET: str = ""'),
            ("APPLE_CLIENT_ID", 'APPLE_CLIENT_ID: str = ""'),
            ("APPLE_CLIENT_SECRET", 'APPLE_CLIENT_SECRET: str = ""'),
            ("APPLE_TEAM_ID", 'APPLE_TEAM_ID: str = ""'),
            ("APPLE_KEY_ID", 'APPLE_KEY_ID: str = ""'),
            ("APPLE_PRIVATE_KEY", 'APPLE_PRIVATE_KEY: str = ""'),
            (
                "SOCIAL_LOGIN_CALLBACK_BASE_URL",
                'SOCIAL_LOGIN_CALLBACK_BASE_URL: str = "http://localhost:8000"',
            ),
        ],
    )


def _patch_routes_init(routes_init: Path) -> None:
    """Register social_auth router in ``app/routes/__init__.py`` idempotently."""
    src = routes_init.read_text()
    import_line = "from app.api.routes.social_auth import router as social_auth_router"
    include_line = "api_router.include_router(social_auth_router)"
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
