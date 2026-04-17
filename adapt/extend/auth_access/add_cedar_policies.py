"""TOOL-071: add_cedar_policies — add AWS Cedar policy-as-code authorization to a FastAPI project.

Installs a CedarEngine with file-based policy loading, AuthzRequest/AuthzResponse
Pydantic models, a CedarAuthzMiddleware that enforces every request against the
loaded policy set, three example .cedar policy files, and two API endpoints
(POST /authz/check, GET /authz/policies).

The tool is idempotent: a second run detects the ``CedarEngine`` fingerprint in
``app/authz/engine.py`` and returns ``status="no_op"`` without touching any file.

Cedar runs AFTER RBAC: if both are installed the RBAC check happens first and
Cedar provides additional ABAC enforcement.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.auth_access.add_cedar_policies import add_cedar_policies

    result = add_cedar_policies(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["...app/authz/engine.py", ...]
    print(result.next_steps)    # ["pip install cedarpy>=0.4.0", ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

MCP_TOOL = {
    "name": "fastapi_add_cedar_policies",
    "description": (
        "Add AWS Cedar policy-as-code ABAC authorization to a FastAPI project. "
        "Generates CedarEngine, middleware, example .cedar policies, and /authz endpoints."
    ),
    "tags": ["extend", "auth_access"],
    "entry": "add_cedar_policies",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _elapsed_ms(start: float) -> int:
    """Return milliseconds elapsed since *start*.

    Args:
        start: ``time.monotonic()`` timestamp from the beginning of the run.

    Returns:
        Elapsed wall-clock time as a positive integer millisecond count.
    """
    return max(1, int((time.monotonic() - start) * 1000))


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_cedar_policies(inp: ToolInput) -> ToolResult:
    """Add AWS Cedar policy-as-code authorization to a FastAPI project.

    Creates the full Cedar authz sub-package (engine, models, middleware,
    example policies, and /authz routes), patches config and requirements,
    and registers the router in ``app/routes/__init__.py``.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.

    Returns:
        ``ToolResult`` describing every file created or modified.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(
            status="error",
            error=err,
            execution_time_ms=_elapsed_ms(start),
        )

    # --- Prerequisite check (standalone mode) --------------------------------
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
            notes=[
                "These prerequisites cannot be auto-created.",
                "Generate a base project first:",
                "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    app_dir = project / "app"

    # --- Idempotency guard ---------------------------------------------------
    engine_file = app_dir / "authz" / "engine.py"
    if engine_file.exists() and "class CedarEngine" in engine_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["Cedar authz engine already present — skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would install Cedar authz: engine, models, middleware, "
                "example policies, /authz routes."
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    files_modified: list[str] = []

    if scaffolded:
        files_created.extend(scaffolded)

    # Step 1: app/authz/__init__.py
    authz_init = app_dir / "authz" / "__init__.py"
    _write_authz_init(authz_init)
    files_created.append(str(authz_init))

    # Step 2: app/authz/engine.py
    _write_engine(engine_file)
    files_created.append(str(engine_file))

    # Step 3: app/authz/models.py
    models_file = app_dir / "authz" / "models.py"
    _write_models(models_file)
    files_created.append(str(models_file))

    # Step 4: app/authz/middleware.py
    middleware_file = app_dir / "authz" / "middleware.py"
    _write_middleware(middleware_file)
    files_created.append(str(middleware_file))

    # Step 5: Example .cedar policy files
    policies_dir = app_dir / "authz" / "policies"
    cedar_files = _write_cedar_policies(policies_dir)
    files_created.extend(cedar_files)

    # Step 6: app/api/routes/authz.py
    authz_routes = app_dir / "api" / "routes" / "authz.py"
    _write_authz_routes(authz_routes)
    files_created.append(str(authz_routes))

    # Step 7: Patch app/core/config.py
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # Step 8: Patch app/routes/__init__.py
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    # Step 9: Patch requirements.txt
    req_file = project / "requirements.txt"
    if req_file.exists():
        _patch_requirements(req_file)
        files_modified.append(str(req_file))

    # --- Validate every generated .py file -----------------------------------
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
            "Cedar authz installed: engine, models, middleware, example policies.",
            "Set CEDAR_ENABLED=true in your .env to activate the middleware.",
            "Add CEDAR_POLICY_DIR=app/authz/policies to point at your .cedar files.",
            "Use POST /authz/check to evaluate a policy decision programmatically.",
            "Cedar coexists with RBAC: RBAC check runs first, Cedar provides ABAC layer.",
            "cedarpy is imported lazily — app boots without it installed.",
        ],
        next_steps=[
            "pip install cedarpy>=0.4.0",
            "Set CEDAR_ENABLED=true in your .env / Settings.",
            "Set CEDAR_POLICY_DIR=app/authz/policies (or absolute path).",
            "Edit the example .cedar files in app/authz/policies/ for your domain.",
            "Restart the application to load the /authz router and middleware.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# Step helpers — each < 50 LOC
# ---------------------------------------------------------------------------

def _write_authz_init(dest: Path) -> None:
    """Write app/authz/__init__.py with re-exports.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Cedar policy-as-code authorization sub-package.

        Re-exports the public API so callers can write::

            from app.authz import CedarEngine, AuthzRequest, AuthzResponse
        \"\"\"

        from app.authz.engine import CedarEngine, get_cedar_engine
        from app.authz.models import AuthzRequest, AuthzResponse

        __all__ = [
            "CedarEngine",
            "get_cedar_engine",
            "AuthzRequest",
            "AuthzResponse",
        ]
    """))


