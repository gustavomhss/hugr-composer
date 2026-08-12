"""TOOL-107: add_request_signing — HMAC request signing (Stripe/AWS Sig V4 pattern).

Orchestration only. Emitted code lives in ``templates/*.py.tmpl``.

Writes a ``HMACSigner`` utility, a ``SignatureVerifier`` FastAPI dependency,
a ``NonceStore`` for replay prevention, and middleware that validates every
signed request.  Canonical string: ``METHOD\\nPATH\\nSORTED_QUERY\\nHEADERS\\nSHA256_BODY``.
Timestamp window defaults to 5 minutes.  Nonce replay prevention via in-process
TTL store (Redis-backed when available).

Idempotent: a second run detects ``class HMACSigner`` in
``app/core/signing/signer.py`` and returns ``status="no_op"``.
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
    "name": "fastapi_auth_add_request_signing",
    "description": (
        "Add HMAC request signing (Stripe/AWS Sig V4 pattern) with canonical string "
        "construction, timestamp window, nonce replay prevention, and a FastAPI "
        "SignatureVerifier dependency."
    ),
    "tags": ["extend", "auth_access", "security"],
    "entry": "add_request_signing",
    "imports_primitives": [],
    "imports_adapters": [],

}

_NOTES_SUCCESS = [
    "HMACSigner + SignatureVerifier dependency installed.",
    "Canonical string: METHOD\\nPATH\\nSORTED_QUERY\\nHEADERS\\nSHA256(body).",
    "Timestamp window: REQUEST_SIGNING_TIMESTAMP_WINDOW_S (default 300s).",
    "Nonce replay prevention: in-process TTL dict, Redis-backed when available.",
    "Use Depends(verify_signature) on any route that requires signing.",
]
_NEXT_STEPS = [
    "Set REQUEST_SIGNING_SECRET in your .env file.",
    "Add REQUEST_SIGNING_TIMESTAMP_WINDOW_S=300 to .env (optional).",
    "Apply Depends(verify_signature) to protected routes or add middleware.",
    "Use HMACSigner.sign(request) in your SDK clients.",
]


def add_request_signing(inp: ToolInput) -> ToolResult:
    """Add HMAC request signing to a FastAPI project."""
    start = time.monotonic()

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.CONFIG_SETTINGS,
        Prereq.ROUTES_INIT,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=["Generate a base project first."],
            execution_time_ms=_elapsed_ms(start),
        )

    project = Path(inp.project_dir)
    app_dir = project / "app"
    signer_file = app_dir / "core" / "signing" / "signer.py"

    if signer_file.exists() and "class HMACSigner" in signer_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["Request signing already installed — skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=["[dry_run] Would install HMAC request signing."],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded)
    files_modified: list[str] = []

    render_to(_HERE, "signer.py.tmpl", dest=signer_file, substitutions={})
    files_created.append(str(signer_file))

    nonce_file = app_dir / "core" / "signing" / "nonce_store.py"
    render_to(_HERE, "nonce_store.py.tmpl", dest=nonce_file, substitutions={})
    files_created.append(str(nonce_file))

    deps_file = app_dir / "core" / "signing" / "deps.py"
    render_to(_HERE, "deps.py.tmpl", dest=deps_file, substitutions={})
    files_created.append(str(deps_file))

    middleware_file = app_dir / "middleware" / "request_signing.py"
    render_to(_HERE, "middleware.py.tmpl", dest=middleware_file, substitutions={})
    files_created.append(str(middleware_file))

    config_file = app_dir / "core" / "config.py"
    if config_file.is_file():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.is_file():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

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
    """Inject REQUEST_SIGNING_* fields inside the Settings class body — idempotent."""
    src = config_file.read_text()
    if "REQUEST_SIGNING_SECRET" in src:
        return
    fields = (
        '    REQUEST_SIGNING_SECRET: str = "changethis-signing-secret"\n'
        "    REQUEST_SIGNING_TIMESTAMP_WINDOW_S: int = 300\n"
    )
    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    if anchor in src:
        src = src.replace(anchor, anchor + "\n" + fields.rstrip())
    else:
        target = "settings = Settings()"
        if target in src:
            src = src.replace(target, fields + "\n" + target)
        else:
            src = src.rstrip("\n") + "\n" + fields
    config_file.write_text(src)


def _patch_routes_init(routes_init: Path) -> None:
    """Add comment pointing to verify_signature dependency — idempotent."""
    content = routes_init.read_text()
    marker = "app.core.signing.deps"
    if marker in content:
        return
    addition = (
        "\n# Request signing: use Depends(verify_signature) on protected routes.\n"
        "# from app.core.signing.deps import verify_signature  # noqa: F401\n"
    )
    if not content.endswith("\n"):
        content += "\n"
    content += addition
    routes_init.write_text(content)


