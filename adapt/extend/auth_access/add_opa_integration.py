"""TOOL-072: add_opa_integration — add Open Policy Agent (OPA) integration to a FastAPI project.

Writes an OPAClient (httpx-based, lazy import, circuit breaker), OPA Pydantic
models, OPAMiddleware, example Rego policy files, and two management endpoints
(POST /authz/opa/check, GET /authz/opa/health).  Patches app/core/config.py
with OPA_URL / OPA_ENABLED / OPA_POLICY_PATH / OPA_TIMEOUT_MS and registers
the router in app/routes/__init__.py.

OPA runs as a sidecar; this tool generates the CLIENT side only.
The tool is idempotent: a second run detects the ``OPAClient`` fingerprint in
``app/authz/opa_client.py`` and returns ``status="no_op"`` without touching
any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.auth_access.add_opa_integration import add_opa_integration

    result = add_opa_integration(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # [".../app/authz/opa_client.py", ...]
    print(result.next_steps)    # ["docker run openpolicyagent/opa ...", ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites


MCP_TOOL = {
    "name": "fastapi_add_opa_integration",
    "description": (
        "Add Open Policy Agent (OPA) integration with circuit breaker, "
        "middleware, example Rego policies, and management endpoints."
    ),
    "tags": ["extend", "auth_access"],
    "entry": "add_opa_integration",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start* as an int.

    Args:
        start: ``time.monotonic()`` snapshot taken at function entry.

    Returns:
        Positive integer milliseconds elapsed.
    """
    return max(1, int((time.monotonic() - start) * 1000))


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def add_opa_integration(inp: ToolInput) -> ToolResult:
    """Add OPA integration to a FastAPI project.

    Creates OPAClient, OPA Pydantic models, OPAMiddleware, example Rego
    policies, and management endpoints.  Patches config.py and registers
    the router.

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

    # --- Prerequisite check --------------------------------------------------
    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.BASE_MODEL,
        Prereq.MODELS_INIT,
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
    opa_client_file = app_dir / "authz" / "opa_client.py"
    if opa_client_file.exists() and "class OPAClient" in opa_client_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["OPA integration already present — skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would install OPAClient, OPAMiddleware, Rego policies, "
                "management routes, config fields."
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    if scaffolded:
        files_created.extend(scaffolded)
    files_modified: list[str] = []

    # Step 1: app/authz/__init__.py
    authz_init = app_dir / "authz" / "__init__.py"
    _write_authz_init(authz_init)
    files_created.append(str(authz_init))

    # Step 2: app/authz/opa_models.py
    opa_models_file = app_dir / "authz" / "opa_models.py"
    _write_opa_models(opa_models_file)
    files_created.append(str(opa_models_file))

    # Step 3: app/authz/opa_client.py  (circuit breaker, lazy httpx)
    _write_opa_client(opa_client_file)
    files_created.append(str(opa_client_file))

    # Step 4: app/authz/opa_middleware.py
    opa_middleware_file = app_dir / "authz" / "opa_middleware.py"
    _write_opa_middleware(opa_middleware_file)
    files_created.append(str(opa_middleware_file))

    # Step 5: app/authz/policies/ with 3 example Rego files
    policies_dir = app_dir / "authz" / "policies"
    policies_dir.mkdir(parents=True, exist_ok=True)
    _write_rego_policies(policies_dir)
    files_created.append(str(policies_dir / "authz.rego"))
    files_created.append(str(policies_dir / "data.json"))
    files_created.append(str(policies_dir / "authz_test.rego"))

    # Step 6: app/api/routes/opa.py
    opa_routes_file = app_dir / "api" / "routes" / "opa.py"
    _write_opa_routes(opa_routes_file)
    files_created.append(str(opa_routes_file))

    # Step 7: Patch app/core/config.py with OPA settings
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # Step 8: Patch app/routes/__init__.py to include router
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    # Step 9: Patch requirements.txt with httpx
    req_file = project / "requirements.txt"
    if req_file.exists():
        _patch_requirements(req_file)
        files_modified.append(str(req_file))

    # --- AST validation for all generated .py files --------------------------
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
            "OPA integration installed: OPAClient, OPAMiddleware, Rego policies.",
            "Client uses httpx (lazy import) with circuit breaker on OPA unavailability.",
            "Configure OPA_FAIL_OPEN=true for fail-open (allow on OPA down) or false for fail-closed.",
            "Example Rego policies in app/authz/policies/. Load them into your OPA sidecar.",
            "Use OPAMiddleware for request-level enforcement or OPAClient directly in routes.",
        ],
        next_steps=[
            "Start OPA sidecar: docker run -p 8181:8181 openpolicyagent/opa run --server",
            "Load policies: opa build app/authz/policies/authz.rego",
            "Set OPA_URL=http://localhost:8181 in your .env",
            "Set OPA_ENABLED=true and OPA_POLICY_PATH=authz/allow",
            "Optionally add OPAMiddleware to app/main.py for request-level enforcement.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# Step helpers — each < 50 LOC
# ---------------------------------------------------------------------------


def _write_authz_init(dest: Path) -> None:
    """Write app/authz/__init__.py with re-exports of core OPA symbols.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return
    dest.write_text(textwrap.dedent("""\
        \"\"\"Authorization package: OPA (Open Policy Agent) integration.\"\"\"

        from app.authz.opa_client import OPAClient, get_opa_client
        from app.authz.opa_models import OPADecision, OPAInput
        from app.authz.opa_middleware import OPAMiddleware

        __all__ = [
            "OPAClient",
            "get_opa_client",
            "OPADecision",
            "OPAInput",
            "OPAMiddleware",
        ]
    """))