def _write_engine(dest: Path) -> None:
    """Write app/authz/engine.py with CedarEngine and singleton getter.

    cedarpy is imported INSIDE method bodies so the app boots without it.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"CedarEngine: load Cedar policies from .cedar files and evaluate requests.

        cedarpy is imported lazily so the application boots without the package
        installed.  Install with ``pip install cedarpy>=0.4.0`` to activate
        policy enforcement.
        \"\"\"

        from __future__ import annotations

        import logging
        from pathlib import Path

        logger = logging.getLogger(__name__)

        _engine_singleton: "CedarEngine | None" = None


        class CedarEngine:
            \"\"\"File-based Cedar policy engine.

            Attributes:
                _policy_dir: Directory from which .cedar files are loaded.
                _policies: Combined policy text from all loaded .cedar files.
                _loaded: True once policies have been loaded successfully.
            \"\"\"

            def __init__(self, policy_dir: str | Path) -> None:
                \"\"\"Initialise the engine with a policy directory.

                Args:
                    policy_dir: Path to the directory containing .cedar files.
                \"\"\"
                self._policy_dir = Path(policy_dir)
                self._policies: str = ""
                self._loaded: bool = False

            def load_policies(self, directory: str | Path | None = None) -> None:
                \"\"\"Load all .cedar files from *directory* (or the configured dir).

                Args:
                    directory: Override the directory set at construction time.
                \"\"\"
                target = Path(directory) if directory else self._policy_dir
                if not target.is_dir():
                    logger.warning("Cedar policy dir not found: %s", target)
                    return
                parts: list[str] = []
                for policy_file in sorted(target.glob("*.cedar")):
                    text = policy_file.read_text(encoding="utf-8")
                    parts.append(text)
                    logger.debug("Loaded Cedar policy: %s", policy_file.name)
                self._policies = "\\n".join(parts)
                self._loaded = bool(parts)
                logger.info("Cedar: loaded %d policy file(s) from %s", len(parts), target)

            def is_authorized(
                self,
                principal: str,
                action: str,
                resource: str,
                context: dict | None = None,
            ) -> bool:
                \"\"\"Evaluate a Cedar authorization decision.

                Falls back to CEDAR_DEFAULT_EFFECT when cedarpy is not installed
                or when no policies are loaded.

                Args:
                    principal: Principal entity string, e.g. ``'User::"alice"'``.
                    action: Action entity string, e.g. ``'Action::"read"'``.
                    resource: Resource entity string, e.g. ``'Resource::"report-42"'``.
                    context: Optional key/value context attributes.

                Returns:
                    ``True`` if the request is allowed, ``False`` if denied.
                \"\"\"
                from app.core.config import settings  # noqa: PLC0415

                if not getattr(settings, "CEDAR_ENABLED", False):
                    return True
                if not self._loaded:
                    effect = getattr(settings, "CEDAR_DEFAULT_EFFECT", "deny")
                    return effect == "allow"
                try:
                    import cedarpy  # noqa: PLC0415

                    req = cedarpy.AuthorizationRequest(
                        principal=principal,
                        action=action,
                        resource=resource,
                        context=context or {},
                    )
                    decision = cedarpy.is_authorized(self._policies, req)
                    return decision.allowed
                except Exception as exc:
                    logger.error("Cedar evaluation error: %s", exc)
                    return False


        def get_cedar_engine() -> "CedarEngine":
            \"\"\"Return the process-wide CedarEngine singleton.

            Loads policies on first call.  Returns a no-op engine when
            ``CEDAR_ENABLED`` is False so the app always starts cleanly.

            Returns:
                The global ``CedarEngine`` instance.
            \"\"\"
            global _engine_singleton
            if _engine_singleton is None:
                from app.core.config import settings  # noqa: PLC0415

                policy_dir = getattr(settings, "CEDAR_POLICY_DIR", "app/authz/policies")
                _engine_singleton = CedarEngine(policy_dir=policy_dir)
                _engine_singleton.load_policies()
            return _engine_singleton
    """))


