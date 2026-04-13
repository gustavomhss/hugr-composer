"""ADAPT tool: add an external service integration to an existing FastAPI project.

Generates production-grade integration boilerplate for common services --
Stripe, S3, SendGrid, and Redis (cache).  Each integration follows the same
structure: a client module under ``integrations/``, config fields, and
requirements updates.

Usage::

    from generators.tools.add_integration import add_integration

    result = add_integration(
        project_dir="/path/to/existing-project",
        service="stripe",
    )

    result = add_integration(
        project_dir="/path/to/existing-project",
        service="s3",
        config={"bucket": "my-assets"},
    )
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from generators.tools._layout import resolve_app_root


_SUPPORTED_SERVICES = ("stripe", "s3", "sendgrid", "redis")


def add_integration(
    project_dir: str,
    service: str,
    config: dict | None = None,
) -> dict:
    """Add an external service integration to an existing FastAPI project.

    Generates a client module, updates requirements, and adds config
    fields.  It is safe to run multiple times -- existing files are
    never overwritten.

    Args:
        project_dir: Root directory of the existing project.
        service: One of ``"stripe"``, ``"s3"``, ``"sendgrid"``, or
            ``"redis"``.
        config: Optional dict of extra configuration specific to the
            service (e.g. ``{"bucket": "my-bucket"}`` for S3).

    Returns:
        Dict with ``files_created``, ``files_modified``, and ``notes``.

    Raises:
        ValueError: If *service* is not one of the supported services.
    """
    service = service.lower().strip()
    if service not in _SUPPORTED_SERVICES:
        raise ValueError(
            f"Unsupported service {service!r}. "
            f"Supported: {', '.join(_SUPPORTED_SERVICES)}"
        )

    root = resolve_app_root(project_dir)
    proj_root = Path(project_dir)  # for requirements.txt and other root-level files
    cfg = config or {}

    files_created: list[str] = []
    files_modified: list[str] = []
    notes: list[str] = []

    # ------------------------------------------------------------------
    # 1. Ensure integrations/ package exists
    # ------------------------------------------------------------------
    integrations_dir = root / "integrations"
    integrations_dir.mkdir(parents=True, exist_ok=True)
    integrations_init = integrations_dir / "__init__.py"
    if not integrations_init.exists():
        integrations_init.write_text('"""External service integrations."""\n')
        files_created.append(str(integrations_init))

    # ------------------------------------------------------------------
    # 2. Dispatch to service-specific generator
    # ------------------------------------------------------------------
    generator = _SERVICE_GENERATORS[service]
    result = generator(root, integrations_dir, cfg, files_created, files_modified, notes)

    return {
        "files_created": files_created,
        "files_modified": files_modified,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# Service generators
# ---------------------------------------------------------------------------


def _generate_stripe(
    root: Path,
    integrations_dir: Path,
    cfg: dict,
    files_created: list[str],
    files_modified: list[str],
    notes: list[str],
) -> None:
    """Generate Stripe integration: client, webhook route, config, requirements."""
    # --- Guard ---
    client_file = integrations_dir / "stripe.py"
    if client_file.exists():
        notes.append("integrations/stripe.py already exists. Skipped.")
        return

    # --- Client module ---
    content = textwrap.dedent("""\
        \"\"\"Stripe integration -- async client helpers and webhook handling.

        All Stripe SDK calls are synchronous — we wrap them in
        ``asyncio.to_thread`` so they don't block the event loop.
        Webhook events are idempotency-guarded via Redis (24h TTL) so
        Stripe retries do not re-fulfill the same order.
        \"\"\"

        from __future__ import annotations

        import asyncio

        import stripe
        import structlog
        from fastapi import HTTPException, Request

        from app.core.config import settings

        logger = structlog.get_logger()

        # Initialise at module level
        stripe.api_key = settings.STRIPE_SECRET_KEY

        # Idempotency window for processed webhook event IDs.
        _WEBHOOK_IDEMPOTENCY_TTL = 60 * 60 * 24  # 24 hours


        async def create_checkout_session(
            *,
            price_id: str,
            success_url: str,
            cancel_url: str,
            customer_email: str | None = None,
            metadata: dict | None = None,
        ) -> stripe.checkout.Session:
            \"\"\"Create a Stripe Checkout session (non-blocking).\"\"\"
            params: dict = {
                "mode": "payment",
                "line_items": [{"price": price_id, "quantity": 1}],
                "success_url": success_url,
                "cancel_url": cancel_url,
            }
            if customer_email:
                params["customer_email"] = customer_email
            if metadata:
                params["metadata"] = metadata

            logger.info("stripe_checkout_creating", price_id=price_id)
            session = await asyncio.to_thread(
                stripe.checkout.Session.create, **params
            )
            logger.info("stripe_checkout_created", session_id=session.id)
            return session


        async def construct_webhook_event(request: Request) -> stripe.Event:
            \"\"\"Verify and construct a Stripe webhook event.

            The signature verification call is synchronous — we run it
            in a thread so the event loop stays free.

            Raises:
                HTTPException: If signature verification fails.
            \"\"\"
            payload = await request.body()
            sig_header = request.headers.get("stripe-signature", "")

            try:
                event = await asyncio.to_thread(
                    stripe.Webhook.construct_event,
                    payload,
                    sig_header,
                    settings.STRIPE_WEBHOOK_SECRET,
                )
            except stripe.error.SignatureVerificationError:
                logger.warning("stripe_webhook_invalid_signature")
                raise HTTPException(status_code=400, detail="Invalid signature")
            except ValueError:
                logger.warning("stripe_webhook_invalid_payload")
                raise HTTPException(status_code=400, detail="Invalid payload")

            return event


        async def _already_processed(event_id: str) -> bool:
            \"\"\"Return True if this event_id has already been processed.

            Uses Redis with a 24h TTL as the idempotency store.  The
            ``SET key value NX EX ttl`` command is atomic, so concurrent
            webhook deliveries of the same event see a single success.

            Redis is REQUIRED — if it is not reachable the webhook will
            raise 503 rather than silently risk duplicate fulfilment.
            \"\"\"
            try:
                import redis.asyncio as aioredis
            except ImportError:
                logger.error("redis_not_installed_for_stripe_idempotency")
                raise HTTPException(
                    status_code=503,
                    detail="Webhook idempotency store unavailable",
                )

            r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            try:
                # SET ... NX returns True only if key was set (not already present)
                ok = await r.set(
                    f"stripe:webhook:{event_id}",
                    "1",
                    nx=True,
                    ex=_WEBHOOK_IDEMPOTENCY_TTL,
                )
            finally:
                await r.aclose()
            return not bool(ok)


        async def _handle_checkout_completed(session: dict) -> None:
            \"\"\"Fulfil a completed Checkout session.

            Looks up the order by ``session['metadata']['order_id']``
            (set during ``create_checkout_session``) and marks it paid.
            Extend this function with your own fulfilment logic.
            \"\"\"
            metadata = session.get("metadata") or {}
            order_id = metadata.get("order_id")
            if not order_id:
                logger.warning(
                    "stripe_checkout_missing_order_id",
                    session_id=session.get("id"),
                )
                return

            # Import lazily to avoid a hard dependency on an Order model.
            try:
                from app.core.db import async_session_maker
                from app.crud.order import get as get_order, update as update_order  # type: ignore
            except ImportError:
                logger.info(
                    "stripe_order_model_not_wired",
                    order_id=order_id,
                    hint="Implement app/crud/order.py to persist fulfilment",
                )
                return

            import uuid
            async with async_session_maker() as db:
                order = await get_order(db, uuid.UUID(str(order_id)))
                if order is None:
                    logger.warning("stripe_order_not_found", order_id=order_id)
                    return
                await update_order(
                    db,
                    db_obj=order,
                    obj_in={
                        "status": "paid",
                        "stripe_session_id": session.get("id"),
                    },
                )
                await db.commit()
            logger.info("stripe_order_fulfilled", order_id=order_id)


        async def handle_webhook_event(event: stripe.Event) -> dict:
            \"\"\"Process a verified Stripe webhook event.

            Idempotent: re-delivery of the same ``event.id`` is a no-op.
            The handler returns quickly (200) after dispatching the
            business-specific handler; heavy work should be offloaded
            to a background queue in your own handler code.
            \"\"\"
            event_type = event["type"]
            event_id = event["id"]

            if await _already_processed(event_id):
                logger.info("stripe_webhook_duplicate", event_id=event_id)
                return {"status": "duplicate"}

            logger.info(
                "stripe_webhook_received",
                event_type=event_type,
                event_id=event_id,
            )

            if event_type == "checkout.session.completed":
                session = event["data"]["object"]
                await _handle_checkout_completed(session)

            elif event_type == "payment_intent.succeeded":
                intent = event["data"]["object"]
                logger.info("stripe_payment_succeeded", intent_id=intent["id"])

            elif event_type == "payment_intent.payment_failed":
                intent = event["data"]["object"]
                logger.warning("stripe_payment_failed", intent_id=intent["id"])

            else:
                logger.debug("stripe_webhook_unhandled", event_type=event_type)

            return {"status": "ok"}
    """)
    client_file.write_text(content)
    files_created.append(str(client_file))
    notes.append("Generated integrations/stripe.py with checkout and webhook helpers.")

    # --- Webhook route ---
    _generate_webhook_route(root, files_created, notes)

    # --- Requirements ---
    _ensure_requirement(root, "stripe>=7.0.0", files_modified, notes)

    # --- Config fields ---
    _ensure_config_field(root, "STRIPE_SECRET_KEY", 'str = ""', files_modified, notes)
    _ensure_config_field(root, "STRIPE_WEBHOOK_SECRET", 'str = ""', files_modified, notes)


def _generate_webhook_route(
    root: Path,
    files_created: list[str],
    notes: list[str],
) -> None:
    """Generate ``api/routes/webhooks.py`` with POST /webhooks/stripe."""
    routes_dir = root / "routes"
    if not routes_dir.exists():
        routes_dir = root / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)

    webhook_file = routes_dir / "webhooks.py"
    if webhook_file.exists():
        notes.append("routes/webhooks.py already exists. Skipped webhook route generation.")
        return

    content = textwrap.dedent("""\
        \"\"\"Webhook routes for external services.\"\"\"

        from __future__ import annotations

        from fastapi import APIRouter, Request
        from fastapi.responses import JSONResponse

        from app.integrations.stripe import construct_webhook_event, handle_webhook_event

        router = APIRouter(prefix="/webhooks", tags=["webhooks"])


        @router.post("/stripe")
        async def stripe_webhook(request: Request) -> JSONResponse:
            \"\"\"Receive and process Stripe webhook events.

            Stripe sends events here when payments succeed, fail, etc.
            The endpoint verifies the signature before processing.
            \"\"\"
            event = await construct_webhook_event(request)
            result = await handle_webhook_event(event)
            return JSONResponse(content=result)
    """)
    webhook_file.write_text(content)
    files_created.append(str(webhook_file))
    notes.append("Generated routes/webhooks.py with POST /webhooks/stripe.")

    # Ensure the api_router in routes/__init__.py picks up the new webhook
    # router so it is actually mounted on the FastAPI app.
    init_file = routes_dir.parent / "routes" / "__init__.py"
    if init_file.exists():
        init_content = init_file.read_text()
        if "webhooks_router" not in init_content:
            lines = init_content.splitlines()
            # Insert the import after the last "from app.routes" or
            # "from app.api.routes" import line.
            insert_at = 0
            for i, line in enumerate(lines):
                if line.startswith("from app.") and "import" in line:
                    insert_at = i + 1
            lines.insert(
                insert_at,
                "from app.routes.webhooks import router as webhooks_router",
            )
            # Append the include call at the end before the __all__ block.
            for i in range(len(lines) - 1, -1, -1):
                if lines[i].startswith("api_router.include_router"):
                    lines.insert(
                        i + 1,
                        "api_router.include_router(webhooks_router)",
                    )
                    break
            else:
                # Fallback: append near the end
                lines.append("api_router.include_router(webhooks_router)")
            init_file.write_text("\n".join(lines) + "\n")
            files_created.append(str(init_file))
            notes.append("Registered webhooks_router in routes/__init__.py.")


def _generate_s3(
    root: Path,
    integrations_dir: Path,
    cfg: dict,
    files_created: list[str],
    files_modified: list[str],
    notes: list[str],
) -> None:
    """Generate S3 integration: client helpers, config, requirements."""
    client_file = integrations_dir / "s3.py"
    if client_file.exists():
        notes.append("integrations/s3.py already exists. Skipped.")
        return

    bucket_default = cfg.get("bucket", "my-bucket")

    content = textwrap.dedent("""\
        \"\"\"AWS S3 integration -- upload, download, presigned URLs, delete.\"\"\"

        from __future__ import annotations

        from typing import BinaryIO

        import boto3
        import structlog
        from botocore.exceptions import ClientError

        from app.core.config import settings

        logger = structlog.get_logger()

        _client = None


        def _get_client():
            \"\"\"Return a shared boto3 S3 client (lazy init).\"\"\"
            global _client
            if _client is None:
                _client = boto3.client(
                    "s3",
                    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                    region_name=getattr(settings, "AWS_REGION", "us-east-1"),
                )
            return _client


        async def upload_file(
            file_obj: BinaryIO,
            key: str,
            bucket: str = "{bucket_default}",
            content_type: str | None = None,
        ) -> str:
            \"\"\"Upload a file to S3 and return the object key.\"\"\"
            extra_args = {{}}
            if content_type:
                extra_args["ContentType"] = content_type

            client = _get_client()
            client.upload_fileobj(file_obj, bucket, key, ExtraArgs=extra_args or None)
            logger.info("s3_uploaded", bucket=bucket, key=key)
            return key


        async def generate_presigned_url(
            key: str,
            bucket: str = "{bucket_default}",
            expires_in: int = 3600,
        ) -> str:
            \"\"\"Generate a presigned URL for downloading an S3 object.

            Args:
                key: S3 object key.
                bucket: Bucket name.
                expires_in: URL expiration in seconds (default: 1 hour).

            Returns:
                Presigned URL string.
            \"\"\"
            client = _get_client()
            url = client.generate_presigned_url(
                "get_object",
                Params={{"Bucket": bucket, "Key": key}},
                ExpiresIn=expires_in,
            )
            logger.info("s3_presigned_url", bucket=bucket, key=key, expires_in=expires_in)
            return url


        async def delete_file(key: str, bucket: str = "{bucket_default}") -> bool:
            \"\"\"Delete an object from S3.

            Returns True if deleted, False if the object did not exist.
            \"\"\"
            client = _get_client()
            try:
                client.delete_object(Bucket=bucket, Key=key)
                logger.info("s3_deleted", bucket=bucket, key=key)
                return True
            except ClientError as exc:
                logger.warning("s3_delete_failed", bucket=bucket, key=key, error=str(exc))
                return False
    """).format(bucket_default=bucket_default)

    client_file.write_text(content)
    files_created.append(str(client_file))
    notes.append(f"Generated integrations/s3.py with upload, presigned URL, and delete (default bucket: {bucket_default}).")

    # --- Requirements ---
    _ensure_requirement(root, "boto3>=1.34.0", files_modified, notes)

    # --- Config fields ---
    _ensure_config_field(root, "AWS_ACCESS_KEY_ID", 'str = ""', files_modified, notes)
    _ensure_config_field(root, "AWS_SECRET_ACCESS_KEY", 'str = ""', files_modified, notes)
    _ensure_config_field(root, "S3_BUCKET_NAME", f'str = "{bucket_default}"', files_modified, notes)


def _generate_sendgrid(
    root: Path,
    integrations_dir: Path,
    cfg: dict,
    files_created: list[str],
    files_modified: list[str],
    notes: list[str],
) -> None:
    """Generate SendGrid integration: email client, config, requirements."""
    client_file = integrations_dir / "sendgrid.py"
    if client_file.exists():
        notes.append("integrations/sendgrid.py already exists. Skipped.")
        return

    content = textwrap.dedent("""\
        \"\"\"SendGrid integration -- transactional and template email sending.\"\"\"

        from __future__ import annotations

        import structlog
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail, To

        from app.core.config import settings

        logger = structlog.get_logger()

        _client = None


        def _get_client() -> SendGridAPIClient:
            \"\"\"Return a shared SendGrid client (lazy init).\"\"\"
            global _client
            if _client is None:
                _client = SendGridAPIClient(settings.SENDGRID_API_KEY)
            return _client


        async def send_email(
            *,
            to_email: str,
            subject: str,
            html_content: str,
            from_email: str | None = None,
        ) -> dict:
            \"\"\"Send a plain transactional email.

            Args:
                to_email: Recipient email address.
                subject: Email subject line.
                html_content: HTML body of the email.
                from_email: Sender email (defaults to config value).

            Returns:
                Dict with ``status_code`` and ``message_id``.
            \"\"\"
            sender = from_email or getattr(settings, "EMAILS_FROM_EMAIL", "noreply@example.com")
            message = Mail(
                from_email=sender,
                to_emails=To(to_email),
                subject=subject,
                html_content=html_content,
            )

            client = _get_client()
            response = client.send(message)

            logger.info(
                "sendgrid_email_sent",
                to=to_email,
                subject=subject,
                status_code=response.status_code,
            )

            return {
                "status_code": response.status_code,
                "message_id": response.headers.get("X-Message-Id", ""),
            }


        async def send_template_email(
            *,
            to_email: str,
            template_id: str,
            dynamic_data: dict | None = None,
            from_email: str | None = None,
        ) -> dict:
            \"\"\"Send an email using a SendGrid dynamic template.

            Args:
                to_email: Recipient email address.
                template_id: SendGrid template ID (e.g. ``d-xxxx``).
                dynamic_data: Template variable substitutions.
                from_email: Sender email (defaults to config value).

            Returns:
                Dict with ``status_code`` and ``message_id``.
            \"\"\"
            sender = from_email or getattr(settings, "EMAILS_FROM_EMAIL", "noreply@example.com")
            message = Mail(
                from_email=sender,
                to_emails=To(to_email),
            )
            message.template_id = template_id
            if dynamic_data:
                message.dynamic_template_data = dynamic_data

            client = _get_client()
            response = client.send(message)

            logger.info(
                "sendgrid_template_sent",
                to=to_email,
                template_id=template_id,
                status_code=response.status_code,
            )

            return {
                "status_code": response.status_code,
                "message_id": response.headers.get("X-Message-Id", ""),
            }
    """)

    client_file.write_text(content)
    files_created.append(str(client_file))
    notes.append("Generated integrations/sendgrid.py with send_email and send_template_email.")

    # --- Requirements ---
    _ensure_requirement(root, "sendgrid>=6.11.0", files_modified, notes)

    # --- Config fields ---
    _ensure_config_field(root, "SENDGRID_API_KEY", 'str = ""', files_modified, notes)


def _generate_redis(
    root: Path,
    integrations_dir: Path,
    cfg: dict,
    files_created: list[str],
    files_modified: list[str],
    notes: list[str],
) -> None:
    """Generate Redis cache integration: client, get/set/delete, decorator."""
    client_file = integrations_dir / "redis_cache.py"
    if client_file.exists():
        notes.append("integrations/redis_cache.py already exists. Skipped.")
        return

    content = textwrap.dedent("""\
        \"\"\"Redis cache integration -- async get/set/delete with TTL and decorator.\"\"\"

        from __future__ import annotations

        import functools
        import hashlib
        import json
        from typing import Any

        import redis.asyncio as aioredis
        import structlog

        from app.core.config import settings

        logger = structlog.get_logger()

        _pool: aioredis.Redis | None = None


        async def get_redis() -> aioredis.Redis:
            \"\"\"Return a shared async Redis connection (lazy init).\"\"\"
            global _pool
            if _pool is None:
                _pool = aioredis.from_url(
                    settings.REDIS_URL,
                    decode_responses=True,
                )
            return _pool


        async def close_redis() -> None:
            \"\"\"Close the shared Redis connection (call during app shutdown).\"\"\"
            global _pool
            if _pool is not None:
                await _pool.aclose()
                _pool = None


        async def cache_get(key: str) -> Any | None:
            \"\"\"Get a JSON-decoded value from cache.  Returns None on miss.\"\"\"
            r = await get_redis()
            raw = await r.get(key)
            if raw is None:
                return None
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return raw


        async def cache_set(key: str, value: Any, ttl: int = 300) -> None:
            \"\"\"Set a JSON-encoded value in cache with TTL (seconds).\"\"\"
            r = await get_redis()
            await r.set(key, json.dumps(value, default=str), ex=ttl)


        async def cache_delete(key: str) -> bool:
            \"\"\"Delete a key from cache.  Returns True if the key existed.\"\"\"
            r = await get_redis()
            return bool(await r.delete(key))


        def cached(ttl: int = 300, prefix: str = "cache"):
            \"\"\"Decorator that caches the return value of an async function.

            The cache key is built from the function name and a hash of
            its arguments.

            Usage::

                @cached(ttl=600, prefix="users")
                async def get_user(user_id: int) -> dict:
                    ...
            \"\"\"

            def decorator(func):
                @functools.wraps(func)
                async def wrapper(*args, **kwargs):
                    # Build deterministic cache key
                    raw_key = f"{func.__name__}:{args}:{sorted(kwargs.items())}"
                    hashed = hashlib.md5(raw_key.encode()).hexdigest()
                    key = f"{prefix}:{func.__name__}:{hashed}"

                    # Try cache first
                    hit = await cache_get(key)
                    if hit is not None:
                        logger.debug("cache_hit", key=key)
                        return hit

                    # Miss -- call function and cache result
                    result = await func(*args, **kwargs)
                    await cache_set(key, result, ttl=ttl)
                    logger.debug("cache_miss", key=key, ttl=ttl)
                    return result

                return wrapper

            return decorator
    """)

    client_file.write_text(content)
    files_created.append(str(client_file))
    notes.append("Generated integrations/redis_cache.py with get/set/delete and @cached decorator.")

    # --- Requirements ---
    _ensure_requirement(root, "redis[hiredis]>=5.0.0", files_modified, notes)

    # --- Config fields ---
    _ensure_config_field(root, "REDIS_URL", 'str = "redis://localhost:6379/0"', files_modified, notes)


# ---------------------------------------------------------------------------
# Service dispatch table
# ---------------------------------------------------------------------------

_SERVICE_GENERATORS = {
    "stripe": _generate_stripe,
    "s3": _generate_s3,
    "sendgrid": _generate_sendgrid,
    "redis": _generate_redis,
}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _read_requirements(root: Path) -> tuple[Path | None, list[str]]:
    """Return (path, lines) for the first requirements*.txt found.

    Searches both downward (rglob) and upward (parent traversal) so it
    works whether `root` is the project root OR the app/ subdirectory.
    """
    # First try downward search (legacy flat layout)
    for candidate in sorted(root.rglob("requirements*.txt")):
        return candidate, candidate.read_text().splitlines()

    # Then walk up looking for project-root requirements.txt (modern layout)
    for parent in root.parents:
        for name in ("requirements.txt", "requirements-prod.txt", "requirements-dev.txt"):
            candidate = parent / name
            if candidate.exists():
                return candidate, candidate.read_text().splitlines()
        # Stop at filesystem root
        if parent == parent.parent:
            break

    return None, []


def _ensure_dep(lines: list[str], dep: str) -> list[str]:
    """Append *dep* if it is not already present (case-insensitive match)."""
    name = dep.split("[")[0].split("=")[0].split(">")[0].split("<")[0].strip().lower()
    for line in lines:
        if name in line.lower():
            return lines
    lines.append(dep)
    return lines


def _ensure_requirement(
    root: Path,
    dep: str,
    files_modified: list[str],
    notes: list[str],
) -> None:
    """Add a dependency to requirements.txt if not already present."""
    req_path, req_lines = _read_requirements(root)
    if req_path is not None:
        before = len(req_lines)
        req_lines[:] = _ensure_dep(req_lines, dep)
        if len(req_lines) > before:
            req_path.write_text("\n".join(req_lines) + "\n")
            files_modified.append(str(req_path))
            notes.append(f"Added {dep} to {req_path.name}.")
    else:
        notes.append(f"No requirements.txt found -- add {dep} manually.")


def _ensure_config_field(
    root: Path,
    field_name: str,
    field_def: str,
    files_modified: list[str],
    notes: list[str],
) -> None:
    """Add a field to ``core/config.py`` Settings class if not present."""
    config_path = root / "core" / "config.py"
    if not config_path.exists():
        notes.append(
            f"core/config.py not found -- add {field_name} to your settings manually."
        )
        return

    content = config_path.read_text()
    if field_name in content:
        return

    lines = content.split("\n")

    # Insert before the first @model_validator or at end of class body
    insert_idx = None
    for i, line in enumerate(lines):
        if "@model_validator" in line:
            insert_idx = i
            break

    if insert_idx is None:
        # Fallback: find end of Settings class body
        in_settings = False
        for i, line in enumerate(lines):
            if "class Settings" in line:
                in_settings = True
            if in_settings and line.strip() and not line.startswith((" ", "\t")) and i > 0:
                insert_idx = i
                break
        if insert_idx is None:
            insert_idx = len(lines)

    # Determine section label from field name
    section = field_name.split("_")[0]
    label_map = {
        "STRIPE": "Stripe",
        "AWS": "AWS / S3",
        "S3": "AWS / S3",
        "SENDGRID": "SendGrid",
        "REDIS": "Redis",
    }
    label = label_map.get(section, section)

    # Check if the section comment already exists
    section_comment = f"# --- {label} ---"
    if section_comment not in content:
        lines.insert(insert_idx, "")
        lines.insert(insert_idx + 1, f"    {section_comment}")
        lines.insert(insert_idx + 2, f"    {field_name}: {field_def}")
        offset = 3
    else:
        # Section exists -- insert field after the section comment
        for i, line in enumerate(lines):
            if section_comment in line:
                lines.insert(i + 1, f"    {field_name}: {field_def}")
                break
        offset = 1

    config_path.write_text("\n".join(lines))
    if str(config_path) not in files_modified:
        files_modified.append(str(config_path))
    notes.append(f"Added {field_name} to core/config.py Settings class.")