def _write_opa_models(dest: Path) -> None:
    """Write app/authz/opa_models.py with OPAInput and OPADecision Pydantic models.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Pydantic models for OPA (Open Policy Agent) requests and responses.\"\"\"

        from __future__ import annotations

        from typing import Any

        from pydantic import BaseModel, ConfigDict, Field


        class OPAInput(BaseModel):
            \"\"\"Input document sent to OPA for policy evaluation.

            Attributes:
                subject: Authenticated user identifier (e.g. user UUID or email).
                action: HTTP method or domain action (e.g. 'GET', 'write').
                resource: Resource path or type (e.g. '/api/v1/items').
                context: Optional free-form context (tenant ID, IP, etc.).
            \"\"\"

            model_config = ConfigDict(from_attributes=True)

            subject: str = Field(..., description="Authenticated user identifier.")
            action: str = Field(..., description="Action being performed.")
            resource: str = Field(..., description="Resource being accessed.")
            context: dict[str, Any] = Field(
                default_factory=dict,
                description="Optional extra context passed verbatim to OPA.",
            )


        class OPADecision(BaseModel):
            \"\"\"Decision returned by OPA policy evaluation.

            Attributes:
                allow: True when the policy grants access.
                reason: Optional human-readable explanation from the policy.
                policy_path: OPA policy rule that was queried.
            \"\"\"

            model_config = ConfigDict(from_attributes=True)

            allow: bool = Field(..., description="True when the policy grants access.")
            reason: str | None = Field(
                default=None, description="Optional explanation from the policy."
            )
            policy_path: str = Field(..., description="OPA rule path that was evaluated.")
    """))