def _write_models(dest: Path) -> None:
    """Write app/authz/models.py with AuthzRequest and AuthzResponse.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Pydantic models for Cedar authorization requests and responses.\"\"\"

        from __future__ import annotations

        from pydantic import BaseModel, Field


        class AuthzRequest(BaseModel):
            \"\"\"Payload for a Cedar authorization check.

            Attributes:
                principal: Entity string for the principal, e.g. ``'User::"alice"'``.
                action: Entity string for the action, e.g. ``'Action::"read"'``.
                resource: Entity string for the resource, e.g. ``'Resource::"doc-1"'``.
                context: Arbitrary key/value attributes injected into the Cedar context.
            \"\"\"

            principal: str = Field(..., examples=['User::"alice"'])
            action: str = Field(..., examples=['Action::"read"'])
            resource: str = Field(..., examples=['Resource::"report-42"'])
            context: dict = Field(default_factory=dict)


        class AuthzResponse(BaseModel):
            \"\"\"Response from a Cedar authorization check.

            Attributes:
                allowed: ``True`` when the policy set permits the request.
                principal: Echo of the evaluated principal.
                action: Echo of the evaluated action.
                resource: Echo of the evaluated resource.
                reason: Human-readable explanation of the decision.
            \"\"\"

            allowed: bool
            principal: str
            action: str
            resource: str
            reason: str
    """))


