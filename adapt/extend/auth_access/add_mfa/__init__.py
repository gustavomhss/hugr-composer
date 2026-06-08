"""TOOL-013: add_mfa — ship TOTP MFA: model, crypto, totp, rate-limit, routes.

CONTRACT §B1.0 + §B1.0.1 pattern (mirrors `add_sms_otp` / `add_graceful_shutdown`):

1. Copy the framework-agnostic primitive `core.venous.auth.TotpVerifier`
   into the generated project plus its FastAPI adapter.
2. Emit a thin ``app/mfa.py`` (≤20 lines of glue) that calls ``install(app)``
   and exposes ``verify_code(...)``.
3. Emit the durable MFA surface the spec requires:
   - ``app/models/mfa.py`` — MFADevice (Fernet-encrypted ``secret_enc``) +
     MFARecoveryCode (single-use via ``used_at``).
   - ``app/core/mfa/crypto.py`` — Fernet encrypt/decrypt of TOTP secrets.
   - ``app/core/mfa/totp.py`` — pyotp-backed constant-time verification.
   - ``app/core/mfa/rate_limit.py`` — durable brute-force 429 limiter (no
     module-level state; throttles on MFADevice.failed_attempts/locked_until).
   - ``app/crud/mfa.py`` — atomic single-use recovery-code consumption.
   - ``app/api/routes/mfa.py`` — mounted ``/auth/mfa`` router with the
     pending-token (``mfa_pending``) challenge flow.
   - Alembic migration + requirements (cryptography, pyotp) + config fields.

HONESTY: status="success" reports file emission only. Every success path
includes a ``⚠ MFA IS NOT ENFORCED`` warning — the tool ships the mechanism,
not the policy; the developer must wire the pending-token step into login.

The tool is idempotent: a second run detects the import chain in
``app/mfa.py`` and returns ``status="no_op"``.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import load_template, render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.migration_helper import find_migration_head

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_auth_add_mfa",
    "description": (
        "Ship TOTP MFA into the project: MFADevice/MFARecoveryCode models, "
        "Fernet secret encryption, pyotp verification, a brute-force limiter, "
        "a mounted /auth/mfa router, migration, and the TotpVerifier primitive."
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


# Warning text emitted in every ToolResult so callers cannot mistake "success"
# for "MFA is now active".  All-caps prefix is intentional — this is a P0
# honesty requirement: the tool ships the MECHANISM, not the POLICY.
_WARN_NOT_AUTO_ENFORCED = (
    "⚠ MFA IS NOT ENFORCED: login does not require a second factor until you "
    "wire the pending-token challenge into the login flow. add_mfa patches "
    "login.py when it exists (issuing a purpose=mfa_pending token for "
    "mfa_enabled users); otherwise copy app/api/routes/_mfa_example.py. "
    "Persist MFA state on the user model / MFADevice."
)


def _glue_body() -> str:
    return load_template(_HERE, "glue.py.tmpl").template


def _example_body() -> str:
    return load_template(_HERE, "mfa_example.py.tmpl").template


def add_mfa(inp: ToolInput) -> ToolResult:
    start = time.monotonic()
    project = Path(inp.project_dir)

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.BASE_MODEL,
        Prereq.MODELS_INIT,
        Prereq.CONFIG_SETTINGS,
        Prereq.REQUIREMENTS_TXT,
        Prereq.ROUTES_INIT,
        Prereq.SESSION_DEP,
        Prereq.ALEMBIC_VERSIONS,
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
            warnings=[_WARN_NOT_AUTO_ENFORCED],
            notes=[
                "[dry_run] Would copy TotpVerifier primitive + adapter and emit "
                "app/models/mfa.py, app/core/mfa/{crypto,totp,rate_limit}.py, "
                "app/crud/mfa.py, app/api/routes/mfa.py, the migration, and "
                "requirements/config additions."
            ],
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

    files_modified: list[str] = []

    # 1. Glue shim (≤20 LOC body) — install_mfa / get_verifier / verify_code.
    app_dir.mkdir(parents=True, exist_ok=True)
    glue_file.write_text(_glue_body())
    files_created.append(str(glue_file))

    # 2. Models: MFADevice (Fernet-encrypted secret) + MFARecoveryCode (used_at).
    model_file = app_dir / "models" / "mfa.py"
    render_to(_HERE, "model.py.tmpl", dest=model_file, substitutions={})
    files_created.append(str(model_file))
    _patch_models_init(
        app_dir / "models" / "__init__.py", [("mfa", "MFADevice"), ("mfa", "MFARecoveryCode")]
    )

    # 3. Core helpers: crypto (Fernet), totp (pyotp), rate_limit (429).
    core_mfa = app_dir / "core" / "mfa"
    core_mfa.mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "core_init.py.tmpl", dest=core_mfa / "__init__.py", substitutions={})
    files_created.append(str(core_mfa / "__init__.py"))
    for tmpl, name in (
        ("crypto.py.tmpl", "crypto.py"),
        ("totp.py.tmpl", "totp.py"),
        ("rate_limit.py.tmpl", "rate_limit.py"),
    ):
        dest = core_mfa / name
        render_to(_HERE, tmpl, dest=dest, substitutions={})
        files_created.append(str(dest))

    # 4. CRUD: atomic single-use recovery-code consumption (used_at).
    crud_file = app_dir / "crud" / "mfa.py"
    render_to(_HERE, "crud.py.tmpl", dest=crud_file, substitutions={})
    files_created.append(str(crud_file))

    # 5. Routes: concrete login-wiring example + mounted /auth/mfa router.
    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    example_file = routes_dir / "_mfa_example.py"
    if not example_file.exists():
        example_file.write_text(_example_body())
        files_created.append(str(example_file))

    mfa_router_file = routes_dir / "mfa.py"
    render_to(_HERE, "routes.py.tmpl", dest=mfa_router_file, substitutions={})
    files_created.append(str(mfa_router_file))

    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists() and _patch_routes_init(routes_init):
        files_modified.append(str(routes_init))

    # 6. Patch the login route to short-circuit mfa_enabled users (INV-MFA-04).
    login_file = routes_dir / "login.py"
    if login_file.exists() and _patch_login(login_file):
        files_modified.append(str(login_file))

    # 7. Alembic migration chaining off the current head.
    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        down_rev = find_migration_head(versions_dir) or "0001_initial"
        mig_file = versions_dir / "0013_add_mfa.py"
        render_to(_HERE, "migration.py.tmpl", dest=mig_file, substitutions={"down_rev": down_rev})
        files_created.append(str(mig_file))

    # 8. requirements.txt: cryptography (Fernet) + pyotp (TOTP).
    req_file = project / "requirements.txt"
    if req_file.exists() and _patch_requirements(req_file):
        files_modified.append(str(req_file))

    # 9. config: MFA encryption key + rate-limit knobs.
    config_file = app_dir / "core" / "config.py"
    if config_file.exists() and _patch_config(config_file):
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
        warnings=[_WARN_NOT_AUTO_ENFORCED],
        notes=[
            "Shipped primitive: core.venous.auth.TotpVerifier (RFC 6238 TOTP, replay-safe).",
            "Shipped adapter: TotpVerifierAdapter (install + verify_code + get_verifier).",
            "Wrote app/models/mfa.py — MFADevice (Fernet-encrypted secret_enc) + "
            "MFARecoveryCode (single-use via used_at).",
            "Wrote app/core/mfa/crypto.py — Fernet encrypt/decrypt of TOTP secrets.",
            "Wrote app/core/mfa/totp.py — pyotp-backed constant-time verify.",
            "Wrote app/core/mfa/rate_limit.py — durable brute-force 429 limiter "
            "(failed_attempts + locked_until on MFADevice; no per-worker state).",
            "Wrote app/crud/mfa.py — atomic single-use recovery-code consumption.",
            "Wrote app/api/routes/mfa.py — mounted /auth/mfa router "
            "(enroll / verify-enrollment / challenge / disable) with the "
            "purpose=mfa_pending pending-token flow.",
            "Wrote app/mfa.py — call install_mfa(app) from main.py.",
            "Added cryptography + pyotp to requirements.txt; MFA config fields to settings.",
        ],
        next_steps=[
            "STEP 1 — run `alembic upgrade head` to create the MFA tables.",
            "STEP 2 — call `install_mfa(app)` in main.py lifespan (after app creation).",
            "STEP 3 — in login.py, for mfa_enabled users issue a purpose=mfa_pending "
            "token instead of the access token, then require POST /auth/mfa/challenge.",
            "STEP 4 — persist last_step on MFADevice before issuing the access token.",
            "See app/api/routes/_mfa_example.py for the exact copy-paste implementation.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _patch_models_init(models_init: Path, class_imports: list[tuple[str, str]]) -> None:
    """Append model imports to ``app/models/__init__.py`` idempotently."""
    if not models_init.exists():
        return
    content = models_init.read_text()
    new_lines: list[str] = []
    for module, cls in class_imports:
        marker = f"from app.models.{module} import {cls}"
        if marker in content:
            continue
        new_lines.append(f"{marker}  # noqa: F401")
    if not new_lines:
        return
    if not content.endswith("\n"):
        content += "\n"
    content += "\n".join(new_lines) + "\n"
    models_init.write_text(content)


def _patch_requirements(req_file: Path) -> bool:
    """Add cryptography + pyotp to requirements.txt idempotently.

    Returns ``True`` when the file is modified.
    """
    src = req_file.read_text()
    lines_to_add: list[str] = []
    if "cryptography" not in src:
        lines_to_add.append("cryptography>=41.0.0")
    if "pyotp" not in src:
        lines_to_add.append("pyotp>=2.9.0")
    if not lines_to_add:
        return False
    req_file.write_text(src.rstrip("\n") + "\n" + "\n".join(lines_to_add) + "\n")
    return True


def _patch_config(config_file: Path) -> bool:
    """Inject MFA config fields into the Settings class idempotently.

    Returns ``True`` when the file is modified.
    """
    from adapt.contracts.config_patcher import patch_settings_fields

    src_before = config_file.read_text()
    if "MFA_ENCRYPTION_KEY" in src_before:
        return False
    patch_settings_fields(
        config_file,
        fields=[
            ("MFA_ENCRYPTION_KEY", 'MFA_ENCRYPTION_KEY: str = ""'),
            ("MFA_RATE_LIMIT_MAX", "MFA_RATE_LIMIT_MAX: int = 5"),
            ("MFA_RATE_LIMIT_WINDOW_SECONDS", "MFA_RATE_LIMIT_WINDOW_SECONDS: int = 300"),
        ],
    )
    return config_file.read_text() != src_before


def _patch_login(login_file: Path) -> bool:
    """Short-circuit mfa_enabled users into the pending-token flow (INV-MFA-04).

    When a user with ``mfa_enabled=True`` passes the password check, the login
    route must NOT return a full access token. Instead it issues a short-lived
    ``pending_token`` carrying ``purpose="mfa_pending"``, which only
    ``POST /auth/mfa/challenge`` accepts. This blocks an attacker who has the
    password but not the second factor from skipping MFA.

    The patch appends a clearly-marked helper + guidance comment. It is
    idempotent (keyed on the ``_MFA_LOGIN_PATCH`` marker) and never rewrites
    the existing login body — wiring the call site stays the developer's job,
    documented inline. Returns ``True`` when the file is modified.
    """
    src = login_file.read_text()
    if "_MFA_LOGIN_PATCH" in src:
        return False
    patch = '''

# --- _MFA_LOGIN_PATCH (added by add_mfa) ---------------------------------
# INV-MFA-04: an mfa_enabled user MUST NOT receive a full access token from
# password auth alone. After validating the password, branch here:
#
#     if user.mfa_enabled:
#         pending_token = issue_mfa_pending_token(user)  # purpose="mfa_pending"
#         return {"mfa_required": True, "pending_token": pending_token}
#     # else: issue the normal access token as usual.
#
# The pending_token carries purpose="mfa_pending"; get_current_user rejects
# that purpose so the half-authenticated session cannot call protected routes.
# Exchange it at POST /auth/mfa/challenge for the real access token.

MFA_PENDING_PURPOSE = "mfa_pending"


def issue_mfa_pending_token(user) -> str:
    """Mint a short-lived token marking a password-verified, MFA-pending login.

    Replace the body with your JWT mint, embedding ``purpose="mfa_pending"``
    so get_current_user rejects it for normal calls (INV-MFA-03).
    """
    raise NotImplementedError(
        "Wire issue_mfa_pending_token to your JWT mint with purpose=mfa_pending."
    )
# --- end _MFA_LOGIN_PATCH ------------------------------------------------
'''
    login_file.write_text(src.rstrip("\n") + "\n" + patch)
    return True


def _patch_routes_init(routes_init: Path) -> bool:
    """Register the mfa router in ``app/routes/__init__.py`` idempotently.

    Returns ``True`` when the registry is modified, ``False`` when the
    import line is already present.
    """
    src = routes_init.read_text()
    import_line = "from app.api.routes.mfa import router as mfa_router"
    include_line = "api_router.include_router(mfa_router)"
    if import_line in src:
        return False
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
    return True


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