def _write_opa_client(dest: Path) -> None:
    """Write app/authz/opa_client.py — OPAClient with lazy httpx and circuit breaker.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"OPA HTTP client with lazy httpx import and circuit breaker.

        OPA runs as a sidecar at OPA_URL.  The circuit breaker trips after
        OPA_CB_THRESHOLD consecutive failures and stays open for OPA_CB_RESET_S
        seconds before allowing a probe.  On open circuit, behaviour is
        controlled by OPA_FAIL_OPEN: True allows, False denies.

        httpx is imported lazily inside async methods so ``app.main`` boots
        without it installed (though it is listed in requirements.txt).
        \"\"\"

        from __future__ import annotations

        import logging
        import time
        from typing import Any

        from app.authz.opa_models import OPADecision, OPAInput

        logger = logging.getLogger(__name__)

        _DEFAULT_POLICY_PATH = "authz/allow"


        def _parse_opa_result(data: dict[str, Any], path: str) -> OPADecision:
            \"\"\"Extract allow flag and reason from an OPA /v1/data response body.

            Args:
                data: Parsed JSON response from OPA (must contain a 'result' key).
                path: Policy path that was evaluated (for the returned OPADecision).

            Returns:
                OPADecision with allow and optional reason.
            \"\"\"
            result = data.get("result", False)
            if isinstance(result, dict):
                allow = bool(result.get("allow", False))
                reason: str | None = result.get("reason")
            else:
                allow = bool(result)
                reason = None
            return OPADecision(allow=allow, reason=reason, policy_path=path)


        async def _post_opa(url: str, payload: dict[str, Any], timeout: float) -> Any:
            \"\"\"Send a JSON POST to OPA and return the parsed response body.

            Args:
                url: Full OPA data endpoint URL (e.g. http://localhost:8181/v1/data/authz/allow).
                payload: JSON body to send (typically {\"input\": {...}}).
                timeout: Request timeout in seconds.

            Returns:
                Parsed JSON dict from OPA.

            Raises:
                Exception: On network error or non-2xx response.
            \"\"\"
            import httpx  # lazy import — optional SDK

            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()


        class _CircuitBreaker:
            \"\"\"Lightweight circuit breaker: closed → half-open → open.

            Attributes:
                threshold: Consecutive failure count before opening.
                reset_s: Seconds to wait before half-open probe.
            \"\"\"

            def __init__(self, threshold: int = 3, reset_s: float = 30.0) -> None:
                \"\"\"Initialise the circuit breaker.

                Args:
                    threshold: Failures before opening.
                    reset_s: Cooldown before half-open attempt.
                \"\"\"
                self.threshold = threshold
                self.reset_s = reset_s
                self._failures = 0
                self._opened_at: float | None = None

            def is_open(self) -> bool:
                \"\"\"Return True when the circuit is open (OPA unreachable).

                Returns:
                    True if open and cooldown has not expired yet.
                \"\"\"
                if self._opened_at is None:
                    return False
                if time.monotonic() - self._opened_at >= self.reset_s:
                    self._opened_at = None
                    self._failures = 0
                    return False
                return True

            def record_success(self) -> None:
                \"\"\"Reset failure counter on a successful call.\"\"\"
                self._failures = 0
                self._opened_at = None

            def record_failure(self) -> None:
                \"\"\"Increment failure counter; open circuit if threshold reached.\"\"\"
                self._failures += 1
                if self._failures >= self.threshold:
                    self._opened_at = time.monotonic()
                    logger.warning(
                        "OPA circuit breaker opened after %d consecutive failures",
                        self._failures,
                    )


        class OPAClient:
            \"\"\"Async OPA HTTP client.

            Sends JSON POST requests to ``{opa_url}/v1/data/{policy_path}``.
            Uses a circuit breaker to avoid hammering an unavailable sidecar.

            Attributes:
                opa_url: Base URL of the OPA sidecar (e.g. http://localhost:8181).
                policy_path: Default Rego rule path (e.g. authz/allow).
                timeout_ms: Request timeout in milliseconds.
                fail_open: Allow access when OPA is unreachable (True) or deny (False).
            \"\"\"

            def __init__(
                self,
                opa_url: str,
                policy_path: str = _DEFAULT_POLICY_PATH,
                timeout_ms: int = 500,
                fail_open: bool = False,
            ) -> None:
                \"\"\"Initialise the OPA client.

                Args:
                    opa_url: Base URL of the OPA sidecar.
                    policy_path: Default Rego rule path used when query() is called
                        without an explicit path override.
                    timeout_ms: Per-request timeout in milliseconds.
                    fail_open: When True, allow access if OPA is unreachable.
                        When False (default), deny access on circuit-open.
                \"\"\"
                self.opa_url = opa_url.rstrip("/")
                self.policy_path = policy_path
                self.timeout_ms = timeout_ms
                self.fail_open = fail_open
                self._cb = _CircuitBreaker()

            async def query(
                self,
                opa_input: OPAInput,
                policy_path: str | None = None,
            ) -> OPADecision:
                \"\"\"Evaluate a policy rule against the given input document.

                Args:
                    opa_input: Input document (subject, action, resource, context).
                    policy_path: Override the default rule path (e.g. 'rbac/allow').

                Returns:
                    OPADecision with allow=True/False and optional reason.
                \"\"\"
                path = (policy_path or self.policy_path).strip("/")
                url = f"{self.opa_url}/v1/data/{path}"

                if self._cb.is_open():
                    logger.warning("OPA circuit open — fail_open=%s", self.fail_open)
                    return OPADecision(
                        allow=self.fail_open,
                        reason="circuit_open",
                        policy_path=path,
                    )

                payload: dict[str, Any] = {"input": opa_input.model_dump()}
                try:
                    data = await _post_opa(url, payload, self.timeout_ms / 1000.0)
                    self._cb.record_success()
                except Exception as exc:
                    self._cb.record_failure()
                    logger.warning("OPA request failed: %s", exc)
                    return OPADecision(
                        allow=self.fail_open,
                        reason="opa_unavailable",
                        policy_path=path,
                    )

                decision = _parse_opa_result(data, path)
                logger.info(
                    "OPA decision subject=%s action=%s resource=%s allow=%s",
                    opa_input.subject, opa_input.action, opa_input.resource,
                    decision.allow,
                )
                return decision

            async def health(self) -> bool:
                \"\"\"Check OPA sidecar health via GET /health.

                Returns:
                    True when OPA responds 200, False otherwise.
                \"\"\"
                import httpx  # lazy import — optional SDK

                try:
                    async with httpx.AsyncClient(timeout=2.0) as client:
                        resp = await client.get(f"{self.opa_url}/health")
                    return resp.status_code == 200
                except Exception:
                    return False


        def get_opa_client() -> OPAClient:
            \"\"\"FastAPI dependency that returns the configured OPA client singleton.

            Reads OPA_URL, OPA_POLICY_PATH, OPA_TIMEOUT_MS, OPA_FAIL_OPEN from
            app settings.  The client is constructed on every call; production code
            should cache via ``lru_cache`` or an app-level lifespan store if needed.

            Returns:
                Configured ``OPAClient`` instance.
            \"\"\"
            from app.core.config import settings  # type: ignore[import]

            return OPAClient(
                opa_url=getattr(settings, "OPA_URL", "http://localhost:8181"),
                policy_path=getattr(settings, "OPA_POLICY_PATH", _DEFAULT_POLICY_PATH),
                timeout_ms=int(getattr(settings, "OPA_TIMEOUT_MS", 500)),
                fail_open=bool(getattr(settings, "OPA_FAIL_OPEN", False)),
            )
    """))