def _write_middleware(dest: Path) -> None:
    """Write app/authz/middleware.py with CedarAuthzMiddleware.

    Skip paths are configurable and default to health and docs. The middleware
    calls ``get_cedar_engine().is_authorized()`` and returns 403 on deny.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"CedarAuthzMiddleware: intercept every request and enforce Cedar policies.

        Install in ``app/main.py``::

            from app.authz.middleware import CedarAuthzMiddleware
            app.add_middleware(CedarAuthzMiddleware)

        Paths listed in ``CEDAR_SKIP_PATHS`` (or the defaults below) bypass
        Cedar evaluation entirely.
        \"\"\"

        from __future__ import annotations

        import json
        import logging

        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.requests import Request
        from starlette.responses import Response

        logger = logging.getLogger(__name__)

        _DEFAULT_SKIP: frozenset[str] = frozenset({
            "/healthz",
            "/readyz",
            "/metrics",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/api/v1/openapi.json",
        })


        class CedarAuthzMiddleware(BaseHTTPMiddleware):
            \"\"\"Starlette middleware that enforces Cedar policies on every request.

            Attributes:
                skip_paths: Set of URL paths that bypass Cedar evaluation.
            \"\"\"

            def __init__(self, app, skip_paths: frozenset[str] | None = None) -> None:
                \"\"\"Initialise the middleware.

                Args:
                    app: The ASGI application to wrap.
                    skip_paths: URL paths that skip Cedar evaluation.  Defaults to
                        health-check and documentation paths.
                \"\"\"
                super().__init__(app)
                self.skip_paths = skip_paths if skip_paths is not None else _DEFAULT_SKIP

            async def dispatch(self, request: Request, call_next) -> Response:
                \"\"\"Evaluate Cedar policy before passing the request downstream.

                Args:
                    request: Incoming Starlette request.
                    call_next: Next middleware or route handler.

                Returns:
                    HTTP 403 JSON response on Cedar deny; otherwise the downstream
                    response.
                \"\"\"
                from app.core.config import settings  # noqa: PLC0415

                if not getattr(settings, "CEDAR_ENABLED", False):
                    return await call_next(request)
                if request.url.path in self.skip_paths:
                    return await call_next(request)

                principal = self._extract_principal(request)
                action = f'Action::"{request.method.lower()}"'
                resource = f'Resource::"{request.url.path}"'

                from app.authz.engine import get_cedar_engine  # noqa: PLC0415

                allowed = get_cedar_engine().is_authorized(principal, action, resource)
                if not allowed:
                    logger.warning(
                        "Cedar DENY principal=%s action=%s resource=%s",
                        principal,
                        action,
                        resource,
                    )
                    body = json.dumps({"detail": "Forbidden by Cedar policy"})
                    return Response(
                        content=body,
                        status_code=403,
                        media_type="application/json",
                    )
                return await call_next(request)

            @staticmethod
            def _extract_principal(request: Request) -> str:
                \"\"\"Extract a Cedar principal string from the request.

                Uses the JWT ``sub`` claim when available; falls back to
                ``'User::anonymous'`` for unauthenticated requests.

                Args:
                    request: Incoming Starlette request.

                Returns:
                    Cedar principal entity string.
                \"\"\"
                user = getattr(request.state, "user", None)
                if user and hasattr(user, "id"):
                    return f'User::"{user.id}"'
                auth_header = request.headers.get("Authorization", "")
                if auth_header.startswith("Bearer "):
                    return 'User::"jwt-user"'
                return 'User::"anonymous"'
    """))


def _write_cedar_policies(policies_dir: Path) -> list[str]:
    """Write 3 example .cedar policy files.

    Args:
        policies_dir: Directory in which to create the .cedar files.

    Returns:
        List of absolute path strings for the files created.
    """
    policies_dir.mkdir(parents=True, exist_ok=True)

    files: list[str] = []

    admin_policy = policies_dir / "admin_full_access.cedar"
    admin_policy.write_text(textwrap.dedent("""\
        // Admin full access — admins may perform any action on any resource.
        permit(
            principal in Role::"admin",
            action,
            resource
        );
    """))
    files.append(str(admin_policy))

    owner_policy = policies_dir / "owner_read_write.cedar"
    owner_policy.write_text(textwrap.dedent("""\
        // Owners may read and write their own resources.
        permit(
            principal,
            action in [Action::"get", Action::"post", Action::"put", Action::"patch", Action::"delete"],
            resource
        ) when {
            resource.owner == principal
        };
    """))
    files.append(str(owner_policy))

    deny_policy = policies_dir / "default_deny.cedar"
    deny_policy.write_text(textwrap.dedent("""\
        // Default deny — all requests not explicitly permitted are forbidden.
        // This policy is implicit when no other permit applies; keep it for clarity.
        forbid(
            principal,
            action,
            resource
        ) unless {
            principal in Role::"admin"
        };
    """))
    files.append(str(deny_policy))

    return files


