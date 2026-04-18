"""TOOL-109: add_canary_tokens — honeypot endpoints + fake credentials + decoy DB records.

Three canary types:

1. **Honeypot endpoints** — ``/api/v1/internal/config``, ``/api/v1/admin/backup``,
   ``/api/v1/debug/env``.  Any access triggers an alert webhook.
2. **Fake credentials** — AWS keys, DB connection strings planted in a well-known
   but non-functional location.  If an attacker uses them, the canary fires.
3. **Decoy DB records** — fake admin users written into the User table at startup,
   with a ``is_canary`` flag.  Any query for these records triggers an alert.

Critical guard: canaries NEVER block requests — the attacker must NOT know they
hit a canary.  Alerting is fire-and-forget (background task).

Config fields added to ``app/core/config.py``::

    CANARY_ENABLED = True
    CANARY_ALERT_WEBHOOK_URL = ""

The tool is idempotent: a second run detects ``class CanaryRegistry`` in
``app/core/canary/registry.py`` and returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_canary_tokens import add_canary_tokens

    result = add_canary_tokens(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # [".../app/core/canary/registry.py", ...]
    print(result.next_steps)    # ["Set CANARY_ALERT_WEBHOOK_URL in .env", ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_add_canary_tokens",
    "description": (
        "Add canary token infrastructure: honeypot endpoints, fake credentials, "
        "and decoy DB records that alert on access without blocking the attacker."
    ),
    "tags": ["extend", "infrastructure", "security"],
    "entry": "add_canary_tokens",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def add_canary_tokens(inp: ToolInput) -> ToolResult:
    """Add canary token infrastructure to a FastAPI project.

    Creates canary registry, alert dispatcher, honeypot routes, fake-credential
    file, and decoy record seeder.  Patches config and routes.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.

    Returns:
        ``ToolResult`` describing every file created or modified.
    """
    start = time.monotonic()

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err,
                          execution_time_ms=_elapsed_ms(start))

    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

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
    registry_file = app_dir / "core" / "canary" / "registry.py"

    # --- Idempotency guard ---------------------------------------------------
    if registry_file.exists() and "class CanaryRegistry" in registry_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["Canary tokens already installed — skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=["[dry_run] Would install canary token infrastructure."],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded)
    files_modified: list[str] = []

    # Step 1: Canary registry
    _write_registry(registry_file)
    files_created.append(str(registry_file))

    # Step 2: Alert dispatcher (fire-and-forget webhook)
    alert_file = app_dir / "core" / "canary" / "alerter.py"
    _write_alerter(alert_file)
    files_created.append(str(alert_file))

    # Step 3: Honeypot routes
    honeypot_file = app_dir / "api" / "routes" / "canary_honeypot.py"
    _write_honeypot_routes(honeypot_file)
    files_created.append(str(honeypot_file))

    # Step 4: Fake credentials file (decoy only, NEVER used in real code)
    fake_creds_file = app_dir / "core" / "canary" / "fake_credentials.py"
    _write_fake_credentials(fake_creds_file)
    files_created.append(str(fake_creds_file))

    # Step 5: Decoy DB record seeder
    seeder_file = app_dir / "core" / "canary" / "decoy_seeder.py"
    _write_decoy_seeder(seeder_file)
    files_created.append(str(seeder_file))

    # Step 6: Patch config.py
    config_file = app_dir / "core" / "config.py"
    if config_file.is_file():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # Step 7: Register honeypot router in routes/__init__.py
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.is_file():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    # --- ast.parse validation ------------------------------------------------
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
            "Canary type 1: Honeypot endpoints /api/v1/internal/config, /api/v1/admin/backup, /api/v1/debug/env.",
            "Canary type 2: Fake credentials in app/core/canary/fake_credentials.py (never used in real code).",
            "Canary type 3: Decoy admin DB records seeded at startup via decoy_seeder.py.",
            "CRITICAL: Canaries NEVER block — attacker sees 200 OK but alert fires in background.",
            "Alert: POST to CANARY_ALERT_WEBHOOK_URL with full request context + canary ID.",
        ],
        next_steps=[
            "Set CANARY_ALERT_WEBHOOK_URL in your .env file.",
            "Set CANARY_ENABLED=true in .env.",
            "Call seed_decoy_records(session) during startup (add to lifespan event).",
            "Monitor webhook for canary_triggered events.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# Step helpers — each < 50 LOC
# ---------------------------------------------------------------------------


def _write_registry(dest: Path) -> None:
    """Write app/core/canary/registry.py with CanaryRegistry."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Canary token registry: tracks all deployed canary tokens by ID.

        Each canary has a unique fingerprint used for attribution when a token fires.
        \"\"\"

        from __future__ import annotations

        import hashlib
        import logging
        import time
        from dataclasses import dataclass, field
        from typing import ClassVar

        logger = logging.getLogger(__name__)


        @dataclass(frozen=True)
        class CanaryToken:
            \"\"\"A registered canary token.

            Attributes:
                token_id: Unique identifier for this canary.
                canary_type: 'honeypot', 'credential', or 'decoy_record'.
                description: Human-readable description.
                fingerprint: Stable SHA-256-based fingerprint for attribution.
            \"\"\"

            token_id: str
            canary_type: str
            description: str
            fingerprint: str = field(init=False)

            def __post_init__(self) -> None:
                \"\"\"Compute the fingerprint from token_id + type.\"\"\"
                fp = hashlib.sha256(
                    f"{self.token_id}:{self.canary_type}".encode()
                ).hexdigest()[:16]
                object.__setattr__(self, "fingerprint", fp)


        class CanaryRegistry:
            \"\"\"Central registry of all deployed canary tokens.

            Attributes:
                _tokens: Internal mapping of token_id → CanaryToken.
            \"\"\"

            _tokens: ClassVar[dict[str, CanaryToken]] = {}

            @classmethod
            def register(
                cls,
                token_id: str,
                canary_type: str,
                description: str,
            ) -> CanaryToken:
                \"\"\"Register a canary token.

                Args:
                    token_id: Unique ID (e.g. 'honeypot_internal_config').
                    canary_type: Token type: 'honeypot', 'credential', 'decoy_record'.
                    description: Human-readable description.

                Returns:
                    The registered ``CanaryToken``.
                \"\"\"
                token = CanaryToken(
                    token_id=token_id,
                    canary_type=canary_type,
                    description=description,
                )
                cls._tokens[token_id] = token
                logger.info("canary_registry: registered %s (%s)", token_id, canary_type)
                return token

            @classmethod
            def get(cls, token_id: str) -> CanaryToken | None:
                \"\"\"Look up a token by ID.

                Args:
                    token_id: The token to look up.

                Returns:
                    ``CanaryToken`` or ``None`` when not registered.
                \"\"\"
                return cls._tokens.get(token_id)

            @classmethod
            def all_tokens(cls) -> list[CanaryToken]:
                \"\"\"Return all registered canary tokens.

                Returns:
                    List of all ``CanaryToken`` instances in registration order.
                \"\"\"
                return list(cls._tokens.values())


        # --- Pre-register built-in canaries ----------------------------------
        CanaryRegistry.register(
            "honeypot_internal_config",
            "honeypot",
            "Access to /api/v1/internal/config",
        )
        CanaryRegistry.register(
            "honeypot_admin_backup",
            "honeypot",
            "Access to /api/v1/admin/backup",
        )
        CanaryRegistry.register(
            "honeypot_debug_env",
            "honeypot",
            "Access to /api/v1/debug/env",
        )
        CanaryRegistry.register(
            "fake_aws_key",
            "credential",
            "Fake AWS access key in fake_credentials.py",
        )
        CanaryRegistry.register(
            "decoy_admin_user",
            "decoy_record",
            "Fake admin user record in the users table",
        )
    """))


def _write_alerter(dest: Path) -> None:
    """Write app/core/canary/alerter.py with fire-and-forget alert dispatcher."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Canary alert dispatcher — fire-and-forget webhook notification.

        CRITICAL INVARIANT: alerting NEVER blocks the request or raises an exception.
        The attacker MUST NOT know they triggered a canary.
        \"\"\"

        from __future__ import annotations

        import asyncio
        import json
        import logging
        import time
        from typing import Any

        logger = logging.getLogger(__name__)


        async def _post_webhook(url: str, payload: dict[str, Any]) -> None:
            \"\"\"POST the alert payload to the webhook URL asynchronously.

            Args:
                url: Webhook URL to POST to.
                payload: Alert payload dict.
            \"\"\"
            try:
                import httpx  # optional SDK: import inside function body
                async with httpx.AsyncClient(timeout=5.0) as client:
                    await client.post(url, json=payload)
                    logger.info("canary_alert: webhook delivered token_id=%s", payload.get("token_id"))
            except Exception as exc:  # noqa: BLE001
                logger.error("canary_alert: webhook failed: %s", exc)


        def fire_canary_alert(
            token_id: str,
            request_context: dict[str, Any],
            webhook_url: str,
        ) -> None:
            \"\"\"Dispatch a canary alert in a background thread — never blocks.

            Args:
                token_id: The canary token that was triggered.
                request_context: Dict with method, path, headers, client_ip, etc.
                webhook_url: URL to POST the alert to.
            \"\"\"
            if not webhook_url:
                logger.warning("canary_alert: CANARY_ALERT_WEBHOOK_URL not set, logging only")
                logger.critical(
                    "CANARY_TRIGGERED token_id=%s context=%s",
                    token_id,
                    json.dumps(request_context),
                )
                return
            payload = {
                "event": "canary_triggered",
                "token_id": token_id,
                "timestamp": int(time.time()),
                "request": request_context,
            }
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(_post_webhook(webhook_url, payload))
                else:
                    asyncio.run(_post_webhook(webhook_url, payload))
            except Exception as exc:  # noqa: BLE001
                logger.error("canary_alert: dispatch error: %s", exc)


        def build_request_context(
            method: str,
            path: str,
            client_ip: str,
            headers: dict[str, str],
            query: str = "",
        ) -> dict[str, Any]:
            \"\"\"Build a sanitised request context dict for the alert payload.

            Args:
                method: HTTP method.
                path: Request path.
                client_ip: Client IP address.
                headers: Lowercase request headers (sensitive values masked).
                query: Query string.

            Returns:
                Sanitised context dict suitable for JSON serialisation.
            \"\"\"
            _MASK_HEADERS = frozenset({"authorization", "cookie", "x-api-key"})
            safe_headers = {
                k: "***" if k in _MASK_HEADERS else v
                for k, v in headers.items()
            }
            return {
                "method": method,
                "path": path,
                "query": query,
                "client_ip": client_ip,
                "headers": safe_headers,
            }
    """))


def _write_honeypot_routes(dest: Path) -> None:
    """Write app/api/routes/canary_honeypot.py with honeypot endpoints."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Honeypot endpoints — look legitimate but fire canary alerts on access.

        Routes:
        * ``GET /api/v1/internal/config`` — fake config dump
        * ``GET /api/v1/admin/backup``    — fake backup endpoint
        * ``GET /api/v1/debug/env``       — fake env dump

        CRITICAL: These routes ALWAYS return HTTP 200 with plausible-looking
        data.  Attackers must NOT see any error or redirect.
        \"\"\"

        from __future__ import annotations

        import logging

        from fastapi import APIRouter, Request

        from app.core.canary.alerter import build_request_context, fire_canary_alert
        from app.core.config import settings

        logger = logging.getLogger(__name__)

        router = APIRouter(prefix="/api/v1", tags=["_canary"])

        _FAKE_CONFIG_RESPONSE = {
            "database_url": "postgresql://app:changeme@db:5432/app",
            "redis_url": "redis://redis:6379/0",
            "environment": "production",
            "debug": False,
        }

        _FAKE_BACKUP_RESPONSE = {
            "status": "ok",
            "last_backup": "2024-01-01T00:00:00Z",
            "size_mb": 1024,
            "location": "s3://backups/app/2024-01-01.tar.gz",
        }

        _FAKE_ENV_RESPONSE = {
            "ENVIRONMENT": "production",
            "LOG_LEVEL": "INFO",
            "WORKERS": "4",
        }


        def _alert(request: Request, token_id: str) -> None:
            \"\"\"Fire canary alert with sanitised request context — never raises.

            Args:
                request: The incoming FastAPI request.
                token_id: The canary token ID that was triggered.
            \"\"\"
            try:
                ctx = build_request_context(
                    method=request.method,
                    path=str(request.url.path),
                    client_ip=request.client.host if request.client else "unknown",
                    headers={k.lower(): v for k, v in request.headers.items()},
                    query=str(request.url.query),
                )
                fire_canary_alert(
                    token_id=token_id,
                    request_context=ctx,
                    webhook_url=getattr(settings, "CANARY_ALERT_WEBHOOK_URL", ""),
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("canary_honeypot: alert dispatch error: %s", exc)


        @router.get("/internal/config")
        async def honeypot_internal_config(request: Request) -> dict:
            \"\"\"Honeypot: fake internal config endpoint.

            Always returns 200 with plausible-looking config data.
            Fires a canary alert in the background.

            Args:
                request: Incoming FastAPI request.

            Returns:
                Fake configuration dict.
            \"\"\"
            _alert(request, "honeypot_internal_config")
            return _FAKE_CONFIG_RESPONSE


        @router.get("/admin/backup")
        async def honeypot_admin_backup(request: Request) -> dict:
            \"\"\"Honeypot: fake admin backup endpoint.

            Always returns 200 with plausible-looking backup status.
            Fires a canary alert in the background.

            Args:
                request: Incoming FastAPI request.

            Returns:
                Fake backup status dict.
            \"\"\"
            _alert(request, "honeypot_admin_backup")
            return _FAKE_BACKUP_RESPONSE


        @router.get("/debug/env")
        async def honeypot_debug_env(request: Request) -> dict:
            \"\"\"Honeypot: fake debug env dump endpoint.

            Always returns 200 with plausible-looking env vars.
            Fires a canary alert in the background.

            Args:
                request: Incoming FastAPI request.

            Returns:
                Fake environment variable dict.
            \"\"\"
            _alert(request, "honeypot_debug_env")
            return _FAKE_ENV_RESPONSE
    """))


def _write_fake_credentials(dest: Path) -> None:
    """Write app/core/canary/fake_credentials.py with decoy credentials."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Fake credentials — canary type 2.

        These credentials look real but are NEVER used in any application code.
        If an attacker extracts and uses them, the associated canary service
        (AWS CloudTrail, etc.) fires an alert.

        NEVER import these values in production application code.
        \"\"\"

        from __future__ import annotations

        import logging

        logger = logging.getLogger(__name__)

        # --- Fake AWS credentials (canary) ------------------------------------
        # These are structurally valid but deliberately inactive.
        # Register them in AWS as canary keys with CloudTrail alerting.
        CANARY_AWS_ACCESS_KEY_ID = "AKIA_CANARY_PLACEHOLDER"
        CANARY_AWS_SECRET_ACCESS_KEY = "canary/secret/placeholder/not/real"
        CANARY_AWS_REGION = "us-east-1"

        # --- Fake DB connection string (canary) --------------------------------
        CANARY_DATABASE_URL = (
            "postgresql://canary_user:canary_password@canary-db.internal:5432/app"
        )

        # --- Fake API key (canary) --------------------------------------------
        CANARY_API_KEY = "sk_canary_0000000000000000000000000000000000000000"

        # --- Canary token IDs (for registry lookup) ---------------------------
        CANARY_TOKEN_IDS = {
            "aws_key": "fake_aws_key",
            "db_url": "canary_db_url",
            "api_key": "canary_api_key",
        }


        def log_canary_inventory() -> None:
            \"\"\"Log all deployed credential canaries at INFO level (no values).

            Called at startup to confirm canaries are in place.
            \"\"\"
            logger.info(
                "canary_credentials: %d credential canaries deployed",
                len(CANARY_TOKEN_IDS),
            )
    """))


def _write_decoy_seeder(dest: Path) -> None:
    """Write app/core/canary/decoy_seeder.py with seed_decoy_records."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Decoy DB record seeder — canary type 3.

        Seeds fake admin user records into the database at startup.
        Any query that returns these records triggers a canary alert.

        Usage — call during startup lifespan::

            from app.core.canary.decoy_seeder import seed_decoy_records

            async with get_session() as session:
                await seed_decoy_records(session)
        \"\"\"

        from __future__ import annotations

        import logging
        import uuid

        logger = logging.getLogger(__name__)

        _DECOY_USERS = [
            {
                "id": "00000000-cafe-babe-dead-000000000001",
                "email": "canary-admin@internal.invalid",
                "full_name": "Canary Admin",
                "is_superuser": True,
                "is_active": False,
            },
            {
                "id": "00000000-cafe-babe-dead-000000000002",
                "email": "canary-root@internal.invalid",
                "full_name": "Canary Root",
                "is_superuser": True,
                "is_active": False,
            },
        ]


        async def seed_decoy_records(session: object) -> list[str]:
            \"\"\"Attempt to insert decoy user records into the users table.

            Silently skips if the users table does not exist or the model
            does not have the expected columns.  Always safe to call.

            Args:
                session: SQLAlchemy ``AsyncSession`` instance.

            Returns:
                List of emails successfully seeded.
            \"\"\"
            seeded: list[str] = []
            try:
                from sqlalchemy import text  # optional SDK: import inside function body
                for decoy in _DECOY_USERS:
                    stmt = text(
                        "INSERT INTO users (id, email, full_name, is_superuser, is_active, hashed_password) "
                        "VALUES (:id, :email, :full_name, :is_superuser, :is_active, :hashed_password) "
                        "ON CONFLICT (email) DO NOTHING"
                    )
                    await session.execute(  # type: ignore[union-attr]
                        stmt,
                        {
                            **decoy,
                            "hashed_password": "canary_not_a_real_hash",
                        },
                    )
                    seeded.append(decoy["email"])
                await session.commit()  # type: ignore[union-attr]
                logger.info("canary_seeder: seeded %d decoy records", len(seeded))
            except Exception as exc:  # noqa: BLE001
                logger.debug("canary_seeder: skipped (table may not exist yet): %s", exc)
            return seeded


        def is_canary_email(email: str) -> bool:
            \"\"\"Return True when *email* matches a known decoy canary email.

            Use in auth/user lookup code to detect canary access attempts.

            Args:
                email: The email address to check.

            Returns:
                ``True`` when the email belongs to a canary decoy record.
            \"\"\"
            canary_emails = {u["email"] for u in _DECOY_USERS}
            return email in canary_emails
    """))


def _patch_config(config_file: Path) -> None:
    """Inject CANARY_* fields inside the Settings class body.

    Args:
        config_file: Path to ``app/core/config.py``.
    """
    src = config_file.read_text()
    if "CANARY_ENABLED" in src:
        return
    fields = (
        "    CANARY_ENABLED: bool = True\n"
        "    CANARY_ALERT_WEBHOOK_URL: str = \"\"\n"
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
    """Register honeypot router in routes/__init__.py idempotently."""
    content = routes_init.read_text()
    marker = "canary_honeypot"
    if marker in content:
        return
    addition = textwrap.dedent("""\

        from app.api.routes.canary_honeypot import router as canary_honeypot_router
        api_router.include_router(canary_honeypot_router)
    """)
    if not content.endswith("\n"):
        content += "\n"
    content += addition
    routes_init.write_text(content)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _elapsed_ms(start: float) -> int:
    """Return wall-clock elapsed milliseconds since *start*.

    Args:
        start: ``time.monotonic()`` snapshot from the top of the function.

    Returns:
        Elapsed time in milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)