def _write_opa_middleware(dest: Path) -> None:
    """Write app/authz/opa_middleware.py — Starlette middleware that calls OPA per-request.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"OPA enforcement middleware: intercepts requests and queries OPA.

        Add to app/main.py::

            from app.authz.opa_middleware import OPAMiddleware
            app.add_middleware(OPAMiddleware)

        Requests to excluded prefixes (``/healthz``, ``/docs``, ``/openapi.json``,
        ``/api/v1/login``) bypass OPA evaluation.  The user subject is derived from
        the ``X-User-Id`` header; in production wire this to your JWT middleware
        result instead.
        \"\"\"

        from __future__ import annotations

        import logging

        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.requests import Request
        from starlette.responses import JSONResponse

        from app.authz.opa_client import get_opa_client
        from app.authz.opa_models import OPAInput

        logger = logging.getLogger(__name__)

        _SKIP_PREFIXES: tuple[str, ...] = (
            "/healthz",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/api/v1/login",
            "/api/v1/openapi.json",
        )


        class OPAMiddleware(BaseHTTPMiddleware):
            \"\"\"Request-level OPA enforcement middleware.

            Queries OPA for every request not in ``_SKIP_PREFIXES``.  Returns
            HTTP 403 when OPA denies access.  If OPA is unreachable, the
            circuit-breaker / fail-open policy in OPAClient controls the outcome.
            \"\"\"

            async def dispatch(self, request: Request, call_next):  # type: ignore[override]
                \"\"\"Intercept request, query OPA, and deny or pass through.

                Args:
                    request: Incoming HTTP request.
                    call_next: ASGI callable for the next handler.

                Returns:
                    HTTP 403 JSON response on denial, or the downstream response.
                \"\"\"
                path = request.url.path
                if any(path.startswith(pfx) for pfx in _SKIP_PREFIXES):
                    return await call_next(request)

                subject = request.headers.get("X-User-Id", "anonymous")
                opa_input = OPAInput(
                    subject=subject,
                    action=request.method,
                    resource=path,
                    context={"query": str(request.query_params)},
                )

                client = get_opa_client()
                decision = await client.query(opa_input)

                if not decision.allow:
                    logger.warning(
                        "OPA denied subject=%s action=%s resource=%s reason=%s",
                        subject,
                        request.method,
                        path,
                        decision.reason,
                    )
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "Forbidden by policy"},
                    )

                return await call_next(request)
    """))