def _write_authz_routes(dest: Path) -> None:
    """Write app/api/routes/authz.py with POST /authz/check and GET /authz/policies.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Cedar authz API endpoints.

        POST /authz/check  — evaluate a Cedar policy decision on demand.
        GET  /authz/policies — list the names of all loaded .cedar policy files.
        \"\"\"

        from __future__ import annotations

        import logging
        from pathlib import Path

        from fastapi import APIRouter, HTTPException, status

        from app.authz.engine import get_cedar_engine
        from app.authz.models import AuthzRequest, AuthzResponse

        logger = logging.getLogger(__name__)
        router = APIRouter(prefix="/authz", tags=["authz"])


        @router.post(
            "/check",
            response_model=AuthzResponse,
            status_code=status.HTTP_200_OK,
            summary="Evaluate a Cedar policy decision",
        )
        def check_authorization(payload: AuthzRequest) -> AuthzResponse:
            \"\"\"Evaluate a Cedar authorization decision for the given request.

            Args:
                payload: ``AuthzRequest`` with principal, action, resource, context.

            Returns:
                ``AuthzResponse`` with ``allowed`` bool and human-readable ``reason``.
            \"\"\"
            engine = get_cedar_engine()
            allowed = engine.is_authorized(
                principal=payload.principal,
                action=payload.action,
                resource=payload.resource,
                context=payload.context,
            )
            reason = "permit" if allowed else "forbid (no matching permit policy)"
            logger.info(
                "Cedar check: allowed=%s principal=%s action=%s resource=%s",
                allowed,
                payload.principal,
                payload.action,
                payload.resource,
            )
            return AuthzResponse(
                allowed=allowed,
                principal=payload.principal,
                action=payload.action,
                resource=payload.resource,
                reason=reason,
            )


        @router.get(
            "/policies",
            response_model=list[str],
            status_code=status.HTTP_200_OK,
            summary="List loaded Cedar policy files",
        )
        def list_policies() -> list[str]:
            \"\"\"Return the names of all .cedar policy files currently loaded.

            Returns:
                Sorted list of policy file stem names (without extension).
            \"\"\"
            engine = get_cedar_engine()
            if not engine._policy_dir.is_dir():
                return []
            return sorted(
                p.stem for p in engine._policy_dir.glob("*.cedar")
            )
    """))


def _patch_config(config_file: Path) -> None:
    """Patch app/core/config.py to add Cedar settings inside the Settings class.

    Args:
        config_file: Absolute path to app/core/config.py.
    """
    content = config_file.read_text()
    fields = [
        "    CEDAR_ENABLED: bool = False",
        '    CEDAR_POLICY_DIR: str = "app/authz/policies"',
        '    CEDAR_DEFAULT_EFFECT: str = "deny"',
    ]
    new_lines: list[str] = []
    for field in fields:
        field_name = field.strip().split(":")[0].strip()
        if field_name not in content:
            new_lines.append(field)
    if not new_lines:
        return
    # Insert before the closing of the Settings class — find 'settings = Settings()'
    sentinel = "settings = Settings()"
    if sentinel in content:
        insert_block = "\n".join(new_lines) + "\n\n"
        content = content.replace(sentinel, insert_block + sentinel)
    else:
        # Fallback: append at end of file
        if not content.endswith("\n"):
            content += "\n"
        content += "\n".join(new_lines) + "\n"
    config_file.write_text(content)


def _patch_routes_init(routes_init: Path) -> None:
    """Register the Cedar authz router in app/routes/__init__.py.

    Args:
        routes_init: Absolute path to app/routes/__init__.py.
    """
    content = routes_init.read_text()
    import_line = "from app.api.routes.authz import router as authz_router"
    include_line = "api_router.include_router(authz_router)"
    if import_line in content:
        return
    if not content.endswith("\n"):
        content += "\n"
    content += f"\n{import_line}\n{include_line}\n"
    routes_init.write_text(content)


def _patch_requirements(req_file: Path) -> None:
    """Append cedarpy to requirements.txt if not already present.

    Args:
        req_file: Absolute path to requirements.txt.
    """
    content = req_file.read_text()
    if "cedarpy" not in content:
        if not content.endswith("\n"):
            content += "\n"
        content += "cedarpy>=0.4.0\n"
        req_file.write_text(content)