def _write_rego_policies(policies_dir: Path) -> None:
    """Write 3 example Rego files into app/authz/policies/.

    Files: authz.rego, data.json, authz_test.rego

    Args:
        policies_dir: Absolute path to the policies directory.
    """
    (policies_dir / "authz.rego").write_text(textwrap.dedent("""\
        # authz.rego — Example OPA policy for HTTP API authorization.
        #
        # Load into OPA:  opa run --server authz.rego data.json
        # Query:          POST /v1/data/authz/allow  { "input": { ... } }

        package authz

        import rego.v1

        # Default: deny all requests.
        default allow := false

        # Allow superusers unconditionally.
        allow if {
            data.roles[input.subject] == "superuser"
        }

        # Allow GET requests for authenticated (non-anonymous) users.
        allow if {
            input.action == "GET"
            input.subject != "anonymous"
        }

        # Allow POST/PUT/DELETE for users with write role.
        allow if {
            input.action in {"POST", "PUT", "DELETE", "PATCH"}
            data.roles[input.subject] == "writer"
        }
    """))

    (policies_dir / "data.json").write_text(textwrap.dedent("""\
        {
            "roles": {
                "admin@example.com": "superuser",
                "writer@example.com": "writer",
                "reader@example.com": "reader"
            }
        }
    """))

    (policies_dir / "authz_test.rego").write_text(textwrap.dedent("""\
        # authz_test.rego — OPA unit tests for the authz policy.
        #
        # Run:  opa test authz.rego data.json authz_test.rego -v

        package authz_test

        import rego.v1
        import data.authz

        # Superuser is always allowed.
        test_superuser_allowed if {
            authz.allow with input as {
                "subject": "admin@example.com",
                "action": "DELETE",
                "resource": "/api/v1/items",
            } with data.roles as {"admin@example.com": "superuser"}
        }

        # Anonymous GET is denied (not authenticated).
        test_anonymous_get_denied if {
            not authz.allow with input as {
                "subject": "anonymous",
                "action": "GET",
                "resource": "/api/v1/items",
            }
        }

        # Authenticated GET is allowed.
        test_reader_get_allowed if {
            authz.allow with input as {
                "subject": "reader@example.com",
                "action": "GET",
                "resource": "/api/v1/items",
            } with data.roles as {"reader@example.com": "reader"}
        }

        # Non-writer POST is denied.
        test_reader_post_denied if {
            not authz.allow with input as {
                "subject": "reader@example.com",
                "action": "POST",
                "resource": "/api/v1/items",
            } with data.roles as {"reader@example.com": "reader"}
        }
    """))


def _write_opa_routes(dest: Path) -> None:
    """Write app/api/routes/opa.py with POST /authz/opa/check and GET /authz/opa/health.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"OPA management endpoints: policy check and sidecar health.\"\"\"

        from __future__ import annotations

        import logging

        from fastapi import APIRouter, Depends, HTTPException, status

        from app.authz.opa_client import OPAClient, get_opa_client
        from app.authz.opa_models import OPADecision, OPAInput

        logger = logging.getLogger(__name__)

        router = APIRouter(prefix="/authz/opa", tags=["opa"])


        @router.post(
            "/check",
            response_model=OPADecision,
            summary="Evaluate an OPA policy rule",
        )
        async def check_policy(
            opa_input: OPAInput,
            client: OPAClient = Depends(get_opa_client),
        ) -> OPADecision:
            \"\"\"Evaluate an OPA policy rule for the given input document.

            Args:
                opa_input: Subject, action, resource and optional context.
                client: OPA HTTP client (injected by FastAPI DI).

            Returns:
                OPADecision with allow flag and optional reason.

            Raises:
                HTTPException: 503 when OPA is unreachable and fail_open is False.
            \"\"\"
            decision = await client.query(opa_input)
            if decision.reason == "opa_unavailable" and not client.fail_open:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="OPA sidecar unavailable",
                )
            return decision


        @router.get(
            "/health",
            summary="OPA sidecar health check",
        )
        async def opa_health(
            client: OPAClient = Depends(get_opa_client),
        ) -> dict[str, str]:
            \"\"\"Probe the OPA sidecar's /health endpoint.

            Args:
                client: OPA HTTP client (injected by FastAPI DI).

            Returns:
                JSON body with status 'ok' or 'unavailable'.
            \"\"\"
            healthy = await client.health()
            return {"status": "ok" if healthy else "unavailable"}
    """))


def _patch_config(config_file: Path) -> None:
    """Inject OPA_URL, OPA_ENABLED, OPA_POLICY_PATH, OPA_TIMEOUT_MS into Settings.

    Appends fields inside the ``class Settings`` body only when they are
    not already present.

    Args:
        config_file: Absolute path to app/core/config.py.
    """
    content = config_file.read_text()
    new_lines: list[str] = []
    fields = {
        "OPA_URL": '    OPA_URL: str = "http://localhost:8181"',
        "OPA_ENABLED": "    OPA_ENABLED: bool = False",
        "OPA_POLICY_PATH": '    OPA_POLICY_PATH: str = "authz/allow"',
        "OPA_TIMEOUT_MS": "    OPA_TIMEOUT_MS: int = 500",
        "OPA_FAIL_OPEN": "    OPA_FAIL_OPEN: bool = False",
    }
    for key, line in fields.items():
        if key not in content:
            new_lines.append(line)

    if not new_lines:
        return

    # Insert before ``settings = Settings()`` or at end of class body
    marker = "settings = Settings()"
    if marker in content:
        content = content.replace(
            marker,
            "\n".join(new_lines) + "\n\n" + marker,
        )
    else:
        content = content.rstrip() + "\n" + "\n".join(new_lines) + "\n"

    config_file.write_text(content)


def _patch_routes_init(routes_init: Path) -> None:
    """Register the OPA router in app/routes/__init__.py idempotently.

    Args:
        routes_init: Absolute path to app/routes/__init__.py.
    """
    content = routes_init.read_text()
    import_line = "from app.api.routes.opa import router as opa_router"
    include_line = "api_router.include_router(opa_router)"

    if import_line in content and include_line in content:
        return

    additions: list[str] = []
    if import_line not in content:
        additions.append(import_line)
    if include_line not in content:
        additions.append(include_line)

    if not content.endswith("\n"):
        content += "\n"
    content += "\n".join(additions) + "\n"
    routes_init.write_text(content)


def _patch_requirements(req_file: Path) -> None:
    """Ensure httpx>=0.28.0 is listed in requirements.txt.

    Args:
        req_file: Absolute path to requirements.txt.
    """
    content = req_file.read_text()
    if "httpx" in content:
        return
    if not content.endswith("\n"):
        content += "\n"
    content += "httpx>=0.28.0\n"
    req_file.write_text(content)
